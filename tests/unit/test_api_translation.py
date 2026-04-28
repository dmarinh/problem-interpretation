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