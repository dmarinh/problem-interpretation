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
from dataclasses import dataclass

_log = logging.getLogger(__name__)

from app.core.state import SessionManager, SessionState, get_session_manager
from app.engines.combase.engine import ComBaseEngine, get_combase_engine
from app.models.enums import (
    ComBaseOrganism,
    Factor4Type,
    IntentType,
    ModelType,
    OrganismGroundingFailureStage,
    SessionStatus,
)
from app.models.extraction import ExtractedDuration
from app.models.metadata import (
    ClarificationQuestion,
    ClarificationRecord,
    ClarificationTranscript,
    ComBaseModelAudit,
    OrganismGroundingFailure,
    SystemAudit,
    ValueProvenance,
    ValueSource,
)
from app.services.audit.system import build_system_audit
from app.services.clarification.clarification_service import (
    ClarificationService,
    get_clarification_service,
)
from app.services.extraction.semantic_parser import SemanticParser, get_semantic_parser
from app.services.grounding.grounding_service import (
    GroundedValues,
    GroundingService,
    get_grounding_service,
)
from app.services.llm.exceptions import LLMProviderError
from app.services.standardization.standardization_service import (
    StandardizationResult,
    StandardizationService,
    get_standardization_service,
)

# The only two OrganismGroundingFailureStage members the organism
# clarification gate can resolve with a question — see
# Orchestrator._build_organism_clarification. Every other stage
# (BRIDGE_DISABLED, INTERNAL_NO_MAPPABLE_CANDIDATE) keeps the existing
# fail-closed path: no question would help.
_CLARIFIABLE_ORGANISM_STAGES = frozenset(
    {
        OrganismGroundingFailureStage.FOOD_UNRECOGNISED,
        OrganismGroundingFailureStage.CATEGORY_HAS_NO_HAZARD_DATA,
    }
)


@dataclass
class _TranscriptResolution:
    """Outcome of Orchestrator._resolve_organism_from_transcript.

    organism is None iff resolution failed closed; failure_reason is then a
    plain-language string (never a short code) suitable for state.set_error().
    Exactly one of the two is populated.
    """

    organism: ComBaseOrganism | None
    failure_reason: str | None


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
      "<field> (no declared valid range for ...)" → the grounded factor4 field
                             (e.g. "nitrite_ppm") when the model declares a
                             factor4 type but the registry has no bounds for
                             it — audit key is the field name itself.

    metadata.provenance uses full field names matching grounded.provenance keys:
      "duration_minutes", "duration_minutes (step N)", "temperature_celsius"
    """
    _NO_VALID_RANGE_MARKER = " (no declared valid range for "

    if field_spec == "duration":
        return "duration_minutes"
    if field_spec.startswith("duration (step "):
        return field_spec.replace("duration (step ", "duration_minutes (step ", 1)
    if field_spec == "temperature":
        return "temperature_celsius"
    if field_spec == "organism" or field_spec.startswith("organism ("):
        return "organism"
    if _NO_VALID_RANGE_MARKER in field_spec:
        return field_spec.split(_NO_VALID_RANGE_MARKER, 1)[0]
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
        clarification_service: ClarificationService | None = None,
    ):
        self._sessions = session_manager or get_session_manager()
        self._parser = semantic_parser or get_semantic_parser()
        self._grounder = grounding_service or get_grounding_service()
        self._standardizer = standardization_service or get_standardization_service()
        self._engine = combase_engine or get_combase_engine()
        self._clarifier = clarification_service or get_clarification_service()

    async def translate(
        self,
        user_input: str,
        model_type: ModelType | None = None,
        transcript: ClarificationTranscript | None = None,
    ) -> TranslationResult:
        """
        Run the full translation pipeline.

        Args:
            user_input: User's natural language input
            model_type: Type of model to run
            transcript: A1b re-entry (2026-07-17). When present, this request
                is answering a prior status=awaiting_clarification response.
                PTM is stateless (no server-side session — see
                specs/lessons.md), so transcript.original_query is what's
                actually reprocessed; user_input is ignored in that case.
                The pipeline runs from scratch exactly as round 1 did, and
                only when it reaches the same clarifiable organism gap does
                the transcript's reply get a chance to resolve it — see
                _handle_missing_required.

        Returns:
            TranslationResult with execution result and metadata
        """
        # Create session. When a transcript is present it is the source of
        # truth for what to (re)process — there is no session to resume, so
        # the original query is reprocessed from scratch each time.
        effective_input = (
            transcript.original_query if transcript is not None else user_input
        )
        state = self._sessions.create_session(effective_input)

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
                outcome = await self._handle_missing_required(
                    state, grounded, transcript, effective_model_type, std_result
                )
                if isinstance(outcome, TranslationResult):
                    return outcome
                # Transcript-driven organism resolution succeeded and
                # standardize() was re-run — continue the pipeline with the
                # new, now-complete result.
                std_result = outcome

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

    def _build_organism_clarification(
        self,
        grounded: "GroundedValues",
        food_description: str,
        model_type: ModelType,
        factor4_type: Factor4Type,
    ) -> ClarificationQuestion | None:
        """
        Build the organism clarification question, or None when no question
        should be asked — either the failure stage isn't one a question can
        resolve, or no viable option set could be derived. None means the
        caller falls back to today's unchanged failure path.

        Assembles the inputs ClarificationService needs (it does no I/O or
        registry access itself): the executable-organism option set is
        derived from the registry ∩ pathogen_characteristics.csv via
        GroundingService.rank_executable_organisms, using the actual
        factor4_type standardization computed for this request — not NONE.
        """
        failure = grounded.organism_failure
        if failure is None or failure.stage not in _CLARIFIABLE_ORGANISM_STAGES:
            return None

        executable = self._engine.registry.get_executable_organisms(
            model_type, factor4_type
        )
        ranked = self._grounder.rank_executable_organisms(executable)
        if not ranked:
            return None

        ranked_organisms = [
            (organism, self._standardizer.organism_display_name(organism))
            for organism in ranked[:5]
        ]

        return self._clarifier.build_organism_question(
            stage=failure.stage,
            food_description=food_description,
            ranked_organisms=ranked_organisms,
            resolved_category=failure.resolved_category,
        )

    def _record_missing_required(
        self, state: SessionState, std_result: StandardizationResult
    ) -> None:
        """Backfill null provenance + a warning for every missing_required field.

        Shared by the initial standardize() failure and, when transcript
        resolution is attempted but standardize() still fails afterward, the
        retry's failure too — so both paths produce the same field_audit
        shape rather than one being backfilled and the other not.
        """
        if not state.metadata:
            return
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

    async def _handle_missing_required(
        self,
        state: SessionState,
        grounded: "GroundedValues",
        transcript: ClarificationTranscript | None,
        model_type: ModelType,
        std_result: StandardizationResult,
    ) -> "TranslationResult | StandardizationResult":
        """
        Handle a standardize() result with missing_required populated.

        Returns a StandardizationResult when transcript-driven organism
        resolution (A1b) succeeded and standardize() was re-run — the caller
        (translate()) should continue the pipeline with it, exactly as if
        organism had been grounded from the start. Returns a terminal
        TranslationResult for every other outcome: a hard failure, or (round
        1, no transcript) a fresh clarification question was asked.

        Narrow trigger, same as A1a: only the bare "organism" spec (organism
        entirely ungrounded) with a clarifiable failure stage reaches either
        the ask path or the re-entry path below. "organism (...)" (grounded
        but not executable), missing factor4 bounds, missing duration, and
        every non-clarifiable organism-failure stage keep the unchanged
        fail-closed path regardless of whether a transcript is present.

        _record_missing_required(state, std_result) is deliberately NOT
        called unconditionally up front — only on branches that are actually
        terminal. Calling it eagerly would leave a stale "required value
        missing — organism" warning in metadata.warnings even after a
        transcript-driven resolution succeeds and the request completes
        (std_result's missing_required reflects the pre-resolution state; it
        must never be recorded once organism is later resolved). Each
        terminal branch below records the *result it is actually failing on*
        (std_result for round 1 / non-clarifiable, new_result for a retry
        that still fails) instead.
        """
        failure: OrganismGroundingFailure | None = (
            grounded.organism_failure
            if "organism" in std_result.missing_required
            else None
        )
        clarifiable = (
            failure is not None and failure.stage in _CLARIFIABLE_ORGANISM_STAGES
        )

        if clarifiable and transcript is not None:
            assert failure is not None  # narrowed by `clarifiable`
            resolution = await self._resolve_organism_from_transcript(
                transcript, model_type, std_result.factor4_type
            )
            if state.metadata:
                state.metadata.add_clarification(
                    ClarificationRecord(
                        turn_number=1,
                        reason=self._clarifier.reason_for_stage(failure.stage),
                        question_asked=transcript.question_asked,
                        user_response=transcript.user_reply,
                        extracted_value=(
                            resolution.organism.value
                            if resolution.organism is not None
                            else None
                        ),
                    )
                )

            if resolution.organism is None:
                self._record_missing_required(state, std_result)
                assert resolution.failure_reason is not None
                state.set_error(resolution.failure_reason)
                return TranslationResult(state)

            # Ground the resolved organism and re-run standardization — the
            # same path as if organism had been grounded from the start.
            grounded.set(
                "organism",
                resolution.organism,
                source=ValueSource.CLARIFICATION_RESPONSE,
                original_text=transcript.user_reply,
                extraction_method="clarification_response",
            )
            if state.metadata:
                state.metadata.add_provenance(
                    "organism", grounded.provenance["organism"]
                )

            new_result = self._standardizer.standardize(grounded, model_type)
            if state.metadata:
                state.metadata.defaults_imputed.extend(new_result.defaults_imputed)
                for clamp in new_result.range_clamps:
                    state.metadata.add_range_clamp(clamp)
                state.metadata.warnings.extend(new_result.warnings)

            if new_result.missing_required:
                # One round only — grounding still fails after the reply was
                # applied (e.g. some other field is now the blocker), so this
                # is a hard failure, never a second question.
                self._record_missing_required(state, new_result)
                state.set_error(
                    f"Missing required values: {', '.join(new_result.missing_required)}"
                )
                return TranslationResult(state)

            return new_result

        if clarifiable:
            # Round 1: ask, unless transcript is absent (checked above) — i.e.
            # this branch is reached only when transcript is None. Terminal
            # either way (asks or falls through to the hard failure below),
            # so record now.
            self._record_missing_required(state, std_result)
            clarification = self._build_organism_clarification(
                grounded,
                (
                    state.extracted_scenario.food_description
                    if state.extracted_scenario
                    else None
                )
                or "",
                model_type,
                std_result.factor4_type,
            )
            if clarification is not None:
                state.clarification_question = clarification
                state.update_status(SessionStatus.AWAITING_CLARIFICATION)
                if state.metadata:
                    state.metadata.add_clarification(
                        ClarificationRecord(
                            turn_number=1,
                            reason=clarification.reason,
                            question_asked=clarification.question,
                            user_response=None,
                        )
                    )
                return TranslationResult(state)
            # clarification is None (no viable option set) — falls through
            # to the hard failure below. Already recorded above (this whole
            # `if clarifiable:` branch is terminal either way), so the
            # non-clarifiable branch's record call below must not double it.

        if not clarifiable:
            self._record_missing_required(state, std_result)

        state.set_error(
            f"Missing required values: {', '.join(std_result.missing_required)}"
        )
        return TranslationResult(state)

    async def _resolve_organism_from_transcript(
        self,
        transcript: ClarificationTranscript,
        model_type: ModelType,
        factor4_type: Factor4Type,
    ) -> _TranscriptResolution:
        """
        Attempt to resolve an organism from the user's reply to a round-1
        clarification question, carried on the request (ClarificationTranscript
        — see its docstring for why PTM does this instead of a server-side
        session).

        Fails closed (organism=None with a plain-language failure_reason)
        rather than guessing, on any of:
          - wants_to_skip=True: no organism default exists, so skipping is a
            refusal, not a fallback.
          - The reply names zero organisms (free-text escape, unrecognised
            name, or nothing identifiable at all).
          - The reply names more than one distinct organism — ambiguous, not
            resolved to an arbitrary one of them.
          - The resolved organism is not among transcript.options_offered — a
            near-miss is not a match, and this is never silently substituted.
          - The resolved organism is not executable for (model_type,
            factor4_type) when re-checked now — the option set was derived at
            some point in the past; the reply is new input, so this is
            checked, not trusted.

        Both selected_option and understood_value are scanned together for
        organism aliases (ComBaseOrganism.all_matches_in_text). Neither field
        is guaranteed by CLARIFICATION_RESPONSE_PROMPT to be an index or an
        exact copy of an offered option string — it is free text — so
        exact-string matching (e.g. from_string()) would reject perfectly
        good answers wrapped in a sentence. If the two fields name different
        organisms, that surfaces as an ambiguous multi-match rather than an
        unresolvable disagreement between fields, since there is no way to
        know which field is authoritative — this is the correct fail-closed
        outcome, not a special case.
        """
        extracted = await self._parser.extract_clarification_response(
            user_response=transcript.user_reply,
            original_question=transcript.question_asked,
            options=[opt.label for opt in transcript.options_offered],
        )

        if extracted.wants_to_skip:
            return _TranscriptResolution(
                organism=None,
                failure_reason=(
                    "You indicated you'd like to skip naming a pathogen, but "
                    "no organism default exists — a pathogen is required to "
                    "run a prediction, so this can't proceed without one."
                ),
            )

        search_text = " ".join(
            part
            for part in (extracted.selected_option, extracted.understood_value)
            if part
        )
        matches = ComBaseOrganism.all_matches_in_text(search_text)

        if not matches:
            return _TranscriptResolution(
                organism=None,
                failure_reason=(
                    f"Your reply ({transcript.user_reply!r}) didn't name a "
                    "pathogen I could identify, so this can't proceed."
                ),
            )

        if len(matches) > 1:
            names = ", ".join(
                sorted(self._standardizer.organism_display_name(o) for o in matches)
            )
            return _TranscriptResolution(
                organism=None,
                failure_reason=(
                    f"Your reply named more than one pathogen ({names}) — "
                    "please name exactly one."
                ),
            )

        candidate = next(iter(matches))
        offered_codes = {opt.code for opt in transcript.options_offered}
        if candidate.value not in offered_codes:
            return _TranscriptResolution(
                organism=None,
                failure_reason=(
                    f"{self._standardizer.organism_display_name(candidate)} "
                    "wasn't one of the options offered, so it can't be used."
                ),
            )

        if not self._engine.registry.is_executable(candidate, model_type, factor4_type):
            name = self._standardizer.organism_display_name(candidate)
            return _TranscriptResolution(
                organism=None,
                failure_reason=(
                    f"{name} is not supported for "
                    f"{model_type.value.replace('_', ' ')} predictions, so "
                    "this can't proceed."
                ),
            )

        return _TranscriptResolution(organism=candidate, failure_reason=None)

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
