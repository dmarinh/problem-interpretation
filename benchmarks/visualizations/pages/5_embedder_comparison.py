"""
Page 5: Embedder Comparison (Experiment 2.1)

Narrative flow:
  Run info → Summary table → 2×2 design chart → Stratum definitions →
  Stratum accuracy → Corpus → Per-query deep dive → Recommendation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from benchmarks.config import RESULTS_DIR
from benchmarks.experiments.exp_2_1_embedder_comparison import compute_recommendation
from benchmarks.visualizations.ui.style import apply_ptm_template, inject_css

_EXPERIMENT_ID = "exp_2_1_embedder_comparison"
_GREEN = 0.90
_AMBER = 0.70

_DATASETS_DIR = _PROJECT_ROOT / "benchmarks" / "datasets"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_latest() -> tuple[dict | None, pd.DataFrame | None]:
    exp_dir = RESULTS_DIR / _EXPERIMENT_ID
    json_path = exp_dir / "latest.json"
    csv_path = exp_dir / "latest.csv"

    if not json_path.exists():
        return None, None

    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None, None

    df = None
    if csv_path.exists():
        try:
            df = pd.read_csv(csv_path)
        except Exception:
            pass

    return data, df


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_ts(ts: str | None) -> str:
    if not ts or len(ts) != 15:
        return ts or "—"
    return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[9:11]}:{ts[11:13]}:{ts[13:15]}"


def _acc_style(val: object) -> str:
    if not isinstance(val, (int, float)):
        return ""
    if val >= _GREEN:
        return "background-color: rgba(42, 99, 71, 0.14)"
    if val >= _AMBER:
        return "background-color: rgba(166, 123, 18, 0.12)"
    return "background-color: rgba(184, 74, 46, 0.12)"


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def _design_chart(embedders: list[dict]) -> go.Figure:
    """2x2 bubble chart: x=training_objective, y=top1_accuracy, size=params_m."""
    rows = []
    for e in embedders:
        s = e.get("summary", {})
        rows.append({
            "name":       e["name"],
            "objective":  e.get("training_objective", "general"),
            "dim_label":  f"{e.get('dim', '?')}d",
            "params_m":   e.get("params_m", 1),
            "top1":       s.get("top1_accuracy", 0),
            "baseline":   e.get("is_baseline", False),
        })
    df = pd.DataFrame(rows)

    fig = px.scatter(
        df,
        x="objective",
        y="top1",
        size="params_m",
        color="dim_label",
        text="name",
        hover_data={"params_m": True, "top1": ":.1%"},
        labels={"objective": "Training objective", "top1": "Top-1 accuracy", "dim_label": "Embedding dim"},
        title="2×2 Design: Training objective × Embedding size",
    )
    fig.update_traces(textposition="top center", marker=dict(opacity=0.85))
    fig.update_yaxes(tickformat=".0%", range=[0, 1.05])
    fig.add_hline(y=_GREEN, line_dash="dash", line_color="green",
                  annotation_text="90%", annotation_position="right")
    fig.add_hline(y=_AMBER, line_dash="dot", line_color="orange",
                  annotation_text="70%", annotation_position="right")
    return apply_ptm_template(fig)


def _stratum_bars(embedders: list[dict]) -> go.Figure:
    """Grouped bar chart: accuracy per stratum per embedder."""
    tiers = ["easy", "medium", "hard", "pathogen"]
    fig = go.Figure()

    for e in embedders:
        ta = e.get("summary", {}).get("tier_accuracy", {})
        fig.add_trace(go.Bar(
            name=e["name"],
            x=tiers,
            y=[ta.get(t, 0) for t in tiers],
            text=[f"{ta.get(t, 0):.0%}" for t in tiers],
            textposition="outside",
        ))

    fig.update_layout(
        barmode="group",
        title="Top-1 Accuracy by Difficulty Stratum",
        yaxis=dict(tickformat=".0%", range=[0, 1.15], title="Accuracy"),
        xaxis_title="Stratum",
        legend_title="Embedder",
    )
    return apply_ptm_template(fig)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

inject_css()

st.title("Experiment 2.1 — Embedder Comparison")
st.caption(
    "Does a different sentence-transformer embedder fix known retrieval failures? "
    "2×2 design: small/base × general/retrieval-optimised."
)

# ── Load data ────────────────────────────────────────────────────────────────
data, df = _load_latest()

if data is None:
    st.info(
        "No results found for Experiment 2.1. "
        "Run the experiment first from the **Run Experiments** page, or from the CLI:"
    )
    st.code("python -m benchmarks.experiments.exp_2_1_embedder_comparison", language="bash")
    st.stop()

embedders: list[dict] = data.get("embedders", [])
corpus_meta: dict = data.get("corpus", {})

if not embedders:
    st.error("results JSON present but embedders list is empty.")
    st.stop()

# ── Section 1: Run info ──────────────────────────────────────────────────────
ts = _fmt_ts(data.get("timestamp"))
n_emb = len(embedders)
n_queries = corpus_meta.get("total_queries", "?")
stratum_counts = corpus_meta.get("stratum_counts", {})

col_ts, col_e, col_q, col_s = st.columns(4)
col_ts.metric("Run", ts)
col_e.metric("Embedders", n_emb)
col_q.metric("Queries", n_queries)
col_s.metric(
    "Strata",
    f"easy {stratum_counts.get('easy', 0)} · med {stratum_counts.get('medium', 0)} "
    f"· hard {stratum_counts.get('hard', 0)} · path {stratum_counts.get('pathogen', 0)}",
)

st.divider()

# ── Section 2: Summary table ─────────────────────────────────────────────────
st.header("Embedder Summary")
st.caption("Sorted by top-1 accuracy. Green ≥ 90% · Amber ≥ 70% · Red < 70%.")

if df is not None and not df.empty:
    _COL_MAP = {
        "embedder_name":        "Embedder",
        "dim":                  "Dim",
        "params_m":             "Params (M)",
        "training_objective":   "Objective",
        "top1_accuracy":        "Top-1",
        "top3_accuracy":        "Top-3",
        "gate_pass_rate":       "Gate pass",
        "mean_expected_score":  "Mean score",
        "tier_easy":            "Easy",
        "tier_medium":          "Medium",
        "tier_hard":            "Hard",
        "tier_pathogen":        "Pathogen",
        "load_time_s":          "Load (s)",
        "corpus_embed_time_s":  "Embed (s)",
        "mean_query_latency_ms": "Query (ms)",
    }
    cols_present = [c for c in _COL_MAP if c in df.columns]
    display_df = (
        df[cols_present]
        .rename(columns=_COL_MAP)
        .sort_values("Top-1", ascending=False)
        .reset_index(drop=True)
    )

    pct_cols = [_COL_MAP[c] for c in cols_present
                if c in {"top1_accuracy", "top3_accuracy", "gate_pass_rate",
                         "tier_easy", "tier_medium", "tier_hard", "tier_pathogen"}]
    acc_style_cols = [_COL_MAP[c] for c in cols_present
                      if c in {"top1_accuracy", "tier_easy", "tier_medium",
                                "tier_hard", "tier_pathogen"}]
    fmt: dict[str, str] = {c: "{:.1%}" for c in pct_cols}
    if "Mean score" in display_df.columns:
        fmt["Mean score"] = "{:.4f}"

    styler = display_df.style.format(fmt, na_rep="—")
    if acc_style_cols:
        styler = styler.map(_acc_style, subset=acc_style_cols)
    st.dataframe(styler, use_container_width=True, hide_index=True)
else:
    st.warning("Summary CSV not available.")

st.divider()

# ── Section 3: 2×2 design chart ──────────────────────────────────────────────
st.header("2×2 Design: Training Objective × Embedding Size")
st.caption(
    "Each bubble is one embedder. Size = parameter count. "
    "Colour = embedding dimensionality. "
    "The **medium stratum** is where retrieval-optimised training matters."
)
if len(embedders) >= 2:
    st.plotly_chart(_design_chart(embedders), use_container_width=True)

st.divider()

# ── Section 4: Stratum definitions callout ────────────────────────────────────
st.header("Accuracy by Difficulty Stratum")
st.markdown(
    "**Reading the four difficulty strata:**\n\n"
    "- **Easy** (10 queries): foods that have their own row in the knowledge base — "
    "chicken, white bread, milk, salmon. "
    "*Every embedder should hit ~100%.* "
    "If not, something is wrong with retrieval itself.\n\n"
    "- **Medium** (10 queries): species-level queries like \"turkey\" or \"lamb\" where no "
    "species-specific row exists, but a category row does (`fresh poultry`, `fresh meat`). "
    "*This is the diagnostic stratum* — the production failure mode that motivated this experiment.\n\n"
    "- **Hard** (6 queries): negative controls. Queries with no correct answer in the knowledge base — "
    "turkey pH, lamb pH, made-up foods like \"zarblax burger\". "
    "*The right behaviour is silence: no doc above the confidence gate.* "
    "Any other behaviour means the embedder is grounding values on unrelated docs.\n\n"
    "- **Pathogen** (4 queries): hazard retrieval — chicken, beef, salmon, oysters. "
    "*A sanity check; not a discriminating stratum.* "
    "All embedders should pass; failure here would indicate a broken harness, not a worse embedder."
)

# ── Section 5: Stratum bar chart ──────────────────────────────────────────────
st.plotly_chart(_stratum_bars(embedders), use_container_width=True)

st.divider()

# ── Section 6: Corpus expander ────────────────────────────────────────────────
with st.expander("▸ View the 30 queries and ground truth"):
    try:
        with open(_DATASETS_DIR / "retrieval_queries.json", encoding="utf-8") as _f:
            _raw_queries = json.load(_f).get("queries", [])
        _corpus_df = pd.DataFrame([
            {
                "id":                    q.get("id"),
                "food_description":      q.get("food_description"),
                "field":                 q.get("field"),
                "tier":                  q.get("tier"),
                "production_tier":       q.get("production_tier"),
                "acceptable_food_names": ", ".join(q.get("acceptable_food_names") or []),
                "comment":               q.get("comment", ""),
            }
            for q in _raw_queries
        ])
        st.dataframe(_corpus_df, use_container_width=True, hide_index=True)
    except Exception as _exc:
        st.warning(f"Could not load corpus: {_exc}")

st.divider()

# ── Section 7: Per-query deep dive ────────────────────────────────────────────
st.header("Per-Query Deep Dive")
st.caption("Inspect how each embedder scored a specific query.")

# Collect all query IDs from the first embedder (all share the same corpus).
sample_queries = embedders[0].get("queries", []) if embedders else []
query_ids = [q["query_id"] for q in sample_queries]
query_map = {q["query_id"]: q for q in sample_queries}

if query_ids:
    selected_qid = st.selectbox("Select query", options=query_ids)

    # Show the query row from corpus.
    ref_q = query_map.get(selected_qid, {})
    if ref_q:
        st.markdown(
            f"**Food:** {ref_q.get('food_description')} · "
            f"**Field:** {ref_q.get('field')} · "
            f"**Tier:** {ref_q.get('tier')} / `{ref_q.get('production_tier')}` · "
            f"**Query:** `{ref_q.get('reformulated_query')}`"
        )

    rows = []
    for emb in embedders:
        q = {q2["query_id"]: q2 for q2 in emb.get("queries", [])}.get(selected_qid)
        if q is None:
            continue
        rows.append({
            "Embedder":       emb["name"],
            "Top-1 food":     q.get("top1_food_name") or "—",
            "Top-1 score":    f"{q.get('top1_score', 0):.4f}" if q.get("top1_score") is not None else "—",
            "Expected rank":  q.get("expected_rank") or "—",
            "Expected score": f"{q.get('expected_score', 0):.4f}" if q.get("expected_score") is not None else "—",
            "Correct@1":      "✓" if q.get("correct_at_1") else "✗",
            "Correct@3":      "✓" if q.get("correct_at_3") else "✗",
            "Gate passed":    "✓" if q.get("gate_passed") else "✗",
        })

    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    with st.expander("Top-3 results per embedder"):
        for emb in embedders:
            q = {q2["query_id"]: q2 for q2 in emb.get("queries", [])}.get(selected_qid)
            if q is None:
                continue
            st.subheader(emb["name"])
            top3 = list(zip(
                q.get("top3_food_names", []),
                q.get("top3_doc_ids", []),
            ))
            if top3:
                st.table(pd.DataFrame(top3, columns=["food_name", "doc_id"]))
            else:
                st.caption("No results.")
else:
    st.info("No query data available.")

st.divider()

# ── Section 8: Recommendation ─────────────────────────────────────────────────
st.header("Recommendation")

rec = compute_recommendation(embedders)
action = rec["action"]
baseline = rec["baseline"]
best = rec["best_candidate"]
delta = rec["delta"]
baseline_acc = baseline.get("summary", {}).get("top1_accuracy", 0) if baseline else 0

if action == "baseline_only":
    st.info("Only the baseline was evaluated. Re-run with additional embedders to compare.")
elif action == "no_baseline":
    st.warning("Baseline embedder not found in results. Cannot generate recommendation.")
else:
    best_acc = best.get("summary", {}).get("top1_accuracy", 0) if best else 0

    col_a, col_b = st.columns(2)
    with col_a:
        st.metric(
            "Baseline top-1",
            f"{baseline_acc:.1%}",
            help=baseline["name"] if baseline else "",
        )
    with col_b:
        if best:
            st.metric(
                "Best candidate top-1",
                f"{best_acc:.1%}",
                delta=f"{delta:+.1%}",
                help=best["name"],
            )
        else:
            st.metric("Best candidate", "—", help="All candidates had hard-tier regressions.")

    if action == "no_safe_candidates":
        st.error(
            "All candidate embedders introduced false positives on the hard (negative-control) "
            "stratum. **Do not switch** — a false positive in production means an unrelated doc "
            "clears the confidence gate, causing silent data corruption."
        )
    elif action == "keep_baseline":
        st.info(
            f"No candidate improves on the baseline. "
            f"**Keep all-MiniLM-L6-v2** (current production embedder). "
            f"Best candidate: **{best['name']}** (Δ = {delta:+.1%})."
        )
    else:  # switch
        cost_note = (
            f"Re-embedding the corpus with **{best['name']}** will take "
            f"~{best.get('corpus_embed_time_s', '?')} s and "
            f"requires rebuilding `data/vector_store/` (production ChromaDB)."
        )
        st.success(
            f"**Switch to {best['name']}** — improves top-1 accuracy by **{delta:+.1%}** "
            f"(from {baseline_acc:.1%} → {best_acc:.1%}) "
            f"with no false-positive regressions on the hard stratum."
        )
        st.caption(cost_note)
        st.caption(
            "To rebuild production: update `SENTENCE_TRANSFORMER_MODEL` in `.env`, "
            "then run `python -m cli.rag_admin --clear` and re-ingest."
        )
