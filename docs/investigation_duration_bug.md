# Duration Bug Investigation Report

**Query:** "We need to model L. monocytogenes growth in vacuum-packed sliced turkey deli meat during retail display for 35 days. Assume typical retail refrigeration. What growth can we expect?"

**Reported symptom:** `duration_minutes` extracted as `2520` (42 hours). Expected: `50400` (35 × 1440).

**Investigation date:** 2026-05-05

---

## 1. Root Cause Hypothesis

**The bug is an LLM unit-conversion failure in the SemanticParser, compounded by the absence of any validation in the schema or grounding layer.**

The `ExtractedDuration.value_minutes` field in `app/models/extraction.py` (lines 59–62) has no Pydantic constraints (`le=`, `ge=`, or any validator). The Pydantic schema is:

```python
value_minutes: float | None = Field(
    default=None,
    description="Explicit duration in minutes if mentioned"
)
```

There is no upper bound, no unit validator, and no cross-field check. The LLM (configured via `LLM_MODEL` in `.env`; currently `ollama/gemma4:latest`) is instructed in `SCENARIO_EXTRACTION_PROMPT` to "Convert all durations to minutes" but the instruction is not enforced structurally. When the duration is expressed in days or weeks, the LLM either:

- **(A) Fails to convert at all** and puts the raw string (e.g. `"35 days"`) into `description`, leaving `value_minutes = None`. This was reproduced live for `gemma4`.
- **(B) Performs an incorrect conversion** — returning a value that is not `N × 1440` for N days — such as `2520` (the reported value) or `5040` (observed for "840 hours", which should be `50400`). The errors are consistent with the LLM treating a day as 72 minutes (`35 × 72 = 2520`) or treating an hour as 6 minutes (`840 × 6 = 5040`), i.e. confusing 60 with 6 or inventing a wrong scale factor.

The original reported value `2520 = 35 × 72 = 35 × (1 hour × 3)` cannot come from any standard conversion. It is most consistent with the model applying an incorrect factor. `5040 = 840 × 6` from the "840 hours" live test is the same pattern: the model multiplied by 6 instead of 60.

**The bug is not:**
- A Pydantic `le=` cap (no such constraint exists on `value_minutes` or anywhere related to duration).
- A hardcoded constant in `rules.py` (no duration constant of 2520, 1440, or any days-scale value exists there; the max is 720 minutes = 12 hours for "all day").
- A cap in the grounding service (no cap on duration exists there).
- A cap in the standardization service (not investigated here, but standardization only clamps to model valid ranges which are temperature/pH/aw, not duration).

**Primary location of the bug:**
- `app/services/extraction/semantic_parser.py`, the `SCENARIO_EXTRACTION_PROMPT` (lines 34–77) — the prompt says "Convert all durations to minutes" but gives no worked example for multi-day durations.
- `app/models/extraction.py`, `ExtractedDuration.value_minutes` (lines 59–62) — the field description says "Explicit duration in minutes if mentioned" but does not specify how to handle days or weeks, and imposes no validation.

**Secondary failure (audit honesty):** When `value_minutes` is populated (e.g. with a wrong value like 2520), the grounding service immediately accepts it as `USER_EXPLICIT` with `extraction_method="direct"`. The audit therefore reports `source="user_explicit"` and `method="direct"` for an LLM-fabricated, incorrectly converted value — which is misleading.

---

## 2. Evidence

### 2.1 No schema constraint on `value_minutes`

From `app/models/extraction.py` (lines 59–62), verbatim:

```python
value_minutes: float | None = Field(
    default=None,
    description="Explicit duration in minutes if mentioned"
)
```

No `le=`, no `ge=`, no validator. Any float (including nonsensical values) passes Pydantic validation.

### 2.2 Prompt does not give multi-day conversion examples

From `app/services/extraction/semantic_parser.py`, `SCENARIO_EXTRACTION_PROMPT` (lines 34–77):

```
- Convert all temperatures to Celsius
- Convert all durations to minutes
```

There are **no examples** showing how to handle days or weeks. The scenario examples in the prompt are all sub-24-hour durations:

```
- "Chicken left out for 3 hours" → is_storage_scenario=True, implied_model_type="growth"
- "Cooking chicken to 75°C for 5 minutes" → is_cooking_scenario=True, ...
- "Beef stored in fridge for a week" → is_storage_scenario=True, ...
```

The "week" example in the prompt does NOT include the expected `value_minutes=10080` — it only demonstrates `implied_model_type`. The LLM is never shown what a correct multi-day conversion looks like in the output schema.

### 2.3 Duration interpretation rules only cover sub-24h vague terms

From `app/config/rules.py`, the `DURATION_INTERPRETATIONS` list (lines 208–346): the longest duration rule is:

```python
InterpretationRule(
    pattern="all day",
    value=720.0,
    conservative=True,
    notes="All day could be 8-14 hours; using 12",
),
```

Maximum: 720 minutes (12 hours). There are no rules for "days", "weeks", or numeric-plus-unit expressions like "35 days".

A unit test enforces this ceiling: `tests/unit/test_rules.py` line 482:
```python
assert 1 <= rule.value <= 1440, f"Unreasonable duration {rule.value} for {rule.pattern}"
```

This means if the LLM puts `"35 days"` into `description` instead of converting to minutes, `find_duration_interpretation("35 days")` returns `None`, and `_resolve_duration_value` returns `(None, None)` — marking the field as ungrounded. This is the silent failure path.

### 2.4 The grounding service accepts any LLM-produced value without validation

From `app/services/grounding/grounding_service.py`, `_resolve_duration_value` (lines 966–970):

```python
if dur.value_minutes is not None:
    return dur.value_minutes, ValueProvenance(
        source=ValueSource.USER_EXPLICIT,
        extraction_method="direct",
    )
```

No range check. No plausibility check. Any value in `value_minutes` — including `2520` or `5040` — is immediately returned as `USER_EXPLICIT` / `direct`.

### 2.5 Live test results (gemma4:latest on Ollama)

Ten inputs were run live against the configured model (`ollama/gemma4:latest`). Results:

| Input | Expected min | Got `value_minutes` | `description` |
|---|---|---|---|
| "...for 35 days at 4C" | 50400 | `None` | `"35 days"` |
| "...for 5 days at 4C" | 7200 | `None` | `"5 days"` |
| "...for 1 day at 4C" | 1440 | `1440.0` | — |
| "...for 2 weeks at 4C" | 20160 | `None` | `"2 weeks"` |
| "...for 24 hours at 4C" | 1440 | `1440.0` | — |
| "...for 1 week at 4C" | 10080 | `None` | `"1 week"` |
| "...over its 35-day shelf life..." | 50400 | `None` | (not recorded) |
| "...for 35 days at 4C (refrigerated)" | 50400 | `None` | (not recorded) |
| "...for 50400 minutes at 4C" | 50400 | `50400.0` | — |
| "...for 840 hours at 4C" | 50400 | `5040.0` | `"840 hours"` |

**Pattern:** The model correctly converts hours ≤ 24 and exact minutes. It fails silently for multi-day and multi-week expressions (value goes to `None`, raw text to `description`). It produces a numerically wrong value for large-hour values: `5040 = 840 × 6` (should be `840 × 60`).

The reported bug value `2520` is consistent with the same LLM on a different run or model version applying an incorrect scale factor to "35 days": e.g. `35 × 72 = 2520`, where the model treats 1 day as 72 minutes instead of 1440 minutes.

### 2.6 No `2520` anywhere in the codebase

Searched the entire codebase for the literal `2520` — no matches. This confirms 2520 is not a hardcoded cap, sentinel, or constant. It is produced by the LLM.

### 2.7 No `le=` constraint on any duration field in `extraction.py` or `combase.py`

From `app/models/execution/combase.py` (grep for `le=`): only pH and aw fields have `le=` constraints (`le=14.0` and `le=1.0` respectively). No duration field has any upper bound enforced at the Pydantic level.

---

## 3. Surface Table

All 10 inputs run live against `ollama/gemma4:latest`. Model confirmed running via Ollama API check (`gemma4:latest`, 8B Q4_K_M).

| Input phrase | Expected minutes | Extracted `value_minutes` | `description` | Result |
|---|---|---|---|---|
| "...for 35 days at 4°C" | 50400 | `None` | `"35 days"` | FAIL — not converted |
| "...for 5 days at 4°C" | 7200 | `None` | `"5 days"` | FAIL — not converted |
| "...for 1 day at 4°C" | 1440 | `1440.0` | not set | OK |
| "...for 2 weeks at 4°C" | 20160 | `None` | `"2 weeks"` | FAIL — not converted |
| "...for 24 hours at 4°C" | 1440 | `1440.0` | not set | OK |
| "...for 1 week at 4°C" | 10080 | `None` | `"1 week"` | FAIL — not converted |
| "...over its 35-day shelf life at 4°C" | 50400 | `None` | (raw text) | FAIL — not converted |
| "...for 35 days at 4°C (refrigerated)" | 50400 | `None` | (raw text) | FAIL — not converted |
| "...for 50400 minutes at 4°C" | 50400 | `50400.0` | not set | OK |
| "...for 840 hours at 4°C" | 50400 | `5040.0` | `"840 hours"` | FAIL — wrong factor (×6 not ×60) |

**Pattern summary:**
- Single-day ("1 day") and small-hour values ("24 hours") convert correctly.
- Multi-day and multi-week durations: model puts raw string in `description`, leaves `value_minutes = None`.
- Very large hour values (840 hours): model produces a numerically wrong `value_minutes` using a factor of 6 instead of 60.
- Exact-minute values pass through correctly.
- The reported `2520` from the original bug is reproducible in principle: on a different run or with `gpt-4o` (the configured fallback), the model may return an incorrect numeric value rather than `None`.

**Why the original bug shows `2520` while our live test shows `None`:** The original bug was likely run with a different LLM (possibly `gpt-4o` based on `settings.py` default, or an earlier version of the same ollama model). `gpt-4o` may attempt the conversion but apply an incorrect scale factor, whereas `gemma4` leaves the field as `None` with the raw description. Both behaviors stem from the same root cause: the prompt does not reliably instruct the model to perform the conversion correctly.

---

## 4. Audit-Honesty Failure Point

### Where the misleading provenance is constructed

In `app/services/grounding/grounding_service.py`, `_resolve_duration_value` (lines 966–970):

```python
if dur.value_minutes is not None:
    return dur.value_minutes, ValueProvenance(
        source=ValueSource.USER_EXPLICIT,
        extraction_method="direct",
    )
```

This is the **only** path that sets `source=USER_EXPLICIT` and `extraction_method="direct"` for `duration_minutes`. It fires whenever the LLM has placed any float in `ExtractedDuration.value_minutes`.

### What "direct" actually means

The `extraction_method` field on `ValueProvenance` is documented in `app/models/metadata.py` (line 97):

```python
description="How the value was extracted: 'regex', 'llm', 'regex+llm', 'rule', 'direct'"
```

The value `"direct"` is used throughout the grounding service for **all user-supplied numeric values** — i.e. values the LLM placed in a numeric field. It is meant to convey "no intermediate regex or rule matching occurred; the number came straight from the extraction model." However, the extraction model is itself an LLM, so `"direct"` is a misleading label. It sounds like the value was typed by the user, but it was inferred by an LLM from free text.

### What would make it honest

Currently there is no `"llm_extraction"` or `"instructor_extraction"` method value anywhere in the codebase. Every LLM-extracted numeric value lands as `"direct"`. An honest label would be `"llm_extraction"` or `"instructor"` — indicating that the value was extracted by Instructor + LLM from free text, not read directly from a typed user input.

The provenance shown in the bug report:
```json
"duration_minutes": {
  "final_value": 2520,
  "source": "user_explicit",
  "extraction": { "method": "direct" },
  "standardization": null
}
```

reads as: "the user explicitly provided 2520 minutes." In reality: "an LLM inferred (incorrectly) that '35 days' is 2520 minutes." The audit is misleading both in `source` (implies typed user value) and in `method` (implies no transformation occurred).

### Where `source=USER_EXPLICIT` is set

The `source` label `USER_EXPLICIT` is defined in `app/models/metadata.py` (line 31):
```python
USER_EXPLICIT = "user_explicit"  # User stated directly
```

Its use for LLM-extracted numeric values is technically accurate at the pipeline boundary (the value was "what the user expressed"), but loses the crucial distinction between "user typed `2520`" and "LLM inferred `2520` from `35 days`".

---

## 5. Fix Options

### Option A — Prompt change: add explicit conversion examples for multi-day durations

**What it changes:**  
Add worked examples to `SCENARIO_EXTRACTION_PROMPT` in `app/services/extraction/semantic_parser.py` showing exact multi-day/multi-week conversions:

```
Duration conversion examples:
- "for 35 days" → value_minutes = 50400  (35 × 24 × 60)
- "for 2 weeks" → value_minutes = 20160  (14 × 24 × 60)
- "for 1 week"  → value_minutes = 10080  (7 × 24 × 60)
- "for 12 hours" → value_minutes = 720
- "shelf life of 35 days" → value_minutes = 50400
```

Also add the field description to `ExtractedDuration.value_minutes`:
```
description="Duration converted to minutes. 1 hour = 60 min, 1 day = 1440 min, 1 week = 10080 min"
```

**What it leaves untouched:** No code changes. No schema changes. No new pipeline stages.

**Risks:**
- Prompt engineering is not guaranteed: any LLM may still hallucinate on edge cases or unusual phrasing ("35-day shelf life", "for about a month").
- The examples will anchor the LLM to those exact values, but it may still apply wrong arithmetic for arbitrary N.
- No regression testing is possible without live LLM calls; test coverage of this path is hard.
- Model-dependent: examples that work for `gpt-4o` may not work for `gemma4`.

**Size:** ~1 hour (prompt authoring and manual validation).

---

### Option B — Dedicated time-arithmetic tool/function callable by the parser

**What it changes:**  
Expose a tool (in Instructor tool-use or a pre-processing step) that the LLM can call to convert a duration expression to minutes. The LLM identifies the expression ("35 days") and the tool computes `35 × 1440 = 50400`. The parser uses `extract_generic` with a two-step flow: (1) extract the raw duration expression as a string, (2) run it through a deterministic arithmetic tool.

Concretely:
- Add a `DurationParsingTool` or pre-processing step before the Instructor extraction call.
- Use regex/NLP to detect `N days`, `N weeks`, `N hours` in the raw user string and pre-compute `value_minutes` before passing to the LLM.
- Pass the pre-computed value as context in the prompt or inject it into the `ExtractedDuration` before the LLM call.

**What it leaves untouched:** The rest of the pipeline (grounding, standardization, engine) is unchanged.

**Risks:**
- Adds complexity to the parser; the tool needs to handle all duration phrasings ("over its 35-day shelf life", "35 days at retail", "for approximately one month").
- Regex-based pre-computation may miss idiomatic expressions.
- Two-step extraction means two LLM calls or a more complex prompt with tool calls.
- Requires `LLMClient` extension (if using Instructor tool use) or a regex preprocessing step.

**Size:** ~4–6 hours (tool design, regex patterns, integration, unit tests).

---

### Option C — Dedicated "duration normalization" stage between extraction and grounding

**What it changes:**  
Add a new pipeline stage after `SemanticParser.extract_scenario` and before `GroundingService.ground_scenario`. This stage inspects `ExtractedDuration`:

1. If `value_minutes is None` and `description` matches a parseable expression (e.g. `r"(\d+)\s*(day|week|month|hour|minute)s?"`) → compute `value_minutes` deterministically.
2. If `value_minutes` is set but implausibly small given the unit in `description` (e.g. description says "days" but value is `< 1440`) → correct it.
3. Log the correction as a structured event (not `USER_EXPLICIT` / `direct`, but a new source like `NORMALIZED_DURATION`).

This stage would live in a new file, e.g. `app/services/extraction/duration_normalizer.py`, and be invoked in `app/core/orchestrator.py` after `_extract_scenario`.

**What it leaves untouched:** `SemanticParser`, `GroundingService`, `StandardizationService`, the ComBase engine, and all existing tests are unchanged.

**Risks:**
- The regex needs to handle the full range of English duration expressions, including ambiguous ones ("for about a month", "over the next 35 days").
- Adds a new pipeline component that needs its own unit tests.
- If the extraction puts "2 weeks" in `description` with no numeric extraction at all, the normalizer must parse English, not just strip a known pattern.
- The `NORMALIZED_DURATION` source label must be carefully defined — is it `USER_INFERRED` (closest existing category) or a new enum value?

**Size:** ~4–8 hours (normalizer, regex coverage, audit label changes, unit tests).

---

## 6. Open Questions for Daniel

1. **Which LLM produced `2520`?** The `.env` currently has `LLM_MODEL=ollama/gemma4:latest`. Was the original bug reproduced with `gpt-4o` (the `settings.py` default) or with gemma4? The error pattern differs: gemma4 produces `None` in live tests; the `2520` value implies a model that attempts the conversion but uses a wrong factor. Understanding which model produced the reported value matters for choosing Fix Option A (prompt tuning is model-dependent).

2. **How was `2520` previously reported as the behavior?** Our live tests with `gemma4` show `None` (not 2520) for "35 days". Was the bug observed with a different model or in a different test run? Is there a recorded response payload from the actual bug occurrence?

3. **What is the acceptable maximum duration?** The rules test file `tests/unit/test_rules.py` line 482 asserts that all DURATION_INTERPRETATIONS values must be `≤ 1440` minutes (24 hours). This ceiling makes sense for vague terms but would need to be revisited if the normalizer is to produce multi-day values from `description`. Does the system ever need to model durations beyond 30 days (43200 minutes)?

4. **Should the `USER_EXPLICIT` / `"direct"` audit label be changed?** Fixing the misleading audit label (Section 4) would require a schema change to `extraction_method` values. This is a correctness improvement but is a breaking change for any consumer that checks for `"direct"`. Is this worth doing alongside the duration fix, or separately?

5. **Should `duration_minutes` have a validation range?** Adding `ge=1, le=100000` (roughly 69 days max, or ~500000 for a longer bound) would at minimum surface bad LLM outputs as Pydantic validation errors rather than silently passing through. But choosing the right max requires knowing the intended use envelope. What is the longest duration the ComBase growth models are valid for?

6. **Is there a test that would catch this regression?** All existing integration tests in `tests/integration/test_full_pipeline.py` mock the semantic parser, so they never exercise the LLM's unit conversion. A live integration test (or benchmark test) would be needed to catch duration regressions. Is that acceptable, or should a unit-level approach be used (e.g. snapshot tests of the extraction model's output)?
