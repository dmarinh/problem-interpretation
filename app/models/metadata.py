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
    ClarificationReason,
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


class RangeBoundSelection(BaseModel):
    """
    Structured record of a range-bound selection performed by StandardizationService.

    Range values arrive from grounding with both bounds preserved (range_pending=True on
    the ValueProvenance).  StandardizationService picks the conservative bound and writes
    this block.  It does NOT appear in bias_corrections or range_clamps — it is a
    deterministic, mechanical operation, not a safety-event-level correction.
    """
    rule: str = Field(
        default="range_bound_selection",
        description="Always 'range_bound_selection'"
    )
    direction: str = Field(
        description="'upper' for growth/survival models, 'lower' for thermal inactivation"
    )
    reason: str = Field(
        description="Plain-English rationale for end users"
    )
    before_value: list[float] = Field(
        description="[min, max] — the original range from grounding"
    )
    after_value: float = Field(
        description="The bound that was selected"
    )


class ValueProvenance(BaseModel):
    """
    Tracks the origin of a single value.

    Attached to any value that flows through the pipeline.
    """
    source: ValueSource = Field(
        description="Where this value came from"
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
    # Audit trail extensions
    extraction_method: str | None = Field(
        default=None,
        description="How the value was extracted: 'regex', 'llm', 'regex+llm', 'rule', 'direct'"
    )
    raw_match: str | None = Field(
        default=None,
        description="Raw text matched before parsing (e.g. '0.94–0.97')"
    )
    parsed_range: list[float] | None = Field(
        default=None,
        description="[min, max] when value was extracted from a range"
    )
    # Range-pending pipeline signal — True when `value` is the range lower bound and
    # StandardizationService must still pick the correct conservative bound.
    # Always False in the final serialized audit output (cleared by standardization).
    range_pending: bool = Field(
        default=False,
        description="Pipeline signal: True when value is a range lower bound awaiting bound selection"
    )
    # Populated by StandardizationService when it selects a bound from a pending range.
    # Lives alongside transformation_applied during the transition; this block is the
    # authoritative record for bound-selection events.
    standardization: RangeBoundSelection | None = Field(
        default=None,
        description="Structured record of the bound selection applied by standardization"
    )
    # Rule-match details — populated by GroundingService for USER_INFERRED values.
    # These carry the InterpretationRule's structured fields so the audit can show
    # exactly which rule fired, whether it was conservative, and (for embedding-fallback
    # matches) the similarity score and the canonical phrase that was the closest match.
    matched_pattern: str | None = Field(
        default=None,
        description="The rule pattern that matched (e.g. 'room temperature')"
    )
    rule_conservative: bool | None = Field(
        default=None,
        description="Whether the matched rule was flagged conservative by its author"
    )
    rule_notes: str | None = Field(
        default=None,
        description="The rule's notes field (human-readable rationale)"
    )
    embedding_similarity: float | None = Field(
        default=None,
        description="Cosine similarity score when value was resolved via embedding fallback"
    )
    canonical_phrase: str | None = Field(
        default=None,
        description="The canonical phrase that scored highest in the embedding lookup"
    )


# =============================================================================
# DEFAULT IMPUTED
# =============================================================================

class DefaultImputed(BaseModel):
    """
    Record of a conservative default substituted for a missing field.

    Emitted by StandardizationService when a required value was absent and a
    safety-conservative default was used in its place.  There is no
    "correction" here — the value was simply absent; the default is the first
    and only value assigned.
    """
    field_name: str = Field(
        description="Which field received a default"
    )
    original_value: float | None = Field(
        default=None,
        description="Always None — no user-supplied value existed"
    )
    imputed_value: float | str = Field(
        description="The conservative default that was substituted"
    )
    reason: str = Field(
        description="Why this default is conservative for the model type"
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

class RunnerUpResult(BaseModel):
    """A non-winning retrieval candidate kept for audit traceability."""
    doc_id: str | None = Field(default=None, description="Document ID")
    content_preview: str | None = Field(
        default=None,
        description="First ~120 characters of retrieved text"
    )
    embedding_score: float | None = Field(
        default=None,
        description="Cosine similarity score (1 − ChromaDB distance)"
    )
    rerank_score: float | None = Field(
        default=None,
        description="Reranker score if a reranker was applied"
    )


class RetrievalResult(BaseModel):
    """
    Metadata about a RAG retrieval operation.
    """
    query: str = Field(
        description="The query used for retrieval"
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
    # Audit trail extensions
    embedding_score: float | None = Field(
        default=None,
        description="Cosine similarity of the top result (1 − ChromaDB distance)"
    )
    rerank_score: float | None = Field(
        default=None,
        description="Reranker score of the top result (distinct from embedding_score)"
    )
    source_ids: list[str] = Field(
        default_factory=list,
        description="Source IDs extracted from the retrieved document metadata"
    )
    full_citations: dict[str, str] = Field(
        default_factory=dict,
        description="Formatted bibliographic citations keyed by source_id"
    )
    runners_up: list[RunnerUpResult] = Field(
        default_factory=list,
        description="Top non-winning retrieval candidates (up to 3)"
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
# COMBASE MODEL AUDIT
# =============================================================================

class ComBaseModelAudit(BaseModel):
    """
    Records which ComBase model was selected and why, for regulatory traceability.
    """
    organism: str = Field(description="Enum name of the organism (e.g. 'BACILLUS_CEREUS')")
    organism_id: str | None = Field(
        default=None,
        description="ComBase short code (e.g. 'bc') — cross-reference to combase_models.csv"
    )
    organism_display_name: str | None = Field(
        default=None,
        description="Human-readable canonical name from combase_models.csv Org column (e.g. 'Bacillus cereus')"
    )
    model_type: str = Field(description="Model type selected (growth / thermal_inactivation / non_thermal_survival)")
    model_id: int | None = Field(default=None, description="ComBase ModelID (1=Growth, 2=Thermal, 3=Non-thermal)")
    coefficients_str: str | None = Field(
        default=None,
        description="Semicolon-separated polynomial coefficients for the selected model"
    )
    valid_ranges: dict[str, tuple[float, float]] | None = Field(
        default=None,
        description="Valid input ranges for the model: {field: (min, max)}"
    )
    selection_reason: str = Field(
        description="One-line explanation of why this model type was chosen"
    )


# =============================================================================
# SYSTEM AUDIT
# =============================================================================

class SystemAudit(BaseModel):
    """
    Immutable facts about the PTM instance that produced this result.

    Allows a regulator to reconstruct the exact software + data state
    without re-running the system.
    """
    rag_store_hash: str | None = Field(
        default=None,
        description="SHA-256 prefix of sorted ChromaDB document IDs at ingestion time"
    )
    rag_ingested_at: str | None = Field(
        default=None,
        description="ISO-8601 timestamp when the RAG store was last ingested"
    )
    source_csv_audit_date: str | None = Field(
        default=None,
        description="Modification date of data/rag/rag_audit_changelog.md at ingestion time"
    )
    ptm_version: str | None = Field(
        default=None,
        description="Git SHA (short) of the running PTM codebase"
    )
    combase_model_table_hash: str | None = Field(
        default=None,
        description="SHA-256 prefix of data/combase_models.csv"
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
    
    # Conservative defaults substituted for missing fields
    defaults_imputed: list[DefaultImputed] = Field(
        default_factory=list,
        description="Conservative defaults applied when a required value was absent"
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
    
    # Warnings and notes
    warnings: list[str] = Field(
        default_factory=list,
        description="Warnings generated during interpretation"
    )
    notes: list[str] = Field(
        default_factory=list,
        description="Additional notes for transparency"
    )

    # Top-level audit blocks (populated by orchestrator)
    combase_model: ComBaseModelAudit | None = Field(
        default=None,
        description="Which ComBase model was selected and why"
    )
    system: SystemAudit | None = Field(
        default=None,
        description="PTM software and data state at time of prediction"
    )

    def add_provenance(self, field_name: str, provenance: ValueProvenance) -> None:
        """Add provenance for a field."""
        self.provenance[field_name] = provenance
    
    def add_default_imputed(self, default: DefaultImputed) -> None:
        """Record a conservative default that was substituted for a missing field."""
        self.defaults_imputed.append(default)

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