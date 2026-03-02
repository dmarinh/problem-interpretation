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


class PredictionResult(BaseModel):
    """Prediction results from the model."""
    # Model info
    organism: str = Field(description="Organism modeled")
    model_type: str = Field(description="Type of model used")
    engine: str = Field(description="Prediction engine used")
    
    # Parameters used
    temperature_celsius: float = Field(description="Temperature used (°C)")
    duration_minutes: float = Field(description="Duration used (minutes)")
    ph: float = Field(description="pH used")
    water_activity: float = Field(description="Water activity used")
    
    # Results
    mu_max: float = Field(description="Maximum growth rate (1/h)")
    doubling_time_hours: float | None = Field(description="Doubling time (hours)")
    total_log_increase: float = Field(description="Total log10 CFU change")
    
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
                        "growth_description": "Moderate growth: ~0.8 log increase (6x population increase)",
                    },
                    "overall_confidence": 0.82,
                }
            ]
        }
    }