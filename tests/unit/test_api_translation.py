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


class TestVerboseAudit:
    """Tests for verbose=true audit output on /api/v1/translate."""

    def _make_verbose_result(self):
        """
        Build a mock TranslationResult with enough metadata to exercise
        every block of _build_audit_detail.
        """
        from app.models.execution.combase import ComBaseExecutionResult, ComBaseModelResult
        from app.models.execution.base import TimeTemperatureStep, TimeTemperatureProfile
        from app.models.execution.combase import (
            ComBaseExecutionPayload,
            ComBaseModelSelection,
            ComBaseParameters,
        )
        from app.core.orchestrator import TranslationResult
        from app.models.metadata import (
            ValueProvenance,
            ValueSource,
            RetrievalResult,
            RunnerUpResult,
            BiasCorrection,
            ComBaseModelAudit,
            SystemAudit,
        )
        from app.models.enums import BiasType, RetrievalConfidenceLevel

        state = SessionState(user_input="slice of white bread left out")
        state.status = SessionStatus.COMPLETED
        state.grounded_values = {"ph": 5.5, "water_activity": 0.97, "organism": "SALMONELLA"}

        meta = InterpretationMetadata(
            session_id=state.session_id,
            original_input=state.user_input,
            status=state.status,
        )

        # pH from RAG with runners-up
        meta.add_provenance(
            "ph",
            ValueProvenance(
                source=ValueSource.RAG_RETRIEVAL,
                confidence=0.80,
                retrieval_source="food_properties:bread_white",
                original_text="White bread: pH 5.0–6.2, water activity 0.94–0.97",
                extraction_method="regex",
                raw_match="5.0–6.2",
                parsed_range=[5.0, 6.2],
                confidence_derivation="retrieval_score 0.86; embedding 0.71, rerank 0.86",
            ),
        )
        # Water activity from RAG (single value)
        meta.add_provenance(
            "water_activity",
            ValueProvenance(
                source=ValueSource.RAG_RETRIEVAL,
                confidence=0.77,
                retrieval_source="food_properties:bread_white",
                original_text="White bread: pH 5.0–6.2, water activity 0.94–0.97",
                extraction_method="regex",
                raw_match="0.94–0.97",
                parsed_range=[0.94, 0.97],
                confidence_derivation="0.86 × 0.9 (range uncertainty) = 0.77; embedding 0.71, rerank 0.86",
            ),
        )
        # Organism explicit
        meta.add_provenance(
            "organism",
            ValueProvenance(
                source=ValueSource.USER_EXPLICIT,
                confidence=0.90,
                extraction_method="direct",
                confidence_derivation="fixed 0.90 (user-stated value)",
            ),
        )

        # Retrieval record with runners-up
        meta.add_retrieval(
            RetrievalResult(
                query="slice of white bread pH water activity properties",
                confidence_level=RetrievalConfidenceLevel.HIGH,
                confidence_score=0.86,
                source_document="food_properties",
                chunk_id="food_properties:bread_white",
                retrieved_text="White bread: pH 5.0–6.2, water activity 0.94–0.97 [FDA-PH-2007]",
                embedding_score=0.71,
                rerank_score=0.86,
                source_ids=["FDA-PH-2007"],
                full_citations={"FDA-PH-2007": "FDA/CFSAN (2007). Approximate pH of Foods."},
                runners_up=[
                    RunnerUpResult(
                        doc_id="food_properties:bread_cracked_wheat",
                        content_preview="Cracked wheat bread: pH 5.2–5.8",
                        embedding_score=0.62,
                        rerank_score=0.62,
                    )
                ],
            )
        )

        # One bias correction
        meta.add_bias_correction(
            BiasCorrection(
                bias_type=BiasType.MISSING_VALUE_IMPUTED,
                field_name="temperature_celsius",
                original_value=None,
                corrected_value=25.0,
                correction_reason="No temperature specified. Using conservative abuse temperature (25°C).",
            )
        )

        meta.defaults_imputed.append("temperature_celsius (defaulted to 25.0°C)")
        meta.overall_confidence = 0.77
        meta.confidence_formula = "min(0.80, 0.77, 0.90) − 0.05·1 − 0.10·0 − 0.10·0 = 0.72"

        meta.combase_model = ComBaseModelAudit(
            organism="SALMONELLA",
            model_type="growth",
            model_id=1,
            coefficients_str="0.1;0.2;0.3",
            valid_ranges={"temperature_celsius": (5.0, 45.0)},
            selection_reason="default (no thermal/non-thermal signals detected)",
        )
        meta.system = SystemAudit(
            rag_store_hash="abc123",
            rag_ingested_at="2026-04-27T00:00:00+00:00",
            source_csv_audit_date="2026-04-17T00:00:00+00:00",
            ptm_version="a1b2c3d",
            combase_model_table_hash="deadbeef",
        )

        state.metadata = meta

        model_result = ComBaseModelResult(
            mu_max=0.42,
            doubling_time_hours=1.65,
            model_type=ModelType.GROWTH,
            organism=ComBaseOrganism.SALMONELLA,
            temperature_used=25.0,
            ph_used=5.5,
            aw_used=0.97,
            engine_type=EngineType.COMBASE_LOCAL,
        )

        state.execution_payload = ComBaseExecutionPayload(
            model_selection=ComBaseModelSelection(
                organism=ComBaseOrganism.SALMONELLA,
                model_type=ModelType.GROWTH,
            ),
            parameters=ComBaseParameters(
                temperature_celsius=25.0,
                ph=5.5,
                water_activity=0.97,
            ),
            time_temperature_profile=TimeTemperatureProfile(
                is_multi_step=False,
                steps=[TimeTemperatureStep(temperature_celsius=25.0, duration_minutes=60.0, step_order=1)],
                total_duration_minutes=60.0,
            ),
        )

        state.execution_result = ComBaseExecutionResult(
            model_result=model_result,
            step_predictions=[],
            total_log_increase=0.21,
            engine_type=EngineType.COMBASE_LOCAL,
            warnings=[],
        )

        mock_result = MagicMock(spec=TranslationResult)
        mock_result.success = True
        mock_result.error = None
        mock_result.state = state
        mock_result.execution_result = state.execution_result
        mock_result.metadata = meta
        return mock_result

    def test_verbose_false_omits_audit(self, client):
        """Default verbose=false must not include audit field."""
        with patch("app.api.routes.translation.get_orchestrator") as mock_get:
            mock_orch = MagicMock()
            mock_orch.translate = AsyncMock(return_value=self._make_verbose_result())
            mock_get.return_value = mock_orch

            response = client.post(
                "/api/v1/translate",
                json={"query": "slice of white bread left out"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data.get("audit") is None

    def test_verbose_true_returns_audit(self, client):
        """verbose=true must return a non-null audit block."""
        with patch("app.api.routes.translation.get_orchestrator") as mock_get:
            mock_orch = MagicMock()
            mock_orch.translate = AsyncMock(return_value=self._make_verbose_result())
            mock_get.return_value = mock_orch

            response = client.post(
                "/api/v1/translate?verbose=true",
                json={"query": "slice of white bread left out"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["audit"] is not None

    def test_verbose_audit_contains_field_entries(self, client):
        """field_audit must have an entry for each grounded field."""
        with patch("app.api.routes.translation.get_orchestrator") as mock_get:
            mock_orch = MagicMock()
            mock_orch.translate = AsyncMock(return_value=self._make_verbose_result())
            mock_get.return_value = mock_orch

            response = client.post(
                "/api/v1/translate?verbose=true",
                json={"query": "slice of white bread left out"},
            )

        audit = response.json()["audit"]
        assert "ph" in audit["field_audit"]
        assert "water_activity" in audit["field_audit"]

    def test_verbose_retrieval_details_populated(self, client):
        """RAG-sourced fields must carry retrieval, source_ids, and full_citations."""
        with patch("app.api.routes.translation.get_orchestrator") as mock_get:
            mock_orch = MagicMock()
            mock_orch.translate = AsyncMock(return_value=self._make_verbose_result())
            mock_get.return_value = mock_orch

            response = client.post(
                "/api/v1/translate?verbose=true",
                json={"query": "slice of white bread left out"},
            )

        ph_entry = response.json()["audit"]["field_audit"]["ph"]
        assert ph_entry["retrieval"] is not None
        top = ph_entry["retrieval"]["top_match"]
        assert top is not None
        assert "FDA-PH-2007" in top["source_ids"]
        assert "FDA-PH-2007" in top["full_citations"]
        assert len(ph_entry["retrieval"]["runners_up"]) == 1

    def test_verbose_audit_summary_none_applied_sentinel(self, client):
        """range_clamps must use the '(none applied)' sentinel when empty."""
        with patch("app.api.routes.translation.get_orchestrator") as mock_get:
            mock_orch = MagicMock()
            mock_orch.translate = AsyncMock(return_value=self._make_verbose_result())
            mock_get.return_value = mock_orch

            response = client.post(
                "/api/v1/translate?verbose=true",
                json={"query": "slice of white bread left out"},
            )

        audit_summary = response.json()["audit"]["audit"]
        assert audit_summary["range_clamps"] == ["(none applied)"]
        assert audit_summary["warnings"] == ["(none applied)"]

    def test_verbose_combase_model_block_present(self, client):
        """combase_model block must include model_id and selection_reason."""
        with patch("app.api.routes.translation.get_orchestrator") as mock_get:
            mock_orch = MagicMock()
            mock_orch.translate = AsyncMock(return_value=self._make_verbose_result())
            mock_get.return_value = mock_orch

            response = client.post(
                "/api/v1/translate?verbose=true",
                json={"query": "slice of white bread left out"},
            )

        cb = response.json()["audit"]["combase_model"]
        assert cb is not None
        assert cb["model_id"] == 1
        assert "selection_reason" in cb

    def test_verbose_system_block_present(self, client):
        """system block must include rag_store_hash and ptm_version."""
        with patch("app.api.routes.translation.get_orchestrator") as mock_get:
            mock_orch = MagicMock()
            mock_orch.translate = AsyncMock(return_value=self._make_verbose_result())
            mock_get.return_value = mock_orch

            response = client.post(
                "/api/v1/translate?verbose=true",
                json={"query": "slice of white bread left out"},
            )

        sys_block = response.json()["audit"]["system"]
        assert sys_block is not None
        assert sys_block["rag_store_hash"] == "abc123"
        assert sys_block["ptm_version"] == "a1b2c3d"


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