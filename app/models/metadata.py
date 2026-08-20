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
    OrganismGroundingFailureStage,
    SessionStatus,
)

# =============================================================================
# VALUE SOURCES
# =============================================================================


class ValueSource(str, Enum):
    """Where a value came from.

    Priority hierarchy (highest to lowest — enforced by grounded.has() guards,
    not by enum ordering):
      USER_EXPLICIT / USER_INFERRED > RAG_RETRIEVAL > RAG_RETRIEVAL_FALLBACK
      > RAG_RETRIEVAL_CATEGORY_BRIDGE > CONSERVATIVE_DEFAULT / COMPOSITE_FOOD_DEFAULT

    CONSERVATIVE_DEFAULT and COMPOSITE_FOOD_DEFAULT sit at the same tier (no-evidence
    safety floor) but are distinguished by reason: COMPOSITE_FOOD_DEFAULT means
    retrieval was deliberately skipped because the food is a composite dish whose
    properties cannot be reliably grounded from single-ingredient documents.
    """

    USER_EXPLICIT = "user_explicit"  # User stated directly
    USER_INFERRED = "user_inferred"  # Inferred from user input
    FUZZY_MATCH = "fuzzy_match"  # Resolved via alias/fuzzy lookup
    RAG_RETRIEVAL = "rag_retrieval"  # Retrieved from knowledge base (primary query, specific-food doc)
    RAG_RETRIEVAL_FALLBACK = "rag_retrieval_fallback"  # Retrieved via per-field secondary query (category-level doc or lower threshold)
    RAG_RETRIEVAL_CATEGORY_BRIDGE = "rag_retrieval_category_bridge"  # Tier 3: food name resolved to FoodEx2 ptm_category via taxonomy bridge; food_properties row retrieved by category filter
    RAG_PATHOGEN_CATEGORY_FALLBACK = "rag_pathogen_category_fallback"  # Organism inferred from food category via IFT-2003-T1 associations ranked by CDC annual deaths; fires when food-specific hazard lookup (Stages 1+2) yields no confident result
    CONSERVATIVE_DEFAULT = "conservative_default"  # Safety default applied
    COMPOSITE_FOOD_DEFAULT = "composite_food_default"  # Retrieval deliberately skipped: food identified as composite dish; single-ingredient documents do not represent the mixture's properties reliably. Conservative default applied.
    LONG_WINDOW_DEFAULT = "long_window_default"  # Duration unspecified; long observation window assumed so prediction trajectory reaches cap. Epistemically distinct from CONSERVATIVE_DEFAULT: duration is a scenario dimension, not an environmental property with a safety-floor.
    CLARIFICATION_RESPONSE = "clarification_response"  # From user clarification
    CLAMPED_TO_RANGE = "clamped_to_range"  # Adjusted to valid range
    CALCULATED = "calculated"  # Derived from other values
    MISSING = "missing"  # Field was required but neither user nor grounding supplied a value; appears in field_audit with final_value=null on validation failure


class PathogenCandidate(BaseModel):
    """One entry in the ranked candidate list produced by the category-level pathogen fallback."""

    pathogen: str = Field(
        description="Pathogen name as it appears in pathogen_food_associations.csv"
    )
    normalized_name: str = Field(
        description="Name after normalization to match pathogen_characteristics.csv"
    )
    annual_deaths_us: int = Field(
        description="Annual US deaths from pathogen_characteristics.csv; used as ranking signal"
    )
    source_id: str = Field(
        description="CDC source ID for the death count (e.g. CDC-2019-T1T2)"
    )


class PathogenCategoryFallbackInfo(BaseModel):
    """Audit record for organism grounded via the category-level pathogen fallback.

    Populated when RAG_PATHOGEN_CATEGORY_FALLBACK fires — food-specific hazard
    lookup yielded no result, so the pipeline resolved food → ptm_category →
    IFT-2003-T1 categories → ranked pathogens → top ComBaseOrganism-mappable
    candidate.

    Attached to ValueProvenance.pathogen_category_fallback when the fallback
    succeeds.
    """

    ptm_category: str = Field(
        description="FoodEx2 ptm_category resolved by the taxonomy bridge"
    )
    ift_categories: list[str] = Field(
        description="IFT-2003-T1 categories the ptm_category mapped to"
    )
    ift_source_id: str = Field(
        default="IFT-2003-T1",
        description="Source ID for the qualitative pathogen-category association table",
    )
    candidate_pathogens: list[PathogenCandidate] = Field(
        description="All candidates gathered from the union of IFT categories, ranked by annual_deaths_us descending"
    )
    selected_pathogen: PathogenCandidate = Field(
        description="The top-ranked candidate that successfully mapped to a ComBaseOrganism"
    )
    skipped_pathogens: list[dict] = Field(
        default_factory=list,
        description="Candidates ranked above the selected one that failed ComBaseOrganism mapping; each entry has {pathogen, reason}",
    )
    full_citations: dict[str, str] = Field(
        default_factory=dict,
        description="Formatted bibliographic citations keyed by source_id; covers ift_source_id and every candidate's source_id",
    )


class OrganismGroundingFailure(BaseModel):
    """Structured record of where organism grounding failed closed.

    Twin of PathogenCategoryFallbackInfo for the failure side: that model
    records a successful category-fallback resolution; this one records why
    GroundingService._category_pathogen_fallback() returned without setting
    organism, so a caller doesn't have to re-derive the reason from the flat
    mark_ungrounded() warning string (which fires regardless and is unchanged).

    Attached to GroundedValues.organism_failure. None when organism grounding
    succeeds via any path (user-explicit, RAG retrieval, or category fallback).
    """

    stage: OrganismGroundingFailureStage = Field(
        description="Which of the six early-return points in _category_pathogen_fallback() fired"
    )
    detail: str = Field(
        description="Human-readable detail; for INTERNAL_NO_MAPPABLE_CANDIDATE, names the specific branch (empty candidate union, all candidates excluded from ranking, or all ranked candidates unmappable)"
    )
    resolved_category: str | None = Field(
        default=None,
        description="ptm_category the taxonomy bridge resolved to; populated only for CATEGORY_HAS_NO_HAZARD_DATA",
    )
    match_score: float | None = Field(
        default=None,
        description="Taxonomy bridge match_score (0-100) for the resolved category; populated only for CATEGORY_HAS_NO_HAZARD_DATA",
    )


class CategoryBridgeInfo(BaseModel):
    """Audit record for a Tier 3 taxonomy-bridge resolution.

    Records the full chain: user food description → FoodEx2 taxonomy entry
    → ptm_category → the specific food_properties row that supplied the value.

    One instance is attached per field on ValueProvenance.category_bridge.
    pH and aw often come from DIFFERENT property rows (e.g. 'chicken' for pH,
    'fresh poultry' for aw within the poultry category), so each field's
    category_bridge independently names its property_row_food_name.
    """

    species: str = Field(
        description="Food description that was looked up, e.g. 'turkey portions'"
    )
    resolved_category: str = Field(
        description="FoodEx2 ptm_category resolved by the bridge, e.g. 'poultry'"
    )
    taxonomy_code: str = Field(
        description="FoodEx2 code of the matched taxonomy entry, e.g. 'A01SQ'"
    )
    taxonomy_label: str = Field(
        description="FoodEx2 verbose label, e.g. 'Turkey fresh meat'"
    )
    taxonomy_source_id: str = Field(
        description="Source ID of the taxonomy catalogue, e.g. 'EFSA-FoodEx2-MTX-12.0'"
    )
    matched_food_name: str = Field(
        description="food_name column value that won the fuzzy match, e.g. 'turkey'"
    )
    match_score: float = Field(
        description="token_set_ratio score (0–100) of the winning match"
    )
    property_row_food_name: str = Field(
        description="food_name of the food_properties row that supplied this field's value"
    )
    property_row_source_ids: list[str] = Field(
        default_factory=list,
        description="Source ID(s) from the ph_source_id or aw_source_id column of the property row",
    )
    query_state: str = Field(
        default="",
        description=(
            "State used for the curated-row lookup (post-_apply_state_default), "
            "e.g. 'fresh', 'cured'.  Empty string when the lookup was not state-aware."
        ),
    )
    assumed_state: str = Field(
        default="",
        description=(
            "Non-empty when _apply_state_default converted the taxonomy state to 'fresh' "
            "(i.e. the original taxonomy state was 'unspecified' or '').  "
            "Empty string when the taxonomy already had a concrete state and no assumption was made."
        ),
    )


class RangeBoundSelection(BaseModel):
    """
    Structured record of a range-bound selection performed by StandardizationService.

    Range values arrive from grounding with both bounds preserved (range_pending=True on
    the ValueProvenance).  StandardizationService picks the conservative bound and writes
    this block.  It does NOT appear in bias_corrections or range_clamps — it is a
    deterministic, mechanical operation, not a safety-event-level correction.
    """

    rule: str = Field(
        default="range_bound_selection", description="Always 'range_bound_selection'"
    )
    direction: str = Field(
        description="'upper' for growth/survival models, 'lower' for thermal inactivation"
    )
    reason: str = Field(description="Plain-English rationale for end users")
    before_value: list[float] = Field(
        description="[min, max] — the original range from grounding"
    )
    after_value: float = Field(description="The bound that was selected")


class ValueProvenance(BaseModel):
    """
    Tracks the origin of a single value.

    Attached to any value that flows through the pipeline.
    """

    source: ValueSource = Field(description="Where this value came from")
    original_value: str | float | None = Field(
        default=None, description="Original value before any transformation"
    )
    original_text: str | None = Field(
        default=None, description="Original text from user input (if applicable)"
    )
    retrieval_source: str | None = Field(
        default=None, description="Document/chunk ID if from RAG retrieval"
    )
    transformation_applied: str | None = Field(
        default=None, description="Description of any transformation applied"
    )
    # Audit trail extensions
    # TODO: convert to Literal[...] for compile-time enforcement (separate refactor)
    extraction_method: str | None = Field(
        default=None,
        description="How the value was extracted: 'regex', 'llm', 'regex+llm', 'rule_match', 'embedding_fallback', 'ranked_by_annual_deaths', 'direct', 'llm_extraction', 'fuzzy_match'",
    )
    raw_match: str | None = Field(
        default=None, description="Raw text matched before parsing (e.g. '0.94–0.97')"
    )
    parsed_range: list[float] | None = Field(
        default=None, description="[min, max] when value was extracted from a range"
    )
    # Range-pending pipeline signal — True when `value` is the range lower bound and
    # StandardizationService must still pick the correct conservative bound.
    # Always False in the final serialized audit output (cleared by standardization).
    range_pending: bool = Field(
        default=False,
        description="Pipeline signal: True when value is a range lower bound awaiting bound selection",
    )
    # Populated by StandardizationService when it selects a bound from a pending range.
    # Lives alongside transformation_applied during the transition; this block is the
    # authoritative record for bound-selection events.
    standardization: RangeBoundSelection | None = Field(
        default=None,
        description="Structured record of the bound selection applied by standardization",
    )
    # Populated by GroundingService when the value was resolved via Tier 3 taxonomy bridge.
    # None for all other source tiers (USER_EXPLICIT, RAG_RETRIEVAL, etc.).
    category_bridge: CategoryBridgeInfo | None = Field(
        default=None,
        description="Taxonomy-bridge provenance when source=RAG_RETRIEVAL_CATEGORY_BRIDGE",
    )
    # Populated when the category-level pathogen fallback fires (RAG_PATHOGEN_CATEGORY_FALLBACK).
    # Carries the full ranking provenance: ptm_category, IFT categories, all candidates,
    # selected pathogen, and any skipped candidates. None for all other source tiers.
    pathogen_category_fallback: PathogenCategoryFallbackInfo | None = Field(
        default=None,
        description="Category-fallback provenance when source=RAG_PATHOGEN_CATEGORY_FALLBACK",
    )
    # Rule-match details — populated by GroundingService for USER_INFERRED values.
    # These carry the InterpretationRule's structured fields so the audit can show
    # exactly which rule fired, whether it was conservative, and (for embedding-fallback
    # matches) the similarity score and the canonical phrase that was the closest match.
    matched_pattern: str | None = Field(
        default=None,
        description="The rule pattern that matched (e.g. 'room temperature')",
    )
    rule_conservative: bool | None = Field(
        default=None,
        description="Whether the matched rule was flagged conservative by its author",
    )
    rule_notes: str | None = Field(
        default=None, description="The rule's notes field (human-readable rationale)"
    )
    embedding_similarity: float | None = Field(
        default=None,
        description="Cosine similarity score when value was resolved via embedding fallback",
    )
    canonical_phrase: str | None = Field(
        default=None,
        description="The canonical phrase that scored highest in the embedding lookup",
    )
    # Generic "grounded but excluded" marker — not specific to any one field or
    # precedence rule. Populated whenever a value was successfully grounded but
    # a downstream selection rule chose a different candidate for the same
    # decision slot (e.g. StandardizationService._get_factor4()'s CO2 > nitrite
    # > lactic acid > acetic acid precedence, when more than one is grounded).
    # None means the value (if present) reached the model normally. Deliberately
    # a single free-text field rather than a companion bool: a bool and a reason
    # string can desync (bool says excluded, reason absent, or vice versa); one
    # field cannot. Any future precedence/selection rule should populate this
    # same field rather than inventing a new one.
    excluded_reason: str | None = Field(
        default=None,
        description="Non-null when this value was grounded but a downstream selection rule chose a different candidate instead; names why",
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

    field_name: str = Field(description="Which field received a default")
    original_value: float | None = Field(
        default=None, description="Always None — no user-supplied value existed"
    )
    imputed_value: float | str = Field(
        description="The conservative default that was substituted"
    )
    reason: str = Field(
        description="Why this default is conservative for the model type"
    )
    source: ValueSource | None = Field(
        default=None,
        description=(
            "Optional override for the ValueSource assigned in field_audit. "
            "When set, the route builder uses this value instead of inferring "
            "CONSERVATIVE_DEFAULT or COMPOSITE_FOOD_DEFAULT from composite_skip. "
            "Use for source variants that are neither conservative-default nor "
            "composite-food-default (e.g., LONG_WINDOW_DEFAULT)."
        ),
    )


class RangeClamp(BaseModel):
    """
    Record of a value being clamped to valid range.
    """

    field_name: str = Field(description="Which field was clamped")
    original_value: float = Field(description="Value before clamping")
    clamped_value: float = Field(description="Value after clamping")
    valid_min: float = Field(description="Minimum valid value")
    valid_max: float = Field(description="Maximum valid value")
    reason: str = Field(description="Why this range applies (e.g., model constraint)")


# =============================================================================
# RETRIEVAL METADATA
# =============================================================================


class RunnerUpResult(BaseModel):
    """A non-winning retrieval candidate kept for audit traceability."""

    doc_id: str | None = Field(default=None, description="Document ID")
    content_preview: str | None = Field(
        default=None, description="First ~120 characters of retrieved text"
    )
    embedding_score: float | None = Field(
        default=None, description="Cosine similarity score (1 − ChromaDB distance)"
    )
    rerank_score: float | None = Field(
        default=None, description="Reranker score if a reranker was applied"
    )


class SkippedDocInfo(BaseModel):
    """A doc ranked first by the reranker but not used because it failed the embedding threshold gate."""

    doc_id: str | None = Field(default=None, description="Document ID")
    content_preview: str | None = Field(
        default=None, description="First ~120 characters of retrieved text"
    )
    embedding_score: float | None = Field(
        default=None, description="Cosine similarity score (1 − ChromaDB distance)"
    )
    rerank_score: float | None = Field(
        default=None, description="Reranker score if a reranker was applied"
    )
    skip_reason: str = Field(
        description="Machine-readable reason for skipping, e.g. 'failed_embedding_threshold:0.70'"
    )


class RetrievalResult(BaseModel):
    """
    Metadata about a RAG retrieval operation.
    """

    query: str = Field(description="The query used for retrieval")
    source_document: str | None = Field(
        default=None, description="Source document identifier"
    )
    chunk_id: str | None = Field(default=None, description="Specific chunk identifier")
    retrieved_text: str | None = Field(
        default=None, description="The text that was retrieved"
    )
    fallback_used: bool = Field(
        default=False,
        description="Whether a fallback/default was used due to low confidence",
    )
    # Audit trail extensions
    embedding_score: float | None = Field(
        default=None,
        description="Cosine similarity of the top result (1 − ChromaDB distance)",
    )
    rerank_score: float | None = Field(
        default=None,
        description="Reranker score of the top result (distinct from embedding_score)",
    )
    source_ids: list[str] = Field(
        default_factory=list,
        description="Source IDs extracted from the retrieved document metadata",
    )
    full_citations: dict[str, str] = Field(
        default_factory=dict,
        description="Formatted bibliographic citations keyed by source_id",
    )
    runners_up: list[RunnerUpResult] = Field(
        default_factory=list,
        description="Top non-winning retrieval candidates (up to 3)",
    )
    reranker_used: str | None = Field(
        default=None,
        description="Reranker model name if reranking was applied, None otherwise",
    )
    attributed_field: str | None = Field(
        default=None,
        description="Field this retrieval result is attributed to (set on per-field fallback queries; None for primary queries that may cover multiple fields)",
    )
    reranker_top: SkippedDocInfo | None = Field(
        default=None,
        description="Present when the reranker's top-ranked doc was skipped because it failed the embedding threshold; the next qualifying doc became top_match",
    )
    attempted_top: SkippedDocInfo | None = Field(
        default=None,
        description="Present when no doc passed the threshold; shows what the system would have used, with skip_reason explaining the gate failure",
    )


# =============================================================================
# CLARIFICATION TRACKING
# =============================================================================


class ClarificationQuestion(BaseModel):
    """
    A clarification question ready to surface to the user.

    Built by ClarificationService (pure, deterministic, no I/O) from
    already-resolved inputs the orchestrator assembles. Free-text only
    (2026-08-19, see specs/lessons.md): no options array — the question
    names a few example pathogens in prose instead of offering a menu, and
    the reply is resolved deterministically (ComBaseOrganism.all_matches_in_text)
    rather than through an LLM extraction + set-membership check. See
    app/services/clarification/clarification_service.py.
    """

    reason: ClarificationReason = Field(description="Why clarification was needed")
    stage: OrganismGroundingFailureStage = Field(
        description="Which organism-grounding failure stage triggered this question"
    )
    question: str = Field(
        description="The question text, including prose pathogen examples"
    )


class ClarificationTranscript(BaseModel):
    """
    A1b (2026-07-17): the single round-1 exchange, carried on the request so
    the pipeline can complete without a server-side session.

    PTM is stateless — no SessionManager, no server-held conversation state
    (see specs/lessons.md on SessionManager._sessions being unbounded,
    TTL-less, and broken under multi-worker deployment; A1b deliberately does
    not build on it). The caller (API client) is responsible for holding the
    round-1 question and echoing it back verbatim alongside the user's reply.

    Structurally caps the exchange to one round: this is a single object with
    three scalar fields, not a list of turns, so there is no representable
    way to accumulate a second round within it. Field-level max_length bounds
    additionally cap payload size. If grounding still fails after a transcript
    is present, the orchestrator fails closed rather than asking again.

    No options_offered field (2026-08-19, free-text-only redesign, see
    specs/lessons.md): there is no menu to echo back, and the reply is
    resolved by ComBaseOrganism.all_matches_in_text() rather than validated
    against an offered set.
    """

    original_query: str = Field(
        min_length=1,
        max_length=2000,
        description="The original query from the round-1 request — reprocessed "
        "from scratch, since no session persists it server-side",
    )
    question_asked: str = Field(
        min_length=1,
        max_length=2000,
        description="The exact question text from the round-1 response "
        "(ClarificationQuestion.question), echoed back for the audit record",
    )
    user_reply: str = Field(
        min_length=1,
        max_length=2000,
        description="The user's free-text answer to the round-1 question",
    )


class DurationClarificationStep(BaseModel):
    """One missing-duration step named in a DurationClarificationQuestion.

    duration_phrase is the raw phrase the user originally used for this
    step's duration (GroundedStep.duration_phrase — populated whether or not
    it resolved, see the multi-step raw-text-preservation work), so the
    question can quote it back ("you said 'a while'"). None when the user
    said nothing about this step's duration at all.
    """

    step_order: int = Field(ge=1)
    duration_phrase: str | None = Field(default=None)


class DurationClarificationQuestion(BaseModel):
    """
    A multi-step duration clarification question, ready to surface to the
    user — the duration-gate analogue of ClarificationQuestion.

    Deliberately has no `options` field (unlike ClarificationQuestion):
    duration is an open numeric quantity, not a closed menu, so there is
    nothing to select from. Built by ClarificationService.build_duration_question()
    (pure, deterministic) from the caller-derived list of currently-missing
    steps — see Orchestrator._handle_missing_required.
    """

    reason: ClarificationReason = Field(description="Why clarification was needed")
    question: str = Field(description="The question text, naming every missing step")
    steps: list[DurationClarificationStep] = Field(
        min_length=1,
        description="Every step still missing a duration, in step_order order",
    )


class DurationStepReply(BaseModel):
    """One step's answer in a DurationClarificationReply.

    hours is a plain number typed by the user directly — never LLM-parsed.
    There is no free-text path for duration clarification (unlike organism's
    ClarificationTranscript.user_reply): a number is USER_EXPLICIT at the
    same trust level as any value in the original query, because there is no
    LLM extraction step to introduce the ambiguity organism's set-membership
    check exists to police. See specs/lessons.md for the full reasoning.
    """

    step_order: int = Field(ge=1)
    hours: float = Field(
        gt=0,
        description="Duration in hours, entered directly by the user. The "
        "90-day plausibility ceiling (mirroring ExtractedDuration.value_minutes) "
        "is enforced in Orchestrator._resolve_duration_reply, not here, so an "
        "out-of-range reply fails closed with a plain message rather than a "
        "generic 422 at the request-parsing layer.",
    )


class DurationClarificationReply(BaseModel):
    """
    The round-1 duration question's reply, carried on the request — the
    duration-gate analogue of ClarificationTranscript.

    No options_offered-equivalent: unlike organism's offered set (a closed
    list that is itself a safety boundary a reply must not escape), "which
    steps are still missing a duration" is recomputed fresh from grounded.steps
    on every round rather than trusted from what was asked in round 1 — a
    step that resolves differently on retry legitimately no longer needs an
    answer. The reply's step_order set must equal that freshly-recomputed
    set exactly (all-or-nothing; see specs/lessons.md) or the request fails
    closed, so echoing back a stale round-1 set would only make the
    validation stricter than it needs to be, not safer.
    """

    original_query: str = Field(
        min_length=1,
        max_length=2000,
        description="The original query from round 1 — reprocessed from "
        "scratch, since no session persists it server-side",
    )
    steps: list[DurationStepReply] = Field(min_length=1, max_length=10)


class ClarificationRecord(BaseModel):
    """
    Record of a clarification exchange with the user.
    """

    turn_number: int = Field(ge=1, description="Which clarification turn (1, 2, 3...)")
    reason: ClarificationReason = Field(description="Why clarification was needed")
    question_asked: str = Field(description="The question that was asked")
    user_response: str | None = Field(
        default=None, description="User's response (None if skipped/timed out)"
    )
    extracted_value: str | float | None = Field(
        default=None, description="Value extracted from response"
    )
    default_used: bool = Field(
        default=False, description="Whether default was used instead of user response"
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow, description="When this clarification occurred"
    )


# =============================================================================
# COMBASE MODEL AUDIT
# =============================================================================


class ComBaseModelAudit(BaseModel):
    """
    Records which ComBase model was selected and why, for regulatory traceability.
    """

    organism: str = Field(
        description="Enum name of the organism (e.g. 'BACILLUS_CEREUS')"
    )
    organism_id: str | None = Field(
        default=None,
        description="ComBase short code (e.g. 'bc') — cross-reference to combase_models.csv",
    )
    organism_display_name: str | None = Field(
        default=None,
        description="Human-readable canonical name from combase_models.csv Org column (e.g. 'Bacillus cereus')",
    )
    model_type: str = Field(
        description="Model type selected (growth / thermal_inactivation / non_thermal_survival)"
    )
    model_id: int | None = Field(
        default=None, description="ComBase ModelID (1=Growth, 2=Thermal, 3=Non-thermal)"
    )
    coefficients_str: str | None = Field(
        default=None,
        description="Semicolon-separated polynomial coefficients for the selected model",
    )
    valid_ranges: dict[str, tuple[float, float]] | None = Field(
        default=None,
        description="Valid input ranges for the model: {field: (min, max)}",
    )
    selection_reason: str = Field(
        description="One-line explanation of why this model type was chosen"
    )
    y_max: float | None = Field(
        default=None, description="Maximum population density (Baranyi model parameter)"
    )
    h0: float | None = Field(
        default=None,
        description="Initial physiological state (Baranyi model parameter)",
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
        description="SHA-256 prefix of sorted ChromaDB document IDs at ingestion time",
    )
    rag_ingested_at: str | None = Field(
        default=None,
        description="ISO-8601 timestamp when the RAG store was last ingested",
    )
    source_csv_audit_date: str | None = Field(
        default=None,
        description="Modification date of data/rag/rag_audit_changelog.md at ingestion time",
    )
    ptm_version: str | None = Field(
        default=None, description="Git SHA (short) of the running PTM codebase"
    )
    combase_model_table_hash: str | None = Field(
        default=None, description="SHA-256 prefix of data/combase_models.csv"
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
    session_id: str = Field(description="Unique session identifier")
    status: SessionStatus = Field(
        default=SessionStatus.PENDING, description="Current session status"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow, description="When the session started"
    )
    completed_at: datetime | None = Field(
        default=None, description="When the session completed"
    )

    # Original input
    original_input: str = Field(description="The user's original input text")

    # Provenance for key fields
    provenance: dict[str, ValueProvenance] = Field(
        default_factory=dict,
        description="Provenance for each field (field_name -> provenance)",
    )

    # Conservative defaults substituted for missing fields
    defaults_imputed: list[DefaultImputed] = Field(
        default_factory=list,
        description="Conservative defaults applied when a required value was absent",
    )
    range_clamps: list[RangeClamp] = Field(
        default_factory=list, description="Range clamps that were applied"
    )

    # Composite-food skip events: field_name → matched keyword.
    # Populated by the orchestrator from GroundedValues.composite_skip when the
    # orchestrator-level composite-food guard fires and skips retrieval for a field.
    # The route builder reads this to assign COMPOSITE_FOOD_DEFAULT source instead
    # of CONSERVATIVE_DEFAULT for these fields.
    composite_skip: dict[str, str] = Field(
        default_factory=dict,
        description="Fields whose retrieval was deliberately skipped due to composite-food guard: {field_name: matched_keyword}",
    )

    # Retrievals performed
    retrievals: list[RetrievalResult] = Field(
        default_factory=list, description="RAG retrievals that were performed"
    )

    # Clarifications
    clarifications: list[ClarificationRecord] = Field(
        default_factory=list, description="Clarification exchanges with user"
    )

    # Warnings and notes
    warnings: list[str] = Field(
        default_factory=list, description="Warnings generated during interpretation"
    )
    notes: list[str] = Field(
        default_factory=list, description="Additional notes for transparency"
    )

    # Top-level audit blocks (populated by orchestrator)
    combase_model: ComBaseModelAudit | None = Field(
        default=None, description="Which ComBase model was selected and why"
    )
    system: SystemAudit | None = Field(
        default=None, description="PTM software and data state at time of prediction"
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
