"""
Integration tests for the full translation pipeline.

These tests run the complete pipeline with real components
(except LLM which is mocked to avoid API costs).
"""

import pytest
from unittest.mock import AsyncMock
from pathlib import Path
import tempfile
import shutil

from app.core.orchestrator import Orchestrator, TranslationResult
from app.core.state import SessionManager
from app.engines.combase.engine import ComBaseEngine
from app.rag.vector_store import VectorStore
from app.rag.retrieval import RetrievalService
from app.services.grounding.grounding_service import GroundingService
from app.services.standardization.standardization_service import StandardizationService
from app.models.enums import (
    SessionStatus,
    ModelType,
    ComBaseOrganism,
)
from app.models.extraction import (
    ExtractedScenario,
    ExtractedIntent,
    ExtractedTemperature,
    ExtractedDuration,
    ExtractedEnvironmentalConditions,
)


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
        environmental_conditions=environmental_conditions or ExtractedEnvironmentalConditions(),
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
    
    parser.classify_intent = AsyncMock(return_value=ExtractedIntent(
        is_prediction_request=True,
        is_information_query=False,
        confidence=0.95,
    ))
    
    parser.extract_scenario = AsyncMock(return_value=create_scenario(
        food_description="raw chicken",
        food_state="raw",
        temperature=ExtractedTemperature(description="room temperature"),
        duration=ExtractedDuration(value_minutes=180.0),
        is_storage_scenario=True,
    ))
    
    return parser


@pytest.fixture
def orchestrator(combase_engine, vector_store, mock_semantic_parser):
    """Create orchestrator with real components except LLM."""
    if not combase_engine.is_available:
        pytest.skip("ComBase models not available")
    
    retrieval_service = RetrievalService(vector_store=vector_store)
    grounding_service = GroundingService(retrieval_service=retrieval_service)
    standardization_service = StandardizationService(model_registry=combase_engine.registry)
    
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
        mock_semantic_parser.extract_scenario = AsyncMock(return_value=create_scenario(
            food_description="raw chicken",
            temperature=ExtractedTemperature(description="room temperature"),
            duration=ExtractedDuration(value_minutes=180.0),
            is_storage_scenario=True,
        ))
        
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
        mock_semantic_parser.extract_scenario = AsyncMock(return_value=create_scenario(
            food_description="raw chicken",
            temperature=ExtractedTemperature(value_celsius=30.0),
            duration=ExtractedDuration(value_minutes=120.0),
            is_storage_scenario=True,
        ))
        
        result = await orchestrator.translate(
            "Chicken at 30°C for 2 hours"
        )
        
        assert result.success is True, f"Failed with error: {result.error}"
        assert result.state.execution_payload.parameters.temperature_celsius == 30.0
    
    @pytest.mark.asyncio
    async def test_explicit_pathogen(self, orchestrator, mock_semantic_parser):
        """Should use explicit pathogen when mentioned."""
        mock_semantic_parser.extract_scenario = AsyncMock(return_value=create_scenario(
            food_description="deli meat",
            pathogen_mentioned="Listeria",
            temperature=ExtractedTemperature(value_celsius=4.0),
            duration=ExtractedDuration(value_minutes=1440.0),
            is_storage_scenario=True,
        ))
        
        result = await orchestrator.translate(
            "Listeria growth in deli meat at 4°C for 24 hours"
        )
        
        assert result.success is True, f"Failed with error: {result.error}"
        assert result.state.execution_payload.model_selection.organism == ComBaseOrganism.LISTERIA_MONOCYTOGENES
    
    @pytest.mark.asyncio
    async def test_rag_grounds_pathogen(self, orchestrator, mock_semantic_parser):
        """Should retrieve pathogen from RAG when not explicit."""
        mock_semantic_parser.extract_scenario = AsyncMock(return_value=create_scenario(
            food_description="raw chicken",
            temperature=ExtractedTemperature(value_celsius=25.0),
            duration=ExtractedDuration(value_minutes=180.0),
            is_storage_scenario=True,
        ))
        
        result = await orchestrator.translate(
            "Raw chicken at 25°C for 3 hours"
        )
        
        assert result.success is True, f"Failed with error: {result.error}"
        # Should find Salmonella from RAG for chicken or use default
        organism = result.state.execution_payload.model_selection.organism
        assert organism is not None
    
    @pytest.mark.asyncio
    async def test_duration_interpretation(self, orchestrator, mock_semantic_parser):
        """Should interpret vague duration descriptions."""
        mock_semantic_parser.extract_scenario = AsyncMock(return_value=create_scenario(
            food_description="cooked rice",
            temperature=ExtractedTemperature(value_celsius=25.0),
            duration=ExtractedDuration(description="overnight"),
            is_storage_scenario=True,
        ))
        
        result = await orchestrator.translate(
            "Cooked rice left out overnight"
        )
        
        assert result.success is True, f"Failed with error: {result.error}"
        # "overnight" should be interpreted as ~480 minutes (8 hours)
        duration = result.state.execution_payload.time_temperature_profile.total_duration_minutes
        assert 400 <= duration <= 600
    
    @pytest.mark.asyncio
    async def test_provenance_tracking(self, orchestrator, mock_semantic_parser):
        """Should track provenance of all grounded values."""
        mock_semantic_parser.extract_scenario = AsyncMock(return_value=create_scenario(
            food_description="raw chicken",
            temperature=ExtractedTemperature(description="room temperature"),
            duration=ExtractedDuration(value_minutes=180.0),
            is_storage_scenario=True,
        ))
        
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
    async def test_thermal_inactivation(self, orchestrator, mock_semantic_parser, combase_engine):
        """Should run thermal inactivation model."""
        # Check if Salmonella thermal model exists
        model = combase_engine.registry.get_model(
            ComBaseOrganism.SALMONELLA,
            ModelType.THERMAL_INACTIVATION,
        )
        if model is None:
            pytest.skip("Salmonella thermal model not available")
        
        mock_semantic_parser.extract_scenario = AsyncMock(return_value=create_scenario(
            food_description="chicken",
            pathogen_mentioned="Salmonella",
            temperature=ExtractedTemperature(value_celsius=60.0),
            duration=ExtractedDuration(value_minutes=10.0),
            is_cooking_scenario=True,
            implied_model_type=ModelType.THERMAL_INACTIVATION,
        ))
        
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
        mock_semantic_parser.classify_intent = AsyncMock(return_value=ExtractedIntent(
            is_prediction_request=False,
            is_information_query=False,
            confidence=0.9,
        ))
        
        result = await orchestrator.translate(
            "What is the meaning of life?"
        )
        
        assert result.success is False
        assert "out of scope" in result.error.lower()
    
    @pytest.mark.asyncio
    async def test_model_type_inference_cooking(self, orchestrator, mock_semantic_parser, combase_engine):
        """Should infer thermal inactivation for cooking scenarios."""
        model = combase_engine.registry.get_model(
            ComBaseOrganism.SALMONELLA,
            ModelType.THERMAL_INACTIVATION,
        )
        if model is None:
            pytest.skip("Salmonella thermal model not available")
        
        mock_semantic_parser.extract_scenario = AsyncMock(return_value=create_scenario(
            food_description="chicken",
            pathogen_mentioned="Salmonella",
            temperature=ExtractedTemperature(value_celsius=70.0),
            duration=ExtractedDuration(value_minutes=5.0),
            is_cooking_scenario=True,
            implied_model_type=ModelType.THERMAL_INACTIVATION,
        ))
        
        # Don't pass model_type - let it be inferred
        result = await orchestrator.translate(
            "Cooking chicken to 70°C for 5 minutes"
        )
        
        assert result.success is True, f"Failed with error: {result.error}"
        assert result.state.execution_payload.model_selection.model_type == ModelType.THERMAL_INACTIVATION
    
    @pytest.mark.asyncio
    async def test_model_type_inference_storage(self, orchestrator, mock_semantic_parser):
        """Should infer growth for storage scenarios."""
        mock_semantic_parser.extract_scenario = AsyncMock(return_value=create_scenario(
            food_description="raw chicken",
            temperature=ExtractedTemperature(value_celsius=25.0),
            duration=ExtractedDuration(value_minutes=180.0),
            is_storage_scenario=True,
            implied_model_type=ModelType.GROWTH,
        ))
        
        # Don't pass model_type - let it be inferred
        result = await orchestrator.translate(
            "Chicken left out for 3 hours"
        )
        
        assert result.success is True, f"Failed with error: {result.error}"
        assert result.state.execution_payload.model_selection.model_type == ModelType.GROWTH


class TestEdgeCases:
    """Edge case and error handling tests."""
    
    @pytest.mark.asyncio
    async def test_missing_duration_fails(self, orchestrator, mock_semantic_parser):
        """Should fail when duration cannot be determined."""
        mock_semantic_parser.extract_scenario = AsyncMock(return_value=create_scenario(
            food_description="chicken",
            temperature=ExtractedTemperature(value_celsius=25.0),
            duration=ExtractedDuration(),  # No duration info
            is_storage_scenario=True,
        ))
        
        result = await orchestrator.translate(
            "Chicken at 25°C"
        )
        
        assert result.success is False
        assert "duration" in result.error.lower()
    
    @pytest.mark.asyncio
    async def test_defaults_applied_with_warnings(self, orchestrator, mock_semantic_parser):
        """Should apply defaults and track warnings."""
        mock_semantic_parser.extract_scenario = AsyncMock(return_value=create_scenario(
            food_description="unknown food",
            temperature=ExtractedTemperature(value_celsius=25.0),
            duration=ExtractedDuration(value_minutes=180.0),
            is_storage_scenario=True,
        ))
        
        result = await orchestrator.translate(
            "Unknown food at 25°C for 3 hours"
        )
        
        assert result.success is True, f"Failed with error: {result.error}"
        # Should have warnings about defaults applied
        assert result.metadata is not None
        assert len(result.metadata.warnings) > 0 or len(result.metadata.defaults_imputed) > 0


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
        mock_semantic_parser.extract_scenario = AsyncMock(return_value=create_scenario(
            food_description="raw chicken",
            pathogen_mentioned="Salmonella",
            temperature=ExtractedTemperature(value_celsius=25.0),
            duration=ExtractedDuration(value_minutes=240.0),
            is_storage_scenario=True,
        ))

        result = await orchestrator.translate(
            "Raw chicken kept at 25°C for 4 hours."
        )

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
        if ph_entry.standardization is not None and ph_entry.standardization.rule == "range_bound_selection":
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
        mock_semantic_parser.extract_scenario = AsyncMock(return_value=create_scenario(
            food_description="cooked rice",
            temperature=ExtractedTemperature(description="sitting out"),
            duration=ExtractedDuration(description="a while"),
            is_storage_scenario=True,
        ))

        result = await orchestrator.translate(
            "Cooked rice was sitting out for a while. Predict Bacillus cereus growth."
        )

        assert result.success is True, f"Failed with error: {result.error}"
        assert result.metadata is not None

        from app.api.routes.translation import _build_field_audit
        field_audit = _build_field_audit(result)

        # water_activity must appear — either from RAG or from conservative default
        assert "water_activity" in field_audit, (
            "water_activity must be present in field_audit whether grounded or defaulted"
        )

        aw_entry = field_audit["water_activity"]
        aw_used = result.state.execution_payload.parameters.water_activity
        assert aw_entry.final_value == pytest.approx(aw_used)

        # temperature_celsius: inferred via rule → extraction block must be populated
        assert "temperature_celsius" in field_audit
        temp_entry = field_audit["temperature_celsius"]
        if temp_entry.extraction is not None:
            assert temp_entry.extraction.method in ("rule_match", "embedding_fallback", None)
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

        mock_semantic_parser.extract_scenario = AsyncMock(return_value=create_scenario(
            food_description="milk",
            pathogen_mentioned="E. coli",
            temperature=ExtractedTemperature(value_celsius=50.0),
            duration=ExtractedDuration(value_minutes=360.0),
            is_storage_scenario=True,
        ))

        result = await orchestrator.translate(
            "Predict E. coli growth on milk at 50°C for 6 hours."
        )

        assert result.success is True, f"Failed with error: {result.error}"
        assert result.metadata is not None

        # Payload temperature must be clamped
        temp_used = result.state.execution_payload.parameters.temperature_celsius
        assert temp_used == pytest.approx(model.constraints.temp_max), (
            f"Expected temperature clamped to {model.constraints.temp_max}°C, got {temp_used}"
        )

        # Structured RangeClamp in metadata
        temp_clamps = [
            c for c in result.metadata.range_clamps
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

        mock_semantic_parser.extract_scenario = AsyncMock(return_value=create_scenario(
            food_description="milk",
            pathogen_mentioned="E. coli",
            temperature=ExtractedTemperature(value_celsius=50.0),
            duration=ExtractedDuration(value_minutes=360.0),
            is_storage_scenario=True,
        ))

        result = await orchestrator.translate(
            "Predict E. coli growth on milk at 50°C for 6 hours."
        )
        assert result.success is True

        from app.api.routes.translation import _build_field_audit, _build_audit_detail
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
    B.2: When no pathogen is named, Salmonella is imputed.
    The imputation must appear in field_audit AND defaults_imputed — not only
    as a warning string.
    """

    @pytest.mark.asyncio
    async def test_default_organism_in_field_audit(
        self, orchestrator, mock_semantic_parser
    ):
        """
        Query with no pathogen_mentioned: 'organism' must appear in field_audit
        with source == "conservative_default" and standardization.rule == "default_imputed".
        """
        mock_semantic_parser.extract_scenario = AsyncMock(return_value=create_scenario(
            food_description="chicken",
            pathogen_mentioned=None,
            temperature=ExtractedTemperature(value_celsius=25.0),
            duration=ExtractedDuration(value_minutes=240.0),
            is_storage_scenario=True,
        ))

        result = await orchestrator.translate(
            "How long before chicken left out at 25°C becomes unsafe?"
        )

        assert result.success is True, f"Failed with error: {result.error}"
        assert result.metadata is not None

        # defaults_imputed must contain the organism entry
        org_defaults = [
            d for d in result.metadata.defaults_imputed
            if d.field_name == "organism"
        ]
        assert len(org_defaults) == 1, (
            f"Expected 1 organism DefaultImputed, got {len(org_defaults)}"
        )
        assert "salmonella" in str(org_defaults[0].imputed_value).lower()

        # field_audit must include organism
        from app.api.routes.translation import _build_field_audit
        field_audit = _build_field_audit(result)

        assert "organism" in field_audit, (
            "organism must appear in field_audit when defaulted"
        )
        org_entry = field_audit["organism"]
        assert org_entry.source == "conservative_default"
        assert org_entry.standardization is not None
        assert org_entry.standardization.rule == "default_imputed"

    @pytest.mark.asyncio
    async def test_default_organism_in_audit_defaults_imputed(
        self, orchestrator, mock_semantic_parser
    ):
        """
        audit.audit.defaults_imputed must contain an entry for 'organism'
        when no pathogen was specified.
        """
        mock_semantic_parser.extract_scenario = AsyncMock(return_value=create_scenario(
            food_description="rice",
            pathogen_mentioned=None,
            temperature=ExtractedTemperature(value_celsius=25.0),
            duration=ExtractedDuration(value_minutes=240.0),
            is_storage_scenario=True,
        ))

        result = await orchestrator.translate(
            "Is rice left out at 25°C for 4 hours safe?"
        )

        assert result.success is True

        from app.api.routes.translation import _build_field_audit, _build_audit_detail
        field_audit = _build_field_audit(result)
        audit_detail = _build_audit_detail(result, field_audit)

        org_imputed = [
            d for d in audit_detail.audit.defaults_imputed
            if d.field_name == "organism"
        ]
        assert len(org_imputed) == 1
        assert "salmonella" in str(org_imputed[0].default_value).lower()


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

        mock_semantic_parser.extract_scenario = AsyncMock(return_value=create_scenario(
            food_description="chicken",
            pathogen_mentioned="Salmonella",
            temperature=ExtractedTemperature(value_celsius=65.0),
            duration=ExtractedDuration(value_minutes=10.0),
            is_cooking_scenario=True,
            implied_model_type=ModelType.THERMAL_INACTIVATION,
        ))

        result = await orchestrator.translate(
            "Calculate Salmonella thermal inactivation in chicken at 65°C for 10 minutes.",
            model_type=ModelType.THERMAL_INACTIVATION,
        )

        assert result.success is True, f"Failed with error: {result.error}"
        assert result.state.execution_payload.model_selection.model_type == ModelType.THERMAL_INACTIVATION
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

        mock_semantic_parser.extract_scenario = AsyncMock(return_value=create_scenario(
            food_description="raw chicken",
            pathogen_mentioned="Salmonella",
            temperature=ExtractedTemperature(value_celsius=65.0),
            duration=ExtractedDuration(value_minutes=10.0),
            is_cooking_scenario=True,
            implied_model_type=ModelType.THERMAL_INACTIVATION,
        ))

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