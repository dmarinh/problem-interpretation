"""
Unit tests for execution models.
"""

import pytest
from pydantic import ValidationError

from app.models.execution import (
    # Base
    TimeTemperatureStep,
    TimeTemperatureProfile,
    # ComBase
    ComBaseParameters,
    ComBaseModelSelection,
    ComBaseExecutionPayload,
    ComBaseModelResult,
    ComBaseExecutionResult,
)
from app.models.enums import (
    ModelType,
    ComBaseOrganism,
    Factor4Type,
    EngineType,
)


class TestTimeTemperatureProfile:
    """Tests for TimeTemperatureProfile model."""
    
    def test_single_step(self):
        """Should accept single step profile."""
        profile = TimeTemperatureProfile(
            is_multi_step=False,
            steps=[
                TimeTemperatureStep(
                    temperature_celsius=25.0,
                    duration_minutes=180.0,
                    step_order=1,
                )
            ],
            total_duration_minutes=180.0,
        )
        
        assert len(profile.steps) == 1
        assert profile.total_duration_minutes == 180.0
    
    def test_multi_step(self):
        """Should accept multi-step profile."""
        profile = TimeTemperatureProfile(
            is_multi_step=True,
            steps=[
                TimeTemperatureStep(
                    temperature_celsius=20.0,
                    duration_minutes=60.0,
                    step_order=1,
                ),
                TimeTemperatureStep(
                    temperature_celsius=4.0,
                    duration_minutes=480.0,
                    step_order=2,
                ),
            ],
            total_duration_minutes=540.0,
        )
        
        assert len(profile.steps) == 2
        assert profile.is_multi_step is True
    
    def test_requires_at_least_one_step(self):
        """Should require at least one step."""
        with pytest.raises(ValidationError):
            TimeTemperatureProfile(
                is_multi_step=False,
                steps=[],
                total_duration_minutes=0.0,
            )
    
    def test_validates_total_duration(self):
        """Should validate total duration matches steps."""
        with pytest.raises(ValidationError) as exc_info:
            TimeTemperatureProfile(
                is_multi_step=False,
                steps=[
                    TimeTemperatureStep(
                        temperature_celsius=25.0,
                        duration_minutes=180.0,
                        step_order=1,
                    )
                ],
                total_duration_minutes=100.0,  # Wrong!
            )
        
        assert "does not match sum" in str(exc_info.value)
    
    def test_validates_step_order(self):
        """Should validate step ordering."""
        with pytest.raises(ValidationError) as exc_info:
            TimeTemperatureProfile(
                is_multi_step=True,
                steps=[
                    TimeTemperatureStep(
                        temperature_celsius=25.0,
                        duration_minutes=60.0,
                        step_order=2,  # Wrong - should be 1
                    ),
                    TimeTemperatureStep(
                        temperature_celsius=4.0,
                        duration_minutes=60.0,
                        step_order=1,  # Wrong - should be 2
                    ),
                ],
                total_duration_minutes=120.0,
            )
        
        assert "must be in order" in str(exc_info.value)


class TestComBaseParameters:
    """Tests for ComBaseParameters model."""
    
    def test_valid_parameters(self):
        """Should accept valid parameters."""
        params = ComBaseParameters(
            temperature_celsius=25.0,
            ph=7.0,
            water_activity=0.99,
        )
        
        assert params.temperature_celsius == 25.0
        assert params.ph == 7.0
        assert params.water_activity == 0.99
    
    def test_with_factor4(self):
        """Should accept fourth factor."""
        params = ComBaseParameters(
            temperature_celsius=25.0,
            ph=7.0,
            water_activity=0.99,
            factor4_type=Factor4Type.CO2,
            factor4_value=10.0,
        )
        
        assert params.factor4_type == Factor4Type.CO2
        assert params.factor4_value == 10.0
    
    def test_factor4_requires_value(self):
        """Should require factor4_value when factor4_type is set."""
        with pytest.raises(ValidationError) as exc_info:
            ComBaseParameters(
                temperature_celsius=25.0,
                ph=7.0,
                water_activity=0.99,
                factor4_type=Factor4Type.CO2,
            )
        
        assert "factor4_value required" in str(exc_info.value)
    
    def test_ph_bounds(self):
        """pH should be bounded 0-14."""
        with pytest.raises(ValidationError):
            ComBaseParameters(
                temperature_celsius=25.0,
                ph=15.0,
                water_activity=0.99,
            )
    
    def test_water_activity_bounds(self):
        """Water activity should be bounded 0-1."""
        with pytest.raises(ValidationError):
            ComBaseParameters(
                temperature_celsius=25.0,
                ph=7.0,
                water_activity=1.5,
            )


class TestComBaseExecutionPayload:
    """Tests for ComBaseExecutionPayload model."""
    
    def test_complete_payload(self):
        """Should accept complete valid payload."""
        payload = ComBaseExecutionPayload(
            model_selection=ComBaseModelSelection(
                organism=ComBaseOrganism.LISTERIA_MONOCYTOGENES,
                model_type=ModelType.GROWTH,
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
        
        assert payload.model_selection.organism == ComBaseOrganism.LISTERIA_MONOCYTOGENES
        assert payload.parameters.temperature_celsius == 25.0
        assert payload.engine_type == EngineType.COMBASE_LOCAL
        assert payload.model_type == ModelType.GROWTH  # Synced from model_selection


class TestComBaseModelResult:
    """Tests for ComBaseModelResult model."""
    
    def test_growth_result(self):
        """Should accept growth model result."""
        result = ComBaseModelResult(
            mu_max=0.5,
            doubling_time_hours=1.4,
            model_type=ModelType.GROWTH,
            organism=ComBaseOrganism.SALMONELLA,
            temperature_used=25.0,
            ph_used=7.0,
            aw_used=0.99,
        )
        
        assert result.mu_max == 0.5
        assert result.doubling_time_hours == 1.4
        assert result.factor4_type_used == Factor4Type.NONE
    
    def test_growth_result_with_factor4(self):
        """Should include factor4 in result."""
        result = ComBaseModelResult(
            mu_max=0.4,
            doubling_time_hours=1.7,
            model_type=ModelType.GROWTH,
            organism=ComBaseOrganism.LISTERIA_MONOCYTOGENES,
            temperature_used=25.0,
            ph_used=7.0,
            aw_used=0.99,
            factor4_type_used=Factor4Type.CO2,
            factor4_value_used=10.0,
        )
        
        assert result.factor4_type_used == Factor4Type.CO2
        assert result.factor4_value_used == 10.0
    
    def test_inactivation_result(self):
        """Should accept inactivation model result (negative mu)."""
        result = ComBaseModelResult(
            mu_max=-2.5,
            doubling_time_hours=None,
            model_type=ModelType.THERMAL_INACTIVATION,
            organism=ComBaseOrganism.SALMONELLA,
            temperature_used=60.0,
            ph_used=7.0,
            aw_used=0.99,
        )
        
        assert result.mu_max == -2.5
        assert result.doubling_time_hours is None