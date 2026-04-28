"""
Core Enumerations

Controlled vocabularies for the Problem Interpretation Module.
These enums ensure no free-text fields in the execution layer.

Design Principles:
- All engine inputs must use these enums (not free text)
- Enums map to engine-supported categories
- Fuzzy matching happens BEFORE enum assignment
- Unknown values trigger clarification or conservative defaults
"""

from enum import Enum


# =============================================================================
# MODEL TYPES
# =============================================================================

class ModelType(str, Enum):
    """
    Types of predictive models available.
    
    Maps to ComBase ModelID:
    - 1 = Growth
    - 2 = Thermal Inactivation
    - 3 = Non-thermal Survival
    """
    GROWTH = "growth"
    THERMAL_INACTIVATION = "thermal_inactivation"
    NON_THERMAL_SURVIVAL = "non_thermal_survival"
    
    @classmethod
    def from_model_id(cls, model_id: int) -> "ModelType":
        """Convert ComBase ModelID to ModelType."""
        mapping = {
            1: cls.GROWTH,
            2: cls.THERMAL_INACTIVATION,
            3: cls.NON_THERMAL_SURVIVAL,
        }
        return mapping.get(model_id, cls.GROWTH)


# =============================================================================
# COMBASE ORGANISMS
# =============================================================================

class ComBaseOrganism(str, Enum):
    """
    ComBase organism identifiers.
    
    Values match the OrganismID column in ComBase models CSV.
    """
    AEROMONAS_HYDROPHILA = "ah"
    BACILLUS_CEREUS = "bc"
    BROCHOTHRIX_THERMOSPHACTA = "bl"
    BACILLUS_SUBTILIS = "bs"
    BACILLUS_STEAROTHERMOPHILUS = "bt"
    CLOSTRIDIUM_BOTULINUM_NONPROT = "cbn"
    CLOSTRIDIUM_BOTULINUM_PROT = "cbp"
    CLOSTRIDIUM_PERFRINGENS = "cp"
    ESCHERICHIA_COLI = "ec"
    LISTERIA_MONOCYTOGENES = "lm"
    PSEUDOMONAS = "ps"
    SALMONELLA = "ss"
    SHIGELLA_FLEXNERI = "sf"
    STAPHYLOCOCCUS_AUREUS = "sa"
    YERSINIA_ENTEROCOLITICA = "ye"
    
    @classmethod
    def _get_fuzzy_map(cls) -> dict[str, "ComBaseOrganism"]:
        """Get mapping of common names/aliases to organisms."""
        return {
            # Aeromonas
            "aeromonas": cls.AEROMONAS_HYDROPHILA,
            "aeromonas hydrophila": cls.AEROMONAS_HYDROPHILA,
            "ah": cls.AEROMONAS_HYDROPHILA,
            # Bacillus cereus
            "bacillus cereus": cls.BACILLUS_CEREUS,
            "b. cereus": cls.BACILLUS_CEREUS,
            "b.cereus": cls.BACILLUS_CEREUS,
            "bc": cls.BACILLUS_CEREUS,
            # Brochothrix
            "brochothrix": cls.BROCHOTHRIX_THERMOSPHACTA,
            "brochothrix thermosphacta": cls.BROCHOTHRIX_THERMOSPHACTA,
            "bl": cls.BROCHOTHRIX_THERMOSPHACTA,
            # Bacillus subtilis
            "bacillus subtilis": cls.BACILLUS_SUBTILIS,
            "b. subtilis": cls.BACILLUS_SUBTILIS,
            "bs": cls.BACILLUS_SUBTILIS,
            # Bacillus stearothermophilus
            "bacillus stearothermophilus": cls.BACILLUS_STEAROTHERMOPHILUS,
            "b. stearothermophilus": cls.BACILLUS_STEAROTHERMOPHILUS,
            "bt": cls.BACILLUS_STEAROTHERMOPHILUS,
            # Clostridium botulinum non-proteolytic
            "clostridium botulinum non-proteolytic": cls.CLOSTRIDIUM_BOTULINUM_NONPROT,
            "c. botulinum non-proteolytic": cls.CLOSTRIDIUM_BOTULINUM_NONPROT,
            "cbn": cls.CLOSTRIDIUM_BOTULINUM_NONPROT,
            # Clostridium botulinum proteolytic
            "clostridium botulinum": cls.CLOSTRIDIUM_BOTULINUM_PROT,
            "c. botulinum": cls.CLOSTRIDIUM_BOTULINUM_PROT,
            "botulinum": cls.CLOSTRIDIUM_BOTULINUM_PROT,
            "cbp": cls.CLOSTRIDIUM_BOTULINUM_PROT,
            # Clostridium perfringens
            "clostridium perfringens": cls.CLOSTRIDIUM_PERFRINGENS,
            "c. perfringens": cls.CLOSTRIDIUM_PERFRINGENS,
            "cp": cls.CLOSTRIDIUM_PERFRINGENS,
            # E. coli
            "escherichia coli": cls.ESCHERICHIA_COLI,
            "e. coli": cls.ESCHERICHIA_COLI,
            "e.coli": cls.ESCHERICHIA_COLI,
            "e coli": cls.ESCHERICHIA_COLI,
            "ec": cls.ESCHERICHIA_COLI,
            # Listeria
            "listeria monocytogenes": cls.LISTERIA_MONOCYTOGENES,
            "listeria": cls.LISTERIA_MONOCYTOGENES,
            "l. monocytogenes": cls.LISTERIA_MONOCYTOGENES,
            "lm": cls.LISTERIA_MONOCYTOGENES,
            # Pseudomonas
            "pseudomonas": cls.PSEUDOMONAS,
            "ps": cls.PSEUDOMONAS,
            # Salmonella
            "salmonella": cls.SALMONELLA,
            "salmonella enteritidis": cls.SALMONELLA,
            "salmonella typhimurium": cls.SALMONELLA,
            "s. enteritidis": cls.SALMONELLA,
            "s. typhimurium": cls.SALMONELLA,
            "ss": cls.SALMONELLA,
            # Shigella
            "shigella": cls.SHIGELLA_FLEXNERI,
            "shigella flexneri": cls.SHIGELLA_FLEXNERI,
            "sf": cls.SHIGELLA_FLEXNERI,
            # Staphylococcus
            "staphylococcus aureus": cls.STAPHYLOCOCCUS_AUREUS,
            "staph aureus": cls.STAPHYLOCOCCUS_AUREUS,
            "s. aureus": cls.STAPHYLOCOCCUS_AUREUS,
            "staph": cls.STAPHYLOCOCCUS_AUREUS,
            "sa": cls.STAPHYLOCOCCUS_AUREUS,
            # Yersinia
            "yersinia enterocolitica": cls.YERSINIA_ENTEROCOLITICA,
            "yersinia": cls.YERSINIA_ENTEROCOLITICA,
            "y. enterocolitica": cls.YERSINIA_ENTEROCOLITICA,
            "ye": cls.YERSINIA_ENTEROCOLITICA,
        }
    
    @classmethod
    def from_string(cls, value: str) -> "ComBaseOrganism | None":
        """
        Fuzzy match organism from string.
        
        Args:
            value: Organism name or code
            
        Returns:
            Matching organism or None
        """
        if not value:
            return None
        
        value_lower = value.lower().strip()
        return cls._get_fuzzy_map().get(value_lower)
    
    @classmethod
    def from_text(cls, text: str) -> "ComBaseOrganism | None":
        """
        Find first matching organism mentioned in text.
        
        Searches for any known organism name/alias within the text.
        Excludes short codes (2 letters) to avoid false positives.
        Longer patterns are checked first to avoid partial matches.
        
        Args:
            text: Text that may contain organism names
            
        Returns:
            First matching organism or None
        """
        if not text:
            return None
        
        text_lower = text.lower()
        
        # Filter out short codes (2 chars) to avoid false matches like "safe" → "sa"
        fuzzy_map = cls._get_fuzzy_map()
        patterns = [p for p in fuzzy_map.keys() if len(p) > 2]
        
        # Sort by length (longest first)
        sorted_patterns = sorted(patterns, key=len, reverse=True)
        
        for pattern in sorted_patterns:
            if pattern in text_lower:
                return fuzzy_map[pattern]
        
        return None

# =============================================================================
# FOURTH FACTOR (OPTIONAL PARAMETER)
# =============================================================================

class Factor4Type(str, Enum):
    """
    Optional fourth factor for ComBase models.
    
    Some models accept an additional environmental parameter
    beyond temperature, pH, and water activity.
    """
    NONE = "none"
    CO2 = "co2"
    NITRITE = "nitrite"
    LACTIC_ACID = "lactic_acid"
    ACETIC_ACID = "acetic_acid"
    
    @classmethod
    def from_string(cls, value: str | None) -> "Factor4Type":
        """Convert string to Factor4Type."""
        if value is None or value.upper() == "NULL" or value == "":
            return cls.NONE
        
        normalized = value.lower().strip()
        
        mappings = {
            "co2": cls.CO2,
            "carbon_dioxide": cls.CO2,
            "nitrite": cls.NITRITE,
            "lactic_acid": cls.LACTIC_ACID,
            "lactic": cls.LACTIC_ACID,
            "acetic_acid": cls.ACETIC_ACID,
            "acetic": cls.ACETIC_ACID,
        }
        
        return mappings.get(normalized, cls.NONE)


# =============================================================================
# ENGINE TYPES
# =============================================================================

class EngineType(str, Enum):
    """Supported predictive model engines."""
    COMBASE_LOCAL = "combase_local"
    COMBASE_API = "combase_api"


# =============================================================================
# WORKFLOW & STATUS
# =============================================================================

class IntentType(str, Enum):
    """User intent classification."""
    PREDICTION_REQUEST = "prediction_request"
    INFORMATION_QUERY = "information_query"
    CLARIFICATION_RESPONSE = "clarification_response"
    OUT_OF_SCOPE = "out_of_scope"


class ClarificationReason(str, Enum):
    """Reasons for requesting user clarification."""
    AMBIGUOUS_DURATION = "ambiguous_duration"
    AMBIGUOUS_TEMPERATURE = "ambiguous_temperature"
    AMBIGUOUS_FOOD = "ambiguous_food"
    MULTIPLE_PATHOGENS = "multiple_pathogens"
    MISSING_CRITICAL_PARAMETER = "missing_critical_parameter"
    LOW_CONFIDENCE_RETRIEVAL = "low_confidence_retrieval"
    OUT_OF_RANGE_VALUE = "out_of_range_value"
    COMPOSITE_FOOD = "composite_food"
    ORGANISM_NOT_SUPPORTED = "organism_not_supported"


class SessionStatus(str, Enum):
    """Status of an interpretation session."""
    PENDING = "pending"
    EXTRACTING = "extracting"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    STANDARDIZING = "standardizing"
    READY_FOR_EXECUTION = "ready_for_execution"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


class RetrievalConfidenceLevel(str, Enum):
    """Classification of retrieval confidence."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    FAILED = "failed"


