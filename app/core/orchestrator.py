"""
Workflow Orchestrator

Coordinates the full translation pipeline:
1. Intent classification
2. Semantic extraction
3. RAG grounding
4. Standardization
5. Engine execution
"""

import logging
import re

_log = logging.getLogger(__name__)

from app.core.state import SessionManager, SessionState, get_session_manager
from app.engines.combase.engine import ComBaseEngine, get_combase_engine
from app.models.enums import IntentType, ModelType, SessionStatus
from app.models.extraction import ExtractedDuration
from app.models.metadata import (
    ComBaseModelAudit,
    SystemAudit,
    ValueProvenance,
    ValueSource,
)
from app.services.audit.system import build_system_audit
from app.services.extraction.semantic_parser import SemanticParser, get_semantic_parser
from app.services.grounding.grounding_service import (
    GroundedValues,
    GroundingService,
    get_grounding_service,
)
from app.services.llm.exceptions import LLMProviderError
from app.services.standardization.standardization_service import (
    StandardizationService,
    get_standardization_service,
)


def _missing_key_to_audit_key(field_spec: str) -> str:
    """
    Map StandardizationService's missing_required field spec to the audit key
    used in metadata.provenance.

    StandardizationService uses short specs:
      "duration"          → single-step duration
      "duration (step N)" → multi-step step N duration
      "temperature"       → single-step temperature (rare — gets a default before missing)
      "organism"          → organism ungrounded (same in both namespaces)
      "organism (...)"    → organism grounded but not executable for this model_type/
                             factor4_type (e.g. "organism (Shigella flexneri is not
                             supported for growth predictions)") — same audit key as
                             plain "organism"; the parenthetical is human-readable
                             detail for the top-level error string, not part of the key.

    metadata.provenance uses full field names matching grounded.provenance keys:
      "duration_minutes", "duration_minutes (step N)", "temperature_celsius"
    """
    if field_spec == "duration":
        return "duration_minutes"
    if field_spec.startswith("duration (step "):
        return field_spec.replace("duration (step ", "duration_minutes (step ", 1)
    if field_spec == "temperature":
        return "temperature_celsius"
    if field_spec == "organism" or field_spec.startswith("organism ("):
        return "organism"
    _log.warning(
        "_missing_key_to_audit_key: unrecognised field spec %r — passing through; audit key may be wrong",
        field_spec,
    )
    return field_spec


class TranslationResult:
    """Result of the translation pipeline."""

    def __init__(self, state: SessionState):
        self.state = state
        self.success = state.status == SessionStatus.COMPLETED
        self.error = state.error

    @property
    def execution_result(self):
        return self.state.execution_result

    @property
    def metadata(self):
        return self.state.metadata


class Orchestrator:
    """
    Orchestrates the full translation pipeline.

    Usage:
        orchestrator = Orchestrator()
        result = await orchestrator.translate("Raw chicken left out for 3 hours at 25C")
    """

    def __init__(
        self,
        session_manager: SessionManager | None = None,
        semantic_parser: SemanticParser | None = None,
        grounding_service: GroundingService | None = None,
        standardization_service: StandardizationService | None = None,
        combase_engine: ComBaseEngine | None = None,
    ):
        self._sessions = session_manager or get_session_manager()
        self._parser = semantic_parser or get_semantic_parser()
        self._grounder = grounding_service or get_grounding_service()
        self._standardizer = standardization_service or get_standardization_service()
        self._engine = combase_engine or get_combase_engine()

    async def translate(
        self,
        user_input: str,
        model_type: ModelType | None = None,
    ) -> TranslationResult:
        """
        Run the full translation pipeline.

        Args:
            user_input: User's natural language input
            model_type: Type of model to run

        Returns:
            TranslationResult with execution result and metadata
        """
        # Create session
        state = self._sessions.create_session(user_input)

        try:
            # Step 1: Classify intent
            state.update_status(SessionStatus.EXTRACTING)
            await self._classify_intent(state)

            if state.intent_type == IntentType.OUT_OF_SCOPE:
                state.set_error("Query is out of scope for food safety predictions")
                return TranslationResult(state)

            if state.intent_type == IntentType.INFORMATION_QUERY:
                state.set_error("Information queries not yet implemented")
                return TranslationResult(state)

            # Step 2: Extract scenario
            await self._extract_scenario(state)

            # Backstop: warn when the LLM captured a numeric duration phrase in
            # description but left value_minutes null.  Does not patch values —
            # the existing rule-library / conservative-default path handles it.
            # Fires only on whitespace-separated forms ("35 days"), not hyphenated
            # adjectives ("35-day shelf life") — the prompt's worked examples cover
            # those; failures there show up cleanly as Set C misses, not backstop catches.
            self._check_duration_backstop(state)

            # Step 3: Determine model type. Model type should have been extracted in step 2 by the LLM.
            # However, we determine it here with rules as a fallback, and we make sure that model type is
            # in any case set to the explicit model type if that was provided (overriding the LLM's decision).
            effective_model_type, model_type_reason = self._determine_model_type(
                model_type,
                state.extracted_scenario,
            )

            # Step 4: Ground values via RAG
            grounded = await self._ground_values(state)

            # Step 5: Standardize and build payload
            state.update_status(SessionStatus.STANDARDIZING)
            std_result = self._standardizer.standardize(grounded, effective_model_type)

            # Always record partial standardization events — even on validation failure,
            # so field_audit captures every field the orchestrator attempted to resolve.
            if state.metadata:
                state.metadata.defaults_imputed.extend(std_result.defaults_imputed)
                for clamp in std_result.range_clamps:
                    state.metadata.add_range_clamp(clamp)
                state.metadata.warnings.extend(std_result.warnings)

            if std_result.missing_required:
                if state.metadata:
                    for field in std_result.missing_required:
                        # Add a null-provenance entry so field_audit shows this field
                        # with final_value=null instead of omitting it entirely.
                        audit_key = _missing_key_to_audit_key(field)
                        if audit_key not in state.metadata.provenance:
                            state.metadata.add_provenance(
                                audit_key,
                                ValueProvenance(source=ValueSource.MISSING),
                            )
                        state.metadata.warnings.append(
                            f"Validation failed: required value missing — {field}"
                        )
                state.set_error(
                    f"Missing required values: {', '.join(std_result.missing_required)}"
                )
                return TranslationResult(state)

            if std_result.payload is None:
                error_detail = (
                    "; ".join(std_result.warnings)
                    if std_result.warnings
                    else "Failed to build execution payload"
                )
                state.set_error(error_detail)
                return TranslationResult(state)

            state.execution_payload = std_result.payload

            # Step 6: Execute model
            state.update_status(SessionStatus.EXECUTING)
            await self._execute_model(state)

            # Record ComBase model selection audit after execution (organism known now)
            if state.metadata and state.execution_payload:
                self._record_combase_model_audit(
                    state, effective_model_type, model_type_reason
                )

            # Complete
            state.update_status(SessionStatus.COMPLETED)
            if state.metadata:
                sys_audit_data = build_system_audit()
                manifest_missing = sys_audit_data.pop("manifest_missing", False)
                state.metadata.system = SystemAudit(**sys_audit_data)
                if manifest_missing:
                    state.metadata.warnings.append(
                        "RAG manifest missing — store provenance unknown"
                    )

            return TranslationResult(state)

        except LLMProviderError:
            raise
        except Exception as e:
            state.set_error(str(e))
            return TranslationResult(state)

    def _determine_model_type(
        self,
        explicit_type: ModelType | None,
        scenario,
    ) -> tuple[ModelType, str]:
        """
        Determine model type from explicit parameter or scenario inference.

        Returns (model_type, selection_reason) so the orchestrator can record
        the rationale in InterpretationMetadata for audit traceability.

        Priority:
        1. Explicit parameter (if provided)
        2. LLM-extracted inference (implied_model_type)
        3. Temperature heuristic (>50°C → thermal inactivation)
        4. Scenario flag: is_cooking_scenario
        5. Scenario flag: is_non_thermal_treatment
        6. Environmental condition: pH < 4.5
        7. Environmental condition: aw < 0.90
        8. Default to Growth

        There is deliberately no "preservative present → NON_THERMAL_SURVIVAL" branch.
        ComBase has zero Factor4 rows for ModelID 2 (thermal_inactivation) or ModelID 3
        (non_thermal_survival) — every organism is non-executable at NON_THERMAL_SURVIVAL
        with any preservative factor4, so that branch could only ever route to a
        guaranteed StandardizationService refusal (removed 2026-07-16; see
        specs/lessons.md). A preservative alone is evidence the food was cured, not
        evidence the user is asking about survival rather than growth — nitrite/lactic/
        acetic presence still reaches StandardizationService via _get_factor4()
        regardless of model_type; it is not discarded.

        Model types:
        - GROWTH: Bacterial multiplication during storage/holding
        - THERMAL_INACTIVATION: Pathogen death from heat treatment
        - NON_THERMAL_SURVIVAL: Pathogen survival under non-thermal stress
        """
        if explicit_type is not None:
            return explicit_type, "explicit model_type parameter override"

        if scenario.implied_model_type is not None:
            return (
                scenario.implied_model_type,
                "LLM inference (implied_model_type field)",
            )

        temp = scenario.single_step_temperature
        if temp.value_celsius is not None and temp.value_celsius > 50:
            return (
                ModelType.THERMAL_INACTIVATION,
                f"temperature heuristic ({temp.value_celsius}°C > 50°C → thermal inactivation)",
            )

        if scenario.is_cooking_scenario:
            return ModelType.THERMAL_INACTIVATION, "scenario flag: is_cooking_scenario"

        if scenario.is_non_thermal_treatment:
            return (
                ModelType.NON_THERMAL_SURVIVAL,
                "scenario flag: is_non_thermal_treatment",
            )

        env = scenario.environmental_conditions
        if env.ph_value is not None and env.ph_value < 4.5:
            return (
                ModelType.NON_THERMAL_SURVIVAL,
                f"environmental condition: pH {env.ph_value} < 4.5",
            )
        if env.water_activity is not None and env.water_activity < 0.90:
            return (
                ModelType.NON_THERMAL_SURVIVAL,
                f"environmental condition: aw {env.water_activity} < 0.90",
            )

        return ModelType.GROWTH, "default (no thermal/non-thermal signals detected)"

    def _record_combase_model_audit(
        self,
        state: "SessionState",
        model_type: ModelType,
        selection_reason: str,
    ) -> None:
        """
        Populate InterpretationMetadata.combase_model after engine execution.

        The organism is read from the execution payload (already resolved by
        grounding + standardization).  Model coefficients and valid ranges are
        fetched from the registry — the same lookup the engine used, so there
        is no risk of mismatch.
        """
        if not state.metadata or not state.execution_payload:
            return

        sel = state.execution_payload.model_selection
        model = self._engine.registry.get_model(
            organism=sel.organism,
            model_type=sel.model_type,
            factor4_type=sel.factor4_type,
        )

        coefficients_str: str | None = None
        valid_ranges: dict | None = None
        model_id: int | None = None

        if model:
            model_id = model.model_id
            coefficients_str = ";".join(f"{c:.6g}" for c in model.coefficients)
            c = model.constraints
            valid_ranges = {
                "temperature_celsius": (c.temp_min, c.temp_max),
                "ph": (c.ph_min, c.ph_max),
                "water_activity": (c.aw_min, c.aw_max),
            }

        state.metadata.combase_model = ComBaseModelAudit(
            organism=sel.organism.name,
            organism_id=sel.organism.value,
            organism_display_name=(
                model.organism_name
                if model and isinstance(model.organism_name, str)
                else None
            ),
            model_type=model_type.value,
            model_id=model_id,
            coefficients_str=coefficients_str,
            valid_ranges=valid_ranges,
            selection_reason=selection_reason,
            y_max=model.y_max if model else None,
            h0=model.h0 if model else None,
        )

    async def _classify_intent(self, state: SessionState) -> None:
        """Classify user intent."""
        state.intent = await self._parser.classify_intent(state.user_input)

        if state.intent.is_prediction_request:
            state.intent_type = IntentType.PREDICTION_REQUEST
        elif state.intent.is_information_query:
            state.intent_type = IntentType.INFORMATION_QUERY
        elif state.intent.requires_clarification:
            state.intent_type = IntentType.PREDICTION_REQUEST
        else:
            state.intent_type = IntentType.OUT_OF_SCOPE

    async def _extract_scenario(self, state: SessionState) -> None:
        """Extract scenario from user input."""
        state.extracted_scenario = await self._parser.extract_scenario(state.user_input)

    # Matches whitespace-separated "N unit" forms (e.g. "35 days", "840 hours").
    # Deliberately excludes hyphenated adjective forms ("35-day") — those are covered
    # by the prompt's worked examples; failures there surface cleanly in live Test C
    # results rather than being masked by the backstop.
    _NUMERIC_DURATION_RE = re.compile(
        r"\b\d+(?:\.\d+)?\s+(?:second|sec|minute|min|hour|hr|h|day|d|week|wk|w)s?\b",
        re.IGNORECASE,
    )

    def _check_duration_backstop(self, state: "SessionState") -> None:
        """
        Warn when the LLM captured a numeric duration phrase in description but
        did not populate value_minutes.  Detection only — no value patching.
        """
        if not state.metadata or not state.extracted_scenario:
            return

        def _check(dur: ExtractedDuration, label: str) -> None:
            if dur.value_minutes is None and dur.description:
                if self._NUMERIC_DURATION_RE.search(dur.description):
                    state.metadata.warnings.append(
                        f"Duration phrase detected in description but value_minutes not extracted"
                        f" ({label}): '{dur.description}'. Falling back to rule-library path."
                    )

        scenario = state.extracted_scenario
        _check(scenario.single_step_duration, "single-step")
        for i, step in enumerate(scenario.time_temperature_steps):
            _check(step.duration, f"step {i + 1}")

    async def _ground_values(self, state: SessionState) -> "GroundedValues":
        """Ground extracted values via RAG."""
        grounded = await self._grounder.ground_scenario(state.extracted_scenario)

        # Store grounded values and provenance
        state.grounded_values = grounded.values

        if state.metadata:
            for field, prov in grounded.provenance.items():
                state.metadata.add_provenance(field, prov)
            for retrieval in grounded.retrievals:
                state.metadata.add_retrieval(retrieval)
            # Composite-food skip events: field → matched keyword.
            # Copied here so the route builder can assign COMPOSITE_FOOD_DEFAULT
            # source without needing direct access to the GroundedValues object.
            if grounded.composite_skip:
                state.metadata.composite_skip.update(grounded.composite_skip)
            # Bridge per-step provenances so field_audit reflects multi-step structure.
            # grounded.provenance holds flat fields (organism/ph/aw); per-step temps
            # and durations live in grounded.steps and would otherwise be invisible
            # to _build_field_audit in translation.py.
            # Also populate grounded_values with step-qualified keys so the
            # final_value lookup in _build_field_audit (which reads grounded_values)
            # resolves to the actual value rather than None.
            for step in grounded.steps:
                temp_key = f"temperature_celsius (step {step.step_order})"
                dur_key = f"duration_minutes (step {step.step_order})"
                if step.temp_provenance is not None:
                    state.metadata.add_provenance(temp_key, step.temp_provenance)
                if step.dur_provenance is not None:
                    state.metadata.add_provenance(dur_key, step.dur_provenance)
                if step.temperature_celsius is not None:
                    state.grounded_values[temp_key] = step.temperature_celsius
                if step.duration_minutes is not None:
                    state.grounded_values[dur_key] = step.duration_minutes
            if grounded.warnings:
                state.metadata.warnings.extend(grounded.warnings)

        return grounded

    async def _execute_model(self, state: SessionState) -> None:
        """Execute the ComBase model."""
        if not self._engine.is_available:
            raise RuntimeError("ComBase engine not available")

        state.execution_result = await self._engine.execute(state.execution_payload)

        # Add execution warnings to metadata
        if state.metadata and state.execution_result:
            state.metadata.warnings.extend(state.execution_result.warnings)


# =============================================================================
# SINGLETON
# =============================================================================

_orchestrator: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    """Get or create the global Orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator


def reset_orchestrator() -> None:
    """Reset the global orchestrator (for testing)."""
    global _orchestrator
    _orchestrator = None
