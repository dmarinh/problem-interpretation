"""
Page 2: Model Comparison (Experiment 3.3)

Section-by-section viewer for the LLM model comparison benchmark.
Narrative flow: Run info → Summary table → Key charts → Deep dive → Recommendation.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd
import streamlit as st

from benchmarks.config import MODELS
from benchmarks.visualizations.lib.charts import (
    accuracy_by_tier_bars,
    cost_vs_accuracy_scatter,
    field_accuracy_heatmap,
    latency_comparison_bars,
    model_type_matrix,
    token_usage_bars,
)
from benchmarks.visualizations.lib.data_loader import (
    load_latest_results,
    load_run_by_timestamp,
)

# Tier lookup for recommendation logic.
_MODEL_TIER: dict[str, int] = {m["name"]: m.get("tier", 4) for m in MODELS}

# Accuracy thresholds (must match spec §Visual design and charts.py constants).
_GREEN = 0.90
_AMBER = 0.70
_PROD_ACCURACY_MIN = 0.80
_OPEN_SOURCE_MIN = 0.70


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_ts(ts: str | None) -> str:
    """Format a run timestamp string for display."""
    if not ts or len(ts) != 15:
        return ts or "—"
    return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[9:11]}:{ts[11:13]}:{ts[13:15]}"


def _acc_style(val: object) -> str:
    """Cell background colour for accuracy values (0–1 range)."""
    if not isinstance(val, (int, float)):
        return ""
    if val >= _GREEN:
        return "background-color: #d4edda"
    if val >= _AMBER:
        return "background-color: #fff3cd"
    return "background-color: #f8d7da"


def _model_type_style(val: object) -> str:
    """Red background when model type accuracy is below 100%."""
    if not isinstance(val, (int, float)):
        return ""
    return "background-color: #f8d7da" if val < 1.0 else ""


def _compute_recommendation(df: pd.DataFrame) -> dict:
    """Derive quality / production / open-source picks from the summary DataFrame.

    Returns a dict with keys: quality, production, open_source_viable, tier4_df.
    Returns an empty dict when the DataFrame is missing required columns.
    """
    if df is None or df.empty or not {"model", "accuracy", "cost_per_call_usd"}.issubset(df.columns):
        return {}

    has_mta = "model_type_accuracy" in df.columns
    has_cons = "consistency" in df.columns

    # Quality: model_type_accuracy == 1.0, then highest accuracy + consistency.
    cands = df.copy()
    if has_mta:
        cands = cands[cands["model_type_accuracy"] >= 1.0]
    if cands.empty:
        quality = None
    else:
        sort_keys = ["accuracy"] + (["consistency"] if has_cons else [])
        quality = cands.sort_values(sort_keys, ascending=False).iloc[0]

    # Production: cheapest model with model_type_accuracy == 1.0 AND accuracy >= 80%.
    prod = df.copy()
    if has_mta:
        prod = prod[prod["model_type_accuracy"] >= 1.0]
    prod = prod[prod["accuracy"] >= _PROD_ACCURACY_MIN]
    production = prod.sort_values("cost_per_call_usd").iloc[0] if not prod.empty else None

    # Open-source: any Tier 4 model with accuracy > 70%.
    tier4 = df[df["model"].map(lambda m: _MODEL_TIER.get(m, 4)) == 4]
    open_source_viable = not tier4.empty and (tier4["accuracy"] > _OPEN_SOURCE_MIN).any()

    return {
        "quality": quality,
        "production": production,
        "open_source_viable": open_source_viable,
        "tier4_df": tier4,
    }


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

st.title("Experiment 3.3 — LLM Model Comparison")

# ── 4a: Data loading ─────────────────────────────────────────────────────────
# Respect sidebar run selection (app.py stores it in session_state).
selected_run = st.session_state.get("selected_run")
if selected_run:
    results, df = load_run_by_timestamp("exp_3_3_model_comparison", selected_run)
else:
    results, df = load_latest_results("exp_3_3_model_comparison")

# Safety-critical banner (Phase 7): any model_type_ok failure → red alert.
# model_type misclassification (GROWTH vs THERMAL_INACTIVATION) reverses the
# sign of bias corrections — a misclassifying model produces optimistic values
# for thermal inactivation scenarios, which is a direct food safety risk.
if results:
    any_failure = any(
        not q.get("model_type_ok", False)
        for r in results
        for q in r.get("queries", [])
        if "model_type" in q.get("field_scores", {})
    )
    if any_failure:
        st.error(
            "**Safety alert: model type classification failures detected.** "
            "One or more models misclassified GROWTH vs THERMAL_INACTIVATION. "
            "Do not use these models for production food safety queries without review. "
            "See the Model Type Matrix section below."
        )

# No-results state.
if results is None:
    st.info(
        "No results found for Experiment 3.3. "
        "Run the experiment first from the **Run Experiments** page."
    )
    st.page_link("pages/3_run_experiments.py", label="Go to Run Experiments", icon="▶")
    st.stop()

# ── 4b: Run information bar ──────────────────────────────────────────────────
model_count = len(results)
queries_list = results[0].get("queries", []) if results else []
query_count = len(queries_list)
runs_per_query = queries_list[0].get("n_valid", "?") if queries_list else "?"
run_label = _fmt_ts(selected_run) if selected_run else "Latest"

col_ts, col_m, col_q, col_r = st.columns(4)
col_ts.metric("Run", run_label)
col_m.metric("Models tested", model_count)
col_q.metric("Queries", query_count)
col_r.metric("Runs per query", runs_per_query)

st.divider()

# ── 4c: Summary table ────────────────────────────────────────────────────────
st.header("Model Summary")
st.caption(
    "Sorted by accuracy (descending). "
    "Green ≥ 90% · Amber ≥ 70% · Red < 70% · "
    "Model Type column turns red when misclassification is detected (safety-critical)."
)

if df is not None and not df.empty:
    # Columns in order of display priority; skip any not present in this run's CSV.
    _COL_MAP = {
        "model": "Model",
        "instructor_mode": "Mode",
        "accuracy": "Accuracy",
        "consistency": "Consistency",
        "model_type_accuracy": "Model Type",
        "schema_compliance": "Schema",
        "latency_p50_s": "P50 (s)",
        "latency_p95_s": "P95 (s)",
        "cost_per_call_usd": "Cost/call",
        "tier_easy": "Easy",
        "tier_medium": "Medium",
        "tier_hard": "Hard",
    }
    cols_present = [c for c in _COL_MAP if c in df.columns]
    display_df = (
        df[cols_present]
        .rename(columns=_COL_MAP)
        .sort_values("Accuracy", ascending=False)
        .reset_index(drop=True)
    )

    # Percentage columns use {:.1%} format; cost and latency get their own formats.
    pct_src = {"accuracy", "consistency", "model_type_accuracy", "schema_compliance",
               "tier_easy", "tier_medium", "tier_hard"}
    acc_style_src = {"accuracy", "consistency", "tier_easy", "tier_medium", "tier_hard"}
    pct_cols = [_COL_MAP[c] for c in cols_present if c in pct_src]
    acc_style_cols = [_COL_MAP[c] for c in cols_present if c in acc_style_src]

    fmt: dict[str, str] = {c: "{:.1%}" for c in pct_cols}
    for src, label, spec in [
        ("cost_per_call_usd", "Cost/call", "${:.5f}"),
        ("latency_p50_s", "P50 (s)", "{:.2f}s"),
        ("latency_p95_s", "P95 (s)", "{:.2f}s"),
    ]:
        if src in cols_present:
            fmt[label] = spec

    styler = display_df.style.format(fmt, na_rep="—")
    if acc_style_cols:
        styler = styler.map(_acc_style, subset=acc_style_cols)
    if "Model Type" in display_df.columns:
        styler = styler.map(_model_type_style, subset=["Model Type"])

    st.dataframe(styler, use_container_width=True, hide_index=True)
else:
    st.warning("Summary CSV not available for this run.")

st.divider()

# ── 4d: Cost vs. accuracy scatter (the key chart) ────────────────────────────
st.header("Cost vs. Accuracy")
st.caption(
    "The key decision chart. Models in the **top-left** quadrant (high accuracy, low cost) "
    "are production candidates. Point size encodes consistency."
)
if df is not None and not df.empty:
    st.plotly_chart(cost_vs_accuracy_scatter(df), use_container_width=True)

st.divider()

# ── 4e: Accuracy by difficulty tier ──────────────────────────────────────────
st.header("Accuracy by Difficulty Tier")
st.caption(
    "Reveals whether cheaper models degrade on harder queries "
    "while performing comparably on easy ones."
)
if df is not None and not df.empty:
    if {"tier_easy", "tier_medium", "tier_hard"}.issubset(df.columns):
        st.plotly_chart(accuracy_by_tier_bars(df), use_container_width=True)
    else:
        st.info("Tier accuracy data not available in this run's CSV.")

st.divider()

# ── 4f: Field accuracy heatmap ───────────────────────────────────────────────
st.header("Field-level Accuracy")
st.caption(
    "Rows = models, columns = extraction fields. "
    "Green = 100% · Amber = 70–90% · Red < 70%."
)
st.plotly_chart(field_accuracy_heatmap(results), use_container_width=True)

st.divider()

# ── 4g: Model type matrix — safety-critical, given prominent placement ────────
st.header("Model Type Classification — Safety-Critical")
st.caption(
    "Each cell: did the model correctly classify GROWTH vs THERMAL_INACTIVATION "
    "for queries where model type is in the ground truth? "
    "**Any red cell means that model must not be used for production food safety decisions.**"
)
st.plotly_chart(model_type_matrix(results), use_container_width=True)

st.divider()

# ── 4h: Latency comparison ───────────────────────────────────────────────────
st.header("Latency Comparison")
st.caption("P50 = median response time. P95 = tail latency. Interactive threshold: 3 s. Batch: 10 s.")
if df is not None and not df.empty:
    st.plotly_chart(latency_comparison_bars(df), use_container_width=True)

st.divider()

# ── 4i: Token usage and cost ─────────────────────────────────────────────────
st.header("Token Usage and Cost")
st.caption(
    "Stacked input/output token bars reveal whether a model is expensive "
    "because of verbosity (many output tokens) or per-token pricing."
)
if df is not None and not df.empty:
    st.plotly_chart(token_usage_bars(df), use_container_width=True)

st.divider()

# ── 4j: Per-query deep dive ──────────────────────────────────────────────────
st.header("Per-Query Deep Dive")

# Collect the ordered union of query IDs across all models.
_seen_qids: set[str] = set()
query_ids: list[str] = []
for r in results:
    for q in r.get("queries", []):
        qid = q["query_id"]
        if qid not in _seen_qids:
            _seen_qids.add(qid)
            query_ids.append(qid)

if query_ids:
    selected_qid = st.selectbox("Select query", options=query_ids)

    # Collect the union of field_scores keys for this query across all models.
    _seen_fields: set[str] = set()
    all_fields: list[str] = []
    for r in results:
        q = {q["query_id"]: q for q in r.get("queries", [])}.get(selected_qid)
        if q:
            for field in q.get("field_scores", {}):
                if field not in _seen_fields:
                    _seen_fields.add(field)
                    all_fields.append(field)

    # Build one row per model.
    deep_rows = []
    for r in results:
        q = {q2["query_id"]: q2 for q2 in r.get("queries", [])}.get(selected_qid)
        if q is None:
            continue
        row: dict[str, object] = {
            "Model": r["model"],
            "Accuracy": f"{q.get('accuracy', 0):.1%}",
            "Latency (s)": f"{q.get('mean_latency_s', 0):.2f}",
            "Model type": "✓" if q.get("model_type_ok", False) else "✗",
        }
        for field in all_fields:
            row[field] = "✓" if q.get("field_scores", {}).get(field) else "✗"
        deep_rows.append(row)

    if deep_rows:
        st.dataframe(pd.DataFrame(deep_rows), use_container_width=True, hide_index=True)

    with st.expander("Raw extraction JSON"):
        for r in results:
            q = {q2["query_id"]: q2 for q2 in r.get("queries", [])}.get(selected_qid)
            if q is None:
                continue
            st.subheader(r["model"])
            details = q.get("details", [])
            st.json(
                details if details
                else {"note": "No per-run detail records stored for this query."}
            )
else:
    st.info("No query data available.")

st.divider()

# ── 4k: Auto-generated recommendation ───────────────────────────────────────
st.header("Recommendation")

rec = _compute_recommendation(df)

if not rec:
    st.info("Insufficient data to generate a recommendation.")
else:
    quality = rec["quality"]
    production = rec["production"]
    open_source_viable = rec["open_source_viable"]
    tier4_df: pd.DataFrame = rec["tier4_df"]

    col_q, col_p, col_os = st.columns(3)

    with col_q:
        st.subheader("Quality pick")
        if quality is not None:
            st.metric(quality["model"], f"{quality['accuracy']:.1%}")
            st.caption("Highest accuracy among models with 100% model type accuracy.")
        else:
            st.warning("No model achieved 100% model type accuracy.")

    with col_p:
        st.subheader("Production pick")
        if production is not None:
            st.metric(production["model"], f"${production['cost_per_call_usd']:.5f}/call")
            st.caption(
                f"Cheapest model with ≥ 80% accuracy and 100% model type accuracy. "
                f"Accuracy: {production['accuracy']:.1%}."
            )
        else:
            st.warning("No model meets accuracy ≥ 80% with 100% model type accuracy.")

    with col_os:
        st.subheader("Open-source viable")
        if open_source_viable:
            best_os = tier4_df.sort_values("accuracy", ascending=False).iloc[0]
            st.metric("Yes", f"{best_os['accuracy']:.1%}")
            st.caption(f"Best Tier 4 model: **{best_os['model']}**.")
        else:
            st.metric("No", "< 70%")
            st.caption("No self-hosted model exceeds the 70% accuracy threshold.")

    # Trade-off sentence comparing quality and production picks.
    if quality is not None and production is not None:
        if quality["model"] != production["model"]:
            cost_saving = (quality["cost_per_call_usd"] - production["cost_per_call_usd"]) * 1000
            acc_loss = (quality["accuracy"] - production["accuracy"]) * 100
            st.info(
                f"Switching from **{quality['model']}** (quality) to "
                f"**{production['model']}** (production) saves "
                f"**${cost_saving:.2f} per 1,000 calls** "
                f"with a **{acc_loss:.1f}% accuracy reduction**."
            )
        else:
            st.success(
                f"**{quality['model']}** is both the quality and production pick — "
                "no accuracy/cost trade-off required."
            )
