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
from typing import cast

from annotated_types import Le

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
    DurationClarificationReply,
    DurationClarificationStep,
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
    GroundedStep,
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

# _determine_model_type()'s final fall-through reason (A1c). Unlike every
# other default in this system, GROWTH-by-fall-through has no conservative
# direction to fall back on — growth vs. inactivation is a binary choice
# about what kind of scenario this is, not a worst-case numeric floor/ceiling.
# Getting it wrong is categorically wrong, not cautious. This exact string is
# shared between the return statement and the fall-through check below it so
# the two can never drift apart.
_MODEL_TYPE_FALLTHROUGH_REASON = "default (no thermal/non-thermal signals detected)"

# The multi-step duration clarification gate's plausibility ceiling, in
# minutes — derived (not duplicated) from ExtractedDuration.value_minutes's
# own Field(le=...) so the two can never silently drift apart the way a
# hand-copied literal could. A duration reply is USER_EXPLICIT at the same
# trust level as any value in the original query (see specs/lessons.md), so
# it gets the exact same ceiling the original extraction enforces — not a
# looser or stricter one.
_le_bound = next(
    m.le
    for m in ExtractedDuration.model_fields["value_minutes"].metadata
    if isinstance(m, Le)
)
_MAX_DURATION_MINUTES: float = float(cast(int, _le_bound))


@dataclass
class _TranscriptResolution:
    """Outcome of Orchestrator._resolve_organism_from_transcript.

    organism is None iff resolution failed closed; failure_reason is then a
    plain-language string (never a short code) suitable for state.set_error().
    Exactly one of the two is populated.
    """

    organism: ComBaseOrganism | None
    failure_reason: str | None


@dataclass
class _DurationReplyResolution:
    """Outcome of Orchestrator._resolve_duration_reply.

    values is a step_order -> minutes mapping iff every answered step
    resolved (structural + range check only — no LLM anywhere in this path);
    failure_reason is a plain-language string otherwise. Exactly one of the
    two is populated. All-or-nothing: values is never partially populated —
    either every step in the reply passed, or none of them are applied.
    """

    values: dict[int, float] | None
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
        duration_reply: DurationClarificationReply | None = None,
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
            duration_reply: multi-step duration gate re-entry (2026-08-17).
                Same statelessness rationale as transcript, but a distinct
                field: a numeric {step_order, hours} reply is never free text
                and never touched by an LLM, so it doesn't share
                ClarificationTranscript's shape. Mutually exclusive with
                transcript in practice — organism-missing and
                duration-missing can never co-occur in the same
                missing_required list (see _handle_missing_required) — but
                both are accepted as parameters unconditionally; which one
                (if either) actually applies is decided entirely by which
                gate the request lands on this round, not by which field the
                caller populated.

        Returns:
            TranslationResult with execution result and metadata
        """
        # Create session. When a transcript or duration_reply is present it is
        # the source of truth for what to (re)process — there is no session to
        # resume, so the original query is reprocessed from scratch each time.
        if transcript is not None:
            effective_input = transcript.original_query
        elif duration_reply is not None:
            effective_input = duration_reply.original_query
        else:
            effective_input = user_input
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

            # A1c: the fall-through has no conservative direction to lean on
            # (unlike temperature/pH/aw defaults), so it must be disclosed as
            # a guess, not a decision. Fires only on the true fall-through —
            # never on explicit/LLM-inferred/heuristic/flag-derived model
            # types, all of which return a different selection_reason string.
            # Matches how LONG_WINDOW_DEFAULT discloses via metadata.warnings
            # (standardization_service.py) so this reaches the plain response
            # through the same existing, unconditional channel.
            if model_type_reason == _MODEL_TYPE_FALLTHROUGH_REASON and state.metadata:
                state.metadata.warnings.append(
                    "No thermal or non-thermal signal was found in this scenario "
                    "— growth was assumed by default. This is a guess, not a "
                    "decision: confirm this is a storage/holding scenario, not "
                    "a cooking or non-thermal preservation scenario, before "
                    "relying on this prediction."
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
                    state,
                    grounded,
                    transcript,
                    duration_reply,
                    effective_model_type,
                    std_result,
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

        return ModelType.GROWTH, _MODEL_TYPE_FALLTHROUGH_REASON

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
    ) -> ClarificationQuestion | None:
        """
        Build the organism clarification question, or None when the failure
        stage isn't one a question can resolve — None means the caller falls
        back to the unchanged failure path.

        Free-text only (2026-08-19, see specs/lessons.md): no options menu,
        so no registry/executable-organism lookup is needed here — the
        question just names a few example pathogens in prose
        (ClarificationService.build_organism_question). The reply is
        resolved deterministically on re-entry
        (_resolve_organism_from_transcript), not validated against anything
        derived at ask-time.
        """
        failure = grounded.organism_failure
        if failure is None or failure.stage not in _CLARIFIABLE_ORGANISM_STAGES:
            return None

        return self._clarifier.build_organism_question(
            stage=failure.stage,
            food_description=food_description,
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
        duration_reply: DurationClarificationReply | None,
        model_type: ModelType,
        std_result: StandardizationResult,
    ) -> "TranslationResult | StandardizationResult":
        """
        Handle a standardize() result with missing_required populated.

        Returns a StandardizationResult when transcript-driven organism
        resolution (A1b) or a duration_reply-driven duration resolution
        succeeded and standardize() was re-run — the caller (translate())
        should continue the pipeline with it, exactly as if the value had
        been grounded from the start. Returns a terminal TranslationResult
        for every other outcome: a hard failure, or (round 1, no reply yet)
        a fresh clarification question was asked.

        Two independent gates, mutually exclusive by construction (see
        StandardizationService.standardize(): the organism check returns
        immediately on failure, strictly before _build_multi_step_profile()
        is ever called, so std_result.missing_required can never mix
        organism and duration entries):
          - organism: narrow trigger, unchanged since A1a — only the bare
            "organism" spec (organism entirely ungrounded) with a clarifiable
            failure stage reaches either the ask path or the re-entry path
            below. "organism (...)" (grounded but not executable) and every
            non-clarifiable organism-failure stage keep the unchanged
            fail-closed path regardless of whether a transcript is present.
          - duration (2026-08-17): fires when every entry in missing_required
            is a "duration (step N)" spec (multi-step step durations that
            never resolved — 2a runs the profile-builder loop to completion
            first, so this set is complete, not just the first miss). Missing
            factor4 bounds and any other non-duration missing_required reason
            keep the fail-closed path.

        _record_missing_required(state, std_result) is deliberately NOT
        called unconditionally up front — only on branches that are actually
        terminal. Calling it eagerly would leave a stale "required value
        missing — organism" warning in metadata.warnings even after a
        transcript-driven resolution succeeds and the request completes
        (std_result's missing_required reflects the pre-resolution state; it
        must never be recorded once organism is later resolved). Each
        terminal branch below records the *result it is actually failing on*
        (std_result for round 1 / non-clarifiable, new_result for a retry
        that still fails) instead. The duration gate mirrors this discipline.
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
            resolution = self._resolve_organism_from_transcript(
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
            # clarification is None only if grounded.organism_failure.stage
            # is no longer clarifiable by the time _build_organism_clarification
            # re-reads it — unreachable in the normal flow, since `clarifiable`
            # above was computed from that same (unmutated) field one line
            # earlier, but not assumed impossible: defense in depth, the same
            # discipline the executability re-check on re-entry uses. Falls
            # through to the hard failure below. Already recorded above (this
            # whole `if clarifiable:` branch is terminal either way), so the
            # non-clarifiable branch's record call below must not double it.

        # Duration gate (2026-08-17). Fires only when every missing_required
        # entry is a "duration (step N)" spec — mutually exclusive with the
        # organism gate above by construction (see docstring).
        duration_missing_specs = [
            f for f in std_result.missing_required if f.startswith("duration (step ")
        ]
        duration_clarifiable = len(duration_missing_specs) > 0 and len(
            duration_missing_specs
        ) == len(std_result.missing_required)

        if duration_clarifiable:
            # Re-derive the missing-step list from grounded.steps (structured,
            # not parsed from the missing_required strings) — the same
            # underlying condition std_result.missing_required's duration
            # entries were built from (GroundedStep.duration_minutes is None),
            # so this can never disagree with duration_missing_specs above.
            missing_steps = sorted(
                (gs for gs in grounded.steps if gs.duration_minutes is None),
                key=lambda gs: gs.step_order,
            )
            question = self._clarifier.build_duration_question(
                [
                    DurationClarificationStep(
                        step_order=gs.step_order, duration_phrase=gs.duration_phrase
                    )
                    for gs in missing_steps
                ]
            )

            if duration_reply is not None:
                duration_resolution = self._resolve_duration_reply(
                    duration_reply, missing_steps
                )
                if state.metadata:
                    state.metadata.add_clarification(
                        ClarificationRecord(
                            turn_number=1,
                            reason=question.reason,
                            question_asked=question.question,
                            user_response="; ".join(
                                f"step {s.step_order}: {s.hours}h"
                                for s in duration_reply.steps
                            ),
                            extracted_value=(
                                "; ".join(
                                    f"step {order}: {minutes}min"
                                    for order, minutes in sorted(
                                        duration_resolution.values.items()
                                    )
                                )
                                if duration_resolution.values is not None
                                else None
                            ),
                        )
                    )

                if duration_resolution.values is None:
                    self._record_missing_required(state, std_result)
                    assert duration_resolution.failure_reason is not None
                    state.set_error(duration_resolution.failure_reason)
                    return TranslationResult(state)

                # Apply the reply — mirrors organism's grounded.set() +
                # add_provenance() re-entry pattern. Both grounded.steps (read
                # by _build_multi_step_profile on the re-run below) and the
                # step-qualified metadata.provenance/grounded_values entries
                # (bridged once at grounding time in _ground_values, now
                # stale MISSING placeholders from _record_missing_required
                # calls in earlier rounds) must be updated together, or the
                # audit would show the new value in one place and the old
                # MISSING placeholder in the other.
                for step_reply in duration_reply.steps:
                    minutes = duration_resolution.values[step_reply.step_order]
                    gs = next(
                        g
                        for g in grounded.steps
                        if g.step_order == step_reply.step_order
                    )
                    gs.duration_minutes = minutes
                    gs.dur_provenance = ValueProvenance(
                        source=ValueSource.CLARIFICATION_RESPONSE,
                        original_text=str(step_reply.hours),
                        extraction_method="clarification_direct_entry",
                    )
                    if state.metadata:
                        dur_key = f"duration_minutes (step {gs.step_order})"
                        state.metadata.add_provenance(dur_key, gs.dur_provenance)
                        state.grounded_values[dur_key] = minutes

                new_result = self._standardizer.standardize(grounded, model_type)
                if state.metadata:
                    # Deduped, unlike the organism re-entry's plain extend
                    # (orchestrator.py ~line 674): organism's first
                    # standardize() call always returns before ph/aw/
                    # inoculum/factor4 are ever processed (it fails at the
                    # organism check, which runs first), so its
                    # defaults_imputed/range_clamps/warnings are always empty
                    # going into re-entry -- nothing to duplicate. Duration's
                    # first call runs past all of those (organism/factor4
                    # already resolved; only the multi-step profile fails),
                    # so this second standardize() call re-defaults/re-clamps
                    # every field that already succeeded the first time, and
                    # a plain extend would double-count them in the audit.
                    for d in new_result.defaults_imputed:
                        if d not in state.metadata.defaults_imputed:
                            state.metadata.defaults_imputed.append(d)
                    for clamp in new_result.range_clamps:
                        if clamp not in state.metadata.range_clamps:
                            state.metadata.add_range_clamp(clamp)
                    for w in new_result.warnings:
                        if w not in state.metadata.warnings:
                            state.metadata.warnings.append(w)

                if new_result.missing_required:
                    # One round only — same discipline as organism re-entry.
                    self._record_missing_required(state, new_result)
                    state.set_error(
                        f"Missing required values: {', '.join(new_result.missing_required)}"
                    )
                    return TranslationResult(state)

                return new_result

            # Round 1: ask. Terminal either way, so record now (mirrors
            # organism above).
            self._record_missing_required(state, std_result)
            state.duration_clarification_question = question
            state.update_status(SessionStatus.AWAITING_CLARIFICATION)
            if state.metadata:
                state.metadata.add_clarification(
                    ClarificationRecord(
                        turn_number=1,
                        reason=question.reason,
                        question_asked=question.question,
                        user_response=None,
                    )
                )
            return TranslationResult(state)

        if not clarifiable and not duration_clarifiable:
            self._record_missing_required(state, std_result)

        state.set_error(
            f"Missing required values: {', '.join(std_result.missing_required)}"
        )
        return TranslationResult(state)

    @staticmethod
    def _resolve_duration_reply(
        duration_reply: DurationClarificationReply,
        missing_steps: list[GroundedStep],
    ) -> _DurationReplyResolution:
        """
        Validate a structured numeric duration reply against the currently
        missing steps. No LLM call anywhere in this method — the reply is
        already numeric (DurationStepReply.hours: float, Pydantic gt=0), so
        this is pure structural + range validation, not extraction. Marked
        @staticmethod because it touches no instance state at all — no
        self._parser, no self._engine — which is itself a small, checkable
        proof that this path really has no service dependency to distrust.

        Contrast with _resolve_organism_from_transcript: organism's safety
        lives in a closed-set membership check because its input is
        LLM-extracted free text; duration's safety lives in this range check
        because its input is a plain number the user typed directly — there
        is no extraction step to distrust. See specs/lessons.md for the full
        reasoning.

        All-or-nothing (Part 1 Q2 of the design recon): the reply's
        step_order set must exactly equal the currently-missing step_order
        set — re-derived fresh from grounded.steps this round, not trusted
        from whatever was asked in round 1, since a step that resolved
        differently on retry shouldn't need re-answering. Any mismatch
        (fewer steps answered, or an extra/stale step_order) fails closed the
        same way an out-of-range value does: nothing is partially applied.
        """
        missing_orders = {gs.step_order for gs in missing_steps}
        reply_orders = {s.step_order for s in duration_reply.steps}

        if reply_orders != missing_orders:
            missing_str = ", ".join(str(o) for o in sorted(missing_orders))
            reply_str = ", ".join(str(o) for o in sorted(reply_orders))
            return _DurationReplyResolution(
                values=None,
                failure_reason=(
                    "This reply must answer exactly the steps that are "
                    f"still missing a duration (step {missing_str}), but "
                    f"named step {reply_str} instead — this can't proceed."
                ),
            )

        values: dict[int, float] = {}
        for step_reply in duration_reply.steps:
            minutes = step_reply.hours * 60.0
            if not (0 < minutes <= _MAX_DURATION_MINUTES):
                max_hours = _MAX_DURATION_MINUTES / 60.0
                return _DurationReplyResolution(
                    values=None,
                    failure_reason=(
                        f"Step {step_reply.step_order}: {step_reply.hours} "
                        f"hours is outside the valid range (0, {max_hours:g}] "
                        "hours — this can't proceed."
                    ),
                )
            values[step_reply.step_order] = minutes

        return _DurationReplyResolution(values=values, failure_reason=None)

    def _resolve_organism_from_transcript(
        self,
        transcript: ClarificationTranscript,
        model_type: ModelType,
        factor4_type: Factor4Type,
    ) -> _TranscriptResolution:
        """
        Attempt to resolve an organism from the user's free-text reply to a
        round-1 clarification question, carried on the request
        (ClarificationTranscript — see its docstring for why PTM does this
        instead of a server-side session).

        Free-text only (2026-08-19, see specs/lessons.md): transcript.user_reply
        is run directly through ComBaseOrganism.all_matches_in_text() — the
        same deterministic substring-alias path a first-turn pathogen_mentioned
        uses. No LLM call anywhere in this method (confirmed live: routing the
        reply through SemanticParser.extract_clarification_response() produced
        an empty extraction ~50% of the time for a clean, unambiguous answer —
        LLM nondeterminism on data that was never ambiguous). Not async: this
        method touches no I/O at all, which is itself a small, checkable proof
        there's no LLM round-trip in this path (contrast with
        _resolve_duration_reply's @staticmethod, the same signal for a method
        that also touches no instance state).

        Fails closed (organism=None with a plain-language failure_reason)
        rather than guessing, on any of:
          - The reply names zero organisms — this also covers a skip/refusal
            ("I don't know", "skip"), since that never names a pathogen
            either; there is no separate wants_to_skip flag to detect, since
            there is no LLM extraction step to produce one.
          - The reply names more than one distinct organism — ambiguous, not
            resolved to an arbitrary one of them.
          - The resolved organism is not executable for (model_type,
            factor4_type) — the real safety boundary. There is no offered-set
            to check membership against: any executable organism may be
            named, not just ones from a prior menu.
        """
        matches = ComBaseOrganism.all_matches_in_text(transcript.user_reply)

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
