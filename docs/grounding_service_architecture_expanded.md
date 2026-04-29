# Grounding Service: Architecture and Design

> ## ⚠️ HISTORICAL DOCUMENT — DO NOT USE AS REFERENCE
>
> **Status:** Out of date as of 2026-04-28.
>
> This document describes a pre-Phase-9.2 state of the architecture. Significant aspects no longer match the codebase. See the historical notice in `grounding_service_documentation.md` for the full list of divergences. The most material:
>
> - Range-bound selection moved from the GroundingService to the StandardizationService in Phase 9.2.
> - The bias-correction layer was removed in Phase 9.3.
> - Per-source confidence numbers were removed in Phase 9.3.
>
> **For the current architecture, see:**
> - `ptm_context.md` (v1.2 or later)
> - The planned `specifications.md` (to be reverse-engineered from the codebase)
>
> This document is retained for historical reference only.

---

This document describes the architecture, design decisions, and technical implementation of the Grounding Service for the Predictive Microbiology Translation Module.

---

## Table of Contents

1. [Overview](#overview)
2. [System Context](#system-context)
3. [Module Structure](#module-structure)
4. [Value Resolution Hierarchy](#value-resolution-hierarchy)
5. [Knowledge Source Classification](#knowledge-source-classification)
6. [Confidence System](#confidence-system)
7. [Interpretation Rules Engine](#interpretation-rules-engine)
8. [Embedding Similarity Fallback](#embedding-similarity-fallback)
9. [RAG Integration](#rag-integration)
10. [Pathogen Resolution](#pathogen-resolution)
11. [Provenance Tracking](#provenance-tracking)
12. [Complete Grounding Workflow](#complete-grounding-workflow)
13. [Design Decisions and Rationale](#design-decisions-and-rationale)
14. [Extending the System](#extending-the-system)
15. [Troubleshooting](#troubleshooting)
16. [Future Enhancements](#future-enhancements)

---

## Overview

The Grounding Service is responsible for resolving extracted values from natural language queries into validated, standardized inputs for predictive microbiology models. It bridges the gap between what users say and what mathematical models require.

### Core Responsibilities

1. **Value Resolution**: Convert vague descriptions ("room temperature", "overnight") into precise numeric values
2. **Knowledge Retrieval**: Fetch food-specific properties (pH, water activity) from the RAG knowledge base
3. **Pathogen Identification**: Determine relevant pathogens based on food type and user mentions
4. **Confidence Assessment**: Quantify certainty for each resolved value
5. **Provenance Tracking**: Record the source and transformation history of every value

### Key Principles

| Principle | Description |
|-----------|-------------|
| **Conservative by Default** | When uncertain, choose values that predict more bacterial growth |
| **User Priority** | User-provided values are never overwritten by system inferences |
| **Full Transparency** | Every value carries its source, confidence, and transformation history |
| **Graceful Degradation** | System continues with warnings rather than failing on missing data |
| **Separation of Concerns** | Scientific facts (RAG) vs. linguistic conventions (Rules) are handled differently |

---

## System Context

### Position in the Pipeline

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           USER QUERY                                    │
│  "I left raw chicken on the counter overnight, is it still safe?"       │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      SEMANTIC PARSER (LLM)                              │
│  Extracts: food="raw chicken", location="counter", duration="overnight" │
│  Output: ExtractedScenario                                              │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    ★ GROUNDING SERVICE ★                                │
│  Resolves: temperature=25°C, duration=480min, pH=6.0, aw=0.99           │
│  Retrieves: pathogen=Salmonella (from RAG)                              │
│  Output: GroundedValues with provenance                                 │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    STANDARDIZATION SERVICE                              │
│  Applies defaults for any remaining ungrounded fields                   │
│  Validates all values are within acceptable ranges                      │
│  Output: StandardizedInput                                              │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                       MODEL EXECUTION                                   │
│  Runs predictive microbiology model (ComBase, etc.)                     │
│  Output: Growth prediction, safety assessment                           │
└─────────────────────────────────────────────────────────────────────────┘
```

### Input/Output Contracts

**Input: ExtractedScenario**
```python
ExtractedScenario(
    food_description="raw chicken",
    food_state="raw",
    pathogen_mentioned=None,  # User didn't specify
    is_multi_step=False,
    single_step_temperature=ExtractedTemperature(
        value_celsius=None,
        description="on the counter",  # Will be interpreted as 25°C
    ),
    single_step_duration=ExtractedDuration(
        value_minutes=None,
        description="overnight",  # Will be interpreted as 480 min
        is_ambiguous=True,
    ),
    environmental_conditions=ExtractedEnvironmentalConditions(
        ph_value=None,  # Not mentioned by user
        water_activity=None,
    ),
    is_storage_scenario=True,
    implied_model_type=ModelType.GROWTH,
)
```

**Output: GroundedValues**
```python
GroundedValues(
    values={
        "temperature_celsius": 25.0,
        "duration_minutes": 480.0,
        "ph": 6.0,
        "water_activity": 0.99,
        "organism": ComBaseOrganism.SALMONELLA,
    },
    provenance={
        "temperature_celsius": ValueProvenance(source=USER_INFERRED, confidence=0.80, ...),
        "duration_minutes": ValueProvenance(source=USER_INFERRED, confidence=0.70, ...),
        "ph": ValueProvenance(source=RAG_RETRIEVAL, confidence=0.85, ...),
        "water_activity": ValueProvenance(source=RAG_RETRIEVAL, confidence=0.85, ...),
        "organism": ValueProvenance(source=RAG_RETRIEVAL, confidence=0.75, ...),
    },
    warnings=["Duration 'overnight' interpreted as 8 hours (480 minutes)"],
    ungrounded_fields=[],
)
```

---

## Module Structure

```
app/
├── services/
│   ├── extraction/
│   │   └── semantic_parser.py       # LLM-based extraction (Instructor)
│   │
│   ├── grounding/
│   │   ├── __init__.py              # Exports GroundingService, GroundedValues
│   │   └── grounding_service.py     # Main service + GroundedValues class
│   │
│   ├── standardization/
│   │   └── standardization_service.py  # Defaults, clamping, bias correction
│   │
│   └── llm/
│       └── client.py                # LLM client wrapper
│
├── config/
│   ├── rules.py                     # Interpretation rules and constants
│   └── settings.py                  # Default values, thresholds
│
├── models/
│   ├── extraction.py                # ExtractedScenario, ExtractedEnvironmentalConditions
│   ├── metadata.py                  # ValueProvenance, ValueSource, RetrievalResult
│   ├── enums.py                     # ComBaseOrganism, Factor4Type, BiasType, etc.
│   └── execution/                   # Model execution payloads
│       ├── base.py                  # TimeTemperatureStep, TimeTemperatureProfile
│       └── combase.py               # ComBaseParameters, ComBaseExecutionPayload
│
└── rag/
    ├── retrieval.py                 # RetrievalService
    └── vector_store.py              # VectorStore (ChromaDB)
```

### Key Classes

| Class | Location | Responsibility |
|-------|----------|----------------|
| `SemanticParser` | `services/extraction/semantic_parser.py` | LLM extraction of scenarios from text |
| `GroundingService` | `services/grounding/grounding_service.py` | Main orchestrator, coordinates all resolution |
| `GroundedValues` | `services/grounding/grounding_service.py` | Container for resolved values + provenance |
| `StandardizationService` | `services/standardization/standardization_service.py` | Applies defaults, clamping, bias correction |
| `ValueProvenance` | `models/metadata.py` | Tracks source, confidence, transformations |
| `ValueSource` | `models/metadata.py` | Enum: USER_EXPLICIT, USER_INFERRED, RAG_RETRIEVAL, CONSERVATIVE_DEFAULT, etc. |
| `InterpretationRule` | `config/rules.py` | Dataclass for linguistic interpretation rules |
| `ComBaseOrganism` | `models/enums.py` | Enum of supported pathogens |

### Service Dependencies

```
SemanticParser (extraction)
    └── LLMClient (Instructor-based extraction)

GroundingService
    ├── RetrievalService (app/rag/retrieval.py)
    │   └── VectorStore (app/rag/vector_store.py)
    ├── LLMClient (fallback extraction)
    └── Rules (app/config/rules.py)
        ├── find_temperature_interpretation_with_fallback()
        └── find_duration_interpretation()

StandardizationService
    ├── GroundedValues (from grounding)
    ├── ComBaseModelRegistry (model constraints)
    └── Settings (default values)
```

### Pipeline Flow

```
User Input
    │
    ▼
SemanticParser.extract_scenario()
    │ Returns: ExtractedScenario
    ▼
GroundingService.ground_scenario()
    │ Returns: GroundedValues
    ▼
StandardizationService.standardize()
    │ Returns: StandardizationResult (contains ComBaseExecutionPayload)
    ▼
Model Execution
```

---

## Value Resolution Hierarchy

The grounding service follows a strict priority hierarchy when resolving values:

| Priority | Source | Description | Confidence Range | Override Behavior |
|----------|--------|-------------|------------------|-------------------|
| 1 (Highest) | User Explicit | Values directly stated by user | 0.90 | Never overridden |
| 2 | User Inferred | Values interpreted from descriptions | 0.50 - 0.85 | Only by user explicit |
| 3 | RAG Retrieval | Values from scientific knowledge base | 0.40 - 0.95 | Only by user values |
| 4 (Lowest) | Conservative Defaults | Safety-first fallback values | N/A | Only when ungrounded |

### Why This Hierarchy?

**User Explicit at Top:**
- User may have measured the actual value
- User has context we don't (actual thermometer reading)
- Respecting user input builds trust
- If user is wrong, that's their responsibility

**User Inferred Above RAG:**
- "Left in the car" tells us about the specific situation
- RAG only knows generic food properties
- User's description carries situational context

**RAG Above Defaults:**
- RAG provides food-specific scientific data
- Defaults are generic safety fallbacks
- "Chicken pH 6.0" is better than "default pH 6.5"

**Design Decision:** Higher priority sources are **never** overwritten by lower priority sources. If a user provides an explicit pH value, RAG retrieval will not replace it, even if RAG has high confidence.

---

## Knowledge Source Classification

### What Belongs Where

| Knowledge Type | Source | Rationale |
|----------------|--------|-----------|
| Food pH values | RAG | Scientific fact, varies by food, should be citable |
| Food water activity | RAG | Scientific fact, varies by food, should be citable |
| Pathogen-food associations | RAG | Epidemiological data, source-dependent |
| Pathogen growth parameters | RAG | Scientific measurements, citable |
| "Room temperature" = 25°C | Rules | Linguistic convention, not a measurement |
| "Overnight" = 8 hours | Rules | Cultural interpretation, not science |
| "Refrigerated" = 4°C | Rules | Standard definition, well-established |
| Temperature bias corrections | Rules | Safety policy decisions |
| Conservative bound selection | Rules | Safety policy, not scientific data |

### Why This Separation Matters

1. **Auditability**
   - Scientific facts can be traced to published sources
   - Linguistic interpretations are documented conventions
   - Users understand why values differ in origin

2. **Updatability**
   - Scientific knowledge evolves (add new pathogens, update pH data)
   - Linguistic conventions are stable ("overnight" will always mean ~8 hours)
   - Different update cycles, different maintenance burden

3. **Transparency**
   - Users understand: "room temperature → 25°C" is an interpretation
   - Users understand: "chicken pH 6.0" is scientific data from FDA
   - Different confidence levels reflect this distinction

4. **Testability**
   - Rules can be unit tested in isolation (pure functions)
   - RAG requires integration tests with vector store
   - Separation enables targeted testing

### Edge Cases

| Scenario | Resolution |
|----------|------------|
| "Refrigerated at 2°C" | User explicit (2°C) takes priority over rule (4°C) |
| "Room temperature, about 22°C" | User explicit (22°C) takes priority |
| "Unknown exotic fruit" | RAG may fail, defaults applied with warning |
| "Left out for hours" | Rules interpret, but low confidence (0.50) |

---

## Confidence System

### Design Philosophy

Confidence values are not arbitrary—they reflect specific sources of uncertainty:

| Uncertainty Source | Impact on Confidence |
|-------------------|---------------------|
| User might misstate | -0.10 from perfect |
| LLM might misextract | -0.05 to -0.10 |
| Interpretation ambiguity | -0.10 to -0.30 |
| Range selection | -0.10 to -0.15 |
| Semantic approximation | -0.15 to -0.30 |
| Retrieval relevance | Variable (0.40 - 0.95) |

### User Explicit Values (0.90)

Values directly stated by the user in their query.

```
"The chicken was at 25°C" → temperature_celsius = 25.0, confidence = 0.90
"pH is 6.0" → ph = 6.0, confidence = 0.90
```

**Why 0.90 and not 1.0?**

| Factor | Uncertainty |
|--------|-------------|
| User might misremember | ~5% |
| User might misstate (typo, wrong unit) | ~3% |
| LLM extraction might misunderstand | ~2% |
| Total uncertainty | ~10% → confidence 0.90 |

**Design Decision:** We chose 0.90 rather than 1.0 because:
1. Overconfidence is dangerous in food safety
2. Leaves room for uncertainty propagation
3. Acknowledges extraction pipeline isn't perfect
4. 0.90 is still "HIGH" confidence level

### User Explicit Ranges (0.75 - 0.80)

When user provides a range, we select a conservative bound.

```
"Temperature was 20-25°C" → temperature_celsius = 25.0 (upper), confidence = 0.80
"pH between 5.5 and 6.0" → ph = 6.0 (upper, toward neutral), confidence = 0.75
```

**Why lower confidence?**

| Factor | Uncertainty |
|--------|-------------|
| Original value was uncertain (hence the range) | ~10% |
| We made a selection decision | ~5% |
| True value could be anywhere in range | ~5-10% |
| Total uncertainty | ~20-25% → confidence 0.75-0.80 |

**Conservative Selection Logic:**

| Parameter | Conservative Direction | Rationale |
|-----------|----------------------|-----------|
| Temperature | Higher | More bacterial growth at higher temps (up to optimum ~37°C) |
| Duration | Longer | More time for bacterial multiplication |
| pH | Higher (toward neutral) | Most pathogens grow better at pH 6-7 than pH 4-5 |
| Water Activity | Higher | More free water available for growth |

**Why Conservative?**

In food safety, false negatives (saying food is safe when it isn't) are far worse than false positives (saying food is unsafe when it's fine). Conservative selection ensures we err on the side of caution.

### User Inferred Values (0.50 - 0.85)

Values interpreted from vague descriptions using rules.

| Pattern | Value | Confidence | Rationale |
|---------|-------|------------|-----------|
| "refrigerated" | 4.0°C | 0.90 | Well-established standard |
| "room temperature" | 25.0°C | 0.80 | Standard assumption, actual range 20-25°C |
| "left out" | 25.0°C | 0.75 | Implies room temp, slightly less certain |
| "overnight" | 480 min | 0.70 | 8 hours, actual range 6-10 hours |
| "in the car" | 30.0°C | 0.65 | Variable (season, parking, etc.) |
| "a while" | 60 min | 0.50 | Very vague, could be 30-90 minutes |

**Why variable confidence?**

Different interpretations have different levels of ambiguity:
- "Refrigerated" has a standard definition (4°C)
- "A while" could mean anything from 20 minutes to 2 hours

The confidence reflects how certain we are about the linguistic mapping, not the user's memory.

### RAG Retrieval (0.40 - 0.95)

Values retrieved from the scientific knowledge base.

**Confidence Calculation:**
```
final_confidence = retrieval_similarity × extraction_factor × source_quality

Where:
- retrieval_similarity: 0.0 - 1.0 from vector cosine similarity
- extraction_factor: 1.0 for single value, 0.9 for range, 0.8 for inferred
- source_quality: 1.0 for CDC/FDA, 0.9 for peer-reviewed, 0.8 for other
```

**Confidence Levels by Retrieval Score:**

| Score Range | Level | Interpretation | Action |
|-------------|-------|----------------|--------|
| ≥ 0.85 | HIGH | Strong semantic match, high-quality source | Use directly |
| 0.70 - 0.85 | MEDIUM | Good match, may need verification | Use with note |
| 0.50 - 0.70 | LOW | Weak match, use with caution | Use + warning |
| < 0.50 | FAILED | No reliable match found | Mark ungrounded |

---

## Interpretation Rules Engine

### Purpose

Convert vague linguistic descriptions into numeric values. These are **conventions**, not scientific facts.

### Rule Structure

```python
@dataclass
class InterpretationRule:
    pattern: str           # Substring to match (case-insensitive)
    value: float           # Numeric value to assign
    confidence: float      # Confidence in this interpretation
    notes: str             # Human-readable explanation
```

### Temperature Rules

| Pattern | Value (°C) | Confidence | Notes |
|---------|------------|------------|-------|
| room temperature | 25.0 | 0.80 | Standard assumption; actual range 20-25°C |
| ambient | 25.0 | 0.80 | Synonym for room temperature |
| refrigerated | 4.0 | 0.90 | Standard refrigeration temperature |
| fridge | 4.0 | 0.90 | Colloquial for refrigerated |
| frozen | -18.0 | 0.90 | Standard freezer temperature |
| freezer | -18.0 | 0.90 | Colloquial for frozen |
| warm | 30.0 | 0.70 | Warm but not hot; 25-35°C range |
| hot | 40.0 | 0.65 | Hot conditions; 35-45°C range |
| left out | 25.0 | 0.75 | Implies room temperature |
| on the counter | 25.0 | 0.80 | Kitchen counter = room temp |
| in the car | 30.0 | 0.65 | Vehicles can get warm; variable |
| outside | 25.0 | 0.60 | Highly variable by season/location |
| unrefrigerated | 25.0 | 0.80 | Explicitly not cold = room temp |

### Duration Rules

| Pattern | Value (min) | Confidence | Notes |
|---------|-------------|------------|-------|
| overnight | 480 | 0.70 | 8 hours; actual range 6-10 hours |
| all day | 720 | 0.65 | 12 hours; could be 8-14 |
| all night | 480 | 0.70 | Same as overnight |
| a few hours | 180 | 0.65 | 3 hours; typically means 2-4 |
| several hours | 240 | 0.65 | 4 hours; typically means 3-6 |
| a couple hours | 120 | 0.70 | 2 hours; fairly standard meaning |
| an hour | 60 | 0.85 | Clear meaning |
| half hour | 30 | 0.85 | Clear meaning |
| briefly | 10 | 0.60 | Very short; 5-15 minutes |
| a while | 60 | 0.50 | Vague; could be 30-90 minutes |
| a long time | 240 | 0.50 | Vague; could be 2-6 hours |

### Rule Matching Algorithm

```python
def find_interpretation(description: str, rules: list[InterpretationRule]) -> Optional[InterpretationRule]:
    description_lower = description.lower()
    
    # Sort by pattern length (longest first)
    sorted_rules = sorted(rules, key=lambda r: len(r.pattern), reverse=True)
    
    # Find first matching rule
    for rule in sorted_rules:
        if rule.pattern in description_lower:
            return rule
    
    return None
```

**Why longest-first matching?**

| Input | Without longest-first | With longest-first |
|-------|----------------------|-------------------|
| "unrefrigerated" | Matches "refrigerated" → 4°C ❌ | Matches "unrefrigerated" → 25°C ✓ |
| "room temperature" | Matches "room" → ??? | Matches "room temperature" → 25°C ✓ |
| "not frozen" | Matches "frozen" → -18°C ❌ | No match → fallback ✓ |

Longest-first prevents partial matches from taking precedence over more specific patterns.

---

## Embedding Similarity Fallback

### Purpose

Handle temperature descriptions that don't match any rule but are semantically similar to known patterns.

### When It's Used

```
User says: "sitting on the kitchen bench"
Rule matching: No rule contains "kitchen bench"
Embedding fallback: Semantically similar to "left out on counter" → 25°C
```

### How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│  Input: "sitting on the kitchen bench"                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 1: Rule matching fails                                    │
│  No rule pattern is substring of input                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 2: Embed the input description                            │
│  "sitting on the kitchen bench" → [0.12, -0.34, 0.56, ...]     │
│  (384-dimensional vector via all-MiniLM-L6-v2)                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 3: Compare to canonical phrase embeddings                 │
│  Cosine similarity with pre-embedded phrases:                   │
│    "room temperature" → 0.42                                    │
│    "left out on counter" → 0.78  ← Best match                   │
│    "in the fridge" → 0.15                                       │
│    "warm environment" → 0.31                                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 4: Apply threshold and select                             │
│  Best match: "left out on counter" (similarity 0.78)            │
│  Threshold: 0.50 ✓                                              │
│  Category: 25.0°C                                               │
│  Confidence: 0.65 × 0.78 = 0.51                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Canonical Phrase Categories

```python
TEMPERATURE_CANONICAL_PHRASES = {
    25.0: [  # Room temperature category
        "room temperature",
        "ambient temperature",
        "left out on counter",
        "sitting at room temp",
        "unrefrigerated",
        "on the kitchen bench",
        "on the table",
        "not in the fridge",
    ],
    30.0: [  # Warm category
        "warm environment",
        "warm day",
        "in a hot car",
        "warm kitchen",
        "sunny spot",
        "near the stove",
    ],
    4.0: [  # Refrigerated category
        "refrigerated",
        "in the fridge",
        "cold storage",
        "chilled",
        "in the refrigerator",
        "kept cold",
    ],
    -18.0: [  # Frozen category
        "frozen",
        "in the freezer",
        "frozen solid",
        "deep freeze",
    ],
    40.0: [  # Hot category
        "hot environment",
        "very warm",
        "hot day outside",
        "in direct sunlight",
    ],
}
```

### Confidence Calculation

```python
EMBEDDING_MATCH_CONFIDENCE = 0.65  # Base confidence for embedding matches
EMBEDDING_SIMILARITY_THRESHOLD = 0.50  # Minimum similarity to accept

confidence = EMBEDDING_MATCH_CONFIDENCE × similarity_score
```

**Why base confidence 0.65?**

Embedding matches are semantic approximations, not exact matches:
- The phrase might have a different meaning in context
- The embedding model might miss domain-specific nuances
- We're extrapolating from similar phrases, not matching the exact phrase

0.65 reflects this additional uncertainty compared to rule matches (0.70-0.90).

**Why threshold 0.50?**

| Threshold | Trade-off |
|-----------|-----------|
| 0.30 | Too permissive, matches unrelated phrases |
| 0.50 | Balanced: catches semantic variants, rejects noise |
| 0.70 | Too strict, misses valid paraphrases |

We chose 0.50 based on empirical testing with food safety descriptions.

### Design Decision: Why Embedding Fallback?

**Problem:** Users express the same concept in countless ways:
- "on the counter" / "on the bench" / "on the table" / "left out"
- "in my car" / "in the vehicle" / "in the automobile"

**Alternative 1: Exhaustive rules**
- ❌ Impossible to enumerate all variations
- ❌ Maintenance burden grows unboundedly
- ❌ Misses creative phrasings

**Alternative 2: LLM interpretation**
- ❌ Slow (API call per interpretation)
- ❌ Expensive at scale
- ❌ Non-deterministic

**Alternative 3: Embedding similarity (chosen)**
- ✓ Handles unseen phrasings
- ✓ Fast (local embedding model)
- ✓ Deterministic
- ✓ Graceful degradation (falls back to default if no match)

---

## RAG Integration

### When RAG Is Used

RAG retrieval is triggered for:
1. **Food pH** — When user doesn't provide explicit pH
2. **Food water activity** — When user doesn't provide explicit aw
3. **Pathogen identification** — When user doesn't mention a specific pathogen

RAG is **not** used for:
- Temperature (linguistic interpretation, not food-specific)
- Duration (linguistic interpretation, not food-specific)
- Values already provided by user (priority hierarchy)

### Query Construction

```python
# For food properties
query = f"{food_description} pH water activity"
# Example: "raw chicken pH water activity"

# For pathogen identification
query = f"{food_description} pathogen hazard"
# Example: "raw chicken pathogen hazard"
```

### Value Extraction from RAG Results

```python
def extract_ph_from_text(text: str) -> Optional[tuple[float, float]]:
    """Extract pH value or range from retrieved text."""
    
    # Pattern 1: Range "pH 5.9-6.2" or "pH 5.9 to 6.2"
    range_pattern = r'pH\s*(?:range\s*)?(\d+\.?\d*)\s*[-–to]\s*(\d+\.?\d*)'
    
    # Pattern 2: Single value "pH 6.0"
    single_pattern = r'pH\s*(\d+\.?\d*)'
    
    # Try range first, then single
    ...
```

### Handling RAG Ranges

When RAG returns a range (e.g., "pH 5.9-6.2"), we apply conservative selection:

```python
ph_min, ph_max = 5.9, 6.2
# Use upper bound (more growth-permissive)
ph = ph_max  # 6.2
confidence = retrieval_confidence * 0.9  # Reduced for range selection
```

### RAG Failure Handling

| Scenario | Response |
|----------|----------|
| No results returned | Mark field ungrounded, add warning |
| Low similarity score (<0.50) | Mark field ungrounded, add warning |
| Value extraction fails | Try LLM fallback, then mark ungrounded |
| Conflicting values | Use most conservative, add warning |

---

## Pathogen Resolution

### Resolution Order

1. **User Explicit**: User mentioned specific pathogen
   ```
   "Is there Salmonella risk?" → organism = SALMONELLA, confidence = 0.90
   ```

2. **RAG Retrieval**: Retrieved from food-pathogen associations
   ```
   Food: "raw chicken" → RAG returns "Salmonella commonly found in poultry"
   → organism = SALMONELLA, confidence = retrieval_score
   ```

3. **Ungrounded**: No pathogen could be determined
   ```
   → Warning added, Standardization Service applies default
   ```

### Pathogen String Matching

The `ComBaseOrganism.from_string()` method handles variations:

| Input | Matched Organism | Method |
|-------|------------------|--------|
| "Salmonella" | SALMONELLA | Direct match |
| "salmonella enterica" | SALMONELLA | Prefix match |
| "Listeria" | LISTERIA_MONOCYTOGENES | Direct match |
| "listeria monocytogenes" | LISTERIA_MONOCYTOGENES | Full match |
| "E. coli" | ESCHERICHIA_COLI | Alias match |
| "e coli o157" | ESCHERICHIA_COLI | Alias + suffix |
| "Staph" | STAPHYLOCOCCUS_AUREUS | Common abbreviation |

### Pathogen from RAG Text

```python
def extract_pathogen_from_text(text: str) -> Optional[ComBaseOrganism]:
    """Scan text for pathogen mentions, return most relevant."""
    
    # Priority: specific species > genus > general terms
    for organism in ComBaseOrganism:
        if organism.value.lower() in text.lower():
            return organism
        for alias in organism.aliases:
            if alias.lower() in text.lower():
                return organism
    
    return None
```

### Multiple Pathogens

When RAG returns text mentioning multiple pathogens:

```
"Raw chicken may contain Salmonella, Campylobacter, and Listeria"
```

**Current behavior:** Return first/primary pathogen (Salmonella)

**Future enhancement:** Return all relevant pathogens for comprehensive analysis

---

## Provenance Tracking

Every grounded value includes full provenance:

```python
@dataclass
class ValueProvenance:
    source: ValueSource              # USER_EXPLICIT, USER_INFERRED, RAG_RETRIEVAL, CONSERVATIVE_DEFAULT
    confidence: float                # 0.0 - 1.0
    retrieval_source: Optional[str]  # Document ID if from RAG
    original_text: Optional[str]     # What we extracted from
    transformation_applied: Optional[str]  # e.g., "Range 5.9-6.2, using upper bound"
    source_id: Optional[str]         # Citation ID (e.g., "CDC-2011-T3")
```

### Value Sources

| Source | Description | Typical Confidence |
|--------|-------------|-------------------|
| USER_EXPLICIT | User directly stated the value | 0.75 - 0.90 |
| USER_INFERRED | Interpreted from user's description | 0.50 - 0.85 |
| RAG_RETRIEVAL | Retrieved from knowledge base | 0.50 - 0.95 |
| CONSERVATIVE_DEFAULT | Safety default applied by standardization | N/A (last resort) |
| CLARIFICATION_RESPONSE | Value provided in clarification dialog | 0.85 - 0.95 |
| CLAMPED_TO_RANGE | Value adjusted to model-valid range | Inherits from original |
| CALCULATED | Derived from other values | Depends on inputs |

### Provenance Examples

**User Explicit:**
```python
ValueProvenance(
    source=ValueSource.USER_EXPLICIT,
    confidence=0.90,
    original_text="The temperature was 25°C",
    transformation_applied=None,
)
```

**User Inferred:**
```python
ValueProvenance(
    source=ValueSource.USER_INFERRED,
    confidence=0.70,
    original_text="overnight",
    transformation_applied="Interpreted as 8 hours (480 minutes)",
)
```

**RAG Retrieval:**
```python
ValueProvenance(
    source=ValueSource.RAG_RETRIEVAL,
    confidence=0.85,
    retrieval_source="food_properties:chicken",
    original_text="chicken (poultry): pH range 5.9 to 6.2 [FDA-PH-2007]",
    transformation_applied="Range 5.9-6.2, using upper bound 6.2",
    source_id="FDA-PH-2007",
)
```

### Why Full Provenance?

1. **Auditability**: Can trace any value back to its source
2. **Debugging**: Understand why a particular value was chosen
3. **User transparency**: Explain decisions to users
4. **Confidence propagation**: Downstream services know reliability
5. **Regulatory compliance**: Food safety decisions are traceable

---

## Complete Grounding Workflow

```
┌─────────────────────────────────────────────────────────────────┐
│                    ExtractedScenario                            │
│  (from LLM extraction of user query)                            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 1: Initialize GroundedValues                              │
│  - Create empty values dict                                     │
│  - Create empty provenance dict                                 │
│  - Initialize warnings and ungrounded_fields lists              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 2: Ground User Explicit Environmental Conditions          │
│  - Check scenario.environmental_conditions                      │
│  - If ph_value set → grounded["ph"], source=USER_EXPLICIT       │
│  - If water_activity set → grounded["water_activity"]           │
│  - If ranges provided → use conservative bound + warning        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 3: Ground User Explicit Pathogen                          │
│  - Check scenario.pathogen_mentioned                            │
│  - If set → ComBaseOrganism.from_string()                       │
│  - Store in grounded["organism"] with USER_EXPLICIT source      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 4: RAG for Food Properties (if needed)                    │
│  - Only if pH or water_activity still ungrounded                │
│  - Query: food_description + "pH water activity"                │
│  - Extract values via regex                                     │
│  - If regex fails → try LLM extraction fallback                 │
│  - Use conservative bounds for ranges                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 5: RAG for Pathogen (if needed)                           │
│  - Only if organism still ungrounded                            │
│  - Query: food_description + "pathogen hazard"                  │
│  - Extract organism from retrieved text                         │
│  - Store with RAG_RETRIEVAL source                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 6: Ground Temperature                                     │
│  - If explicit value → use directly, USER_EXPLICIT              │
│  - If range → use upper bound, reduced confidence               │
│  - If description → find_temperature_interpretation()           │
│    - Try rule matching first                                    │
│    - Fall back to embedding similarity                          │
│  - Store with USER_INFERRED source                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 7: Ground Duration                                        │
│  - If explicit value → use directly, USER_EXPLICIT              │
│  - If range → use upper bound, reduced confidence               │
│  - If description → find_duration_interpretation()              │
│  - Store with USER_INFERRED source                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 8: Mark Ungrounded Fields                                 │
│  - Check for any fields still None                              │
│  - Add to ungrounded_fields list with reason                    │
│  - Add warning for each ungrounded field                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      GroundedValues                             │
│  - values: {ph, water_activity, organism, temperature, duration}│
│  - provenance: {field → ValueProvenance}                        │
│  - retrievals: [RetrievalResult, ...]                           │
│  - warnings: [string, ...]                                      │
│  - ungrounded_fields: [string, ...]                             │
└─────────────────────────────────────────────────────────────────┘
```

---

## Design Decisions and Rationale

### Decision 1: Strict Priority Hierarchy

**Choice:** User values always take precedence over system inferences

**Alternatives Considered:**
1. **Confidence-based override**: Higher confidence value wins regardless of source
2. **Hybrid**: User values can be overridden if system has very high confidence

**Why we chose strict hierarchy:**
- **Trust**: Users need to trust that their input is respected
- **Control**: Users with actual measurements shouldn't be second-guessed
- **Liability**: If user says 25°C and we use 30°C, we've overridden their data
- **Simplicity**: Clear, predictable behavior

**Trade-off:** We might miss cases where user made a typo and RAG has correct data. We accept this because user trust is more important.

### Decision 2: Conservative Bound Selection

**Choice:** When given a range, select the bound that predicts more bacterial growth

**Alternatives Considered:**
1. **Midpoint**: Use average of range
2. **Random**: Sample from range
3. **Ask user**: Request clarification

**Why we chose conservative:**
- **Food safety principle**: False negatives (unsafe declared safe) are much worse than false positives
- **Regulatory alignment**: Food safety standards are inherently conservative
- **User expectation**: Users asking about safety want worst-case assessment

**Trade-off:** We may be overly cautious in some cases. This is acceptable for food safety.

### Decision 3: Rules vs. RAG Separation

**Choice:** Linguistic interpretations in rules, scientific facts in RAG

**Alternatives Considered:**
1. **All in RAG**: Store "room temperature = 25°C" as knowledge
2. **All in rules**: Hardcode food pH values in rules
3. **LLM interpretation**: Let LLM interpret everything

**Why we chose separation:**
- **Different update cycles**: Science evolves, language conventions don't
- **Different confidence characteristics**: Rules are certain (it's our definition), RAG varies by retrieval
- **Testability**: Rules can be unit tested, RAG requires integration tests
- **Transparency**: Users understand the difference

**Trade-off:** Two systems to maintain. Worth it for clarity and appropriate handling.

### Decision 4: Embedding Fallback with Threshold

**Choice:** Use embedding similarity for unmatched descriptions, with 0.50 threshold

**Alternatives Considered:**
1. **No fallback**: If no rule matches, mark ungrounded
2. **Lower threshold (0.30)**: Accept weaker matches
3. **LLM fallback**: Ask LLM to interpret

**Why we chose 0.50 threshold:**
- **Balance**: Catches semantic variants without accepting noise
- **Empirical**: Tested with food safety descriptions, 0.50 gave best precision/recall
- **Graceful**: If similarity is too low, falls back to default (safe)

**Trade-off:** Some valid interpretations might be missed at 0.50. We accept this because false interpretations are worse.

### Decision 5: Confidence of 0.90 for User Explicit

**Choice:** User-provided values get 0.90 confidence, not 1.0

**Alternatives Considered:**
1. **1.0**: User values are perfectly reliable
2. **Variable**: Assess each user value individually
3. **0.80**: More conservative

**Why we chose 0.90:**
- **Acknowledges uncertainty**: Users can misremember, mistype, use wrong units
- **Extraction uncertainty**: LLM might misparse user's statement
- **Leaves headroom**: Confidence propagation needs room to compound uncertainty
- **Still HIGH level**: 0.90 is clearly "high confidence"

### Decision 6: Full Provenance Tracking

**Choice:** Every value carries complete provenance information

**Alternatives Considered:**
1. **Source only**: Just track where value came from
2. **No tracking**: Just return values
3. **Logging only**: Track in logs, not in return value

**Why we chose full provenance:**
- **Auditability**: Food safety decisions need to be traceable
- **Debugging**: Engineers need to understand value sources
- **User transparency**: Can explain decisions to users
- **Downstream use**: Standardization service needs confidence levels

**Trade-off:** More complex data structures, more memory. Worth it for transparency.

---

## Extending the System

### Adding a New Temperature Interpretation

1. **Add rule to `config/rules.py`:**
```python
TEMPERATURE_RULES = [
    # ... existing rules ...
    InterpretationRule(
        pattern="in the sun",
        value=35.0,
        confidence=0.65,
        notes="Direct sunlight, can get quite warm"
    ),
]
```

2. **Add canonical phrases for embedding fallback:**
```python
TEMPERATURE_CANONICAL_PHRASES = {
    # ... existing categories ...
    35.0: [
        "in direct sunlight",
        "in the sun",
        "sunny spot",
        "sunlit area",
    ],
}
```

3. **Add test case:**
```python
def test_temperature_in_sun():
    result = find_temperature_interpretation("food was in the sun")
    assert result.value == 35.0
    assert result.confidence == 0.65
```

### Adding a New Duration Interpretation

1. **Add rule to `config/rules.py`:**
```python
DURATION_RULES = [
    # ... existing rules ...
    InterpretationRule(
        pattern="over the weekend",
        value=2880,  # 48 hours
        confidence=0.65,
        notes="Weekend typically means ~48 hours"
    ),
]
```

2. **Add test case**

### Adding a New Value Type

To add a completely new grounded value (e.g., `initial_contamination_level`):

1. **Update `GroundedValues` model:**
```python
@dataclass
class GroundedValues:
    values: dict[str, Any]  # Add new field here
    # ...
```

2. **Add extraction logic to `ExtractedScenario`**

3. **Add grounding logic to `GroundingService.ground_scenario()`**

4. **Add interpretation rules if linguistic interpretation needed**

5. **Update standardization service with defaults**

### Adding a New Knowledge Source to RAG

See `rag_data_sources_architecture.md` for detailed instructions on adding new data sources to the RAG system.

---

## Troubleshooting

### Common Issues

**"Room temperature" interpreted as refrigerated:**
- Check rule ordering (longest-first)
- Verify "unrefrigerated" rule exists and is longer than "refrigerated"
- Check for typos in rule patterns

**RAG returning wrong food properties:**
- Check query construction (food description + "pH water activity")
- Verify food exists in knowledge base
- Check retrieval similarity scores in logs

**Low confidence for user-provided values:**
- Verify extraction correctly identified USER_EXPLICIT source
- Check if value was extracted as range instead of single value
- Review extraction logs for parsing issues

**Pathogen not being identified:**
- Check `ComBaseOrganism.from_string()` aliases
- Verify pathogen exists in RAG food-pathogen associations
- Check if user mentioned pathogen is in supported list

**Embedding fallback not triggering:**
- Verify rule matching actually failed (not partial match)
- Check embedding model is loaded correctly
- Review canonical phrases for coverage

### Debugging Tips

1. **Enable verbose logging:**
```python
import logging
logging.getLogger("app.services.grounding").setLevel(logging.DEBUG)
```

2. **Inspect provenance:**
```python
result = grounding_service.ground_scenario(scenario)
for field, prov in result.provenance.items():
    print(f"{field}: {prov.source} (confidence={prov.confidence})")
    print(f"  Original: {prov.original_text}")
    print(f"  Transform: {prov.transformation_applied}")
```

3. **Check rule matching:**
```python
from app.config.rules import find_temperature_interpretation
rule = find_temperature_interpretation("your description")
print(f"Matched: {rule}")
```

4. **Test embedding similarity:**
```python
from app.services.grounding import get_embedding_similarity
similarity = get_embedding_similarity("your description", "canonical phrase")
print(f"Similarity: {similarity}")
```

### Verification Queries

| Input | Expected Output |
|-------|-----------------|
| "25°C" | temperature=25.0, source=USER_EXPLICIT, confidence=0.90 |
| "room temperature" | temperature=25.0, source=USER_INFERRED, confidence=0.80 |
| "overnight" | duration=480, source=USER_INFERRED, confidence=0.70 |
| "raw chicken" (no pH given) | pH from RAG, source=RAG_RETRIEVAL |
| "Salmonella risk" | organism=SALMONELLA, source=USER_EXPLICIT |

---

## Future Enhancements

### Planned Improvements

1. **Clarification Loop**
   - When confidence is low (<0.60), ask user for clarification
   - "You mentioned 'a while' — could you specify how many hours?"

2. **Multi-step Scenarios**
   - Handle sequences: "refrigerated for 2 hours, then left out overnight"
   - Track time-temperature history

3. **Regional Variations**
   - "Room temperature" varies by region/climate
   - User location context for better interpretation

4. **Seasonal Adjustments**
   - "Left in the car" differs summer vs. winter
   - Date/season context for temperature interpretation

5. **Uncertainty Propagation**
   - Carry confidence through to final predictions
   - Report prediction uncertainty based on input uncertainty

6. **Multiple Pathogens**
   - Return all relevant pathogens, not just primary
   - Parallel model execution for comprehensive risk assessment

7. **Learning from Corrections**
   - If user corrects an interpretation, learn from it
   - Improve rules based on usage patterns

---

## References

### Internal Documentation

- `rag_data_sources_architecture.md` — RAG system design
- `app/config/rules.py` — Interpretation rules source
- `app/models/metadata.py` — ValueProvenance, ValueSource, RetrievalResult
- `app/models/extraction.py` — ExtractedScenario, ExtractedTemperature, etc.
- `app/models/enums.py` — ComBaseOrganism, ModelType, BiasType, etc.
- `scripts/test_semantic_parser.py` — Manual semantic parser test
- `tests/unit/test_grounding_service.py` — Unit tests

### External References

- FDA Food Code temperature requirements
- ComBase predictive microbiology models
- Sentence-BERT embedding models (all-MiniLM-L6-v2)

---

*Last updated: 2026-03-17*
