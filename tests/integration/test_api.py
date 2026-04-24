"""
Integration tests for API endpoints.
"""

import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, MagicMock

from app.core.orchestrator import TranslationResult
from app.core.state import SessionState
from app.models.enums import (
    ComBaseOrganism,
    EngineType,
    Factor4Type,
    ModelType,
    SessionStatus,
)
from app.models.execution.base import (
    GrowthPrediction,
    TimeTemperatureProfile,
    TimeTemperatureStep,
)
from app.models.execution.combase import (
    ComBaseExecutionPayload,
    ComBaseExecutionResult,
    ComBaseModelResult,
    ComBaseModelSelection,
    ComBaseParameters,
)


class TestAPIIntegration:
    """Integration tests for the full API."""

    @pytest.mark.asyncio
    async def test_full_health_check_flow(self, async_client: AsyncClient, patch_llm_client):
        """Test complete health check flow."""
        # Check liveness
        live_response = await async_client.get("/health/live")
        assert live_response.status_code == 200

        # Check readiness
        ready_response = await async_client.get("/health/ready")
        assert ready_response.status_code == 200

        # Check full health
        health_response = await async_client.get("/health")
        assert health_response.status_code == 200

        health_data = health_response.json()
        assert health_data["status"] in ["healthy", "degraded", "unhealthy"]

    @pytest.mark.asyncio
    async def test_openapi_schema_available(self, async_client: AsyncClient):
        """OpenAPI schema should be accessible."""
        response = await async_client.get("/openapi.json")

        assert response.status_code == 200
        data = response.json()
        assert "openapi" in data
        assert "paths" in data

    @pytest.mark.asyncio
    async def test_docs_available(self, async_client: AsyncClient):
        """Swagger docs should be accessible."""
        response = await async_client.get("/docs")

        assert response.status_code == 200


def _build_translation_result(steps_data: list[tuple[float, float]]) -> TranslationResult:
    """
    Build a successful TranslationResult with the given (temperature, duration) steps.

    Used to exercise the API response conversion without running the full pipeline.
    """
    steps = [
        TimeTemperatureStep(
            step_order=i + 1,
            temperature_celsius=temp,
            duration_minutes=dur,
        )
        for i, (temp, dur) in enumerate(steps_data)
    ]
    total_duration = sum(s.duration_minutes for s in steps)
    profile = TimeTemperatureProfile(
        is_multi_step=len(steps) > 1,
        steps=steps,
        total_duration_minutes=total_duration,
    )

    # Each step contributes log_increase = 0.1 per hour at its temperature (fake, reconciles exactly)
    step_predictions = [
        GrowthPrediction(
            step_order=s.step_order,
            duration_minutes=s.duration_minutes,
            temperature_celsius=s.temperature_celsius,
            mu_max=0.2 + 0.01 * s.temperature_celsius,
            log_increase=round(0.1 * (s.duration_minutes / 60.0), 6),
        )
        for s in steps
    ]
    total_log_increase = round(sum(sp.log_increase for sp in step_predictions), 6)

    first = steps[0]
    first_pred = step_predictions[0]
    model_result = ComBaseModelResult(
        model_type=ModelType.GROWTH,
        engine_type=EngineType.COMBASE_LOCAL,
        mu_max=first_pred.mu_max,
        doubling_time_hours=0.693 / first_pred.mu_max if first_pred.mu_max > 0 else None,
        organism=ComBaseOrganism.SALMONELLA,
        temperature_used=first.temperature_celsius,
        ph_used=6.5,
        aw_used=0.99,
        factor4_type_used=Factor4Type.NONE,
        factor4_value_used=None,
    )

    exec_payload = ComBaseExecutionPayload(
        engine_type=EngineType.COMBASE_LOCAL,
        model_type=ModelType.GROWTH,
        model_selection=ComBaseModelSelection(
            organism=ComBaseOrganism.SALMONELLA,
            model_type=ModelType.GROWTH,
            factor4_type=Factor4Type.NONE,
        ),
        parameters=ComBaseParameters(
            temperature_celsius=first.temperature_celsius,
            ph=6.5,
            water_activity=0.99,
        ),
        time_temperature_profile=profile,
    )

    exec_result = ComBaseExecutionResult(
        engine_type=EngineType.COMBASE_LOCAL,
        model_result=model_result,
        step_predictions=step_predictions,
        total_log_increase=total_log_increase,
    )

    state = SessionState(
        user_input="test query",
        status=SessionStatus.COMPLETED,
        execution_payload=exec_payload,
        execution_result=exec_result,
    )

    return TranslationResult(state)


@pytest.fixture
def patch_orchestrator_factory(monkeypatch: pytest.MonkeyPatch):
    """
    Return a helper that patches get_orchestrator in the translation route
    to return a fake orchestrator whose .translate() yields the given TranslationResult.
    """
    def _patch(result: TranslationResult):
        fake = MagicMock()
        fake.translate = AsyncMock(return_value=result)
        import app.api.routes.translation as route_module
        monkeypatch.setattr(route_module, "get_orchestrator", lambda: fake)
        return fake

    return _patch


class TestTranslateEndpointMultiStep:
    """
    Tests for the /translate endpoint's exposure of multi-step profile data.

    Regression guard: the route used to drop profile.steps and
    exec_result.step_predictions before returning to the caller.
    """

    @pytest.mark.asyncio
    async def test_single_step_response_includes_step_breakdown(
        self, async_client: AsyncClient, patch_orchestrator_factory
    ):
        """Single-step translations still populate steps[] and step_predictions[] with length 1."""
        result = _build_translation_result([(25.0, 180.0)])
        patch_orchestrator_factory(result)

        response = await async_client.post(
            "/api/v1/translate",
            json={"query": "Raw chicken at 25C for 3 hours"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        pred = data["prediction"]
        assert pred["is_multi_step"] is False
        assert len(pred["steps"]) == 1
        assert len(pred["step_predictions"]) == 1
        assert pred["steps"][0]["step_order"] == 1
        assert pred["steps"][0]["temperature_celsius"] == 25.0
        assert pred["steps"][0]["duration_minutes"] == 180.0
        assert pred["step_predictions"][0]["temperature_celsius"] == 25.0

    @pytest.mark.asyncio
    async def test_multi_step_response_exposes_per_step_data(
        self, async_client: AsyncClient, patch_orchestrator_factory
    ):
        """Multi-step translations expose full per-step breakdown with is_multi_step=True."""
        result = _build_translation_result([(28.0, 45.0), (22.0, 60.0), (4.0, 120.0)])
        patch_orchestrator_factory(result)

        response = await async_client.post(
            "/api/v1/translate",
            json={"query": "chicken through warm car, counter, then fridge"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        pred = data["prediction"]

        assert pred["is_multi_step"] is True
        assert len(pred["steps"]) == 3
        assert len(pred["step_predictions"]) == 3

        # Order is preserved 1..3
        assert [s["step_order"] for s in pred["steps"]] == [1, 2, 3]
        assert [sp["step_order"] for sp in pred["step_predictions"]] == [1, 2, 3]

        # Input side: temperatures + durations as submitted
        assert [s["temperature_celsius"] for s in pred["steps"]] == [28.0, 22.0, 4.0]
        assert [s["duration_minutes"] for s in pred["steps"]] == [45.0, 60.0, 120.0]

        # Output side: per-step predictions reconcile to the aggregate total
        sum_log = sum(sp["log_increase"] for sp in pred["step_predictions"])
        assert sum_log == pytest.approx(pred["total_log_increase"])

        # Scalar summary still reflects first-step (documented back-compat behavior)
        assert pred["temperature_celsius"] == 28.0
        # Aggregate duration is the sum
        assert pred["duration_minutes"] == pytest.approx(225.0)

    @pytest.mark.asyncio
    async def test_empty_step_predictions_does_not_crash(
        self, async_client: AsyncClient, patch_orchestrator_factory
    ):
        """
        If an engine result has step_predictions=[] (e.g., a legacy or partial result),
        the route must still populate steps[] from the profile and return an empty
        step_predictions list rather than raising.
        """
        result = _build_translation_result([(25.0, 180.0)])
        # Simulate a legacy/partial execution result where per-step data was not recorded
        result.state.execution_result.step_predictions = []

        patch_orchestrator_factory(result)

        response = await async_client.post(
            "/api/v1/translate",
            json={"query": "Raw chicken at 25C for 3 hours"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        pred = data["prediction"]
        # steps[] still comes from the profile (which is always populated)
        assert len(pred["steps"]) == 1
        # step_predictions[] round-trips as empty — no crash, no inferred entries
        assert pred["step_predictions"] == []
        assert pred["is_multi_step"] is False

    @pytest.mark.asyncio
    async def test_schema_advertises_new_fields(self, async_client: AsyncClient):
        """OpenAPI schema exposes is_multi_step, steps, and step_predictions on PredictionResult."""
        response = await async_client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        pred_schema = schema["components"]["schemas"]["PredictionResult"]
        props = pred_schema["properties"]
        assert "is_multi_step" in props
        assert "steps" in props
        assert "step_predictions" in props
        assert "StepInput" in schema["components"]["schemas"]
        assert "StepPrediction" in schema["components"]["schemas"]