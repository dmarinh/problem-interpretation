"""
Unit tests for ComBase engine.
"""

import pytest
from pathlib import Path

from app.engines.combase.engine import ComBaseEngine, get_combase_engine, reset_combase_engine
from app.models.enums import ModelType, ComBaseOrganism, Factor4Type, EngineType
from app.models.execution.base import TimeTemperatureStep, TimeTemperatureProfile
from app.models.execution.combase import (
    ComBaseParameters,
    ComBaseModelSelection,
    ComBaseExecutionPayload,
)


@pytest.fixture
def engine() -> ComBaseEngine:
    """Create and load engine."""
    eng = ComBaseEngine()
    csv_path = Path("data/combase_models.csv")
    if csv_path.exists():
        eng.load_models(csv_path)
    return eng


@pytest.fixture
def simple_payload() -> ComBaseExecutionPayload:
    """Create a simple test payload."""
    return ComBaseExecutionPayload(
        model_selection=ComBaseModelSelection(
            organism=ComBaseOrganism.LISTERIA_MONOCYTOGENES,
            model_type=ModelType.GROWTH,
            factor4_type=Factor4Type.NONE,
        ),
        parameters=ComBaseParameters(
            temperature_celsius=25.0,
            ph=7.0,
            water_activity=0.99,
        ),
        time_temperature_profile=TimeTemperatureProfile(
            is_multi_step=False,
            steps=[
                TimeTemperatureStep(
                    temperature_celsius=25.0,
                    duration_minutes=180.0,
                    step_order=1,
                )
            ],
            total_duration_minutes=180.0,
        ),
    )


class TestComBaseEngine:
    """Tests for ComBaseEngine."""
    
    def test_engine_not_loaded(self):
        """Should report not available before loading."""
        eng = ComBaseEngine()
        
        assert eng.is_available is False
    
    def test_load_models(self, engine):
        """Should load models from CSV."""
        if not engine.is_available:
            pytest.skip("combase_models.csv not found")
        
        assert engine.is_available is True
        assert len(engine.registry) > 0
    
    @pytest.mark.asyncio
    async def test_execute_growth(self, engine, simple_payload):
        """Should execute growth prediction."""
        if not engine.is_available:
            pytest.skip("combase_models.csv not found")
        
        result = await engine.execute(simple_payload)
        
        assert result.model_result.mu_max > 0
        assert result.model_result.doubling_time_hours > 0
        assert result.total_log_increase > 0
        assert result.engine_type == EngineType.COMBASE_LOCAL
    
    @pytest.mark.asyncio
    async def test_execute_multi_step(self, engine):
        """Should execute multi-step prediction."""
        if not engine.is_available:
            pytest.skip("combase_models.csv not found")
        
        payload = ComBaseExecutionPayload(
            model_selection=ComBaseModelSelection(
                organism=ComBaseOrganism.SALMONELLA,
                model_type=ModelType.GROWTH,
                factor4_type=Factor4Type.NONE,
            ),
            parameters=ComBaseParameters(
                temperature_celsius=25.0,
                ph=7.0,
                water_activity=0.99,
            ),
            time_temperature_profile=TimeTemperatureProfile(
                is_multi_step=True,
                steps=[
                    TimeTemperatureStep(
                        temperature_celsius=25.0,
                        duration_minutes=60.0,
                        step_order=1,
                    ),
                    TimeTemperatureStep(
                        temperature_celsius=4.0,
                        duration_minutes=240.0,
                        step_order=2,
                    ),
                ],
                total_duration_minutes=300.0,
            ),
        )
        
        result = await engine.execute(payload)
        
        assert len(result.step_predictions) == 2
        assert result.step_predictions[0].step_order == 1
        assert result.step_predictions[1].step_order == 2
        assert result.step_predictions[0].mu_max > 0  # check mu_max per step
        assert result.step_predictions[1].mu_max > 0
        # First step at 25°C should have more growth than second at 4°C
        assert result.step_predictions[0].log_increase > result.step_predictions[1].log_increase
    
    @pytest.mark.asyncio
    async def test_execute_inactivation(self, engine):
        """Should execute thermal inactivation prediction."""
        if not engine.is_available:
            pytest.skip("combase_models.csv not found")
        
        payload = ComBaseExecutionPayload(
            model_selection=ComBaseModelSelection(
                organism=ComBaseOrganism.SALMONELLA,
                model_type=ModelType.THERMAL_INACTIVATION,
                factor4_type=Factor4Type.NONE,
            ),
            parameters=ComBaseParameters(
                temperature_celsius=60.0,
                ph=7.0,
                water_activity=0.99,
            ),
            time_temperature_profile=TimeTemperatureProfile(
                is_multi_step=False,
                steps=[
                    TimeTemperatureStep(
                        temperature_celsius=60.0,
                        duration_minutes=10.0,
                        step_order=1,
                    )
                ],
                total_duration_minutes=10.0,
            ),
        )
        
        result = await engine.execute(payload)
        
        assert result.model_result.mu_max < 0  # Negative for inactivation
        assert result.total_log_increase < 0  # Log reduction
    
    @pytest.mark.asyncio
    async def test_model_not_found(self, engine):
        """Should raise error for unknown model."""
        if not engine.is_available:
            pytest.skip("combase_models.csv not found")
        
        payload = ComBaseExecutionPayload(
            model_selection=ComBaseModelSelection(
                organism=ComBaseOrganism.PSEUDOMONAS,
                model_type=ModelType.THERMAL_INACTIVATION,  # Doesn't exist
                factor4_type=Factor4Type.NONE,
            ),
            parameters=ComBaseParameters(
                temperature_celsius=60.0,
                ph=7.0,
                water_activity=0.99,
            ),
            time_temperature_profile=TimeTemperatureProfile(
                is_multi_step=False,
                steps=[
                    TimeTemperatureStep(
                        temperature_celsius=60.0,
                        duration_minutes=10.0,
                        step_order=1,
                    )
                ],
                total_duration_minutes=10.0,
            ),
        )
        
        with pytest.raises(ValueError, match="Model not found"):
            await engine.execute(payload)
    
    @pytest.mark.asyncio
    async def test_health_check_loaded(self, engine):
        """Should report healthy when loaded."""
        if not engine.is_available:
            pytest.skip("combase_models.csv not found")
        
        health = await engine.health_check()
        
        assert health["healthy"] is True
        assert "models" in health["message"].lower()
    
    @pytest.mark.asyncio
    async def test_health_check_not_loaded(self):
        """Should report unhealthy when not loaded."""
        eng = ComBaseEngine()
        
        health = await eng.health_check()
        
        assert health["healthy"] is False


class TestComBaseEngineSingleton:
    """Tests for singleton management."""
    
    def test_get_engine_returns_instance(self):
        """get_combase_engine should return an engine."""
        reset_combase_engine()
        engine = get_combase_engine()
        
        assert isinstance(engine, ComBaseEngine)
    
    def test_get_engine_returns_same_instance(self):
        """get_combase_engine should return singleton."""
        reset_combase_engine()
        engine1 = get_combase_engine()
        engine2 = get_combase_engine()
        
        assert engine1 is engine2