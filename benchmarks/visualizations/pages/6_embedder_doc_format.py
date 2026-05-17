"""
Page 6: Embedder × Doc Text Format (Experiment 2.2)

Narrative flow (top to bottom):
  Header → Recommendation panel → Cell grid heatmaps → Stratum definitions →
  MRR by stratum → Doc-format effect → Threshold sweep curves →
  Corpus expander → Per-query deep dive → Doc format examples →
  Per-cell threshold table → Further observations
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd
import plotly.colors as pc
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from benchmarks.config import RESULTS_DIR
from benchmarks.experiments.exp_2_2_embedder_doc_format import (
    build_corpus_docs,
    compute_recommendation,
)
from benchmarks.visualizations.ui.style import PTM_COLORWAY, apply_ptm_template, inject_css

_EXPERIMENT_ID = "exp_2_2_embedder_doc_format"
_DATASETS_DIR  = _PROJECT_ROOT / "benchmarks" / "datasets"
_DATA_DIR      = _PROJECT_ROOT / "data" / "rag"

# Semantic palette: format_id → colour
_FORMAT_COLOR = {
    "terse":   PTM_COLORWAY[4],  # neutral gray
    "current": PTM_COLORWAY[0],  # slate-blue (production)
    "verbose": PTM_COLORWAY[2],  # forest green
}

# Embedder short labels (display only)
_EMB_LABEL = {
    "minilm-l6-v2":       "MiniLM-L6 (22M)",
    "bge-small-en-v1.5":  "BGE-small (33M)",
    "bge-base-en-v1.5":   "BGE-base (109M)",
    "mpnet-base-v2":      "mpnet-base (109M)",
}

_MRR_GREEN = 0.85
_MRR_AMBER = 0.70

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60)
def _load_latest() -> dict | None:
    path = RESULTS_DIR / _EXPERIMENT_ID / "latest.json"
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_ts(ts: str | None) -> str:
    if not ts or len(ts) < 8:
        return ts or "—"
    try:
        return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[9:11]}:{ts[11:13]}:{ts[13:15]}"
    except Exception:
        return ts


def _cell_lookup(cells: list[dict]) -> dict[str, dict]:
    return {c["cell_id"]: c for c in cells}


def _fmt_thr(val: float | None, prod: float | None = None, undefined: bool = False) -> str:
    if undefined:
        return "null — undefined"
    if val is None:
        return "—"
    s = f"{val:.2f}"
    if prod is not None and val != prod:
        s += f" (prod: {prod:.2f})"
    return s


# ---------------------------------------------------------------------------
# Chart builders
# ---------------------------------------------------------------------------

def _cell_grid_heatmap(cells: list[dict], metric: str, title: str, fmt: str = ".2f",
                       colorscale: str = "RdYlGn", reversescale: bool = False) -> go.Figure:
    """4 × 3 heatmap (embedder × format) for a single summary metric."""
    embedder_ids = list(dict.fromkeys(c["embedder_id"] for c in cells))
    format_ids   = ["terse", "current", "verbose"]

    z, text = [], []
    for eid in embedder_ids:
        row_z, row_t = [], []
        for fid in format_ids:
            cell = next((c for c in cells if c["embedder_id"] == eid and c["format_id"] == fid), None)
            val  = cell["summary"].get(metric) if cell else None
            row_z.append(val if val is not None else 0.0)
            row_t.append(f"{val:{fmt}}" if val is not None else "—")
        z.append(row_z)
        text.append(row_t)

    y_labels = [_EMB_LABEL.get(eid, eid) for eid in embedder_ids]

    fig = go.Figure(go.Heatmap(
        z=z,
        x=format_ids,
        y=y_labels,
        text=text,
        texttemplate="%{text}",
        colorscale=colorscale,
        reversescale=reversescale,
        showscale=True,
        zmin=0.0,
        zmax=1.0,
        hovertemplate="Embedder: %{y}<br>Format: %{x}<br>Value: %{text}<extra></extra>",
    ))
    fig.update_layout(
        title=title,
        xaxis_title="Doc text format",
        yaxis_title="Embedder",
        height=240,
        margin=dict(l=160, r=24, t=44, b=44),
    )
    return apply_ptm_template(fig)


def _mrr_stratum_bars(cells: list[dict]) -> go.Figure:
    """Grouped bar chart: pure MRR per stratum, coloured by format_id."""
    rows = []
    for c in cells:
        ms = c["summary"].get("mrr_by_stratum", {})
        for stratum in ("easy", "medium", "pathogen"):
            rows.append({
                "cell_id":    c["cell_id"],
                "embedder":   _EMB_LABEL.get(c["embedder_id"], c["embedder_id"]),
                "format_id":  c["format_id"],
                "stratum":    stratum,
                "mrr":        ms.get(stratum) or 0.0,
            })

    df = pd.DataFrame(rows)
    df["cell_id"] = df["cell_id"].astype(str)  # guard against int-colour trap
    df["label"]   = df["format_id"].astype(str)

    fig = px.bar(
        df,
        x="stratum",
        y="mrr",
        color="label",
        barmode="group",
        facet_col="embedder",
        color_discrete_map={k: v for k, v in _FORMAT_COLOR.items()},
        labels={"mrr": "Pure MRR", "stratum": "Stratum", "label": "Format"},
        title="Pure MRR by Difficulty Stratum",
        category_orders={"stratum": ["easy", "medium", "pathogen"],
                         "label":   ["terse", "current", "verbose"]},
    )
    fig.update_yaxes(tickformat=".0%", range=[0, 1.10], title="")
    fig.update_xaxes(title="")
    fig.for_each_annotation(lambda a: a.update(text=a.text.replace("embedder=", "")))
    fig.update_layout(legend_title="Format", height=320)
    return apply_ptm_template(fig)


def _format_effect_chart(cells: list[dict]) -> go.Figure:
    """Grouped bar: x = embedder, 3 bars (terse/current/verbose), y = pure mrr_medium."""
    rows = []
    for c in cells:
        mrr_m = c["summary"].get("mrr_by_stratum", {}).get("medium")
        rows.append({
            "embedder":  _EMB_LABEL.get(c["embedder_id"], c["embedder_id"]),
            "format_id": c["format_id"],
            "mrr_medium": mrr_m if mrr_m is not None else 0.0,
        })

    df = pd.DataFrame(rows)
    df["format_id"] = df["format_id"].astype(str)

    fig = px.bar(
        df,
        x="embedder",
        y="mrr_medium",
        color="format_id",
        barmode="group",
        color_discrete_map={k: v for k, v in _FORMAT_COLOR.items()},
        labels={"mrr_medium": "Pure MRR (medium)", "embedder": "Embedder", "format_id": "Format"},
        title="Format Effect on Medium-Stratum Pure MRR",
        category_orders={"format_id": ["terse", "current", "verbose"]},
    )
    fig.update_yaxes(tickformat=".0%", range=[0, 1.10], title="Pure MRR (medium stratum)")
    fig.update_xaxes(title="")
    fig.update_layout(legend_title="Format", height=340)
    return apply_ptm_template(fig)


def _sweep_chart(cells: list[dict], tier: str, rec_cell_id: str, base_cell_id: str) -> go.Figure:
    """F1 vs threshold sweep for one tier, all cells. Recommended and baseline highlighted."""
    TIER_LABELS = {"tier_2": "Tier 2 (pH / aw queries)", "pathogen_stage_1": "Pathogen stage 1"}
    fig = go.Figure()

    _palette = pc.qualitative.Light24  # 24 distinct colours

    for i, cell in enumerate(cells):
        cal   = cell["summary"].get("threshold_calibration", {}).get(tier, {})
        sweep = cal.get("sweep", [])
        if not sweep:
            continue

        xs = [s["threshold"] for s in sweep]
        ys = [s["f1"]        for s in sweep]
        cid = cell["cell_id"]

        is_rec  = cid == rec_cell_id
        is_base = cid == base_cell_id

        if is_rec:
            colour, width, dash, opacity, layer = PTM_COLORWAY[2], 3, "solid", 1.0, "above"
        elif is_base:
            colour, width, dash, opacity, layer = PTM_COLORWAY[3], 2, "dash",  0.9, "above"
        else:
            colour, width, dash, opacity, layer = _palette[i % len(_palette)], 1, "solid", 0.25, "below"

        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines",
            name=cid,
            line=dict(color=colour, width=width, dash=dash),
            opacity=opacity,
            hovertemplate=f"{cid}<br>threshold=%{{x:.2f}}<br>F1=%{{y:.4f}}<extra></extra>",
            legendgroup=layer,
            showlegend=is_rec or is_base,
        ))

        # Mark the calibrated threshold with a vertical line (rec and baseline only)
        opt = cal.get("optimal_threshold")
        if opt is not None and (is_rec or is_base):
            fig.add_vline(
                x=opt, line_dash="dot",
                line_color=colour,
                annotation_text=f"cal={opt:.2f}",
                annotation_position="top right",
                annotation_font_size=10,
            )

    # FPR ceiling annotation
    fig.add_hline(y=0, line_dash="dot", line_color="rgba(0,0,0,0)")  # invisible, just sets range
    fig.update_layout(
        title=TIER_LABELS.get(tier, tier),
        xaxis=dict(title="Threshold", range=[0.30, 0.90]),
        yaxis=dict(title="F1", range=[0, 1.05], tickformat=".2f"),
        showlegend=True,
        legend=dict(orientation="v", x=1.01, y=1),
        height=320,
    )
    return apply_ptm_template(fig)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

inject_css()

st.title("Experiment 2.2 — Embedder × Doc Text Format")
st.caption(
    "2-factor retrieval benchmark: 4 embedders × 3 doc text formats = 12 cells. "
    "Primary metric: pure MRR (rank-based, threshold-invariant). "
    "Hard-stratum queries are negative controls — the right behaviour is silence."
)

# ── Load data ─────────────────────────────────────────────────────────────────
data = _load_latest()

if data is None:
    st.info(
        "No results found for Experiment 2.2. Run the experiment or recalibrate first:\n\n"
        "```bash\n"
        "python -m benchmarks.experiments.exp_2_2_embedder_doc_format --recalibrate\n"
        "```"
    )
    st.stop()

cells: list[dict]  = data.get("cells", [])
corpus_meta: dict  = data.get("corpus", {})
rec: dict          = data.get("recommendation") or compute_recommendation(cells)

if not cells:
    st.error("Results JSON is present but the cells list is empty.")
    st.stop()

cell_by_id = _cell_lookup(cells)

# ── Section 1: Header ─────────────────────────────────────────────────────────
ts       = _fmt_ts(data.get("timestamp"))
n_cells  = len(cells)
n_q      = corpus_meta.get("total_queries", "?")
sc       = corpus_meta.get("stratum_counts", {})

col_ts, col_c, col_q, col_s = st.columns(4)
col_ts.metric("Run",      ts)
col_c.metric("Cells",     f"4 embedders × 3 formats = {n_cells}")
col_q.metric("Queries",   n_q)
col_s.metric(
    "Strata",
    f"easy {sc.get('easy', 0)} · med {sc.get('medium', 0)} "
    f"· hard {sc.get('hard', 0)} · path {sc.get('pathogen', 0)}",
)

st.divider()

# ── Section 2: Recommendation panel ──────────────────────────────────────────
st.header("Recommendation")

action = rec.get("action", "")
base_cid = (rec.get("baseline") or {}).get("cell_id")
best_cid = (rec.get("best_cell") or {}).get("cell_id")
delta_mrr = rec.get("delta_mrr")

_ACTION_ICONS = {
    "switch":          ("✅", "green"),
    "keep_baseline":   ("➡️", "blue"),
    "no_viable_cells": ("⚠️", "orange"),
    "baseline_only":   ("ℹ️", "gray"),
    "no_baseline":     ("❌", "red"),
}
icon, _colour = _ACTION_ICONS.get(action, ("ℹ️", "gray"))

if action in ("baseline_only", "no_baseline"):
    st.info(f"{icon} {action.replace('_', ' ').title()} — see terminal output for details.")
else:
    base_cell = cell_by_id.get(base_cid or "", {})
    base_sum  = base_cell.get("summary", {})
    base_mrr  = (rec.get("baseline") or {}).get("mrr") or base_sum.get("mrr") or 0.0

    if action == "switch" and best_cid:
        best_cell = cell_by_id.get(best_cid, {})
        best_sum  = best_cell.get("summary", {})
        best_mrr  = (rec.get("best_cell") or {}).get("mrr") or best_sum.get("mrr") or 0.0

        base_mrr_m = base_sum.get("mrr_by_stratum", {}).get("medium")
        best_mrr_m = best_sum.get("mrr_by_stratum", {}).get("medium")
        delta_m    = (
            round(best_mrr_m - base_mrr_m, 4)
            if best_mrr_m is not None and base_mrr_m is not None else None
        )

        st.success(f"{icon} **Verdict: Switch to `{best_cid}`**")

        rc1, rc2, rc3, rc4 = st.columns(4)
        rc1.metric("Baseline (pure MRR)", f"{base_mrr:.3f}", help=base_cid)
        rc2.metric(
            "Recommended (pure MRR)", f"{best_mrr:.3f}",
            delta=f"{delta_mrr:+.4f}" if delta_mrr is not None else None,
            help=best_cid,
        )
        rc3.metric(
            "Δ mrr_medium", f"{delta_m:+.3f}" if delta_m is not None else "—",
            help="Pure MRR on medium-difficulty queries (species probes)"
        )
        rc4.metric("Viable", "PARTIAL", help="tier_1 FPR is undefined (no negatives route through tier_1)")

        # Calibrated thresholds for recommended cell
        rec_cal = best_sum.get("threshold_calibration", {})
        t1  = rec_cal.get("tier_1", {})
        t2  = rec_cal.get("tier_2", {})
        pa  = rec_cal.get("pathogen_stage_1", {})

        def _thr_md(tier_label: str, cal: dict) -> str:
            prod = cal.get("production_threshold")
            prod_s = f"{prod:.2f}" if prod is not None else "?"
            if cal.get("viable") is None:
                return (
                    f"**{tier_label}:** `null — undefined`  \n"
                    f"<small>No negative controls in this tier on this corpus. "
                    f"FPR is 0/0 (indeterminate). Production: {prod_s}</small>"
                )
            opt = cal.get("optimal_threshold")
            opt_s = f"{opt:.2f}" if opt is not None else "—"
            f1_s  = f"{cal['f1_at_optimal']:.4f}" if cal.get("f1_at_optimal") is not None else "—"
            fpr_s = f"{cal['fpr_at_optimal']:.0%}" if cal.get("fpr_at_optimal") is not None else "—"
            return (
                f"**{tier_label}:** `{opt_s}`  \n"
                f"<small>Production: {prod_s} · F1 at calibrated: {f1_s} · FPR: {fpr_s}</small>"
            )

        st.markdown("**Calibrated thresholds for recommended cell:**")
        thr_col1, thr_col2, thr_col3 = st.columns(3)
        thr_col1.markdown(_thr_md("tier_1",   t1), unsafe_allow_html=True)
        thr_col2.markdown(_thr_md("tier_2",   t2), unsafe_allow_html=True)
        thr_col3.markdown(_thr_md("pathogen", pa), unsafe_allow_html=True)

        st.caption(
            "**Cost:** Re-embed corpus with verbose doc format; rebuild ChromaDB collection; "
            "recalibrate production threshold on the new score distribution before deployment."
        )
        st.caption(
            "**Tiebreak note:** mpnet-base-v2_verbose has marginally higher pure MRR but the "
            "decision rule selects the smaller model within the 0.02 ΔMRR band "
            "(22M vs 110M parameters)."
        )

    elif action == "keep_baseline":
        st.info(
            f"{icon} **Keep baseline (`{base_cid}`)** — no candidate improves pure MRR "
            f"while meeting all viability criteria. "
            f"Best candidate delta: {delta_mrr:+.4f}" if delta_mrr is not None else "."
        )

    elif action == "no_viable_cells":
        closest = rec.get("closest_cell", {})
        st.warning(
            f"{icon} **No viable cells.** Closest candidate: `{closest.get('cell_id', '?')}` — "
            f"{closest.get('failure_reason', '?')}. "
            f"{rec.get('note', '')}"
        )

st.divider()

# ── Section 3: Cell grid heatmaps ─────────────────────────────────────────────
st.header("Cell Grid — Pure MRR and Hard FPR")
st.caption(
    "Each cell is one (embedder × format) combination. "
    "Green = high MRR / zero FPR. Red = low MRR / high FPR. "
    "Hard FPR should be 0.00 — any non-zero value means the system grounded values "
    "from an unrelated document."
)

hm1, hm2 = st.columns(2)
with hm1:
    st.plotly_chart(
        _cell_grid_heatmap(cells, "mrr", "Pure MRR", fmt=".3f"),
        use_container_width=True,
    )
with hm2:
    st.plotly_chart(
        _cell_grid_heatmap(cells, "hard_fpr", "Hard FPR (negatives)",
                           fmt=".3f", colorscale="RdYlGn", reversescale=True),
        use_container_width=True,
    )

st.divider()

# ── Section 4: Stratum definitions callout ────────────────────────────────────
st.header("Accuracy by Difficulty Stratum")
st.markdown(
    "**Reading the four difficulty strata:**\n\n"
    "- **Easy** — foods that have their own row in the knowledge base: chicken, white bread, "
    "salmon. *Every cell should hit ~100% pure MRR. Failures here indicate a retrieval regression.*\n\n"
    "- **Medium** — species-level queries like 'turkey' or 'lamb' where no species-specific row "
    "exists, but a category row does (`fresh poultry`, `fresh meat`). "
    "*This is the diagnostic stratum.* Pure MRR separates embedders that retrieve the right "
    "category doc from those that miss it entirely.\n\n"
    "- **Hard** — negative controls. Queries with no correct answer in the knowledge base — "
    "turkey pH, lamb pH, made-up foods like `zarblax burger`. "
    "*The right behaviour is silence: no doc above the confidence gate.* "
    "Shown as `hard_negative_control_pass_rate` in the threshold table below.\n\n"
    "- **Pathogen** — hazard retrieval (chicken, beef, salmon, oysters). "
    "*A sanity check, not a discriminating stratum.* All cells should pass."
)

# ── Section 5: MRR by stratum ─────────────────────────────────────────────────
st.plotly_chart(_mrr_stratum_bars(cells), use_container_width=True)
st.caption(
    "Pure MRR shows where the canonical doc ranks in the top-K — independent of threshold. "
    "Compare this with mrr_gate_filtered (threshold-dependent) in the threshold table to see "
    "how much of the medium-stratum MRR gap is a gating issue vs a retrieval issue."
)

st.divider()

# ── Section 6: Doc text format effect ────────────────────────────────────────
st.header("Doc Text Format Effect on Medium-Stratum MRR")
st.plotly_chart(_format_effect_chart(cells), use_container_width=True)
st.caption(
    "Format moves pure MRR on medium-difficulty queries by 0.20–0.30 across embedders. "
    "The recommendation pairs the smallest model (MiniLM-L6, 22M params) with its best format "
    "(verbose), matching the per-embedding performance of larger models at a fraction of the cost."
)

st.divider()

# ── Section 7: Threshold sweep curves ─────────────────────────────────────────
st.header("Threshold Calibration Sweep")
st.caption(
    "FPR-constrained calibration: argmax F1 subject to FPR ≤ 5%. "
    "One line per cell. Recommended cell (solid green) and baseline (dashed amber) are labelled. "
    "tier_1 is omitted — all 12 cells have no negative controls in that tier (FPR = 0/0, undefined). "
    "pathogen curves are shown but have no calibrated threshold marker for the same reason."
)

sw1, sw2 = st.columns(2)
_rec_cid  = best_cid or ""
_base_cid = base_cid or ""
with sw1:
    st.plotly_chart(
        _sweep_chart(cells, "tier_2", _rec_cid, _base_cid),
        use_container_width=True,
    )
with sw2:
    st.plotly_chart(
        _sweep_chart(cells, "pathogen_stage_1", _rec_cid, _base_cid),
        use_container_width=True,
    )

st.divider()

# ── Section 8: Corpus expander ────────────────────────────────────────────────
with st.expander("▸ View the 60 queries and ground truth"):
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

# ── Section 9: Per-query deep dive ────────────────────────────────────────────
st.header("Per-Query Deep Dive")
st.caption(
    "Inspect how each cell scored a specific query. "
    "Default: **M01 (turkey)** — rank #1 doc is correct, but the cosine score sits below "
    "the production threshold. Pure MRR = 1.0; gate-filtered MRR = 0.0."
)

# Collect all query IDs (from the first cell; all share the same corpus)
_sample_cell = cells[0] if cells else {}
_all_qids    = [q["query_id"] for q in _sample_cell.get("queries", [])]

# Default to first medium-stratum query if present
_medium_qids = [
    q["query_id"] for q in _sample_cell.get("queries", []) if q.get("tier") == "medium"
]
_default_qid = _medium_qids[0] if _medium_qids else (_all_qids[0] if _all_qids else None)

if _all_qids:
    _sel_qid = st.selectbox(
        "Select query", options=_all_qids,
        index=_all_qids.index(_default_qid) if _default_qid in _all_qids else 0,
    )

    # Show query metadata from the first cell
    _ref_q = {q["query_id"]: q for q in _sample_cell.get("queries", [])}.get(_sel_qid, {})
    if _ref_q:
        st.markdown(
            f"**Food:** {_ref_q.get('food_description')} · "
            f"**Field:** {_ref_q.get('field')} · "
            f"**Tier:** {_ref_q.get('tier')} / `{_ref_q.get('production_tier')}` · "
            f"**Query:** `{_ref_q.get('reformulated_query', '—')}`"
        )

    # Build per-cell comparison table
    _dive_rows = []
    for cell in cells:
        q_map = {q["query_id"]: q for q in cell.get("queries", [])}
        q = q_map.get(_sel_qid)
        if q is None:
            continue
        _dive_rows.append({
            "Cell":           cell["cell_id"],
            "Format":         cell["format_id"],
            "Top-1 food":     q.get("top1_food_name") or "—",
            "Top-1 score":    f"{q['top1_score']:.4f}" if q.get("top1_score") is not None else "—",
            "Expected rank":  q.get("expected_rank") or "—",
            "Expected score": f"{q['expected_score']:.4f}" if q.get("expected_score") is not None else "—",
            "Pure RR":        f"{q['pure_reciprocal_rank']:.4f}" if q.get("pure_reciprocal_rank") is not None else "—",
            "GF RR":          f"{q['reciprocal_rank']:.4f}" if q.get("reciprocal_rank") is not None else "—",
            "Gate passed":    "✓" if q.get("gate_passed") else "✗",
        })

    if _dive_rows:
        st.dataframe(pd.DataFrame(_dive_rows), use_container_width=True, hide_index=True)
        st.caption("Pure RR = pure reciprocal rank (rank-based). GF RR = gate-filtered (threshold-dependent).")

    with st.expander("Top-3 results per cell"):
        for cell in cells:
            q_map = {q["query_id"]: q for q in cell.get("queries", [])}
            q = q_map.get(_sel_qid)
            if q is None:
                continue
            st.subheader(cell["cell_id"])
            top3 = q.get("top3_food_names", [])
            if top3:
                st.table(pd.DataFrame({"rank": range(1, len(top3)+1), "food_name": top3}))
            else:
                st.caption("No results.")
else:
    st.info("No query data available.")

st.divider()

# ── Section 10: Doc text format examples ──────────────────────────────────────
with st.expander("▸ Doc text format examples (chicken)"):
    st.caption(
        "The three formats control what text gets embedded for each knowledge-base row. "
        "Verbose adds grammatical structure; terse strips it. "
        "The experiment measures whether embedding quality is sensitive to this choice."
    )
    try:
        _example_rows = []
        for _fmt in ["terse", "current", "verbose"]:
            _docs = build_corpus_docs(_fmt, _DATA_DIR)
            _doc  = next(
                (d for d in _docs if d["metadata"].get("food_name") == "chicken"), None
            )
            if _doc:
                _example_rows.append({"Format": _fmt, "Embedded text": _doc["text"]})
        if _example_rows:
            st.table(pd.DataFrame(_example_rows))
    except Exception as _exc:
        st.warning(f"Could not build format examples: {_exc}")

st.divider()

# ── Section 11: Per-cell threshold table ──────────────────────────────────────
st.header("Per-Cell Calibration Thresholds")
st.caption(
    "Calibrated = highest-F1 threshold where hard-stratum FPR ≤ 5%. "
    "null — undefined = no negative-control queries route through this tier on this corpus "
    "(FPR is 0/0, not 0). Production thresholds shown for reference."
)

_thr_rows = []
for cell in cells:
    tc = cell["summary"].get("threshold_calibration", {})
    t1 = tc.get("tier_1", {})
    t2 = tc.get("tier_2", {})
    pa = tc.get("pathogen_stage_1", {})

    _thr_rows.append({
        "Cell":               cell["cell_id"],
        "Embedder":           _EMB_LABEL.get(cell["embedder_id"], cell["embedder_id"]),
        "Format":             cell["format_id"],
        "Viable":             cell["summary"].get("viable_at_calibrated_threshold", "?"),
        "hard_ncpr":          cell["summary"].get("hard_negative_control_pass_rate"),
        "tier_1 (cal)":       _fmt_thr(None, t1.get("production_threshold"), undefined=t1.get("viable") is None),
        "tier_2 (cal)":       _fmt_thr(t2.get("optimal_threshold"), t2.get("production_threshold"), undefined=t2.get("viable") is None),
        "pathogen (cal)":     _fmt_thr(pa.get("optimal_threshold"), pa.get("production_threshold"), undefined=pa.get("viable") is None),
        "tier_2 FPR@cal":     f"{t2.get('fpr_at_optimal', 0):.1%}" if t2.get("fpr_at_optimal") is not None else "—",
        "pathogen FPR@cal":   f"{pa.get('fpr_at_optimal', 0):.1%}" if pa.get("fpr_at_optimal") is not None else "—",
    })

_thr_df = pd.DataFrame(_thr_rows)
st.dataframe(
    _thr_df.style.format({"hard_ncpr": "{:.0%}"}, na_rep="—"),
    use_container_width=True, hide_index=True,
)

st.divider()

# ── Section 12: Further observations ─────────────────────────────────────────
st.header("Further Observations")
st.markdown(
    "Beyond the embedder/format recommendation, the pure MRR analysis surfaces a structural "
    "observation: the canonical doc is already ranked at #1 for the majority of medium-stratum "
    "queries across all four embedders, but its cosine score frequently sits below the "
    "production threshold of 0.62. The species-probe failures identified in exp 2.1 are "
    "therefore partly a gating problem, not purely a retrieval problem. A single-cell "
    "threshold sweep on the current production stack would characterise the score-distribution "
    "trade-off and could yield further improvements independent of the embedder/format choice. "
    "Filed for a follow-up experiment."
)
