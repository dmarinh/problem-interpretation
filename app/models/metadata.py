"""
Provenance and Metadata Models

Track the origin, confidence, and transformations of all values
in the interpretation pipeline.

Key Principles:
- Every value should be traceable to its source
- All corrections/defaults must be logged
- Confidence levels propagate through the pipeline
- Auditable for safety-critical decisions
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.models.enums import (
    BiasType,
    ClarificationReason,
    RetrievalConfidenceLevel,
    SessionStatus,
)


# =============================================================================
# VALUE SOURCES
# =============================================================================

class ValueSource(str, Enum):
    """Where a value came from."""
    USER_EXPLICIT = "user_explicit"           # User stated directly
    USER_INFERRED = "user_inferred"           # Inferred from user input
    FUZZY_MATCH = "fuzzy_match"               # Resolved via alias/fuzzy lookup
    RAG_RETRIEVAL = "rag_retrieval"           # Retrieved from knowledge base
    CONSERVATIVE_DEFAULT = "conservative_default"  # Safety default applied
    CLARIFICATION_RESPONSE = "clarification_response"  # From user clarification
    CLAMPED_TO_RANGE = "clamped_to_range"     # Adjusted to valid range
    CALCULATED = "calculated"                  # Derived from other values


class ValueProvenance(BaseModel):
    """
    Tracks the origin and confidence of a single value.
    
    Attached to any value that flows through the pipeline.
    """
    source: ValueSource = Field(
        description="Where this value came from"
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence in this value (0-1)"
    )
    original_value: str | float | None = Field(
        default=None,
        description="Original value before any transformation"
    )
    original_text: str | None = Field(
        default=None,
        description="Original text from user input (if applicable)"
    )
    retrieval_source: str | None = Field(
        default=None,
        description="Document/chunk ID if from RAG retrieval"
    )
    transformation_applied: str | None = Field(
        default=None,
        description="Description of any transformation applied"
    )


# =============================================================================
# BIAS CORRECTIONS
# =============================================================================

class BiasCorrection(BaseModel):
    """
    Record of a bias correction applied to a value.
    """
    bias_type: BiasType = Field(
        description="Type of bias that was corrected"
    )
    field_name: str = Field(
        description="Which field was corrected"
    )
    original_value: float | None = Field(
        description="Value before correction"
    )
    corrected_value: float = Field(
        description="Value after correction"
    )
    correction_reason: str = Field(
        description="Why this correction was applied"
    )
    correction_magnitude: float | None = Field(
        default=None,
        description="How much the value changed"
    )


class RangeClamp(BaseModel):
    """
    Record of a value being clamped to valid range.
    """
    field_name: str = Field(
        description="Which field was clamped"
    )
    original_value: float = Field(
        description="Value before clamping"
    )
    clamped_value: float = Field(
        description="Value after clamping"
    )
    valid_min: float = Field(
        description="Minimum valid value"
    )
    valid_max: float = Field(
        description="Maximum valid value"
    )
    reason: str = Field(
        description="Why this range applies (e.g., model constraint)"
    )


# =============================================================================
# RETRIEVAL METADATA
# =============================================================================

class RetrievalResult(BaseModel):
    """
    Metadata about a RAG retrieval operation.
    """
    query: str = Field(
        description="The query used for retrieval"
    )
    confidence_level: RetrievalConfidenceLevel = Field(
        description="Classification of retrieval confidence"
    )
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Raw confidence score"
    )
    source_document: str | None = Field(
        default=None,
        description="Source document identifier"
    )
    chunk_id: str | None = Field(
        default=None,
        description="Specific chunk identifier"
    )
    retrieved_text: str | None = Field(
        default=None,
        description="The text that was retrieved"
    )
    fallback_used: bool = Field(
        default=False,
        description="Whether a fallback/default was used due to low confidence"
    )


# =============================================================================
# CLARIFICATION TRACKING
# =============================================================================

class ClarificationRecord(BaseModel):
    """
    Record of a clarification exchange with the user.
    """
    turn_number: int = Field(
        ge=1,
        description="Which clarification turn (1, 2, 3...)"
    )
    reason: ClarificationReason = Field(
        description="Why clarification was needed"
    )
    question_asked: str = Field(
        description="The question that was asked"
    )
    user_response: str | None = Field(
        default=None,
        description="User's response (None if skipped/timed out)"
    )
    extracted_value: str | float | None = Field(
        default=None,
        description="Value extracted from response"
    )
    default_used: bool = Field(
        default=False,
        description="Whether default was used instead of user response"
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="When this clarification occurred"
    )


# =============================================================================
# SESSION METADATA
# =============================================================================

class InterpretationMetadata(BaseModel):
    """
    Complete metadata for an interpretation session.
    
    Aggregates all provenance, corrections, and confidence information.
    """
    # Session info
    session_id: str = Field(
        description="Unique session identifier"
    )
    status: SessionStatus = Field(
        default=SessionStatus.PENDING,
        description="Current session status"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When the session started"
    )
    completed_at: datetime | None = Field(
        default=None,
        description="When the session completed"
    )
    
    # Original input
    original_input: str = Field(
        description="The user's original input text"
    )
    
    # Provenance for key fields
    provenance: dict[str, ValueProvenance] = Field(
        default_factory=dict,
        description="Provenance for each field (field_name -> provenance)"
    )
    
    # Corrections applied
    bias_corrections: list[BiasCorrection] = Field(
        default_factory=list,
        description="Bias corrections that were applied"
    )
    range_clamps: list[RangeClamp] = Field(
        default_factory=list,
        description="Range clamps that were applied"
    )
    
    # Retrievals performed
    retrievals: list[RetrievalResult] = Field(
        default_factory=list,
        description="RAG retrievals that were performed"
    )
    
    # Clarifications
    clarifications: list[ClarificationRecord] = Field(
        default_factory=list,
        description="Clarification exchanges with user"
    )
    
    # Overall confidence
    overall_confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Aggregate confidence in the interpretation"
    )
    
    # Warnings and notes
    warnings: list[str] = Field(
        default_factory=list,
        description="Warnings generated during interpretation"
    )
    notes: list[str] = Field(
        default_factory=list,
        description="Additional notes for transparency"
    )
    
    def add_provenance(self, field_name: str, provenance: ValueProvenance) -> None:
        """Add provenance for a field."""
        self.provenance[field_name] = provenance
    
    def add_bias_correction(self, correction: BiasCorrection) -> None:
        """Record a bias correction."""
        self.bias_corrections.append(correction)
    
    def add_range_clamp(self, clamp: RangeClamp) -> None:
        """Record a range clamp."""
        self.range_clamps.append(clamp)
    
    def add_retrieval(self, retrieval: RetrievalResult) -> None:
        """Record a retrieval operation."""
        self.retrievals.append(retrieval)
    
    def add_clarification(self, clarification: ClarificationRecord) -> None:
        """Record a clarification exchange."""
        self.clarifications.append(clarification)
    
    def add_warning(self, warning: str) -> None:
        """Add a warning."""
        self.warnings.append(warning)
    
    def compute_overall_confidence(self) -> float:
        """
        Compute aggregate confidence from all sources.
        
        Uses minimum confidence across all provenance records,
        with penalties for bias corrections and low-confidence retrievals.
        """
        if not self.provenance:
            return 1.0
        
        # Start with minimum field confidence
        min_confidence = min(p.confidence for p in self.provenance.values())
        
        # Penalty for each bias correction (5% each)
        bias_penalty = len(self.bias_corrections) * 0.05
        
        # Penalty for each range clamp (10% each)
        clamp_penalty = len(self.range_clamps) * 0.10
        
        # Penalty for low-confidence retrievals
        low_conf_retrievals = sum(
            1 for r in self.retrievals 
            if r.confidence_level in (RetrievalConfidenceLevel.LOW, RetrievalConfidenceLevel.FAILED)
        )
        retrieval_penalty = low_conf_retrievals * 0.10
        
        # Compute final confidence
        overall = min_confidence - bias_penalty - clamp_penalty - retrieval_penalty
        self.overall_confidence = max(0.0, min(1.0, overall))
        
        return self.overall_confidence