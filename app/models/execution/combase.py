"""
ComBase Execution Models

Models specific to the ComBase broth model engine.
"""

from pydantic import BaseModel, Field, model_validator

from app.models.enums import (
    ModelType,
    ComBaseOrganism,
    Factor4Type,
    EngineType,
)
from app.models.execution.base import (
    BaseExecutionPayload,
    BaseModelResult,
    BaseExecutionResult,
    TimeTemperatureProfile,
    GrowthPrediction,
)


# =============================================================================
# COMBASE-SPECIFIC PARAMETERS
# =============================================================================

class ComBaseParameters(BaseModel):
    """
    Parameters for a ComBase broth model execution.
    
    These are the actual values passed to the ComBase calculation.
    All values must be within the model's valid ranges.
    """
    # Required parameters
    temperature_celsius: float = Field(
        description="Temperature in Celsius"
    )
    ph: float = Field(
        ge=0.0,
        le=14.0,
        description="pH value"
    )
    water_activity: float = Field(
        ge=0.0,
        le=1.0,
        description="Water activity (aw)"
    )
    
    # Optional fourth factor
    factor4_type: Factor4Type = Field(
        default=Factor4Type.NONE,
        description="Type of fourth factor if applicable"
    )
    factor4_value: float | None = Field(
        default=None,
        description="Value of fourth factor (units depend on type)"
    )
    
    @model_validator(mode="after")
    def validate_factor4(self) -> "ComBaseParameters":
        """Ensure factor4_value is set if factor4_type is not NONE."""
        if self.factor4_type != Factor4Type.NONE and self.factor4_value is None:
            raise ValueError(f"factor4_value required when factor4_type is {self.factor4_type}")
        return self


class ComBaseModelSelection(BaseModel):
    """
    Selection of which ComBase model to run.
    
    Identifies the specific model by organism, model type, and factor4.
    """
    organism: ComBaseOrganism = Field(
        description="Target organism"
    )
    model_type: ModelType = Field(
        description="Type of model (growth, inactivation, survival)"
    )
    factor4_type: Factor4Type = Field(
        default=Factor4Type.NONE,
        description="Fourth factor type (determines which model variant)"
    )


# =============================================================================
# COMBASE EXECUTION PAYLOAD
# =============================================================================

class ComBaseExecutionPayload(BaseExecutionPayload):
    """
    Complete payload for ComBase model execution.
    
    This is what gets sent to the ComBase engine (local or API).
    """
    # Override engine_type with ComBase default
    engine_type: EngineType = Field(
        default=EngineType.COMBASE_LOCAL,
        description="Which engine implementation to use"
    )

    # Override with default to allow validator to set it
    model_type: ModelType = Field(
        default=ModelType.GROWTH,
        description="Type of model (synced from model_selection)"
    )
    
    # Model selection
    model_selection: ComBaseModelSelection = Field(
        description="Which model to run"
    )
    
    # Model parameters
    parameters: ComBaseParameters = Field(
        description="Environmental parameters for the model"
    )
    
    # Inherited from base:
    # - time_temperature_profile
    # - model_type (we can derive from model_selection)
    
    @model_validator(mode="after")
    def sync_model_type(self) -> "ComBaseExecutionPayload":
        """Ensure model_type matches model_selection."""
        # Use model_selection as source of truth
        object.__setattr__(self, "model_type", self.model_selection.model_type)
        return self


# =============================================================================
# COMBASE RESULTS
# =============================================================================

class ComBaseModelResult(BaseModelResult):
    """
    Result from a single ComBase model calculation.
    """
    # Override engine_type with ComBase default
    engine_type: EngineType = Field(
        default=EngineType.COMBASE_LOCAL,
        description="Which engine produced this result"
    )
    
    # Growth rate output
    mu_max: float = Field(
        description="Maximum specific growth rate (log10 CFU/h for growth, negative for inactivation)"
    )
    doubling_time_hours: float | None = Field(
        default=None,
        description="Doubling time in hours (for growth models only)"
    )
    
    # Organism
    organism: ComBaseOrganism = Field(
        description="Organism modeled"
    )
    
    # Parameters used (for traceability)
    temperature_used: float = Field(
        description="Temperature used in calculation"
    )
    ph_used: float = Field(
        description="pH used in calculation"
    )
    aw_used: float = Field(
        description="Water activity used in calculation"
    )
    factor4_type_used: Factor4Type = Field(
        default=Factor4Type.NONE,
        description="Fourth factor type used"
    )
    factor4_value_used: float | None = Field(
        default=None,
        description="Fourth factor value used"
    )


class ComBaseExecutionResult(BaseExecutionResult):
    """
    Complete result from ComBase execution.
    """
    # Override engine_type with ComBase default
    engine_type: EngineType = Field(
        default=EngineType.COMBASE_LOCAL,
        description="Which engine was used"
    )
    
    # ComBase-specific model result
    model_result: ComBaseModelResult = Field(
        description="Raw model calculation result"
    )
    
    # Inherited from base:
    # - step_predictions
    # - total_log_increase
    # - warnings