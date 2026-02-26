"""
Unit tests for workflow orchestrator.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from app.core.orchestrator import Orchestrator, TranslationResult
from app.core.state import SessionState, SessionManager
from app.models.enums import SessionStatus, IntentType, ModelType, ComBaseOrganism
from app.models.extraction import (
    ExtractedScenario,
    ExtractedIntent,
    ExtractedTemperature,
    ExtractedDuration,
)
from app.services.grounding.grounding_service import GroundedValues
from app.models.metadata import ValueSource


@pytest.fixture
def mock_parser():
    """Create mock semantic parser."""
    parser = MagicMock()
    parser.classify_intent = AsyncMock(return_value=ExtractedIntent(
        is_prediction_request=True,
        is_information_query=False,
        confidence=0.95,
    ))
    parser.extract_scenario = AsyncMock(return_value=ExtractedScenario(
        food_description="raw chicken",
        single_step_temperature=ExtractedTemperature(value_celsius=25.0),
        single_step_duration=ExtractedDuration(value_minutes=180.0),
    ))
    return parser


@pytest.fixture
def mock_grounder():
    """Create mock grounding service."""
    grounder = MagicMock()
    
    async def mock_ground(scenario):
        grounded = GroundedValues()
        grounded.set("temperature_celsius", 25.0, ValueSource.USER_EXPLICIT, 0.95)
        grounded.set("duration_minutes", 180.0, ValueSource.USER_EXPLICIT, 0.95)
        grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.RAG_RETRIEVAL, 0.85)
        grounded.set("ph", 6.0, ValueSource.RAG_RETRIEVAL, 0.80)
        grounded.set("water_activity", 0.99, ValueSource.RAG_RETRIEVAL, 0.80)
        return grounded
    
    grounder.ground_scenario = mock_ground
    return grounder


@pytest.fixture
def mock_engine():
    """Create mock ComBase engine."""
    from app.models.execution.combase import ComBaseExecutionResult, ComBaseModelResult
    from app.models.enums import EngineType
    
    engine = MagicMock()
    engine.is_available = True
    engine.execute = AsyncMock(return_value=ComBaseExecutionResult(
        model_result=ComBaseModelResult(
            mu_max=0.5,
            doubling_time_hours=1.4,
            model_type=ModelType.GROWTH,
            organism=ComBaseOrganism.SALMONELLA,
            temperature_used=25.0,
            ph_used=6.0,
            aw_used=0.99,
        ),
        step_predictions=[],
        total_log_increase=0.65,
        engine_type=EngineType.COMBASE_LOCAL,
        warnings=[],
    ))
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
        result = await orchestrator.translate(
            "Raw chicken left out for 3 hours at 25C"
        )
        
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
        mock_parser.classify_intent = AsyncMock(return_value=ExtractedIntent(
            is_prediction_request=False,
            is_information_query=False,
            confidence=0.9,
        ))
        
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