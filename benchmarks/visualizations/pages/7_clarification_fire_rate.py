"""
Page 7: Clarification Gate Fire Rate (Experiment 5.1)

Narrative flow:
  Description → Run info → Prominent caveat → The two stages → Per-category
  chart (binary) → Summary table → Known limitation → Method → Corpus.

Audience note: this page is written for a reader who has never seen this
codebase before and will not read the experiment script. Every domain term
(organism grounding, the taxonomy bridge, IFT-2003-T1, ptm_category) is
explained in prose here, not assumed. See
benchmarks/experiments/exp_5_1_clarification_fire_rate.py for the full
methodology writeup this page summarises.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from benchmarks.config import RESULTS_DIR
from benchmarks.visualizations.ui.style import (
    PTM_COLORWAY,
    apply_ptm_template,
    inject_css,
)

_EXPERIMENT_ID = "exp_5_1_clarification_fire_rate"

# Two discrete colors, not a gradient -- the finding is binary (a category
# either always triggers the gate or never does, nothing in between was
# observed), and a gradient/heatmap would visually imply a spectrum that
# isn't in the data. Reused from the existing PTM_COLORWAY's semantic
# slots: index 5 is already used elsewhere for "safety / error", index 2
# for "cost-optimised / normal" -- keeping that same association here
# (fires = attention-worthy, clear = normal) rather than inventing new
# colors.
_FIRES = PTM_COLORWAY[5]  # "#B84A2E" terracotta
_CLEAR = PTM_COLORWAY[2]  # "#2A6347" forest green


# ---------------------------------------------------------------------------
# Data loading
#
# Loader caveat (learned from Experiment 2.1's own page): the shared
# benchmarks.visualizations.lib.data_loader.load_latest_results() only
# accepts a JSON file whose top-level structure is a *list* (one entry per
# thing-being-compared, e.g. one per embedder or one per model). This
# experiment's results file is a *dict* at the top level (experiment_id,
# timestamp, corpus, summary, queries) because there's only one thing being
# reported here, not several things being compared -- so it needs its own
# loader, same as Experiment 2.1's page does, rather than the shared one.
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


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------


def _category_bar_chart(per_category: dict) -> go.Figure:
    """
    One bar per ptm_category, height = fraction of that category's queries
    that triggered the clarification gate. Deliberately two flat colors
    (fires / doesn't fire), not a continuous color scale -- the observed
    result is 9 categories at exactly 0% and 2 at exactly 100%, nothing in
    between, so a gradient would suggest a spectrum this data doesn't have.
    """
    cats = list(per_category.keys())
    rates = [per_category[c]["clarification_rate"] or 0.0 for c in cats]
    counts = [
        f"{per_category[c]['clarification_total']}/{per_category[c]['n']}" for c in cats
    ]
    colors = [_FIRES if r > 0 else _CLEAR for r in rates]

    fig = go.Figure(
        go.Bar(
            x=cats,
            y=rates,
            marker_color=colors,
            text=counts,
            textposition="outside",
            hovertemplate="%{x}: %{text} queries triggered clarification<extra></extra>",
        )
    )
    fig.update_layout(
        title="Clarification Gate Fire Rate by Food Category",
        yaxis=dict(
            tickformat=".0%",
            range=[0, 1.15],
            title="Share of queries that triggered the gate",
        ),
        xaxis_title="Food category (ptm_category)",
        showlegend=False,
    )
    return apply_ptm_template(fig)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

inject_css()

st.title("Experiment 5.1 — Clarification Gate Fire Rate")

with st.expander("▸ What does this experiment measure?", expanded=True):
    st.markdown("""
Every prediction this system makes needs to know **which specific pathogen**
(bacterium) it's predicting growth or survival for — e.g. *Salmonella*,
*Listeria monocytogenes*. Figuring that out from a food description is
called **organism grounding**. When it fails, the system does **not**
guess: there is no defensible "worst-case pathogen" the way there's a
defensible worst-case temperature or pH. So a failed grounding either
fails the request outright, or — since a recent change — **asks the user
instead**, offering a short list of plausible pathogens to pick from. That
ask/answer mechanism is what this project calls the **clarification gate**,
and this experiment measures how often it actually fires in practice, and
why.

**Why "why" matters as much as "how often":** the gate can fire for two
structurally different reasons (see *The two failure reasons*, below). One
reason means the system's own food-recognition step is missing foods it
should know — a bug worth fixing. The other means the reference data this
system relies on for pathogen-per-food-category information simply doesn't
cover that category — a limitation of the data, not something more code
can fix. A single "fire rate" number can't tell these apart; this
experiment is built to.
        """)

# ── Load data ────────────────────────────────────────────────────────────────
data, df = _load_latest()

if data is None:
    st.info(
        "No results found for Experiment 5.1. "
        "Run the experiment first from the CLI (this makes live, billed LLM "
        "calls — see the script's own docstring for cost control):"
    )
    st.code(
        "python -m benchmarks.experiments.exp_5_1_clarification_fire_rate --dry-run  "
        "# cost estimate, no LLM calls\n"
        "python -m benchmarks.experiments.exp_5_1_clarification_fire_rate  "
        "# the real run",
        language="bash",
    )
    st.stop()

summary: dict = data.get("summary", {})
per_category: dict = summary.get("per_category", {})
overall: dict = summary.get("taxonomy_weighted_overall", {})
corpus_meta: dict = data.get("corpus", {})
queries: list = data.get("queries", [])

if not per_category:
    st.error("results JSON present but summary.per_category is empty.")
    st.stop()

# ── Section 1: Run info ──────────────────────────────────────────────────────
ts = _fmt_ts(data.get("timestamp"))
n_categories = len(corpus_meta.get("categories", []))
n_per_cat = corpus_meta.get("n_per_category", "?")
n_total = corpus_meta.get("total_queries", "?")

col_ts, col_c, col_n, col_seed = st.columns(4)
col_ts.metric("Run", ts)
col_c.metric("Categories", n_categories)
col_n.metric("Queries", f"{n_total} ({n_per_cat}/category)")
col_seed.metric("Sample seed", corpus_meta.get("seed", "?"))

st.divider()

# ── Section 2: Prominent caveat ──────────────────────────────────────────────
st.warning(
    "**This corpus is taxonomy-weighted, not user-weighted.** Every food "
    "category contributes the same number of queries "
    f"({n_per_cat} each), regardless of how often real users actually ask "
    "about that category. Real queries skew heavily toward common foods "
    "like chicken and rice, not obscure entries drawn evenly from a "
    "2,917-row food classification table. **Any single aggregate number "
    "on this page (e.g. an overall percentage) describes how the gate "
    "behaves averaged across the food taxonomy's own categories — it is "
    "NOT an estimate of how often a real user would see this gate fire.** "
    "Read the per-category chart and table below as the primary result."
)

st.divider()

# ── Section 3: The two failure reasons ───────────────────────────────────────
st.header("The Two Failure Reasons")
st.markdown(
    "When organism grounding fails, it fails for one of two reasons that "
    "this system tells apart and reports separately — because they call "
    "for completely different responses:"
)

col_left, col_right = st.columns(2)
with col_left:
    st.subheader(":material/search_off: FOOD_UNRECOGNISED")
    st.markdown(
        "The **taxonomy bridge** — the component that maps a free-text food "
        "description onto a known food category — didn't recognise the "
        "food at all. This is **this project's own problem**: either the "
        "food-matching logic needs improvement, or the reference food list "
        "needs to grow. **Fixable by engineering work.**"
    )
with col_right:
    st.subheader(":material/rule_folder: CATEGORY_HAS_NO_HAZARD_DATA")
    st.markdown(
        "The food **was** recognised and correctly placed into a category "
        '— but the reference source this project uses for "which pathogens '
        'are typically a concern for this category of food" '
        "(a table from a 2003 Institute of Food Technologists publication, "
        "cited internally as **IFT-2003-T1**) simply has no entry for that "
        "category. This is a **coverage ceiling of the reference data**, "
        "not a defect in this project's code. **Not fixable by asking "
        "harder — only by sourcing better/broader reference data.**"
    )

st.divider()

# ── Section 4: Main finding — binary chart ───────────────────────────────────
st.header("The Result")

n_total_int = overall.get("n", 0)
stage_counts = overall.get("clarification_by_stage", {})
# Exact counts from the JSON's own per-stage dict -- never reconstructed by
# multiplying a rounded rate back out (overall["clarification_rate"] is
# stored rounded to 3 decimals, so rate * n can silently under/over-count).
n_food_unrec = stage_counts.get("food_unrecognised", 0)
n_cat_no_haz = stage_counts.get("category_has_no_hazard_data", 0)
n_fires = n_food_unrec + n_cat_no_haz

st.markdown(
    f"Out of **{n_total_int} queries** (taxonomy-weighted — see caveat above), "
    f"the gate fired **{n_fires}** times. **{n_cat_no_haz}** of those were "
    f"**CATEGORY_HAS_NO_HAZARD_DATA**; **{n_food_unrec}** were FOOD_UNRECOGNISED "
    "— across every category sampled, the taxonomy bridge never once failed "
    "to recognise a food. That is itself a meaningful negative result: the "
    "main risk this experiment was checking for — a hidden food-recognition "
    "bug masquerading as a graceful clarification — was not found."
)

st.plotly_chart(_category_bar_chart(per_category), use_container_width=True)

st.markdown(
    "**The split is exactly binary.** 9 of 11 categories never trigger the "
    "gate (0%); the other 2 — **condiment** and **beverage** — trigger it "
    "**every single time** (100%). There is no partial/intermediate case "
    "anywhere in this run. That is consistent with the gate firing at a "
    "hard edge of the reference data's coverage, not a fuzzy retrieval "
    "problem: condiment and beverage are precisely the two food categories "
    "that IFT-2003-T1 has no pathogen table for at all, so once a food is "
    "correctly recognised as belonging to either one, there is structurally "
    "no hazard data left to look up."
)

st.divider()

# ── Section 5: Summary table ─────────────────────────────────────────────────
st.header("Per-Category Summary")

if df is not None and not df.empty:
    _COL_MAP = {
        "ptm_category": "Category",
        "n": "n",
        "answered": "Answered",
        "answered_rate": "Answered %",
        "clarification_food_unrecognised": "FOOD_UNRECOGNISED",
        "clarification_category_has_no_hazard_data": "CATEGORY_HAS_NO_HAZARD_DATA",
        "other_failure": "Other failure",
    }
    cols_present = [c for c in _COL_MAP if c in df.columns]
    display_df = df.loc[:, cols_present].rename(columns=_COL_MAP).reset_index(drop=True)
    fmt = {"Answered %": "{:.0%}"} if "Answered %" in display_df.columns else {}
    st.dataframe(
        display_df.style.format(fmt, na_rep="—"),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(
        '"Other failure" = a hard failure the gate does not catch at all '
        "(e.g. the organism was identified but isn't supported by this "
        "system's prediction models, or the query was misclassified as not "
        "being a food-safety question). Zero in every category in this run."
    )
else:
    st.warning("Summary CSV not available.")

st.divider()

# ── Section 6: Known limitation ──────────────────────────────────────────────
st.header("Known Limitation")
st.info(
    '**"Condiment" is a broad bucket that includes nuts and spices** — '
    "e.g. peanut butter, tahini, black pepper — foods with **documented "
    "*Salmonella* outbreak histories** in real-world food safety literature. "
    "This system currently asks a clarifying question about *all* of them, "
    "identically to how it treats coffee or wine, because neither the "
    "hazard reference CSV nor the category-to-IFT mapping distinguishes "
    '"condiment" foods with known pathogen associations from those '
    "without. **This is a gap in the underlying knowledge base, not a "
    "defect in the gate's logic** — the gate is behaving correctly given "
    "what it has access to. Closing this gap (adding category- or "
    "food-specific hazard data for at-risk condiment items) is out of "
    "scope for this experiment, which only measures current behaviour."
)

st.divider()

# ── Section 7: Method ────────────────────────────────────────────────────────
st.header("Method, Briefly")
st.markdown(f"""
- **{n_total_int} queries** ({n_per_cat} per category × {n_categories}
  categories), sampled from `data/rag/food_taxonomy.csv` with a fixed
  random seed (**{corpus_meta.get('seed', '?')}**) so the sample is
  reproducible.
- **One fixed scenario template**, with only the food name substituted, so
  the food is the only thing that varies between queries:
  `"{corpus_meta.get('scenario_template', '')}"`
- **Live LLM extraction** — each query goes through this project's real
  natural-language understanding step, not a scripted/mocked shortcut, so
  the result reflects how the system actually behaves for a real query.
- **Outcomes measured from the plain API response** (`status`,
  `clarification.stage`) exactly as an external caller of this system's API
  would see them — never from internal-only debugging state, and never
  from the verbose/expanded diagnostic mode this API also offers.
""")

st.divider()

# ── Section 8: Corpus — every food sampled, and what happened to it ─────────
st.header("The Corpus")
st.caption(
    "Every food this experiment queried, and what happened to it. This is "
    "what makes the finding above checkable rather than a bare claim — "
    "search or filter by category to see exactly which foods triggered "
    "the gate."
)

if queries:
    corpus_df = pd.DataFrame(
        [
            {
                "Category": q.get("ptm_category"),
                "Food": q.get("food_name"),
                "Outcome": q.get("outcome"),
                "Stage": q.get("clarification_stage") or "—",
            }
            for q in queries
        ]
    )

    cat_options = ["All"] + sorted(corpus_df["Category"].unique().tolist())
    selected_cat = st.selectbox("Filter by category", options=cat_options)
    filtered_df = (
        corpus_df
        if selected_cat == "All"
        else corpus_df[corpus_df["Category"] == selected_cat]
    )
    st.dataframe(filtered_df, use_container_width=True, hide_index=True)
else:
    st.info("No per-query data available in this results file.")
