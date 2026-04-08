# Model-Type-Aware Conservative Bias

## Summary

This document describes a critical fix to the conservative bias logic in the Problem Translation Module. The original implementation applied uniform bias corrections that were only correct for growth models, creating an anti-conservative (unsafe) bias for thermal inactivation models.

**Status:** Fixed in Phase 9.1  
**Priority:** High (Safety-Critical)  
**Files Modified:**
- `app/services/standardization/standardization_service.py`
- `app/services/grounding/grounding_service.py`
- `tests/unit/test_model_type_aware_bias.py` (new)

---

## The Problem

### Original Behavior

The original implementation applied the same "conservative" bias regardless of model type:

| Bias Correction | Original Behavior |
|-----------------|-------------------|
| Duration margin | +20% (multiply by 1.2) |
| Temperature bump | +5°C for low confidence |
| Range selection | Always use upper bound |

### Why This Was Wrong

For **growth models**, these corrections are conservative:
- More time at higher temperature → more bacterial growth → worse outcome ✓

For **thermal inactivation models**, these corrections are **anti-conservative**:
- More time at higher temperature → more pathogen kill → **better** outcome ✗
- This makes undercooked food look safer than it actually is!

### Example: The Chicken Nuggets Bug (Query C2)

> User: "Chicken nuggets reached about 68°C instead of 74°C, held for roughly 8 minutes"

**Old (buggy) behavior:**
```
Duration: 8 min × 1.2 = 9.6 min (↑)
Temperature: 68°C + 5°C = 73°C (↑) [due to low confidence]

Result: Predicts MORE Salmonella kill
System says: "Probably safe"
Reality: Undercooked chicken with surviving pathogens!
```

**New (correct) behavior:**
```
Duration: 8 min × 0.8 = 6.4 min (↓)
Temperature: 68°C - 5°C = 63°C (↓) [due to low confidence]

Result: Predicts LESS Salmonella kill
System says: "May not be safe - insufficient cooking"
Reality: Correctly flags potential risk!
```

---

## The Fix

### Core Principle

**"Conservative" always means predicting the WORSE food safety outcome.**

| Model Type | Worse Outcome | Conservative Bias Direction |
|------------|---------------|----------------------------|
| Growth | More bacterial growth | ↑ temperature, ↑ duration |
| Thermal Inactivation | Less pathogen kill | ↓ temperature, ↓ duration |
| Non-thermal Survival | More pathogen survival | ↑ temperature, ↑ duration |

### Implementation Details

#### 1. Duration Margin (StandardizationService)

```python
DURATION_MARGIN_GROWTH = 1.2       # +20%
DURATION_MARGIN_INACTIVATION = 0.8  # -20%

def _get_duration_margin(self, model_type: ModelType) -> float:
    if model_type == ModelType.THERMAL_INACTIVATION:
        return self.DURATION_MARGIN_INACTIVATION
    return self.DURATION_MARGIN_GROWTH
```

#### 2. Temperature Bump (StandardizationService)

```python
TEMPERATURE_BUMP_GROWTH = +5.0        # Warmer = more growth
TEMPERATURE_BUMP_INACTIVATION = -5.0  # Cooler = less kill

def _get_temperature_bump(self, model_type: ModelType) -> float:
    if model_type == ModelType.THERMAL_INACTIVATION:
        return self.TEMPERATURE_BUMP_INACTIVATION
    return self.TEMPERATURE_BUMP_GROWTH
```

#### 3. Range Bound Selection (GroundingService)

```python
def _select_range_bound(
    self,
    range_min: float,
    range_max: float,
    model_type: ModelType,
    field_name: str,
) -> tuple[float, str]:
    if model_type == ModelType.THERMAL_INACTIVATION:
        # Lower bound = less kill = worse
        return range_min, "LOWER bound (conservative for thermal inactivation)"
    else:
        # Upper bound = more growth = worse
        return range_max, "UPPER bound (conservative for growth)"
```

---

## Non-Thermal Survival Considerations

The `NON_THERMAL_SURVIVAL` model type uses the **same bias direction as GROWTH**.

### Rationale

Non-thermal survival models predict how pathogens survive treatments like:
- Acid exposure (low pH)
- Drying (low water activity)
- Preservatives (nitrite, organic acids)
- Modified atmosphere (CO₂)

**Conservative = predict MORE survival** because more surviving pathogens = worse food safety outcome.

### Bias Direction for Survival Models

| Parameter | Conservative Direction | Reason |
|-----------|----------------------|--------|
| Duration | Longer (+20%) | More survival time = more survivors |
| Temperature | Higher (+5°C) | Higher temp may reduce treatment efficacy |
| pH (if range) | Upper bound | Higher pH = less acidic = more survival |
| Water Activity (if range) | Upper bound | Higher aw = more water = more survival |

### When Survival Differs from Growth

In some edge cases, non-thermal survival may require different logic:

1. **Acid treatment:** Lower pH = more stressful = more kill
   - Conservative: Use HIGHER pH (less acidic)
   
2. **Drying:** Lower aw = more stressful = more kill
   - Conservative: Use HIGHER aw (more moisture)

Currently, these are handled by the same "upper bound = conservative" logic, which is correct because higher values are generally more favorable for pathogen survival.

---

## Architecture Flow

```
User Input
    │
    ▼
┌───────────────────┐
│  SemanticParser   │  Extracts raw values and determines implied_model_type
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ GroundingService  │  Resolves ranges using model-type-aware bound selection
│                   │  ├─ GROWTH: use upper bound
│                   │  └─ INACTIVATION: use lower bound
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│StandardizationSvc │  Applies bias corrections with model-type-aware direction
│                   │  ├─ Duration margin: +20% (growth) or -20% (inactivation)
│                   │  └─ Temperature bump: +5°C (growth) or -5°C (inactivation)
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│   ComBaseEngine   │  Executes model with corrected parameters
└───────────────────┘
```

---

## Testing

The fix includes comprehensive unit tests in `tests/unit/test_model_type_aware_bias.py`:

### Test Categories

1. **Duration Margin Tests**
   - `test_duration_margin_growth_adds_20_percent`
   - `test_duration_margin_inactivation_reduces_20_percent`
   - `test_duration_margin_survival_same_as_growth`
   - `test_explicit_duration_not_adjusted`

2. **Temperature Bump Tests**
   - `test_temperature_bump_growth_adds_5_degrees`
   - `test_temperature_bump_inactivation_subtracts_5_degrees`
   - `test_high_confidence_temp_not_bumped`

3. **Range Selection Tests**
   - `test_temperature_range_growth_uses_upper_bound`
   - `test_temperature_range_inactivation_uses_lower_bound`
   - `test_duration_range_growth_uses_upper_bound`
   - `test_duration_range_inactivation_uses_lower_bound`

4. **Chicken Nuggets Scenario (Critical)**
   - `test_chicken_nuggets_inactivation_conservative_bias`
   - `test_chicken_nuggets_growth_would_be_opposite`

5. **Non-Thermal Survival Tests**
   - `test_survival_duration_margin_same_as_growth`
   - `test_survival_temp_bump_same_as_growth`
   - `test_survival_range_uses_upper_bound`

### Running Tests

```bash
pytest tests/unit/test_model_type_aware_bias.py -v
```

---

## Configuration

The bias correction magnitudes are defined as class constants:

```python
class StandardizationService:
    # Duration margin multipliers
    DURATION_MARGIN_GROWTH = 1.2       # +20%
    DURATION_MARGIN_INACTIVATION = 0.8  # -20%
    
    # Temperature bump magnitudes
    TEMPERATURE_BUMP_GROWTH = 5.0       # +5°C
    TEMPERATURE_BUMP_INACTIVATION = -5.0  # -5°C
    
    # Confidence threshold for temperature bump
    LOW_CONFIDENCE_THRESHOLD = 0.5
```

These can be adjusted if needed, but the directions (positive vs negative) are fundamental to the safety logic and should not be changed.

---

## Audit Trail

Each bias correction is recorded in the `StandardizationResult.bias_corrections` list with:

- `bias_type`: The type of correction (e.g., `OPTIMISTIC_DURATION`)
- `field_name`: Which field was corrected
- `original_value`: Value before correction
- `corrected_value`: Value after correction
- `correction_reason`: Human-readable explanation including:
  - The direction of correction
  - The model type it's for
  - Why this is conservative

Example correction record:
```python
BiasCorrection(
    bias_type=BiasType.OPTIMISTIC_DURATION,
    field_name="duration_minutes",
    original_value=8.0,
    corrected_value=6.4,
    correction_reason="Inferred duration adjusted -20% for thermal_inactivation model: assuming shorter cooking (less pathogen kill).",
    correction_magnitude=-1.6,
)
```

---

## Future Considerations

### 1. Multi-Step Scenarios (Phase 11)

When implementing multi-step scenarios (e.g., "cooked then cooled"), each step may use a different model type:
- Step 1 (cooking): THERMAL_INACTIVATION → lower bounds
- Step 2 (cooling): GROWTH → upper bounds

The bias logic must be applied per-step.

### 2. Dynamic Model Type Detection

Currently, the model type is inferred from `ExtractedScenario.implied_model_type`. Future work could:
- Improve detection heuristics in SemanticParser
- Add clarification for ambiguous cases ("Are you asking about cooking or storage?")

### 3. Configurable Bias Magnitudes

The current ±20% duration margin and ±5°C temperature bump are reasonable defaults, but could be made configurable per-organism or per-use-case (e.g., higher margins for vulnerable populations).

---

## References

- Original critique: Conversation transcript (Phase 9.1)
- Query C2: "Chicken nuggets at 68°C for 8 minutes" scenario
- Files: See "Files Modified" section above
