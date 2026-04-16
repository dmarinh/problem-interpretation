---
name: Project Architecture & Safety Invariants
description: Core architecture, safety-critical invariants, and canonical patterns discovered during Phase 2–7 reviews
type: project
---

Pipeline: User Query → SemanticParser (LLM) → GroundingService (RAG + rules) → StandardizationService → ComBase engine → Result

**Why:** Safety-critical system — conservative defaults and model-type-aware bias direction are not stylistic preferences; wrong direction on thermal inactivation makes undercooked food look safe.

**How to apply:** Every review must verify both services maintain correct bias direction for all three ModelType values.

## Key Safety Invariants

### Conservative defaults (verified in settings.py)
- Temperature: 25°C (growth), 60°C (thermal inactivation) — hardcoded in service, not from settings
- pH: 7.0 (neutral) — from `settings.default_ph_neutral`
- Water activity: 0.99 (high) — from `settings.default_water_activity`

### Model-type-aware bias direction (standardization_service.py)
- GROWTH / NON_THERMAL_SURVIVAL: UPPER bound for ranges, +5°C bump, ×1.2 duration
- THERMAL_INACTIVATION: LOWER bound for ranges, −5°C bump, ×0.8 duration
- Low-confidence threshold for temp bump: confidence < 0.5 (strict less-than)
- Duration margin only applied when provenance.source == ValueSource.USER_INFERRED

### Range selection (grounding_service.py)
- Same model-type-aware rules applied during grounding (range bound selection)
- GroundingService handles range selection; StandardizationService handles bias correction after grounding
- Both layers must be consistent

## Provenance Tracking
- ValueSource enum: USER_EXPLICIT, USER_INFERRED, RAG_RETRIEVAL, CONSERVATIVE_DEFAULT, CLAMPED_TO_RANGE, CALCULATED, CLARIFICATION_RESPONSE
- NOTE: FUZZY_MATCH enum value is documented in CLAUDE.md but does NOT exist in ValueSource enum in metadata.py — only in the architecture description
- BiasCorrection model tracks: bias_type, field_name, original_value, corrected_value, correction_reason, correction_magnitude
- StandardizationResult is a plain class (not Pydantic) — used internally only

## Known Pattern Issues Found in Phase 2
- `_ground_food_properties()` is NOT async-called correctly: it calls `self._retrieval.query_food_properties()` synchronously (not awaited) — check if RetrievalService is sync or async
- `_extract_food_properties()` regex builder sets ph_max = ph.value when not a range — this creates a range (min=None, max=single_value) that may confuse downstream range selection
- `standardize()` catches bare `except Exception` at payload build — should narrow
- `_extract_food_properties_llm()` catches bare `except Exception` silently — LLM failures swallowed without logging
- `LLMClient.health_check()` catches bare `except Exception`

## Benchmark Suite (exp_3_3_model_comparison.py)
- Monkey-patches `litellm.acompletion` globally for token/cost tracking — not thread-safe
- Scores only first valid run against ground truth (valid[0]) — ignores consistency of accuracy across runs
- `score_extraction` range_preserved logic: accepts collapsed-to-bound as True, rejects only midpoint — correct
- Model type classification flagged as SAFETY-CRITICAL in scoring output
- `_token_log` is a module-level list mutated across async runs — race condition if concurrency ever added
- Thermal inactivation default temperature (60°C) is hardcoded in service, not configurable via settings

## Benchmark Visualization (Phase 7 findings)
- `load_latest_results` return type annotation says `list | None` for first tuple member but actually returns
  whatever `_load_json_safe` returns — which is `dict | list | None`. Malformed JSON as a top-level dict
  would cause `for r in results` and `len(results)` on page 2 to iterate/count dict keys.
- Page 3 `get_query_count` already guards with `isinstance(results, list)` — page 2 does not.
- `st.sidebar.page_link` in app.py is called BEFORE `st.navigation([...])` — may produce Streamlit warnings
  or fail in strict navigation mode.
- `_fmt_run_ts` in app.py truncates seconds from the timestamp label (shows HH:MM, not HH:MM:SS),
  inconsistent with `_format_timestamp` in overview page and page 3 which shows full HH:MM:SS.
- Stale `selected_run` in session_state: if runs exist, user picks one, then results are deleted, the
  session key is never cleared — page 2 calls `load_run_by_timestamp` with stale ts, gets (None, None),
  shows "No results found" rather than falling back to latest.
- Colorscale `0.6999` step approach is semantically correct but the 0.0001 gap is tighter than necessary;
  a value of exactly 0.7 maps to position 0.7 which hits the amber entry correctly.
- `test_field_accuracy_heatmap_colorscale_has_exactly_six_stops` is fragile — any stop addition breaks it.
- test_viz_model_comparison.py mirrored helper is identical to the production expression — if the page
  expression changes without updating the mirror, tests continue to pass against the stale copy.
