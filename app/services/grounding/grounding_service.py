"""
Grounding Service

Resolves extracted values to grounded, validated values using RAG.
"""

from app.config import settings
from app.models.enums import ComBaseOrganism, RetrievalConfidenceLevel
from app.models.extraction import ExtractedScenario, ExtractedEnvironmentalConditions
from app.models.metadata import ValueProvenance, ValueSource, RetrievalResult
from app.rag.retrieval import RetrievalService, get_retrieval_service
from app.rag.vector_store import VectorStore


class GroundedValues:
    """Container for grounded values with provenance."""
    
    def __init__(self):
        self.values: dict = {}
        self.provenance: dict[str, ValueProvenance] = {}
        self.retrievals: list[RetrievalResult] = []
    
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


class GroundingService:
    """
    Service for grounding extracted values using RAG.
    
    Resolves:
    - Food descriptions → pH, water activity
    - Pathogen mentions → ComBase organism
    - Temperature descriptions → numeric values
    - Vague durations → conservative estimates
    
    Usage:
        service = GroundingService()
        grounded = await service.ground_scenario(extracted_scenario)
    """
    
    # Temperature mappings for common descriptions
    TEMPERATURE_MAPPINGS = {
        "room temperature": 25.0,
        "ambient": 25.0,
        "warm": 30.0,
        "hot": 40.0,
        "cold": 10.0,
        "refrigerated": 4.0,
        "fridge": 4.0,
        "refrigerator": 4.0,
        "freezer": -18.0,
        "frozen": -18.0,
        "chilled": 4.0,
    }
    
    # Duration mappings for vague descriptions (in minutes)
    DURATION_MAPPINGS = {
        "a few minutes": 15,
        "briefly": 10,
        "a while": 60,
        "a few hours": 180,
        "several hours": 300,
        "overnight": 480,
        "all day": 720,
        "a long time": 360,
    }
    
    def __init__(
        self,
        retrieval_service: RetrievalService | None = None,
    ):
        self._retrieval = retrieval_service or get_retrieval_service()
    
    async def ground_scenario(
        self,
        scenario: ExtractedScenario,
    ) -> GroundedValues:
        """
        Ground all values in an extracted scenario.
        
        Args:
            scenario: Extracted scenario from user input
            
        Returns:
            GroundedValues with resolved values and provenance
        """
        grounded = GroundedValues()
        
        # Ground food properties (pH, aw)
        if scenario.food_description:
            await self._ground_food_properties(
                scenario.food_description,
                grounded,
            )
        
        # Ground pathogen
        await self._ground_pathogen(scenario, grounded)
        
        # Ground temperature
        self._ground_temperature(scenario, grounded)
        
        # Ground duration
        self._ground_duration(scenario, grounded)
        
        # Ground environmental conditions
        self._ground_environmental_conditions(
            scenario.environmental_conditions,
            grounded,
        )
        
        return grounded
    
    async def _ground_food_properties(
        self,
        food_description: str,
        grounded: GroundedValues,
    ) -> None:
        """Ground food pH and water activity via RAG."""
        response = self._retrieval.query_food_properties(food_description)
        
        # Record retrieval
        grounded.retrievals.append(RetrievalResult(
            query=f"{food_description} pH water activity",
            confidence_level=response.results[0].confidence_level if response.results else RetrievalConfidenceLevel.FAILED,
            confidence_score=response.results[0].confidence if response.results else 0.0,
            source_document=response.results[0].source if response.results else None,
            retrieved_text=response.results[0].content if response.results else None,
            fallback_used=not response.has_confident_result,
        ))
        
        if response.has_confident_result:
            # Parse pH and aw from retrieved content
            content = response.top_result.content.lower()
            
            # Extract pH (simple pattern matching)
            ph_value = self._extract_numeric_value(content, ["ph"])
            if ph_value:
                grounded.set(
                    "ph",
                    ph_value,
                    source=ValueSource.RAG_RETRIEVAL,
                    confidence=response.top_result.confidence,
                    retrieval_source=response.top_result.doc_id,
                    original_text=response.top_result.content,
                )
            
            # Extract water activity
            aw_value = self._extract_numeric_value(content, ["water activity", "aw"])
            if aw_value:
                grounded.set(
                    "water_activity",
                    aw_value,
                    source=ValueSource.RAG_RETRIEVAL,
                    confidence=response.top_result.confidence,
                    retrieval_source=response.top_result.doc_id,
                    original_text=response.top_result.content,
                )
    
    async def _ground_pathogen(
        self,
        scenario: ExtractedScenario,
        grounded: GroundedValues,
    ) -> None:
        """Ground pathogen to ComBase organism."""
        # First try explicit mention
        if scenario.pathogen_mentioned:
            organism = ComBaseOrganism.from_string(scenario.pathogen_mentioned)
            if organism:
                grounded.set(
                    "organism",
                    organism,
                    source=ValueSource.USER_EXPLICIT,
                    confidence=0.95,
                    original_text=scenario.pathogen_mentioned,
                )
                return
        
        # Otherwise, try to find relevant pathogen via RAG
        if scenario.food_description:
            response = self._retrieval.query_pathogen_hazards(scenario.food_description)
            
            grounded.retrievals.append(RetrievalResult(
                query=f"{scenario.food_description} pathogen",
                confidence_level=response.results[0].confidence_level if response.results else RetrievalConfidenceLevel.FAILED,
                confidence_score=response.results[0].confidence if response.results else 0.0,
                source_document=response.results[0].source if response.results else None,
                retrieved_text=response.results[0].content if response.results else None,
                fallback_used=not response.has_confident_result,
            ))
            
            if response.has_confident_result:
                # Try to extract organism from content
                content = response.top_result.content.lower()
                organism = self._extract_organism_from_text(content)
                if organism:
                    grounded.set(
                        "organism",
                        organism,
                        source=ValueSource.RAG_RETRIEVAL,
                        confidence=response.top_result.confidence,
                        retrieval_source=response.top_result.doc_id,
                        original_text=response.top_result.content,
                    )
    
    def _ground_temperature(
        self,
        scenario: ExtractedScenario,
        grounded: GroundedValues,
    ) -> None:
        """Ground temperature from extraction."""
        temp = scenario.single_step_temperature
        
        # Explicit value takes priority
        if temp.value_celsius is not None:
            grounded.set(
                "temperature_celsius",
                temp.value_celsius,
                source=ValueSource.USER_EXPLICIT,
                confidence=0.95,
            )
            return
        
        # Try range - use conservative (higher) value
        if temp.is_range and temp.range_max_celsius is not None:
            grounded.set(
                "temperature_celsius",
                temp.range_max_celsius,
                source=ValueSource.USER_INFERRED,
                confidence=0.85,
                transformation_applied="Used upper bound of range (conservative)",
            )
            return
        
        # Try description mapping
        if temp.description:
            desc_lower = temp.description.lower()
            for key, value in self.TEMPERATURE_MAPPINGS.items():
                if key in desc_lower:
                    grounded.set(
                        "temperature_celsius",
                        value,
                        source=ValueSource.USER_INFERRED,
                        confidence=0.75,
                        original_text=temp.description,
                        transformation_applied=f"Mapped '{key}' to {value}°C",
                    )
                    return
    
    def _ground_duration(
        self,
        scenario: ExtractedScenario,
        grounded: GroundedValues,
    ) -> None:
        """Ground duration from extraction."""
        dur = scenario.single_step_duration
        
        # Explicit value takes priority
        if dur.value_minutes is not None:
            grounded.set(
                "duration_minutes",
                dur.value_minutes,
                source=ValueSource.USER_EXPLICIT,
                confidence=0.95,
            )
            return
        
        # Try range - use conservative (longer) value
        if dur.range_max_minutes is not None:
            grounded.set(
                "duration_minutes",
                dur.range_max_minutes,
                source=ValueSource.USER_INFERRED,
                confidence=0.85,
                transformation_applied="Used upper bound of range (conservative)",
            )
            return
        
        # Try description mapping
        if dur.description:
            desc_lower = dur.description.lower()
            for key, value in self.DURATION_MAPPINGS.items():
                if key in desc_lower:
                    grounded.set(
                        "duration_minutes",
                        float(value),
                        source=ValueSource.USER_INFERRED,
                        confidence=0.65,
                        original_text=dur.description,
                        transformation_applied=f"Mapped '{key}' to {value} minutes",
                    )
                    return
    
    def _ground_environmental_conditions(
        self,
        conditions: ExtractedEnvironmentalConditions,
        grounded: GroundedValues,
    ) -> None:
        """Ground explicitly provided environmental conditions."""
        if conditions.ph_value is not None:
            grounded.set(
                "ph",
                conditions.ph_value,
                source=ValueSource.USER_EXPLICIT,
                confidence=0.95,
            )
        
        if conditions.water_activity is not None:
            grounded.set(
                "water_activity",
                conditions.water_activity,
                source=ValueSource.USER_EXPLICIT,
                confidence=0.95,
            )
        
        if conditions.co2_percent is not None:
            grounded.set(
                "co2_percent",
                conditions.co2_percent,
                source=ValueSource.USER_EXPLICIT,
                confidence=0.95,
            )
        
        if conditions.nitrite_ppm is not None:
            grounded.set(
                "nitrite_ppm",
                conditions.nitrite_ppm,
                source=ValueSource.USER_EXPLICIT,
                confidence=0.95,
            )
        
        if conditions.lactic_acid_ppm is not None:
            grounded.set(
                "lactic_acid_ppm",
                conditions.lactic_acid_ppm,
                source=ValueSource.USER_EXPLICIT,
                confidence=0.95,
            )
        
        if conditions.acetic_acid_ppm is not None:
            grounded.set(
                "acetic_acid_ppm",
                conditions.acetic_acid_ppm,
                source=ValueSource.USER_EXPLICIT,
                confidence=0.95,
            )
    
    def _extract_numeric_value(
        self,
        text: str,
        keywords: list[str],
    ) -> float | None:
        """Extract a numeric value near a keyword."""
        import re
        
        for keyword in keywords:
            # Pattern: keyword followed by numbers (with optional range)
            pattern = rf"{keyword}[:\s]+(\d+\.?\d*)"
            match = re.search(pattern, text)
            if match:
                return float(match.group(1))
            
            # Pattern: numbers followed by keyword
            pattern = rf"(\d+\.?\d*)\s*{keyword}"
            match = re.search(pattern, text)
            if match:
                return float(match.group(1))
        
        return None
    
    def _extract_organism_from_text(self, text: str) -> ComBaseOrganism | None:
        """Extract ComBase organism from text."""
        # Try each organism
        organism_keywords = {
            ComBaseOrganism.SALMONELLA: ["salmonella"],
            ComBaseOrganism.LISTERIA_MONOCYTOGENES: ["listeria"],
            ComBaseOrganism.ESCHERICHIA_COLI: ["e. coli", "e.coli", "escherichia"],
            ComBaseOrganism.STAPHYLOCOCCUS_AUREUS: ["staphylococcus", "staph"],
            ComBaseOrganism.BACILLUS_CEREUS: ["bacillus cereus", "b. cereus"],
            ComBaseOrganism.CLOSTRIDIUM_PERFRINGENS: ["clostridium perfringens", "c. perfringens"],
            ComBaseOrganism.CLOSTRIDIUM_BOTULINUM_PROT: ["clostridium botulinum", "botulinum"],
            ComBaseOrganism.CAMPYLOBACTER: ["campylobacter"],
            ComBaseOrganism.YERSINIA_ENTEROCOLITICA: ["yersinia"],
            ComBaseOrganism.VIBRIO_PARAHAEMOLYTICUS: ["vibrio"],
        }
        
        for organism, keywords in organism_keywords.items():
            for keyword in keywords:
                if keyword in text:
                    return organism
        
        return None


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