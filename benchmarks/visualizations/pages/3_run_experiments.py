"""
Page 3: Run Experiments

Experiment selector, model picker, run configuration, streaming output,
and run history. Subprocess plumbing is delegated to lib/experiment_runner.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on sys.path when Streamlit launches this page directly.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd
import streamlit as st

from benchmarks.config import MODELS
from benchmarks.visualizations.lib.data_loader import (
    list_available_runs,
    load_latest_results,
    load_run_by_timestamp,
)
from benchmarks.visualizations.lib.experiment_runner import (
    check_model_availability,
    get_available_experiments,
    run_experiment,
)

# ---------------------------------------------------------------------------
# Helpers (pure — duplicated in test_viz_runner_page.py for unit testing
# because Streamlit pages execute on import and cannot be imported directly)
# ---------------------------------------------------------------------------

_COST_THRESHOLD_USD = 0.001  # matches charts.py COST_THRESHOLD


def estimate_calls(model_names: list[str], runs: int, query_count: int | None) -> str:
    """Total LLM calls = models × runs × queries."""
    if query_count is None:
        return "?"
    return str(len(model_names) * runs * query_count)


def estimate_cost(
    model_names: list[str],
    runs: int,
    query_count: int | None,
    models_config: list[dict],
) -> str:
    """Estimated USD cost across selected models × runs × queries."""
    if query_count is None:
        return "?"
    cost_map = {m["name"]: m.get("cost_per_call", 0.0) for m in models_config}
    total = sum(cost_map.get(name, 0.0) * runs * query_count for name in model_names)
    return f"~${total:.4f}"


def estimate_time(model_names: list[str], runs: int, query_count: int | None) -> str:
    """Rough wall-clock estimate assuming ~5 s average per LLM call."""
    if query_count is None:
        return "?"
    total_calls = len(model_names) * runs * query_count
    total_seconds = total_calls * 5
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"~{minutes}m {seconds}s" if minutes else f"~{seconds}s"


def get_query_count(experiment_id: str | None) -> int | None:
    """Infer query count from the latest run of an experiment.

    Returns None when no results exist yet (first run).
    """
    if not experiment_id:
        return None
    results, _ = load_latest_results(experiment_id)
    if not results or not isinstance(results, list):
        return None
    # results is a non-empty list of dicts at this point
    queries = results[0].get("queries", [])
    return len(queries) or None


def format_timestamp(ts: str | None) -> str:
    """Convert '20260410_113632' → '2026-04-10 11:36:32'."""
    if not ts or len(ts) != 15:
        return "—"
    return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[9:11]}:{ts[11:13]}:{ts[13:15]}"


def model_option_label(model: dict) -> str:
    """Short display label for a model in the multiselect."""
    tier = model.get("tier", 4)
    return f"{model['name']} (T{tier})"


# ---------------------------------------------------------------------------
# Page — 6a: Experiment selector + configuration panel
# ---------------------------------------------------------------------------

st.title("Run Experiments")
st.caption(
    "Select an experiment, configure which models and how many runs, "
    "then launch directly from the browser."
)

st.header("Configuration")

experiments = get_available_experiments()
if not experiments:
    st.warning(
        "No experiments found in `benchmarks/experiments/`. "
        "Add a file matching `exp_*.py` to that directory."
    )
    st.stop()

exp_name_to_meta = {e["name"]: e for e in experiments}
selected_exp_name = st.selectbox(
    "Experiment",
    options=list(exp_name_to_meta.keys()),
    help="Scans benchmarks/experiments/exp_*.py — new files appear automatically.",
)
selected_experiment = exp_name_to_meta[selected_exp_name]

# Model availability — only show models the environment can reach.
try:
    models_with_avail = check_model_availability(MODELS)
except Exception as exc:
    st.error(f"Could not determine model availability: {exc}. Treating all models as unavailable.")
    models_with_avail = [{**m, "available": False} for m in MODELS]

available = [m for m in models_with_avail if m["available"]]
unavailable = [m for m in models_with_avail if not m["available"]]

available_labels = [model_option_label(m) for m in available]
label_to_model = {model_option_label(m): m for m in available}

selected_labels = st.multiselect(
    "Models to test",
    options=available_labels,
    default=available_labels,
    help=(
        "API models appear when their key env var is set. "
        "Ollama models are always listed — they will fail at runtime if the daemon is not running. "
        "Missing-key models are listed below."
    ),
)
selected_models = [label_to_model[lbl] for lbl in selected_labels]
selected_model_names = [m["name"] for m in selected_models]

if unavailable:
    with st.expander(f"{len(unavailable)} model(s) unavailable — missing API keys"):
        for m in unavailable:
            env_var = m.get("api_key_env_var") or "OLLAMA_HOST"
            st.caption(f"**{m['name']}** — set `{env_var}` in `.env`")

col_runs, col_mlflow = st.columns([2, 1])
with col_runs:
    runs = st.slider("Runs per query", min_value=1, max_value=50, value=5)
with col_mlflow:
    no_mlflow = st.checkbox("Skip MLflow logging", value=False)

# Live estimate row
query_count = get_query_count(selected_experiment["id"])
col_calls, col_time, col_cost = st.columns(3)
col_calls.metric(
    "Estimated LLM calls",
    estimate_calls(selected_model_names, runs, query_count),
    help=f"models × runs × queries ({query_count or '?'} queries inferred from last run)",
)
col_time.metric(
    "Estimated time",
    estimate_time(selected_model_names, runs, query_count),
    help="Assumes ~5 s average latency per call",
)
col_cost.metric(
    "Estimated cost",
    estimate_cost(selected_model_names, runs, query_count, MODELS),
    help="Based on cost_per_call values in benchmarks/config.py",
)

st.divider()

# ---------------------------------------------------------------------------
# 6b: Run button + streaming progress
# ---------------------------------------------------------------------------

st.header("Run")

run_disabled = not selected_models
if run_disabled:
    st.warning("Select at least one model to enable the run button.")

if st.button("Run Experiment", disabled=run_disabled, type="primary"):
    with st.status("Running experiment…", expanded=True) as status:
        proc = run_experiment(
            experiment_id=selected_experiment["id"],
            models=selected_model_names,
            runs=runs,
            no_mlflow=no_mlflow,
        )

        # Stream stdout line by line — Popen is synchronous by design;
        # this loop blocks the Streamlit thread until the subprocess exits.
        for line in proc.stdout:
            st.write(line.rstrip())

        proc.wait()

        if proc.returncode == 0:
            status.update(label="Experiment complete!", state="complete", expanded=False)
            st.success("Run finished successfully.")
            st.page_link(
                "pages/2_model_comparison.py",
                label="View Results in Model Comparison",
                icon="🔍",
            )
        else:
            status.update(label="Experiment failed", state="error", expanded=True)
            st.error(
                f"Process exited with code {proc.returncode}. "
                "Check the output above for details, or run the experiment from the "
                "terminal for the full error output."
            )

st.divider()

# ---------------------------------------------------------------------------
# 6c: Run history table
# ---------------------------------------------------------------------------

st.header("Run History")

runs_history = list_available_runs(selected_experiment["id"])

if not runs_history:
    st.caption("No completed runs found for this experiment yet.")
else:
    # Cap at 10 rows to avoid slow loads on large result sets.
    history_rows = []
    for run_info in runs_history[:10]:
        ts = run_info["timestamp"]
        _, run_df = load_run_by_timestamp(selected_experiment["id"], ts)
        if run_df is not None and not run_df.empty:
            try:
                models_str = ", ".join(run_df["model"].tolist())
                best_acc = f"{run_df['accuracy'].max():.1%}"
                # Total cost sums cost_per_call across all models in that run.
                total_cost = run_df["cost_per_call_usd"].sum()
                cost_str = f"${total_cost:.5f}"
            except KeyError:
                models_str = best_acc = cost_str = "—"
        else:
            models_str = best_acc = cost_str = "—"

        history_rows.append(
            {
                "Timestamp": format_timestamp(ts),
                "Models": models_str,
                "Best accuracy": best_acc,
                "Total cost/call": cost_str,
            }
        )

    st.dataframe(
        pd.DataFrame(history_rows),
        use_container_width=True,
        hide_index=True,
    )
    if len(runs_history) > 10:
        st.caption(f"Showing 10 of {len(runs_history)} runs.")
