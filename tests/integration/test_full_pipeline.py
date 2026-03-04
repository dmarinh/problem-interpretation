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
        assert len(result.metadata.warnings) > 0 or len(result.metadata.bias_corrections) > 0