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
import re
from dataclasses import dataclass, field

from app.config.rules import (
    find_temperature_interpretation_with_fallback,
    find_duration_interpretation,
)
from app.models.enums import ComBaseOrganism
from app.models.extraction import (
    ExtractedScenario,
    ExtractedEnvironmentalConditions,
    ExtractedFoodProperties,
    ExtractedTemperature,
    ExtractedDuration,
)
from app.models.metadata import ValueProvenance, ValueSource, RetrievalResult, RunnerUpResult
from app.rag.retrieval import RetrievalService, get_retrieval_service, RetrievalResponse
from app.services.audit.citations import get_full_citations
from app.services.llm.client import LLMClient, get_llm_client

logger = logging.getLogger(__name__)

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
    emb = (1.0 - r.distance) if r.distance is not None else None
    return RunnerUpResult(
        doc_id=r.doc_id,
        content_preview=r.content[:120] if r.content else None,
        embedding_score=round(emb, 4) if emb is not None else None,
        rerank_score=round(r.rerank_score, 4) if r.rerank_score is not None else None,
    )


def _build_retrieval_metadata(response: RetrievalResponse) -> RetrievalResult:
    """
    Build a metadata RetrievalResult from a rag-layer RetrievalResponse.

    Captures embedding/rerank scores, source_ids, full citations, and
    runners-up from the full result list rather than only the top hit.

    All attribute reads are guarded with isinstance checks because tests
    supply MagicMock objects that satisfy the duck-type interface but carry
    non-numeric values for optional fields.
    """
    top = response.results[0] if response.results else None

    embedding_score: float | None = None
    rerank_score: float | None = None
    source_ids: list[str] = []
    full_citations: dict[str, str] = {}
    runners_up: list[RunnerUpResult] = []

    if top:
        dist = top.distance
        if isinstance(dist, (int, float)):
            embedding_score = round(1.0 - dist, 4)
        rr = top.rerank_score
        if isinstance(rr, (int, float)):
            rerank_score = round(rr, 4)
        meta = top.metadata
        raw_sid = meta.get("source_id", "") if isinstance(meta, dict) else ""
        raw_sid = raw_sid or ""
        source_ids = [s.strip() for s in raw_sid.split(",") if s.strip()]
        full_citations = get_full_citations(source_ids)
        runners_up = [_to_runner_up(r) for r in response.results[1:4]]

    query = response.query if isinstance(response.query, str) else ""

    return RetrievalResult(
        query=query,
        source_document=top.source if top else None,
        chunk_id=top.doc_id if top else None,
        retrieved_text=top.content if top else None,
        fallback_used=not response.has_confident_result,
        embedding_score=embedding_score,
        rerank_score=rerank_score,
        source_ids=source_ids,
        full_citations=full_citations,
        runners_up=runners_up,
    )



@dataclass
class GroundedStep:
    """A single grounded time-temperature step for multi-step scenarios."""
    step_order: int
    temperature_celsius: float | None
    duration_minutes: float | None
    temp_provenance: ValueProvenance | None = None
    dur_provenance: ValueProvenance | None = None


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
    ) -> None:
        """Append a grounded time-temperature step."""
        self.steps.append(GroundedStep(
            step_order=step_order,
            temperature_celsius=temperature_celsius,
            duration_minutes=duration_minutes,
            temp_provenance=temp_provenance,
            dur_provenance=dur_provenance,
        ))

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
    ):
        self._retrieval = retrieval_service or get_retrieval_service()
        self._llm = llm_client or get_llm_client()
        self._use_llm_extraction = use_llm_extraction
    
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
                f"Could not determine pathogen for '{scenario.food_description or 'unknown food'}'"
            )

        # Step 5 & 6: Temperature and duration
        if scenario.is_multi_step and scenario.time_temperature_steps:
            self._ground_multi_step_profile(scenario, grounded)
        else:
            self._ground_temperature(scenario, grounded)
            self._ground_duration(scenario, grounded)

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
        # pH
        if conditions.ph_value is not None:
            if 0.0 <= conditions.ph_value <= 14.0:
                grounded.set(
                    "ph",
                    conditions.ph_value,
                    source=ValueSource.USER_EXPLICIT,
                    extraction_method="direct",
                )
            else:
                grounded.warnings.append(
                    f"Ignoring extracted ph_value={conditions.ph_value} "
                    f"(must be 0–14; likely LLM field confusion)"
                )

        # Water activity
        if conditions.water_activity is not None:
            if 0.0 <= conditions.water_activity <= 1.0:
                grounded.set(
                    "water_activity",
                    conditions.water_activity,
                    source=ValueSource.USER_EXPLICIT,
                    extraction_method="direct",
                )
            else:
                grounded.warnings.append(
                    f"Ignoring extracted water_activity={conditions.water_activity} "
                    f"(must be 0–1; likely LLM field confusion)"
                )

        # Other conditions (these don't require range selection)
        if conditions.co2_percent is not None:
            grounded.set("co2_percent", conditions.co2_percent, ValueSource.USER_EXPLICIT,
                         extraction_method="direct")
        if conditions.nitrite_ppm is not None:
            grounded.set("nitrite_ppm", conditions.nitrite_ppm, ValueSource.USER_EXPLICIT,
                         extraction_method="direct")
        if conditions.lactic_acid_ppm is not None:
            grounded.set("lactic_acid_ppm", conditions.lactic_acid_ppm, ValueSource.USER_EXPLICIT,
                         extraction_method="direct")
        if conditions.acetic_acid_ppm is not None:
            grounded.set("acetic_acid_ppm", conditions.acetic_acid_ppm, ValueSource.USER_EXPLICIT,
                         extraction_method="direct")
    
    # =========================================================================
    # RAG RETRIEVAL WITH HYBRID EXTRACTION
    # =========================================================================
    
    async def _ground_food_properties(
        self,
        food_description: str,
        grounded: GroundedValues,
    ) -> None:
        """
        Ground food pH and water activity via RAG with hybrid extraction.

        When a range is retrieved, both bounds are preserved: the lower bound is
        stored as the placeholder value with range_pending=True and
        parsed_range=[min, max].  StandardizationService selects the conservative
        bound based on model type.
        """
        response = await asyncio.to_thread(
            self._retrieval.query_food_properties, food_description
        )

        # Build and record enriched retrieval metadata
        retrieval_meta = _build_retrieval_metadata(response)
        grounded.retrievals.append(retrieval_meta)

        if not response.has_confident_result:
            if not grounded.has("ph"):
                grounded.warnings.append(
                    f"Could not retrieve pH for '{food_description}' from knowledge base"
                )
            if not grounded.has("water_activity"):
                grounded.warnings.append(
                    f"Could not retrieve water activity for '{food_description}' from knowledge base"
                )
            return

        top = response.top_result
        content = top.content

        # Extract properties using hybrid approach (returns props + raw match strings)
        props, ph_raw_match, aw_raw_match = await self._extract_food_properties(content)

        # Set pH if found and not already set
        if not grounded.has("ph") and props.has_ph:
            if props.ph_value is not None:
                grounded.set(
                    "ph",
                    props.ph_value,
                    source=ValueSource.RAG_RETRIEVAL,
                    retrieval_source=top.doc_id,
                    original_text=content,
                    transformation_applied=f"Extracted via {props.extraction_method}",
                    extraction_method=props.extraction_method,
                    raw_match=ph_raw_match,
                )
            elif props.ph_min is not None and props.ph_max is not None:
                # Range — store lower bound as placeholder; standardization picks the bound.
                grounded.set(
                    "ph",
                    props.ph_min,
                    source=ValueSource.RAG_RETRIEVAL,
                    retrieval_source=top.doc_id,
                    original_text=content,
                    transformation_applied="range extracted, awaiting standardization",
                    extraction_method=props.extraction_method,
                    raw_match=ph_raw_match,
                    parsed_range=[props.ph_min, props.ph_max],
                    range_pending=True,
                )

        # Set water activity if found and not already set
        if not grounded.has("water_activity") and props.has_aw:
            if props.aw_value is not None:
                if 0.0 <= props.aw_value <= 1.0:
                    grounded.set(
                        "water_activity",
                        props.aw_value,
                        source=ValueSource.RAG_RETRIEVAL,
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
                # Range — store lower bound as placeholder; standardization picks the bound.
                grounded.set(
                    "water_activity",
                    props.aw_min,
                    source=ValueSource.RAG_RETRIEVAL,
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
            m = re.search(rf'\b{re.escape(keyword_lower)}\b', text_lower)
            if m is None:
                continue

            after_keyword = text_lower[m.end():]

            # Pattern 1: "between X and Y" or "from X to Y"
            range_pattern1 = r'(?:between|from)?\s*(\d+\.?\d*)\s*(?:and|to|-)\s*(\d+\.?\d*)'
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
            range_pattern2 = r'[:\s]*(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)'
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
            single_pattern = r'^[:\s=]*(?:(?:is|of)\s+)?(\d+\.?\d*)'
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
        """
        Ground pathogen via RAG retrieval.
        
        Looks up the food in the pathogen hazards collection to find
        associated pathogens (e.g., chicken → Salmonella).
        """
        response = await asyncio.to_thread(
            self._retrieval.query_pathogen_hazards, food_description
        )

        retrieval_meta = _build_retrieval_metadata(response)
        grounded.retrievals.append(retrieval_meta)

        if response.has_confident_result:
            top = response.top_result
            organism = ComBaseOrganism.from_text(top.content)
            if organism:
                grounded.set(
                    "organism",
                    organism,
                    source=ValueSource.RAG_RETRIEVAL,
                    retrieval_source=top.doc_id,
                    original_text=top.content,
                    extraction_method="direct",
                )
    
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
                extraction_method="direct",
            )

        if temp.is_range and temp.range_min_celsius is not None and temp.range_max_celsius is not None:
            return temp.range_min_celsius, ValueProvenance(
                source=ValueSource.USER_EXPLICIT,
                transformation_applied="range extracted, awaiting standardization",
                extraction_method="direct",
                parsed_range=[temp.range_min_celsius, temp.range_max_celsius],
                range_pending=True,
            )

        if temp.description:
            rule = find_temperature_interpretation_with_fallback(temp.description)
            if rule:
                method = "embedding_fallback" if rule.similarity is not None else "rule_match"
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
                extraction_method="direct",
            )

        if dur.range_min_minutes is not None and dur.range_max_minutes is not None:
            return dur.range_min_minutes, ValueProvenance(
                source=ValueSource.USER_EXPLICIT,
                transformation_applied="range extracted, awaiting standardization",
                extraction_method="direct",
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
        """Ground single-step temperature into grounded.temperature_celsius."""
        value, prov = self._resolve_temperature_value(scenario.single_step_temperature)
        if value is not None and prov is not None:
            grounded.set_with_prov("temperature_celsius", value, prov)
        else:
            desc = scenario.single_step_temperature.description
            if desc:
                grounded.mark_ungrounded(
                    "temperature_celsius", f"Could not interpret: '{desc}'"
                )
            else:
                grounded.mark_ungrounded("temperature_celsius", "No temperature specified")

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
                reason = f"Could not interpret: '{desc}'" if desc else "No temperature specified"
                grounded.warnings.append(f"Step {order} temperature: {reason}")

            if dur_val is None:
                desc = step.duration.description or ""
                reason = f"Could not interpret: '{desc}'" if desc else "No duration specified"
                grounded.warnings.append(f"Step {order} duration: {reason}")

            grounded.add_step(
                step_order=order,
                temperature_celsius=temp_val,
                duration_minutes=dur_val,
                temp_provenance=temp_prov,
                dur_provenance=dur_prov,
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
