"""
PTM Benchmark Dashboard

Entry point for the Streamlit multi-page app.
Usage: streamlit run benchmarks/visualizations/app.py
"""

import sys
from pathlib import Path

# Ensure the project root is on sys.path so `benchmarks.*` imports resolve
# regardless of which directory Streamlit is launched from.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

from benchmarks.visualizations.lib.data_loader import (
    list_available_runs,
    list_experiments_with_results,
)
from benchmarks.visualizations.lib.experiment_runner import humanize_experiment_id


def _fmt_run_ts(ts: str) -> str:
    """Format a run timestamp for the sidebar selectbox label."""
    if len(ts) != 15:
        return ts
    return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[9:11]}:{ts[11:13]}:{ts[13:15]}"


def main():
    st.set_page_config(
        page_title="PTM Benchmarks",
        page_icon="🔬",
        layout="wide",
    )

    # Sidebar branding
    st.sidebar.title("PTM Benchmarks")
    st.sidebar.caption(
        "Problem Translation Module\n\n"
        "Benchmark suite for evaluating LLM models "
        "on food safety scenario extraction."
    )

    # Sidebar: per-experiment run selectors (auto-discovered)
    try:
        experiments_with_results = list_experiments_with_results()
    except Exception:
        experiments_with_results = []

    for exp in experiments_with_results:
        exp_id = exp["experiment_id"]
        if not exp["has_results"]:
            st.session_state[f"selected_run:{exp_id}"] = None
            continue

        runs = list_available_runs(exp_id)
        if len(runs) < 2:
            # Only one run — no selector needed, default to latest.
            st.session_state[f"selected_run:{exp_id}"] = None
            continue

        st.sidebar.divider()
        st.sidebar.subheader(humanize_experiment_id(exp_id))

        run_labels = ["Latest"] + [r["timestamp"] for r in runs]
        selected = st.sidebar.selectbox(
            "Run",
            options=run_labels,
            format_func=lambda ts: "Latest" if ts == "Latest" else _fmt_run_ts(ts),
            key=f"sidebar_run_selector_{exp_id}",
        )
        st.session_state[f"selected_run:{exp_id}"] = (
            None if selected == "Latest" else selected
        )

    overview = st.Page("pages/1_overview.py", title="Overview", icon="📊", default=True)
    model_comparison = st.Page(
        "pages/2_model_comparison.py", title="Model Comparison", icon="🔍"
    )
    run_experiments = st.Page(
        "pages/3_run_experiments.py", title="Run Experiments", icon="▶"
    )
    ph_stochasticity = st.Page(
        "pages/4_ph_stochasticity.py", title="pH Stochasticity", icon="⚗️"
    )

    nav = st.navigation([overview, model_comparison, ph_stochasticity, run_experiments])
    # page_link must come after st.navigation() so the target page is registered.
    st.sidebar.page_link(
        "pages/3_run_experiments.py",
        label="Run new experiment",
        icon="▶",
    )
    nav.run()


if __name__ == "__main__":
    main()
