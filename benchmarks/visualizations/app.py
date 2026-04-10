"""
Visualization: LLM Model Comparison (Experiment 3.3)

Interactive dashboard for exploring model comparison results.
Reads pre-computed results from benchmarks/results/exp_3_3_model_comparison/.

Usage:
    streamlit run benchmarks/visualizations/app.py
"""

import json
import sys
from pathlib import Path

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# Paths
BENCHMARKS_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = BENCHMARKS_ROOT / "results" / "exp_3_3_model_comparison"


def load_results():
    """Load pre-computed results."""
    metrics_path = RESULTS_DIR / "metrics.csv"
    detail_path = RESULTS_DIR / "per_query_detail.csv"
    detail_full_path = RESULTS_DIR / "per_query_detail_full.json"
    meta_path = RESULTS_DIR / "run_metadata.json"

    if not metrics_path.exists():
        return None, None, None, None

    metrics = pd.read_csv(metrics_path)
    detail = pd.read_csv(detail_path) if detail_path.exists() else None
    detail_full = None
    if detail_full_path.exists():
        with open(detail_full_path) as f:
            detail_full = json.load(f)
    meta = None
    if meta_path.exists():
        with open(meta_path) as f:
            meta = json.load(f)

    return metrics, detail, detail_full, meta


def page_model_comparison():
    st.title("Experiment 3.3 — LLM Model Comparison")
    st.markdown(
        "Evaluating candidate LLMs for the semantic parser: "
        "which model best extracts food safety scenario parameters "
        "from natural language?"
    )

    metrics, detail, detail_full, meta = load_results()

    if metrics is None:
        st.warning(
            "No results found. Run the experiment first:\n\n"
            "```\npython -m benchmarks.experiments.exp_3_3_model_comparison\n```"
        )
        return

    # --- Run info ---
    if meta:
        st.caption(
            f"Run: {meta.get('timestamp', '?')} · "
            f"Git: {meta.get('git_commit', '?')} · "
            f"Duration: {meta.get('duration_seconds', 0):.0f}s"
        )

    # --- Summary metrics table ---
    st.header("Summary")

    display_cols = [
        "model", "overall_accuracy", "overall_consistency",
        "schema_compliance", "model_type_accuracy",
        "mean_latency_s", "est_cost_per_call_usd",
    ]
    col_labels = {
        "model": "Model",
        "overall_accuracy": "Accuracy",
        "overall_consistency": "Consistency",
        "schema_compliance": "Schema OK",
        "model_type_accuracy": "Model Type Acc.",
        "mean_latency_s": "Latency (s)",
        "est_cost_per_call_usd": "Cost/call ($)",
    }

    summary_df = metrics[display_cols].rename(columns=col_labels)
    # Format percentages
    for col in ["Accuracy", "Consistency", "Schema OK", "Model Type Acc."]:
        if col in summary_df.columns:
            summary_df[col] = summary_df[col].apply(lambda x: f"{x:.1%}")

    st.dataframe(summary_df, use_container_width=True, hide_index=True)

    # --- Bar chart: selectable metric ---
    st.header("Model Comparison")

    metric_options = {
        "Overall Accuracy": "overall_accuracy",
        "Consistency (reproducibility)": "overall_consistency",
        "Model Type Classification": "model_type_accuracy",
        "Schema Compliance": "schema_compliance",
        "Mean Latency (s)": "mean_latency_s",
        "Cost per Call ($)": "est_cost_per_call_usd",
    }
    selected_label = st.selectbox("Select metric", list(metric_options.keys()))
    selected_col = metric_options[selected_label]

    is_pct = selected_col not in ("mean_latency_s", "est_cost_per_call_usd", "p95_latency_s")
    fig = px.bar(
        metrics.sort_values(selected_col, ascending=False),
        x="model", y=selected_col,
        title=selected_label,
        text_auto=".1%" if is_pct else ".3f",
        color="model",
    )
    fig.update_layout(showlegend=False, yaxis_title=selected_label)
    if is_pct:
        fig.update_yaxis(range=[0, 1], tickformat=".0%")
    st.plotly_chart(fig, use_container_width=True)

    # --- Heatmap: accuracy per model × query ---
    if detail is not None and len(detail) > 0:
        st.header("Accuracy by Query")

        pivot = detail.pivot_table(
            index="query_id", columns="model", values="accuracy", aggfunc="first"
        )
        fig_heat = px.imshow(
            pivot.values,
            x=pivot.columns.tolist(),
            y=pivot.index.tolist(),
            color_continuous_scale="RdYlGn",
            zmin=0, zmax=1,
            aspect="auto",
            title="Field-level accuracy: Models × Queries",
            labels={"color": "Accuracy"},
        )
        fig_heat.update_layout(height=max(400, len(pivot) * 25))
        st.plotly_chart(fig_heat, use_container_width=True)

        # --- Difficulty breakdown ---
        st.header("Accuracy by Difficulty")

        if "difficulty" in detail.columns:
            diff_summary = detail.groupby(["model", "difficulty"])["accuracy"].mean().reset_index()
            fig_diff = px.bar(
                diff_summary,
                x="difficulty", y="accuracy", color="model",
                barmode="group",
                title="Mean accuracy by query difficulty tier",
                text_auto=".0%",
            )
            fig_diff.update_yaxis(range=[0, 1], tickformat=".0%")
            st.plotly_chart(fig_diff, use_container_width=True)

    # --- Model type classification detail ---
    if detail is not None:
        st.header("Model Type Classification (Safety-Critical)")
        st.markdown(
            "Misclassifying growth vs. thermal inactivation reverses the "
            "direction of conservative bias — this is the most dangerous error."
        )

        mt_data = detail[detail["model_type_correct"].notna()].copy()
        if len(mt_data) > 0:
            mt_summary = mt_data.groupby("model")["model_type_correct"].mean().reset_index()
            mt_summary.columns = ["Model", "Classification Accuracy"]
            mt_summary["Classification Accuracy"] = mt_summary["Classification Accuracy"].apply(
                lambda x: f"{x:.0%}"
            )
            st.dataframe(mt_summary, use_container_width=True, hide_index=True)

            failures = mt_data[mt_data["model_type_correct"] == False]
            if len(failures) > 0:
                st.error(f"⚠ {len(failures)} classification errors found:")
                for _, row in failures.iterrows():
                    st.write(
                        f"- **{row['model']}** on query {row['query_id']}: "
                        f"expected `{row.get('model_type_expected', '?')}`, "
                        f"got `{row.get('model_type_actual', '?')}`"
                    )
            else:
                st.success("✓ All models classified all queries correctly.")

    # --- Latency distribution ---
    st.header("Latency")
    if detail is not None and "mean_latency_s" in detail.columns:
        fig_lat = px.box(
            detail, x="model", y="mean_latency_s",
            title="Extraction latency distribution across queries",
            labels={"mean_latency_s": "Latency (seconds)"},
        )
        st.plotly_chart(fig_lat, use_container_width=True)

    # --- Per-query deep dive ---
    if detail_full:
        st.header("Query Deep Dive")
        query_ids = sorted(set(d["query_id"] for d in detail_full))
        selected_qid = st.selectbox("Select query", query_ids)

        query_details = [d for d in detail_full if d["query_id"] == selected_qid]
        for qd in query_details:
            with st.expander(f"{qd['model']} — accuracy {qd['accuracy']:.0%}"):
                if qd.get("field_scores"):
                    scores_df = pd.DataFrame(qd["field_scores"])
                    scores_df["status"] = scores_df["correct"].apply(
                        lambda x: "✓" if x else "✗"
                    )
                    st.dataframe(
                        scores_df[["field_name", "status", "expected", "actual", "notes"]],
                        use_container_width=True, hide_index=True,
                    )


# --- Main app ---

def main():
    st.set_page_config(
        page_title="PTM Benchmarks",
        page_icon="🔬",
        layout="wide",
    )
    page_model_comparison()


if __name__ == "__main__":
    main()
