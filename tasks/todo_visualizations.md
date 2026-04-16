# Benchmark Visualization UI — Phased Implementation Plan

Source spec: `specs/visualization_specs.md`

Each phase is sized to complete and verify independently. Run
`streamlit run benchmarks/visualizations/app.py` after each phase.

---

## Phase 0: Scaffolding & entry point

**Goal:** App launches, shows an empty landing page, sidebar branding works.

**Tasks:**
- Create directory tree: `benchmarks/visualizations/{pages,lib}/`
- Add empty `__init__.py` where needed (none required for Streamlit pages).
- Create `app.py` with `st.set_page_config(layout="wide")`, title,
  sidebar branding (project name + short description).
- Add `streamlit` and `plotly` to `requirements.txt` (or pyproject) if
  not already present.

**Tests / verification:**
- `streamlit run benchmarks/visualizations/app.py` launches with no errors.
- Sidebar shows the project name.
- Page shows a placeholder headline.

---

## Phase 1: Data loader library (`lib/data_loader.py`)

**Goal:** Pure functions to load results from disk, independent of UI.

**Tasks:**
- Implement all functions per spec §"lib/data_loader.py":
  - `load_latest_results(experiment_id)`
  - `load_run_by_timestamp(experiment_id, timestamp)`
  - `list_available_runs(experiment_id)`
  - `list_experiments_with_results()`
  - `load_config_models()` (imports `benchmarks.config`)
- All functions return `None` / empty list gracefully when files are missing.

**Tests:**
- Unit tests `tests/unit/test_viz_data_loader.py`:
  - Missing experiment dir → `(None, None)`.
  - Malformed JSON → warning + `None`, no crash.
  - `list_experiments_with_results()` returns expected entry when
    `latest.json` exists (use tmp_path fixtures with fake results).
  - `list_available_runs` sorts newest first by timestamp.
- Run against real `exp_3_3_model_comparison` results if present.

---

## Phase 2: Overview page (`pages/1_overview.py`)

**Goal:** Landing page renders a usable experiment summary with zero
experiments AND with one experiment.

**Tasks:**
- Implement page per spec §"Page 1: Overview".
- Status cards row: count, last run, best model, best cost-efficient.
- Experiment table built from `list_experiments_with_results()`.
- Quick-link buttons (use `st.page_link`).
- "Best cost-efficient" rule: highest accuracy among models with
  `actual_cost_per_call_usd < 0.001`.

**Tests:**
- Manual: fresh repo (no results) shows empty state gracefully.
- Manual: with exp_3_3 results present, cards populate; table shows
  one row; quick-link navigates to Model Comparison.
- Unit test for a helper that computes "best cost-efficient" from a
  sample DataFrame (green/amber/red edge cases).

---

## Phase 3: Charts library (`lib/charts.py`) — chart-by-chart

Build one chart at a time. Each chart gets a standalone "chart preview"
block in a throwaway page (or the model comparison page as it grows)
to render it against real data.

### 3a: `cost_vs_accuracy_scatter`
- Log X axis, threshold lines at 90% and $0.001, quadrant annotations.
- **Test:** renders with real exp_3_3 `latest.csv`; points labeled;
  dashed threshold lines visible.

### 3b: `accuracy_by_tier_bars`
- Grouped bars, x = difficulty tier, color per model.
- **Test:** chart displays Easy/Medium/Hard for each model from
  `summary.tier_accuracy`.

### 3c: `field_accuracy_heatmap`
- Rows = models, cols = fields from `summary.field_accuracy`.
- **Test:** heatmap renders with expected field set; green-to-red scale.

### 3d: `model_type_matrix`
- Pass/fail cell per (model, query with `model_type` in ground truth).
- **Test:** title turns red when any `model_type_ok == false`.

### 3e: `latency_comparison_bars`
- P50 and P95 side-by-side; threshold lines at 3 s and 10 s.
- **Test:** both bars visible for each model; threshold lines labelled.

### 3f: `token_usage_bars`
- Stacked input/output token bars; secondary axis or companion
  cost-per-call chart.
- **Test:** stacks sum equals `total_input_tokens + total_output_tokens`.

**Shared verification for Phase 3:**
- Unit tests where feasible (e.g., assert figure has expected trace count
  and axis titles). Visual checks manual.

---

## Phase 4: Model Comparison page (`pages/2_model_comparison.py`) — section-by-section

Build sections in order. Each section is independently testable by
loading the page.

### 4a: Data wiring + "no results" state
- Load `latest.json` + `latest.csv`; show guidance message with a link
  to the runner page when missing.
- **Test:** delete/rename `latest.json` → page shows friendly message.

### 4b: Section 1 — Run information bar
- Timestamp, model count, query count, runs per query.
- **Test:** values match the JSON metadata.

### 4c: Section 2 — Summary table
- Columns, sort-by-accuracy default, conditional formatting
  (green ≥90 / amber ≥70 / red <70), red background on
  `model_type_accuracy < 100%`, cost format `$0.00XXX`.
- **Test:** introduce a synthetic row with `model_type_accuracy=0.8`
  and confirm red highlight.

### 4d: Section 3 — Cost vs. accuracy scatter (key chart)
- Full width, ~500 px height; legend by tier; size by consistency.
- **Test:** chart renders with real data; thresholds visible.

### 4e: Section 4 — Accuracy-by-tier bars
### 4f: Section 5 — Field accuracy heatmap
### 4g: Section 6 — Model type matrix (prominent placement)
### 4h: Section 7 — Latency comparison
### 4i: Section 8 — Token / cost breakdown
- For each: drop the chart from `lib/charts.py` into the section with a
  short narrative caption.
- **Tests (each):** section renders without error; chart is populated.

### 4j: Section 9 — Per-query deep dive
- Query-id dropdown; per-model row with field checkmarks, accuracy,
  latency; expandable raw JSON (from `queries[].details`).
- **Test:** switching query updates the table; expander shows raw JSON.

### 4k: Section 10 — Auto-generated recommendation
- Compute "quality pick", "production pick", "open-source viable",
  and the trade-off sentence from the summary DataFrame.
- **Tests:** unit test the recommendation helper against:
  - All models fail `model_type_accuracy == 1.0` → production pick is
    `None` with explanatory text.
  - One Tier 4 model at 75% accuracy → open-source "Yes".

---

## Phase 5: Experiment runner library (`lib/experiment_runner.py`)

**Goal:** Subprocess plumbing isolated from the UI.

**Tasks:**
- `get_available_experiments()` scans `benchmarks/experiments/exp_*.py`.
- `check_model_availability(models)` reads API-key env vars per
  provider; flags Ollama models as available if Ollama env is set.
- `run_experiment(...)` builds the `python -m benchmarks.experiments.<id>`
  command and returns a `subprocess.Popen`-style handle so the page can
  stream stdout.

**Tests:**
- Unit: `get_available_experiments` finds `exp_3_3_model_comparison`.
- Unit: `check_model_availability` toggles correctly with monkeypatched
  env vars.
- Integration (optional, gated on API key): `run_experiment` with
  `--runs 1 --models "GPT-4o"` exits 0 and writes a new `latest.json`.

---

## Phase 6: Runner page (`pages/3_run_experiments.py`)

### 6a: Experiment selector + config panel
- Dropdown of experiments from the library.
- Multiselect of models with tier; grey out unavailable keys.
- Runs-per-query input (1–50, default 5).
- Skip-MLflow checkbox.
- Live "X LLM calls / ~Y sec / ~$Z" summary.
- **Tests:** toggling selections updates the computed totals; unavailable
  models cannot be selected.

### 6b: Run button + streaming progress
- `subprocess.Popen` with line-by-line stdout → `st.status` expander.
- Progress bar estimated from models × queries.
- Success/failure banner; "View Results" link to Page 2.
- **Tests:** manual run with `--runs 1 --models "GPT-4o"`; verify stream
  appears and final banner shows status.

### 6c: Run history table
- Rows loaded from timestamped files in the results directory.
- Columns: timestamp, models, best accuracy, total cost.
- Row click loads that run (optionally via query param passed to Page 2).
- **Tests:** after two runs, history has two rows sorted newest first.

---

## Phase 7: Polish & visual design pass

**Tasks:**
- Apply tier colour palette consistently across all charts (spec
  §"Color palette"). Consider adding a `tier` field to each model dict
  in `benchmarks/config.py`.
- Accuracy colour thresholds applied uniformly (green/amber/red).
- Safety-critical banner on Page 2 when any `model_type_ok` is false.
- Sidebar: run selector dropdown (timestamped runs), "Run new" button.
- `st.divider()` / `st.header()` separators per spec §"Layout principles".

**Tests:**
- Manual visual review against §"Visual design".
- Snapshot test (optional): render each chart function with a fixed
  fixture and assert trace/marker colours match the palette.

---

## Phase 8: End-to-end smoke test

**Goal:** Spec §"Testing" checklist passes top-to-bottom.

1. `streamlit run benchmarks/visualizations/app.py` launches clean.
2. Navigate to Model Comparison with no results → friendly message.
3. Run experiment from the runner page with
   `--runs 1 --models "GPT-4o"`.
4. Return to Model Comparison → all sections populated.
5. Sort summary table by each numeric column.
6. Open per-query deep dive; verify raw JSON expander.
7. Overview page shows updated "last run" and "best model".

Document any deviations or follow-ups in `tasks/lessons.md` per the
workflow convention.
