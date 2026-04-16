"""
Page 1: Overview

Landing page showing a summary of all benchmark experiments.
Scans the results directory so new experiments appear automatically.
"""

import streamlit as st
import pandas as pd

from benchmarks.visualizations.lib.data_loader import (
    list_experiments_with_results,
    load_latest_results,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def best_cost_efficient_model(df: pd.DataFrame) -> str | None:
    """Highest accuracy among models with cost < $0.001/call.

    Returns model name, or None if no model qualifies.
    """
    if df is None or df.empty:
        return None

    affordable = df[df["cost_per_call_usd"] < 0.001]
    if affordable.empty:
        return None

    best_idx = affordable["accuracy"].idxmax()
    return affordable.loc[best_idx, "model"]


def _format_timestamp(ts: str | None) -> str:
    """Convert '20260410_113632' to '2026-04-10 11:36:32'."""
    if not ts or len(ts) != 15:
        return "—"
    return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[9:11]}:{ts[11:13]}:{ts[13:15]}"


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


st.title("Problem Translation Module — Benchmark Dashboard")

experiments = list_experiments_with_results()
experiments_with_data = [e for e in experiments if e["has_results"]]

# Load summary data for each experiment that has results
experiment_summaries = {}
for exp in experiments_with_data:
    results, df = load_latest_results(exp["experiment_id"])
    if results is not None:
        experiment_summaries[exp["experiment_id"]] = {
            "results": results,
            "df": df,
            "timestamp": exp["latest_timestamp"],
        }

# --- Status cards ---
st.header("At a Glance")

if not experiment_summaries:
    st.info(
        "No benchmark results found yet. Run an experiment first:\n\n"
        "```\npython -m benchmarks.experiments.exp_3_3_model_comparison\n```"
    )
else:
    # Gather cross-experiment stats from whichever experiments have data
    most_recent_ts = max(
        (s["timestamp"] for s in experiment_summaries.values() if s["timestamp"]),
        default=None,
    )

    # Best model and best cost-efficient across all experiments
    best_model_name = None
    best_accuracy = -1.0
    cost_efficient_name = None

    for summary in experiment_summaries.values():
        df = summary["df"]
        if df is None or df.empty:
            continue

        top_idx = df["accuracy"].idxmax()
        if df.loc[top_idx, "accuracy"] > best_accuracy:
            best_accuracy = df.loc[top_idx, "accuracy"]
            best_model_name = df.loc[top_idx, "model"]

        candidate = best_cost_efficient_model(df)
        if candidate is not None:
            cost_efficient_name = candidate

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Experiments with results", len(experiments_with_data))
    col2.metric("Most recent run", _format_timestamp(most_recent_ts))
    col3.metric(
        "Best model",
        best_model_name or "—",
        f"{best_accuracy:.1%}" if best_model_name else None,
    )
    col4.metric("Best cost-efficient", cost_efficient_name or "—")

# --- Experiment results table ---
st.header("Experiments")

if not experiments:
    st.caption("No experiment directories found.")
else:
    rows = []
    for exp in experiments:
        eid = exp["experiment_id"]
        summary = experiment_summaries.get(eid)

        if summary and summary["df"] is not None and not summary["df"].empty:
            df = summary["df"]
            rows.append(
                {
                    "Experiment": eid,
                    "Last run": _format_timestamp(exp["latest_timestamp"]),
                    "Models tested": len(df),
                    "Best accuracy": f"{df['accuracy'].max():.1%}",
                    "Status": "Has results",
                }
            )
        else:
            rows.append(
                {
                    "Experiment": eid,
                    "Last run": "—",
                    "Models tested": 0,
                    "Best accuracy": "—",
                    "Status": "No results",
                }
            )

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# --- Quick links ---
st.header("Quick Links")

st.page_link("pages/2_model_comparison.py", label="Model Comparison (Exp 3.3)", icon="🔍")
