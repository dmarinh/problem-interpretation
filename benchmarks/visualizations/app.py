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

from dotenv import load_dotenv

load_dotenv(_PROJECT_ROOT / ".env")

import streamlit as st

from benchmarks.visualizations.lib.data_loader import (
    list_available_runs,
    list_experiments_with_results,
)
from benchmarks.visualizations.lib.experiment_runner import humanize_experiment_id
from benchmarks.visualizations.ui.style import inject_css, logo_as_pil, sidebar_logo


def _fmt_run_ts(ts: str) -> str:
    """Format a run timestamp for the sidebar selectbox label."""
    if len(ts) != 15:
        return ts
    return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[9:11]}:{ts[11:13]}:{ts[13:15]}"


def main():
    st.set_page_config(
        page_title="PTM Benchmarks",
        page_icon=logo_as_pil(),
        layout="wide",
    )

    inject_css()

    # Register pages first — st.navigation() must be called before any
    # st.sidebar.page_link() so URL pathnames are resolved. position="hidden"
    # suppresses the auto-rendered nav block, letting us control sidebar order.
    overview = st.Page(
        "pages/1_overview.py",
        title="Overview",
        icon=":material/dashboard:",
        default=True,
    )
    model_comparison = st.Page(
        "pages/2_model_comparison.py",
        title="Model Comparison",
        icon=":material/bar_chart:",
    )
    run_experiments = st.Page(
        "pages/3_run_experiments.py",
        title="Run Experiments",
        icon=":material/play_circle:",
    )
    ph_stochasticity = st.Page(
        "pages/4_ph_stochasticity.py",
        title="pH Stochasticity",
        icon=":material/science:",
    )
    embedder_comparison = st.Page(
        "pages/5_embedder_comparison.py",
        title="Embedder Comparison",
        icon=":material/compare:",
    )
    embedder_doc_format = st.Page(
        "pages/6_embedder_doc_format.py",
        title="Embedder × Doc Format",
        icon=":material/text_fields:",
    )
    clarification_fire_rate = st.Page(
        "pages/7_clarification_fire_rate.py",
        title="Clarification Fire Rate",
        icon=":material/help_outline:",
    )

    nav = st.navigation(
        [
            overview,
            model_comparison,
            ph_stochasticity,
            embedder_comparison,
            embedder_doc_format,
            clarification_fire_rate,
            run_experiments,
        ],
        position="hidden",
    )

    # ── Sidebar: branding ────────────────────────────────────────────────────
    sidebar_logo()
    st.sidebar.caption(
        "Problem Translation Module — benchmark suite for evaluating LLM models "
        "on food safety scenario extraction."
    )

    st.sidebar.divider()

    # ── Sidebar: navigation ──────────────────────────────────────────────────
    st.sidebar.page_link(
        "pages/1_overview.py", label="Overview", icon=":material/dashboard:"
    )
    st.sidebar.page_link(
        "pages/2_model_comparison.py",
        label="Model Comparison",
        icon=":material/bar_chart:",
    )
    st.sidebar.page_link(
        "pages/4_ph_stochasticity.py",
        label="pH Stochasticity",
        icon=":material/science:",
    )
    st.sidebar.page_link(
        "pages/5_embedder_comparison.py",
        label="Embedder Comparison",
        icon=":material/compare:",
    )
    st.sidebar.page_link(
        "pages/6_embedder_doc_format.py",
        label="Embedder × Doc Format",
        icon=":material/text_fields:",
    )
    st.sidebar.page_link(
        "pages/7_clarification_fire_rate.py",
        label="Clarification Fire Rate",
        icon=":material/help_outline:",
    )
    st.sidebar.page_link(
        "pages/3_run_experiments.py",
        label="Run Experiments",
        icon=":material/play_circle:",
    )

    # ── Sidebar: per-experiment run selectors (auto-discovered) ──────────────
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

    nav.run()


if __name__ == "__main__":
    main()
