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

from benchmarks.visualizations.lib.data_loader import list_available_runs


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

    # Sidebar: run selector for Exp 3.3
    st.sidebar.divider()
    st.sidebar.subheader("Exp 3.3 — Results")
    try:
        runs = list_available_runs("exp_3_3_model_comparison")
    except Exception:
        runs = []

    if runs:
        run_labels = ["Latest"] + [r["timestamp"] for r in runs]
        selected = st.sidebar.selectbox(
            "Run",
            options=run_labels,
            format_func=lambda ts: "Latest" if ts == "Latest" else _fmt_run_ts(ts),
            key="sidebar_run_selector",
        )
        # Store in session_state so Page 2 reads the same selection.
        st.session_state["selected_run"] = None if selected == "Latest" else selected
    else:
        st.sidebar.caption("No runs yet.")
        st.session_state["selected_run"] = None  # clear any stale selection

    overview = st.Page("pages/1_overview.py", title="Overview", icon="📊", default=True)
    model_comparison = st.Page(
        "pages/2_model_comparison.py", title="Model Comparison", icon="🔍"
    )
    run_experiments = st.Page(
        "pages/3_run_experiments.py", title="Run Experiments", icon="▶"
    )

    nav = st.navigation([overview, model_comparison, run_experiments])
    # page_link must come after st.navigation() so the target page is registered.
    st.sidebar.page_link(
        "pages/3_run_experiments.py",
        label="Run new experiment",
        icon="▶",
    )
    nav.run()


if __name__ == "__main__":
    main()
