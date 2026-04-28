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

# =============================================================================
# AUDIT SCHEMA (verbose=true only)
# =============================================================================

class RunnerUpInfo(BaseModel):
    """A non-winning retrieval candidate."""
    doc_id: str | None
    content_preview: str | None
    embedding_score: float | None
    rerank_score: float | None


class RetrievalTopMatchInfo(BaseModel):
    """Full details of the top retrieval hit."""
    doc_id: str | None
    embedding_score: float | None
    rerank_score: float | None
    retrieved_text: str | None
    source_ids: list[str]
    full_citations: dict[str, str]


class RetrievalAuditInfo(BaseModel):
    """Retrieval details for one RAG call."""
    query: str
    top_match: RetrievalTopMatchInfo | None
    runners_up: list[RunnerUpInfo]


class ExtractionAuditInfo(BaseModel):
    """How the numeric value was extracted from retrieved text or rule lookup."""
    method: str | None
    raw_match: str | None
    parsed_range: list[float] | None
    # Rule-match details — present when method is "rule_match" or "embedding_fallback"
    matched_pattern: str | None = None
    conservative: bool | None = None
    notes: str | None = None
    # Embedding-fallback only
    similarity: float | None = None
    canonical_phrase: str | None = None


class StandardizationAuditInfo(BaseModel):
    """Structured record of the standardization event that touched this field.

    rule: one of "range_bound_selection", "range_clamp", "default_imputed"
    direction: "upper" or "lower" for range_bound_selection; null otherwise
    before_value: [min, max] for range_bound_selection; scalar for range_clamp; null for default_imputed
    after_value: the post-standardization value that reached the model (float for numeric fields, str for organism)
    reason: human-readable rationale
    """
    rule: str
    direction: str | None = None
    before_value: list[float] | float | None = None
    after_value: float | str
    reason: str


class FieldAuditEntry(BaseModel):
    """Complete per-field audit record."""
    final_value: float | str | None
    source: str
    retrieval: RetrievalAuditInfo | None
    extraction: ExtractionAuditInfo | None
    standardization: StandardizationAuditInfo | None


class ComBaseModelAuditInfo(BaseModel):
    """Which ComBase model was selected and why."""
    organism: str
    organism_id: str | None = None
    organism_display_name: str | None = None
    model_type: str
    model_id: int | None
    coefficients_str: str | None
    valid_ranges: dict[str, tuple[float, float]] | None
    selection_reason: str


class SystemAuditInfo(BaseModel):
    """Software and data state at time of prediction."""
    rag_store_hash: str | None
    rag_ingested_at: str | None
    source_csv_audit_date: str | None
    ptm_version: str | None
    combase_model_table_hash: str | None


class DefaultImputedInfo(BaseModel):
    """A conservative default substituted for a missing field."""
    field_name: str
    default_value: float | str
    reason: str


class RangeClampInfo(BaseModel):
    """A value that was clamped to the model's valid range."""
    field_name: str
    original_value: float
    clamped_value: float
    valid_min: float
    valid_max: float
    reason: str


class AuditSummary(BaseModel):
    """Cross-field audit summary."""
    range_clamps: list[RangeClampInfo] = Field(default_factory=list)
    defaults_imputed: list[DefaultImputedInfo] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AuditDetail(BaseModel):
    """Full verbose audit payload, returned only when verbose=true."""
    field_audit: dict[str, FieldAuditEntry]
    combase_model: ComBaseModelAuditInfo | None
    audit: AuditSummary
    system: SystemAuditInfo | None


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
    
    # Error (only if success=False)
    error: str | None = Field(
        default=None,
        description="Error message if translation failed",
    )

    # Full audit detail (only when verbose=true query parameter is set)
    audit: "AuditDetail | None" = Field(
        default=None,
        description="Full per-field audit trail (populated only when verbose=true)",
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
                },
            ]
        }
    }