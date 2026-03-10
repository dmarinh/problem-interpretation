# Grounding Service: Technical Documentation

## Overview

The Grounding Service is responsible for resolving extracted values from natural language queries into validated, standardized inputs for predictive microbiology models. It bridges the gap between what users say and what mathematical models require.

**Core Principle:** Transform ambiguous human language into precise scientific parameters while maintaining full transparency about the source and confidence of each value.

---

## Value Resolution Hierarchy

The grounding service follows a strict priority hierarchy when resolving values:

| Priority | Source | Description | Confidence Range |
|----------|--------|-------------|------------------|
| 1 (Highest) | User Explicit | Values directly stated by user | 0.90 |
| 2 | User Inferred | Values interpreted from user descriptions | 0.60 - 0.85 |
| 3 | RAG Retrieval | Values retrieved from scientific knowledge base | 0.50 - 0.95 (depends on retrieval score) |
| 4 (Lowest) | Conservative Defaults | Safety-first fallback values | Applied by Standardization Service |

**Key Design Decision:** Higher priority sources are never overwritten by lower priority sources. If a user provides an explicit pH value, RAG retrieval will not replace it.

---

## Knowledge Source Classification

### What Belongs Where

| Knowledge Type | Source | Rationale |
|----------------|--------|-----------|
| Food pH values | RAG | Scientific fact, varies by food, should be citable |
| Food water activity | RAG | Scientific fact, varies by food, should be citable |
| Pathogen-food associations | RAG | Scientific fact, epidemiological data |
| "Room temperature" = 25°C | Rules | Linguistic convention, not a scientific measurement |
| "Overnight" = 8 hours | Rules | Linguistic convention, cultural interpretation |
| Temperature bias corrections | Rules | Safety policy decisions |

### Why This Separation Matters

1. **Auditability:** Scientific facts can be traced to sources; linguistic interpretations are documented conventions
2. **Updatability:** Scientific knowledge evolves; linguistic conventions are stable
3. **Transparency:** Users understand why "room temperature" became 25°C (interpretation) vs. why chicken pH is 6.0 (scientific data)

---

## Confidence Levels

### User Explicit Values (0.90)

Values directly stated by the user in their query.

```
"The chicken was at 25°C" → temperature_celsius = 25.0, confidence = 0.90
"pH is 6.0" → ph = 6.0, confidence = 0.90
```

**Why 0.90 and not 1.0?**
- User might misremember or misstate values
- LLM extraction might have misunderstood
- Measurement error in original value
- Still high confidence because user stated it explicitly

### User Explicit Ranges (0.75 - 0.80)

When user provides a range, we select a conservative bound.

```
"Temperature was 20-25°C" → temperature_celsius = 25.0 (upper), confidence = 0.80
"pH between 5.5 and 6.0" → ph = 6.0 (upper, more growth), confidence = 0.75
```

**Why lower confidence?**
- Original value was uncertain (hence the range)
- We made a selection decision (upper vs. lower bound)
- Compounds uncertainty: extraction + selection

**Conservative Selection Logic:**

| Parameter | Conservative Direction | Rationale |
|-----------|----------------------|-----------|
| Temperature | Higher | More bacterial growth at higher temps (up to optimum) |
| Duration | Longer | More time for growth |
| pH | Higher (toward neutral) | Most pathogens grow better near neutral pH |
| Water Activity | Higher | More water available for growth |

### User Inferred Values (0.60 - 0.85)

Values interpreted from vague descriptions using rules.

```
"Room temperature" → 25.0°C, confidence = 0.80
"Left out overnight" → 480 minutes, confidence = 0.70
"In the car" → 30.0°C, confidence = 0.65
```

**Why variable confidence?**
- Some interpretations are more standardized ("refrigerated" = 4°C is well-established)
- Some are more ambiguous ("a while" could be 30-90 minutes)
- Confidence reflects certainty of the linguistic mapping

### RAG Retrieval (Variable)

Values retrieved from the scientific knowledge base.

```
Query: "raw chicken" → pH: 5.9-6.2, aw: 0.99
Retrieval confidence depends on:
- Semantic similarity score
- Document relevance
- Extraction success
```

**Confidence Calculation:**
```
final_confidence = retrieval_score × extraction_factor

Where:
- retrieval_score: 0.0 - 1.0 from vector similarity
- extraction_factor: 1.0 for single value, 0.9 for range
```

**Confidence Levels by Retrieval Score:**

| Score Range | Level | Interpretation |
|-------------|-------|----------------|
| ≥ 0.8 | HIGH | Strong semantic match |
| 0.6 - 0.8 | MEDIUM | Reasonable match, may need verification |
| 0.4 - 0.6 | LOW | Weak match, use with caution |
| < 0.4 | FAILED | No reliable match found |

---

## Interpretation Rules System

### Purpose

Convert vague linguistic descriptions into numeric values. These are **conventions**, not scientific facts.

### Temperature Interpretations

| Pattern | Value (°C) | Confidence | Notes |
|---------|------------|------------|-------|
| room temperature | 25.0 | 0.80 | Standard assumption; actual range 20-25°C |
| refrigerated | 4.0 | 0.90 | Standard refrigeration |
| frozen | -18.0 | 0.90 | Standard freezer |
| warm | 30.0 | 0.70 | Warm but not hot; 25-35°C range |
| hot | 40.0 | 0.65 | Hot conditions; 35-45°C range |
| left out | 25.0 | 0.75 | Implies room temperature |
| in the car | 30.0 | 0.65 | Vehicle can get warm |
| counter | 25.0 | 0.80 | Kitchen counter = room temp |

### Duration Interpretations

| Pattern | Value (min) | Confidence | Notes |
|---------|-------------|------------|-------|
| overnight | 480 | 0.70 | 8 hours; actual range 6-10 hours |
| a few hours | 180 | 0.65 | 3 hours; typically means 2-4 |
| all day | 720 | 0.65 | 12 hours; could be 8-14 |
| briefly | 10 | 0.60 | Very short duration |
| a while | 60 | 0.50 | Vague; could be 30-90 minutes |

### Rule Matching Algorithm

1. Convert description to lowercase
2. Sort rules by pattern length (longest first)
3. Find first rule where pattern is substring of description
4. Return matching rule or None

**Why longest-first?**
- Prevents partial matches: "unrefrigerated" should not match "refrigerated"
- More specific patterns take precedence: "room temperature" before "room"

---

## Embedding Similarity Fallback

### Purpose

Handle temperature descriptions that don't match any rule but are semantically similar to known patterns.

### How It Works

1. **Rule matching fails** → No substring match found
2. **Embed the description** → Convert to 384-dimensional vector
3. **Compare to canonical phrases** → Cosine similarity with pre-embedded phrases
4. **Select best match** → If similarity ≥ 0.5, use that temperature category

### Canonical Phrase Categories

```python
TEMPERATURE_CANONICAL_PHRASES = {
    25.0: [  # Room temperature
        "room temperature",
        "ambient temperature",
        "left out on counter",
        "sitting at room temp",
        "unrefrigerated",
        "on the kitchen bench",
    ],
    30.0: [  # Warm
        "warm environment",
        "warm day",
        "in a hot car",
        "warm kitchen",
    ],
    4.0: [  # Refrigerated
        "refrigerated",
        "in the fridge",
        "cold storage",
        "chilled",
    ],
    # ... etc
}
```

### Confidence for Embedding Matches

```
confidence = EMBEDDING_MATCH_CONFIDENCE × similarity_score
           = 0.65 × similarity_score
```

**Why lower base confidence (0.65)?**
- Embedding matches are semantic approximations
- Less certain than explicit rule matches
- Should be flagged for potential review

### Example

```
Input: "on the windowsill"
Rule match: None
Embedding similarity to "room temperature": 0.72
Result: 25.0°C, confidence = 0.65 × 0.72 = 0.47
Notes: "Matched via embedding similarity (score: 0.72)"
```

---

## RAG-Based Food Property Extraction

### Hybrid Extraction Approach

The system uses a two-stage extraction process:

```
RAG Retrieved Text
       │
       ▼
┌─────────────────┐
│ Regex Extraction │ ◄── Fast, free, deterministic
└────────┬────────┘
         │
    Found both?
         │
    ┌────┴────┐
    │ Yes     │ No
    ▼         ▼
  Done    ┌─────────────────┐
          │  LLM Extraction  │ ◄── Slower, costs, handles edge cases
          └────────┬────────┘
                   │
                   ▼
              Merge Results
```

### Regex Extraction Patterns

Handles common formats:

| Pattern | Example | Extracted |
|---------|---------|-----------|
| Single value | "pH 6.0" | value=6.0 |
| Colon format | "pH: 6.5" | value=6.5 |
| Range with hyphen | "pH 5.9-6.2" | min=5.9, max=6.2 |
| Range with "and" | "pH between 5.5 and 6.0" | min=5.5, max=6.0 |
| Range with "to" | "pH 5.5 to 6.0" | min=5.5, max=6.0 |

### LLM Extraction (Fallback)

When regex fails or partially succeeds:

```python
prompt = """Extract pH and water activity from the text.
Return JSON with: ph_value, ph_min, ph_max, aw_value, aw_min, aw_max
Only extract explicitly stated values. Do not infer."""
```

**When LLM is called:**
- Regex found pH but not water activity (or vice versa)
- Text format doesn't match regex patterns
- `use_llm_extraction=True` (configurable)

**Extraction Method Tracking:**

| Method | Meaning |
|--------|---------|
| regex | Both values extracted via regex |
| llm | Both values extracted via LLM |
| regex+llm | Regex found some, LLM filled gaps |

---

## Pathogen Grounding

### Resolution Order

1. **User Explicit:** User mentioned specific pathogen
   ```
   "Is there Salmonella risk?" → organism = SALMONELLA, confidence = 0.90
   ```

2. **RAG Retrieval:** Retrieved from food-pathogen associations
   ```
   Food: "raw chicken" → RAG returns "Salmonella commonly found in poultry"
   → organism = SALMONELLA, confidence = retrieval_score
   ```

3. **Ungrounded:** No pathogen could be determined
   ```
   → Warning added, Standardization Service applies default
   ```

### Pathogen String Matching

The `ComBaseOrganism.from_string()` method handles variations:

| Input | Matched Organism |
|-------|------------------|
| "Salmonella" | SALMONELLA |
| "salmonella enterica" | SALMONELLA |
| "Listeria" | LISTERIA_MONOCYTOGENES |
| "listeria monocytogenes" | LISTERIA_MONOCYTOGENES |
| "E. coli" | ESCHERICHIA_COLI |
| "e coli o157" | ESCHERICHIA_COLI |

### Pathogen from RAG Text

The `ComBaseOrganism.from_text()` method scans text for pathogen mentions:

```python
text = "Salmonella is commonly found in raw poultry and eggs."
organism = ComBaseOrganism.from_text(text)  # Returns SALMONELLA
```

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
│  Step 1: Ground User Explicit Environmental Conditions          │
│  - Check scenario.environmental_conditions                      │
│  - If ph_value set → grounded["ph"], source=USER_EXPLICIT       │
│  - If water_activity set → grounded["water_activity"]           │
│  - If ranges provided → use conservative bound + warning        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 2: Ground User Explicit Pathogen                          │
│  - Check scenario.pathogen_mentioned                            │
│  - If set → ComBaseOrganism.from_string() → grounded["organism"]│
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 3: RAG for Food Properties (if needed)                    │
│  - Only if pH or water_activity still ungrounded                │
│  - Query: food_description + "pH water activity"                │
│  - Extract values via regex (+ LLM fallback)                    │
│  - Use conservative bounds for ranges                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 4: RAG for Pathogen (if needed)                           │
│  - Only if organism still ungrounded                            │
│  - Query: food_description + "pathogen hazard"                  │
│  - Extract organism from retrieved text                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 5: Ground Temperature (Interpretation Rules)              │
│  - If explicit value → use directly                             │
│  - If range → use upper bound (conservative)                    │
│  - If description → find_temperature_interpretation_with_fallback│
│    - Try rule matching first                                    │
│    - Fall back to embedding similarity                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 6: Ground Duration (Interpretation Rules)                 │
│  - If explicit value → use directly                             │
│  - If range → use upper bound (conservative)                    │
│  - If description → find_duration_interpretation()              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      GroundedValues                             │
│  - values: {ph, water_activity, organism, temperature, duration}│
│  - provenance: {field → source, confidence, notes}              │
│  - retrievals: [RetrievalResult, ...]                           │
│  - warnings: [string, ...]                                      │
│  - ungrounded_fields: [string, ...]                             │
└─────────────────────────────────────────────────────────────────┘
```

---

## Provenance Tracking

Every grounded value includes full provenance:

```python
ValueProvenance(
    source=ValueSource.RAG_RETRIEVAL,     # Where it came from
    confidence=0.85,                       # How certain we are
    retrieval_source="doc_123",           # Which document (if RAG)
    original_text="pH between 5.9 and 6.2", # What we extracted from
    transformation_applied="Range 5.9-6.2, using upper bound",
)
```

### Value Sources

| Source | Description |
|--------|-------------|
| USER_EXPLICIT | User directly stated the value |
| USER_INFERRED | Interpreted from user's vague description |
| RAG_RETRIEVAL | Retrieved from scientific knowledge base |
| DEFAULT | Applied by standardization (safety fallback) |

---

## Error Handling and Warnings

### Ungrounded Fields

When a value cannot be determined:

```python
grounded.mark_ungrounded(
    "temperature_celsius",
    "Could not interpret temperature description: 'xyz'"
)
```

The Standardization Service will:
1. Check if field is required
2. Apply conservative default if available
3. Add warning about default application

### Warning Categories

| Warning Type | Example |
|--------------|---------|
| Range used | "pH range (5.9-6.2) provided. Using upper bound 6.2" |
| Retrieval failed | "Could not retrieve pH for 'exotic fruit' from knowledge base" |
| Interpretation uncertain | "Matched via embedding similarity (score: 0.52)" |
| Default applied | "Using default pH 6.5 (no food-specific data)" |

---

## Configuration Options

### GroundingService Constructor

```python
GroundingService(
    retrieval_service=None,      # Custom retrieval service
    llm_client=None,             # Custom LLM client
    use_llm_extraction=True,     # Enable/disable LLM fallback
)
```

### Tunable Parameters

| Parameter | Default | Location | Effect |
|-----------|---------|----------|--------|
| EMBEDDING_SIMILARITY_THRESHOLD | 0.5 | rules.py | Minimum similarity for embedding fallback |
| EMBEDDING_MATCH_CONFIDENCE | 0.65 | rules.py | Base confidence for embedding matches |
| Retrieval top_k | 3 | retrieval.py | Number of documents to consider |
| Reranker threshold | 0.5 | retrieval.py | Minimum reranker score |

---

## Testing Strategy

### Unit Tests

- Rule matching accuracy
- Regex extraction patterns
- Confidence calculations
- Provenance tracking

### Integration Tests

- Full grounding workflow
- RAG integration
- User explicit vs. RAG priority
- Warning generation

### Test Scenarios

| Scenario | Tests |
|----------|-------|
| User provides everything | No RAG calls, all USER_EXPLICIT |
| User provides nothing | Full RAG + rules, proper fallbacks |
| Partial information | Correct merging, priority respected |
| Unknown food | Warnings added, defaults applied |
| Ambiguous descriptions | Embedding fallback triggered |

---

## Future Enhancements

1. **Clarification Loop:** When confidence is low, ask user for clarification
2. **Multi-step Scenarios:** Handle sequences of time-temperature steps
3. **Regional Variations:** "Room temperature" varies by region/climate
4. **Seasonal Adjustments:** "Left in the car" differs summer vs. winter
5. **Uncertainty Propagation:** Carry confidence through to final predictions
