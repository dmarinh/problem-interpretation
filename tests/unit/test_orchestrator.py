"""
Unit tests for workflow orchestrator.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.orchestrator import (
    Orchestrator,
    _missing_key_to_audit_key,
)
from app.core.state import SessionManager
from app.models.enums import ComBaseOrganism, Factor4Type, ModelType, SessionStatus
from app.models.extraction import (
    ExtractedClarificationResponse,
    ExtractedDuration,
    ExtractedIntent,
    ExtractedScenario,
    ExtractedTemperature,
)
from app.models.metadata import (
    ClarificationOption,
    ClarificationTranscript,
    DurationClarificationReply,
    DurationStepReply,
    ValueProvenance,
    ValueSource,
)
from app.services.grounding.grounding_service import GroundedStep, GroundedValues


@pytest.fixture
def mock_parser():
    """Create mock semantic parser."""
    parser = MagicMock()
    parser.classify_intent = AsyncMock(
        return_value=ExtractedIntent(
            is_prediction_request=True,
            is_information_query=False,
            confidence=0.95,
        )
    )
    parser.extract_scenario = AsyncMock(
        return_value=ExtractedScenario(
            food_description="raw chicken",
            single_step_temperature=ExtractedTemperature(value_celsius=25.0),
            single_step_duration=ExtractedDuration(value_minutes=180.0),
        )
    )
    return parser


@pytest.fixture
def mock_grounder():
    """Create mock grounding service."""
    grounder = MagicMock()

    async def mock_ground(scenario):
        grounded = GroundedValues()
        grounded.set("temperature_celsius", 25.0, ValueSource.USER_EXPLICIT)
        grounded.set("duration_minutes", 180.0, ValueSource.USER_EXPLICIT)
        grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.RAG_RETRIEVAL)
        grounded.set("ph", 6.0, ValueSource.RAG_RETRIEVAL)
        grounded.set("water_activity", 0.99, ValueSource.RAG_RETRIEVAL)
        return grounded

    grounder.ground_scenario = mock_ground
    return grounder


@pytest.fixture
def mock_engine():
    """Create mock ComBase engine."""
    from app.models.enums import EngineType
    from app.models.execution.combase import ComBaseExecutionResult, ComBaseModelResult

    engine = MagicMock()
    engine.is_available = True
    engine.execute = AsyncMock(
        return_value=ComBaseExecutionResult(
            model_result=ComBaseModelResult(
                mu_max=0.5,
                doubling_time_hours=1.4,
                y_max=10.0,
                h0=0.1,
                model_type=ModelType.GROWTH,
                organism=ComBaseOrganism.SALMONELLA,
                temperature_used=25.0,
                ph_used=6.0,
                aw_used=0.99,
            ),
            step_predictions=[],
            total_log_increase=0.65,
            initial_log_cfu=3.0,
            final_log_cfu=3.65,
            engine_type=EngineType.COMBASE_LOCAL,
            warnings=[],
        )
    )
    return engine


@pytest.fixture
def orchestrator(mock_parser, mock_grounder, mock_engine):
    """Create orchestrator with mocks."""
    return Orchestrator(
        session_manager=SessionManager(),
        semantic_parser=mock_parser,
        grounding_service=mock_grounder,
        standardization_service=None,  # Use real standardizer
        combase_engine=mock_engine,
    )


class TestOrchestrator:
    """Tests for Orchestrator."""

    @pytest.mark.asyncio
    async def test_successful_interpretation(self, orchestrator):
        """Should complete full pipeline successfully."""
        result = await orchestrator.translate("Raw chicken left out for 3 hours at 25C")

        assert result.success is True
        assert result.state.status == SessionStatus.COMPLETED
        assert result.execution_result is not None
        assert result.execution_result.model_result.mu_max > 0

    @pytest.mark.asyncio
    async def test_creates_session(self, orchestrator):
        """Should create a session."""
        result = await orchestrator.translate("Test input")

        assert result.state.session_id is not None
        assert result.state.user_input == "Test input"

    @pytest.mark.asyncio
    async def test_extracts_scenario(self, orchestrator, mock_parser):
        """Should extract scenario from input."""
        result = await orchestrator.translate("Raw chicken at 25C for 3 hours")

        mock_parser.extract_scenario.assert_called_once()
        assert result.state.extracted_scenario is not None

    @pytest.mark.asyncio
    async def test_grounds_values(self, orchestrator, mock_grounder):
        """Should ground values via RAG."""
        result = await orchestrator.translate("Raw chicken at 25C for 3 hours")

        assert result.state.grounded_values is not None
        assert "temperature_celsius" in result.state.grounded_values

    @pytest.mark.asyncio
    async def test_builds_execution_payload(self, orchestrator):
        """Should build execution payload."""
        result = await orchestrator.translate("Raw chicken at 25C for 3 hours")

        assert result.state.execution_payload is not None
        assert result.state.execution_payload.parameters.temperature_celsius == 25.0

    @pytest.mark.asyncio
    async def test_tracks_metadata(self, orchestrator):
        """Should track provenance metadata."""
        result = await orchestrator.translate("Raw chicken at 25C for 3 hours")

        assert result.metadata is not None
        assert len(result.metadata.provenance) > 0

    @pytest.mark.asyncio
    async def test_out_of_scope_fails(self, orchestrator, mock_parser):
        """Should fail for out-of-scope queries."""
        mock_parser.classify_intent = AsyncMock(
            return_value=ExtractedIntent(
                is_prediction_request=False,
                is_information_query=False,
                confidence=0.9,
            )
        )

        result = await orchestrator.translate("What is the meaning of life?")

        assert result.success is False
        assert "out of scope" in result.error.lower()

    @pytest.mark.asyncio
    async def test_engine_not_available(self, orchestrator, mock_engine):
        """Should fail if engine not available."""
        mock_engine.is_available = False

        result = await orchestrator.translate("Raw chicken at 25C for 3 hours")

        assert result.success is False
        assert "not available" in result.error.lower()


class TestMissingKeyToAuditKey:
    """Unit tests for the _missing_key_to_audit_key helper."""

    def test_single_step_duration(self):
        assert _missing_key_to_audit_key("duration") == "duration_minutes"

    def test_multi_step_duration(self):
        assert (
            _missing_key_to_audit_key("duration (step 1)")
            == "duration_minutes (step 1)"
        )
        assert (
            _missing_key_to_audit_key("duration (step 3)")
            == "duration_minutes (step 3)"
        )

    def test_single_step_temperature(self):
        assert _missing_key_to_audit_key("temperature") == "temperature_celsius"

    def test_organism_explicit_branch(self):
        assert _missing_key_to_audit_key("organism") == "organism"

    def test_factor4_no_declared_range(self):
        assert (
            _missing_key_to_audit_key(
                "nitrite_ppm (no declared valid range for nitrite "
                "— cannot bound the input, not modelled)"
            )
            == "nitrite_ppm"
        )

    def test_unknown_field_passthrough(self, caplog):
        import logging

        with caplog.at_level(logging.WARNING, logger="app.core.orchestrator"):
            result = _missing_key_to_audit_key("some_other_field")
        assert result == "some_other_field"
        assert "unrecognised field spec" in caplog.text


class TestValidationFailureAuditCompleteness:
    """
    Verify that when standardization fails with missing_required, the
    orchestrator still populates metadata completely so _build_field_audit
    can produce a useful audit trail — true regardless of whether the
    terminal outcome is a hard FAILED or (2026-08-17, duration gate)
    AWAITING_CLARIFICATION; _record_missing_required() fires on both paths.

    Uses the real StandardizationService (no registry — defaults/missing only)
    and a mock grounder that returns a multi-step GroundedValues where step 1
    has a resolved temperature but no duration.
    """

    @pytest.fixture
    def mock_parser_multistep(self):
        from app.models.extraction import ExtractedEnvironmentalConditions

        parser = MagicMock()
        parser.classify_intent = AsyncMock(
            return_value=ExtractedIntent(
                is_prediction_request=True,
                is_information_query=False,
                confidence=0.95,
            )
        )
        parser.extract_scenario = AsyncMock(
            return_value=ExtractedScenario(
                food_description="ground beef",
                is_multi_step=True,
                single_step_temperature=ExtractedTemperature(),
                single_step_duration=ExtractedDuration(),
                time_temperature_steps=[],
                environmental_conditions=ExtractedEnvironmentalConditions(),
            )
        )
        return parser

    @pytest.fixture
    def mock_grounder_missing_duration(self):
        """
        Returns GroundedValues for a 2-step scenario where step 1 has a
        resolved temperature (room temperature → 25°C) but no duration.
        Step 2 is omitted to keep the fixture minimal.
        """
        grounder = MagicMock()

        async def _ground(_scenario):
            grounded = GroundedValues()
            grounded.set(
                "organism", ComBaseOrganism.SALMONELLA, ValueSource.RAG_RETRIEVAL
            )
            grounded.add_step(
                step_order=1,
                temperature_celsius=25.0,
                duration_minutes=None,
                temp_provenance=ValueProvenance(
                    source=ValueSource.USER_INFERRED,
                    extraction_method="rule_match",
                    matched_pattern="room temperature",
                ),
                dur_provenance=None,  # grounding returned (None, None) for duration
            )
            return grounded

        grounder.ground_scenario = _ground
        return grounder

    @pytest.fixture
    def orchestrator_for_failure(
        self, mock_parser_multistep, mock_grounder_missing_duration, mock_engine
    ):
        return Orchestrator(
            session_manager=SessionManager(),
            semantic_parser=mock_parser_multistep,
            grounding_service=mock_grounder_missing_duration,
            standardization_service=None,  # real standardizer, no registry
            combase_engine=mock_engine,
        )

    @pytest.mark.asyncio
    async def test_failure_result_is_awaiting_duration_clarification(
        self, orchestrator_for_failure
    ):
        """2026-08-17: a single missing step duration (organism resolved) now
        routes to the duration clarification gate (AWAITING_CLARIFICATION),
        not a hard FAILED -- same as the organism gate's own convention.
        Previously (before the duration gate existed) this asserted FAILED."""
        result = await orchestrator_for_failure.translate("A2-style multi-step query")
        assert result.success is False
        assert result.state.status == SessionStatus.AWAITING_CLARIFICATION

    @pytest.mark.asyncio
    async def test_duration_clarification_question_names_missing_field(
        self, orchestrator_for_failure
    ):
        """2026-08-17: replaces the old test_error_names_missing_field --
        error stays None on the clarification path (state.set_error() is
        never called), so the missing field now shows up on the duration
        clarification question instead of the error string."""
        result = await orchestrator_for_failure.translate("A2-style multi-step query")
        assert result.error is None
        question = result.state.duration_clarification_question
        assert question is not None
        assert [s.step_order for s in question.steps] == [1]

    @pytest.mark.asyncio
    async def test_organism_in_provenance(self, orchestrator_for_failure):
        result = await orchestrator_for_failure.translate("A2-style multi-step query")
        assert result.metadata is not None
        assert "organism" in result.metadata.provenance

    @pytest.mark.asyncio
    async def test_step_temperature_bridged_to_provenance(
        self, orchestrator_for_failure
    ):
        """Per-step temperature provenance must be visible in metadata after grounding."""
        result = await orchestrator_for_failure.translate("A2-style multi-step query")
        assert "temperature_celsius (step 1)" in result.metadata.provenance
        prov = result.metadata.provenance["temperature_celsius (step 1)"]
        assert prov.source == ValueSource.USER_INFERRED

    @pytest.mark.asyncio
    async def test_missing_duration_appears_with_null_source(
        self, orchestrator_for_failure
    ):
        """The missing duration must appear in provenance with source=MISSING."""
        result = await orchestrator_for_failure.translate("A2-style multi-step query")
        assert "duration_minutes (step 1)" in result.metadata.provenance
        prov = result.metadata.provenance["duration_minutes (step 1)"]
        assert prov.source == ValueSource.MISSING

    @pytest.mark.asyncio
    async def test_defaults_imputed_populated_on_failure(
        self, orchestrator_for_failure
    ):
        """Defaults imputed before the failure point must appear in metadata."""
        result = await orchestrator_for_failure.translate("A2-style multi-step query")
        imputed_fields = {d.field_name for d in result.metadata.defaults_imputed}
        # ph and water_activity are always defaulted when not grounded
        assert "ph" in imputed_fields
        assert "water_activity" in imputed_fields

    @pytest.mark.asyncio
    async def test_structured_warning_names_missing_field(
        self, orchestrator_for_failure
    ):
        """audit.warnings must contain a structured message naming the missing field."""
        result = await orchestrator_for_failure.translate("A2-style multi-step query")
        warning_text = " ".join(result.metadata.warnings)
        assert "Validation failed" in warning_text
        assert "duration (step 1)" in warning_text

    @pytest.mark.asyncio
    async def test_prediction_is_null_on_failure(self, orchestrator_for_failure):
        result = await orchestrator_for_failure.translate("A2-style multi-step query")
        assert result.execution_result is None


class TestResolveOrganismFromTranscript:
    """
    A1b: Orchestrator._resolve_organism_from_transcript() -- the validation
    layer for a round-2 re-entry reply, tested directly and in isolation
    from the rest of the pipeline. Tests mock the LLM
    (extract_clarification_response) and the registry's executability
    check; the point is the validation layer, not extraction accuracy.
    """

    @staticmethod
    def _make_orchestrator(
        *,
        extracted_response: ExtractedClarificationResponse,
        is_executable: bool = True,
    ) -> Orchestrator:
        parser = MagicMock()
        parser.extract_clarification_response = AsyncMock(
            return_value=extracted_response
        )

        engine = MagicMock()
        engine.registry.is_executable = MagicMock(return_value=is_executable)

        standardizer = MagicMock()
        standardizer.organism_display_name = MagicMock(
            side_effect=lambda o: o.name.replace("_", " ").title()
        )

        return Orchestrator(
            session_manager=SessionManager(),
            semantic_parser=parser,
            grounding_service=MagicMock(),
            standardization_service=standardizer,
            combase_engine=engine,
        )

    @staticmethod
    def _transcript(
        *, options_offered: list[ClarificationOption], user_reply: str = "my reply"
    ) -> ClarificationTranscript:
        return ClarificationTranscript(
            original_query="frobnitz left out for 3 hours",
            question_asked="Which pathogen are you concerned about?",
            options_offered=options_offered,
            user_reply=user_reply,
        )

    @pytest.mark.asyncio
    async def test_resolves_offered_executable_organism(self):
        orch = self._make_orchestrator(
            extracted_response=ExtractedClarificationResponse(
                selected_option="Salmonella", wants_to_skip=False
            ),
        )
        transcript = self._transcript(
            options_offered=[ClarificationOption(code="ss", label="Salmonella")]
        )

        resolution = await orch._resolve_organism_from_transcript(
            transcript, ModelType.GROWTH, Factor4Type.NONE
        )

        assert resolution.organism == ComBaseOrganism.SALMONELLA
        assert resolution.failure_reason is None

    @pytest.mark.asyncio
    async def test_wants_to_skip_fails_closed(self):
        orch = self._make_orchestrator(
            extracted_response=ExtractedClarificationResponse(wants_to_skip=True),
        )
        transcript = self._transcript(
            options_offered=[ClarificationOption(code="ss", label="Salmonella")]
        )

        resolution = await orch._resolve_organism_from_transcript(
            transcript, ModelType.GROWTH, Factor4Type.NONE
        )

        assert resolution.organism is None
        assert "no organism default exists" in resolution.failure_reason.lower()

    @pytest.mark.asyncio
    async def test_unmapped_reply_fails_closed(self):
        orch = self._make_orchestrator(
            extracted_response=ExtractedClarificationResponse(
                selected_option="something else", wants_to_skip=False
            ),
        )
        transcript = self._transcript(
            options_offered=[ClarificationOption(code="ss", label="Salmonella")]
        )

        resolution = await orch._resolve_organism_from_transcript(
            transcript, ModelType.GROWTH, Factor4Type.NONE
        )

        assert resolution.organism is None
        assert "didn't name a pathogen" in resolution.failure_reason.lower()

    @pytest.mark.asyncio
    async def test_ambiguous_multi_match_fails_closed(self):
        orch = self._make_orchestrator(
            extracted_response=ExtractedClarificationResponse(
                selected_option="Salmonella or Listeria", wants_to_skip=False
            ),
        )
        transcript = self._transcript(
            options_offered=[
                ClarificationOption(code="ss", label="Salmonella"),
                ClarificationOption(code="lm", label="Listeria monocytogenes"),
            ]
        )

        resolution = await orch._resolve_organism_from_transcript(
            transcript, ModelType.GROWTH, Factor4Type.NONE
        )

        assert resolution.organism is None
        assert "more than one" in resolution.failure_reason.lower()

    @pytest.mark.asyncio
    async def test_disagreement_between_fields_is_ambiguous(self):
        """selected_option and understood_value naming different organisms
        is scanned as one combined text -- surfaces as ambiguous multi-match,
        not resolved by picking either field as authoritative."""
        orch = self._make_orchestrator(
            extracted_response=ExtractedClarificationResponse(
                selected_option="Salmonella",
                understood_value="Actually I meant Listeria",
                wants_to_skip=False,
            ),
        )
        transcript = self._transcript(
            options_offered=[
                ClarificationOption(code="ss", label="Salmonella"),
                ClarificationOption(code="lm", label="Listeria monocytogenes"),
            ]
        )

        resolution = await orch._resolve_organism_from_transcript(
            transcript, ModelType.GROWTH, Factor4Type.NONE
        )

        assert resolution.organism is None
        assert "more than one" in resolution.failure_reason.lower()

    @pytest.mark.asyncio
    async def test_resolved_but_not_offered_fails_closed(self):
        """Names a real organism the LLM can map, but it wasn't in
        transcript.options_offered -- not silently substituted."""
        orch = self._make_orchestrator(
            extracted_response=ExtractedClarificationResponse(
                selected_option="Shigella", wants_to_skip=False
            ),
        )
        transcript = self._transcript(
            options_offered=[ClarificationOption(code="ss", label="Salmonella")]
        )

        resolution = await orch._resolve_organism_from_transcript(
            transcript, ModelType.GROWTH, Factor4Type.NONE
        )

        assert resolution.organism is None
        assert "wasn't one of the options" in resolution.failure_reason.lower()

    @pytest.mark.asyncio
    async def test_offered_but_no_longer_executable_fails_closed(self):
        """Defense in depth: even though the organism was offered, a fresh
        executability re-check (registry.is_executable) can still say no --
        checked, not trusted, per the A1b spec."""
        orch = self._make_orchestrator(
            extracted_response=ExtractedClarificationResponse(
                selected_option="Salmonella", wants_to_skip=False
            ),
            is_executable=False,
        )
        transcript = self._transcript(
            options_offered=[ClarificationOption(code="ss", label="Salmonella")]
        )

        resolution = await orch._resolve_organism_from_transcript(
            transcript, ModelType.GROWTH, Factor4Type.NONE
        )

        assert resolution.organism is None
        assert "not supported for" in resolution.failure_reason.lower()


class TestResolveDurationReply:
    """
    2026-08-17: Orchestrator._resolve_duration_reply() -- the duration gate's
    validation layer, tested directly and in isolation. Unlike
    TestResolveOrganismFromTranscript, no mocking is needed at all: the
    method is @staticmethod, touches no service, and calls no LLM -- pure
    structural + range validation over plain Python values.
    """

    @staticmethod
    def _step(order: int) -> GroundedStep:
        return GroundedStep(
            step_order=order, temperature_celsius=25.0, duration_minutes=None
        )

    @staticmethod
    def _reply(*pairs: tuple[int, float]) -> DurationClarificationReply:
        return DurationClarificationReply(
            original_query="q",
            steps=[
                DurationStepReply(step_order=order, hours=hours)
                for order, hours in pairs
            ],
        )

    def test_exact_match_resolves_verbatim(self):
        resolution = Orchestrator._resolve_duration_reply(
            self._reply((1, 2.0), (2, 8.0)), [self._step(1), self._step(2)]
        )
        assert resolution.failure_reason is None
        assert resolution.values == {1: 120.0, 2: 480.0}

    def test_partial_reply_fails_closed(self):
        """Reply answers only step 1; step 2 is still missing -> reject,
        nothing applied (all-or-nothing)."""
        resolution = Orchestrator._resolve_duration_reply(
            self._reply((1, 2.0)), [self._step(1), self._step(2)]
        )
        assert resolution.values is None
        assert "step" in resolution.failure_reason.lower()

    def test_extra_stale_step_order_fails_closed(self):
        """Reply names a step that isn't currently missing -> reject, same
        as an incomplete reply -- both directions of mismatch fail the same
        way."""
        resolution = Orchestrator._resolve_duration_reply(
            self._reply((1, 2.0), (3, 1.0)), [self._step(1)]
        )
        assert resolution.values is None

    def test_zero_missing_steps_now_resolved_on_retry_is_not_required(self):
        """If grounding resolved a step differently between rounds, the
        currently-missing set can shrink -- the reply must match THAT set,
        not a stale round-1 set the caller might still be holding."""
        resolution = Orchestrator._resolve_duration_reply(
            self._reply((2, 8.0)), [self._step(2)]
        )
        assert resolution.failure_reason is None
        assert resolution.values == {2: 480.0}

    def test_out_of_range_value_fails_closed_not_clamped(self):
        """5000 hours exceeds the 2190h/131400min ceiling."""
        resolution = Orchestrator._resolve_duration_reply(
            self._reply((1, 5000.0)), [self._step(1)]
        )
        assert resolution.values is None
        assert "5000" in resolution.failure_reason

    def test_ceiling_boundary_is_inclusive(self):
        """Exactly 2190 hours (131400 min) is the documented boundary and
        must be accepted, not rejected."""
        resolution = Orchestrator._resolve_duration_reply(
            self._reply((1, 2190.0)), [self._step(1)]
        )
        assert resolution.failure_reason is None
        assert resolution.values == {1: 131400.0}

    def test_no_llm_or_service_dependency(self):
        """The method is callable with no Orchestrator instance at all --
        proof there is no self._parser/self._engine dependency, i.e. no LLM
        anywhere in this path."""
        resolution = Orchestrator._resolve_duration_reply(
            self._reply((1, 2.0)), [self._step(1)]
        )
        assert resolution.values == {1: 120.0}
