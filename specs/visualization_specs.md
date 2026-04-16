# Benchmark Visualization UI — Specification

## Purpose

This document specifies a web-based dashboard for the Problem Translation
Module benchmark suite. Feed this entire document to Claude Code to build
the implementation.

The dashboard serves two purposes:
1. **View results** from pre-computed benchmark experiments (tables, charts)
2. **Run experiments** directly from the UI (with parameter controls)

The UI is an internal research tool for an AI engineering team working on
food safety predictive microbiology. It must look professional but
prioritize function over aesthetics. It will be demonstrated to an
advisory board.

---

## Technology

- **Framework:** Streamlit (latest stable version)
- **Charts:** Plotly Express (already a Streamlit dependency)
- **Data:** Pandas DataFrames loaded from JSON/CSV files
- **Styling:** Streamlit's built-in theming + minimal custom CSS
- **Experiment execution:** Python subprocess calls to existing scripts

---

## Project structure

All UI code lives inside `benchmarks/visualizations/`. It reads results
from `benchmarks/results/` and runs experiments from
`benchmarks/experiments/`.

```
benchmarks/
├── config.py                                   # Model definitions
├── datasets/
│   └── extraction_queries.json                 # Ground truth
├── experiments/
│   └── exp_3_3_model_comparison.py             # Experiment script
├── results/
│   └── exp_3_3_model_comparison/
│       ├── results_YYYYMMDD_HHMMSS.json        # Full data
│       ├── summary_YYYYMMDD_HHMMSS.csv         # Summary table
│       ├── latest.json                         # Most recent run
│       └── latest.csv
└── visualizations/
    ├── app.py                                  # Entry point: streamlit run benchmarks/visualizations/app.py
    ├── pages/
    │   ├── 1_overview.py                       # Landing page with summary across experiments
    │   ├── 2_model_comparison.py               # Exp 3.3 viewer
    │   └── 3_run_experiments.py                # Experiment runner
    └── lib/
        ├── data_loader.py                      # Load results from files
        ├── charts.py                           # Reusable chart functions
        └── experiment_runner.py                # Subprocess wrapper
```

### Why this structure

- `app.py` is the Streamlit entry point. It sets page config and sidebar branding.
- `pages/` uses Streamlit's native multi-page convention (files prefixed with numbers for ordering).
- `lib/` contains shared utilities. Each file is self-contained and readable.
- One page per experiment (when new experiments are added, add a new page file).
- The runner page is separate from viewer pages — clear separation of "look at results" vs. "generate results".

### Code style rules

- **Favor readability and simplicity over DRY.** If two pages need similar charts
  but with different columns, duplicate the chart code in each page rather than
  creating an abstraction. Shared utilities in `lib/` are for genuinely identical
  logic (loading files, running subprocesses), not for chart variations.
- **Each page file should be understandable on its own.** A developer reading
  `2_model_comparison.py` should not need to read any other file to understand
  what it does.
- **No global state.** Each page loads its own data. Streamlit reruns the entire
  page on every interaction, so stateful patterns break.
- **Comments explain WHY, not WHAT.** The code should be self-documenting for
  WHAT it does. Comments explain domain-specific reasoning (e.g., "model type
  accuracy is weighted highest because misclassification is safety-critical").

---

## Page specifications

### Page 1: Overview (`1_overview.py`)

**Purpose:** Landing page. Shows a summary table of all experiments that have
been run, with key metrics. This is what someone opens first to get the big
picture.

**Content:**

1. **Title:** "Problem Translation Module — Benchmark Dashboard"

2. **Status cards** (one row of metrics):
   - Number of experiments with results
   - Date of most recent run
   - Best model (highest accuracy from exp_3_3)
   - Best cost-efficient model (highest accuracy among models under $0.001/call)

3. **Experiment results table:**
   One row per experiment. Columns: experiment name, last run date, number of
   models tested, best accuracy, status (has results / no results).
   Currently only exp_3_3 exists, but the table should be built from scanning
   the `results/` directory so new experiments appear automatically.

4. **Quick links:** Buttons to navigate to each experiment's detail page.

**Data source:** Scan `benchmarks/results/` for subdirectories. For each,
check if `latest.json` exists. If so, load summary metrics.

---

### Page 2: Model Comparison (`2_model_comparison.py`)

**Purpose:** Detailed viewer for Experiment 3.3 (LLM Model Comparison).
This is the most important page — it's where the model selection decision
is made.

**Layout:** Top-to-bottom narrative flow. The page tells a story:
"Here's what we tested → here's how they compare → here's the recommendation."

**Data source:** Load from `benchmarks/results/exp_3_3_model_comparison/latest.json`
and `latest.csv`. If no results exist, show a message directing to the runner page.

#### Section 1: Run information

Small info bar showing: run timestamp, number of models, number of queries,
runs per query. Loaded from the results JSON metadata.

#### Section 2: Summary table

Full comparison table, one row per model. This is the primary decision tool.

Columns:
- Model name
- Instructor mode (TOOLS / JSON)
- Overall accuracy (%)
- Consistency (%)
- Model type accuracy (%) — highlight in red if < 100%
- Schema compliance (%)
- Latency P50 (seconds)
- Latency P95 (seconds)
- Cost per call (USD)
- Tier accuracy: Easy / Medium / Hard

Formatting:
- Percentages as colored bars or conditional formatting (green > 90%, yellow > 70%, red < 70%)
- Model type accuracy: red background if < 100% (safety-critical)
- Cost: format as "$0.00XXX"
- Sort by accuracy descending by default
- Allow user to sort by clicking column headers

#### Section 3: Cost vs. accuracy scatter plot (THE KEY CHART)

This is the most important visualization. It answers: "Which model gives
the best accuracy for the money?"

- X axis: cost per call (USD), log scale
- Y axis: overall accuracy (0–100%)
- Each point is a model, labeled with model name
- Color by tier (Tier 0/1/2/3/4 using a categorical color scale)
- Point size proportional to consistency (larger = more consistent)
- Horizontal dashed line at 90% accuracy ("acceptable threshold")
- Vertical dashed line at $0.001 ("cost threshold for production")
- The ideal model is in the top-left quadrant (high accuracy, low cost)
- Add annotation: "Frontier zone" (top-right), "Sweet spot" (top-left),
  "Inadequate" (bottom)

This chart should be large (use full width, ~500px height).

#### Section 4: Accuracy by difficulty tier (grouped bar chart)

- X axis: difficulty tier (Easy, Medium, Hard)
- Y axis: accuracy (0–100%)
- One bar per model, grouped by tier
- Color by model
- This shows whether cheap models handle easy queries but fail on hard ones

#### Section 5: Accuracy by field (heatmap)

- Rows: models
- Columns: extraction fields (food_description, model_type, pathogen,
  temperature, duration, range_preserved, duration_ambiguous, is_multi_step)
- Cell color: accuracy (green = 100%, red = 0%)
- This identifies systematic field-level weaknesses per model

#### Section 6: Model type classification (safety-critical)

- Simple pass/fail matrix: models × queries that have model_type in ground truth
- Green = correct, red = wrong
- Title in red if any model has any error
- This is prominently displayed because it's the most important metric

#### Section 7: Latency comparison

- Bar chart: models on X axis, latency on Y axis
- Show both P50 (solid bar) and P95 (outline/lighter bar) side by side
- Horizontal line at 3 seconds ("interactive threshold")
- Horizontal line at 10 seconds ("batch acceptable")

#### Section 8: Token usage and cost

- Stacked bar chart: models on X axis, token count on Y axis
- Two segments per bar: input tokens (darker) and output tokens (lighter)
- Secondary Y axis or separate chart: cost per call
- This shows whether a model is expensive because it's verbose (lots of
  output tokens) or because the per-token price is high

#### Section 9: Per-query deep dive

- Dropdown to select a specific query (shows query text)
- For the selected query, show a table: one row per model, columns for
  each field score (checkmark or X), accuracy, latency
- Expandable detail: show the raw extraction JSON for each model
- This is for debugging specific failures

#### Section 10: Recommendation

- Auto-generated text based on the data:
  - "Recommended for quality: [model with highest (model_type_accuracy, accuracy, consistency)]"
  - "Recommended for production: [cheapest model with model_type_accuracy >= 100% and accuracy >= 80%]"
  - "Open-source viable: [Yes/No based on whether any Tier 4 model exceeds 70% accuracy]"
- Show the key tradeoff: "Switching from [quality] to [production] saves $X per
  1000 calls with Y% accuracy reduction"

---

### Page 3: Run Experiments (`3_run_experiments.py`)

**Purpose:** Execute benchmark experiments directly from the UI.

**Layout:**

#### Section 1: Experiment selector

- Dropdown: select which experiment to run (currently only "3.3 Model Comparison")
- As new experiments are added to `benchmarks/experiments/`, they should appear
  here automatically (scan the experiments directory for `exp_*.py` files)

#### Section 2: Configuration panel

For exp_3_3, show:

- **Models to test:** Multiselect checkbox list, populated from `config.py`'s MODELS list.
  Show model name and tier. Pre-select all models whose API keys are available
  (check env vars). Grey out models whose keys are missing.
- **Runs per query:** Number input, default 5, range 1–50
- **Skip MLflow:** Checkbox, default unchecked
- Show computed summary: "This will make X LLM calls (Y models × Z queries × N runs)"
- Estimated time: rough calculation based on ~2s per API call, ~15s per Ollama call
- Estimated cost: sum of cost_per_call × queries × runs for selected models

#### Section 3: Run button and progress

- Large "Run Experiment" button
- When clicked:
  - Build the command: `python -m benchmarks.experiments.exp_3_3_model_comparison --runs N --models "A,B,C"`
  - Run as subprocess
  - Stream stdout to a Streamlit expander (shows real-time progress)
  - Show a progress bar (estimated from number of models × queries)
  - On completion: show success/failure status
  - Button: "View Results" → navigates to the model comparison page

#### Section 4: Run history

- Table of past runs, loaded from timestamped files in the results directory
- Columns: timestamp, models tested, best accuracy, total cost
- Click a row to load that run's results in the viewer page

---

## Shared library specifications

### `lib/data_loader.py`

```python
def load_latest_results(experiment_id: str) -> tuple[dict | None, pd.DataFrame | None]:
    """Load latest.json and latest.csv for an experiment.
    
    Args:
        experiment_id: e.g., "exp_3_3_model_comparison"
    
    Returns:
        (full_results_dict, summary_dataframe) or (None, None) if no results exist.
    """

def load_run_by_timestamp(experiment_id: str, timestamp: str) -> tuple[dict | None, pd.DataFrame | None]:
    """Load a specific timestamped run."""

def list_available_runs(experiment_id: str) -> list[dict]:
    """List all runs for an experiment.
    
    Returns list of {"timestamp": str, "filepath": Path} sorted newest first.
    """

def list_experiments_with_results() -> list[dict]:
    """Scan results/ directory for experiments that have results.
    
    Returns list of {"experiment_id": str, "has_results": bool, "latest_timestamp": str}.
    """

def load_config_models() -> list[dict]:
    """Load MODELS from config.py. Used by the runner page."""
```

### `lib/charts.py`

Reusable Plotly chart functions. Each returns a `plotly.graph_objects.Figure`.

```python
def cost_vs_accuracy_scatter(df: pd.DataFrame) -> go.Figure:
    """The key decision chart. See Section 3 spec above."""

def accuracy_by_tier_bars(df: pd.DataFrame) -> go.Figure:
    """Grouped bar chart of accuracy by difficulty tier."""

def field_accuracy_heatmap(results: dict) -> go.Figure:
    """Heatmap of field-level accuracy per model."""

def model_type_matrix(results: dict) -> go.Figure:
    """Pass/fail matrix for model type classification."""

def latency_comparison_bars(df: pd.DataFrame) -> go.Figure:
    """P50 and P95 latency side by side."""

def token_usage_bars(df: pd.DataFrame) -> go.Figure:
    """Stacked bar chart of input/output tokens with cost overlay."""
```

### `lib/experiment_runner.py`

```python
def get_available_experiments() -> list[dict]:
    """Scan benchmarks/experiments/ for exp_*.py files.
    
    Returns list of {"id": str, "name": str, "filepath": Path}.
    """

def check_model_availability(models: list[dict]) -> list[dict]:
    """Check which models have their API keys set.
    
    Returns models with added "available" boolean field.
    """

def run_experiment(experiment_id: str, models: list[str], runs: int,
                   no_mlflow: bool = False) -> subprocess.CompletedProcess:
    """Run an experiment as a subprocess.
    
    Builds and executes the command:
        python -m benchmarks.experiments.{experiment_id} --runs N --models "A,B,C"
    
    Returns the completed process (check returncode for success/failure).
    """
```

---

## Visual design

### Color palette

Use a consistent color scheme across all charts:

- **Tier 0 (latest frontier):** deep purple (#7B2D8E)
- **Tier 1 (established frontier):** blue (#1F77B4)
- **Tier 2 (cost-optimized):** green (#2CA02C)
- **Tier 3 (reasoning):** orange (#FF7F0E)
- **Tier 4 (open source):** gray (#7F7F7F)

Assign each model a tier in the visualization by looking at the order in
config.py (first N models are Tier 0, next M are Tier 1, etc.) or by
adding a "tier" field to each model dict in config.py.

### Accuracy coloring

- >= 90%: green (#2CA02C)
- >= 70%: yellow/amber (#FFC107)
- < 70%: red (#D62728)

### Safety-critical highlighting

Any metric related to model type classification uses red (#D62728) for
failures and has a warning icon or banner when any failure exists.

### Layout principles

- Full width for charts (use `st.plotly_chart(fig, use_container_width=True)`)
- Tables use `st.dataframe()` with column config for formatting
- Sections separated by `st.divider()` or `st.header()`
- Sidebar shows: experiment selector (for future multi-experiment support),
  run selector (dropdown of timestamped runs), and a "Run new" button
- Mobile-friendly is not required (desktop internal tool)

---

## Implementation notes for Claude Code

### How to feed this spec to Claude Code

1. Open Claude Code in the project root directory
2. Make sure the `benchmarks/` directory exists with the current files
3. Give Claude Code this prompt:

```
Read the file benchmarks/visualizations/SPEC.md (this document).
Implement the full visualization UI as specified.
Start with app.py, then lib/ files, then pages/ in order.
After each file, verify it runs with `streamlit run benchmarks/visualizations/app.py`.
```

### Key implementation details

- **Streamlit version:** Use `st.set_page_config(layout="wide")` for full-width layout
- **Data loading:** Always check if files exist before loading. Show helpful
  messages when no results are available ("Run the experiment first" with
  a link to the runner page).
- **Chart sizing:** All charts should use `use_container_width=True`
- **Table formatting:** Use `st.dataframe()` with `column_config` parameter
  for percentage formatting, color scales, etc.
- **Subprocess for experiments:** Use `subprocess.Popen` with line-by-line
  stdout reading for real-time progress. Wrap in `st.status()` container.
- **Error handling:** If a results file is malformed or missing fields,
  show a warning and skip that section rather than crashing.
- **Imports:** Put all imports at the top of each file. No lazy imports.

### File reading patterns

The results JSON has this structure (load with `json.load()`):
```python
[
    {
        "model": "GPT-4o",
        "litellm_model": "gpt-4o",
        "instructor_mode": "TOOLS",
        "queries": [
            {
                "query_id": "E1",
                "difficulty": "easy",
                "accuracy": 1.0,
                "field_scores": {"food_description": true, "model_type": true, ...},
                "consistency": 1.0,
                "field_consistency": {"food_description": 1.0, ...},
                "model_type_ok": true,
                "mean_latency_s": 1.2,
                "input_tokens": 523,
                "output_tokens": 287,
                "cost_usd": 0.004,
                "n_valid": 5,
                "n_errors": 0,
                "details": [],
            },
            ...
        ],
        "summary": {
            "overall_accuracy": 0.92,
            "overall_consistency": 0.98,
            "model_type_accuracy": 1.0,
            "schema_compliance": 1.0,
            "latency_p50_s": 1.1,
            "latency_p95_s": 2.3,
            "latency_mean_s": 1.3,
            "total_input_tokens": 10460,
            "total_output_tokens": 5740,
            "actual_cost_per_call_usd": 0.0048,
            "total_cost_usd": 0.48,
            "field_accuracy": {"food_description": 0.95, "model_type": 1.0, ...},
            "tier_accuracy": {"easy": 1.0, "medium": 0.9, "hard": 0.85},
            "model_type_errors": [],
        }
    },
    ...  # one dict per model
]
```

The summary CSV has one row per model with flattened metrics (see experiment
save_results function for exact column names).

### Testing

After building, test with:
1. `streamlit run benchmarks/visualizations/app.py` — should load without errors
2. Navigate to Model Comparison page — should show "no results" message gracefully
3. Run experiment from runner page with `--runs 1 --models "GPT-4o"` (needs API key)
4. Navigate back to Model Comparison — should show charts
5. Check that all charts render and table sorts correctly

---

## Future extensibility

When new experiments are added (e.g., exp_1_1_llm_ph_stochasticity):

1. Create a new page file: `pages/4_ph_stochasticity.py`
2. The overview page auto-discovers it via the results directory scan
3. The runner page auto-discovers it via the experiments directory scan
4. Each page is self-contained — it loads its own data and builds its own charts
5. Shared chart functions in `lib/charts.py` are optional — only add a function
   there if it's genuinely identical across two experiments (not just similar)

This spec does NOT try to build a generic "experiment viewer framework."
Each experiment page is hand-crafted for its specific metrics and visualizations.
This is intentional — the experiments have different structures and different
stories to tell. A generic framework would either be too rigid or too complex.
