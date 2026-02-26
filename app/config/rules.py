"""
Interpretation Rules

Rules for resolving AMBIGUOUS LINGUISTIC TERMS to numeric values.
These are NOT scientific facts — they are interpretation conventions.

What belongs here:
- Temperature descriptions → numeric values ("room temperature" → 25°C)
- Duration descriptions → numeric values ("overnight" → 8 hours)
- Bias correction policies (add safety margins)

What does NOT belong here:
- Food pH/aw values (→ RAG)
- Pathogen-food associations (→ RAG)
- Any scientific fact that should be citable (→ RAG)
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class InterpretationRule:
    """Rule for interpreting ambiguous linguistic terms."""
    pattern: str
    value: Any
    confidence: float
    conservative: bool = False
    notes: str = ""


# =============================================================================
# TEMPERATURE INTERPRETATION
# Converts vague temperature descriptions to numeric values (°C)
# These are linguistic conventions, not scientific facts
# =============================================================================

TEMPERATURE_INTERPRETATIONS: list[InterpretationRule] = [
    # Room/ambient
    InterpretationRule(
        pattern="room temperature",
        value=25.0,
        confidence=0.80,
        conservative=True,
        notes="Standard assumption; actual range 20-25°C",
    ),
    InterpretationRule(
        pattern="ambient",
        value=25.0,
        confidence=0.75,
        conservative=True,
        notes="Ambient varies by location; conservative estimate",
    ),
    InterpretationRule(
        pattern="counter",
        value=25.0,
        confidence=0.80,
        conservative=True,
        notes="Left on counter implies room temperature",
    ),
    # Warm conditions
    InterpretationRule(
        pattern="warm",
        value=30.0,
        confidence=0.70,
        conservative=True,
        notes="Warm but not hot; 25-35°C range",
    ),
    InterpretationRule(
        pattern="hot",
        value=40.0,
        confidence=0.65,
        conservative=True,
        notes="Hot conditions; 35-45°C range",
    ),
    InterpretationRule(
        pattern="summer",
        value=30.0,
        confidence=0.65,
        conservative=True,
        notes="Summer temperatures vary; using warm estimate",
    ),
    # Cold storage
    InterpretationRule(
        pattern="refrigerated",
        value=4.0,
        confidence=0.90,
        conservative=False,
        notes="Standard refrigeration temperature",
    ),
    InterpretationRule(
        pattern="refrigerator",
        value=4.0,
        confidence=0.90,
        conservative=False,
        notes="Standard refrigeration temperature",
    ),
    InterpretationRule(
        pattern="fridge",
        value=4.0,
        confidence=0.90,
        conservative=False,
        notes="Standard refrigeration temperature",
    ),
    InterpretationRule(
        pattern="chilled",
        value=4.0,
        confidence=0.85,
        conservative=False,
        notes="Chilled typically means refrigerated",
    ),
    InterpretationRule(
        pattern="cold",
        value=10.0,
        confidence=0.70,
        conservative=True,
        notes="Cold but not necessarily refrigerated; conservative estimate",
    ),
    InterpretationRule(
        pattern="cool",
        value=15.0,
        confidence=0.65,
        conservative=True,
        notes="Cool is warmer than cold; conservative estimate",
    ),
    # Frozen
    InterpretationRule(
        pattern="freezer",
        value=-18.0,
        confidence=0.90,
        conservative=False,
        notes="Standard freezer temperature",
    ),
    InterpretationRule(
        pattern="frozen",
        value=-18.0,
        confidence=0.90,
        conservative=False,
        notes="Standard freezer temperature",
    ),
]


# =============================================================================
# DURATION INTERPRETATION
# Converts vague duration descriptions to numeric values (minutes)
# These are linguistic conventions, not scientific facts
# =============================================================================

DURATION_INTERPRETATIONS: list[InterpretationRule] = [
    # Very short
    InterpretationRule(
        pattern="briefly",
        value=10.0,
        confidence=0.60,
        conservative=False,
        notes="Very short duration; typically <15 minutes",
    ),
    InterpretationRule(
        pattern="a few minutes",
        value=15.0,
        confidence=0.70,
        conservative=True,
        notes="Few minutes; using upper estimate",
    ),
    InterpretationRule(
        pattern="a moment",
        value=5.0,
        confidence=0.60,
        conservative=False,
        notes="Very brief moment",
    ),
    InterpretationRule(
        pattern="quick",
        value=10.0,
        confidence=0.60,
        conservative=False,
        notes="Quick implies brief",
    ),
    # Medium durations
    InterpretationRule(
        pattern="a while",
        value=60.0,
        confidence=0.50,
        conservative=True,
        notes="Vague duration; could be 30-90 minutes",
    ),
    InterpretationRule(
        pattern="some time",
        value=60.0,
        confidence=0.50,
        conservative=True,
        notes="Vague duration; using conservative estimate",
    ),
    InterpretationRule(
        pattern="a bit",
        value=30.0,
        confidence=0.55,
        conservative=True,
        notes="A bit is vague; 15-45 minutes",
    ),
    # Hours
    InterpretationRule(
        pattern="an hour",
        value=60.0,
        confidence=0.85,
        conservative=False,
        notes="Explicit hour mention",
    ),
    InterpretationRule(
        pattern="a couple hours",
        value=120.0,
        confidence=0.75,
        conservative=False,
        notes="Couple typically means 2",
    ),
    InterpretationRule(
        pattern="a couple of hours",
        value=120.0,
        confidence=0.75,
        conservative=False,
        notes="Couple typically means 2",
    ),
    InterpretationRule(
        pattern="a few hours",
        value=180.0,
        confidence=0.65,
        conservative=True,
        notes="Few hours typically means 2-4; using 3",
    ),
    InterpretationRule(
        pattern="several hours",
        value=300.0,
        confidence=0.60,
        conservative=True,
        notes="Several hours typically means 4-6; using 5",
    ),
    InterpretationRule(
        pattern="many hours",
        value=360.0,
        confidence=0.55,
        conservative=True,
        notes="Many hours; using 6 as conservative",
    ),
    # Half day
    InterpretationRule(
        pattern="half a day",
        value=360.0,
        confidence=0.75,
        conservative=False,
        notes="Half day = ~6 hours",
    ),
    InterpretationRule(
        pattern="half the day",
        value=360.0,
        confidence=0.75,
        conservative=False,
        notes="Half day = ~6 hours",
    ),
    # Long durations
    InterpretationRule(
        pattern="overnight",
        value=480.0,
        confidence=0.70,
        conservative=True,
        notes="Overnight typically 6-10 hours; using 8",
    ),
    InterpretationRule(
        pattern="all night",
        value=480.0,
        confidence=0.70,
        conservative=True,
        notes="All night similar to overnight; 8 hours",
    ),
    InterpretationRule(
        pattern="all day",
        value=720.0,
        confidence=0.65,
        conservative=True,
        notes="All day could be 8-14 hours; using 12",
    ),
    InterpretationRule(
        pattern="the whole day",
        value=720.0,
        confidence=0.65,
        conservative=True,
        notes="Whole day = all day; 12 hours",
    ),
    InterpretationRule(
        pattern="a long time",
        value=360.0,
        confidence=0.45,
        conservative=True,
        notes="Very vague; using 6 hours as conservative",
    ),
    InterpretationRule(
        pattern="ages",
        value=360.0,
        confidence=0.40,
        conservative=True,
        notes="Colloquial for long time; very uncertain",
    ),
    InterpretationRule(
        pattern="forever",
        value=480.0,
        confidence=0.35,
        conservative=True,
        notes="Hyperbole; using 8 hours, very uncertain",
    ),
]


# =============================================================================
# BIAS CORRECTION RULES
# Safety margins and conservative adjustments
# =============================================================================

@dataclass
class BiasCorrectionRule:
    """Rule for applying safety bias to values."""
    name: str
    condition: str
    correction_type: str  # "multiply", "use_upper", "use_lower", "add"
    factor: float | None = None
    notes: str = ""


BIAS_CORRECTIONS: list[BiasCorrectionRule] = [
    BiasCorrectionRule(
        name="inferred_duration_margin",
        condition="duration_from_interpretation",
        correction_type="multiply",
        factor=1.2,
        notes="Add 20% safety margin when duration is inferred from vague description",
    ),
    BiasCorrectionRule(
        name="temperature_range_upper",
        condition="temperature_is_range",
        correction_type="use_upper",
        notes="When temperature range given, use upper bound (more growth = conservative)",
    ),
    BiasCorrectionRule(
        name="duration_range_upper",
        condition="duration_is_range",
        correction_type="use_upper",
        notes="When duration range given, use upper bound (longer = conservative)",
    ),
    BiasCorrectionRule(
        name="low_confidence_temperature_bump",
        condition="temperature_confidence_below_0.6",
        correction_type="add",
        factor=5.0,
        notes="Add 5°C when temperature confidence is very low",
    ),
]


# =============================================================================
# LOOKUP UTILITIES
# =============================================================================

def find_temperature_interpretation(description: str) -> InterpretationRule | None:
    """
    Find matching temperature interpretation rule.
    
    Args:
        description: Temperature description from user (e.g., "room temperature")
        
    Returns:
        Matching rule or None
    """
    if not description:
        return None
    
    desc_lower = description.lower()
    
    # Try exact-ish matches first (longer patterns)
    sorted_rules = sorted(
        TEMPERATURE_INTERPRETATIONS,
        key=lambda r: len(r.pattern),
        reverse=True,
    )
    
    for rule in sorted_rules:
        if rule.pattern in desc_lower:
            return rule
    
    return None


def find_duration_interpretation(description: str) -> InterpretationRule | None:
    """
    Find matching duration interpretation rule.
    
    Args:
        description: Duration description from user (e.g., "overnight")
        
    Returns:
        Matching rule or None
    """
    if not description:
        return None
    
    desc_lower = description.lower()
    
    # Try exact-ish matches first (longer patterns)
    sorted_rules = sorted(
        DURATION_INTERPRETATIONS,
        key=lambda r: len(r.pattern),
        reverse=True,
    )
    
    for rule in sorted_rules:
        if rule.pattern in desc_lower:
            return rule
    
    return None


def get_bias_correction(name: str) -> BiasCorrectionRule | None:
    """Get a specific bias correction rule by name."""
    for rule in BIAS_CORRECTIONS:
        if rule.name == name:
            return rule
    return None