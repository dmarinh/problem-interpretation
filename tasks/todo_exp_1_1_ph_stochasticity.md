# Exp 1.1 pH Stochasticity Visualization — Phased Implementation Plan

Source spec: `specs/SPEC_exp_1_1_ph_stochasticity.md`

Each phase is sized to complete and verify independently. Run
`streamlit run benchmarks/visualizations/app.py` after each phase.

Existing infrastructure reused:
- `lib/data_loader.py::load_latest_results("exp_1_1_ph_stochasticity")` — already works
- `lib/experiment_runner.py::get_available_experiments()` — already scans `exp_*.py`
- `lib/charts.py` — add new chart builders here following existing patterns

---

## Phase 1: Page scaffold, run info & summary table (Sections 1–2)

**Goal:** New page loads data and renders basic info. Validates the data
pipeline end-to-end before building complex charts.

**Tasks:**
- Create `pages/4_ph_stochasticity.py` following the existing page pattern
  (sys.path setup, imports from `lib/`).
- Load results via `load_latest_results("exp_1_1_ph_stochasticity")`.
- Show friendly empty-state message when no results exist.
- **Section 1 — Run information:** `st.metric` cards in a row showing
  temperature, number of runs, number of models, number of foods.
  Extract from the JSON top-level fields.
- **Section 2 — Summary table:** One row per model. Columns: model name,
  overall MAE, overall stdev, foods with boundary crossings, foods with
  safety impact, total cost. Use `st.dataframe` with column config for
  formatting (2 decimal places for floats, $ prefix for cost).
- Add difficulty tier color constants to `lib/charts.py`:
  `DIFFICULTY_COLORS = {"easy": "#2CA02C", "medium": "#FFC107", "hard": "#D62728"}`

**Tests / verification:**
- Manual: page loads with existing `latest.json`, shows 4 metric cards
  and a summary table.
- Manual: delete `latest.json` temporarily — page shows empty-state message.
- Unit test `tests/unit/test_viz_ph_stochasticity.py`:
  - Test helper that builds summary DataFrame from raw JSON (pure function).
  - Test with missing fields in JSON → graceful defaults.

---

## Phase 2: Violin plots — pH distributions (Section 3)

**Goal:** The key chart that visually demonstrates the stochasticity problem.

**Tasks:**
- Add `ph_violin_chart(foods, reference_phs, difficulty_map)` to
  `lib/charts.py`. Uses `plotly.graph_objects.Violin`.
- One violin per food, ordered by increasing stdev (left → right).
- Overlay FDA reference pH as a horizontal dashed line per food
  (use `add_shape` or scatter markers).
- Overlay pH 4.6 boundary as a red horizontal line spanning full chart.
- Color violins by difficulty tier using `DIFFICULTY_COLORS`.
- In the page: if multiple models, add `st.selectbox` to pick a model.
  Filter foods list by selected model before passing to chart builder.
- Use `st.plotly_chart(fig, use_container_width=True)`.

**Tests / verification:**
- Manual: chart renders with real data, violins ordered by stdev,
  reference lines visible, colors match difficulty tiers.
- Unit test in `tests/unit/test_viz_charts.py`:
  - `ph_violin_chart` returns a valid `go.Figure` with correct number
    of traces.
  - Violins are ordered by stdev (check trace x-axis order).
  - pH 4.6 boundary line exists in figure shapes.

---

## Phase 3: MAE bar chart & boundary crossing histograms (Sections 4 & 6)

**Goal:** Two complementary charts: overall accuracy (MAE) and zoomed-in
boundary behavior.

**Tasks:**
- **Section 4 — MAE bar chart:**
  - Add `mae_by_food_chart(foods, difficulty_map, models=None)` to
    `lib/charts.py`.
  - X: food names, Y: MAE, color by difficulty tier.
  - If multiple models: grouped bars (one group per food, one bar per model).
  - Horizontal dashed line at MAE = 0.5 (food-safety relevance threshold).

- **Section 6 — Boundary crossing histograms:**
  - Add `boundary_crossing_histogram(ph_values, food_name, reference_ph)`
    to `lib/charts.py`.
  - Histogram of sampled pH values with vertical red line at pH 4.6.
  - Annotate fraction of samples on each side.
  - In the page: only render for foods where `boundary_crossing_rate > 0`.
  - If no foods cross the boundary, show `st.info("No foods crossed...")`.

**Tests / verification:**
- Manual: MAE chart shows bars colored by difficulty, 0.5 threshold visible.
- Manual: boundary histograms appear only for relevant foods.
- Unit tests in `tests/unit/test_viz_charts.py`:
  - `mae_by_food_chart` produces correct number of bars.
  - `mae_by_food_chart` with multiple models produces grouped bars.
  - `boundary_crossing_histogram` includes vertical line at 4.6.
  - `boundary_crossing_histogram` annotation text includes percentage.

---

## Phase 4: Growth propagation impact chart (Section 5)

**Goal:** The money chart — directly answers whether pH variance changes
safety conclusions. Interactive threshold slider.

**Tasks:**
- Add `growth_propagation_chart(foods, log_threshold)` to `lib/charts.py`.
  - Horizontal bars spanning `[log_increase_min, log_increase_max]` per food.
  - Vertical line at `log_threshold`.
  - Bar color: red if range crosses threshold, green otherwise.
  - Food name labels on Y axis.
  - Sort foods so red bars appear at the top.

- In the page:
  - `st.slider("Log threshold", 0.1, 3.0, 1.0, 0.1)` above the chart.
  - Recompute colors on slider change (no experiment re-run needed).
  - Show `st.metric` with count of safety-impacted foods above the chart.
  - Skip foods without `growth_propagation` data.

**Tests / verification:**
- Manual: move slider — bars recolor in real time, count updates.
- Manual: verify a bar that spans across the threshold line is red.
- Unit tests in `tests/unit/test_viz_charts.py`:
  - `growth_propagation_chart` with bar crossing threshold → red color.
  - `growth_propagation_chart` with bar fully below threshold → green color.
  - Changing `log_threshold` arg changes bar colors without error.

---

## Phase 5: Model comparison & per-food deep dive (Sections 7 & 8)

**Goal:** Multi-model comparison (when available) and single-food drill-down.

**Tasks:**
- **Section 7 — Model comparison** (only rendered if `len(results) > 1`):
  - Side-by-side MAE comparison bar chart (one bar per model).
  - Side-by-side stdev comparison bar chart.
  - Add `model_comparison_bars(models_summary, metric)` to `lib/charts.py`
    or reuse a grouped-bar builder.
  - `st.info` note: "Even the best model has non-zero stdev at temperature > 0."

- **Section 8 — Per-food deep dive:**
  - `st.selectbox` to pick a food from the selected model's food list.
  - Histogram of pH values for that food (reuse/adapt boundary histogram).
  - Reference pH value overlay.
  - Display all raw pH values as a small `st.dataframe`.
  - If `growth_propagation` available: show log increase distribution
    (min/mean/max as bullet points or small bar).
  - Expander with raw LLM responses from `raw_runs` (food name, run index,
    `raw_response`, latency, error).

**Tests / verification:**
- Manual: model comparison charts appear only with multi-model data.
- Manual: food dropdown updates all sub-charts.
- Manual: raw responses expander shows actual LLM text.
- Unit tests:
  - `model_comparison_bars` returns figure with correct number of bars.
  - Deep-dive helper extracts correct food data from results.

---

## Phase 6: Key finding auto-text & runner integration (Section 9 + page 3)

**Goal:** Auto-generated narrative text and ability to launch Exp 1.1 from
the runner page.

**Tasks:**
- **Section 9 — Key finding:**
  - Add `generate_key_finding(results, log_threshold)` pure function
    (in page file or `lib/`).
  - Count foods with safety impact (where growth range crosses threshold).
  - Find worst food (largest `log_increase_range` that crosses threshold).
  - Render templated text per spec:
    - "LLM pH variance changed the safety conclusion for X out of Y..."
    - "RAG grounding eliminates this variance..."
  - Use `st.success` or `st.warning` box depending on whether impacts exist.

- **Runner integration (`pages/3_run_experiments.py`):**
  - Exp 1.1 already appears in the experiment dropdown (auto-scanned).
  - Add experiment-specific parameters when `exp_1_1` is selected:
    - Temperature slider (0.0–1.0, default 0.7).
    - Log threshold slider (0.1–3.0, default 1.0).
  - Pass `--temperature T` and `--log-threshold L` to the command.
  - Update `run_experiment()` in `lib/experiment_runner.py` to accept
    optional `extra_args: dict` parameter, or build a more flexible
    command builder.

**Tests / verification:**
- Manual: key finding text renders correctly, updates when log threshold
  slider changes.
- Manual: select Exp 1.1 in runner page → temperature and threshold
  sliders appear. Run the experiment → streams output.
- Unit tests:
  - `generate_key_finding` with 0 impacts → success message.
  - `generate_key_finding` with N > 0 impacts → includes worst food name
    and correct count.
  - `run_experiment` with extra args includes them in the command string.

---

## Phase 7: Final polish & full test suite

**Goal:** All sections work together. Tests cover edge cases.

**Tasks:**
- Verify all 9 sections render correctly with real data.
- Verify empty-state behavior (no results file).
- Verify single-model vs multi-model rendering.
- Add any missing unit tests identified during prior phases.
- Ensure all chart functions follow the Plotly string-key lesson
  (cast color columns to `str` for `color_discrete_map`).
- Check that safety-critical defaults follow the fail-closed lesson
  (missing `growth_propagation` → skip, not assume safe).
- Run full test suite: `pytest tests/unit/ -v`.

**Tests / verification:**
- `pytest tests/unit/test_viz_charts.py -v` — all new chart tests pass.
- `pytest tests/unit/test_viz_ph_stochasticity.py -v` — all page tests pass.
- `pytest tests/unit/ -v` — no regressions.
- Manual smoke test: navigate all sections, interact with all sliders
  and dropdowns, verify no Streamlit errors in the terminal.
