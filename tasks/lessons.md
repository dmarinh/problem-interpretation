# Lessons Learned

Prevention rules collected after corrections. Newest first.

## 2026-04-21 â€” Ensure models used in type hints are imported

**Context:** `app/core/orchestrator.py` used `"GroundedValues"` in a type hint but did not import it. This caused a "Could not find name" error in static analysis/IDEs, even though it was a quoted forward reference.

**Rule:** Always import classes used in type hints, even if they are referenced as strings (forward references). Quoted strings prevent runtime `NameError` for circular dependencies but do not satisfy static analysis if the name is not in the module's scope.

**Prevention:** Check for missing imports even when using forward references. Align imports with the classes used in methods' signatures.

---

## 2026-04-16 â€” Phase 8 smoke-test results and deviations

**Context:** End-to-end smoke test for the benchmark visualization UI
(`streamlit run benchmarks/visualizations/app.py`).

**Automated checks (all pass):**
- 466 unit tests pass (438 app + 28 visualization charts).
- All 7 visualization source files parse without syntax errors.
- `app.py`, all `pages/`, and all `lib/` files are syntactically valid.

**Smoke test checklist status:**

| # | Item | Status |
|---|------|--------|
| 1 | App launches without errors | âœ… Verified (syntax clean, imports resolve) |
| 2 | Model Comparison with no results â†’ friendly message | âœ… Implemented (page 2 shows info + link to runner) |
| 3 | Run experiment `--runs 1 --models "GPT-4o"` | âš  Requires `OPENAI_API_KEY` in `.env` |
| 4 | Model Comparison shows all sections after run | âŒ Blocked â€” Phase 4 not yet implemented |
| 5 | Sort summary table by each numeric column | âŒ Blocked â€” Phase 4 not yet implemented |
| 6 | Per-query deep dive; raw JSON expander | âŒ Blocked â€” Phase 4 not yet implemented |
| 7 | Overview shows updated "last run" and "best model" | âœ… Implemented (overview scans results dir) |

**Root cause of blocked items:** The implementation sequence skipped Phase 4
(Model Comparison full page). Phases completed: 0 â†’ 1 â†’ 2 â†’ 3 â†’ 5 â†’ 6 â†’ 7 â†’ 8.
Phase 4 sections 4aâ€“4k remain as a placeholder stub in
`pages/2_model_comparison.py` (currently shows safety-critical banner + info message).

**Follow-ups required before advisory board demo:**
1. Implement Phase 4 (`pages/2_model_comparison.py`) â€” sections 4aâ€“4k per
   `tasks/todo_visualizations.md`.
2. Run smoke-test items 4â€“6 manually after Phase 4 is complete.
3. If `OPENAI_API_KEY` is unavailable, use `GPT-4o-mini` or any model whose
   key is set; update item 3 accordingly.

**Rule:** When a phased plan has dependencies (Phase 8 requires Phase 4),
flag the blocked items explicitly at Phase 8 entry rather than discovering
them during the smoke test. Check the dependency chain before executing
a final-phase task.

---

## 2026-04-15 â€” Safety-critical defaults must fail closed

**Context:** `benchmarks/visualizations/lib/charts.py::model_type_matrix`
originally used `q.get("model_type_ok", q["field_scores"]["model_type"])`
as the pass/fail source. `field_scores["model_type"]` is a presence marker
(True = the field was scored in ground truth), not a correctness signal.
A malformed result lacking `model_type_ok` would silently render a green
("pass") cell on the safety-critical chart.

**Rule:** For any safety-critical metric (model type classification,
conservative defaults, safety gates), missing data must default to the
worst-case interpretation â€” never borrow a semantically-different field
as a fallback. Use `.get(key, False)` / the spec's conservative default,
not `.get(key, some_other_field)`.

**Applies to:** extractors, orchestrator model-type determination,
provenance scoring, and any chart or report that surfaces safety results.
Mirrors the existing CLAUDE.md rule: "Missing values default to
worst-case for growth."

**Prevention:** Add a unit test that passes a record with the safety
field omitted and asserts the failure path is taken.

---

## 2026-04-15 â€” Plotly Express `color_discrete_map` keys must be strings

**Context:** `cost_vs_accuracy_scatter` passed an integer `tier` column
to `px.scatter` with an integer-keyed `color_discrete_map`. Plotly
Express stringifies integer color values when building the discrete
legend, so the map keys silently did not match and the tier palette
was not applied.

**Rule:** When using `px.scatter(..., color=<col>, color_discrete_map=...)`,
cast the color column to `str` and key the map with strings.

**Prevention:** Render the chart against real data during development
and inspect the legend, not just the figure object.
