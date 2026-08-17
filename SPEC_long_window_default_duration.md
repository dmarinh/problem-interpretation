# SPEC: Long-Window Default for Missing Duration

**Status:** Implemented as Phase 9.7 on 2026-05-17.  
**Author:** Claude Code (investigation + spec) / Daniel Marin (decisions)  
**Date:** 2026-05-17  

---

## 1. Problem Statement

When a user query omits duration, the PTM pipeline currently returns `success=false` with `error="Missing required values: duration"`. This was intentional — duration was treated as a required field — and was meant to gate on a future clarification module that has not yet been built.

The clarification module will not be built in the near term. Instead, for **single-step** scenarios only, a missing duration will be defaulted to `10,080 minutes` (7 days). This ensures the prediction trajectory runs long enough to reach the `_PHYSICAL_LOG_LIMIT = 15.0` cap under worst-case conditions. The future Result Interpretation Module will slice meaningful sub-windows from the long prediction; the math layer just needs to run far enough that the cap-reaching trajectory is visible.

Multi-step scenarios keep the current failure path because a missing step duration is structurally different: the user has declared `T₁ for D₁, then T₂ for D₂, …` and a missing `Dᵢ` is a malformed claim, not a "give me the worst case" question.

This change reverses §8.13's current treatment of duration (it was symmetric with organism). Duration moves from the "required field → missing_required path" category to the "defaulted field → DefaultImputed event with warning" category. Organism stays in `missing_required` because no single organism is a safe default across all food categories (see §8.13 and Decision §5.4 below).

---

## 2. Current Behavior Trace

### 2.1 Single-Step Missing Duration — Full Path

**Step 1 — Grounding (`grounding_service.py`):**

```
ground_scenario() [line 583-588]:
    if scenario.is_multi_step and scenario.time_temperature_steps:
        _ground_multi_step_profile(...)   ← multi-step branch
    else:
        _ground_temperature(...)
        _ground_duration(...)              ← single-step branch
```

`_ground_duration()` at [lines 1472–1488](app/services/grounding/grounding_service.py#L1472):

```python
def _ground_duration(self, scenario, grounded):
    value, prov = self._resolve_duration_value(scenario.single_step_duration)
    if value is not None and prov is not None:
        grounded.set_with_prov("duration_minutes", value, prov)
    else:
        desc = scenario.single_step_duration.description
        if desc:
            grounded.mark_ungrounded("duration_minutes", f"Could not interpret: '{desc}'")
        else:
            grounded.mark_ungrounded("duration_minutes", "No duration specified")
```

When `_resolve_duration_value()` returns `(None, None)` — which happens when `scenario.single_step_duration.value_minutes is None`, no explicit range, and no description matching a rule or embedding threshold — `mark_ungrounded()` is called. This **does not** set a value in `grounded.values` (the key is absent from the dict); it records the field in `grounded.ungrounded_fields`.

**Step 2 — Standardization (`standardization_service.py`):**

`_get_duration()` at [lines 356–385](app/services/standardization/standardization_service.py#L356):

```python
def _get_duration(self, grounded, result, model_type) -> float | None:
    duration = grounded.get("duration_minutes")   # returns None — key absent
    prov = grounded.provenance.get("duration_minutes")  # returns None — not in provenance

    # range resolution (lines 374-379) — skipped because prov is None

    if duration is None:                             # line 381 — fires
        result.warnings.append("Duration is required but not specified")
        return None                                  # line 383
```

The caller `standardize()` at [lines 167–170](app/services/standardization/standardization_service.py#L167):

```python
duration = self._get_duration(grounded, result, model_type)
if duration is None:                              # fires
    result.missing_required.append("duration")   # "duration" (not "duration_minutes")
    return result                                 # early return, payload=None
```

**Step 3 — Orchestrator (`orchestrator.py`):**

`_missing_key_to_audit_key()` at [lines 50–51](app/core/orchestrator.py#L50):

```python
if field_spec == "duration":
    return "duration_minutes"     # "duration" → "duration_minutes" for field_audit
```

Missing-required handling at [lines 167–184](app/core/orchestrator.py#L167):

```python
if std_result.missing_required:      # True — contains ["duration"]
    if state.metadata:
        for field in std_result.missing_required:   # "duration"
            audit_key = _missing_key_to_audit_key(field)  # → "duration_minutes"
            if audit_key not in state.metadata.provenance:
                state.metadata.add_provenance(
                    audit_key,
                    ValueProvenance(source=ValueSource.MISSING),   # null-provenance entry
                )
            state.metadata.warnings.append(
                f"Validation failed: required value missing — {field}"
            )
    state.set_error(
        f"Missing required values: {', '.join(std_result.missing_required)}"
        # exact string: "Missing required values: duration"
    )
    return TranslationResult(state)   # success=False
```

**Step 4 — Field audit (`translation.py`):**

The provenance loop at [lines 98–256](app/api/routes/translation.py#L98) processes `"duration_minutes"` in provenance (added by orchestrator). Because `source=ValueSource.MISSING`, `source_str = "missing"`. The `final_value` resolves to `grounded_values.get("duration_minutes")` which is `None`. The entry is constructed as:

```
field_audit["duration_minutes"]:
  final_value: null
  source: "missing"
  retrieval: null
  extraction: null
  standardization: null
```

### 2.2 Multi-Step Missing Duration — Full Path

**Grounding** (`grounding_service.py` [lines 1490–1534](app/services/grounding/grounding_service.py#L1490)):

`_ground_multi_step_profile()` calls `_resolve_duration_value(step.duration)` per step. When `dur_val is None`:
- Appends a warning to `grounded.warnings`: `"Step N duration: No duration specified"`
- Calls `grounded.add_step(..., duration_minutes=None)` — **stores None in the step**

This is the key behavioral difference from single-step: multi-step grounding does NOT call `mark_ungrounded()`; it allows `None` in a `GroundedStep`.

**Standardization** (`standardization_service.py` [lines 681–699](app/services/standardization/standardization_service.py#L681)):

Inside `_build_multi_step_profile()`:

```python
dur = gs.duration_minutes    # None
# ... range resolution — skipped
if dur is None:              # line 697 — fires
    result.missing_required.append(f"duration (step {gs.step_order})")
    return None              # step builder exits, payload not built
```

The caller at [lines 155–157](app/services/standardization/standardization_service.py#L155):

```python
profile = self._build_multi_step_profile(grounded, result, constraints, model_type)
if profile is None:
    return result    # missing_required already populated
```

Error message is `"Missing required values: duration (step 1)"` (or step N).

**Current behavior when ALL step durations are None:** First step returns `None` immediately; `missing_required` contains `"duration (step 1)"`. Standardization returns without checking later steps. Error names step 1 only. This is currently the behavior and the spec recommends keeping it unchanged (see §4).

### 2.3 Isolation Confirmation

The single-step and multi-step duration paths **do not share any duration-handling code**. The routing at `grounding_service.py:583-588` is a hard branch: `_ground_duration()` vs. `_ground_multi_step_profile()`. The standardization service's `_get_duration()` (called only for single-step) and `_build_multi_step_profile()` (called only for multi-step) are separate methods. Any change to `_get_duration()` cannot accidentally affect multi-step processing.

---

## 3. Proposed Behavior — Single-Step

### 3.1 Sequence Overview

For a single-step scenario where `grounded.get("duration_minutes")` is `None`:

1. `StandardizationService._get_duration()` detects `duration is None`.
2. Duration is set to `settings.default_long_window_minutes` (10080.0).
3. A `DefaultImputed` event is appended to `result.defaults_imputed` with the new `source=ValueSource.LONG_WINDOW_DEFAULT` field.
4. A warning string is appended to `result.warnings`.
5. `_get_duration()` returns `10080.0` — **never returns `None` for single-step after this change**.
6. The caller's `if duration is None` check (currently lines 168–170) becomes dead code; it should be removed.
7. Standardization continues normally; payload is built; orchestrator reaches `success=True`.
8. Route builder picks up `duration_minutes` from `metadata.defaults_imputed` (not from `metadata.provenance`) and constructs the `field_audit` entry with `source="long_window_default"`.

### 3.2 Where the Check Fires

**File:** `app/services/standardization/standardization_service.py`  
**Method:** `_get_duration()` at lines 381–383  
**Current body:**
```python
if duration is None:
    result.warnings.append("Duration is required but not specified")
    return None
```

**Replacement body:**
```python
if duration is None:
    duration = float(settings.default_long_window_minutes)
    result.defaults_imputed.append(DefaultImputed(
        field_name="duration_minutes",
        imputed_value=duration,
        reason=(
            f"No duration specified. Using long-window default "
            f"({int(duration / 60)} hours / {int(duration / 1440)} days) to ensure "
            "the prediction trajectory reaches the physical growth cap. "
            "The Result Interpretation Module will identify actionable sub-windows."
        ),
        source=ValueSource.LONG_WINDOW_DEFAULT,
    ))
    result.warnings.append(
        f"Duration not specified — long-window default applied "
        f"({int(duration / 60)} hours / {int(duration / 1440)} days). "
        "Prediction shows full growth trajectory to physical cap; "
        "sub-window analysis required for actionable interpretation."
    )
```

The `DefaultImputed.reason` string style models on pH/aw reason strings:
- pH growth: `"No pH specified. Using neutral default which is near-optimal for pathogen growth (conservative)."`
- Temperature growth: `"No temperature specified. Using conservative abuse temperature (25°C) for growth prediction."`
- Duration (new): `"No duration specified. Using long-window default (168 hours / 7 days) to ensure the prediction trajectory reaches the physical growth cap. The Result Interpretation Module will identify actionable sub-windows."`

The warning string models on temperature-default-related warnings — though see Open Question OQ-1 about whether temperature actually emits a warning.

### 3.3 Dead Code Removal

**In `_get_duration()` return type:** Changes from `float | None` to `float`. Update the type hint.

**In `standardize()` caller** (lines 168–170):
```python
# REMOVE: these lines become dead code
if duration is None:
    result.missing_required.append("duration")
    return result
```
After removal, the code at lines 167 and 172 flows directly:
```python
duration = self._get_duration(grounded, result, model_type)
representative_temp = temperature
profile = TimeTemperatureProfile(...)
```

**In `_missing_key_to_audit_key()` (orchestrator.py lines 50–51):**
```python
if field_spec == "duration":
    return "duration_minutes"
```
This branch becomes dead code for single-step once duration never reaches `missing_required`. **Recommendation: leave this branch in place.** It is correct, harmless, and acts as a safety net if a regression ever causes single-step duration to reach this code path. Removing it would make the test at `test_orchestrator.py:182` fail for no gain.

### 3.4 New `ValueSource` Enum Variant

**File:** `app/models/metadata.py` — `ValueSource` enum at lines 29–54  
**Add** after `COMPOSITE_FOOD_DEFAULT = "composite_food_default"` (line 50):

```python
LONG_WINDOW_DEFAULT = "long_window_default"  # Duration unspecified; long observation window
                                              # assumed so prediction trajectory reaches cap.
                                              # Epistemically distinct from CONSERVATIVE_DEFAULT:
                                              # duration is a scenario dimension, not an
                                              # environmental property with a safety-floor.
```

**Docstring addition** to `ValueSource`'s class docstring — add to the priority table note:
```
LONG_WINDOW_DEFAULT sits at the same safety-floor tier as CONSERVATIVE_DEFAULT and
COMPOSITE_FOOD_DEFAULT but is epistemically distinct: "duration unspecified, long window
assumed" is different from "environmental property unresolvable; conservative value applied."
```

### 3.5 `DefaultImputed` Source Field Addition

**File:** `app/models/metadata.py` — `DefaultImputed` at lines 273–294  
**Add** an optional `source` field:

```python
class DefaultImputed(BaseModel):
    field_name: str
    original_value: float | None = None
    imputed_value: float | str
    reason: str
    source: ValueSource | None = Field(
        default=None,
        description=(
            "Optional override for the ValueSource assigned in field_audit. "
            "When set, the route builder uses this value instead of inferring "
            "CONSERVATIVE_DEFAULT or COMPOSITE_FOOD_DEFAULT from composite_skip. "
            "Use for source variants that are neither conservative-default nor "
            "composite-food-default (e.g., LONG_WINDOW_DEFAULT)."
        ),
    )
```

This is backward-compatible: all existing callers construct `DefaultImputed` without `source`, which defaults to `None`. The route builder continues to infer `CONSERVATIVE_DEFAULT` / `COMPOSITE_FOOD_DEFAULT` when `source is None`.

### 3.6 `DefaultImputedInfo` API Schema Addition

**File:** `app/api/schemas/translation.py` — `DefaultImputedInfo` at lines 264–268  
**Add** an optional `source` field so API consumers can distinguish `LONG_WINDOW_DEFAULT` in the `defaults_imputed` summary without cross-referencing `field_audit`:

```python
class DefaultImputedInfo(BaseModel):
    field_name: str
    default_value: float | str
    reason: str
    source: str | None = Field(
        default=None,
        description="ValueSource variant (e.g. 'long_window_default', 'conservative_default'). "
                    "Null for defaults added before this field was introduced.",
    )
```

### 3.7 Route Builder Update

**File:** `app/api/routes/translation.py` — defaults loop at lines 313–317  
**Current:**
```python
default_source = (
    ValueSource.COMPOSITE_FOOD_DEFAULT.value
    if d.field_name in composite_skip
    else ValueSource.CONSERVATIVE_DEFAULT.value
)
```

**Replacement:**
```python
if d.source is not None:
    default_source = d.source.value
elif d.field_name in composite_skip:
    default_source = ValueSource.COMPOSITE_FOOD_DEFAULT.value
else:
    default_source = ValueSource.CONSERVATIVE_DEFAULT.value
```

Also update `DefaultImputedInfo` construction at lines 428–432 to propagate `source`:
```python
DefaultImputedInfo(
    field_name=d.field_name,
    default_value=d.imputed_value,
    reason=d.reason,
    source=d.source.value if d.source is not None else None,
)
```

### 3.8 Settings Addition

**File:** `app/config/settings.py` — Conservative Defaults section at lines 190–212  
**Add** after `default_water_activity` (line 211):

```python
default_long_window_minutes: float = Field(
    default=10080.0,
    ge=1.0,
    description=(
        "Duration default (minutes) when no duration is specified in a single-step query. "
        "7 days (168 hours) — long enough for any model type's trajectory to reach the "
        "physical growth cap (±15 log CFU) under worst-case conditions."
    ),
)
```

**File:** `.env.example` — after `DEFAULT_WATER_ACTIVITY=0.99`  
**Add:**
```
DEFAULT_LONG_WINDOW_MINUTES=10080.0
```

### 3.9 Final `field_audit["duration_minutes"]` State (Verbose Response)

When duration is missing on a single-step query (post-change):

```json
{
  "duration_minutes": {
    "final_value": 10080.0,
    "source": "long_window_default",
    "retrieval": null,
    "extraction": null,
    "standardization": {
      "rule": "default_imputed",
      "direction": null,
      "before_value": null,
      "after_value": 10080.0,
      "reason": "No duration specified. Using long-window default (168 hours / 7 days) to ensure the prediction trajectory reaches the physical growth cap. The Result Interpretation Module will identify actionable sub-windows."
    }
  }
}
```

Note: `duration_minutes` will appear **only** in the `defaults_imputed` processing branch of `_build_field_audit` (route builder lines 258–329), not in the grounding-provenance branch (lines 98–256). This is because `_ground_duration()` calls `mark_ungrounded()` (not `set_with_prov()`), so `grounded.provenance["duration_minutes"]` is absent. The route builder's defaults loop picks it up from `metadata.defaults_imputed`.

The `AuditSummary.defaults_imputed` list will include:
```json
{
  "field_name": "duration_minutes",
  "default_value": 10080.0,
  "reason": "No duration specified. Using long-window default (168 hours / 7 days)...",
  "source": "long_window_default"
}
```

---

## 4. Proposed Behavior — Multi-Step

**Multi-step behavior is unchanged.** This section exists to confirm the isolation and document the exact code paths that must NOT be modified.

### 4.1 Code Paths Not Touched

| What | File | Lines | Why unchanged |
|---|---|---|---|
| `_ground_multi_step_profile()` | grounding_service.py | 1490–1534 | Separate method, not called by single-step path |
| `_build_multi_step_profile()` | standardization_service.py | ~655–720 | Separate method; `dur is None → missing_required.append(f"duration (step N)")` stays |
| `_get_duration()` multi-step range resolution | standardization_service.py | 685–695 | This code lives inside `_build_multi_step_profile`, not `_get_duration` |
| `_missing_key_to_audit_key("duration (step N)")` | orchestrator.py | 52–53 | Still needed; maps step specs to audit keys |

### 4.2 Multi-Step Missing Duration — All Cases

**One step has `duration_minutes=None`:** `_build_multi_step_profile()` reaches that step, appends `"duration (step N)"` to `missing_required`, returns `None`. Standardization fails. Error: `"Missing required values: duration (step N)"`. **Keep this behavior.**

**All steps have `duration_minutes=None`:** First step encountered causes `return None` immediately. `missing_required` contains `"duration (step 1)"` only — later steps are not reached. This is technically imprecise (all steps are missing) but the behavior is correct: the request fails with a clear error naming the first problem. **Recommendation: keep this behavior unchanged.** The user's multi-step claim was malformed at step 1; requiring them to fix one step at a time is acceptable. Adding iteration to collect all missing steps would be a disproportionate change.

**Update (2026-08-17) — the "collect all missing steps" recommendation above was reversed; report only, terminal outcome is unchanged.** The multi-step duration clarification gate (`specs/specifications.md` §3.5) needs the complete set of missing steps to ask about all of them in one round, not just the first — so `_build_multi_step_profile()` now runs the loop to completion (`continue` instead of `return None` on a missing duration; every step's temperature is still evaluated/defaulted/clamped regardless), and only checks `if result.missing_required: return None` after the loop. `missing_required` for the "all steps missing" case above now contains `"duration (step 1)", "duration (step 2)", ...` — every step, not just the first. **What did NOT change:** `standardize()` still fails closed with `payload=None`; there is still no multi-step duration default (a value supplied via the clarification gate is not a default — absence still fails closed). The line 411/413 recommendation to "keep this behavior unchanged" was correct at the time it was written — no clarification gate existed yet, so collecting all missing steps had no consumer and would have been unused iteration. It stopped being correct once a consumer (the duration gate) needed the complete list. See `specs/lessons.md` (2026-08-17) for the full design reasoning.

### 4.3 Confirmed Isolation Proof

The routing gate at grounding_service.py:583–588 is the only entry to multi-step handling:
```python
if scenario.is_multi_step and scenario.time_temperature_steps:
    self._ground_multi_step_profile(scenario, grounded)
else:
    self._ground_temperature(scenario, grounded)
    self._ground_duration(scenario, grounded)   # ← the only call to _ground_duration
```

The `_get_duration()` method is called exclusively from `standardize()` lines 167:
```python
duration = self._get_duration(grounded, result, model_type)
```
This call is inside the `else:` branch of `if grounded.steps:` (the multi-step routing in `standardize()`). The new default logic is inside `_get_duration()`, which the multi-step path never calls.

---

## 5. Code Changes — File by File

### 5.1 `app/models/metadata.py`

**Changes:**

1. `ValueSource` enum [lines 49–50]: add `LONG_WINDOW_DEFAULT = "long_window_default"` after `COMPOSITE_FOOD_DEFAULT`. Update class docstring priority table.

2. `DefaultImputed` class [lines 273–294]: add `source: ValueSource | None = Field(default=None, ...)`.

**Test impact:** Tests constructing `DefaultImputed` without `source` are unaffected (backward compatible). Tests importing `ValueSource` that check exact member lists need `LONG_WINDOW_DEFAULT` added (see §6 item 6).

---

### 5.2 `app/config/settings.py`

**Changes:**

Add `default_long_window_minutes: float = Field(default=10080.0, ...)` after `default_water_activity` [line 211].

**Test impact:** None — additive.

---

### 5.3 `.env.example`

**Changes:**

Add `DEFAULT_LONG_WINDOW_MINUTES=10080.0` after `DEFAULT_WATER_ACTIVITY=0.99`.

**Test impact:** None.

---

### 5.4 `app/services/standardization/standardization_service.py`

**Changes:**

1. `_get_duration()` [lines 381–383]: replace the `if duration is None` body with the DefaultImputed + warning emission (see §3.2). Update return type from `float | None` to `float`. Ensure `ValueSource` is imported (add `from app.models.metadata import DefaultImputed, ValueSource` if not already present — verify at top of file).

2. `standardize()` caller [lines 168–170]: remove the `if duration is None: result.missing_required.append("duration"); return result` block. This is dead code after the change.

**Test impact:**
- `test_missing_duration_fails` (integration, §6 item 1): **breaks** — see §6.
- Any test that calls `_get_duration()` or `standardize()` with missing duration and asserts failure: **breaks** — see §6.

---

### 5.5 `app/core/orchestrator.py`

**No changes required.** The `_missing_key_to_audit_key("duration")` branch at lines 50–51 becomes dead code for single-step but is harmless. The `if std_result.missing_required:` block at lines 167–184 no longer fires for single-step missing duration (since `missing_required` is empty). Multi-step behavior is unchanged.

**Test impact:** `test_orchestrator.py:test_single_step_duration` [line 182–183] tests `_missing_key_to_audit_key("duration")`. This test is still correct (the function still handles the input correctly; it's just that this case is now unreachable in production). Leave the test in place.

---

### 5.6 `app/api/routes/translation.py`

**Changes:**

1. `_build_field_audit()` defaults loop [lines 313–317]: update `default_source` logic to check `d.source` first (see §3.7).

2. `DefaultImputedInfo` construction [lines 428–432]: propagate `source` field (see §3.7).

**Test impact:** Tests asserting `field_audit["duration_minutes"].source == "missing"` on single-step missing-duration scenarios: **break** — replace with `"long_window_default"`.

---

### 5.7 `app/api/schemas/translation.py`

**Changes:**

`DefaultImputedInfo` [lines 264–268]: add `source: str | None = Field(default=None, ...)` (see §3.6).

**Test impact:** Tests constructing `DefaultImputedInfo` without `source`: unaffected (backward compatible). Tests asserting on `defaults_imputed` list entries in API responses: add assertion for `source == "long_window_default"` on the duration entry.

---

## 6. Test Changes

### 6.1 Tests That Break

**T-1: `tests/integration/test_full_pipeline.py:381-396` — `test_missing_duration_fails`**

Current assertions:
```python
assert result.success is False
assert "duration" in result.error.lower()
```

After the change, a single-step query with no duration succeeds. **Replace with:**
```python
# success is True
assert result.success is True
assert result.error is None
# DefaultImputed entry for duration is present
duration_default = next(
    (d for d in result.metadata.defaults_imputed if d.field_name == "duration_minutes"),
    None,
)
assert duration_default is not None
assert duration_default.imputed_value == 10080.0
assert duration_default.source == ValueSource.LONG_WINDOW_DEFAULT
# Warning is present
assert any("duration" in w.lower() for w in result.metadata.warnings)
```

Consider renaming the test to `test_missing_single_step_duration_defaults_to_long_window`.

### 6.2 Tests That Stay Unchanged (Verified)

**T-2: `tests/unit/test_multistep_grounding.py:428-434` — `test_missing_duration_fails_with_missing_required`**

Multi-step fixture (`_make_grounded((25.0, None))`). Asserts `any("duration" in m for m in result.missing_required)` and `result.payload is None`. **Unchanged** — multi-step path unaffected.

**T-3: `tests/unit/test_multistep_grounding.py:436-442` — `test_missing_duration_mid_sequence_fails`**

Multi-step fixture with 3 steps, step 2 duration=None. Asserts `any("step 2" in m.lower() for m in result.missing_required)`. **Unchanged**.

**T-4: `tests/unit/test_orchestrator.py:182-183` — `test_single_step_duration`**

Tests `_missing_key_to_audit_key("duration") == "duration_minutes"`. The function is unchanged; the test remains correct. **Unchanged.**

**T-5: `tests/unit/test_orchestrator.py:278-281` — `test_error_names_missing_field`**

Orchestrator fixture (`orchestrator_for_failure`) uses `mock_grounder_missing_duration` which builds a multi-step scenario (calls `add_step(duration_minutes=None)`). Asserts `"step 1" in result.error.lower()`. Multi-step path. **Unchanged.**

**T-6: `tests/unit/test_orchestrator.py:298-303` — `test_missing_duration_appears_with_null_source`**

Multi-step fixture, asserts `field_audit["duration_minutes (step 1)"].source == ValueSource.MISSING`. **Unchanged** — multi-step.

**T-7: `tests/unit/test_model_type_aware_bias.py:156-159` — duration defaults == [] when explicit duration**

```python
duration_defaults = [d for d in result.defaults_imputed if "duration" in d.field_name]
assert duration_defaults == []
```

The grounded values fixture provides `duration_minutes=8.0` explicitly (line 152). No long-window default fires. **Unchanged.**

**T-8: `tests/unit/test_model_type_aware_bias.py:609-616` — `non_inoculum_defaults == []` for bread range test**

`_make_grounded_bread()` at line 569 sets `duration_minutes=180.0`. No long-window default fires. **Unchanged.**

**T-9: `tests/unit/test_model_type_aware_bias.py:633-636` — same for inactivation variant**

Same fixture provides duration. **Unchanged.**

### 6.3 `defaults_imputed == []` Assertion Fragility — Audit

The 2026-05-11 lesson explicitly flagged `== []` assertions on `defaults_imputed` as fragile. Searching the test corpus for this pattern as it relates to single-step missing-duration scenarios:

- `test_model_type_aware_bias.py:614` (`non_inoculum_defaults == []`): SAFE — fixture provides duration explicitly.
- `test_model_type_aware_bias.py:636` (`non_inoculum_defaults == []`): SAFE — same.
- `test_api_translation.py:459` (`audit_summary["warnings"] == []`): needs manual verification — if the underlying scenario omits duration, this will break. **Flag for review during implementation.**

General rule: any test that constructs a `GroundedValues` without setting `duration_minutes` AND then asserts `defaults_imputed == []` or `non_inoculum_defaults == []` WILL break. The fix is always the field-filtered pattern:
```python
non_duration_non_inoculum_defaults = [
    d for d in result.defaults_imputed
    if d.field_name not in ("duration_minutes", "initial_inoculum_log_cfu")
]
assert non_duration_non_inoculum_defaults == []
```

### 6.4 New Tests Required

**NT-1: Single-step with no duration → success, long-window default applied**
```
File: tests/integration/test_full_pipeline.py (or new test class)
Scenario: food="chicken", organism="Salmonella", temperature=25.0°C, duration=None
Assert:
  - result.success is True
  - result.metadata.defaults_imputed contains entry: field_name="duration_minutes",
    imputed_value=10080.0, source=LONG_WINDOW_DEFAULT
  - result.metadata.warnings contains a string with "duration" and "long-window"
  - result.prediction.total_log_increase ≈ ±15.0 (physical cap reached, worst-case growth)
```

**NT-2: Single-step with explicit duration → no regression**
```
Scenario: food="chicken", organism="Salmonella", temperature=25.0°C, duration=120 min
Assert: result.success is True, no duration entry in defaults_imputed
```

**NT-3: Single-step with rule-matched duration ("overnight" → 480 min) → no long-window fires**
```
Scenario: single_step_duration.description="overnight"
Assert: result.success is True, field_audit["duration_minutes"].source == "user_inferred",
        no duration entry in defaults_imputed, payload.total_duration_minutes == 480.0
```

**NT-4: Multi-step with one step missing duration → success=False unchanged**
```
Scenario: is_multi_step=True, step 1 duration=None, step 2 duration=60 min
Assert: result.success is False, "step 1" in result.error.lower()
```

**NT-5: Multi-step with all step durations missing → success=False, error names step 1**
```
Scenario: is_multi_step=True, step 1 duration=None, step 2 duration=None
Assert: result.success is False, "step 1" in result.error.lower()
```

**NT-6: Audit shape — `LONG_WINDOW_DEFAULT` source in field_audit and defaults_imputed**
```
File: tests/unit/ (standardization or route builder test)
Scenario: standardize() with duration=None, single-step
Assert:
  - "duration_minutes" in result.defaults_imputed (field)
  - result.defaults_imputed[duration_entry].source == ValueSource.LONG_WINDOW_DEFAULT
  - _build_field_audit(result)["duration_minutes"].source == "long_window_default"
  - _build_field_audit(result)["duration_minutes"].final_value == 10080.0
  - _build_field_audit(result)["duration_minutes"].standardization.rule == "default_imputed"
```

**NT-7: Settings override — `default_long_window_minutes` is configurable**
```
Set DEFAULT_LONG_WINDOW_MINUTES=2880 (2 days) via environment
Standardize with duration=None
Assert: defaults_imputed duration entry has imputed_value=2880.0
```

---

## 7. Documentation Updates

### 7.1 `docs/ptm_context.md`

**§5.2 Grounding Service — Priority table:**  
No change to the table rows. Add a sentence to the `CONSERVATIVE_DEFAULT` row notes: *"Duration is not included here — see §5.3 and §8.13 for its new defaulting behavior via `LONG_WINDOW_DEFAULT`."*

**§5.2 Interpretation rules — Duration rules paragraph:**  
After the existing paragraph ending *"Below threshold, the field is marked ungrounded and standardization will apply a conservative default."*: change the last clause to *"…standardization will apply a long-window default (see §5.3 and §8.13)"*.

**§5.3 Standardization Service — Default imputation paragraph:**  
Update bullet list under "When a required value is absent":
- Add: `duration_minutes (GROWTH/NON_THERMAL/THERMAL) → 10080.0 min (7 days) — long observation window ensuring trajectory reaches physical cap. Source: LONG_WINDOW_DEFAULT.`

Update the **Conservative defaults (current)** list:
```
- default_temperature_abuse_c = 25.0
- default_ph_neutral = 7.0
- default_aw_high = 0.99
- default_long_window_minutes = 10080.0  ← ADD
```

Add a note to the `duration_minutes` bullet: *"This default is epistemically distinct from CONSERVATIVE_DEFAULT: duration is a scenario dimension (how long to simulate) rather than an environmental property with a scientifically-defensible worst-case. The value 10080 min is chosen to ensure the trajectory visibly reaches the `_PHYSICAL_LOG_LIMIT = 15.0` cap under all model types and worst-case environmental inputs."*

**§8.13 Organism is a required field:**  
Retitle to: **8.13 Required fields: organism is required; duration defaults to long-window for single-step**.

Restructure the opening paragraph to explicitly state the split:
- Organism: required field, no default. `missing_required` path, `success=False`. Rationale: no single organism is safe across all food categories.
- Duration (single-step): now defaulted. `LONG_WINDOW_DEFAULT` event, `success=True`. Rationale: duration is a scenario dimension; the 7-day default ensures full trajectory visibility without asserting a hazard identity.
- Duration (multi-step): still required per step. Rationale: a missing step duration is a structurally malformed multi-step claim.

Update the "Symmetric precedent" sentence (currently: *"Duration uses the same pattern."* [line 747]) to read: *"Duration previously used the same pattern. As of Phase XX (2026-05-xx), single-step duration has been moved to the defaulted-field category (LONG_WINDOW_DEFAULT); organism retains the required-field behavior."*

**§10.1 Component status:**  
Add row: `Phase XX | LONG_WINDOW_DEFAULT for missing single-step duration | ✅ Done`

**§15 Changelog:**  
Add version entry:
```
| 1.6 | 2026-05-xx | Long-window default for single-step missing duration. Duration moves
from required-field (success=False) to defaulted-field (LONG_WINDOW_DEFAULT, success=True)
for single-step scenarios. Multi-step keeps failure path. Added `default_long_window_minutes=10080`
to settings. Added `LONG_WINDOW_DEFAULT` to ValueSource and `source` field to DefaultImputed/
DefaultImputedInfo. §5.3 default table, §8.13, §9.2 updated. |
```

**§16 Deferred items:**  
No new deferred items unless OQ-3 (frontend Zod schema) goes unresolved.

### 7.2 `specs/specifications.md`

**§3.3 StandardizationService — Operation 2 default table:**  
Add row:
```
| `duration_minutes` | `10080.0 min` (7 days) (`settings.default_long_window_minutes`) | Single-step only — long window ensuring trajectory reaches cap. Source: LONG_WINDOW_DEFAULT. Multi-step duration is a required field. |
```

Also correct the existing `organism → SALMONELLA` row — this default was removed in Phase 9.5 (see §8.13 and 2026-05-08 lesson). The row should be removed. **This is a pre-existing documentation debt, not introduced by this change; fix it in the same PR.**

**§4.5 `ValueProvenance` member list:**  
In the `source` field description, add `LONG_WINDOW_DEFAULT` to the list of enum values shown.

**§9.2 Default Values table:**  
Add row:
```
| duration_minutes (single-step only) | 10080.0 min | Long window — trajectory reaches physical cap |
```

Also remove the `organism → Salmonella` row (same pre-existing debt as §3.3). **Fix in same PR.**

**§14 Glossary:**  
Add entry:
```
**`LONG_WINDOW_DEFAULT`** — ValueSource variant emitted when a single-step query provides no
duration. The 7-day (10080 min) window ensures the prediction trajectory reaches the physical
growth cap (±15 log CFU) under all model types. Epistemically distinct from CONSERVATIVE_DEFAULT:
duration is a scenario dimension (how long to simulate), not an environmental property with a
scientifically-defensible worst-case value.
```

---

## 8. Open Questions for Daniel

### OQ-1: Does temperature imputation currently emit a warning?

`specifications.md §5.3` says *"A warning string is also emitted for missing critical fields (organism, temperature)."* However, reading `standardization_service.py` lines 314–334, `_get_temperature()` appends to `result.defaults_imputed` but does NOT call `result.warnings.append(...)`. No warning is emitted by temperature imputation in the current code. The spec text appears aspirational rather than descriptive.

**Impact on this change:** Decision #5 says duration's long-window default DOES emit a warning. The proposed code (§3.2) emits the warning. This is correct regardless of whether temperature actually does.

**Recommended resolution:** During implementation, verify whether temperature emits a warning (grep for `result.warnings` in `_get_temperature()`). If it does not, add a note in `specifications.md §5.3` clarifying that temperature imputation emits only `DefaultImputed`, not a warning. The duration warning is a new behavior, and the spec should be honest about it. The fact that temperature doesn't warn does not weaken the decision for duration — duration's warning is epistemically important because a 7-day default dramatically changes the interpretation scope.

---

### OQ-2: `test_api_translation.py:459` — `audit_summary["warnings"] == []`

This test (around line 459) asserts `audit_summary["warnings"] == []`. The scenario it uses needs to be checked. If the scenario omits duration, the new warning fires. **If the test omits duration, it will break and should be updated with a field-filtered assertion.**

**Recommended resolution:** During implementation, inspect the test's scenario construction. If duration is omitted: update the assertion to allow the duration warning while still asserting other expected warnings are absent. If duration is explicit: no change needed.

---

### OQ-3: Frontend Zod schema for `source` in `DefaultImputedInfo`

If a frontend consumer has a Zod schema for the API response, it may need the new `source` field added to `DefaultImputedInfo`. It may also need `"long_window_default"` added to any `ValueSource`-equivalent union type.

**Recommended resolution:** The frontend repo is not in this checkout. Daniel should check the frontend Zod schema for `DefaultImputedInfo` and add the optional `source` field. The new `source` field defaults to `null` in the API response (for historical entries), so strict parsers that don't handle `null | undefined` will break only if they assert `source` is always a specific string.

---

### OQ-4: Pre-existing documentation debt in `specifications.md §3.3` and `§9.2`

Both sections list `organism → SALMONELLA` as a default value. This default was removed in Phase 9.5 (May 2026). The row should be deleted. This is not introduced by this change but should be cleaned up in the same PR to prevent compounding the debt.

**Recommended resolution:** Include the deletion in the PR that implements this spec. The two rows are: §3.3 Operation 2 table `| organism | SALMONELLA | ...` and §9.2 Default Values table `| organism | Salmonella | Broadly applicable worst-case |`.

---

### OQ-5: Standardize the `DefaultImputed.source` field — migration note

Adding `source` to `DefaultImputed` is backward-compatible at the Python level. However, if `DefaultImputed` objects are ever serialized to the database (MLflow, SQLite, etc.) or persisted in experiment results, existing records won't have the field and deserialization may need a migration or a `None` default. From inspection, `DefaultImputed` objects are only held in-memory within a single request/response cycle — they are never persisted directly to disk. They DO appear in the API response via `DefaultImputedInfo`, which gains the optional `source: str | None` field.

**Recommended resolution:** No migration needed. Confirm by checking whether any code serializes `DefaultImputed` directly to disk.

---

## Appendix: Investigation Verification Log

All file:line references in this spec were verified by direct file reads on 2026-05-17. Where the investigation agent's findings diverged from direct reads, direct reads win.

| Finding | Verified via | Notes |
|---|---|---|
| `_ground_duration()` at lines 1472–1488 | Direct read | Confirmed |
| `_get_duration()` at lines 356–385 | Direct read | Confirmed |
| `standardize()` caller at lines 167–170 | Direct read | Confirmed |
| Orchestrator `_missing_key_to_audit_key` at lines 50–51 | Direct read | Confirmed |
| Orchestrator missing-required block at lines 167–184 | Direct read | Confirmed |
| Route builder defaults loop at lines 313–317 | Direct read | Confirmed |
| `ValueSource` enum at lines 29–54 in `metadata.py` | Direct read | Confirmed |
| `DefaultImputed` class at lines 273–294 | Direct read | Confirmed |
| `DefaultImputedInfo` at lines 264–268 | Direct read | Confirmed |
| `settings.py` conservative defaults at lines 190–212 | Direct read | Confirmed |
| Multi-step routing at grounding_service.py:583–588 | Direct read | Confirmed |
| Multi-step duration check at standardization_service.py:697–699 | Direct read | Confirmed |
| `test_missing_duration_fails` at integration/test_full_pipeline.py:381 | Direct read | Single-step, confirmed |
| `test_missing_duration_fails_with_missing_required` at test_multistep_grounding.py:428 | Direct read | Multi-step, confirmed |
| Bread fixture `_make_grounded_bread` includes duration at line 569 | Direct read | Confirmed — bread range tests are safe |
