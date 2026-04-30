---
name: Project Architecture & Safety Invariants
description: Core architecture, safety-critical invariants, and canonical patterns discovered during Phase 2–7 reviews + Phase 3 two-tier RAG review
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
- ValueSource enum (current, post Phase 3 two-tier RAG): USER_EXPLICIT, USER_INFERRED, FUZZY_MATCH, RAG_RETRIEVAL, RAG_RETRIEVAL_FALLBACK, CONSERVATIVE_DEFAULT, CLARIFICATION_RESPONSE, CLAMPED_TO_RANGE, CALCULATED
- NOTE: FUZZY_MATCH now present in metadata.py ValueSource enum (was previously missing); RAG_RETRIEVAL_FALLBACK added for Tier 2 per-field queries
- attributed_field on RetrievalResult (metadata.py): None for primary queries, set to field name ("ph"/"water_activity") for Tier 2 fallback queries; drives audit routing in translation.py Priority 1 path
- No confidence numbers emitted in audit response; embedding_score (cosine similarity) is the only numeric score — categorical source tier is the reliability signal
- BiasCorrection model tracks: bias_type, field_name, original_value, corrected_value, correction_reason, correction_magnitude
- StandardizationResult is a plain class (not Pydantic) — used internally only

## Known Pattern Issues Found in Phase 2 (some resolved)
- `_ground_food_properties()` sync call issue: RESOLVED — all retrieval calls now use `asyncio.to_thread()` correctly
- `_extract_food_properties()` ph_max bug: RESOLVED — ph_max only set when is_range=True
- `standardize()` catches bare `except Exception` at payload build — still present, should narrow
- `_extract_food_properties_llm()` catches bare `except Exception` — PARTIALLY RESOLVED: now logs warning before returning; still overbroad but no longer silent
- `LLMClient.health_check()` catches bare `except Exception` — not in scope of recent review

## Two-Tier RAG Architecture (Phase 3, 2026-04-30)
- Tier 1 threshold: food_properties_confidence = 0.70 (primary query, combined pH+aw)
- Tier 2 threshold: food_properties_fallback_confidence = 0.62 (per-field queries, calibrated)
- Tier 2 fires unconditionally for any field still ungrounded after Tier 1
- RetrievalService methods: query_food_properties (Tier 1), query_food_ph (Tier 2), query_food_water_activity (Tier 2) — all sync, called via asyncio.to_thread()
- rag_retrievals dict in _build_field_audit is keyed by query string — duplicate queries would collide; not a current risk since queries are distinct
- test_user_explicit_takes_priority: user provides pH=6.5 but NOT aw; primary returns confident result; Tier 2 aw fallback fires — mock_retrieval for query_food_water_activity NOT set up explicitly in this test (relies on MagicMock auto-return which has has_confident_result=MagicMock(), not False). This is a latent mock-completeness gap.

## Reranker Wiring (Phase N, 2026-04-30)
- CrossEncoderReranker was implemented but never injected into get_retrieval_service(); fixed so create_reranker() is called at singleton init
- create_reranker(enabled=False) returns NoOpReranker (model_name="noop") — NOT None. This means when RERANKER_ENABLED=False, NoOpReranker is still injected, it fires (truthy object), and the audit reports reranker_used="noop" + non-null rerank_scores. The reranker_used="noop" string is disclosed in the audit doc as intentional.
- Top-result threshold gate (line 175, retrieval.py): uses results[0].confidence (embedding score) NOT rerank_score. This is a known semantic gap: a reranker-promoted result below embedding threshold is rejected even if the reranker thinks it is the best match.
- Sort key mixes rerank_score and confidence in the same lambda: when reranker fires, ALL results have non-null rerank_score (NoOp assigns artificial 1.0, 0.99… scores), so the mixing issue only manifests if rerank_score is None on some results and non-None on others from the same query — which shouldn't happen in practice but could theoretically if _apply_reranker returns fewer results than n_results fetch from the store.
- Settings: reranker_enabled (default True) and reranker_model — NOT yet in .env.example
- The async-sync concern: get_retrieval_service() is called from GroundingService.__init__(), which runs synchronously. CrossEncoderReranker.__init__() loads the model synchronously (sentence_transformers). First call blocks the thread but NOT the event loop (init happens before async ground_scenario() is awaited). Not a correctness risk but a latency concern on cold start.

## Benchmark Suite (exp_3_3_model_comparison.py)
- Monkey-patches `litellm.acompletion` globally for token/cost tracking — not thread-safe
- Scores only first valid run against ground truth (valid[0]) — ignores consistency of accuracy across runs
- `score_extraction` range_preserved logic: accepts collapsed-to-bound as True, rejects only midpoint — correct
- Model type classification flagged as SAFETY-CRITICAL in scoring output
- `_token_log` is a module-level list mutated across async runs — race condition if concurrency ever added
- Thermal inactivation default temperature (60°C) is hardcoded in service, not configurable via settings

## Benchmark Visualization — Exp 1.1 pH Violin (Phase 2 findings, updated Phase 8 test review)

### Production code behavior (verified by probing)
- `ph_violin_chart` always adds the Scatter trace, even when all foods have `reference_ph=None` → trace has `x=[], y=[]` (empty, harmless).
- `ph_values=[]` produces a Violin trace with `x=[], y=[]` — Plotly renders nothing but trace still exists in `fig.data`. `ph_values=None` is normalized via `or []` and behaves identically.
- Missing `ph_stats` key entirely: production code uses `f.get("ph_stats", {}).get("stdev", 0.0)` — defaults to 0.0. No crash. Not tested explicitly.
- Unknown `difficulty` value: falls back to `#888888` color via `DIFFICULTY_COLORS.get(difficulty, "#888888")`. Creates its own `legendgroup`. Not tested.
- Equal-stdev foods: Python's `sorted()` is stable — insertion order preserved. Not guaranteed by spec but stable in practice.
- `food_name` missing: falls back to `"?"` string (used as x-category in Violin and in scatter x). Not tested.

### Test coverage gaps found in Phase 8 review
- `test_ph_violin_chart_food_with_no_ph_values_skipped_gracefully`: asserts `len(violins)==1` and `x==[]` but does NOT assert `y==[]`. Degenerate violin is present in trace list — callers iterating `fig.data` see it.
- `test_ph_violin_chart_food_missing_reference_ph_does_not_crash`: checks `y` of scatter but NOT `x`. If code put wrong food name in `x`, the scatter marker would appear over the wrong violin, and the test would still pass.
- `test_ph_violin_chart_empty_foods_does_not_crash`: does not check that the always-present Scatter trace has empty x/y, nor that the hline is still rendered.
- No test for `violinmode="overlay"` — a regression could silently change it to `"group"` or `"stack"`.
- No test for boundary line color (#D62728) — shape y0==y1==4.6 is checked, but color is not.
- No test for unknown/unmapped `difficulty` values (fallback color, unique legendgroup).
- No test for foods with `ph_stats` key entirely absent (exercises the `{}.get("stdev", 0.0)` fallback).
- No test that the Scatter trace is always present (even empty) — structural invariant undocumented.
- Module-level `_FOOD_*` dicts are shared references. `sorted()` in production code returns new list but references original dicts. No mutation risk today (production only reads), but no fixture isolation (no deepcopy/fixture function). If a future implementation wrote back to a food dict, all tests sharing that dict would silently pick up the mutation.

### PH_SAFETY_BOUNDARY constant
- Only used in charts.py hline; one test imports it for shape comparison. No cross-module consistency risk yet.

## Benchmark Visualization — Exp 1.1 Phase 3 (mae_by_food_chart + boundary_crossing_histogram + page sections 4 & 6)

### CRITICAL: fixture docstring/comment error in tests (HIGH severity bug)
- `_PH_SAMPLES_CROSSING = [4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9]`
- Comment on the line reads: `# 4 values ≤ 4.6 (4.3, 4.4, 4.5, 4.6) → 57%; 3 values > 4.6 (4.7, 4.8, 4.9) → 43%` (CORRECT in Phase 3 final code)
- Test `test_fraction_values_are_correct` docstring says `"4 of 7 samples ≤ 4.6 → 57%"` — this is CORRECT and matches production `<=` semantics.
- `test_fraction_values_are_correct` ordering assertion (idx_57 < idx_43) tests the wrong invariant: it checks
  that "57%" appears before "43%" in the merged annotation string, but when annotation text contains BOTH values,
  the index comparison depends on character position across all annotations concatenated with spaces — not on
  which side of the boundary they represent. This is a FRAGILE assertion.

### boundary_crossing_histogram: semantic mismatch between producer and visualizer
- Experiment producer (`exp_1_1_ph_stochasticity.py` line 462-467): A "crossing" is when the LLM returns a value on
  the WRONG side of the boundary relative to the food's reference pH. For acid foods (ref_ph <= 4.6), a crossing is
  a sample where v >= 4.6. For low-acid foods (ref_ph > 4.6), a crossing is v < 4.6.
- Chart visualizer (`boundary_crossing_histogram`): counts n_below = sum(v <= 4.6) and labels it "≤" side, n_above = > side.
  This is a fixed split regardless of which side is "wrong". The fractions shown are therefore NOT the same as
  the boundary_crossing_rate from the experiment — they are a raw split. For low-acid foods, the "below" fraction
  IS the crossing fraction; for acid foods, the "above" fraction is the crossing fraction.
- Impact: the histogram annotation is not wrong per se (it shows a neutral split), but could be misleading.
  Not a correctness bug in the chart math, but a documentation/label gap.

### Page Section 6: st.columns(min(len(crossing_foods), 2)) with 1 food
- `st.columns(1)` returns a list with one element. `cols[0 % 2]` = `cols[0]` — works correctly. No crash.
- Verified safe.

### Page Section 6: first-model-wins deduplication
- Deduplicated by food_name, first model wins. Means if Model A and Model B both have "salsa" with different
  ph_values (different stochasticity), only Model A's salsa histogram is shown. This may hide variance differences.
  Documented as a design choice to verify, not a bug.

### mae_by_food_chart single-model path: silent drop of unknown difficulty
- Foods whose difficulty is not in ("easy","medium","hard") are silently dropped. No warning, no fallback trace.
- Documented in test `test_food_with_unknown_difficulty_is_silently_dropped`. Acceptable if intentional.

### Assertion weakness patterns confirmed in Phase 3 tests
- `test_mae_values_correct`: checks only sorted y-values across all traces — x-label swap bugs would pass
- `test_fraction_annotation_present`: checks for `%` symbol only — passes even on `0% / 0%` output
- `test_reference_ph_line_present_when_provided` in boundary histogram: assertions on color (black) and dash style
  ARE present in Phase 3 (lines 988-989) — previously noted gap is now covered
- `test_all_samples_below_boundary`: asserts `"100%"` is present AND `"0%"` is present — both sides checked
- `test_all_samples_above_boundary`: added in Phase 3, covers the previously noted gap

### Coverage gaps remaining after Phase 3
- No test for multiple foods within the same difficulty tier (food-name ordering within a tier)
- No test for multi-model with different food sets per model (mismatched x-axis per model)
- No test for `reference_ph == PH_SAFETY_BOUNDARY` (both vlines at same x=4.6)
- No test for `showlegend=False` on the histogram chart layout
- No page-level test for Section 6 deduplication logic (first-model-wins behavior)
- No page-level test for `st.columns(1)` single-crossing-food layout

### Safe patterns confirmed
- `add_vline` does produce shapes with `x0 == x1` — vline detection idiom in tests is correct
- `add_hline` produces `y0 == y1 == value` — MAE threshold detection in tests is correct
- `legend_title_text` in `update_layout` maps to `layout.legend.title.text` — legend title assertions correct
- `_make_results` now uses `copy.deepcopy` — fixture isolation is correct
- `load_latest_results` now guards against non-list JSON with isinstance check before returning — previous
  Phase 7 finding about malformed JSON is resolved in data_loader.py

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
