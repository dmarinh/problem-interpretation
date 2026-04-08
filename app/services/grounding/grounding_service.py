"""
Grounding Service

Resolves extracted values to grounded, validated values.

This service sits between the SemanticParser (which extracts raw user input)
and the StandardizationService (which prepares execution payloads).

IMPORTANT: Range Bound Selection
================================
When a user provides a range (e.g., "between 65 and 70°C"), the grounding
service must select which bound to use. This selection depends on the
model type:

- GROWTH models: Use UPPER bound (more temperature/time = more growth)
- THERMAL INACTIVATION models: Use LOWER bound (less temperature/time = less kill)
- NON_THERMAL SURVIVAL models: Use UPPER bound (same as growth)

This ensures we always err toward the worse food safety outcome.

Note: The GroundingService handles range selection during grounding.
The StandardizationService handles bias corrections AFTER grounding.
Both must use model-type-aware logic for correct conservative behavior.
"""

import re
from dataclasses import dataclass

from app.config.rules import (
    find_temperature_interpretation_with_fallback,
    find_duration_interpretation,
)
from app.models.enums import ComBaseOrganism, RetrievalConfidenceLevel, ModelType
from app.models.extraction import (
    ExtractedScenario,
    ExtractedEnvironmentalConditions,
    ExtractedFoodProperties,
)
from app.models.metadata import ValueProvenance, ValueSource, RetrievalResult
from app.rag.retrieval import RetrievalService, get_retrieval_service
from app.services.llm.client import LLMClient, get_llm_client


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
        self.values: dict = {}
        self.provenance: dict[str, ValueProvenance] = {}
        self.retrievals: list[RetrievalResult] = []
        self.warnings: list[str] = []
        self.ungrounded_fields: list[str] = []
    
    def set(
        self,
        field: str,
        value,
        source: ValueSource,
        confidence: float,
        **kwargs,
    ) -> None:
        """Set a grounded value with provenance."""
        self.values[field] = value
        self.provenance[field] = ValueProvenance(
            source=source,
            confidence=confidence,
            **kwargs,
        )
    
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
    4. Defaults are NOT applied here - that's the StandardizationService's job
    
    IMPORTANT: Range Selection
    --------------------------
    When values are given as ranges, the bound selection depends on the model type.
    This is passed to ground_scenario() via the optional model_type parameter.
    
    - Growth models: Use upper bound (more growth = worse)
    - Inactivation models: Use lower bound (less kill = worse)
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
        model_type: ModelType | None = None,
    ) -> GroundedValues:
        """
        Ground all values in an extracted scenario.
        
        Args:
            scenario: The extracted scenario from SemanticParser
            model_type: Optional model type for range bound selection.
                       If None, inferred from scenario.implied_model_type.
                       Defaults to GROWTH if not determinable.
        
        Returns:
            GroundedValues with resolved values and provenance
        
        Note on model_type:
            The model_type affects how ranges are resolved:
            - For GROWTH: ranges use upper bound (more growth = worse)
            - For THERMAL_INACTIVATION: ranges use lower bound (less kill = worse)
            - For NON_THERMAL_SURVIVAL: same as growth (more survival = worse)
        """
        grounded = GroundedValues()
        
        # Determine model type for range selection
        effective_model_type = model_type or scenario.implied_model_type or ModelType.GROWTH
        
        # Step 1: User explicit environmental conditions (highest priority)
        self._ground_environmental_conditions(
            scenario.environmental_conditions,
            grounded,
        )
        
        # Step 2: User explicit pathogen
        if scenario.pathogen_mentioned:
            organism = ComBaseOrganism.from_string(scenario.pathogen_mentioned)
            if organism:
                grounded.set(
                    "organism",
                    organism,
                    source=ValueSource.USER_EXPLICIT,
                    confidence=0.90,
                    original_text=scenario.pathogen_mentioned,
                )
        
        # Step 3: RAG for food properties - only if pH or aw still needed
        needs_ph = not grounded.has("ph")
        needs_aw = not grounded.has("water_activity")
        
        if scenario.food_description and (needs_ph or needs_aw):
            await self._ground_food_properties(
                scenario.food_description,
                grounded,
                effective_model_type,
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
        
        # Step 5: Temperature (interpretation rules with model-aware range selection)
        self._ground_temperature(scenario, grounded, effective_model_type)
        
        # Step 6: Duration (interpretation rules with model-aware range selection)
        self._ground_duration(scenario, grounded, effective_model_type)
        
        return grounded
    
    # =========================================================================
    # HELPER: RANGE BOUND SELECTION
    # =========================================================================
    
    def _select_range_bound(
        self,
        range_min: float,
        range_max: float,
        model_type: ModelType,
        field_name: str,
    ) -> tuple[float, str]:
        """
        Select which bound of a range to use based on model type.
        
        For conservative bias:
        - GROWTH models: Use upper bound (more temp/time = more growth = worse)
        - THERMAL_INACTIVATION: Use lower bound (less temp/time = less kill = worse)
        - NON_THERMAL_SURVIVAL: Use upper bound (more survival = worse)
        
        Args:
            range_min: Lower bound of the range
            range_max: Upper bound of the range
            model_type: The type of model being used
            field_name: Name of the field (for logging)
            
        Returns:
            Tuple of (selected_value, transformation_description)
        """
        if model_type == ModelType.THERMAL_INACTIVATION:
            # For cooking/inactivation: lower temp/time = less pathogen kill = worse
            value = range_min
            description = (
                f"Range {range_min}-{range_max}, using LOWER bound {range_min} "
                f"(conservative for thermal inactivation: less pathogen kill)"
            )
        else:
            # For growth/survival: higher temp/time = more growth = worse
            value = range_max
            description = (
                f"Range {range_min}-{range_max}, using UPPER bound {range_max} "
                f"(conservative for {model_type.value}: more pathogen growth)"
            )
        
        return value, description
    
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
        They have the highest priority and confidence (0.90).
        """
        # pH
        if conditions.ph_value is not None:
            grounded.set(
                "ph",
                conditions.ph_value,
                source=ValueSource.USER_EXPLICIT,
                confidence=0.90,
            )
        
        # Water activity
        if conditions.water_activity is not None:
            grounded.set(
                "water_activity",
                conditions.water_activity,
                source=ValueSource.USER_EXPLICIT,
                confidence=0.90,
            )
        
        # Other conditions (these don't require range selection)
        if conditions.co2_percent is not None:
            grounded.set("co2_percent", conditions.co2_percent, ValueSource.USER_EXPLICIT, 0.90)
        if conditions.nitrite_ppm is not None:
            grounded.set("nitrite_ppm", conditions.nitrite_ppm, ValueSource.USER_EXPLICIT, 0.90)
        if conditions.lactic_acid_ppm is not None:
            grounded.set("lactic_acid_ppm", conditions.lactic_acid_ppm, ValueSource.USER_EXPLICIT, 0.90)
        if conditions.acetic_acid_ppm is not None:
            grounded.set("acetic_acid_ppm", conditions.acetic_acid_ppm, ValueSource.USER_EXPLICIT, 0.90)
    
    # =========================================================================
    # RAG RETRIEVAL WITH HYBRID EXTRACTION
    # =========================================================================
    
    async def _ground_food_properties(
        self,
        food_description: str,
        grounded: GroundedValues,
        model_type: ModelType,
    ) -> None:
        """
        Ground food pH and water activity via RAG with hybrid extraction.
        
        This retrieves food properties from the knowledge base and extracts
        numeric values. When ranges are found, the bound selection depends
        on the model type (see _select_range_bound).
        """
        response = self._retrieval.query_food_properties(food_description)
        
        # Record retrieval attempt
        retrieval_result = RetrievalResult(
            query=f"{food_description} pH water activity",
            confidence_level=(
                response.results[0].confidence_level
                if response.results
                else RetrievalConfidenceLevel.FAILED
            ),
            confidence_score=(
                response.results[0].confidence
                if response.results
                else 0.0
            ),
            source_document=(
                response.results[0].source
                if response.results
                else None
            ),
            retrieved_text=(
                response.results[0].content
                if response.results
                else None
            ),
            fallback_used=not response.has_confident_result,
        )
        grounded.retrievals.append(retrieval_result)
        
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
        
        content = response.top_result.content
        
        # Extract properties using hybrid approach
        props = await self._extract_food_properties(content)
        
        # Set pH if found and not already set
        if not grounded.has("ph") and props.has_ph:
            if props.ph_value is not None:
                # Single value
                grounded.set(
                    "ph",
                    props.ph_value,
                    source=ValueSource.RAG_RETRIEVAL,
                    confidence=response.top_result.confidence,
                    retrieval_source=response.top_result.doc_id,
                    original_text=content,
                    transformation_applied=f"Extracted via {props.extraction_method}",
                )
            elif props.ph_min is not None and props.ph_max is not None:
                # Range - select bound based on model type
                # For pH: higher pH is closer to neutral, which is better for growth
                # So for growth models, we use upper bound (more neutral = more growth)
                # For inactivation, lower pH can be more protective, so we use
                # the model-aware selection
                value, transformation = self._select_range_bound(
                    props.ph_min,
                    props.ph_max,
                    model_type,
                    "ph",
                )
                grounded.set(
                    "ph",
                    value,
                    source=ValueSource.RAG_RETRIEVAL,
                    confidence=response.top_result.confidence * 0.9,
                    retrieval_source=response.top_result.doc_id,
                    original_text=content,
                    transformation_applied=f"{transformation} ({props.extraction_method})",
                )
        
        # Set water activity if found and not already set
        if not grounded.has("water_activity") and props.has_aw:
            if props.aw_value is not None:
                grounded.set(
                    "water_activity",
                    props.aw_value,
                    source=ValueSource.RAG_RETRIEVAL,
                    confidence=response.top_result.confidence,
                    retrieval_source=response.top_result.doc_id,
                    original_text=content,
                    transformation_applied=f"Extracted via {props.extraction_method}",
                )
            elif props.aw_min is not None and props.aw_max is not None:
                # Range - higher aw = more water = more growth/survival
                value, transformation = self._select_range_bound(
                    props.aw_min,
                    props.aw_max,
                    model_type,
                    "water_activity",
                )
                grounded.set(
                    "water_activity",
                    value,
                    source=ValueSource.RAG_RETRIEVAL,
                    confidence=response.top_result.confidence * 0.9,
                    retrieval_source=response.top_result.doc_id,
                    original_text=content,
                    transformation_applied=f"{transformation} ({props.extraction_method})",
                )
    
    async def _extract_food_properties(self, text: str) -> ExtractedFoodProperties:
        """
        Extract food properties using hybrid approach.
        
        1. Try regex extraction (fast, free)
        2. Fall back to LLM if regex fails and LLM enabled
        """
        # Try regex first
        ph = self._extract_numeric_value(text, ["ph"])
        aw = self._extract_numeric_value(text, ["water activity", "aw"])
        
        # Build result from regex
        props = ExtractedFoodProperties(
            ph_value=ph.value if ph.value and not ph.is_range else None,
            ph_min=ph.range_min,
            ph_max=ph.range_max if ph.is_range else ph.value,
            aw_value=aw.value if aw.value and not aw.is_range else None,
            aw_min=aw.range_min,
            aw_max=aw.range_max if aw.is_range else aw.value,
            extraction_method="regex",
        )
        
        # If both found with regex, return
        if props.has_ph and props.has_aw:
            return props
        
        # Fall back to LLM if enabled and regex missed something
        if self._use_llm_extraction and (not props.has_ph or not props.has_aw):
            try:
                llm_props = await self._extract_food_properties_llm(text)
                
                # Merge: prefer regex results, fill gaps with LLM
                return ExtractedFoodProperties(
                    ph_value=props.ph_value or llm_props.ph_value,
                    ph_min=props.ph_min or llm_props.ph_min,
                    ph_max=props.ph_max or llm_props.ph_max,
                    aw_value=props.aw_value or llm_props.aw_value,
                    aw_min=props.aw_min or llm_props.aw_min,
                    aw_max=props.aw_max or llm_props.aw_max,
                    extraction_method="regex+llm" if (props.has_ph or props.has_aw) else "llm",
                )
            except Exception:
                # LLM failed, return regex results
                pass
        
        return props
    
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
            keyword_pos = text_lower.find(keyword_lower)
            if keyword_pos == -1:
                continue
            
            after_keyword = text_lower[keyword_pos + len(keyword):]
            
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
            
            # Pattern 3: Single value
            single_pattern = r'(?:is|:|of)?\s*(\d+\.?\d*)'
            match = re.search(single_pattern, after_keyword[:20])
            if match:
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
        response = self._retrieval.query_pathogen_hazards(food_description)
        
        retrieval_result = RetrievalResult(
            query=f"{food_description} pathogen hazard",
            confidence_level=(
                response.results[0].confidence_level
                if response.results
                else RetrievalConfidenceLevel.FAILED
            ),
            confidence_score=(
                response.results[0].confidence
                if response.results
                else 0.0
            ),
            source_document=(
                response.results[0].source
                if response.results
                else None
            ),
            retrieved_text=(
                response.results[0].content
                if response.results
                else None
            ),
            fallback_used=not response.has_confident_result,
        )
        grounded.retrievals.append(retrieval_result)
        
        if response.has_confident_result:
            organism = ComBaseOrganism.from_text(response.top_result.content)
            if organism:
                grounded.set(
                    "organism",
                    organism,
                    source=ValueSource.RAG_RETRIEVAL,
                    confidence=response.top_result.confidence,
                    retrieval_source=response.top_result.doc_id,
                    original_text=response.top_result.content,
                )
    
    # =========================================================================
    # INTERPRETATION RULES
    # =========================================================================
    
    def _ground_temperature(
        self,
        scenario: ExtractedScenario,
        grounded: GroundedValues,
        model_type: ModelType,
    ) -> None:
        """
        Ground temperature from extraction with model-type-aware range selection.
        
        Priority:
        1. Explicit numeric value (e.g., "25°C") → USER_EXPLICIT
        2. Range with model-aware bound selection → USER_INFERRED
        3. Description interpreted via rules (e.g., "room temperature") → USER_INFERRED
        """
        temp = scenario.single_step_temperature
        
        # Priority 1: Explicit value
        if temp.value_celsius is not None:
            grounded.set(
                "temperature_celsius",
                temp.value_celsius,
                source=ValueSource.USER_EXPLICIT,
                confidence=0.90,
            )
            return
        
        # Priority 2: Range - select bound based on model type
        if temp.is_range and temp.range_min_celsius is not None and temp.range_max_celsius is not None:
            value, transformation = self._select_range_bound(
                temp.range_min_celsius,
                temp.range_max_celsius,
                model_type,
                "temperature_celsius",
            )
            grounded.set(
                "temperature_celsius",
                value,
                source=ValueSource.USER_INFERRED,
                confidence=0.80,
                transformation_applied=transformation,
            )
            return
        
        # Priority 3: Description interpretation
        if temp.description:
            rule = find_temperature_interpretation_with_fallback(temp.description)
            if rule:
                grounded.set(
                    "temperature_celsius",
                    rule.value,
                    source=ValueSource.USER_INFERRED,
                    confidence=rule.confidence,
                    original_text=temp.description,
                    transformation_applied=f"Interpreted as {rule.value}°C ({rule.notes})",
                )
                return
            else:
                grounded.mark_ungrounded(
                    "temperature_celsius",
                    f"Could not interpret: '{temp.description}'"
                )
        else:
            grounded.mark_ungrounded("temperature_celsius", "No temperature specified")
    
    def _ground_duration(
        self,
        scenario: ExtractedScenario,
        grounded: GroundedValues,
        model_type: ModelType,
    ) -> None:
        """
        Ground duration from extraction with model-type-aware range selection.
        
        Priority:
        1. Explicit numeric value (e.g., "3 hours") → USER_EXPLICIT
        2. Range with model-aware bound selection → USER_INFERRED
        3. Description interpreted via rules (e.g., "overnight") → USER_INFERRED
        """
        dur = scenario.single_step_duration
        
        # Priority 1: Explicit value
        if dur.value_minutes is not None:
            grounded.set(
                "duration_minutes",
                dur.value_minutes,
                source=ValueSource.USER_EXPLICIT,
                confidence=0.90,
            )
            return
        
        # Priority 2: Range - select bound based on model type
        if dur.range_min_minutes is not None and dur.range_max_minutes is not None:
            value, transformation = self._select_range_bound(
                dur.range_min_minutes,
                dur.range_max_minutes,
                model_type,
                "duration_minutes",
            )
            grounded.set(
                "duration_minutes",
                value,
                source=ValueSource.USER_INFERRED,
                confidence=0.80,
                transformation_applied=transformation,
            )
            return
        
        # Priority 3: Description interpretation
        if dur.description:
            rule = find_duration_interpretation(dur.description)
            if rule:
                grounded.set(
                    "duration_minutes",
                    rule.value,
                    source=ValueSource.USER_INFERRED,
                    confidence=rule.confidence,
                    original_text=dur.description,
                    transformation_applied=f"Interpreted as {rule.value} min ({rule.notes})",
                )
                return
            else:
                grounded.mark_ungrounded(
                    "duration_minutes",
                    f"Could not interpret: '{dur.description}'"
                )
        else:
            grounded.mark_ungrounded("duration_minutes", "No duration specified")


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
