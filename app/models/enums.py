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
    Organisms supported by ComBase broth models.
    
    These are the exact organism IDs from ComBase.
    Each organism may have multiple model variants (with different Factor4 options).
    """
    AEROMONAS_HYDROPHILA = "ah"
    BACILLUS_CEREUS = "bc"
    BACILLUS_LICHENIFORMIS = "bl"
    BACILLUS_SUBTILIS = "bs"
    BROCHOTHRIX_THERMOSPHACTA = "bt"
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
    def from_string(cls, value: str) -> "ComBaseOrganism | None":
        """
        Match a string to a ComBase organism.
        
        Handles common names and variations.
        Returns None if no match found.
        """
        normalized = value.lower().strip().replace(" ", "_").replace("-", "_")
        
        # Direct match on enum value
        for member in cls:
            if member.value == normalized:
                return member
        
        # Common name mappings
        mappings = {
            "listeria": cls.LISTERIA_MONOCYTOGENES,
            "listeria_monocytogenes": cls.LISTERIA_MONOCYTOGENES,
            "l_monocytogenes": cls.LISTERIA_MONOCYTOGENES,
            "l.monocytogenes": cls.LISTERIA_MONOCYTOGENES,
            "listeria_innocua": cls.LISTERIA_MONOCYTOGENES,
            "salmonella": cls.SALMONELLA,
            "salmonellae": cls.SALMONELLA,
            "salmonella_typhimurium": cls.SALMONELLA,
            "salmonella_enteritidis": cls.SALMONELLA,
            "e_coli": cls.ESCHERICHIA_COLI,
            "e.coli": cls.ESCHERICHIA_COLI,
            "ecoli": cls.ESCHERICHIA_COLI,
            "e._coli": cls.ESCHERICHIA_COLI,
            "escherichia_coli": cls.ESCHERICHIA_COLI,
            "staph": cls.STAPHYLOCOCCUS_AUREUS,
            "staphylococcus": cls.STAPHYLOCOCCUS_AUREUS,
            "staph_aureus": cls.STAPHYLOCOCCUS_AUREUS,
            "s_aureus": cls.STAPHYLOCOCCUS_AUREUS,
            "clostridium_botulinum": cls.CLOSTRIDIUM_BOTULINUM_PROT,
            "c_botulinum": cls.CLOSTRIDIUM_BOTULINUM_PROT,
            "botulinum": cls.CLOSTRIDIUM_BOTULINUM_PROT,
            "clostridium_perfringens": cls.CLOSTRIDIUM_PERFRINGENS,
            "c_perfringens": cls.CLOSTRIDIUM_PERFRINGENS,
            "perfringens": cls.CLOSTRIDIUM_PERFRINGENS,
            "bacillus_cereus": cls.BACILLUS_CEREUS,
            "b_cereus": cls.BACILLUS_CEREUS,
            "bacillus": cls.BACILLUS_CEREUS,
            "yersinia": cls.YERSINIA_ENTEROCOLITICA,
            "yersinia_enterocolitica": cls.YERSINIA_ENTEROCOLITICA,
            "y_enterocolitica": cls.YERSINIA_ENTEROCOLITICA,
            "pseudomonas": cls.PSEUDOMONAS,
            "shigella": cls.SHIGELLA_FLEXNERI,
            "aeromonas": cls.AEROMONAS_HYDROPHILA,
            "brochothrix": cls.BROCHOTHRIX_THERMOSPHACTA,
        }
        
        for key, organism in mappings.items():
            if key in normalized or normalized in key:
                return organism
        
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


class BiasType(str, Enum):
    """Types of bias corrections applied."""
    OPTIMISTIC_TEMPERATURE = "optimistic_temperature"
    OPTIMISTIC_DURATION = "optimistic_duration"
    MISSING_VALUE_IMPUTED = "missing_value_imputed"
    OUT_OF_RANGE_CLAMPED = "out_of_range_clamped"