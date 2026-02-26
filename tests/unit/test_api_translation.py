"""
Unit tests for translation API endpoint.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from fastapi.testclient import TestClient

from app.main import app
from app.models.enums import SessionStatus, ModelType, ComBaseOrganism, EngineType
from app.core.state import SessionState
from app.models.metadata import InterpretationMetadata


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_translation_result():
    """Create mock orchestrator with successful result."""
    from app.models.execution.combase import ComBaseExecutionResult, ComBaseModelResult
    from app.core.orchestrator import TranslationResult
    
    # Create mock state
    state = SessionState(user_input="test query")
    state.status = SessionStatus.COMPLETED
    state.metadata = InterpretationMetadata(
        session_id=state.session_id,
        original_input=state.user_input,
        status=state.status,
    )
    
    # Create mock execution result
    model_result = ComBaseModelResult(
        mu_max=0.42,
        doubling_time_hours=1.65,
        model_type=ModelType.GROWTH,
        organism=ComBaseOrganism.SALMONELLA,
        temperature_used=25.0,
        ph_used=6.0,
        aw_used=0.99,
        engine_type=EngineType.COMBASE_LOCAL,
    )
    
    from app.models.execution.base import TimeTemperatureStep, TimeTemperatureProfile
    from app.models.execution.combase import ComBaseExecutionPayload, ComBaseModelSelection, ComBaseParameters
    
    state.execution_payload = ComBaseExecutionPayload(
        model_selection=ComBaseModelSelection(
            organism=ComBaseOrganism.SALMONELLA,
            model_type=ModelType.GROWTH,
        ),
        parameters=ComBaseParameters(
            temperature_celsius=25.0,
            ph=6.0,
            water_activity=0.99,
        ),
        time_temperature_profile=TimeTemperatureProfile(
            is_multi_step=False,
            steps=[TimeTemperatureStep(
                temperature_celsius=25.0,
                duration_minutes=180.0,
                step_order=1,
            )],
            total_duration_minutes=180.0,
        ),
    )
    
    state.execution_result = ComBaseExecutionResult(
        model_result=model_result,
        step_predictions=[],
        total_log_increase=0.78,
        engine_type=EngineType.COMBASE_LOCAL,
        warnings=[],
    )
    
    # Create mock result
    mock_result = MagicMock(spec=TranslationResult)
    mock_result.success = True
    mock_result.error = None
    mock_result.state = state
    mock_result.execution_result = state.execution_result
    mock_result.metadata = state.metadata
    
    return mock_result


class TestTranslationEndpoint:
    """Tests for /api/v1/translate endpoint."""
    
    def test_successful_translation(self, client, mock_translation_result):
        """Should return successful translation."""
        with patch("app.api.routes.translation.get_orchestrator") as mock_get:
            mock_orch = MagicMock()
            mock_orch.translate = AsyncMock(return_value=mock_translation_result)
            mock_get.return_value = mock_orch
            
            response = client.post(
                "/api/v1/translate",
                json={"query": "Raw chicken left out for 3 hours"},
            )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["prediction"] is not None
        assert data["prediction"]["organism"] == "SALMONELLA"
    
    def test_returns_prediction_details(self, client, mock_translation_result):
        """Should return detailed prediction info."""
        with patch("app.api.routes.translation.get_orchestrator") as mock_get:
            mock_orch = MagicMock()
            mock_orch.translate = AsyncMock(return_value=mock_translation_result)
            mock_get.return_value = mock_orch
            
            response = client.post(
                "/api/v1/translate",
                json={"query": "Raw chicken left out for 3 hours"},
            )
        
        data = response.json()
        prediction = data["prediction"]
        
        assert prediction["temperature_celsius"] == 25.0
        assert prediction["duration_minutes"] == 180.0
        assert prediction["mu_max"] == 0.42
        assert "growth_description" in prediction
    
    def test_returns_session_id(self, client, mock_translation_result):
        """Should return session ID for tracking."""
        with patch("app.api.routes.translation.get_orchestrator") as mock_get:
            mock_orch = MagicMock()
            mock_orch.translate = AsyncMock(return_value=mock_translation_result)
            mock_get.return_value = mock_orch
            
            response = client.post(
                "/api/v1/translate",
                json={"query": "Test query"},
            )
        
        data = response.json()
        assert "session_id" in data
        assert len(data["session_id"]) > 0
    
    def test_empty_query_rejected(self, client):
        """Should reject empty queries."""
        response = client.post(
            "/api/v1/translate",
            json={"query": ""},
        )
        
        assert response.status_code == 422
    
    def test_custom_model_type(self, client, mock_translation_result):
        """Should accept custom model type."""
        with patch("app.api.routes.translation.get_orchestrator") as mock_get:
            mock_orch = MagicMock()
            mock_orch.translate = AsyncMock(return_value=mock_translation_result)
            mock_get.return_value = mock_orch
            
            response = client.post(
                "/api/v1/translate",
                json={
                    "query": "Cooking chicken at 75C",
                    "model_type": "thermal_inactivation",
                },
            )
        
        assert response.status_code == 200
    
    def test_failed_translation_returns_error(self, client):
        """Should return error for failed translation."""
        from app.core.orchestrator import TranslationResult
        
        state = SessionState(user_input="bad query")
        state.status = SessionStatus.FAILED
        state.error = "Could not translate query"
        
        mock_result = MagicMock(spec=TranslationResult)
        mock_result.success = False
        mock_result.error = "Could not translate query"
        mock_result.state = state
        mock_result.metadata = None
        
        with patch("app.api.routes.translation.get_orchestrator") as mock_get:
            mock_orch = MagicMock()
            mock_orch.translate = AsyncMock(return_value=mock_result)
            mock_get.return_value = mock_orch
            
            response = client.post(
                "/api/v1/translate",
                json={"query": "Something incomprehensible"},
            )
        
        data = response.json()
        assert data["success"] is False
        assert data["error"] is not None


class TestGrowthDescription:
    """Tests for growth description formatting."""
    
    def test_minimal_growth(self):
        """Should describe minimal growth correctly."""
        from app.api.routes.translation import _format_growth_description
        
        desc = _format_growth_description(0.1)
        assert "minimal" in desc.lower()
    
    def test_moderate_growth(self):
        """Should describe moderate growth correctly."""
        from app.api.routes.translation import _format_growth_description
        
        desc = _format_growth_description(0.5)
        assert "moderate" in desc.lower()
    
    def test_significant_growth(self):
        """Should describe significant growth correctly."""
        from app.api.routes.translation import _format_growth_description
        
        desc = _format_growth_description(2.0)
        assert "significant" in desc.lower()
    
    def test_reduction(self):
        """Should describe log reduction correctly."""
        from app.api.routes.translation import _format_growth_description
        
        desc = _format_growth_description(-3.0)
        assert "reduction" in desc.lower()