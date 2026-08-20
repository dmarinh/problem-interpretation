"""
Integration tests for the full translation pipeline.

These tests run the complete pipeline with real components
(except LLM which is mocked to avoid API costs).
"""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.core.orchestrator import Orchestrator
from app.core.state import SessionManager
from app.engines.combase.engine import ComBaseEngine
from app.models.enums import (
    ClarificationReason,
    ComBaseOrganism,
    ModelType,
    OrganismGroundingFailureStage,
    SessionStatus,
)
from app.models.extraction import (
    ExtractedDuration,
    ExtractedEnvironmentalConditions,
    ExtractedIntent,
    ExtractedScenario,
    ExtractedTemperature,
    ExtractedTimeTemperatureStep,
)
from app.models.metadata import (
    ClarificationTranscript,
    DurationClarificationReply,
    DurationStepReply,
    ValueSource,
)
from app.rag.retrieval import RetrievalService
from app.rag.vector_store import VectorStore
from app.services.grounding.grounding_service import GroundingService
from app.services.standardization.standardization_service import StandardizationService


def create_scenario(
    food_description: str | None = None,
    food_state: str | None = None,
    pathogen_mentioned: str | None = None,
    temperature: ExtractedTemperature | None = None,
    duration: ExtractedDuration | None = None,
    environmental_conditions: ExtractedEnvironmentalConditions | None = None,
    is_cooking_scenario: bool = False,
    is_storage_scenario: bool = False,
    is_non_thermal_treatment: bool = False,
    implied_model_type: ModelType | None = None,
) -> ExtractedScenario:
    """Helper to create ExtractedScenario with all required fields."""
    return ExtractedScenario(
        food_description=food_description,
        food_state=food_state,
        pathogen_mentioned=pathogen_mentioned,
        is_multi_step=False,
        single_step_temperature=temperature or ExtractedTemperature(),
        single_step_duration=duration or ExtractedDuration(),
        time_temperature_steps=[],
        environmental_conditions=environmental_conditions
        or ExtractedEnvironmentalConditions(),
        concern_type="safety",
        additional_context=None,
        is_cooking_scenario=is_cooking_scenario,
        is_storage_scenario=is_storage_scenario,
        is_non_thermal_treatment=is_non_thermal_treatment,
        implied_model_type=implied_model_type,
    )


@pytest.fixture
def temp_dir():
    """Create temporary directory for test artifacts."""
    d = Path(tempfile.mkdtemp())
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def combase_engine():
    """Load real ComBase engine."""
    engine = ComBaseEngine()
    csv_path = Path("data/combase_models.csv")
    if csv_path.exists():
        engine.load_models(csv_path)
    return engine


@pytest.fixture
def vector_store(temp_dir):
    """Create and populate vector store with test data."""
    store = VectorStore(persist_directory=temp_dir / "vectors")
    store.initialize()

    # Add food properties
    store.add_documents(
        documents=[
            "Raw chicken has pH between 5.9 and 6.2, water activity 0.99. Store below 4°C.",
            "Raw ground beef has pH 5.4-5.8 and water activity 0.98.",
            "Cooked rice has pH 6.0-6.6 and water activity 0.96-0.98.",
            "Fresh salmon has pH 6.1-6.5 and water activity 0.98-0.99.",
            "Pasteurized milk has pH 6.5-6.7 and water activity 0.99.",
        ],
        doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
    )

    # Add pathogen hazards
    store.add_documents(
        documents=[
            "Salmonella is commonly found in raw poultry and eggs. Growth range 5-47°C, optimal 37°C.",
            "Listeria monocytogenes can grow at refrigeration temperatures 0-4°C. Found in deli meats.",
            "E. coli O157:H7 is associated with undercooked ground beef. Minimum growth temperature 7°C.",
            "Bacillus cereus produces toxins in cooked rice left at room temperature.",
        ],
        doc_type=VectorStore.TYPE_PATHOGEN_HAZARDS,
    )

    return store


@pytest.fixture
def mock_semantic_parser():
    """Create mock semantic parser."""
    parser = AsyncMock()

    parser.classify_intent = AsyncMock(
        return_value=ExtractedIntent(
            is_prediction_request=True,
            is_information_query=False,
            confidence=0.95,
        )
    )

    # pathogen_mentioned is now required — the silent Salmonella default was removed.
    # This fixture explicitly names Salmonella so tests that rely on the default
    # fixture (and aren't specifically testing pathogen behavior) continue to work.
    parser.extract_scenario = AsyncMock(
        return_value=create_scenario(
            food_description="raw chicken",
            food_state="raw",
            pathogen_mentioned="Salmonella",
            temperature=ExtractedTemperature(description="room temperature"),
            duration=ExtractedDuration(value_minutes=180.0),
            is_storage_scenario=True,
        )
    )

    return parser


@pytest.fixture
def orchestrator(combase_engine, vector_store, mock_semantic_parser):
    """Create orchestrator with real components except LLM."""
    if not combase_engine.is_available:
        pytest.skip("ComBase models not available")

    retrieval_service = RetrievalService(vector_store=vector_store)
    grounding_service = GroundingService(retrieval_service=retrieval_service)
    standardization_service = StandardizationService(
        model_registry=combase_engine.registry
    )

    return Orchestrator(
        session_manager=SessionManager(),
        semantic_parser=mock_semantic_parser,
        grounding_service=grounding_service,
        standardization_service=standardization_service,
        combase_engine=combase_engine,
    )


class TestFullPipeline:
    """End-to-end pipeline tests."""

    @pytest.mark.asyncio
    async def test_chicken_room_temperature(self, orchestrator, mock_semantic_parser):
        """Should process chicken at room temperature query."""
        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=create_scenario(
                food_description="raw chicken",
                pathogen_mentioned="Salmonella",
                temperature=ExtractedTemperature(description="room temperature"),
                duration=ExtractedDuration(value_minutes=180.0),
                is_storage_scenario=True,
            )
        )

        result = await orchestrator.translate(
            "Raw chicken left out for 3 hours at room temperature"
        )

        assert result.success is True, f"Failed with error: {result.error}"
        assert result.state.status == SessionStatus.COMPLETED
        assert result.execution_result is not None
        assert result.execution_result.total_log_increase > 0

    @pytest.mark.asyncio
    async def test_explicit_temperature(self, orchestrator, mock_semantic_parser):
        """Should use explicit temperature when provided."""
        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=create_scenario(
                food_description="raw chicken",
                pathogen_mentioned="Salmonella",
                temperature=ExtractedTemperature(value_celsius=30.0),
                duration=ExtractedDuration(value_minutes=120.0),
                is_storage_scenario=True,
            )
        )

        result = await orchestrator.translate("Chicken at 30°C for 2 hours")

        assert result.success is True, f"Failed with error: {result.error}"
        assert result.state.execution_payload.parameters.temperature_celsius == 30.0

    @pytest.mark.asyncio
    async def test_explicit_pathogen(self, orchestrator, mock_semantic_parser):
        """Should use explicit pathogen when mentioned."""
        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=create_scenario(
                food_description="deli meat",
                pathogen_mentioned="Listeria",
                temperature=ExtractedTemperature(value_celsius=4.0),
                duration=ExtractedDuration(value_minutes=1440.0),
                is_storage_scenario=True,
            )
        )

        result = await orchestrator.translate(
            "Listeria growth in deli meat at 4°C for 24 hours"
        )

        assert result.success is True, f"Failed with error: {result.error}"
        assert (
            result.state.execution_payload.model_selection.organism
            == ComBaseOrganism.LISTERIA_MONOCYTOGENES
        )

    @pytest.mark.asyncio
    async def test_explicitly_named_pathogen_flows_through(
        self, orchestrator, mock_semantic_parser
    ):
        """Explicitly named pathogen flows through grounding into the execution payload."""
        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=create_scenario(
                food_description="raw chicken",
                pathogen_mentioned="Salmonella",
                temperature=ExtractedTemperature(value_celsius=25.0),
                duration=ExtractedDuration(value_minutes=180.0),
                is_storage_scenario=True,
            )
        )

        result = await orchestrator.translate("Raw chicken at 25°C for 3 hours")

        assert result.success is True, f"Failed with error: {result.error}"
        organism = result.state.execution_payload.model_selection.organism
        assert organism == ComBaseOrganism.SALMONELLA

    @pytest.mark.asyncio
    async def test_duration_interpretation(self, orchestrator, mock_semantic_parser):
        """Should interpret vague duration descriptions."""
        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=create_scenario(
                food_description="cooked rice",
                pathogen_mentioned="Salmonella",
                temperature=ExtractedTemperature(value_celsius=25.0),
                duration=ExtractedDuration(description="overnight"),
                is_storage_scenario=True,
            )
        )

        result = await orchestrator.translate("Cooked rice left out overnight")

        assert result.success is True, f"Failed with error: {result.error}"
        # "overnight" should be interpreted as ~480 minutes (8 hours)
        duration = (
            result.state.execution_payload.time_temperature_profile.total_duration_minutes
        )
        assert 400 <= duration <= 600

    @pytest.mark.asyncio
    async def test_provenance_tracking(self, orchestrator, mock_semantic_parser):
        """Should track provenance of all grounded values."""
        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=create_scenario(
                food_description="raw chicken",
                pathogen_mentioned="Salmonella",
                temperature=ExtractedTemperature(description="room temperature"),
                duration=ExtractedDuration(value_minutes=180.0),
                is_storage_scenario=True,
            )
        )

        result = await orchestrator.translate(
            "Raw chicken at room temperature for 3 hours"
        )

        assert result.success is True, f"Failed with error: {result.error}"
        assert result.metadata is not None
        assert len(result.metadata.provenance) > 0

        # Should have provenance for temperature (from interpretation rule)
        temp_prov = result.metadata.provenance.get("temperature_celsius")
        assert temp_prov is not None

    @pytest.mark.asyncio
    async def test_thermal_inactivation(
        self, orchestrator, mock_semantic_parser, combase_engine
    ):
        """Should run thermal inactivation model."""
        # Check if Salmonella thermal model exists
        model = combase_engine.registry.get_model(
            ComBaseOrganism.SALMONELLA,
            ModelType.THERMAL_INACTIVATION,
        )
        if model is None:
            pytest.skip("Salmonella thermal model not available")

        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=create_scenario(
                food_description="chicken",
                pathogen_mentioned="Salmonella",
                temperature=ExtractedTemperature(value_celsius=60.0),
                duration=ExtractedDuration(value_minutes=10.0),
                is_cooking_scenario=True,
                implied_model_type=ModelType.THERMAL_INACTIVATION,
            )
        )

        result = await orchestrator.translate(
            "Cooking chicken at 60°C for 10 minutes",
            model_type=ModelType.THERMAL_INACTIVATION,
        )

        assert result.success is True, f"Failed with error: {result.error}"
        # Thermal inactivation should show negative log change (death)
        assert result.execution_result.total_log_increase < 0

    @pytest.mark.asyncio
    async def test_out_of_scope_query(self, orchestrator, mock_semantic_parser):
        """Should reject out-of-scope queries."""
        mock_semantic_parser.classify_intent = AsyncMock(
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
    async def test_model_type_inference_cooking(
        self, orchestrator, mock_semantic_parser, combase_engine
    ):
        """Should infer thermal inactivation for cooking scenarios."""
        model = combase_engine.registry.get_model(
            ComBaseOrganism.SALMONELLA,
            ModelType.THERMAL_INACTIVATION,
        )
        if model is None:
            pytest.skip("Salmonella thermal model not available")

        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=create_scenario(
                food_description="chicken",
                pathogen_mentioned="Salmonella",
                temperature=ExtractedTemperature(value_celsius=70.0),
                duration=ExtractedDuration(value_minutes=5.0),
                is_cooking_scenario=True,
                implied_model_type=ModelType.THERMAL_INACTIVATION,
            )
        )

        # Don't pass model_type - let it be inferred
        result = await orchestrator.translate("Cooking chicken to 70°C for 5 minutes")

        assert result.success is True, f"Failed with error: {result.error}"
        assert (
            result.state.execution_payload.model_selection.model_type
            == ModelType.THERMAL_INACTIVATION
        )

    @pytest.mark.asyncio
    async def test_model_type_inference_storage(
        self, orchestrator, mock_semantic_parser
    ):
        """Should infer growth for storage scenarios."""
        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=create_scenario(
                food_description="raw chicken",
                pathogen_mentioned="Salmonella",
                temperature=ExtractedTemperature(value_celsius=25.0),
                duration=ExtractedDuration(value_minutes=180.0),
                is_storage_scenario=True,
                implied_model_type=ModelType.GROWTH,
            )
        )

        # Don't pass model_type - let it be inferred
        result = await orchestrator.translate("Chicken left out for 3 hours")

        assert result.success is True, f"Failed with error: {result.error}"
        assert (
            result.state.execution_payload.model_selection.model_type
            == ModelType.GROWTH
        )


class TestEdgeCases:
    """Edge case and error handling tests."""

    @pytest.mark.asyncio
    async def test_missing_single_step_duration_defaults_to_long_window(
        self, orchestrator, mock_semantic_parser
    ):
        """Phase 9.7: missing single-step duration succeeds with long-window default applied."""
        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=create_scenario(
                food_description="chicken",
                pathogen_mentioned="Salmonella",
                temperature=ExtractedTemperature(value_celsius=25.0),
                duration=ExtractedDuration(),  # No duration info
                is_storage_scenario=True,
            )
        )

        result = await orchestrator.translate("Chicken at 25°C")

        assert result.success is True
        assert result.error is None

        duration_default = next(
            (
                d
                for d in result.metadata.defaults_imputed
                if d.field_name == "duration_minutes"
            ),
            None,
        )
        assert duration_default is not None
        assert duration_default.imputed_value == 10080.0
        assert duration_default.source == ValueSource.LONG_WINDOW_DEFAULT
        assert any("duration" in w.lower() for w in result.metadata.warnings)
        # 7-day window at 25°C reaches the physical growth cap
        assert abs(result.execution_result.total_log_increase) == 15.0

    @pytest.mark.asyncio
    async def test_explicit_duration_no_long_window_regression(
        self, orchestrator, mock_semantic_parser
    ):
        """Phase 9.7: explicit duration does not trigger the long-window default."""
        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=create_scenario(
                food_description="chicken",
                pathogen_mentioned="Salmonella",
                temperature=ExtractedTemperature(value_celsius=25.0),
                duration=ExtractedDuration(value_minutes=120.0),
                is_storage_scenario=True,
            )
        )

        result = await orchestrator.translate("Chicken at 25°C for 2 hours")

        assert result.success is True
        duration_defaults = [
            d
            for d in result.metadata.defaults_imputed
            if d.field_name == "duration_minutes"
        ]
        assert duration_defaults == []

    @pytest.mark.asyncio
    async def test_rule_matched_duration_no_long_window(
        self, orchestrator, mock_semantic_parser
    ):
        """Phase 9.7: rule-matched duration ('overnight' → 480 min) does not trigger long-window."""
        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=create_scenario(
                food_description="chicken",
                pathogen_mentioned="Salmonella",
                temperature=ExtractedTemperature(value_celsius=25.0),
                duration=ExtractedDuration(description="overnight"),
                is_storage_scenario=True,
            )
        )

        result = await orchestrator.translate("Chicken overnight")

        assert result.success is True
        duration_defaults = [
            d
            for d in result.metadata.defaults_imputed
            if d.field_name == "duration_minutes"
        ]
        assert duration_defaults == []
        assert (
            result.state.execution_payload.time_temperature_profile.total_duration_minutes
            == 480.0
        )

    @pytest.mark.asyncio
    async def test_multistep_missing_one_duration_routes_to_duration_gate(
        self, orchestrator, mock_semantic_parser
    ):
        """2026-08-17: multi-step with a single missing step duration now
        routes to the duration clarification gate (AWAITING_CLARIFICATION)
        instead of hard-failing -- organism resolved, only step 1's duration
        is missing. Previously (Phase 9.7, before the duration gate existed)
        this hard-failed naming step 1 in the error string; now it asks."""
        multi_step_scenario = ExtractedScenario(
            food_description="chicken",
            pathogen_mentioned="Salmonella",
            is_multi_step=True,
            single_step_temperature=ExtractedTemperature(),
            single_step_duration=ExtractedDuration(),
            time_temperature_steps=[
                ExtractedTimeTemperatureStep(
                    sequence_order=1,
                    temperature=ExtractedTemperature(value_celsius=25.0),
                    duration=ExtractedDuration(),  # missing
                ),
                ExtractedTimeTemperatureStep(
                    sequence_order=2,
                    temperature=ExtractedTemperature(value_celsius=4.0),
                    duration=ExtractedDuration(value_minutes=60.0),
                ),
            ],
            environmental_conditions=ExtractedEnvironmentalConditions(),
            concern_type="safety",
            additional_context=None,
            is_cooking_scenario=False,
            is_storage_scenario=True,
            is_non_thermal_treatment=False,
            implied_model_type=ModelType.GROWTH,
        )
        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=multi_step_scenario
        )

        result = await orchestrator.translate("Chicken in two stages")

        assert result.success is False
        assert result.state.status == SessionStatus.AWAITING_CLARIFICATION
        assert result.error is None
        question = result.state.duration_clarification_question
        assert question is not None
        assert [s.step_order for s in question.steps] == [1]

    @pytest.mark.asyncio
    async def test_multistep_all_missing_duration_gate_names_every_step(
        self, orchestrator, mock_semantic_parser
    ):
        """2026-08-17: multi-step with both durations missing routes to the
        duration gate naming BOTH steps in a single question -- proves 2a
        (the profile-builder loop now runs to completion, collecting every
        missing duration, not just the first). Previously (Phase 9.7) this
        hard-failed naming step 1 only, because the old loop returned at the
        first missing duration and never evaluated step 2 at all."""
        multi_step_scenario = ExtractedScenario(
            food_description="chicken",
            pathogen_mentioned="Salmonella",
            is_multi_step=True,
            single_step_temperature=ExtractedTemperature(),
            single_step_duration=ExtractedDuration(),
            time_temperature_steps=[
                ExtractedTimeTemperatureStep(
                    sequence_order=1,
                    temperature=ExtractedTemperature(value_celsius=25.0),
                    duration=ExtractedDuration(),  # missing
                ),
                ExtractedTimeTemperatureStep(
                    sequence_order=2,
                    temperature=ExtractedTemperature(value_celsius=4.0),
                    duration=ExtractedDuration(),  # missing
                ),
            ],
            environmental_conditions=ExtractedEnvironmentalConditions(),
            concern_type="safety",
            additional_context=None,
            is_cooking_scenario=False,
            is_storage_scenario=True,
            is_non_thermal_treatment=False,
            implied_model_type=ModelType.GROWTH,
        )
        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=multi_step_scenario
        )

        result = await orchestrator.translate("Chicken in two stages")

        assert result.success is False
        assert result.state.status == SessionStatus.AWAITING_CLARIFICATION
        assert result.error is None
        question = result.state.duration_clarification_question
        assert question is not None
        assert [s.step_order for s in question.steps] == [1, 2]

    @pytest.mark.asyncio
    async def test_defaults_applied_with_warnings(
        self, orchestrator, mock_semantic_parser
    ):
        """Should apply defaults and track warnings."""
        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=create_scenario(
                food_description="unknown food",
                pathogen_mentioned="Salmonella",
                temperature=ExtractedTemperature(value_celsius=25.0),
                duration=ExtractedDuration(value_minutes=180.0),
                is_storage_scenario=True,
            )
        )

        result = await orchestrator.translate("Unknown food at 25°C for 3 hours")

        assert result.success is True, f"Failed with error: {result.error}"
        # Should have warnings about defaults applied
        assert result.metadata is not None
        assert (
            len(result.metadata.warnings) > 0
            or len(result.metadata.defaults_imputed) > 0
        )


class TestAuditFieldMap:
    """
    Integration tests for the post-standardization field_audit map.

    These tests run the pipeline end-to-end (with mocked LLM) and inspect
    the field_audit dict built by _build_field_audit via the route handler.
    """

    @pytest.mark.asyncio
    async def test_chicken_query_ph_final_value_is_upper_bound(
        self, orchestrator, mock_semantic_parser
    ):
        """
        T1 (chicken): the test vector store has "Raw chicken has pH between 5.9
        and 6.2".  For a growth model the upper bound (6.2) must be selected.
        field_audit.ph.final_value must reflect that selection, not the
        pre-standardization placeholder (5.9).
        """
        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=create_scenario(
                food_description="raw chicken",
                pathogen_mentioned="Salmonella",
                temperature=ExtractedTemperature(value_celsius=25.0),
                duration=ExtractedDuration(value_minutes=240.0),
                is_storage_scenario=True,
            )
        )

        result = await orchestrator.translate("Raw chicken kept at 25°C for 4 hours.")

        assert result.success is True, f"Failed with error: {result.error}"
        assert result.metadata is not None

        from app.api.routes.translation import _build_field_audit

        field_audit = _build_field_audit(result)

        # pH must be present and reflect the post-standardization bound
        assert "ph" in field_audit, "ph must appear in field_audit"
        ph_entry = field_audit["ph"]

        # final_value must equal the value the model actually received
        ph_used = result.state.execution_payload.parameters.ph
        assert ph_entry.final_value == pytest.approx(ph_used), (
            f"field_audit.ph.final_value ({ph_entry.final_value}) should equal "
            f"the model's ph_used ({ph_used})"
        )

        # When a range was retrieved and a bound was selected, assert the structure
        if (
            ph_entry.standardization is not None
            and ph_entry.standardization.rule == "range_bound_selection"
        ):
            std = ph_entry.standardization
            assert std.direction == "upper"
            assert isinstance(std.before_value, list) and len(std.before_value) == 2
            assert std.after_value == pytest.approx(ph_used)

    @pytest.mark.asyncio
    async def test_rice_query_defaulted_water_activity_in_field_audit(
        self, orchestrator, mock_semantic_parser
    ):
        """
        T4 (rice): cooked rice has aw grounded from RAG; but if it is absent,
        StandardizationService defaults it to 0.99.  Either way water_activity
        must appear in field_audit — whether grounded or defaulted.
        """
        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=create_scenario(
                food_description="cooked rice",
                pathogen_mentioned="Salmonella",
                temperature=ExtractedTemperature(description="sitting out"),
                duration=ExtractedDuration(description="a while"),
                is_storage_scenario=True,
            )
        )

        result = await orchestrator.translate(
            "Cooked rice was sitting out for a while. Predict Bacillus cereus growth."
        )

        assert result.success is True, f"Failed with error: {result.error}"
        assert result.metadata is not None

        from app.api.routes.translation import _build_field_audit

        field_audit = _build_field_audit(result)

        # water_activity must appear — either from RAG or from conservative default
        assert (
            "water_activity" in field_audit
        ), "water_activity must be present in field_audit whether grounded or defaulted"

        aw_entry = field_audit["water_activity"]
        aw_used = result.state.execution_payload.parameters.water_activity
        assert aw_entry.final_value == pytest.approx(aw_used)

        # temperature_celsius: inferred via rule → extraction block must be populated
        assert "temperature_celsius" in field_audit
        temp_entry = field_audit["temperature_celsius"]
        if temp_entry.extraction is not None:
            assert temp_entry.extraction.method in (
                "rule_match",
                "embedding_fallback",
                None,
            )
            if temp_entry.extraction.method in ("rule_match", "embedding_fallback"):
                assert temp_entry.extraction.matched_pattern is not None
                assert isinstance(temp_entry.extraction.conservative, bool)


class TestRangeClampingEndToEnd:
    """
    End-to-end tests for B.1: values outside the model's valid range are
    clamped, and the three audit signals (RangeClamp record, per-field
    standardization block, warning string) are all populated.
    """

    @pytest.mark.asyncio
    async def test_T8_ecoli_50c_temperature_clamped_to_42(
        self, orchestrator, mock_semantic_parser, combase_engine
    ):
        """
        T8: E. coli growth model has temp max 42°C.
        Input 50°C must be clamped to 42°C.
        Verify: payload temp == 42, range_clamps populated, field_audit.standardization,
        and a warning string is emitted.
        """
        model = combase_engine.registry.get_model(
            ComBaseOrganism.ESCHERICHIA_COLI,
            ModelType.GROWTH,
        )
        if model is None:
            pytest.skip("E. coli growth model not available")

        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=create_scenario(
                food_description="milk",
                pathogen_mentioned="E. coli",
                temperature=ExtractedTemperature(value_celsius=50.0),
                duration=ExtractedDuration(value_minutes=360.0),
                is_storage_scenario=True,
            )
        )

        result = await orchestrator.translate(
            "Predict E. coli growth on milk at 50°C for 6 hours."
        )

        assert result.success is True, f"Failed with error: {result.error}"
        assert result.metadata is not None

        # Payload temperature must be clamped
        temp_used = result.state.execution_payload.parameters.temperature_celsius
        assert temp_used == pytest.approx(
            model.constraints.temp_max
        ), f"Expected temperature clamped to {model.constraints.temp_max}°C, got {temp_used}"

        # Structured RangeClamp in metadata
        temp_clamps = [
            c
            for c in result.metadata.range_clamps
            if c.field_name == "temperature_celsius"
        ]
        assert len(temp_clamps) == 1
        clamp = temp_clamps[0]
        assert clamp.original_value == pytest.approx(50.0)
        assert clamp.clamped_value == pytest.approx(model.constraints.temp_max)

        # Warning string
        assert any(
            "50" in w and str(int(model.constraints.temp_max)) in w
            for w in result.metadata.warnings
        ), f"Expected clamping warning; got: {result.metadata.warnings}"

        # field_audit.temperature_celsius.standardization.rule == "range_clamp"
        from app.api.routes.translation import _build_field_audit

        field_audit = _build_field_audit(result)
        assert "temperature_celsius" in field_audit
        std = field_audit["temperature_celsius"].standardization
        assert std is not None
        assert std.rule == "range_clamp"
        assert std.before_value == pytest.approx(50.0)
        assert std.after_value == pytest.approx(model.constraints.temp_max)

    @pytest.mark.asyncio
    async def test_T8_range_clamps_in_audit_summary(
        self, orchestrator, mock_semantic_parser, combase_engine
    ):
        """
        T8: audit.audit.range_clamps must contain a structured RangeClampInfo,
        not a plain string.
        """
        model = combase_engine.registry.get_model(
            ComBaseOrganism.ESCHERICHIA_COLI,
            ModelType.GROWTH,
        )
        if model is None:
            pytest.skip("E. coli growth model not available")

        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=create_scenario(
                food_description="milk",
                pathogen_mentioned="E. coli",
                temperature=ExtractedTemperature(value_celsius=50.0),
                duration=ExtractedDuration(value_minutes=360.0),
                is_storage_scenario=True,
            )
        )

        result = await orchestrator.translate(
            "Predict E. coli growth on milk at 50°C for 6 hours."
        )
        assert result.success is True

        from app.api.routes.translation import _build_audit_detail, _build_field_audit

        field_audit = _build_field_audit(result)
        audit_detail = _build_audit_detail(result, field_audit)

        assert len(audit_detail.audit.range_clamps) >= 1
        rc = audit_detail.audit.range_clamps[0]
        # Structured fields (not a plain string)
        assert rc.field_name == "temperature_celsius"
        assert rc.original_value == pytest.approx(50.0)
        assert rc.clamped_value == pytest.approx(model.constraints.temp_max)
        assert rc.valid_min == pytest.approx(model.constraints.temp_min)
        assert rc.valid_max == pytest.approx(model.constraints.temp_max)


class TestDefaultOrganismFieldAudit:
    """
    B.2: Pathogen is a required field. When no pathogen is named and neither RAG
    nor the category-level fallback can ground one, the pipeline never defaults
    or substitutes an organism — but it no longer always dead-ends either.

    The category-level fallback successfully grounds organisms for most common
    foods (chicken → poultry → Salmonella, rice → grain → Salmonella).  To test
    the true "nothing grounds" path, we use a food that the fallback cannot
    resolve: "frobnitz" (bridge returns None — FOOD_UNRECOGNISED) and "mustard"
    (bridge → condiment, no IFT mapping — CATEGORY_HAS_NO_HAZARD_DATA).

    As of A1a, both of those stages are clarifiable: since the reason organism
    grounding failed is one a question can resolve, the pipeline asks instead
    of dead-ending — success=False either way (status is never COMPLETED), but
    status is AWAITING_CLARIFICATION with a free-text question (2026-08-19:
    no options menu — see specs/lessons.md), not FAILED. See
    TestShigellaExecutability for a missing_required organism case that
    remains an unchanged hard failure (organism grounded but not executable —
    a question can't fix that).
    """

    @pytest.mark.asyncio
    async def test_missing_pathogen_produces_failure(
        self, orchestrator, mock_semantic_parser
    ):
        """
        Truly unresolvable food with no pathogen_mentioned must yield
        success=False, field_audit["organism"].source == "missing", and (since
        FOOD_UNRECOGNISED is clarifiable) AWAITING_CLARIFICATION with a
        question naming the unrecognised food and a derived organism option
        set — not a dead-end FAILED status.

        Uses "frobnitz" — TaxonomyBridge returns None (no FoodEx2 match), so
        the category fallback returns immediately without grounding organism.
        """
        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=create_scenario(
                food_description="frobnitz",
                pathogen_mentioned=None,
                temperature=ExtractedTemperature(value_celsius=25.0),
                duration=ExtractedDuration(value_minutes=240.0),
                is_storage_scenario=True,
            )
        )

        result = await orchestrator.translate(
            "How long before frobnitz left out at 25°C becomes unsafe?"
        )

        assert result.success is False
        assert result.state.status == SessionStatus.AWAITING_CLARIFICATION

        from app.api.routes.translation import _build_field_audit

        field_audit = _build_field_audit(result)

        assert (
            "organism" in field_audit
        ), "organism must appear in field_audit as a missing required field"
        org_entry = field_audit["organism"]
        assert org_entry.source == "missing"

        question = result.state.clarification_question
        assert question is not None
        assert question.stage == OrganismGroundingFailureStage.FOOD_UNRECOGNISED
        assert "frobnitz" in question.question
        # Free-text only: no options menu, just prose pathogen examples.
        assert not hasattr(question, "options")
        assert "Salmonella" in question.question

        # Recorded to metadata.clarifications for audit traceability.
        assert result.metadata is not None
        assert len(result.metadata.clarifications) == 1
        record = result.metadata.clarifications[0]
        assert record.turn_number == 1
        assert record.user_response is None
        assert record.question_asked == question.question

    @pytest.mark.asyncio
    async def test_missing_pathogen_no_salmonella_in_defaults_imputed(
        self, orchestrator, mock_semantic_parser
    ):
        """
        When pathogen is missing AND unresolvable, defaults_imputed must NOT
        contain a Salmonella entry — the silent default was removed — and,
        since CATEGORY_HAS_NO_HAZARD_DATA is clarifiable, the pipeline asks a
        question naming the resolved category ("condiment") and the source's
        coverage limit instead of dead-ending.

        Uses "mustard" — bridge resolves to condiment, which has no IFT-2003-T1
        row, so the category fallback returns without grounding organism.
        """
        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=create_scenario(
                food_description="mustard",
                pathogen_mentioned=None,
                temperature=ExtractedTemperature(value_celsius=25.0),
                duration=ExtractedDuration(value_minutes=240.0),
                is_storage_scenario=True,
            )
        )

        result = await orchestrator.translate(
            "Is mustard left out at 25°C for 4 hours safe?"
        )

        assert result.success is False
        assert result.state.status == SessionStatus.AWAITING_CLARIFICATION

        org_defaults = [
            d
            for d in (result.metadata.defaults_imputed if result.metadata else [])
            if d.field_name == "organism"
        ]
        assert org_defaults == []

        question = result.state.clarification_question
        assert question is not None
        assert (
            question.stage == OrganismGroundingFailureStage.CATEGORY_HAS_NO_HAZARD_DATA
        )
        assert "mustard" in question.question
        assert "condiment" in question.question
        assert "IFT-2003-T1" in question.question


class TestClarificationReEntry:
    """
    Free-text organism clarification (2026-08-19, see specs/lessons.md): the
    round-1 organism clarification gate is followed by a round-2 request
    carrying a ClarificationTranscript, resolving to a full prediction, a
    fail-closed refusal, or (never) a second question. The reply is free
    text, resolved deterministically (ComBaseOrganism.all_matches_in_text())
    -- no LLM call, no options menu, no offered-set gate. This replaced the
    old LLM-extraction round trip, which was confirmed to fail extraction on
    a clean, unambiguous answer ("Salmonellae") ~50% of the time across
    identical runs.

    PTM is stateless, so round 2 reprocesses "frobnitz left out for 3 hours"
    from scratch via the same mocked extract_scenario — round 1's real
    question is captured and echoed back on the transcript, exactly as a
    real stateless client would.
    """

    QUERY = "How long before frobnitz left out at 25°C becomes unsafe?"

    @staticmethod
    def _scenario():
        return create_scenario(
            food_description="frobnitz",
            pathogen_mentioned=None,
            temperature=ExtractedTemperature(value_celsius=25.0),
            duration=ExtractedDuration(value_minutes=240.0),
            is_storage_scenario=True,
        )

    async def _ask(self, orchestrator, mock_semantic_parser):
        """Round 1: get the real question for this query."""
        mock_semantic_parser.extract_scenario = AsyncMock(return_value=self._scenario())
        result = await orchestrator.translate(self.QUERY)
        assert result.state.status == SessionStatus.AWAITING_CLARIFICATION
        question = result.state.clarification_question
        assert question is not None
        return question

    def _transcript(self, question, user_reply: str) -> ClarificationTranscript:
        return ClarificationTranscript(
            original_query=self.QUERY,
            question_asked=question.question,
            user_reply=user_reply,
        )

    @pytest.mark.asyncio
    async def test_named_organism_completes_prediction(
        self, orchestrator, mock_semantic_parser
    ):
        """Free-text reply naming an executable organism -> full prediction,
        source: clarification_response, final_value = the organism actually
        executed. Uses "Salmonellae" -- the exact input confirmed live to be
        nondeterministic under the old LLM-extraction path."""
        question = await self._ask(orchestrator, mock_semantic_parser)

        mock_semantic_parser.extract_scenario = AsyncMock(return_value=self._scenario())

        result = await orchestrator.translate(
            self.QUERY,
            transcript=self._transcript(question, "Salmonellae"),
        )

        assert result.success is True, f"Failed with error: {result.error}"
        assert result.state.status == SessionStatus.COMPLETED
        assert result.execution_result is not None

        from app.api.routes.translation import _build_field_audit

        field_audit = _build_field_audit(result)
        assert field_audit["organism"].source == "clarification_response"

        # A resolved-and-executed request must not carry a stale "required
        # value missing" warning from before the transcript resolved it.
        assert not any(
            "required value missing" in w for w in result.metadata.warnings
        ), result.metadata.warnings

        # Exactly one ClarificationRecord for the whole exchange, not two.
        assert len(result.metadata.clarifications) == 1
        record = result.metadata.clarifications[0]
        assert record.turn_number == 1
        assert record.user_response == "Salmonellae"
        assert record.extracted_value == ComBaseOrganism.SALMONELLA.value

    @pytest.mark.asyncio
    async def test_named_organism_resolves_deterministically_across_runs(
        self, orchestrator, mock_semantic_parser
    ):
        """The flakiness that motivated this redesign, made explicit: the
        same reply resolves to the same organism every time, not ~50% of
        the time (the confirmed failure rate of the old LLM-extraction
        path)."""
        question = await self._ask(orchestrator, mock_semantic_parser)
        mock_semantic_parser.extract_scenario = AsyncMock(return_value=self._scenario())

        for _ in range(6):
            result = await orchestrator.translate(
                self.QUERY,
                transcript=self._transcript(question, "Salmonellae"),
            )
            assert result.success is True, f"Failed with error: {result.error}"

            from app.api.routes.translation import _build_field_audit

            field_audit = _build_field_audit(result)
            assert "salmonella" in field_audit["organism"].final_value.lower()

    @pytest.mark.asyncio
    async def test_organism_outside_old_top5_menu_completes_prediction(
        self, orchestrator, mock_semantic_parser
    ):
        """A free-text reply naming an executable organism that would not
        have been in the old top-5-by-CDC-deaths menu still resolves and
        predicts -- there is no menu to be excluded from anymore."""
        question = await self._ask(orchestrator, mock_semantic_parser)
        mock_semantic_parser.extract_scenario = AsyncMock(return_value=self._scenario())

        result = await orchestrator.translate(
            self.QUERY,
            transcript=self._transcript(question, "Staphylococcus aureus"),
        )

        assert result.success is True, f"Failed with error: {result.error}"
        assert result.state.status == SessionStatus.COMPLETED
        assert result.execution_result is not None

        from app.api.routes.translation import _build_field_audit

        field_audit = _build_field_audit(result)
        assert "staphylococcus" in field_audit["organism"].final_value.lower()

    @pytest.mark.asyncio
    async def test_skip_fails_closed_no_default(
        self, orchestrator, mock_semantic_parser
    ):
        """A reply that names no pathogen -> fail closed, plain language, no
        organism default. There is no separate wants_to_skip flag anymore --
        this is just the empty-match case, since there's no LLM to produce
        such a flag."""
        question = await self._ask(orchestrator, mock_semantic_parser)
        mock_semantic_parser.extract_scenario = AsyncMock(return_value=self._scenario())

        result = await orchestrator.translate(
            self.QUERY,
            transcript=self._transcript(question, "I don't know, just use a default"),
        )

        assert result.success is False
        assert result.state.status == SessionStatus.FAILED
        assert result.error is not None
        assert "didn't name a pathogen" in result.error.lower()

        org_defaults = [
            d
            for d in (result.metadata.defaults_imputed if result.metadata else [])
            if d.field_name == "organism"
        ]
        assert org_defaults == []

    @pytest.mark.asyncio
    async def test_non_executable_organism_fails_closed_not_substituted(
        self, orchestrator, mock_semantic_parser
    ):
        """Reply names a real, unambiguous organism (Shigella flexneri) that
        isn't executable for this growth scenario (no plain-growth row in
        data/combase_models.csv) -> fail closed, not silently substituted.
        There is no offered-set to check anymore -- executability is the
        actual safety boundary."""
        question = await self._ask(orchestrator, mock_semantic_parser)
        mock_semantic_parser.extract_scenario = AsyncMock(return_value=self._scenario())

        result = await orchestrator.translate(
            self.QUERY,
            transcript=self._transcript(question, "It's Shigella"),
        )

        assert result.success is False
        assert result.state.status == SessionStatus.FAILED
        assert result.error is not None
        assert "shigella" in result.error.lower()
        assert "not supported for" in result.error.lower()

    @pytest.mark.asyncio
    async def test_unmappable_reply_fails_closed(
        self, orchestrator, mock_semantic_parser
    ):
        """Reply that can't be mapped to any organism at all -> fail closed."""
        question = await self._ask(orchestrator, mock_semantic_parser)
        mock_semantic_parser.extract_scenario = AsyncMock(return_value=self._scenario())

        result = await orchestrator.translate(
            self.QUERY,
            transcript=self._transcript(question, "Something else / I'm not sure"),
        )

        assert result.success is False
        assert result.state.status == SessionStatus.FAILED
        assert result.error is not None
        assert "didn't name a pathogen" in result.error.lower()

    @pytest.mark.asyncio
    async def test_ambiguous_multi_organism_reply_fails_closed(
        self, orchestrator, mock_semantic_parser
    ):
        """Reply naming more than one organism -> ambiguous, fail closed
        rather than resolved to an arbitrary one of them."""
        question = await self._ask(orchestrator, mock_semantic_parser)
        mock_semantic_parser.extract_scenario = AsyncMock(return_value=self._scenario())

        result = await orchestrator.translate(
            self.QUERY,
            transcript=self._transcript(question, "Salmonella or Listeria, not sure"),
        )

        assert result.success is False
        assert result.state.status == SessionStatus.FAILED
        assert result.error is not None
        assert "more than one" in result.error.lower()

    @pytest.mark.asyncio
    async def test_transcript_present_still_fails_no_second_question(
        self, orchestrator, mock_semantic_parser
    ):
        """One round only: if resolution fails, status must be FAILED, never
        AWAITING_CLARIFICATION again — no second question."""
        question = await self._ask(orchestrator, mock_semantic_parser)
        mock_semantic_parser.extract_scenario = AsyncMock(return_value=self._scenario())

        result = await orchestrator.translate(
            self.QUERY,
            transcript=self._transcript(question, "I don't know"),
        )

        assert result.state.status != SessionStatus.AWAITING_CLARIFICATION
        assert result.state.status == SessionStatus.FAILED
        assert result.state.clarification_question is None


class TestCategoryPathogenFallbackWarningPropagation:
    """B.4: Transparency warning from category-level pathogen fallback must reach metadata.warnings.

    The orchestrator propagates grounded.warnings → state.metadata.warnings.
    This test verifies the full propagation chain for a food whose organism is
    resolved via the category fallback (frobnitz-adjacent: barley, which maps
    grain → cereal grains → Salmonella).
    """

    @pytest.mark.asyncio
    async def test_category_fallback_warning_in_metadata_warnings(
        self, orchestrator, mock_semantic_parser
    ):
        """When the category fallback grounds organism, a transparency warning must appear
        in result.metadata.warnings (not just grounded.warnings, which is internal)."""
        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=create_scenario(
                food_description="barley grain",
                pathogen_mentioned=None,
                temperature=ExtractedTemperature(value_celsius=25.0),
                duration=ExtractedDuration(value_minutes=240.0),
                is_storage_scenario=True,
            )
        )

        result = await orchestrator.translate(
            "How safe is barley grain left out at 25°C for 4 hours?"
        )

        assert result.success is True
        assert result.metadata is not None
        fallback_warnings = [w for w in result.metadata.warnings if "IFT-2003-T1" in w]
        assert len(fallback_warnings) >= 1, (
            "Category fallback transparency warning must propagate from grounded.warnings "
            "to result.metadata.warnings via the orchestrator"
        )


class TestQualifierStrippingEndToEnd:
    """B.5: Qualifier-stripped food descriptions must resolve via the category-level pathogen fallback.

    The semantic parser now instructs the LLM to strip leading quantity/container qualifiers.
    This test simulates the corrected parser output ("ham") for the canonical problem query
    ("a large batch of ham") and verifies the full downstream chain:
      ham → bridge(meat) → meats and poultry → Salmonella (238 deaths) → success=True
    """

    @pytest.mark.asyncio
    async def test_large_batch_of_ham_category_fallback(
        self, orchestrator, mock_semantic_parser
    ):
        """'a large batch of ham' stripped to 'ham' → category fallback → success."""
        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=create_scenario(
                food_description="ham",  # simulates qualifier-stripped parser output
                pathogen_mentioned=None,
                temperature=ExtractedTemperature(value_celsius=25.0),
                duration=ExtractedDuration(value_minutes=240.0),
                is_storage_scenario=True,
            )
        )

        result = await orchestrator.translate(
            "What happens to a large batch of ham left to cool at room temperature?"
        )

        # food_description in extracted scenario
        assert mock_semantic_parser.extract_scenario.call_count >= 1
        extracted = mock_semantic_parser.extract_scenario.return_value
        assert extracted.food_description == "ham"

        # full pipeline succeeds and organism grounded via category fallback
        assert result.success is True

        from app.api.routes.translation import _build_field_audit

        field_audit = _build_field_audit(result)
        assert "organism" in field_audit
        assert field_audit["organism"].source == "rag_pathogen_category_fallback"


class TestThermalInactivationEndToEnd:
    """
    B.3: Thermal inactivation queries must succeed and use lower range bounds.

    The intent-classification prompt fix (B.3) is validated separately via the
    live LLM; these tests confirm the pipeline works end-to-end for
    THERMAL_INACTIVATION once intent routing is correct (mocked as prediction_request).
    """

    @pytest.mark.asyncio
    async def test_T7_thermal_inactivation_succeeds(
        self, orchestrator, mock_semantic_parser, combase_engine
    ):
        """
        T7: Salmonella thermal inactivation at 65°C for 10 min must succeed
        and return a meaningful (negative log) prediction.
        """
        model = combase_engine.registry.get_model(
            ComBaseOrganism.SALMONELLA,
            ModelType.THERMAL_INACTIVATION,
        )
        if model is None:
            pytest.skip("Salmonella thermal inactivation model not available")

        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=create_scenario(
                food_description="chicken",
                pathogen_mentioned="Salmonella",
                temperature=ExtractedTemperature(value_celsius=65.0),
                duration=ExtractedDuration(value_minutes=10.0),
                is_cooking_scenario=True,
                implied_model_type=ModelType.THERMAL_INACTIVATION,
            )
        )

        result = await orchestrator.translate(
            "Calculate Salmonella thermal inactivation in chicken at 65°C for 10 minutes.",
            model_type=ModelType.THERMAL_INACTIVATION,
        )

        assert result.success is True, f"Failed with error: {result.error}"
        assert (
            result.state.execution_payload.model_selection.model_type
            == ModelType.THERMAL_INACTIVATION
        )
        assert result.execution_result is not None
        # Thermal inactivation produces a negative log change (pathogen death)
        assert result.execution_result.total_log_increase < 0

    @pytest.mark.asyncio
    async def test_thermal_inactivation_range_direction_is_lower(
        self, orchestrator, mock_semantic_parser, combase_engine
    ):
        """
        For THERMAL_INACTIVATION, ranged RAG values must be resolved to their
        LOWER bound (less kill = more conservative).

        The test vector store has "Raw chicken has pH between 5.9 and 6.2".
        For inactivation, lower pH (5.9) must be selected.
        """
        model = combase_engine.registry.get_model(
            ComBaseOrganism.SALMONELLA,
            ModelType.THERMAL_INACTIVATION,
        )
        if model is None:
            pytest.skip("Salmonella thermal inactivation model not available")

        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=create_scenario(
                food_description="raw chicken",
                pathogen_mentioned="Salmonella",
                temperature=ExtractedTemperature(value_celsius=65.0),
                duration=ExtractedDuration(value_minutes=10.0),
                is_cooking_scenario=True,
                implied_model_type=ModelType.THERMAL_INACTIVATION,
            )
        )

        result = await orchestrator.translate(
            "Predict Salmonella thermal inactivation in chicken at 65°C for 10 minutes.",
            model_type=ModelType.THERMAL_INACTIVATION,
        )

        assert result.success is True, f"Failed with error: {result.error}"
        assert result.metadata is not None

        from app.api.routes.translation import _build_field_audit

        field_audit = _build_field_audit(result)

        # If pH was retrieved as a range, the standardization block must show "lower"
        if "ph" in field_audit:
            ph_entry = field_audit["ph"]
            if (
                ph_entry.standardization is not None
                and ph_entry.standardization.rule == "range_bound_selection"
            ):
                assert ph_entry.standardization.direction == "lower", (
                    f"Expected lower bound for thermal inactivation pH; "
                    f"got direction={ph_entry.standardization.direction}"
                )


class TestValidationFailureAudit:
    """
    Integration tests: field_audit completeness when standardization fails
    with missing required values (A2-style multi-step query).

    Uses the full pipeline with real grounding and standardization; only the
    LLM is mocked to control what the semantic parser extracts.
    """

    def _make_a2_scenario(self) -> ExtractedScenario:
        """
        Minimal A2-style scenario: 2-step, step 1 has a resolvable temperature
        but no duration, step 2 is complete.  Standardization will fail with
        "duration (step 1)" in missing_required.
        """
        return ExtractedScenario(
            food_description="ground beef",
            food_state="raw",
            pathogen_mentioned="Salmonella",
            is_multi_step=True,
            single_step_temperature=ExtractedTemperature(),
            single_step_duration=ExtractedDuration(),
            time_temperature_steps=[
                ExtractedTimeTemperatureStep(
                    description="transport from supermarket",
                    temperature=ExtractedTemperature(description="room temperature"),
                    duration=ExtractedDuration(),  # no value, no description — will fail
                    sequence_order=1,
                ),
                ExtractedTimeTemperatureStep(
                    description="home refrigerator storage",
                    temperature=ExtractedTemperature(description="refrigerated"),
                    duration=ExtractedDuration(value_minutes=1440.0),
                    sequence_order=2,
                ),
            ],
            environmental_conditions=ExtractedEnvironmentalConditions(),
            concern_type="safety",
            is_storage_scenario=True,
        )

    @pytest.mark.asyncio
    async def test_missing_duration_routes_to_duration_gate_not_hard_failure(
        self, orchestrator, mock_semantic_parser
    ):
        """2026-08-17: this A2-style query's missing step-1 duration is now
        answerable via the duration clarification gate (AWAITING_CLARIFICATION),
        not a hard failure -- error stays None, same as the organism gate's
        own convention (state.set_error() is not called for a clarification).
        Previously this asserted result.error named "duration"; that error
        string no longer exists for this scenario since it no longer fails."""
        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=self._make_a2_scenario()
        )
        result = await orchestrator.translate(
            "For the exposure assessment, we need to estimate Salmonella growth on ground beef "
            "from purchase to cooking. Model the growth during the transport and home storage "
            "segments separately."
        )
        assert result.success is False
        assert result.state.status == SessionStatus.AWAITING_CLARIFICATION
        assert result.error is None
        question = result.state.duration_clarification_question
        assert question is not None
        assert [s.step_order for s in question.steps] == [1]

    @pytest.mark.asyncio
    async def test_organism_in_field_audit(self, orchestrator, mock_semantic_parser):
        from app.api.routes.translation import _build_field_audit

        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=self._make_a2_scenario()
        )
        result = await orchestrator.translate("A2-style ground beef multi-step query")
        field_audit = _build_field_audit(result)
        assert "organism" in field_audit
        assert field_audit["organism"].final_value is not None

    @pytest.mark.asyncio
    async def test_step_temperature_in_field_audit(
        self, orchestrator, mock_semantic_parser
    ):
        """Step 1 temperature resolved via rule → must appear with a non-null final_value."""
        from app.api.routes.translation import _build_field_audit

        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=self._make_a2_scenario()
        )
        result = await orchestrator.translate("A2-style ground beef multi-step query")
        field_audit = _build_field_audit(result)
        assert "temperature_celsius (step 1)" in field_audit
        assert field_audit["temperature_celsius (step 1)"].final_value is not None

    @pytest.mark.asyncio
    async def test_missing_duration_in_field_audit_with_null_value(
        self, orchestrator, mock_semantic_parser
    ):
        """Step 1 duration was not provided → must appear with final_value=null and source=missing."""
        from app.api.routes.translation import _build_field_audit

        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=self._make_a2_scenario()
        )
        result = await orchestrator.translate("A2-style ground beef multi-step query")
        field_audit = _build_field_audit(result)
        assert "duration_minutes (step 1)" in field_audit
        entry = field_audit["duration_minutes (step 1)"]
        assert entry.final_value is None
        assert entry.source == ValueSource.MISSING.value

    @pytest.mark.asyncio
    async def test_defaults_imputed_appear_in_audit_summary(
        self, orchestrator, mock_semantic_parser
    ):
        """
        ph and water_activity must appear in the audit even on failure.
        They may be grounded from RAG (field_audit) or defaulted (defaults_imputed)
        depending on what the test vector store contains for the food.
        Either channel is acceptable — the invariant is that they are not silently absent.
        """
        from app.api.routes.translation import _build_audit_detail, _build_field_audit

        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=self._make_a2_scenario()
        )
        result = await orchestrator.translate("A2-style ground beef multi-step query")
        field_audit = _build_field_audit(result)
        audit = _build_audit_detail(result, field_audit)
        all_resolved_fields = set(field_audit.keys()) | {
            d.field_name for d in audit.audit.defaults_imputed
        }
        assert "ph" in all_resolved_fields
        assert "water_activity" in all_resolved_fields

    @pytest.mark.asyncio
    async def test_structured_warning_in_audit(
        self, orchestrator, mock_semantic_parser
    ):
        """audit.audit.warnings must contain a message naming the missing field."""
        from app.api.routes.translation import _build_audit_detail, _build_field_audit

        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=self._make_a2_scenario()
        )
        result = await orchestrator.translate("A2-style ground beef multi-step query")
        field_audit = _build_field_audit(result)
        audit = _build_audit_detail(result, field_audit)
        warning_text = " ".join(audit.audit.warnings)
        assert "Validation failed" in warning_text
        assert "duration" in warning_text

    @pytest.mark.asyncio
    async def test_prediction_is_null(self, orchestrator, mock_semantic_parser):
        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=self._make_a2_scenario()
        )
        result = await orchestrator.translate("A2-style ground beef multi-step query")
        assert result.execution_result is None

    @pytest.mark.live
    @pytest.mark.asyncio
    async def test_a2_verbatim_live(self, orchestrator):
        """
        Runs the A2 query verbatim with a real LLM.  The LLM may or may not
        extract durations for both steps; the test asserts that whatever the
        outcome, field_audit is never empty and the failure path (if taken)
        still produces a useful audit with at least organism and ph entries.

        Marked @pytest.mark.live — excluded from standard pytest run.
        Run with: pytest -m live tests/integration/test_full_pipeline.py::TestValidationFailureAudit::test_a2_verbatim_live
        """
        from app.api.routes.translation import _build_field_audit
        from app.services.extraction.semantic_parser import get_semantic_parser

        # Swap in the real parser for this test
        real_orchestrator = Orchestrator(
            session_manager=orchestrator._sessions,
            semantic_parser=get_semantic_parser(),
            grounding_service=orchestrator._grounder,
            standardization_service=orchestrator._standardizer,
            combase_engine=orchestrator._engine,
        )

        result = await real_orchestrator.translate(
            "For the exposure assessment, we need to estimate Salmonella growth on ground beef "
            "from purchase to cooking. The consumer picks it up at the supermarket, drives home "
            "— assume a typical shopping trip — and stores it in the home refrigerator. "
            "Model the growth during the transport and home storage segments separately."
        )

        field_audit = _build_field_audit(result)
        assert (
            len(field_audit) > 0
        ), "field_audit must never be empty regardless of success/failure"
        assert (
            "organism" in field_audit
        ), "organism must always be present in field_audit"
        # On failure: error must name the missing field
        if not result.success:
            assert result.error is not None
            assert result.metadata is not None
            warning_text = " ".join(result.metadata.warnings)
            assert "Validation failed" in warning_text


class TestTemperatureExtractionShape:
    """
    Set A — prompt extraction shape (live LLM, @pytest.mark.live).

    Verifies that the temperature guard section in SCENARIO_EXTRACTION_PROMPT
    produces the correct (value_celsius, description) shape for each worked example.
    Uses the semantic parser directly — no orchestrator needed.

    Run with: pytest -m live tests/integration/test_full_pipeline.py::TestTemperatureExtractionShape
    """

    @pytest.mark.live
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "phrase,expected_celsius,desc_contains",
        [
            # Explicit numeric — value_celsius populated, description null or carries qualifier
            ("4°C", 4.0, None),
            ("around 4°C", 4.0, "4"),
            ("72°F", pytest.approx(22.2, abs=0.5), "72"),
            ("refrigerator set to 38°F", pytest.approx(3.3, abs=0.5), "38"),
            # Descriptive — value_celsius null, description carries original phrase verbatim
            ("home refrigerator", None, "home refrigerator"),
            ("domestic refrigerator", None, "domestic refrigerator"),
            ("household freezer", None, "household freezer"),
            ("typical retail refrigeration", None, "typical retail refrigeration"),
            ("room temperature", None, "room temperature"),
            ("stored cold", None, "stored cold"),
            ("ambient", None, "ambient"),
        ],
    )
    async def test_extraction_shape(self, phrase, expected_celsius, desc_contains):
        """
        Live extractor must produce the documented (value_celsius, description) shape.

        Tolerance on Fahrenheit conversions is abs=0.5 — LLM rounding on conversions
        is not what this workstream is testing; the direction matters, not the precision.
        """
        from app.services.extraction.semantic_parser import get_semantic_parser

        parser = get_semantic_parser()
        query = f"Ground beef stored at {phrase} for 4 hours"
        scenario = await parser.extract_scenario(query)
        temp = scenario.single_step_temperature

        if expected_celsius is None:
            assert temp.value_celsius is None, (
                f"'{phrase}': expected value_celsius=null but got {temp.value_celsius}. "
                f"LLM applied world-knowledge inference despite prompt guard."
            )
        else:
            assert (
                temp.value_celsius == expected_celsius
            ), f"'{phrase}': expected value_celsius≈{expected_celsius} but got {temp.value_celsius}"

        if desc_contains is None:
            # Pure numeric — no descriptive qualifier, description may be null
            pass  # Not asserting on description for plain "4°C"
        else:
            assert (
                temp.description is not None
            ), f"'{phrase}': expected description to contain '{desc_contains}' but description=null"
            assert desc_contains.lower() in temp.description.lower(), (
                f"'{phrase}': description '{temp.description}' does not contain '{desc_contains}'. "
                f"LLM paraphrased instead of preserving original phrasing."
            )


class TestVagueTemperatureAuditShapes:
    """
    Set C — end-to-end audit shape (live LLM, @pytest.mark.live).

    Verifies that the full pipeline (prompt guard + rule library) produces
    the correct temperature audit shape for the five target queries.

    Shipping threshold: all 5 must produce the correct audit shape on 3 consecutive runs.
    If 'method=llm_extraction' appears where 'rule_match' is expected, the prompt guard
    is insufficient on that run and a grounding-precedence override should be reconsidered.

    Run with: pytest -m live tests/integration/test_full_pipeline.py::TestVagueTemperatureAuditShapes
    """

    def _make_live_orchestrator(self, orchestrator):
        """Swap in the real semantic parser, keep all other components from the fixture."""
        from app.services.extraction.semantic_parser import get_semantic_parser

        return Orchestrator(
            session_manager=orchestrator._sessions,
            semantic_parser=get_semantic_parser(),
            grounding_service=orchestrator._grounder,
            standardization_service=orchestrator._standardizer,
            combase_engine=orchestrator._engine,
        )

    @pytest.mark.live
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "query,expected_source,expected_method",
        [
            (
                "Salmonella in ground beef stored in the home refrigerator for 4 hours",
                "user_inferred",
                "rule_match",
            ),
            (
                "L. monocytogenes in deli turkey under typical retail refrigeration for 35 days",
                "user_inferred",
                "rule_match",
            ),
            (
                "Ground beef stored cold for 2 hours",
                "user_inferred",
                "rule_match",
            ),
            (
                "Cheese in household freezer for 30 days",
                "user_inferred",
                "rule_match",
            ),
            (
                "Sauce held at 4°C for 6 hours",
                "user_explicit",
                "llm_extraction",
            ),
        ],
    )
    async def test_temperature_audit_shape(
        self, orchestrator, query, expected_source, expected_method
    ):
        """
        For each query, assert the temperature audit entry has the expected source and method.

        The numeric value is not asserted here — it is determined by the rule library and is
        unchanged from pre-workstream behaviour. Only the audit label matters.
        """
        from app.api.routes.translation import _build_field_audit

        live_orchestrator = self._make_live_orchestrator(orchestrator)
        result = await live_orchestrator.translate(query)

        field_audit = _build_field_audit(result)
        assert (
            "temperature_celsius" in field_audit
        ), f"temperature_celsius missing from field_audit for query: {query!r}"

        temp_entry = field_audit["temperature_celsius"]
        assert temp_entry.source == expected_source, (
            f"Expected source={expected_source!r} but got {temp_entry.source!r}\n"
            f"Query: {query!r}\n"
            f"If source='user_explicit', the prompt guard is not suppressing LLM world-knowledge "
            f"inference on this run."
        )
        assert (
            temp_entry.extraction is not None
        ), f"extraction block is null for query: {query!r}"
        assert temp_entry.extraction.method == expected_method, (
            f"Expected method={expected_method!r} but got {temp_entry.extraction.method!r}\n"
            f"Query: {query!r}"
        )


class TestShigellaExecutability:
    """A0.5b: sf (Shigella flexneri) has no (ModelID=1, Factor4=NONE) row -- the
    only organism with this gap. StandardizationService must fail closed before
    building a payload the engine cannot execute, with an error naming the
    organism and model type in plain language -- not the internal short codes
    that used to leak via engine.execute()'s ValueError("Model not found: sf /
    growth / none")."""

    @pytest.mark.asyncio
    async def test_shigella_plain_growth_fails_closed_with_human_readable_error(
        self, orchestrator, mock_semantic_parser
    ):
        """'shigella in my salad' (growth, no nitrite) -> success=false, error
        names Shigella and growth in plain language; no short-code string
        ("sf / growth / none") reaches the caller."""
        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=create_scenario(
                food_description="salad",
                pathogen_mentioned="Shigella",
                temperature=ExtractedTemperature(value_celsius=25.0),
                duration=ExtractedDuration(value_minutes=180.0),
                is_storage_scenario=True,
            )
        )

        result = await orchestrator.translate(
            "Shigella in my salad left out for 3 hours"
        )

        assert result.success is False
        assert result.error is not None
        assert "shigella" in result.error.lower(), result.error
        assert "growth" in result.error.lower(), result.error
        assert "sf / growth / none" not in result.error, result.error
        assert "sf /" not in result.error, result.error

    @pytest.mark.asyncio
    async def test_shigella_with_nitrite_executes_normally(
        self, orchestrator, mock_semantic_parser
    ):
        """sf + Factor4Type.NITRITE is executable and must keep working -- the
        executability check must use the actual factor4_type being built, not
        assume NONE."""
        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=create_scenario(
                food_description="cured meat",
                pathogen_mentioned="Shigella",
                temperature=ExtractedTemperature(value_celsius=25.0),
                duration=ExtractedDuration(value_minutes=180.0),
                environmental_conditions=ExtractedEnvironmentalConditions(
                    nitrite_ppm=100.0
                ),
                is_storage_scenario=True,
            )
        )

        # Explicit model_type=GROWTH: Shigella's only executable row is
        # (ModelID=1/GROWTH, Factor4=nitrite). _determine_model_type() would
        # reach GROWTH by default here anyway (no preservative-routing branch
        # exists as of 2026-07-16), but pinning it explicitly keeps this test's
        # intent -- "sf+nitrite executes" -- independent of that default branch.
        result = await orchestrator.translate(
            "Shigella on cured meat with 100ppm nitrite left out for 3 hours",
            model_type=ModelType.GROWTH,
        )

        assert result.success is True, f"Failed with error: {result.error}"
        assert result.execution_result is not None


class TestPreservativeRoutingRemoved:
    """2026-07-16: _determine_model_type() no longer routes preservative presence to
    NON_THERMAL_SURVIVAL. ComBase has zero Factor4 rows for ModelID 2/3 -- every
    organism was non-executable at NON_THERMAL_SURVIVAL with any preservative
    factor4, so the removed branch could only ever produce a refusal, converting
    answerable growth questions into "no model exists". See specs/lessons.md."""

    @pytest.mark.asyncio
    async def test_nitrite_with_no_implied_model_type_falls_through_to_growth(
        self, orchestrator, mock_semantic_parser
    ):
        """No LLM-inferred model type, no cooking/non-thermal scenario flag, no
        low pH/aw -- only nitrite_ppm set. Must fall through to the GROWTH default
        and produce a real prediction, not a refusal. Salmonella + nitrite + GROWTH
        is executable (3 organisms are, per the executable-organism matrix)."""
        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=create_scenario(
                food_description="cured meat",
                pathogen_mentioned="Salmonella",
                temperature=ExtractedTemperature(value_celsius=25.0),
                duration=ExtractedDuration(value_minutes=180.0),
                environmental_conditions=ExtractedEnvironmentalConditions(
                    nitrite_ppm=100.0
                ),
                is_storage_scenario=True,
                implied_model_type=None,
            )
        )

        result = await orchestrator.translate(
            "Salmonella on cured meat with 100ppm nitrite left out for 3 hours"
        )

        assert result.success is True, f"Failed with error: {result.error}"
        assert result.execution_result is not None
        assert result.metadata is not None
        assert result.metadata.combase_model is not None
        assert result.metadata.combase_model.model_type == "growth"
        assert result.metadata.combase_model.selection_reason == (
            "default (no thermal/non-thermal signals detected)"
        )

        # A1c: the fall-through must disclose itself as a guess via the plain
        # (non-verbose) response's warnings channel, not just the verbose-only
        # combase_model.selection_reason asserted above.
        assert any(
            "growth was assumed by default" in w for w in result.metadata.warnings
        ), f"No fall-through disclosure warning in metadata.warnings: {result.metadata.warnings}"

        from app.api.routes.translation import _build_warnings_list

        plain_warnings = _build_warnings_list(result)
        assert any(
            "growth was assumed by default" in w.message for w in plain_warnings
        ), f"Fall-through disclosure did not reach the plain-response warnings list: {plain_warnings}"


class TestModelTypeFallthroughDisclosure:
    """A1c: _determine_model_type()'s fall-through (orchestrator.py) has no
    conservative direction -- growth vs. inactivation is a binary choice about
    scenario kind, not a worst-case floor/ceiling. A wrong guess here is
    categorically wrong, not cautious, so it must be disclosed in the plain
    response -- but only on the true fall-through. If the warning fired on
    confident paths too, it would train users to ignore it (see prompt intent:
    "must distinguish a guess from a decision")."""

    _FALLTHROUGH_PHRASE = "growth was assumed by default"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "label,scenario_kwargs",
        [
            (
                "explicit_model_type_param",
                {
                    "food_description": "cured meat",
                    "pathogen_mentioned": "Salmonella",
                    "temperature": ExtractedTemperature(value_celsius=25.0),
                    "duration": ExtractedDuration(value_minutes=180.0),
                    "is_storage_scenario": True,
                },
            ),
            (
                "llm_inferred",
                {
                    "food_description": "raw chicken",
                    "pathogen_mentioned": "Salmonella",
                    "temperature": ExtractedTemperature(value_celsius=25.0),
                    "duration": ExtractedDuration(value_minutes=180.0),
                    "is_storage_scenario": True,
                    "implied_model_type": ModelType.GROWTH,
                },
            ),
            (
                "temperature_heuristic",
                {
                    "food_description": "raw chicken",
                    "pathogen_mentioned": "Salmonella",
                    "temperature": ExtractedTemperature(value_celsius=65.0),
                    "duration": ExtractedDuration(value_minutes=10.0),
                    "is_cooking_scenario": True,
                },
            ),
            (
                "cooking_flag",
                {
                    "food_description": "raw chicken",
                    "pathogen_mentioned": "Salmonella",
                    "temperature": ExtractedTemperature(value_celsius=25.0),
                    "duration": ExtractedDuration(value_minutes=10.0),
                    "is_cooking_scenario": True,
                },
            ),
            (
                "non_thermal_flag",
                {
                    "food_description": "pickled vegetables",
                    "pathogen_mentioned": "Salmonella",
                    "temperature": ExtractedTemperature(value_celsius=25.0),
                    "duration": ExtractedDuration(value_minutes=180.0),
                    "is_non_thermal_treatment": True,
                },
            ),
            (
                "low_ph_condition",
                {
                    "food_description": "pickled vegetables",
                    "pathogen_mentioned": "Salmonella",
                    "temperature": ExtractedTemperature(value_celsius=25.0),
                    "duration": ExtractedDuration(value_minutes=180.0),
                    "environmental_conditions": ExtractedEnvironmentalConditions(
                        ph_value=4.0
                    ),
                    "is_storage_scenario": True,
                },
            ),
            (
                "low_aw_condition",
                {
                    "food_description": "beef jerky",
                    "pathogen_mentioned": "Salmonella",
                    "temperature": ExtractedTemperature(value_celsius=25.0),
                    "duration": ExtractedDuration(value_minutes=180.0),
                    "environmental_conditions": ExtractedEnvironmentalConditions(
                        water_activity=0.80
                    ),
                    "is_storage_scenario": True,
                },
            ),
        ],
    )
    async def test_confident_model_type_paths_do_not_warn(
        self, orchestrator, mock_semantic_parser, label, scenario_kwargs
    ):
        """None of these branches is the fall-through -- each returns a
        selection_reason distinct from _MODEL_TYPE_FALLTHROUGH_REASON -- so
        none should emit the guess-disclosure warning."""
        mock_semantic_parser.extract_scenario = AsyncMock(
            return_value=create_scenario(**scenario_kwargs)
        )

        explicit_type = (
            ModelType.GROWTH if label == "explicit_model_type_param" else None
        )
        result = await orchestrator.translate(
            f"Test query for {label}", model_type=explicit_type
        )

        assert result.metadata is not None
        assert not any(
            self._FALLTHROUGH_PHRASE in w for w in result.metadata.warnings
        ), (
            f"Confident path {label!r} incorrectly emitted the fall-through "
            f"disclosure warning: {result.metadata.warnings}"
        )


class TestDurationClarificationGate:
    """
    2026-08-17: multi-step duration clarification gate -- the duration-gate
    analogue of TestClarificationReEntry (organism). Round 1 asks about every
    step with an unresolvable duration (2a: the profile-builder loop runs to
    completion, so the question can name all of them in one round, not just
    the first). Round 2 answers with a structured numeric {step_order, hours}
    reply per step -- validated structurally and applied verbatim. Organism's
    reply is free text resolved by a deterministic alias matcher (2026-08-19,
    see specs/lessons.md); duration's is a plain number with no matching step
    at all -- the two gates are still safe for different reasons, not
    variants of one mechanism (§8.16).
    """

    QUERY = "Chicken transported then stored, two stages"

    @staticmethod
    def _scenario() -> ExtractedScenario:
        return ExtractedScenario(
            food_description="raw chicken",
            pathogen_mentioned="Salmonella",
            is_multi_step=True,
            single_step_temperature=ExtractedTemperature(),
            single_step_duration=ExtractedDuration(),
            time_temperature_steps=[
                ExtractedTimeTemperatureStep(
                    sequence_order=1,
                    temperature=ExtractedTemperature(value_celsius=25.0),
                    duration=ExtractedDuration(
                        description="xyz123"
                    ),  # unresolvable phrase -- quoted in the question
                ),
                ExtractedTimeTemperatureStep(
                    sequence_order=2,
                    temperature=ExtractedTemperature(value_celsius=4.0),
                    duration=ExtractedDuration(),  # no phrase at all
                ),
            ],
            environmental_conditions=ExtractedEnvironmentalConditions(),
            concern_type="safety",
            is_storage_scenario=True,
            implied_model_type=ModelType.GROWTH,
        )

    async def _ask(self, orchestrator, mock_semantic_parser):
        """Round 1: get the real duration clarification question."""
        mock_semantic_parser.extract_scenario = AsyncMock(return_value=self._scenario())
        result = await orchestrator.translate(self.QUERY)
        assert result.state.status == SessionStatus.AWAITING_CLARIFICATION
        question = result.state.duration_clarification_question
        assert question is not None
        return question

    def _reply(self, steps: list[tuple[int, float]]) -> DurationClarificationReply:
        return DurationClarificationReply(
            original_query=self.QUERY,
            steps=[
                DurationStepReply(step_order=order, hours=hours)
                for order, hours in steps
            ],
        )

    @pytest.mark.asyncio
    async def test_round1_names_both_steps_quoting_phrase_where_present(
        self, orchestrator, mock_semantic_parser
    ):
        """Proves 2a end-to-end: both steps named in ONE question, not just
        the first. Step 1's unresolvable phrase is quoted; step 2 (no phrase
        at all) is named by step number only."""
        question = await self._ask(orchestrator, mock_semantic_parser)

        assert [s.step_order for s in question.steps] == [1, 2]
        assert question.steps[0].duration_phrase == "xyz123"
        assert question.steps[1].duration_phrase is None
        assert "xyz123" in question.question
        assert question.reason == ClarificationReason.AMBIGUOUS_DURATION

    @pytest.mark.asyncio
    async def test_full_structured_reply_completes_prediction_verbatim(
        self, orchestrator, mock_semantic_parser
    ):
        """Acceptance: [{step_order:1, hours:2}, {step_order:2, hours:8}] ->
        full prediction, both durations source=clarification_response, and
        the reply is used verbatim (2h=120min, 8h=480min exactly) -- no LLM
        anywhere in this path, so no drift is possible."""
        await self._ask(orchestrator, mock_semantic_parser)

        mock_semantic_parser.extract_scenario = AsyncMock(return_value=self._scenario())
        result = await orchestrator.translate(
            self.QUERY,
            duration_reply=self._reply([(1, 2.0), (2, 8.0)]),
        )

        assert result.success is True, f"Failed with error: {result.error}"
        assert result.state.status == SessionStatus.COMPLETED
        assert result.execution_result is not None

        profile = result.state.execution_payload.time_temperature_profile
        durations = {s.step_order: s.duration_minutes for s in profile.steps}
        assert durations == {1: 120.0, 2: 480.0}

        from app.api.routes.translation import _build_field_audit

        field_audit = _build_field_audit(result)
        assert field_audit["duration_minutes (step 1)"].source == (
            "clarification_response"
        )
        assert field_audit["duration_minutes (step 2)"].source == (
            "clarification_response"
        )
        assert field_audit["duration_minutes (step 1)"].final_value == 120.0
        assert field_audit["duration_minutes (step 2)"].final_value == 480.0

        # A resolved-and-executed request must not carry a stale "required
        # value missing" warning from before the reply resolved it.
        assert not any(
            "required value missing" in w for w in result.metadata.warnings
        ), result.metadata.warnings

        assert len(result.metadata.clarifications) == 1
        assert result.metadata.clarifications[0].turn_number == 1

        # Regression: standardize() runs twice for this gate (once before
        # the reply, once after) -- fields defaulted on the FIRST call (this
        # scenario supplies no initial_inoculum_log_cfu, so it's always
        # defaulted) must not be double-recorded when the second call
        # defaults the same field again. Unlike the organism gate, whose
        # first standardize() call always returns before ph/aw/inoculum are
        # ever processed, duration's first call runs past all of them.
        inoculum_defaults = [
            d
            for d in result.metadata.defaults_imputed
            if d.field_name == "initial_inoculum_log_cfu"
        ]
        assert len(inoculum_defaults) == 1, (
            f"initial_inoculum_log_cfu default recorded {len(inoculum_defaults)} "
            f"times, expected exactly 1: {result.metadata.defaults_imputed}"
        )

    @pytest.mark.asyncio
    async def test_partial_reply_fails_closed(self, orchestrator, mock_semantic_parser):
        """Reply answering only one of two missing steps -> fails closed per
        the all-or-nothing multiplicity decision, plain message, nothing
        partially applied."""
        await self._ask(orchestrator, mock_semantic_parser)

        mock_semantic_parser.extract_scenario = AsyncMock(return_value=self._scenario())
        result = await orchestrator.translate(
            self.QUERY,
            duration_reply=self._reply([(1, 2.0)]),  # step 2 not answered
        )

        assert result.success is False
        assert result.state.status == SessionStatus.FAILED
        assert result.error is not None
        assert "step" in result.error.lower()
        assert result.state.execution_payload is None

    @pytest.mark.asyncio
    async def test_out_of_range_reply_fails_closed_not_clamped(
        self, orchestrator, mock_semantic_parser
    ):
        """5000 hours (300000 min) exceeds the 2190h/131400min ceiling ->
        fails closed with a plain message, not silently clamped to the max."""
        await self._ask(orchestrator, mock_semantic_parser)

        mock_semantic_parser.extract_scenario = AsyncMock(return_value=self._scenario())
        result = await orchestrator.translate(
            self.QUERY,
            duration_reply=self._reply([(1, 5000.0), (2, 8.0)]),
        )

        assert result.success is False
        assert result.state.status == SessionStatus.FAILED
        assert result.error is not None
        assert "5000" in result.error
        assert result.state.execution_payload is None

    @pytest.mark.asyncio
    async def test_organism_missing_multistep_still_routes_to_organism_gate(
        self, orchestrator, mock_semantic_parser
    ):
        """Multi-step scenario with an unrecognised food (organism ungrounded,
        both step durations fully explicit) must still route to the organism
        gate, unaffected by the duration gate existing alongside it."""
        scenario = ExtractedScenario(
            food_description="frobnitz",
            pathogen_mentioned=None,
            is_multi_step=True,
            single_step_temperature=ExtractedTemperature(),
            single_step_duration=ExtractedDuration(),
            time_temperature_steps=[
                ExtractedTimeTemperatureStep(
                    sequence_order=1,
                    temperature=ExtractedTemperature(value_celsius=25.0),
                    duration=ExtractedDuration(value_minutes=120.0),
                ),
                ExtractedTimeTemperatureStep(
                    sequence_order=2,
                    temperature=ExtractedTemperature(value_celsius=4.0),
                    duration=ExtractedDuration(value_minutes=60.0),
                ),
            ],
            environmental_conditions=ExtractedEnvironmentalConditions(),
            concern_type="safety",
            is_storage_scenario=True,
            implied_model_type=ModelType.GROWTH,
        )
        mock_semantic_parser.extract_scenario = AsyncMock(return_value=scenario)

        result = await orchestrator.translate("Frobnitz transported then stored")

        assert result.state.status == SessionStatus.AWAITING_CLARIFICATION
        assert result.state.clarification_question is not None
        assert (
            result.state.clarification_question.stage
            == OrganismGroundingFailureStage.FOOD_UNRECOGNISED
        )
        assert result.state.duration_clarification_question is None
