"""
Grounding Service

Resolves extracted values to grounded, validated values.
"""

import re
from dataclasses import dataclass

from app.config.rules import (
    find_temperature_interpretation_with_fallback,
    find_duration_interpretation,
)
from app.models.enums import ComBaseOrganism, RetrievalConfidenceLevel
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
    """Container for grounded values with provenance."""
    
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
        """Ground all values in an extracted scenario."""
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
        
        # Step 5: Temperature (interpretation rules)
        self._ground_temperature(scenario, grounded)
        
        # Step 6: Duration (interpretation rules)
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
        """Ground explicitly provided environmental conditions."""
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
        
        # Other conditions
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
    ) -> None:
        """Ground food pH and water activity via RAG with hybrid extraction."""
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
            elif props.ph_max is not None:
                # Range - use upper bound (conservative for growth)
                grounded.set(
                    "ph",
                    props.ph_max,
                    source=ValueSource.RAG_RETRIEVAL,
                    confidence=response.top_result.confidence * 0.9,
                    retrieval_source=response.top_result.doc_id,
                    original_text=content,
                    transformation_applied=f"Range {props.ph_min}-{props.ph_max}, using upper bound ({props.extraction_method})",
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
            elif props.aw_max is not None:
                # Range - use upper bound (conservative for growth)
                grounded.set(
                    "water_activity",
                    props.aw_max,
                    source=ValueSource.RAG_RETRIEVAL,
                    confidence=response.top_result.confidence * 0.9,
                    retrieval_source=response.top_result.doc_id,
                    original_text=content,
                    transformation_applied=f"Range {props.aw_min}-{props.aw_max}, using upper bound ({props.extraction_method})",
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
        """Extract numeric value(s) near a keyword, handling ranges."""
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
        """Ground pathogen via RAG retrieval."""
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
    ) -> None:
        """Ground temperature from extraction."""
        temp = scenario.single_step_temperature
        
        if temp.value_celsius is not None:
            grounded.set(
                "temperature_celsius",
                temp.value_celsius,
                source=ValueSource.USER_EXPLICIT,
                confidence=0.90,
            )
            return
        
        if temp.is_range and temp.range_max_celsius is not None:
            grounded.set(
                "temperature_celsius",
                temp.range_max_celsius,
                source=ValueSource.USER_INFERRED,
                confidence=0.80,
                transformation_applied="Used upper bound of range (conservative)",
            )
            return
        
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
    ) -> None:
        """Ground duration from extraction."""
        dur = scenario.single_step_duration
        
        if dur.value_minutes is not None:
            grounded.set(
                "duration_minutes",
                dur.value_minutes,
                source=ValueSource.USER_EXPLICIT,
                confidence=0.90,
            )
            return
        
        if dur.range_max_minutes is not None:
            grounded.set(
                "duration_minutes",
                dur.range_max_minutes,
                source=ValueSource.USER_INFERRED,
                confidence=0.80,
                transformation_applied="Used upper bound of range (conservative)",
            )
            return
        
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
