"""
Translation API schemas.

Request and response models for the translation endpoint.
Translates natural language queries into model-ready payloads.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import (
    ModelType,
    SessionStatus,
)


# =============================================================================
# REQUEST
# =============================================================================

class TranslationRequest(BaseModel):
    """
    Request body for translation endpoint.
    """
    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Natural language food safety query",
        examples=[
            "I left raw chicken on the counter for 3 hours at room temperature",
            "Is cooked rice safe after sitting out overnight?",
            "Ground beef was in my car for 2 hours at 30°C",
        ],
    )
    model_type: ModelType | None = Field(
        default=None,
        description="Type of prediction model. If not provided, inferred from query context.",
    )
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "query": "Raw chicken left out for 3 hours at room temperature",
                },
                {
                    "query": "Cooking chicken to 75°C for 5 minutes",
                },
                {
                    "query": "Marinating raw fish in vinegar for preservation",
                }
            ]
        }
    }


# =============================================================================
# RESPONSE COMPONENTS
# =============================================================================

class ProvenanceInfo(BaseModel):
    """Provenance information for a grounded value."""
    field: str = Field(description="Field name")
    value: str = Field(description="Value used")
    source: str = Field(description="Source of the value")
    confidence: float = Field(description="Confidence in the value")
    notes: str | None = Field(default=None, description="Additional notes")


class WarningInfo(BaseModel):
    """Warning or correction applied during translation."""
    type: str = Field(description="Warning type")
    message: str = Field(description="Warning message")
    field: str | None = Field(default=None, description="Affected field")


class StepInput(BaseModel):
    """A single time-temperature step as submitted to the engine."""
    step_order: int = Field(description="Step order (1-indexed)")
    temperature_celsius: float = Field(description="Temperature during this step (°C)")
    duration_minutes: float = Field(description="Duration of this step (minutes)")


class StepPrediction(BaseModel):
    """Per-step growth prediction output from the engine."""
    step_order: int = Field(description="Step order (1-indexed)")
    temperature_celsius: float = Field(description="Temperature during this step (°C)")
    duration_minutes: float = Field(description="Duration of this step (minutes)")
    mu_max: float = Field(description="Growth rate at this step's temperature (1/h)")
    log_increase: float = Field(description="log10 CFU change during this step")


class PredictionResult(BaseModel):
    """Prediction results from the model."""
    # Model info
    organism: str = Field(description="Organism modeled")
    model_type: str = Field(description="Type of model used")
    engine: str = Field(description="Prediction engine used")

    # Parameters used (scalar summary — first-step values for multi-step scenarios)
    temperature_celsius: float = Field(description="Temperature used (°C)")
    duration_minutes: float = Field(description="Duration used (minutes) — total across all steps")
    ph: float = Field(description="pH used")
    water_activity: float = Field(description="Water activity used")

    # Results (scalar summary)
    mu_max: float = Field(description="Maximum growth rate (1/h) — first-step value for multi-step scenarios")
    doubling_time_hours: float | None = Field(description="Doubling time (hours) — first-step value for multi-step scenarios")
    total_log_increase: float = Field(description="Total log10 CFU change across all steps")

    # Multi-step breakdown (always populated; length 1 for single-step scenarios)
    is_multi_step: bool = Field(
        default=False,
        description="Whether the scenario had more than one time-temperature step",
    )
    steps: list[StepInput] = Field(
        default_factory=list,
        description="Time-temperature steps submitted to the engine",
    )
    step_predictions: list[StepPrediction] = Field(
        default_factory=list,
        description="Per-step growth predictions returned by the engine",
    )

    # Description
    growth_description: str = Field(description="Human-readable growth description")


# =============================================================================
# RESPONSE
# =============================================================================

class TranslationResponse(BaseModel):
    """
    Response from translation endpoint.
    """
    # Status
    success: bool = Field(description="Whether translation succeeded")
    session_id: str = Field(description="Unique session identifier")
    status: SessionStatus = Field(description="Final session status")
    
    # Timing
    created_at: datetime = Field(description="When the request was received")
    completed_at: datetime = Field(description="When processing completed")
    
    # Original input
    original_query: str = Field(description="The original user query")
    
    # Results (only if success=True)
    prediction: PredictionResult | None = Field(
        default=None,
        description="Prediction results",
    )
    
    # Provenance (transparency)
    provenance: list[ProvenanceInfo] = Field(
        default_factory=list,
        description="How each value was determined",
    )
    
    # Warnings and corrections
    warnings: list[WarningInfo] = Field(
        default_factory=list,
        description="Warnings and corrections applied",
    )
    
    # Confidence
    overall_confidence: float | None = Field(
        default=None,
        description="Overall confidence in the translation (0-1)",
    )
    
    # Error (only if success=False)
    error: str | None = Field(
        default=None,
        description="Error message if translation failed",
    )
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "session_id": "abc-123",
                    "status": "completed",
                    "created_at": "2024-01-15T10:30:00Z",
                    "completed_at": "2024-01-15T10:30:02Z",
                    "original_query": "Raw chicken left out for 3 hours",
                    "prediction": {
                        "organism": "Salmonella",
                        "model_type": "growth",
                        "engine": "combase_local",
                        "temperature_celsius": 25.0,
                        "duration_minutes": 180.0,
                        "ph": 6.0,
                        "water_activity": 0.99,
                        "mu_max": 0.42,
                        "doubling_time_hours": 1.65,
                        "total_log_increase": 0.78,
                        "is_multi_step": False,
                        "steps": [
                            {"step_order": 1, "temperature_celsius": 25.0, "duration_minutes": 180.0}
                        ],
                        "step_predictions": [
                            {
                                "step_order": 1,
                                "temperature_celsius": 25.0,
                                "duration_minutes": 180.0,
                                "mu_max": 0.42,
                                "log_increase": 0.78,
                            }
                        ],
                        "growth_description": "Moderate growth: ~0.8 log increase (6x population increase)",
                    },
                    "overall_confidence": 0.82,
                },
                {
                    "success": True,
                    "session_id": "def-456",
                    "status": "completed",
                    "created_at": "2024-01-15T10:31:00Z",
                    "completed_at": "2024-01-15T10:31:02Z",
                    "original_query": "Raw chicken in a warm car at 28°C for 45 min, then on the counter at 22°C for 1 hour, then fridge at 4°C for 2 hours",
                    "prediction": {
                        "organism": "Salmonella",
                        "model_type": "growth",
                        "engine": "combase_local",
                        "temperature_celsius": 28.0,
                        "duration_minutes": 225.0,
                        "ph": 6.0,
                        "water_activity": 0.99,
                        "mu_max": 0.55,
                        "doubling_time_hours": 1.26,
                        "total_log_increase": 1.10,
                        "is_multi_step": True,
                        "steps": [
                            {"step_order": 1, "temperature_celsius": 28.0, "duration_minutes": 45.0},
                            {"step_order": 2, "temperature_celsius": 22.0, "duration_minutes": 60.0},
                            {"step_order": 3, "temperature_celsius": 4.0, "duration_minutes": 120.0},
                        ],
                        "step_predictions": [
                            {"step_order": 1, "temperature_celsius": 28.0, "duration_minutes": 45.0, "mu_max": 0.55, "log_increase": 0.72},
                            {"step_order": 2, "temperature_celsius": 22.0, "duration_minutes": 60.0, "mu_max": 0.32, "log_increase": 0.38},
                            {"step_order": 3, "temperature_celsius": 4.0, "duration_minutes": 120.0, "mu_max": 0.0, "log_increase": 0.0},
                        ],
                        "growth_description": "Significant growth: 1.1 log increase (~13x population)",
                    },
                    "overall_confidence": 0.78,
                },
            ]
        }
    }