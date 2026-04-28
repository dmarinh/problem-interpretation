"""
Interpretation Rules

Rules for resolving AMBIGUOUS LINGUISTIC TERMS to numeric values.
These are NOT scientific facts — they are interpretation conventions.

What belongs here:
- Temperature descriptions → numeric values ("room temperature" → 25°C)
- Duration descriptions → numeric values ("overnight" → 8 hours)

What does NOT belong here:
- Food pH/aw values (→ RAG)
- Pathogen-food associations (→ RAG)
- Any scientific fact that should be citable (→ RAG)

Conservative direction is committed in the rule's chosen value, not added
on top of it.  "room temperature → 25°C" is already the upper end of the
20–25°C interval; "a while → 60 min" is already the upper end of 30–90 min.
The `conservative: bool` field records that the author made this choice
deliberately, so a regulator can distinguish rule-conservatism from
user-supplied values.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


@dataclass
class InterpretationRule:
    """Rule for interpreting ambiguous linguistic terms."""
    pattern: str
    value: Any
    conservative: bool = False
    notes: str = ""
    # Embedding-fallback only — None for exact/substring rule matches.
    similarity: float | None = None
    canonical_phrase: str | None = None


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
        conservative=True,
        notes="Standard assumption; actual range 20-25°C",
    ),
    InterpretationRule(
        pattern="ambient",
        value=25.0,
        conservative=True,
        notes="Ambient varies by location; conservative estimate",
    ),
    InterpretationRule(
        pattern="counter",
        value=25.0,
        conservative=True,
        notes="Left on counter implies room temperature",
    ),
    InterpretationRule(
        pattern="bench",
        value=25.0,
        conservative=True,
        notes="On bench implies room temperature",
    ),
    InterpretationRule(
        pattern="table",
        value=25.0,
        conservative=True,
        notes="On table implies room temperature",
    ),
    InterpretationRule(
        pattern="left out",
        value=25.0,
        conservative=True,
        notes="Left out implies room temperature",
    ),
    InterpretationRule(
        pattern="sitting out",
        value=25.0,
        conservative=True,
        notes="Sitting out implies room temperature",
    ),
    InterpretationRule(
        pattern="sat out",
        value=25.0,
        conservative=True,
        notes="Sat out implies room temperature",
    ),
    InterpretationRule(
        pattern="unrefrigerated",
        value=25.0,
        conservative=True,
        notes="Unrefrigerated implies room temperature",
    ),
    InterpretationRule(
        pattern="out of the fridge",
        value=25.0,
        conservative=True,
        notes="Out of fridge implies room temperature",
    ),
    InterpretationRule(
        pattern="in my bag",
        value=25.0,
        conservative=True,
        notes="Bag at ambient temperature",
    ),
    # Warm conditions
    InterpretationRule(
        pattern="warm",
        value=30.0,
        conservative=True,
        notes="Warm but not hot; 25-35°C range",
    ),
    InterpretationRule(
        pattern="hot",
        value=40.0,
        conservative=True,
        notes="Hot conditions; 35-45°C range",
    ),
    InterpretationRule(
        pattern="summer",
        value=30.0,
        conservative=True,
        notes="Summer temperatures vary; using warm estimate",
    ),
    InterpretationRule(
        pattern="in the car",
        value=30.0,
        conservative=True,
        notes="Car interior can get warm; conservative estimate",
    ),
    InterpretationRule(
        pattern="in my car",
        value=30.0,
        conservative=True,
        notes="Car interior can get warm; conservative estimate",
    ),
    # Cold storage
    InterpretationRule(
        pattern="refrigerated",
        value=4.0,
        conservative=False,
        notes="Standard refrigeration temperature",
    ),
    InterpretationRule(
        pattern="refrigerator",
        value=4.0,
        conservative=False,
        notes="Standard refrigeration temperature",
    ),
    InterpretationRule(
        pattern="fridge",
        value=4.0,
        conservative=False,
        notes="Standard refrigeration temperature",
    ),
    InterpretationRule(
        pattern="chilled",
        value=4.0,
        conservative=False,
        notes="Chilled typically means refrigerated",
    ),
    InterpretationRule(
        pattern="cold",
        value=10.0,
        conservative=True,
        notes="Cold but not necessarily refrigerated; conservative estimate",
    ),
    InterpretationRule(
        pattern="cool",
        value=15.0,
        conservative=True,
        notes="Cool is warmer than cold; conservative estimate",
    ),
    # Frozen
    InterpretationRule(
        pattern="freezer",
        value=-18.0,
        conservative=False,
        notes="Standard freezer temperature",
    ),
    InterpretationRule(
        pattern="frozen",
        value=-18.0,
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
        conservative=False,
        notes="Very short duration; typically <15 minutes",
    ),
    InterpretationRule(
        pattern="a few minutes",
        value=15.0,
        conservative=True,
        notes="Few minutes; using upper estimate",
    ),
    InterpretationRule(
        pattern="a moment",
        value=5.0,
        conservative=False,
        notes="Very brief moment",
    ),
    InterpretationRule(
        pattern="quick",
        value=10.0,
        conservative=False,
        notes="Quick implies brief",
    ),
    # Medium durations
    InterpretationRule(
        pattern="a while",
        value=60.0,
        conservative=True,
        notes="Vague duration; could be 30-90 minutes",
    ),
    InterpretationRule(
        pattern="some time",
        value=60.0,
        conservative=True,
        notes="Vague duration; using conservative estimate",
    ),
    InterpretationRule(
        pattern="a bit",
        value=30.0,
        conservative=True,
        notes="A bit is vague; 15-45 minutes",
    ),
    # Hours
    InterpretationRule(
        pattern="an hour",
        value=60.0,
        conservative=False,
        notes="Explicit hour mention",
    ),
    InterpretationRule(
        pattern="a couple hours",
        value=120.0,
        conservative=False,
        notes="Couple typically means 2",
    ),
    InterpretationRule(
        pattern="a couple of hours",
        value=120.0,
        conservative=False,
        notes="Couple typically means 2",
    ),
    InterpretationRule(
        pattern="a few hours",
        value=180.0,
        conservative=True,
        notes="Few hours typically means 2-4; using 3",
    ),
    InterpretationRule(
        pattern="several hours",
        value=300.0,
        conservative=True,
        notes="Several hours typically means 4-6; using 5",
    ),
    InterpretationRule(
        pattern="many hours",
        value=360.0,
        conservative=True,
        notes="Many hours; using 6 as conservative",
    ),
    # Half day
    InterpretationRule(
        pattern="half a day",
        value=360.0,
        conservative=False,
        notes="Half day = ~6 hours",
    ),
    InterpretationRule(
        pattern="half the day",
        value=360.0,
        conservative=False,
        notes="Half day = ~6 hours",
    ),
    # Long durations
    InterpretationRule(
        pattern="overnight",
        value=480.0,
        conservative=True,
        notes="Overnight typically 6-10 hours; using 8",
    ),
    InterpretationRule(
        pattern="all night",
        value=480.0,
        conservative=True,
        notes="All night similar to overnight; 8 hours",
    ),
    InterpretationRule(
        pattern="all day",
        value=720.0,
        conservative=True,
        notes="All day could be 8-14 hours; using 12",
    ),
    InterpretationRule(
        pattern="the whole day",
        value=720.0,
        conservative=True,
        notes="Whole day = all day; 12 hours",
    ),
    InterpretationRule(
        pattern="a long time",
        value=360.0,
        conservative=True,
        notes="Very vague; using 6 hours as conservative",
    ),
    InterpretationRule(
        pattern="ages",
        value=360.0,
        conservative=True,
        notes="Colloquial for long time; very uncertain",
    ),
    InterpretationRule(
        pattern="forever",
        value=480.0,
        conservative=True,
        notes="Hyperbole; using 8 hours, very uncertain",
    ),
]


# =============================================================================
# LOOKUP UTILITIES
# =============================================================================

def find_temperature_interpretation(description: str) -> InterpretationRule | None:
    """Find matching temperature interpretation rule."""
    if not description:
        return None

    desc_lower = description.lower()

    # Try exact-ish matches first (longer patterns match before shorter ones)
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
    """Find matching duration interpretation rule."""
    if not description:
        return None

    desc_lower = description.lower()

    sorted_rules = sorted(
        DURATION_INTERPRETATIONS,
        key=lambda r: len(r.pattern),
        reverse=True,
    )

    for rule in sorted_rules:
        if rule.pattern in desc_lower:
            return rule

    return None


# =============================================================================
# EMBEDDING FALLBACK FOR TEMPERATURE INTERPRETATION
# =============================================================================

# Canonical phrases for each temperature category
TEMPERATURE_CANONICAL_PHRASES: dict[float, list[str]] = {
    25.0: [
        "room temperature",
        "ambient temperature",
        "left out on counter",
        "sitting at room temp",
        "unrefrigerated",
        "on the kitchen bench",
        "at ambient conditions",
        "on the table",
        "left on the side",
        "sitting on the counter",
        "kept out",
    ],
    30.0: [
        "warm environment",
        "warm day",
        "in a hot car",
        "warm kitchen",
        "warm room",
        "left in vehicle",
        "sunny spot",
        "parked car",
    ],
    35.0: [
        "hot day",
        "very warm",
        "hot environment",
        "summer heat",
        "direct sunlight",
        "in the sun",
    ],
    4.0: [
        "refrigerated",
        "in the fridge",
        "cold storage",
        "chilled",
        "refrigerator temperature",
        "kept cold",
        "in the refrigerator",
    ],
    -18.0: [
        "frozen",
        "in the freezer",
        "freezer storage",
        "deep frozen",
    ],
}

EMBEDDING_SIMILARITY_THRESHOLD = 0.5


@lru_cache(maxsize=1)
def _get_embedding_model() -> "SentenceTransformer":
    """Lazy-load embedding model for similarity matching."""
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("all-MiniLM-L6-v2")


@lru_cache(maxsize=1)
def _get_canonical_embeddings() -> dict[float, list]:
    """Pre-compute embeddings for canonical phrases."""
    model = _get_embedding_model()
    embeddings = {}
    for temp, phrases in TEMPERATURE_CANONICAL_PHRASES.items():
        embeddings[temp] = model.encode(phrases, convert_to_numpy=True)
    return embeddings


def find_temperature_by_similarity(
    description: str,
) -> tuple[float | None, float, str | None]:
    """
    Find temperature using embedding similarity as fallback.

    Returns:
        Tuple of (temperature_value, similarity_score, best_canonical_phrase)
        or (None, 0.0, None) when no confident match.
    """
    if not description or len(description) < 3:
        return None, 0.0, None

    try:
        import numpy as np

        model = _get_embedding_model()
        canonical_embeddings = _get_canonical_embeddings()

        query_embedding = model.encode([description.lower()], convert_to_numpy=True)[0]

        best_temp = None
        best_score = 0.0
        best_phrase: str | None = None

        for temp, phrase_embeddings in canonical_embeddings.items():
            phrases = TEMPERATURE_CANONICAL_PHRASES[temp]
            for phrase, phrase_emb in zip(phrases, phrase_embeddings):
                similarity = float(
                    np.dot(query_embedding, phrase_emb) /
                    (np.linalg.norm(query_embedding) * np.linalg.norm(phrase_emb))
                )
                if similarity > best_score:
                    best_score = similarity
                    best_temp = temp
                    best_phrase = phrase

        if best_score >= EMBEDDING_SIMILARITY_THRESHOLD:
            return best_temp, best_score, best_phrase

        return None, best_score, None

    except Exception:
        return None, 0.0, None


def find_temperature_interpretation_with_fallback(
    description: str,
) -> InterpretationRule | None:
    """
    Find temperature interpretation with embedding fallback.

    1. Try exact/substring rule matching (fast, deterministic)
    2. Fall back to embedding similarity (slower, semantic)

    For embedding matches, the returned rule carries similarity and
    canonical_phrase so callers can build structured audit records.
    """
    rule = find_temperature_interpretation(description)
    if rule is not None:
        return rule

    temp_value, similarity, canonical_phrase = find_temperature_by_similarity(description)

    if temp_value is not None:
        return InterpretationRule(
            pattern=description.lower(),
            value=temp_value,
            conservative=True,
            notes=f"Matched via embedding similarity (score: {similarity:.2f})",
            similarity=similarity,
            canonical_phrase=canonical_phrase,
        )

    return None
