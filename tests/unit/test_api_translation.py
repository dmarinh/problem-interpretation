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
            DefaultImputed,
            ComBaseModelAudit,
            SystemAudit,
        )

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
                retrieval_source="food_properties:bread_white",
                original_text="White bread: pH 5.0–6.2, water activity 0.94–0.97",
                extraction_method="regex",
                raw_match="5.0–6.2",
                parsed_range=[5.0, 6.2],
            ),
        )
        # Water activity from RAG (single value)
        meta.add_provenance(
            "water_activity",
            ValueProvenance(
                source=ValueSource.RAG_RETRIEVAL,
                retrieval_source="food_properties:bread_white",
                original_text="White bread: pH 5.0–6.2, water activity 0.94–0.97",
                extraction_method="regex",
                raw_match="0.94–0.97",
                parsed_range=[0.94, 0.97],
            ),
        )
        # Organism explicit
        meta.add_provenance(
            "organism",
            ValueProvenance(
                source=ValueSource.USER_EXPLICIT,
                extraction_method="direct",
            ),
        )

        # Retrieval record with runners-up
        meta.add_retrieval(
            RetrievalResult(
                query="slice of white bread pH water activity properties",
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

        # One default imputed
        meta.add_default_imputed(
            DefaultImputed(
                field_name="temperature_celsius",
                imputed_value=25.0,
                reason="No temperature specified. Using conservative abuse temperature (25°C).",
            )
        )

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

    def test_verbose_audit_summary_empty_lists(self, client):
        """Empty audit categories must emit [] not a sentinel string."""
        with patch("app.api.routes.translation.get_orchestrator") as mock_get:
            mock_orch = MagicMock()
            mock_orch.translate = AsyncMock(return_value=self._make_verbose_result())
            mock_get.return_value = mock_orch

            response = client.post(
                "/api/v1/translate?verbose=true",
                json={"query": "slice of white bread left out"},
            )

        audit_summary = response.json()["audit"]["audit"]
        assert audit_summary["range_clamps"] == []
        assert audit_summary["warnings"] == []

    def test_verbose_defaults_imputed_structured(self, client):
        """defaults_imputed must be a list of structured objects, not plain strings."""
        with patch("app.api.routes.translation.get_orchestrator") as mock_get:
            mock_orch = MagicMock()
            mock_orch.translate = AsyncMock(return_value=self._make_verbose_result())
            mock_get.return_value = mock_orch

            response = client.post(
                "/api/v1/translate?verbose=true",
                json={"query": "slice of white bread left out"},
            )

        defaults = response.json()["audit"]["audit"]["defaults_imputed"]
        assert len(defaults) == 1
        entry = defaults[0]
        assert entry["field_name"] == "temperature_celsius"
        assert entry["default_value"] == 25.0
        assert "reason" in entry

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


    def _make_fallback_result(self):
        """
        Mock result where pH comes from the primary RAG query (RAG_RETRIEVAL)
        and water_activity comes from the Tier 2 per-field fallback query
        (RAG_RETRIEVAL_FALLBACK, with attributed_field tag on the retrieval).

        This mirrors Capture A from the two-tier fallback design: the primary
        doc had pH but a blank aw field, so the fallback fired for aw.
        """
        from app.models.execution.combase import (
            ComBaseExecutionResult, ComBaseModelResult,
            ComBaseExecutionPayload, ComBaseModelSelection, ComBaseParameters,
        )
        from app.models.execution.base import TimeTemperatureStep, TimeTemperatureProfile
        from app.core.orchestrator import TranslationResult
        from app.models.metadata import (
            ValueProvenance, ValueSource, RetrievalResult,
            DefaultImputed, ComBaseModelAudit, SystemAudit,
        )

        state = SessionState(user_input="raw chicken at 25C for 4 hours")
        state.status = SessionStatus.COMPLETED
        state.grounded_values = {"ph": 6.2, "water_activity": 0.98}

        meta = InterpretationMetadata(
            session_id=state.session_id,
            original_input=state.user_input,
            status=state.status,
        )

        # pH from primary RAG query
        meta.add_provenance(
            "ph",
            ValueProvenance(
                source=ValueSource.RAG_RETRIEVAL,
                retrieval_source="food_properties:chicken_raw",
                original_text="Raw chicken: pH 5.9–6.5",
                extraction_method="regex",
                raw_match="5.9–6.5",
                parsed_range=[5.9, 6.5],
            ),
        )
        # water_activity from Tier 2 fallback query
        meta.add_provenance(
            "water_activity",
            ValueProvenance(
                source=ValueSource.RAG_RETRIEVAL_FALLBACK,
                retrieval_source="food_properties:poultry_category",
                original_text="Poultry (fresh): water activity 0.97–0.99",
                extraction_method="regex",
                raw_match="0.97–0.99",
                parsed_range=[0.97, 0.99],
            ),
        )

        # Primary retrieval (untagged — attributed_field=None)
        meta.add_retrieval(
            RetrievalResult(
                query="raw chicken pH water activity food properties",
                source_document="food_properties",
                chunk_id="food_properties:chicken_raw",
                retrieved_text="Raw chicken: pH 5.9–6.5 [FDA-PH-2007]",
                embedding_score=0.78,
                source_ids=["FDA-PH-2007"],
                full_citations={"FDA-PH-2007": "FDA/CFSAN (2007). Approximate pH of Foods."},
            )
        )
        # Fallback retrieval for water_activity (tagged)
        meta.add_retrieval(
            RetrievalResult(
                query="raw chicken water activity aw moisture",
                source_document="food_properties",
                chunk_id="food_properties:poultry_category",
                retrieved_text="Poultry (fresh): water activity 0.97–0.99 [IFT-2003]",
                embedding_score=0.66,
                source_ids=["IFT-2003"],
                full_citations={"IFT-2003": "IFT (2003). Kinetics of Microbial Inactivation."},
                attributed_field="water_activity",
            )
        )

        meta.add_default_imputed(
            DefaultImputed(
                field_name="temperature_celsius",
                imputed_value=25.0,
                reason="No temperature specified; using conservative abuse temperature.",
            )
        )
        meta.combase_model = ComBaseModelAudit(
            organism="SALMONELLA",
            model_type="growth",
            model_id=1,
            coefficients_str="0.1;0.2;0.3",
            valid_ranges={"temperature_celsius": (5.0, 45.0)},
            selection_reason="default",
        )
        meta.system = SystemAudit(
            rag_store_hash="abc123",
            rag_ingested_at="2026-04-30T00:00:00+00:00",
            source_csv_audit_date="2026-04-17T00:00:00+00:00",
            ptm_version="a1b2c3d",
            combase_model_table_hash="deadbeef",
        )

        state.metadata = meta

        model_result = ComBaseModelResult(
            mu_max=0.926,
            doubling_time_hours=0.75,
            model_type=ModelType.GROWTH,
            organism=ComBaseOrganism.SALMONELLA,
            temperature_used=25.0,
            ph_used=6.2,
            aw_used=0.98,
            engine_type=EngineType.COMBASE_LOCAL,
        )
        state.execution_payload = ComBaseExecutionPayload(
            model_selection=ComBaseModelSelection(
                organism=ComBaseOrganism.SALMONELLA,
                model_type=ModelType.GROWTH,
            ),
            parameters=ComBaseParameters(
                temperature_celsius=25.0,
                ph=6.2,
                water_activity=0.98,
            ),
            time_temperature_profile=TimeTemperatureProfile(
                is_multi_step=False,
                steps=[TimeTemperatureStep(temperature_celsius=25.0, duration_minutes=240.0, step_order=1)],
                total_duration_minutes=240.0,
            ),
        )
        state.execution_result = ComBaseExecutionResult(
            model_result=model_result,
            step_predictions=[],
            total_log_increase=1.61,
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

    def test_fallback_source_tier_appears_in_field_audit(self, client):
        """
        RAG_RETRIEVAL_FALLBACK provenance must flow through _build_audit_detail
        and appear correctly in field_audit. Regression guard: the Tier 2
        fallback was added after the verbose audit tests were written, so the
        existing mocks don't exercise this source tier through _build_audit_detail.
        """
        with patch("app.api.routes.translation.get_orchestrator") as mock_get:
            mock_orch = MagicMock()
            mock_orch.translate = AsyncMock(return_value=self._make_fallback_result())
            mock_get.return_value = mock_orch

            response = client.post(
                "/api/v1/translate?verbose=true",
                json={"query": "raw chicken at 25C for 4 hours"},
            )

        assert response.status_code == 200
        data = response.json()

        # Top-level audit block must be present
        assert data["audit"] is not None
        field_audit = data["audit"]["field_audit"]

        # pH: primary RAG — retrieval block references the primary query
        ph = field_audit["ph"]
        assert ph["source"] == "rag_retrieval"
        assert ph["retrieval"] is not None
        assert "raw chicken" in ph["retrieval"]["query"]
        assert "water activity" in ph["retrieval"]["query"]  # primary is combined

        # water_activity: fallback RAG — retrieval block references the fallback query
        aw = field_audit["water_activity"]
        assert aw["source"] == "rag_retrieval_fallback"
        assert aw["retrieval"] is not None
        assert "water activity" in aw["retrieval"]["query"]
        # The fallback query must NOT be the combined primary query
        assert "ph" not in aw["retrieval"]["query"].lower()

        # All four top-level audit sub-blocks present
        assert data["audit"]["combase_model"] is not None
        assert data["audit"]["audit"] is not None
        assert data["audit"]["system"] is not None

    def _make_result_with_reranker_top(self):
        """
        Primary Tier 1 query where the reranker promoted doc_26 to first place but
        doc_26 failed the embedding threshold; doc_24 (next in reranked list) passed
        and supplied pH 6.4.  This mirrors the Q04 chicken observation.
        """
        from app.models.execution.combase import (
            ComBaseExecutionResult, ComBaseModelResult,
            ComBaseExecutionPayload, ComBaseModelSelection, ComBaseParameters,
        )
        from app.models.execution.base import TimeTemperatureStep, TimeTemperatureProfile
        from app.core.orchestrator import TranslationResult
        from app.models.metadata import (
            ValueProvenance, ValueSource, RetrievalResult, SkippedDocInfo,
            DefaultImputed, ComBaseModelAudit, SystemAudit,
        )

        state = SessionState(user_input="raw chicken at room temperature")
        state.status = SessionStatus.COMPLETED
        state.grounded_values = {"ph": 6.4, "water_activity": 0.98}

        meta = InterpretationMetadata(
            session_id=state.session_id,
            original_input=state.user_input,
            status=state.status,
        )
        meta.add_provenance(
            "ph",
            ValueProvenance(
                source=ValueSource.RAG_RETRIEVAL,
                retrieval_source="food_properties_24",
                original_text="Chicken (raw): pH 6.2–6.6",
                extraction_method="regex",
                raw_match="6.2–6.6",
                parsed_range=[6.2, 6.6],
            ),
        )
        meta.add_retrieval(
            RetrievalResult(
                query="raw chicken pH water activity properties",
                source_document="food_properties",
                chunk_id="food_properties_24",
                retrieved_text="Chicken (raw): pH 6.2–6.6 [FDA-PH-2007]",
                embedding_score=0.75,
                rerank_score=0.80,
                source_ids=["FDA-PH-2007"],
                full_citations={"FDA-PH-2007": "FDA/CFSAN (2007). Approximate pH of Foods."},
                reranker_top=SkippedDocInfo(
                    doc_id="food_properties_26",
                    content_preview="Chicken anatomy document (no pH data)",
                    embedding_score=0.58,
                    rerank_score=0.95,
                    skip_reason="failed_embedding_threshold:0.70",
                ),
            )
        )
        meta.add_default_imputed(
            DefaultImputed(
                field_name="temperature_celsius",
                imputed_value=25.0,
                reason="No temperature specified.",
            )
        )
        meta.combase_model = ComBaseModelAudit(
            organism="SALMONELLA", model_type="growth", model_id=1,
            coefficients_str="0.1;0.2;0.3",
            valid_ranges={"temperature_celsius": (5.0, 45.0)},
            selection_reason="default",
        )
        meta.system = SystemAudit(
            rag_store_hash="abc123", rag_ingested_at="2026-05-01T00:00:00+00:00",
            source_csv_audit_date="2026-04-17T00:00:00+00:00",
            ptm_version="a1b2c3d", combase_model_table_hash="deadbeef",
        )
        state.metadata = meta

        model_result = ComBaseModelResult(
            mu_max=0.926, doubling_time_hours=0.75,
            model_type=ModelType.GROWTH, organism=ComBaseOrganism.SALMONELLA,
            temperature_used=25.0, ph_used=6.4, aw_used=0.98,
            engine_type=EngineType.COMBASE_LOCAL,
        )
        state.execution_payload = ComBaseExecutionPayload(
            model_selection=ComBaseModelSelection(
                organism=ComBaseOrganism.SALMONELLA, model_type=ModelType.GROWTH,
            ),
            parameters=ComBaseParameters(temperature_celsius=25.0, ph=6.4, water_activity=0.98),
            time_temperature_profile=TimeTemperatureProfile(
                is_multi_step=False,
                steps=[TimeTemperatureStep(temperature_celsius=25.0, duration_minutes=180.0, step_order=1)],
                total_duration_minutes=180.0,
            ),
        )
        state.execution_result = ComBaseExecutionResult(
            model_result=model_result, step_predictions=[],
            total_log_increase=1.2, engine_type=EngineType.COMBASE_LOCAL, warnings=[],
        )
        mock_result = MagicMock(spec=TranslationResult)
        mock_result.success = True
        mock_result.error = None
        mock_result.state = state
        mock_result.execution_result = state.execution_result
        mock_result.metadata = meta
        return mock_result

    def _make_result_with_attempted_top(self):
        """
        Primary Tier 1 query where all docs failed the embedding threshold.
        pH is sourced as RAG_RETRIEVAL (forcing the audit retrieval block to be
        built) but top_match is null — only attempted_top is populated, showing
        what the system almost used.  This exercises the attempted_top → JSON
        mapping path in translation.py.
        """
        from app.models.execution.combase import (
            ComBaseExecutionResult, ComBaseModelResult,
            ComBaseExecutionPayload, ComBaseModelSelection, ComBaseParameters,
        )
        from app.models.execution.base import TimeTemperatureStep, TimeTemperatureProfile
        from app.core.orchestrator import TranslationResult
        from app.models.metadata import (
            ValueProvenance, ValueSource, RetrievalResult, SkippedDocInfo,
            DefaultImputed, ComBaseModelAudit, SystemAudit,
        )

        state = SessionState(user_input="exotic fermented food")
        state.status = SessionStatus.COMPLETED
        state.grounded_values = {"ph": 7.0, "water_activity": 0.99}

        meta = InterpretationMetadata(
            session_id=state.session_id,
            original_input=state.user_input,
            status=state.status,
        )
        # RAG_RETRIEVAL source so _build_field_audit enters the retrieval block;
        # retrieval_source=None reflects that no doc passed the threshold.
        meta.add_provenance(
            "ph",
            ValueProvenance(
                source=ValueSource.RAG_RETRIEVAL,
                retrieval_source=None,
                extraction_method="regex",
            ),
        )
        # Retrieval record where all docs failed threshold: chunk_id=None,
        # top_match will be null, attempted_top carries the near-miss doc.
        meta.add_retrieval(
            RetrievalResult(
                query="exotic fermented food pH water activity properties",
                source_document=None,
                chunk_id=None,
                retrieved_text=None,
                embedding_score=None,
                rerank_score=None,
                source_ids=[],
                full_citations={},
                fallback_used=True,
                attempted_top=SkippedDocInfo(
                    doc_id="food_properties_99",
                    content_preview="Generic fermented food profile",
                    embedding_score=0.52,
                    rerank_score=0.88,
                    skip_reason="failed_embedding_threshold:0.70",
                ),
            )
        )
        meta.add_default_imputed(
            DefaultImputed(field_name="temperature_celsius", imputed_value=25.0, reason="No temperature."),
        )
        meta.combase_model = ComBaseModelAudit(
            organism="SALMONELLA", model_type="growth", model_id=1,
            coefficients_str="0.1;0.2;0.3",
            valid_ranges={"temperature_celsius": (5.0, 45.0)},
            selection_reason="default",
        )
        meta.system = SystemAudit(
            rag_store_hash="abc123", rag_ingested_at="2026-05-01T00:00:00+00:00",
            source_csv_audit_date="2026-04-17T00:00:00+00:00",
            ptm_version="a1b2c3d", combase_model_table_hash="deadbeef",
        )
        state.metadata = meta

        model_result = ComBaseModelResult(
            mu_max=0.5, doubling_time_hours=1.4,
            model_type=ModelType.GROWTH, organism=ComBaseOrganism.SALMONELLA,
            temperature_used=25.0, ph_used=7.0, aw_used=0.99,
            engine_type=EngineType.COMBASE_LOCAL,
        )
        state.execution_payload = ComBaseExecutionPayload(
            model_selection=ComBaseModelSelection(
                organism=ComBaseOrganism.SALMONELLA, model_type=ModelType.GROWTH,
            ),
            parameters=ComBaseParameters(temperature_celsius=25.0, ph=7.0, water_activity=0.99),
            time_temperature_profile=TimeTemperatureProfile(
                is_multi_step=False,
                steps=[TimeTemperatureStep(temperature_celsius=25.0, duration_minutes=60.0, step_order=1)],
                total_duration_minutes=60.0,
            ),
        )
        state.execution_result = ComBaseExecutionResult(
            model_result=model_result, step_predictions=[],
            total_log_increase=0.5, engine_type=EngineType.COMBASE_LOCAL, warnings=[],
        )
        mock_result = MagicMock(spec=TranslationResult)
        mock_result.success = True
        mock_result.error = None
        mock_result.state = state
        mock_result.execution_result = state.execution_result
        mock_result.metadata = meta
        return mock_result

    def test_reranker_top_surfaces_in_retrieval_audit(self, client):
        """
        When the reranker promoted a below-threshold doc (Q04 scenario), the audit
        must show reranker_top with the skipped doc's id and skip_reason, while
        top_match holds the threshold-passing doc that supplied final_value.
        """
        with patch("app.api.routes.translation.get_orchestrator") as mock_get:
            mock_orch = MagicMock()
            mock_orch.translate = AsyncMock(return_value=self._make_result_with_reranker_top())
            mock_get.return_value = mock_orch

            response = client.post(
                "/api/v1/translate?verbose=true",
                json={"query": "raw chicken at room temperature"},
            )

        assert response.status_code == 200
        ph = response.json()["audit"]["field_audit"]["ph"]
        retrieval = ph["retrieval"]

        assert retrieval["top_match"]["doc_id"] == "food_properties_24"
        assert retrieval["reranker_top"] is not None
        assert retrieval["reranker_top"]["doc_id"] == "food_properties_26"
        assert retrieval["reranker_top"]["skip_reason"] == "failed_embedding_threshold:0.70"
        assert retrieval["reranker_top"]["embedding_score"] == 0.58
        assert retrieval["attempted_top"] is None

    def test_attempted_top_surfaces_when_all_failed(self, client):
        """
        When no result passed the threshold, top_match must be null and attempted_top
        must show the reranker's top pick with a skip_reason.  pH is sourced as
        RAG_RETRIEVAL so the retrieval block is rendered; chunk_id=None means top_match
        is null; attempted_top carries the near-miss doc.
        """
        with patch("app.api.routes.translation.get_orchestrator") as mock_get:
            mock_orch = MagicMock()
            mock_orch.translate = AsyncMock(return_value=self._make_result_with_attempted_top())
            mock_get.return_value = mock_orch

            response = client.post(
                "/api/v1/translate?verbose=true",
                json={"query": "exotic fermented food"},
            )

        assert response.status_code == 200
        ph = response.json()["audit"]["field_audit"]["ph"]
        retrieval = ph["retrieval"]

        assert retrieval["top_match"] is None
        assert retrieval["reranker_top"] is None
        assert retrieval["attempted_top"] is not None
        assert retrieval["attempted_top"]["doc_id"] == "food_properties_99"
        assert retrieval["attempted_top"]["skip_reason"] == "failed_embedding_threshold:0.70"
        assert retrieval["attempted_top"]["embedding_score"] == 0.52

    def test_no_reranker_divergence_reranker_top_absent(self, client):
        """
        When the reranker's top pick also passes the gate (common case), both
        reranker_top and attempted_top must be absent (null) in the audit.
        """
        with patch("app.api.routes.translation.get_orchestrator") as mock_get:
            mock_orch = MagicMock()
            mock_orch.translate = AsyncMock(return_value=self._make_verbose_result())
            mock_get.return_value = mock_orch

            response = client.post(
                "/api/v1/translate?verbose=true",
                json={"query": "slice of white bread left out"},
            )

        assert response.status_code == 200
        ph = response.json()["audit"]["field_audit"]["ph"]
        assert ph["retrieval"]["reranker_top"] is None
        assert ph["retrieval"]["attempted_top"] is None


class TestAuditPostStandardization:
    """
    Tests that verify the audit snapshot is post-standardization.

    Each test constructs a mock result where standardization has mutated
    the ValueProvenance objects in-place (as the real pipeline does), then
    asserts that field_audit reflects those post-standardization values.
    """

    def _make_range_result(self):
        """
        Bread-style: ph grounded as range [5.0, 6.2] with standardization
        selecting the upper bound (6.2) for a growth model.
        """
        from app.models.execution.combase import (
            ComBaseExecutionResult, ComBaseModelResult,
            ComBaseExecutionPayload, ComBaseModelSelection, ComBaseParameters,
        )
        from app.models.execution.base import TimeTemperatureStep, TimeTemperatureProfile
        from app.core.orchestrator import TranslationResult
        from app.models.metadata import (
            ValueProvenance, ValueSource, RangeBoundSelection,
            DefaultImputed, ComBaseModelAudit, SystemAudit,
        )

        state = SessionState(user_input="white bread query")
        state.status = SessionStatus.COMPLETED
        state.grounded_values = {"ph": 5.0, "water_activity": 0.94}

        meta = InterpretationMetadata(
            session_id=state.session_id,
            original_input=state.user_input,
            status=state.status,
        )

        # pH: range 5.0–6.2, standardization selected upper bound 6.2
        ph_prov = ValueProvenance(
            source=ValueSource.RAG_RETRIEVAL,
            extraction_method="regex",
            raw_match="5.0–6.2",
            parsed_range=[5.0, 6.2],
            range_pending=False,  # cleared by standardization
            standardization=RangeBoundSelection(
                rule="range_bound_selection",
                direction="upper",
                before_value=[5.0, 6.2],
                after_value=6.2,
                reason="Range narrowed to upper bound for growth model",
            ),
        )
        meta.add_provenance("ph", ph_prov)

        # water_activity: range 0.94–0.97, standardization selected upper bound 0.97
        aw_prov = ValueProvenance(
            source=ValueSource.RAG_RETRIEVAL,
            extraction_method="regex",
            raw_match="0.94–0.97",
            parsed_range=[0.94, 0.97],
            range_pending=False,
            standardization=RangeBoundSelection(
                rule="range_bound_selection",
                direction="upper",
                before_value=[0.94, 0.97],
                after_value=0.97,
                reason="Range narrowed to upper bound for growth model",
            ),
        )
        meta.add_provenance("water_activity", aw_prov)

        meta.combase_model = ComBaseModelAudit(
            organism="BACILLUS_CEREUS",
            organism_id="bc",
            organism_display_name="Bacillus cereus",
            model_type="growth",
            model_id=1,
            coefficients_str="0.1",
            valid_ranges=None,
            selection_reason="default",
        )
        meta.system = SystemAudit(ptm_version="test")
        state.metadata = meta

        state.execution_payload = ComBaseExecutionPayload(
            model_selection=ComBaseModelSelection(
                organism=ComBaseOrganism.SALMONELLA, model_type=ModelType.GROWTH,
            ),
            parameters=ComBaseParameters(
                temperature_celsius=25.0, ph=6.2, water_activity=0.97,
            ),
            time_temperature_profile=TimeTemperatureProfile(
                is_multi_step=False,
                steps=[TimeTemperatureStep(temperature_celsius=25.0, duration_minutes=60.0, step_order=1)],
                total_duration_minutes=60.0,
            ),
        )
        state.execution_result = ComBaseExecutionResult(
            model_result=ComBaseModelResult(
                mu_max=0.42, doubling_time_hours=1.65, model_type=ModelType.GROWTH,
                organism=ComBaseOrganism.SALMONELLA, temperature_used=25.0,
                ph_used=6.2, aw_used=0.97, engine_type=EngineType.COMBASE_LOCAL,
            ),
            step_predictions=[], total_log_increase=0.21,
            engine_type=EngineType.COMBASE_LOCAL, warnings=[],
        )

        mock_result = MagicMock(spec=TranslationResult)
        mock_result.success = True
        mock_result.error = None
        mock_result.state = state
        mock_result.execution_result = state.execution_result
        mock_result.metadata = meta
        return mock_result

    def _make_default_result(self):
        """
        Rice-style: water_activity not grounded, defaulted to 0.99.
        Temperature inferred via rule ("sitting out" → 25°C).
        """
        from app.models.execution.combase import (
            ComBaseExecutionResult, ComBaseModelResult,
            ComBaseExecutionPayload, ComBaseModelSelection, ComBaseParameters,
        )
        from app.models.execution.base import TimeTemperatureStep, TimeTemperatureProfile
        from app.core.orchestrator import TranslationResult
        from app.models.metadata import (
            ValueProvenance, ValueSource, DefaultImputed, ComBaseModelAudit, SystemAudit,
        )

        state = SessionState(user_input="cooked rice query")
        state.status = SessionStatus.COMPLETED
        state.grounded_values = {"temperature_celsius": 25.0}

        meta = InterpretationMetadata(
            session_id=state.session_id,
            original_input=state.user_input,
            status=state.status,
        )

        # temperature_celsius: inferred via rule "sitting out" → 25°C
        temp_prov = ValueProvenance(
            source=ValueSource.USER_INFERRED,
            original_text="sitting out",
            transformation_applied="Interpreted as 25.0°C (Sitting out implies room temperature)",
            extraction_method="rule_match",
            matched_pattern="sitting out",
            rule_conservative=True,
            rule_notes="Sitting out implies room temperature",
        )
        meta.add_provenance("temperature_celsius", temp_prov)

        # water_activity: never grounded — defaulted to 0.99 by standardization
        meta.add_default_imputed(DefaultImputed(
            field_name="water_activity",
            imputed_value=0.99,
            reason="No water activity specified. Using conservative high default (0.99).",
        ))

        meta.combase_model = ComBaseModelAudit(
            organism="BACILLUS_CEREUS",
            model_type="growth",
            model_id=1,
            coefficients_str="0.1",
            valid_ranges=None,
            selection_reason="default",
        )
        meta.system = SystemAudit(ptm_version="test")
        state.metadata = meta

        state.execution_payload = ComBaseExecutionPayload(
            model_selection=ComBaseModelSelection(
                organism=ComBaseOrganism.SALMONELLA, model_type=ModelType.GROWTH,
            ),
            parameters=ComBaseParameters(
                temperature_celsius=25.0, ph=7.0, water_activity=0.99,
            ),
            time_temperature_profile=TimeTemperatureProfile(
                is_multi_step=False,
                steps=[TimeTemperatureStep(temperature_celsius=25.0, duration_minutes=60.0, step_order=1)],
                total_duration_minutes=60.0,
            ),
        )
        state.execution_result = ComBaseExecutionResult(
            model_result=ComBaseModelResult(
                mu_max=0.38, doubling_time_hours=1.8, model_type=ModelType.GROWTH,
                organism=ComBaseOrganism.SALMONELLA, temperature_used=25.0,
                ph_used=7.0, aw_used=0.99, engine_type=EngineType.COMBASE_LOCAL,
            ),
            step_predictions=[], total_log_increase=0.15,
            engine_type=EngineType.COMBASE_LOCAL, warnings=[],
        )

        mock_result = MagicMock(spec=TranslationResult)
        mock_result.success = True
        mock_result.error = None
        mock_result.state = state
        mock_result.execution_result = state.execution_result
        mock_result.metadata = meta
        return mock_result

    def _get_audit(self, client, mock_result):
        with patch("app.api.routes.translation.get_orchestrator") as mock_get:
            mock_orch = MagicMock()
            mock_orch.translate = AsyncMock(return_value=mock_result)
            mock_get.return_value = mock_orch
            response = client.post(
                "/api/v1/translate?verbose=true",
                json={"query": "test"},
            )
        assert response.status_code == 200
        return response.json()["audit"]

    # T1 — Bread-style: final_value reflects post-standardization bound selection

    def test_ph_final_value_reflects_range_bound_selection(self, client):
        """field_audit.ph.final_value must be the upper bound selected by standardization (6.2), not the grounded placeholder (5.0)."""
        audit = self._get_audit(client, self._make_range_result())
        ph_entry = audit["field_audit"]["ph"]
        assert ph_entry["final_value"] == pytest.approx(6.2)

    def test_water_activity_final_value_reflects_range_bound_selection(self, client):
        """field_audit.water_activity.final_value must be 0.97 (upper bound), not 0.94 (placeholder)."""
        audit = self._get_audit(client, self._make_range_result())
        aw_entry = audit["field_audit"]["water_activity"]
        assert aw_entry["final_value"] == pytest.approx(0.97)

    def test_ph_standardization_block_is_structured(self, client):
        """field_audit.ph.standardization must have rule/direction/before_value/after_value/reason."""
        audit = self._get_audit(client, self._make_range_result())
        std = audit["field_audit"]["ph"]["standardization"]
        assert std is not None
        assert std["rule"] == "range_bound_selection"
        assert std["direction"] == "upper"
        assert std["before_value"] == [5.0, 6.2]
        assert std["after_value"] == pytest.approx(6.2)
        assert "reason" in std and std["reason"]

    # T4 — Rice-style: defaulted fields appear in field_audit

    def test_defaulted_water_activity_appears_in_field_audit(self, client):
        """water_activity must appear in field_audit even when it was not grounded (defaulted by standardization)."""
        audit = self._get_audit(client, self._make_default_result())
        assert "water_activity" in audit["field_audit"]

    def test_defaulted_field_has_correct_source_and_value(self, client):
        """Defaulted field must show source=conservative_default and final_value=0.99."""
        audit = self._get_audit(client, self._make_default_result())
        aw_entry = audit["field_audit"]["water_activity"]
        assert aw_entry["source"] == "conservative_default"
        assert aw_entry["final_value"] == pytest.approx(0.99)

    def test_defaulted_field_has_default_imputed_standardization_block(self, client):
        """Defaulted field's standardization block must use rule=default_imputed."""
        audit = self._get_audit(client, self._make_default_result())
        std = audit["field_audit"]["water_activity"]["standardization"]
        assert std is not None
        assert std["rule"] == "default_imputed"
        assert std["before_value"] is None
        assert std["after_value"] == pytest.approx(0.99)
        assert "reason" in std and std["reason"]

    # Rule extraction fields (T2 / T4 shared)

    def test_inferred_temperature_extraction_block_has_rule_fields(self, client):
        """field_audit for USER_INFERRED temperature must carry matched_pattern, conservative, notes."""
        audit = self._get_audit(client, self._make_default_result())
        extraction = audit["field_audit"]["temperature_celsius"]["extraction"]
        assert extraction is not None
        assert extraction["method"] == "rule_match"
        assert extraction["matched_pattern"] == "sitting out"
        assert extraction["conservative"] is True
        assert extraction["notes"] is not None

    # Legacy provenance list derives post-standardization values

    def test_legacy_provenance_value_is_post_standardization(self, client):
        """The top-level provenance list must show final post-standardization value, not placeholder."""
        with patch("app.api.routes.translation.get_orchestrator") as mock_get:
            mock_orch = MagicMock()
            mock_orch.translate = AsyncMock(return_value=self._make_range_result())
            mock_get.return_value = mock_orch
            response = client.post("/api/v1/translate", json={"query": "test"})

        provenance = response.json()["provenance"]
        ph_entry = next((p for p in provenance if p["field"] == "ph"), None)
        assert ph_entry is not None
        # Must show 6.2, not 5.0 (the pre-standardization placeholder)
        assert ph_entry["value"] == "6.2"

    def test_legacy_provenance_notes_not_stale_placeholder(self, client):
        """The legacy provenance notes must not contain the stale 'range extracted, awaiting standardization' text."""
        with patch("app.api.routes.translation.get_orchestrator") as mock_get:
            mock_orch = MagicMock()
            mock_orch.translate = AsyncMock(return_value=self._make_range_result())
            mock_get.return_value = mock_orch
            response = client.post("/api/v1/translate", json={"query": "test"})

        provenance = response.json()["provenance"]
        ph_entry = next((p for p in provenance if p["field"] == "ph"), None)
        assert ph_entry is not None
        notes = ph_entry.get("notes") or ""
        assert "awaiting standardization" not in notes

    # Organism representation

    def test_organism_display_name_in_combase_model_block(self, client):
        """combase_model block must include organism_id and organism_display_name."""
        audit = self._get_audit(client, self._make_range_result())
        cb = audit["combase_model"]
        assert cb["organism_id"] == "bc"
        assert cb["organism_display_name"] == "Bacillus cereus"


class TestDefaultedWithRetrieval:
    """
    Tests that defaulted fields carry retrieval metadata when RAG was attempted
    before the default was applied (Q15 / fictional-food scenario).

    The fix: when a field appears in defaults_imputed AND a retrieval record
    exists with attributed_field == field_name, the audit entry must populate
    the retrieval block (with top_match=null and attempted_top showing the
    best-rejected doc), rather than leaving retrieval=null.
    """

    def _make_fictional_food_result(self):
        """
        Mock result for "zarblax burger" — a fictional food with no KB entry.

        Both pH and water_activity are attempted via Tier 2 per-field RAG
        (attributed_field tagged), both fail threshold, both default.
        The retrieval records carry attempted_top with the best-rejected doc.
        """
        from app.models.execution.combase import (
            ComBaseExecutionResult, ComBaseModelResult,
            ComBaseExecutionPayload, ComBaseModelSelection, ComBaseParameters,
        )
        from app.models.execution.base import TimeTemperatureStep, TimeTemperatureProfile
        from app.core.orchestrator import TranslationResult
        from app.models.metadata import (
            ValueProvenance, ValueSource, RetrievalResult, SkippedDocInfo,
            DefaultImputed, ComBaseModelAudit, SystemAudit,
        )

        state = SessionState(user_input="zarblax burger at 25C for 4 hours")
        state.status = SessionStatus.COMPLETED
        state.grounded_values = {}

        meta = InterpretationMetadata(
            session_id=state.session_id,
            original_input=state.user_input,
            status=state.status,
        )

        # pH and water_activity: never grounded — defaulted to conservative values.
        meta.add_default_imputed(DefaultImputed(
            field_name="ph",
            imputed_value=7.0,
            reason="No pH data found for 'zarblax burger'. Using conservative neutral default.",
        ))
        meta.add_default_imputed(DefaultImputed(
            field_name="water_activity",
            imputed_value=0.99,
            reason="No water activity data found for 'zarblax burger'. Using conservative high default.",
        ))

        # Primary Tier 1 retrieval (untagged) — failed threshold.
        meta.add_retrieval(RetrievalResult(
            query="zarblax burger pH water activity food properties",
            source_document=None,
            chunk_id=None,
            retrieved_text=None,
            embedding_score=None,
            rerank_score=None,
            source_ids=[],
            full_citations={},
            fallback_used=True,
            attempted_top=SkippedDocInfo(
                doc_id="food_properties_42",
                content_preview="Hamburger patty: pH 5.5–6.0, water activity 0.97",
                embedding_score=0.41,
                rerank_score=0.55,
                skip_reason="failed_embedding_threshold:0.70",
            ),
        ))
        # Tier 2 fallback for pH (tagged) — failed threshold.
        meta.add_retrieval(RetrievalResult(
            query="zarblax burger pH acidity",
            source_document=None,
            chunk_id=None,
            retrieved_text=None,
            embedding_score=None,
            rerank_score=None,
            source_ids=[],
            full_citations={},
            fallback_used=True,
            attributed_field="ph",
            attempted_top=SkippedDocInfo(
                doc_id="food_properties_07",
                content_preview="Generic burger: pH 5.4–6.1",
                embedding_score=0.38,
                rerank_score=0.50,
                skip_reason="failed_embedding_threshold:0.62",
            ),
        ))
        # Tier 2 fallback for water_activity (tagged) — failed threshold.
        meta.add_retrieval(RetrievalResult(
            query="zarblax burger water activity moisture",
            source_document=None,
            chunk_id=None,
            retrieved_text=None,
            embedding_score=None,
            rerank_score=None,
            source_ids=[],
            full_citations={},
            fallback_used=True,
            attributed_field="water_activity",
            attempted_top=SkippedDocInfo(
                doc_id="food_properties_11",
                content_preview="Ground beef patty: water activity 0.96–0.98",
                embedding_score=0.35,
                rerank_score=0.47,
                skip_reason="failed_embedding_threshold:0.62",
            ),
        ))

        meta.combase_model = ComBaseModelAudit(
            organism="BACILLUS_CEREUS",
            model_type="growth",
            model_id=1,
            coefficients_str="0.1;0.2;0.3",
            valid_ranges={"temperature_celsius": (5.0, 45.0)},
            selection_reason="default",
        )
        meta.system = SystemAudit(
            rag_store_hash="abc123",
            rag_ingested_at="2026-05-01T00:00:00+00:00",
            source_csv_audit_date="2026-04-17T00:00:00+00:00",
            ptm_version="a1b2c3d",
            combase_model_table_hash="deadbeef",
        )
        state.metadata = meta

        model_result = ComBaseModelResult(
            mu_max=0.5,
            doubling_time_hours=1.4,
            model_type=ModelType.GROWTH,
            organism=ComBaseOrganism.SALMONELLA,
            temperature_used=25.0,
            ph_used=7.0,
            aw_used=0.99,
            engine_type=EngineType.COMBASE_LOCAL,
        )
        state.execution_payload = ComBaseExecutionPayload(
            model_selection=ComBaseModelSelection(
                organism=ComBaseOrganism.SALMONELLA,
                model_type=ModelType.GROWTH,
            ),
            parameters=ComBaseParameters(temperature_celsius=25.0, ph=7.0, water_activity=0.99),
            time_temperature_profile=TimeTemperatureProfile(
                is_multi_step=False,
                steps=[TimeTemperatureStep(temperature_celsius=25.0, duration_minutes=240.0, step_order=1)],
                total_duration_minutes=240.0,
            ),
        )
        state.execution_result = ComBaseExecutionResult(
            model_result=model_result,
            step_predictions=[],
            total_log_increase=1.8,
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

    def _get_field_audit(self, client, mock_result):
        with patch("app.api.routes.translation.get_orchestrator") as mock_get:
            mock_orch = MagicMock()
            mock_orch.translate = AsyncMock(return_value=mock_result)
            mock_get.return_value = mock_orch
            response = client.post(
                "/api/v1/translate?verbose=true",
                json={"query": "zarblax burger at 25C for 4 hours"},
            )
        assert response.status_code == 200
        return response.json()["audit"]["field_audit"]

    def test_defaulted_field_source_remains_conservative_default(self, client):
        """source must stay conservative_default even when retrieval block is now attached."""
        fa = self._get_field_audit(client, self._make_fictional_food_result())
        assert fa["ph"]["source"] == "conservative_default"
        assert fa["water_activity"]["source"] == "conservative_default"

    def test_defaulted_field_carries_retrieval_block(self, client):
        """pH defaulted after failed RAG must have a non-null retrieval block."""
        fa = self._get_field_audit(client, self._make_fictional_food_result())
        assert fa["ph"]["retrieval"] is not None
        assert fa["water_activity"]["retrieval"] is not None

    def test_defaulted_field_retrieval_top_match_is_null(self, client):
        """top_match must be null when no doc passed threshold."""
        fa = self._get_field_audit(client, self._make_fictional_food_result())
        assert fa["ph"]["retrieval"]["top_match"] is None
        assert fa["water_activity"]["retrieval"]["top_match"] is None

    def test_defaulted_field_retrieval_attempted_top_populated(self, client):
        """attempted_top must show the best-rejected doc with skip_reason."""
        fa = self._get_field_audit(client, self._make_fictional_food_result())
        ph_at = fa["ph"]["retrieval"]["attempted_top"]
        assert ph_at is not None
        assert ph_at["doc_id"] == "food_properties_07"
        assert ph_at["skip_reason"] == "failed_embedding_threshold:0.62"
        assert ph_at["embedding_score"] == pytest.approx(0.38)

        aw_at = fa["water_activity"]["retrieval"]["attempted_top"]
        assert aw_at is not None
        assert aw_at["doc_id"] == "food_properties_11"
        assert aw_at["skip_reason"] == "failed_embedding_threshold:0.62"

    def test_defaulted_field_retrieval_query_is_field_specific(self, client):
        """retrieval query must be the per-field fallback query, not the primary combined query."""
        fa = self._get_field_audit(client, self._make_fictional_food_result())
        ph_query = fa["ph"]["retrieval"]["query"]
        assert "ph" in ph_query.lower() or "acid" in ph_query.lower()
        assert "water activity" not in ph_query.lower()

        aw_query = fa["water_activity"]["retrieval"]["query"]
        assert "water activity" in aw_query.lower() or "moisture" in aw_query.lower()

    def test_defaulted_without_rag_attempt_still_has_null_retrieval(self, client):
        """Regression: a defaulted field with no attributed retrieval must keep retrieval=null."""
        from app.core.orchestrator import TranslationResult
        from app.models.metadata import DefaultImputed, ComBaseModelAudit, SystemAudit

        state = SessionState(user_input="something")
        state.status = SessionStatus.COMPLETED
        state.grounded_values = {}
        meta = InterpretationMetadata(
            session_id=state.session_id,
            original_input=state.user_input,
            status=state.status,
        )
        meta.add_default_imputed(DefaultImputed(
            field_name="temperature_celsius",
            imputed_value=25.0,
            reason="No temperature specified.",
        ))
        meta.combase_model = ComBaseModelAudit(
            organism="SALMONELLA", model_type="growth", model_id=1,
            coefficients_str="0.1", valid_ranges=None, selection_reason="default",
        )
        meta.system = SystemAudit(ptm_version="test")
        state.metadata = meta

        from app.models.execution.combase import (
            ComBaseExecutionResult, ComBaseModelResult,
            ComBaseExecutionPayload, ComBaseModelSelection, ComBaseParameters,
        )
        from app.models.execution.base import TimeTemperatureStep, TimeTemperatureProfile

        state.execution_payload = ComBaseExecutionPayload(
            model_selection=ComBaseModelSelection(
                organism=ComBaseOrganism.SALMONELLA, model_type=ModelType.GROWTH,
            ),
            parameters=ComBaseParameters(temperature_celsius=25.0, ph=7.0, water_activity=0.99),
            time_temperature_profile=TimeTemperatureProfile(
                is_multi_step=False,
                steps=[TimeTemperatureStep(temperature_celsius=25.0, duration_minutes=60.0, step_order=1)],
                total_duration_minutes=60.0,
            ),
        )
        state.execution_result = ComBaseExecutionResult(
            model_result=ComBaseModelResult(
                mu_max=0.5, doubling_time_hours=1.4, model_type=ModelType.GROWTH,
                organism=ComBaseOrganism.SALMONELLA, temperature_used=25.0,
                ph_used=7.0, aw_used=0.99, engine_type=EngineType.COMBASE_LOCAL,
            ),
            step_predictions=[], total_log_increase=0.5,
            engine_type=EngineType.COMBASE_LOCAL, warnings=[],
        )
        mock_result = MagicMock(spec=TranslationResult)
        mock_result.success = True
        mock_result.error = None
        mock_result.state = state
        mock_result.execution_result = state.execution_result
        mock_result.metadata = meta

        fa = self._get_field_audit(client, mock_result)
        assert fa["temperature_celsius"]["retrieval"] is None


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