"""
Grounding Service

Resolves extracted values to grounded, validated values.

This service sits between the SemanticParser (which extracts raw user input)
and the StandardizationService (which prepares execution payloads).

Responsibilities
----------------
1. USER_EXPLICIT: Values directly stated by the user ("25°C", "3 hours").
2. USER_INFERRED: Values interpreted from linguistic descriptions
   ("room temperature" → 25°C via config/rules.py).
3. RAG_RETRIEVAL: Values retrieved from the knowledge base (chicken pH → 6.0).

When grounding encounters a range (user-supplied or RAG), it preserves BOTH
bounds — it does NOT collapse to a single value.  The lower bound is stored as
the placeholder value; ValueProvenance.range_pending is set to True and
parsed_range carries [min, max].

Range-bound selection (choosing upper vs. lower based on model type) is a
StandardizationService responsibility.  It is a model-type-aware, deterministic
transformation that belongs alongside bias correction and clamping, not here.
"""

import asyncio
import logging
import os
import re
import string
from dataclasses import dataclass
from pathlib import Path

from app.config.rules import (
    find_duration_interpretation,
    find_temperature_interpretation_with_fallback,
)
from app.models.enums import OrganismGroundingFailureStage
from app.models.extraction import (
    ExtractedDuration,
    ExtractedEnvironmentalConditions,
    ExtractedFoodProperties,
    ExtractedScenario,
    ExtractedTemperature,
)
from app.models.metadata import (
    CategoryBridgeInfo,
    OrganismGroundingFailure,
    PathogenCandidate,
    PathogenCategoryFallbackInfo,
    RetrievalResult,
    RunnerUpResult,
    SkippedDocInfo,
    ValueProvenance,
    ValueSource,
)
from app.rag.retrieval import RetrievalResponse, RetrievalService, get_retrieval_service
from app.services.audit.citations import get_full_citations
from app.services.grounding.taxonomy_bridge import TaxonomyBridge
from app.services.llm.client import LLMClient, get_llm_client
from predictive.models.enums import ComBaseOrganism

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Category-level pathogen fallback — static data
# ---------------------------------------------------------------------------

# Maps pathogen names as they appear in pathogen_food_associations.csv (lowercase)
# to the corresponding name in pathogen_characteristics.csv (lowercase).
# Used only for the annual_deaths_us lookup; from_text() uses the original
# associations-CSV name directly for ComBaseOrganism mapping.
_PATHOGEN_NAME_NORMALIZATION: dict[str, str] = {
    "salmonella spp.": "salmonella nontyphoidal",
    "campylobacter jejuni": "campylobacter spp.",
    "escherichia coli o157:h7": "stec o157",
    "vibrio cholerae": "vibrio cholerae toxigenic",
    # Direct matches (same name, kept explicit for completeness):
    "clostridium botulinum": "clostridium botulinum",
    "clostridium perfringens": "clostridium perfringens",
    "listeria monocytogenes": "listeria monocytogenes",
    "yersinia enterocolitica": "yersinia enterocolitica",
    "staphylococcus aureus": "staphylococcus aureus",
    "bacillus cereus": "bacillus cereus",
    "shigella spp.": "shigella spp.",
    "vibrio vulnificus": "vibrio vulnificus",
    "vibrio parahaemolyticus": "vibrio parahaemolyticus",
}

_DEFAULT_IFT_ALIGNMENT_PATH = Path("data/rag/ift_category_alignment.csv")
_DEFAULT_PATHOGEN_ASSOCIATIONS_PATH = Path("data/rag/pathogen_food_associations.csv")
_DEFAULT_PATHOGEN_CHARACTERISTICS_PATH = Path("data/rag/pathogen_characteristics.csv")

# Composite-food keywords.  When the normalised food description contains one of
# these tokens (or the multi-word "stir-fry"/"stir fry"), the orchestrator-level
# guard fires and all three tiers of food-property retrieval are skipped.  The
# guard sits here — at the food-property orchestration layer — so it gates Tier 1
# and Tier 2 as well as Tier 3, not just the taxonomy bridge.
#
# Expansion history:
#   Initial set (2026-05-07): soup, salad, stew, pie, sandwich, roll, wrap,
#       casserole, curry, mixed, platter, dish
#   2026-05-08: chili, custard, chowder, gumbo, bisque, lasagna, lasagne
_COMPOSITE_KEYWORDS: frozenset[str] = frozenset(
    {
        "soup",
        "salad",
        "stew",
        "pie",
        "sandwich",
        "roll",
        "wrap",
        "casserole",
        "curry",
        "mixed",
        "platter",
        "dish",
        "chili",
        "custard",
        "chowder",
        "gumbo",
        "bisque",
        "lasagna",
        "lasagne",
    }
)


def _normalise_food_description(text: str) -> str:
    """Lowercase, strip punctuation (except hyphen), collapse whitespace."""
    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation.replace("-", "")))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _composite_keyword_match(food_description: str) -> str | None:
    """Return the matched composite keyword, or None if the food is not composite.

    Uses token intersection on whitespace-split tokens plus substring match for
    the multi-word entries "stir-fry" and "stir fry".  Input must be normalised
    (lowercase, punctuation-stripped, whitespace-collapsed) before calling.
    """
    normalised = _normalise_food_description(food_description)
    tokens = set(normalised.split())
    matched = tokens & _COMPOSITE_KEYWORDS
    if matched:
        return next(iter(matched))
    for multi in ("stir-fry", "stir fry"):
        if multi in normalised:
            return multi
    return None


# Sentinel distinguishing "caller did not pass taxonomy_bridge" (read env var)
# from "caller explicitly passed None" (disable bridge unconditionally).
_BRIDGE_SENTINEL = object()


def _parse_bridge_enabled_env() -> bool:
    """Return True when PTM_TAXONOMY_BRIDGE_ENABLED is truthy or unset."""
    raw = os.environ.get("PTM_TAXONOMY_BRIDGE_ENABLED")
    if raw is None:
        return True  # unset → default enabled
    return raw.strip().lower() in ("true", "1", "yes")


def _apply_state_default(state: str) -> str:
    """Convert 'unspecified' or '' to 'fresh'; pass all other states through unchanged.

    FoodEx2 marks many entries as 'unspecified' when state is irrelevant.
    For food safety grounding we assume fresh, which is the most common
    scenario and the only state with curated rows in category_level_rows.csv.
    The assumption is surfaced in CategoryBridgeInfo.assumed_state.
    """
    return "fresh" if state in ("unspecified", "") else state


FOOD_PROPERTIES_EXTRACTION_PROMPT = """Extract pH and water activity values from the following text about food properties.

Rules:
- Extract only explicitly stated values
- If a range is given (e.g., "pH 5.5-6.0"), extract both min and max
- If a single value is given (e.g., "pH 6.0"), extract it as the single value
- Water activity (aw) is always between 0 and 1
- pH is typically between 0 and 14
- If a value is not mentioned, leave it as null
- Do not infer or guess values

Text:
{text}
"""


@dataclass
class ExtractedNumericValue:
    """Result of numeric extraction from text."""

    value: float | None = None
    is_range: bool = False
    range_min: float | None = None
    range_max: float | None = None
    original_text: str | None = None


def _to_runner_up(r) -> RunnerUpResult:
    """Convert a rag-layer RetrievalResult to a metadata RunnerUpResult."""
    emb = (1.0 - r.distance) if isinstance(r.distance, (int, float)) else None
    rr = r.rerank_score if isinstance(r.rerank_score, (int, float)) else None
    return RunnerUpResult(
        doc_id=r.doc_id,
        content_preview=r.content[:120] if r.content else None,
        embedding_score=round(emb, 4) if emb is not None else None,
        rerank_score=round(rr, 4) if rr is not None else None,
    )


def _to_skipped_doc(r, threshold: float) -> SkippedDocInfo:
    """Build a SkippedDocInfo for a doc that the reranker ranked first but that failed the embedding threshold gate."""
    emb = (1.0 - r.distance) if isinstance(r.distance, (int, float)) else None
    rr = r.rerank_score if isinstance(r.rerank_score, (int, float)) else None
    return SkippedDocInfo(
        doc_id=r.doc_id,
        content_preview=r.content[:120] if r.content else None,
        embedding_score=round(emb, 4) if emb is not None else None,
        rerank_score=round(rr, 4) if rr is not None else None,
        skip_reason=f"failed_embedding_threshold:{threshold:.2f}",
    )


def _build_retrieval_metadata(response: RetrievalResponse) -> RetrievalResult:
    """
    Build a metadata RetrievalResult from a rag-layer RetrievalResponse.

    top_match (chunk_id / retrieved_text) reflects response.top_result — the
    first reranked result that cleared the embedding confidence threshold, and
    therefore the doc whose content was used for value extraction.

    When the reranker's top-ranked result (results[0]) differs from top_result
    because it failed the threshold gate, that doc is surfaced as reranker_top
    with a skip_reason.  When no result passed the threshold at all (top_result
    is None), results[0] is surfaced as attempted_top instead.

    runners_up are populated from results that appear in neither top_match nor
    reranker_top / attempted_top, capped at 3.

    All numeric attribute reads are guarded with isinstance checks because tests
    supply MagicMock objects that satisfy the duck-type interface but carry
    non-numeric values for optional fields.
    """
    # Structural invariant: top_result is None iff has_confident_result is False.
    top_result = response.top_result if response.has_confident_result else None
    first_result = (
        response.results[0] if response.results else None
    )  # reranker's top pick

    # ── Metadata from the value-supplying doc ─────────────────────────────────
    embedding_score: float | None = None
    rerank_score: float | None = None
    source_ids: list[str] = []
    full_citations: dict[str, str] = {}

    if top_result:
        dist = top_result.distance
        if isinstance(dist, (int, float)):
            embedding_score = round(1.0 - dist, 4)
        rr = top_result.rerank_score
        if isinstance(rr, (int, float)):
            rerank_score = round(rr, 4)
        meta = top_result.metadata
        raw_sid = meta.get("source_id", "") if isinstance(meta, dict) else ""
        raw_sid = raw_sid or ""
        source_ids = [s.strip() for s in raw_sid.split(",") if s.strip()]
        full_citations = get_full_citations(source_ids)

    # ── Reranker-skipped doc ───────────────────────────────────────────────────
    reranker_top: SkippedDocInfo | None = None
    attempted_top: SkippedDocInfo | None = None

    if first_result is not None:
        top_id = top_result.doc_id if top_result else None
        if top_result is None:
            # No doc passed threshold — show the would-be pick under attempted_top.
            attempted_top = _to_skipped_doc(first_result, response.threshold)
        elif first_result.doc_id != top_id:
            # Reranker promoted a below-threshold doc; a different doc supplied the value.
            reranker_top = _to_skipped_doc(first_result, response.threshold)

    # ── Runners-up: all results not already surfaced above, capped at 3 ───────
    # Use object identity so that None doc_ids don't accidentally match each other.
    surfaced: set[int] = set()
    if top_result is not None:
        surfaced.add(id(top_result))
    if first_result is not None:
        surfaced.add(id(first_result))
    runners_up = [_to_runner_up(r) for r in response.results if id(r) not in surfaced][
        :3
    ]

    query = response.query if isinstance(response.query, str) else ""
    reranker_used = (
        response.reranker_used if isinstance(response.reranker_used, str) else None
    )

    return RetrievalResult(
        query=query,
        source_document=top_result.source if top_result else None,
        chunk_id=top_result.doc_id if top_result else None,
        retrieved_text=top_result.content if top_result else None,
        fallback_used=not response.has_confident_result,
        embedding_score=embedding_score,
        rerank_score=rerank_score,
        reranker_used=reranker_used,
        source_ids=source_ids,
        full_citations=full_citations,
        runners_up=runners_up,
        reranker_top=reranker_top,
        attempted_top=attempted_top,
    )


@dataclass
class GroundedStep:
    """A single grounded time-temperature step for multi-step scenarios."""

    step_order: int
    temperature_celsius: float | None
    duration_minutes: float | None
    temp_provenance: ValueProvenance | None = None
    dur_provenance: ValueProvenance | None = None
    # A1c multi-step recon (2026-08-17): the user's original phrasing, carried
    # through unconditionally (populated whenever the parser captured a
    # description, whether or not it resolved). Purely additive -- nothing
    # reads these yet. They exist so a future duration/temperature
    # clarification question can quote the user back rather than only
    # naming the step number, the way _ground_multi_step_profile()'s
    # unresolved-value warning strings do today but then discard.
    duration_phrase: str | None = None
    temperature_phrase: str | None = None


class GroundedValues:
    """
    Container for grounded values with provenance.

    This class holds the resolved values along with metadata about where
    each value came from (source) and how confident we are (confidence).

    Usage:
        grounded = GroundedValues()
        grounded.set("ph", 6.0, ValueSource.RAG_RETRIEVAL, confidence=0.85)

        if grounded.has("ph"):
            ph_value = grounded.get("ph")
            ph_provenance = grounded.provenance["ph"]
    """

    def __init__(self):
        self.values: dict[str, object] = {}
        self.provenance: dict[str, ValueProvenance] = {}
        self.retrievals: list[RetrievalResult] = []
        self.warnings: list[str] = []
        self.ungrounded_fields: list[str] = []
        self.steps: list[GroundedStep] = []
        # Populated when the taxonomy bridge resolves a category for a field
        # but the category has NO food_properties rows supplying that field.
        # Keys are field names ("ph", "water_activity").  The CategoryBridgeInfo
        # records what was attempted so StandardizationService can include
        # "bridge resolved to category X, no Y data available" in the
        # DefaultImputed reason instead of a silent "no value found".
        self.bridge_attempts: dict[str, CategoryBridgeInfo] = {}
        # Populated when the orchestrator-level composite-food guard fires and
        # skips retrieval for a field.  Keys are field names; values are the
        # matched keyword (e.g. {"ph": "chili", "water_activity": "chili"}).
        # The route builder reads this to assign COMPOSITE_FOOD_DEFAULT source.
        self.composite_skip: dict[str, str] = {}
        # Populated at each early return of _category_pathogen_fallback() when
        # organism grounding fails closed. The organism equivalent of
        # bridge_attempts: a structured near-miss record instead of a silent
        # return. Purely additive — mark_ungrounded()'s warning string still
        # fires unchanged. None when organism grounding succeeds.
        self.organism_failure: OrganismGroundingFailure | None = None

    @property
    def has_steps(self) -> bool:
        return len(self.steps) > 0

    def add_step(
        self,
        step_order: int,
        temperature_celsius: float | None,
        duration_minutes: float | None,
        temp_provenance: ValueProvenance | None = None,
        dur_provenance: ValueProvenance | None = None,
        duration_phrase: str | None = None,
        temperature_phrase: str | None = None,
    ) -> None:
        """Append a grounded time-temperature step."""
        self.steps.append(
            GroundedStep(
                step_order=step_order,
                temperature_celsius=temperature_celsius,
                duration_minutes=duration_minutes,
                temp_provenance=temp_provenance,
                dur_provenance=dur_provenance,
                duration_phrase=duration_phrase,
                temperature_phrase=temperature_phrase,
            )
        )

    def set(
        self,
        field: str,
        value,
        source: ValueSource,
        **kwargs,
    ) -> None:
        """Set a grounded value with provenance."""
        self.values[field] = value
        self.provenance[field] = ValueProvenance(
            source=source,
            **kwargs,
        )

    def set_with_prov(
        self,
        field: str,
        value,
        provenance: ValueProvenance,
    ) -> None:
        """Set a grounded value with a pre-built provenance object.

        Use this instead of set() when the caller already constructed
        the ValueProvenance (e.g. _resolve_temperature_value) and needs
        all fields preserved without re-listing them as kwargs.
        """
        self.values[field] = value
        self.provenance[field] = provenance

    def get(self, field: str, default=None):
        """Get a grounded value."""
        return self.values.get(field, default)

    def has(self, field: str) -> bool:
        """Check if a field is grounded."""
        return field in self.values

    def mark_ungrounded(self, field: str, reason: str) -> None:
        """Mark a field as ungrounded with reason."""
        self.ungrounded_fields.append(field)
        self.warnings.append(f"{field}: {reason}")


class GroundingService:
    """
    Service for grounding extracted values using RAG and interpretation rules.

    The grounding process resolves vague user descriptions into precise numeric
    values suitable for predictive models. It follows a strict priority hierarchy:

    1. USER_EXPLICIT: Values directly stated by user ("25°C", "3 hours")
    2. USER_INFERRED: Values interpreted from descriptions ("room temperature" → 25°C)
    3. RAG_RETRIEVAL: Values retrieved from knowledge base (chicken pH → 6.0)
    4. Defaults are NOT applied here — that's the StandardizationService's job

    Range handling
    --------------
    When a value arrives as a range (user-supplied or from RAG), grounding preserves
    BOTH bounds.  The lower bound is stored as the placeholder; ValueProvenance has
    range_pending=True and parsed_range=[min, max].  Choosing which bound to use
    (upper for growth, lower for thermal inactivation) is StandardizationService's job.
    """

    def __init__(
        self,
        retrieval_service: RetrievalService | None = None,
        llm_client: LLMClient | None = None,
        use_llm_extraction: bool = True,
        taxonomy_bridge: TaxonomyBridge | None = _BRIDGE_SENTINEL,  # type: ignore[assignment]
        ift_alignment: dict[str, list[str]] | None = None,
        pathogen_associations: dict[str, list[str]] | None = None,
        pathogen_characteristics: dict[str, tuple[int, str]] | None = None,
    ):
        self._retrieval = retrieval_service or get_retrieval_service()
        self._llm = llm_client or get_llm_client()
        self._use_llm_extraction = use_llm_extraction
        if taxonomy_bridge is _BRIDGE_SENTINEL:
            self._taxonomy_bridge: TaxonomyBridge | None = (
                TaxonomyBridge() if _parse_bridge_enabled_env() else None
            )
        else:
            self._taxonomy_bridge = taxonomy_bridge
        # Category-level pathogen fallback lookup tables.
        # When None, each is loaded from the default CSV path on first use.
        # Tests inject pre-built dicts to avoid filesystem reads.
        self._ift_alignment: dict[str, list[str]] = (
            ift_alignment
            if ift_alignment is not None
            else self._load_ift_alignment(_DEFAULT_IFT_ALIGNMENT_PATH)
        )
        self._pathogen_associations: dict[str, list[str]] = (
            pathogen_associations
            if pathogen_associations is not None
            else self._load_pathogen_associations(_DEFAULT_PATHOGEN_ASSOCIATIONS_PATH)
        )
        self._pathogen_characteristics: dict[str, tuple[int, str]] = (
            pathogen_characteristics
            if pathogen_characteristics is not None
            else self._load_pathogen_characteristics(
                _DEFAULT_PATHOGEN_CHARACTERISTICS_PATH
            )
        )

    # ------------------------------------------------------------------
    # Startup loaders for category-level pathogen fallback
    # ------------------------------------------------------------------

    @staticmethod
    def _load_ift_alignment(path: Path) -> dict[str, list[str]]:
        """Load ift_category_alignment.csv → {ptm_category: [ift_category, ...]}."""
        result: dict[str, list[str]] = {}
        if not path.exists():
            logger.warning("ift_category_alignment.csv not found at %s", path)
            return result
        import csv as _csv

        with open(path, newline="", encoding="utf-8") as f:
            for row in _csv.DictReader(f):
                ptm = row.get("ptm_category", "").strip()
                ift = row.get("ift_category", "").strip()
                if ptm and ift:
                    result.setdefault(ptm, [])
                    if ift not in result[ptm]:
                        result[ptm].append(ift)
        return result

    @staticmethod
    def _load_pathogen_associations(path: Path) -> dict[str, list[str]]:
        """Load pathogen_food_associations.csv → {ift_category: [pathogen, ...]}."""
        result: dict[str, list[str]] = {}
        if not path.exists():
            logger.warning("pathogen_food_associations.csv not found at %s", path)
            return result
        import csv as _csv

        with open(path, newline="", encoding="utf-8") as f:
            for row in _csv.DictReader(f):
                cat = row.get("food_category", "").strip()
                pathogen = row.get("pathogen", "").strip()
                if cat and pathogen:
                    result.setdefault(cat, [])
                    if pathogen not in result[cat]:
                        result[cat].append(pathogen)
        return result

    @staticmethod
    def _load_pathogen_characteristics(path: Path) -> dict[str, tuple[int, str]]:
        """Load pathogen_characteristics.csv → {normalized_name_lower: (annual_deaths_us, source_id)}.

        annual_deaths_us values that are '<0.1' or similar strings are treated as 0.
        """
        result: dict[str, tuple[int, str]] = {}
        if not path.exists():
            logger.warning("pathogen_characteristics.csv not found at %s", path)
            return result
        import csv as _csv

        with open(path, newline="", encoding="utf-8") as f:
            for row in _csv.DictReader(f):
                name = row.get("pathogen", "").strip().lower()
                source_id = row.get("source_id", "").strip()
                raw_deaths = row.get("annual_deaths", "0").strip()
                try:
                    deaths = int(raw_deaths)
                except ValueError:
                    deaths = 0
                if name:
                    result[name] = (deaths, source_id)
        return result

    async def ground_scenario(
        self,
        scenario: ExtractedScenario,
    ) -> GroundedValues:
        """
        Ground all values in an extracted scenario.

        Ranges are preserved with both bounds — bound selection happens in
        StandardizationService, not here.

        Args:
            scenario: The extracted scenario from SemanticParser

        Returns:
            GroundedValues with resolved values and provenance
        """
        grounded = GroundedValues()

        # Step 1: User explicit environmental conditions (highest priority)
        self._ground_environmental_conditions(
            scenario.environmental_conditions,
            grounded,
        )

        # Step 2: User explicit pathogen
        if scenario.pathogen_mentioned:
            organism = ComBaseOrganism.from_string(scenario.pathogen_mentioned)
            if organism:
                # from_string() does alias dict lookup, not true fuzzy matching,
                # so all successful matches represent explicit user intent.
                # FUZZY_MATCH will be used when rapidfuzz is added to from_string().
                grounded.set(
                    "organism",
                    organism,
                    source=ValueSource.USER_EXPLICIT,
                    original_text=scenario.pathogen_mentioned,
                    extraction_method="direct",
                )

        # Step 3: RAG for food properties - only if pH or aw still needed
        needs_ph = not grounded.has("ph")
        needs_aw = not grounded.has("water_activity")

        if scenario.food_description and (needs_ph or needs_aw):
            await self._ground_food_properties(
                scenario.food_description,
                grounded,
            )

        # Step 4: RAG for pathogen - only if not already grounded
        if not grounded.has("organism") and scenario.food_description:
            await self._ground_pathogen_from_rag(
                scenario.food_description,
                grounded,
            )

        # Mark organism as ungrounded if still missing
        if not grounded.has("organism"):
            grounded.mark_ungrounded(
                "organism",
                f"Could not determine pathogen for '{scenario.food_description or 'unknown food'}'",
            )

        # Step 5 & 6: Temperature and duration
        if scenario.is_multi_step and scenario.time_temperature_steps:
            self._ground_multi_step_profile(scenario, grounded)
        else:
            self._ground_temperature(scenario, grounded)
            self._ground_duration(scenario, grounded)

        # Step 7: Initial inoculum (user-supplied only; default applied later in StandardizationService)
        if scenario.initial_inoculum_log_cfu is not None:
            grounded.set(
                "initial_inoculum_log_cfu",
                scenario.initial_inoculum_log_cfu,
                ValueSource.USER_EXPLICIT,
                extraction_method="llm_extraction",
                original_text=str(scenario.initial_inoculum_log_cfu),
            )

        return grounded

    # =========================================================================
    # USER EXPLICIT VALUES
    # =========================================================================

    def _ground_environmental_conditions(
        self,
        conditions: ExtractedEnvironmentalConditions,
        grounded: GroundedValues,
    ) -> None:
        """
        Ground explicitly provided environmental conditions.

        These are values the user directly stated (e.g., "pH 6.5").
        They have the highest priority.
        """
        # pH — range takes priority over single value
        if conditions.ph_min is not None and conditions.ph_max is not None:
            if 0.0 <= conditions.ph_min <= 14.0 and 0.0 <= conditions.ph_max <= 14.0:
                grounded.set(
                    "ph",
                    conditions.ph_min,
                    source=ValueSource.USER_EXPLICIT,
                    extraction_method="llm_extraction",
                    raw_match=f"{conditions.ph_min}–{conditions.ph_max}",
                    parsed_range=[conditions.ph_min, conditions.ph_max],
                    range_pending=True,
                )
            else:
                grounded.warnings.append(
                    f"Ignoring extracted ph_range=[{conditions.ph_min}, {conditions.ph_max}] "
                    f"(must be 0–14; likely LLM field confusion)"
                )
        elif conditions.ph_value is not None:
            if 0.0 <= conditions.ph_value <= 14.0:
                grounded.set(
                    "ph",
                    conditions.ph_value,
                    source=ValueSource.USER_EXPLICIT,
                    extraction_method="llm_extraction",
                )
            else:
                grounded.warnings.append(
                    f"Ignoring extracted ph_value={conditions.ph_value} "
                    f"(must be 0–14; likely LLM field confusion)"
                )

        # Water activity — range takes priority over single value
        if (
            conditions.water_activity_min is not None
            and conditions.water_activity_max is not None
        ):
            if (
                0.0 <= conditions.water_activity_min <= 1.0
                and 0.0 <= conditions.water_activity_max <= 1.0
            ):
                grounded.set(
                    "water_activity",
                    conditions.water_activity_min,
                    source=ValueSource.USER_EXPLICIT,
                    extraction_method="llm_extraction",
                    raw_match=f"{conditions.water_activity_min}–{conditions.water_activity_max}",
                    parsed_range=[
                        conditions.water_activity_min,
                        conditions.water_activity_max,
                    ],
                    range_pending=True,
                )
            else:
                grounded.warnings.append(
                    f"Ignoring extracted water_activity_range=[{conditions.water_activity_min}, {conditions.water_activity_max}] "
                    f"(must be 0–1; likely LLM field confusion)"
                )
        elif conditions.water_activity is not None:
            if 0.0 <= conditions.water_activity <= 1.0:
                grounded.set(
                    "water_activity",
                    conditions.water_activity,
                    source=ValueSource.USER_EXPLICIT,
                    extraction_method="llm_extraction",
                )
            else:
                grounded.warnings.append(
                    f"Ignoring extracted water_activity={conditions.water_activity} "
                    f"(must be 0–1; likely LLM field confusion)"
                )

        # Other conditions (these don't require range selection)
        if conditions.co2_percent is not None:
            grounded.set(
                "co2_percent",
                conditions.co2_percent,
                ValueSource.USER_EXPLICIT,
                extraction_method="llm_extraction",
            )
        if conditions.nitrite_ppm is not None:
            grounded.set(
                "nitrite_ppm",
                conditions.nitrite_ppm,
                ValueSource.USER_EXPLICIT,
                extraction_method="llm_extraction",
            )
        if conditions.lactic_acid_ppm is not None:
            grounded.set(
                "lactic_acid_ppm",
                conditions.lactic_acid_ppm,
                ValueSource.USER_EXPLICIT,
                extraction_method="llm_extraction",
            )
        if conditions.acetic_acid_ppm is not None:
            grounded.set(
                "acetic_acid_ppm",
                conditions.acetic_acid_ppm,
                ValueSource.USER_EXPLICIT,
                extraction_method="llm_extraction",
            )

    # =========================================================================
    # RAG RETRIEVAL WITH HYBRID EXTRACTION
    # =========================================================================

    async def _ground_food_properties(
        self,
        food_description: str,
        grounded: GroundedValues,
    ) -> None:
        """
        Ground food pH and water activity via two-tier RAG retrieval.

        Composite-food guard (pre-Tier-1):
          If the food description matches a composite keyword, all three tiers
          are skipped.  grounded.composite_skip is populated for each field that
          still needs grounding (ph / water_activity), recording the matched
          keyword so downstream services can produce an informative audit entry
          with source COMPOSITE_FOOD_DEFAULT rather than CONSERVATIVE_DEFAULT.

        Tier 1 — primary query (threshold food_properties_confidence = 0.70):
          Single query retrieving the best-matching food doc.  Both pH and aw
          are extracted from that doc if present.  Source: RAG_RETRIEVAL.

        Tier 2 — per-field fallback (threshold food_properties_fallback_confidence = 0.62):
          Fires for each field still ungrounded after Tier 1, whether because
          the primary query missed threshold or because the top doc lacked that
          field.  Uses a targeted single-property query that can match
          category-level docs (e.g. "fresh poultry water activity").
          Source: RAG_RETRIEVAL_FALLBACK, with attributed_field set so the
          audit routing can link this retrieval to the correct field without
          relying on query-string keyword matching.

        CONSERVATIVE_DEFAULT fires only when both tiers produce no hit above
        their respective thresholds — it is the last resort, not the second.

        Range handling: both bounds are preserved with range_pending=True;
        StandardizationService selects the conservative bound based on model type.
        """
        # ── Composite-food guard ──────────────────────────────────────────────
        # Must run before any retrieval call so composite queries cannot
        # accidentally match a single-ingredient document at high confidence
        # and bypass this check (e.g. "chili" → "chili sauce acidified").
        matched_keyword = _composite_keyword_match(food_description)
        if matched_keyword is not None:
            if not grounded.has("ph"):
                grounded.composite_skip["ph"] = matched_keyword
            if not grounded.has("water_activity"):
                grounded.composite_skip["water_activity"] = matched_keyword
            return

        # ── Tier 1: primary query ─────────────────────────────────────────────
        primary_response = await asyncio.to_thread(
            self._retrieval.query_food_properties, food_description
        )
        primary_meta = _build_retrieval_metadata(primary_response)
        grounded.retrievals.append(primary_meta)

        if primary_response.has_confident_result:
            top = primary_response.top_result
            content = top.content
            props, ph_raw_match, aw_raw_match = await self._extract_food_properties(
                content
            )

            if not grounded.has("ph") and props.has_ph:
                self._set_ph_from_props(
                    grounded,
                    props,
                    top,
                    content,
                    ph_raw_match,
                    ValueSource.RAG_RETRIEVAL,
                )

            if not grounded.has("water_activity") and props.has_aw:
                self._set_aw_from_props(
                    grounded,
                    props,
                    top,
                    content,
                    aw_raw_match,
                    ValueSource.RAG_RETRIEVAL,
                )

        # ── Tier 2: per-field fallback queries ───────────────────────────────
        # Fire for any field still ungrounded — regardless of whether Tier 1
        # missed threshold entirely or returned a doc that lacked the field.
        if not grounded.has("ph"):
            await self._ground_field_fallback(food_description, "ph", grounded)

        if not grounded.has("water_activity"):
            await self._ground_field_fallback(
                food_description, "water_activity", grounded
            )

        # ── Tier 3: taxonomy bridge ───────────────────────────────────────────
        # Fires only when at least one field is still ungrounded after both
        # Tier 1 and Tier 2.  Resolves the food name to a FoodEx2 ptm_category
        # via deterministic fuzzy matching, then reads food_properties rows for
        # that category directly from the pre-loaded CSV.  No ChromaDB query.
        if not grounded.has("ph") or not grounded.has("water_activity"):
            self._ground_via_taxonomy_bridge(food_description, grounded)

    async def _ground_field_fallback(
        self,
        food_description: str,
        field: str,
        grounded: GroundedValues,
    ) -> None:
        """
        Fire a targeted per-field fallback retrieval (Tier 2).

        Uses food_properties_fallback_confidence threshold (0.62).  The
        RetrievalResult is tagged with attributed_field so the audit routing
        in translation.py can link it to the correct field without relying on
        query-string keyword heuristics.
        """
        if field == "ph":
            response = await asyncio.to_thread(
                self._retrieval.query_food_ph, food_description
            )
        else:
            response = await asyncio.to_thread(
                self._retrieval.query_food_water_activity, food_description
            )

        fallback_meta = _build_retrieval_metadata(response)
        fallback_meta.attributed_field = field
        grounded.retrievals.append(fallback_meta)

        if not response.has_confident_result:
            grounded.warnings.append(
                f"Could not retrieve {field} for '{food_description}' from knowledge base "
                f"(primary and fallback queries both below threshold)"
            )
            return

        top = response.top_result
        content = top.content
        props, ph_raw_match, aw_raw_match = await self._extract_food_properties(content)

        if field == "ph" and props.has_ph:
            self._set_ph_from_props(
                grounded,
                props,
                top,
                content,
                ph_raw_match,
                ValueSource.RAG_RETRIEVAL_FALLBACK,
            )
        elif field == "water_activity" and props.has_aw:
            self._set_aw_from_props(
                grounded,
                props,
                top,
                content,
                aw_raw_match,
                ValueSource.RAG_RETRIEVAL_FALLBACK,
            )
        else:
            grounded.warnings.append(
                f"Fallback retrieval for {field} returned a doc with no {field} data "
                f"(food='{food_description}', doc='{top.doc_id}')"
            )

    def _ground_via_taxonomy_bridge(
        self,
        food_description: str,
        grounded: GroundedValues,
    ) -> None:
        """
        Tier 3 — taxonomy bridge: resolve food_description → ptm_category →
        single curated row, then set any still-missing pH or aw fields.

        This method is synchronous: TaxonomyBridge does all lookups in-memory
        from pre-loaded CSV data; no async I/O is needed.

        State-aware curated lookup
        --------------------------
        The bridge inherits only from rows explicitly published as category-wide
        claims in category_level_rows.csv.  The lookup key is (category, state,
        field); no envelope-across-all-rows is performed.

        _apply_state_default converts "unspecified"/"" to "fresh" before the
        lookup; the conversion is surfaced in CategoryBridgeInfo.assumed_state.

        Audit-honesty for missing curated rows (§8.7)
        -----------------------------------------------
        When the bridge resolves a category but no curated row exists for
        (category, state, field), grounded.bridge_attempts[field] is populated
        with a CategoryBridgeInfo so StandardizationService can emit a specific
        DefaultImputed reason rather than a silent "no value found".
        """
        if self._taxonomy_bridge is None:
            return

        resolution = self._taxonomy_bridge.resolve(food_description)
        if resolution is None:
            return

        raw_state = resolution.matched_state
        query_state = _apply_state_default(raw_state)
        # assumed_state is non-empty only when we converted "unspecified"/"" → "fresh"
        assumed_state = "fresh" if raw_state in ("unspecified", "") else ""

        fields_to_try: list[tuple[str, str, str]] = []
        if not grounded.has("ph"):
            fields_to_try.append(("ph", "ph_min", "ph_max"))
        if not grounded.has("water_activity"):
            fields_to_try.append(("water_activity", "aw_min", "aw_max"))

        for field_name, min_col, max_col in fields_to_try:
            field_key = (
                "ph" if field_name == "ph" else "aw"
            )  # matches _index_category_level_rows key convention
            curated_row = self._taxonomy_bridge.lookup_category_level_row(
                resolution.ptm_category, query_state, field_key
            )

            if curated_row is None:
                grounded.bridge_attempts[field_name] = CategoryBridgeInfo(
                    species=food_description,
                    resolved_category=resolution.ptm_category,
                    taxonomy_code=resolution.taxonomy_code,
                    taxonomy_label=resolution.taxonomy_label,
                    taxonomy_source_id=resolution.taxonomy_source_id,
                    matched_food_name=resolution.matched_food_name,
                    match_score=resolution.match_score,
                    property_row_food_name="",
                    property_row_source_ids=[],
                    query_state=query_state,
                    assumed_state=assumed_state,
                )
                continue

            try:
                val_min = float(curated_row[min_col])
                val_max = float(curated_row[max_col])
                if val_min > val_max:
                    logger.warning(
                        "Curated row for (%s, %s, %s) has min=%.4f > max=%.4f — "
                        "data may be transposed in category_level_rows.csv",
                        resolution.ptm_category,
                        query_state,
                        field_key,
                        val_min,
                        val_max,
                    )
            except (ValueError, KeyError) as exc:
                logger.warning(
                    "Taxonomy bridge: could not parse %s/%s in curated row for "
                    "(%s, %s, %s): %s",
                    min_col,
                    max_col,
                    resolution.ptm_category,
                    query_state,
                    field_key,
                    exc,
                )
                continue

            source_col = "ph_source_id" if field_name == "ph" else "aw_source_id"
            source_ids = [s for s in [curated_row.get(source_col, "")] if s]

            bridge_info = CategoryBridgeInfo(
                species=food_description,
                resolved_category=resolution.ptm_category,
                taxonomy_code=resolution.taxonomy_code,
                taxonomy_label=resolution.taxonomy_label,
                taxonomy_source_id=resolution.taxonomy_source_id,
                matched_food_name=resolution.matched_food_name,
                match_score=resolution.match_score,
                property_row_food_name=curated_row["food_name"],
                property_row_source_ids=source_ids,
                query_state=query_state,
                assumed_state=assumed_state,
            )

            grounded.set(
                field_name,
                val_min,
                source=ValueSource.RAG_RETRIEVAL_CATEGORY_BRIDGE,
                transformation_applied="range extracted via taxonomy bridge, awaiting standardization",
                extraction_method="taxonomy_bridge",
                parsed_range=[val_min, val_max],
                range_pending=True,
                category_bridge=bridge_info,
            )

    def _set_ph_from_props(
        self,
        grounded: GroundedValues,
        props,
        top,
        content: str,
        ph_raw_match: str | None,
        source: ValueSource,
    ) -> None:
        """Write pH into grounded values from an ExtractedFoodProperties result."""
        if props.ph_value is not None:
            grounded.set(
                "ph",
                props.ph_value,
                source=source,
                retrieval_source=top.doc_id,
                original_text=content,
                transformation_applied=f"Extracted via {props.extraction_method}",
                extraction_method=props.extraction_method,
                raw_match=ph_raw_match,
            )
        elif props.ph_min is not None and props.ph_max is not None:
            grounded.set(
                "ph",
                props.ph_min,
                source=source,
                retrieval_source=top.doc_id,
                original_text=content,
                transformation_applied="range extracted, awaiting standardization",
                extraction_method=props.extraction_method,
                raw_match=ph_raw_match,
                parsed_range=[props.ph_min, props.ph_max],
                range_pending=True,
            )

    def _set_aw_from_props(
        self,
        grounded: GroundedValues,
        props,
        top,
        content: str,
        aw_raw_match: str | None,
        source: ValueSource,
    ) -> None:
        """Write water_activity into grounded values from an ExtractedFoodProperties result."""
        if props.aw_value is not None:
            if 0.0 <= props.aw_value <= 1.0:
                grounded.set(
                    "water_activity",
                    props.aw_value,
                    source=source,
                    retrieval_source=top.doc_id,
                    original_text=content,
                    transformation_applied=f"Extracted via {props.extraction_method}",
                    extraction_method=props.extraction_method,
                    raw_match=aw_raw_match,
                )
            else:
                grounded.warnings.append(
                    f"Discarding invalid aw={props.aw_value} extracted from RAG "
                    f"(must be 0–1; regex/LLM extraction error)"
                )
        elif props.aw_min is not None and props.aw_max is not None:
            grounded.set(
                "water_activity",
                props.aw_min,
                source=source,
                retrieval_source=top.doc_id,
                original_text=content,
                transformation_applied="range extracted, awaiting standardization",
                extraction_method=props.extraction_method,
                raw_match=aw_raw_match,
                parsed_range=[props.aw_min, props.aw_max],
                range_pending=True,
            )

    async def _extract_food_properties(
        self, text: str
    ) -> tuple[ExtractedFoodProperties, str | None, str | None]:
        """
        Extract food properties using hybrid approach.

        Returns (props, ph_raw_match, aw_raw_match) where the raw match strings
        are the text fragments matched by regex before numeric parsing.  When a
        value was filled by the LLM fallback the corresponding raw_match is None.

        1. Try regex extraction (fast, free)
        2. Fall back to LLM if regex fails and LLM enabled
        """
        # Try regex first; capture raw match text before validation
        ph = self._extract_numeric_value(text, ["ph"])
        aw = self._extract_numeric_value(text, ["water activity", "aw"])

        # Raw match strings from the regex pass (None if regex found nothing)
        ph_raw = ph.original_text
        aw_raw = aw.original_text

        # Build result from regex.
        # ph_max/aw_max must only be set when is_range=True; setting them for
        # single values would trigger the range-selection branch downstream with
        # ph_min=None, causing a crash or silent wrong-value selection.
        # Domain constraints are applied here so physically impossible regex
        # results (e.g. aw=200 from a citation year) are treated as "not found",
        # which lets the LLM fallback run and recover the real value.
        def _valid_ph(v: float | None) -> float | None:
            return v if v is not None and 0.0 <= v <= 14.0 else None

        def _valid_aw(v: float | None) -> float | None:
            return v if v is not None and 0.0 <= v <= 1.0 else None

        props = ExtractedFoodProperties(
            ph_value=_valid_ph(ph.value) if not ph.is_range else None,
            ph_min=_valid_ph(ph.range_min),
            ph_max=_valid_ph(ph.range_max) if ph.is_range else None,
            aw_value=_valid_aw(aw.value) if not aw.is_range else None,
            aw_min=_valid_aw(aw.range_min),
            aw_max=_valid_aw(aw.range_max) if aw.is_range else None,
            extraction_method="regex",
        )

        # If both found with regex, return immediately
        if props.has_ph and props.has_aw:
            return props, ph_raw, aw_raw

        # Fall back to LLM if enabled and regex missed something
        if self._use_llm_extraction and (not props.has_ph or not props.has_aw):
            try:
                llm_props = await self._extract_food_properties_llm(text)
                method = "regex+llm" if (props.has_ph or props.has_aw) else "llm"
                # Fields filled by LLM have no raw_match
                if not props.has_ph and llm_props.has_ph:
                    ph_raw = None
                if not props.has_aw and llm_props.has_aw:
                    aw_raw = None
                merged = ExtractedFoodProperties(
                    ph_value=props.ph_value or llm_props.ph_value,
                    ph_min=props.ph_min or llm_props.ph_min,
                    ph_max=props.ph_max or llm_props.ph_max,
                    aw_value=props.aw_value or llm_props.aw_value,
                    aw_min=props.aw_min or llm_props.aw_min,
                    aw_max=props.aw_max or llm_props.aw_max,
                    extraction_method=method,
                )
                return merged, ph_raw, aw_raw
            except Exception as exc:
                # LLM failed — log and fall back to regex results
                logger.warning(
                    "LLM food property extraction failed: %s", exc, exc_info=True
                )

        return props, ph_raw, aw_raw

    async def _extract_food_properties_llm(self, text: str) -> ExtractedFoodProperties:
        """Extract food properties using LLM."""
        result = await self._llm.extract(
            response_model=ExtractedFoodProperties,  # Same model
            messages=[{"role": "user", "content": text}],
            system_prompt=FOOD_PROPERTIES_EXTRACTION_PROMPT.format(text=text),
            temperature=0.0,
        )
        result.extraction_method = "llm"
        return result

    # =========================================================================
    # REGEX EXTRACTION (kept as fast first pass)
    # =========================================================================

    def _extract_numeric_value(
        self,
        text: str,
        keywords: list[str],
    ) -> ExtractedNumericValue:
        """
        Extract numeric value(s) near a keyword, handling ranges.

        Handles multiple formats:
        - Single values: "pH 6.0", "pH: 6.5", "aw 0.98"
        - Ranges with hyphen: "pH 5.9-6.2"
        - Ranges with "to": "pH 5.5 to 6.0"
        - Ranges with "and": "pH between 5.5 and 6.0"

        Args:
            text: The text to search
            keywords: List of keywords to look for (e.g., ["ph"], ["water activity", "aw"])

        Returns:
            ExtractedNumericValue with the extracted value(s)
        """
        text_lower = text.lower()

        for keyword in keywords:
            keyword_lower = keyword.lower()
            # Use word-boundary matching so short tokens like "aw" don't match
            # inside longer words (e.g. "raw", "thaw", "draw").
            m = re.search(rf"\b{re.escape(keyword_lower)}\b", text_lower)
            if m is None:
                continue

            after_keyword = text_lower[m.end() :]

            # Pattern 1: "between X and Y" or "from X to Y"
            range_pattern1 = (
                r"(?:between|from)?\s*(\d+\.?\d*)\s*(?:and|to|-)\s*(\d+\.?\d*)"
            )
            match = re.search(range_pattern1, after_keyword[:50])
            if match:
                val1 = float(match.group(1))
                val2 = float(match.group(2))
                return ExtractedNumericValue(
                    value=min(val1, val2),
                    is_range=True,
                    range_min=min(val1, val2),
                    range_max=max(val1, val2),
                    original_text=match.group(0).strip(),
                )

            # Pattern 2: "X-Y" or "X - Y"
            range_pattern2 = r"[:\s]*(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)"
            match = re.search(range_pattern2, after_keyword[:30])
            if match:
                val1 = float(match.group(1))
                val2 = float(match.group(2))
                return ExtractedNumericValue(
                    value=min(val1, val2),
                    is_range=True,
                    range_min=min(val1, val2),
                    range_max=max(val1, val2),
                    original_text=match.group(0).strip(),
                )

            # Pattern 3: Single value — must appear immediately after the keyword
            # (optional connector: colon, equals, whitespace, "is", "of").
            # Anchored with re.match so a number buried in unrelated text (e.g.
            # a citation year like "[FDA-PH-2007]") is never captured.
            single_pattern = r"^[:\s=]*(?:(?:is|of)\s+)?(\d+\.?\d*)"
            match = re.match(single_pattern, after_keyword)
            if match and match.group(1):
                return ExtractedNumericValue(
                    value=float(match.group(1)),
                    is_range=False,
                    original_text=match.group(0).strip(),
                )

        return ExtractedNumericValue()

    # =========================================================================
    # PATHOGEN GROUNDING
    # =========================================================================

    async def _ground_pathogen_from_rag(
        self,
        food_description: str,
        grounded: GroundedValues,
    ) -> None:
        """Ground pathogen via two-stage RAG retrieval with category-level fallback.

        Stage 1 — food name resolution: semantic query identifies the canonical
        food_name metadata key (e.g. "raw chicken" → "chicken raw").

        Stage 2 — ranked fetch: metadata filter retrieves all hazards for that
        food, sorted by annual_deaths_us descending so the most dangerous
        pathogen is selected deterministically, not by embedding similarity.

        When Stages 1+2 yield no confident result (three paths: Stage 1 below
        threshold, Stage 2 empty, or Stage 2 from_text unmapped), the
        category-level fallback fires instead of the former embedding fallback.
        """
        # Stage 1: resolve food description to canonical food_name
        response = await asyncio.to_thread(
            self._retrieval.query_pathogen_hazards, food_description
        )

        retrieval_meta = _build_retrieval_metadata(response)
        retrieval_meta.attributed_field = "organism"
        grounded.retrievals.append(retrieval_meta)

        if not response.has_confident_result:
            # Stage 1 below threshold — go directly to category fallback.
            self._category_pathogen_fallback(food_description, grounded)
            return

        top = response.top_result
        food_name = top.metadata.get("food_name") if top.metadata else None

        # Stage 2: fetch all hazards for this food, ranked by annual deaths
        if food_name:
            ranked = await asyncio.to_thread(
                self._retrieval.get_hazards_for_food, food_name
            )
            if ranked:
                best = ranked[0]
                organism = ComBaseOrganism.from_text(best.get("document", ""))
                if organism:
                    grounded.set(
                        "organism",
                        organism,
                        source=ValueSource.RAG_RETRIEVAL,
                        retrieval_source=best.get("id"),
                        original_text=best.get("document", ""),
                        extraction_method="ranked_by_annual_deaths",
                    )
                    return
                # from_text returned None — fall through to category fallback

        # food_name absent, Stage 2 empty, or from_text unmapped → category fallback.
        self._category_pathogen_fallback(food_description, grounded)

    def _category_pathogen_fallback(
        self,
        food_description: str,
        grounded: GroundedValues,
    ) -> None:
        """Category-level pathogen fallback for when food-specific hazard lookup yields no result.

        Resolves food → ptm_category (FoodEx2 bridge) → IFT-2003-T1 categories
        → union of pathogens → ranked by annual_deaths_us → top ComBaseOrganism-
        mappable candidate.  Fails closed at every step: if any step produces no
        result, the method returns without setting organism, preserving the
        existing ungrounded path.
        """
        if not self._taxonomy_bridge:
            grounded.organism_failure = OrganismGroundingFailure(
                stage=OrganismGroundingFailureStage.BRIDGE_DISABLED,
                detail="Taxonomy bridge is disabled (PTM_TAXONOMY_BRIDGE_ENABLED=false)",
            )
            return

        # Step 1: Resolve food → ptm_category via FoodEx2 bridge
        resolution = self._taxonomy_bridge.resolve(food_description)
        if resolution is None:
            grounded.organism_failure = OrganismGroundingFailure(
                stage=OrganismGroundingFailureStage.FOOD_UNRECOGNISED,
                detail=f"Taxonomy bridge could not resolve '{food_description}' to a FoodEx2 category",
            )
            return

        ptm_category = resolution.ptm_category

        # Step 2: Map ptm_category → IFT categories
        ift_categories = self._ift_alignment.get(ptm_category)
        if not ift_categories:
            grounded.organism_failure = OrganismGroundingFailure(
                stage=OrganismGroundingFailureStage.CATEGORY_HAS_NO_HAZARD_DATA,
                detail=f"Category '{ptm_category}' has no IFT-2003-T1 hazard mapping",
                resolved_category=ptm_category,
                match_score=resolution.match_score,
            )
            return

        # Step 3: Gather union of pathogen names across all IFT categories;
        # deduplicate before ranking (cheaper and semantically equivalent).
        seen_lower: set[str] = set()
        candidate_names: list[str] = []
        for ift_cat in ift_categories:
            for pathogen in self._pathogen_associations.get(ift_cat, []):
                key = pathogen.lower()
                if key not in seen_lower:
                    seen_lower.add(key)
                    candidate_names.append(pathogen)

        if not candidate_names:
            grounded.organism_failure = OrganismGroundingFailure(
                stage=OrganismGroundingFailureStage.INTERNAL_NO_MAPPABLE_CANDIDATE,
                detail=f"No pathogens found in pathogen_food_associations.csv for IFT categories {list(ift_categories)}",
            )
            return

        # Step 4: Rank by annual_deaths_us from pathogen_characteristics.csv.
        # Pathogens absent from characteristics are excluded entirely
        # (absence of evidence ≠ zero deaths).
        # Pathogens present with annual_deaths=0 are ranked last (not excluded).
        ranked: list[PathogenCandidate] = []
        for pathogen in candidate_names:
            norm_name = _PATHOGEN_NAME_NORMALIZATION.get(
                pathogen.lower(), pathogen.lower()
            )
            entry = self._pathogen_characteristics.get(norm_name)
            if entry is None:
                continue  # not in characteristics — exclude from ranking
            deaths, source_id = entry
            ranked.append(
                PathogenCandidate(
                    pathogen=pathogen,  # associations CSV form e.g. "Salmonella spp."
                    normalized_name=norm_name,  # characteristics CSV form e.g. "salmonella nontyphoidal"
                    annual_deaths_us=deaths,
                    source_id=source_id,
                )
            )

        ranked.sort(key=lambda c: c.annual_deaths_us, reverse=True)

        if not ranked:
            grounded.organism_failure = OrganismGroundingFailure(
                stage=OrganismGroundingFailureStage.INTERNAL_NO_MAPPABLE_CANDIDATE,
                detail="All candidate pathogens are absent from pathogen_characteristics.csv",
            )
            return

        # Step 5: Select the top-ranked candidate that maps to a ComBaseOrganism;
        # descend on failure and record skipped candidates.
        selected: PathogenCandidate | None = None
        selected_organism: ComBaseOrganism | None = None
        skipped: list[dict] = []
        for candidate in ranked:
            # Use the original associations-CSV name for from_text() — it contains
            # recognisable substrings like "Salmonella" that the alias dict matches.
            organism = ComBaseOrganism.from_text(candidate.pathogen)
            if organism is None:
                skipped.append(
                    {
                        "pathogen": candidate.pathogen,
                        "reason": "no_combase_organism_mapping",
                    }
                )
                continue
            selected = candidate
            selected_organism = organism
            break

        if selected is None or selected_organism is None:
            grounded.organism_failure = OrganismGroundingFailure(
                stage=OrganismGroundingFailureStage.INTERNAL_NO_MAPPABLE_CANDIDATE,
                detail="All ranked candidate pathogens failed ComBaseOrganism mapping",
            )
            return

        _pcf_source_ids = list(
            dict.fromkeys(["IFT-2003-T1"] + [c.source_id for c in ranked])
        )
        fallback_info = PathogenCategoryFallbackInfo(
            ptm_category=ptm_category,
            ift_categories=list(
                ift_categories
            ),  # defensive copy — ift_categories is a ref into _ift_alignment
            ift_source_id="IFT-2003-T1",
            candidate_pathogens=ranked,
            selected_pathogen=selected,
            skipped_pathogens=skipped,
            full_citations=get_full_citations(_pcf_source_ids),
        )

        grounded.set(
            "organism",
            selected_organism,
            source=ValueSource.RAG_PATHOGEN_CATEGORY_FALLBACK,
            original_text=selected.pathogen,
            extraction_method="category_fallback_ranked_by_annual_deaths",
            pathogen_category_fallback=fallback_info,
        )

        # Emit a transparency warning so the audit surface names the inference.
        grounded.warnings.append(
            f"Organism {selected_organism.value!r} inferred from food category "
            f"'{ptm_category}' (IFT-2003-T1) — no specific hazard data for "
            f"'{food_description}'. Pathogen ranked by CDC annual deaths."
        )

    def rank_executable_organisms(
        self, executable: list[ComBaseOrganism]
    ) -> list[ComBaseOrganism]:
        """
        Rank a caller-supplied set of executable organisms by CDC annual death
        toll. Originally built to derive the organism clarification gate's
        options menu; that menu was deleted in the 2026-08-19 free-text
        redesign (see specs/lessons.md), so this method currently has no
        production caller — kept intentionally, not orphaned by oversight, as
        a general-purpose severity-ranking utility (same treatment as
        SemanticParser.extract_clarification_response(), also kept with no
        production caller for the same reason). Still exercised directly by
        its own unit tests (tests/unit/test_grounding_service.py).

        Uses the same severity metric (annual_deaths_us from
        pathogen_characteristics.csv, via self._pathogen_characteristics) and
        the same ComBaseOrganism.from_text() name mapping that
        _category_pathogen_fallback() uses — just inverted: that method ranks
        candidate pathogen *names* pulled from a food category's associations
        and then maps to organism; this ranks *organisms* the caller already
        knows are executable, keeping only the ones this table can score. One
        severity metric and one name-mapping function, not a second ranker.

        Organisms absent from pathogen_characteristics.csv are excluded
        entirely (absence of evidence != zero deaths — same convention as
        _category_pathogen_fallback's Step 4).

        Presentation order only — never a likelihood claim. The caller does
        not know the food (that is why organism grounding failed), so CDC
        death toll is the least-arbitrary deterministic order available, not
        a prediction about which pathogen is likely for this food.
        """
        executable_set = set(executable)
        seen: set[ComBaseOrganism] = set()
        scored: list[tuple[ComBaseOrganism, int]] = []
        for name, (deaths, _source_id) in self._pathogen_characteristics.items():
            organism = ComBaseOrganism.from_text(name)
            if organism is None or organism not in executable_set or organism in seen:
                continue
            seen.add(organism)
            scored.append((organism, deaths))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return [organism for organism, _deaths in scored]

    # =========================================================================
    # INTERPRETATION RULES
    # =========================================================================

    def _resolve_temperature_value(
        self,
        temp: ExtractedTemperature,
    ) -> tuple[float | None, ValueProvenance | None]:
        """
        Resolve an ExtractedTemperature to a numeric value with provenance.

        Priority:
        1. Explicit numeric value → USER_EXPLICIT
        2. User-supplied range → USER_EXPLICIT, range_pending=True (lower bound stored)
        3. Description via interpretation rules → USER_INFERRED

        When a range is returned, both bounds are preserved in parsed_range and
        range_pending is True.  StandardizationService selects the conservative bound.

        Returns (value, provenance) or (None, None) if unresolvable.
        """
        if temp.value_celsius is not None:
            return temp.value_celsius, ValueProvenance(
                source=ValueSource.USER_EXPLICIT,
                extraction_method="llm_extraction",
            )

        if (
            temp.is_range
            and temp.range_min_celsius is not None
            and temp.range_max_celsius is not None
        ):
            return temp.range_min_celsius, ValueProvenance(
                source=ValueSource.USER_EXPLICIT,
                transformation_applied="range extracted, awaiting standardization",
                extraction_method="llm_extraction",
                parsed_range=[temp.range_min_celsius, temp.range_max_celsius],
                range_pending=True,
            )

        if temp.description:
            rule = find_temperature_interpretation_with_fallback(temp.description)
            if rule:
                method = (
                    "embedding_fallback"
                    if rule.similarity is not None
                    else "rule_match"
                )
                return rule.value, ValueProvenance(
                    source=ValueSource.USER_INFERRED,
                    original_text=temp.description,
                    transformation_applied=f"Interpreted as {rule.value}°C ({rule.notes})",
                    extraction_method=method,
                    matched_pattern=rule.pattern,
                    rule_conservative=rule.conservative,
                    rule_notes=rule.notes,
                    embedding_similarity=rule.similarity,
                    canonical_phrase=rule.canonical_phrase,
                )

        return None, None

    def _resolve_duration_value(
        self,
        dur: ExtractedDuration,
    ) -> tuple[float | None, ValueProvenance | None]:
        """
        Resolve an ExtractedDuration to a numeric value with provenance.

        Priority:
        1. Explicit numeric value → USER_EXPLICIT
        2. User-supplied range → USER_EXPLICIT, range_pending=True (lower bound stored)
        3. Description via interpretation rules → USER_INFERRED

        When a range is returned, both bounds are preserved in parsed_range and
        range_pending is True.  StandardizationService selects the conservative bound.

        Returns (value, provenance) or (None, None) if unresolvable.
        """
        if dur.value_minutes is not None:
            return dur.value_minutes, ValueProvenance(
                source=ValueSource.USER_EXPLICIT,
                extraction_method="llm_extraction",
            )

        if dur.range_min_minutes is not None and dur.range_max_minutes is not None:
            return dur.range_min_minutes, ValueProvenance(
                source=ValueSource.USER_EXPLICIT,
                transformation_applied="range extracted, awaiting standardization",
                extraction_method="llm_extraction",
                parsed_range=[dur.range_min_minutes, dur.range_max_minutes],
                range_pending=True,
            )

        if dur.description:
            rule = find_duration_interpretation(dur.description)
            if rule:
                return rule.value, ValueProvenance(
                    source=ValueSource.USER_INFERRED,
                    original_text=dur.description,
                    transformation_applied=f"Interpreted as {rule.value} min ({rule.notes})",
                    extraction_method="rule_match",
                    matched_pattern=rule.pattern,
                    rule_conservative=rule.conservative,
                    rule_notes=rule.notes,
                )

        return None, None

    def _ground_temperature(
        self,
        scenario: ExtractedScenario,
        grounded: GroundedValues,
    ) -> None:
        """Ground single-step temperature into grounded.temperature_celsius.

        A1c: the two mark_ungrounded() reasons below are deliberately distinct
        sentences, not a shared template — "user said something we couldn't
        parse" and "user said nothing" are different epistemic states (see
        specs/lessons.md, 2026-05-14 §2.4). Model type isn't known at
        grounding time (ground_scenario() doesn't receive it), so neither
        message names the eventual default's numeric value — that would be
        wrong for THERMAL_INACTIVATION scenarios, whose default differs from
        the GROWTH/NON_THERMAL_SURVIVAL abuse-temperature default applied in
        StandardizationService._get_temperature().
        """
        value, prov = self._resolve_temperature_value(scenario.single_step_temperature)
        if value is not None and prov is not None:
            grounded.set_with_prov("temperature_celsius", value, prov)
        else:
            desc = scenario.single_step_temperature.description
            if desc:
                grounded.mark_ungrounded(
                    "temperature_celsius",
                    f"Temperature description '{desc}' could not be interpreted "
                    "— a conservative default temperature will be assumed for "
                    "this prediction.",
                )
            else:
                grounded.mark_ungrounded(
                    "temperature_celsius",
                    "No temperature was specified — a conservative default "
                    "temperature will be assumed for this prediction.",
                )

    def _ground_duration(
        self,
        scenario: ExtractedScenario,
        grounded: GroundedValues,
    ) -> None:
        """Ground single-step duration into grounded.duration_minutes."""
        value, prov = self._resolve_duration_value(scenario.single_step_duration)
        if value is not None and prov is not None:
            grounded.set_with_prov("duration_minutes", value, prov)
        else:
            desc = scenario.single_step_duration.description
            if desc:
                grounded.mark_ungrounded(
                    "duration_minutes", f"Could not interpret: '{desc}'"
                )
            else:
                grounded.mark_ungrounded("duration_minutes", "No duration specified")

    def _ground_multi_step_profile(
        self,
        scenario: ExtractedScenario,
        grounded: GroundedValues,
    ) -> None:
        """
        Ground each step in a multi-step time-temperature profile.

        Iterates scenario.time_temperature_steps in sequence order, resolves
        temperature and duration for each step using the same priority rules as
        the single-step path, and appends each result to grounded.steps.

        Range values are stored with range_pending=True on the provenance object;
        StandardizationService selects the conservative bound per step.

        Steps with unresolvable values store None; the standardization service
        will apply defaults for temperature and flag missing durations.

        Also carries the raw `description` phrase for each field onto
        GroundedStep (duration_phrase/temperature_phrase), unconditionally,
        for future clarification quoting.
        """
        sorted_steps = sorted(
            scenario.time_temperature_steps,
            key=lambda s: s.sequence_order if s.sequence_order is not None else 999,
        )
        for idx, step in enumerate(sorted_steps, start=1):
            order = step.sequence_order if step.sequence_order is not None else idx

            temp_val, temp_prov = self._resolve_temperature_value(step.temperature)
            dur_val, dur_prov = self._resolve_duration_value(step.duration)

            if temp_val is None:
                desc = step.temperature.description or ""
                reason = (
                    f"Could not interpret: '{desc}'"
                    if desc
                    else "No temperature specified"
                )
                grounded.warnings.append(f"Step {order} temperature: {reason}")

            if dur_val is None:
                desc = step.duration.description or ""
                reason = (
                    f"Could not interpret: '{desc}'"
                    if desc
                    else "No duration specified"
                )
                grounded.warnings.append(f"Step {order} duration: {reason}")

            grounded.add_step(
                step_order=order,
                temperature_celsius=temp_val,
                duration_minutes=dur_val,
                temp_provenance=temp_prov,
                dur_provenance=dur_prov,
                duration_phrase=step.duration.description,
                temperature_phrase=step.temperature.description,
            )


# =============================================================================
# SINGLETON
# =============================================================================

_service: GroundingService | None = None


def get_grounding_service() -> GroundingService:
    """Get or create the global GroundingService instance."""
    global _service
    if _service is None:
        _service = GroundingService()
    return _service


def reset_grounding_service() -> None:
    """Reset the global service (for testing)."""
    global _service
    _service = None
