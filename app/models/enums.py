"""
Orchestration Enumerations

Controlled vocabularies for the Problem Interpretation Module's
orchestration layer (intent, clarification, session workflow).

The 4 engine-owned enums (ModelType, ComBaseOrganism, Factor4Type,
EngineType) moved to predictive/models/enums.py during the engine
relocation (see specs/lessons.md) — the predictive library owns the
types it speaks in. Import those from predictive.models.enums.

Design Principles:
- Fuzzy matching happens BEFORE enum assignment
- Unknown values trigger clarification or conservative defaults
"""

from enum import Enum

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
    ORGANISM_FOOD_UNRECOGNIZED = "organism_food_unrecognized"
    ORGANISM_CATEGORY_UNCOVERED = "organism_category_uncovered"


class OrganismGroundingFailureStage(str, Enum):
    """Where organism grounding failed closed, for structured audit traceability.

    Populated by GroundingService._category_pathogen_fallback() at each of its
    six early-return points. Purely additive — the existing mark_ungrounded()
    warning string is unchanged; this is a structured parallel record.
    """

    BRIDGE_DISABLED = "bridge_disabled"
    FOOD_UNRECOGNISED = "food_unrecognised"
    CATEGORY_HAS_NO_HAZARD_DATA = "category_has_no_hazard_data"
    INTERNAL_NO_MAPPABLE_CANDIDATE = "internal_no_mappable_candidate"


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
