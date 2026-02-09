"""
Base Execution Models

Abstract base classes that define the interface for all engine implementations.
New engines should inherit from these bases.
"""

from pydantic import BaseModel, Field, model_validator

from app.models.enums import EngineType, ModelType


# =============================================================================
# TIME-TEMPERATURE PROFILE (Shared across all engines)
# =============================================================================

class TimeTemperatureStep(BaseModel):
    """
    A single step in a time-temperature profile.
    
    This is engine-agnostic and used by all implementations.
    """
    temperature_celsius: float = Field(
        description="Temperature in Celsius"
    )
    duration_minutes: float = Field(
        gt=0,
        description="Duration in minutes (must be positive)"
    )
    step_order: int = Field(
        ge=1,
        description="Order in the sequence (1-indexed)"
    )


class TimeTemperatureProfile(BaseModel):
    """
    Complete time-temperature profile for execution.
    
    Engine-agnostic representation of the thermal history.
    """
    is_multi_step: bool = Field(
        default=False,
        description="Whether this is a multi-step profile"
    )
    steps: list[TimeTemperatureStep] = Field(
        min_length=1,
        description="Time-temperature steps (at least one required)"
    )
    total_duration_minutes: float = Field(
        gt=0,
        description="Total duration across all steps"
    )
    
    @model_validator(mode="after")
    def validate_steps(self) -> "TimeTemperatureProfile":
        """Validate step consistency."""
        # Check step ordering
        orders = [s.step_order for s in self.steps]
        if orders != sorted(orders):
            raise ValueError("Steps must be in order")
        if orders != list(range(1, len(orders) + 1)):
            raise ValueError("Step orders must be sequential starting from 1")
        
        # Check total duration matches sum
        calculated_total = sum(s.duration_minutes for s in self.steps)
        if abs(calculated_total - self.total_duration_minutes) > 0.01:
            raise ValueError(
                f"total_duration_minutes ({self.total_duration_minutes}) "
                f"does not match sum of steps ({calculated_total})"
            )
        
        # Check multi-step flag
        if len(self.steps) > 1 and not self.is_multi_step:
            raise ValueError("is_multi_step must be True for multiple steps")
        
        return self


# =============================================================================
# BASE CLASSES FOR ENGINE IMPLEMENTATIONS
# =============================================================================

class BaseExecutionPayload(BaseModel):
    """
    Base class for all engine execution payloads.
    
    Each engine implementation should inherit from this and add
    its specific parameters.
    """
    engine_type: EngineType = Field(
        description="Which engine implementation to use"
    )
    time_temperature_profile: TimeTemperatureProfile = Field(
        description="Time-temperature history"
    )
    model_type: ModelType = Field(
        description="Type of model (growth, inactivation, survival)"
    )


class BaseModelResult(BaseModel):
    """
    Base class for model calculation results.
    
    Each engine should return results that inherit from this.
    """
    model_type: ModelType = Field(
        description="Type of model that was run"
    )
    engine_type: EngineType = Field(
        description="Which engine produced this result"
    )


class GrowthPrediction(BaseModel):
    """
    Growth prediction for a single time-temperature step.
    
    Engine-agnostic representation of growth during one step.
    """
    step_order: int = Field(
        description="Which step this prediction is for"
    )
    duration_minutes: float = Field(
        description="Duration of this step"
    )
    temperature_celsius: float = Field(
        description="Temperature during this step"
    )
    mu_max: float = Field(
        description="Growth rate at this step's temperature (1/h)"
    )
    log_increase: float = Field(
        description="Predicted log10 CFU increase during this step"
    )


class BaseExecutionResult(BaseModel):
    """
    Base class for complete execution results.
    
    Includes predictions and summary statistics.
    """
    # Model result (engine-specific, set by subclass)
    
    # Growth predictions per step
    step_predictions: list[GrowthPrediction] = Field(
        default_factory=list,
        description="Predictions for each time-temperature step"
    )
    
    # Summary
    total_log_increase: float = Field(
        description="Total log10 CFU increase across all steps"
    )
    
    # Metadata
    engine_type: EngineType = Field(
        description="Which engine was used"
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Any warnings generated during execution"
    )