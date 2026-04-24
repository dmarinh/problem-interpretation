"""
Page 4: pH Stochasticity (Experiment 1.1)

Visualises the Monte Carlo pH sampling results that demonstrate LLM output
variance near food-safety boundaries.

Narrative: "LLMs return different pH values for the same food each time you
ask. For foods near safety boundaries, this variance alone can flip the safety
conclusion. That's why RAG grounding is necessary."
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd
import streamlit as st

from benchmarks.visualizations.lib.charts import (
    growth_propagation_dot_errorbar,
    mae_by_food_chart,
    model_comparison_bars,
    ph_deep_dive_boxplot,
    ph_deep_dive_histogram,
    ph_deep_dive_scatter,
    ph_violin_chart,
)
from benchmarks.visualizations.lib.data_loader import (
    load_latest_results,
    load_run_by_timestamp,
)

_EXPERIMENT_ID = "exp_1_1_ph_stochasticity"

# ---------------------------------------------------------------------------
# Helpers (pure functions — importable and testable without Streamlit)
# ---------------------------------------------------------------------------


def build_summary_df(results: list[dict]) -> pd.DataFrame:
    """Build a one-row-per-model summary DataFrame from raw JSON results.

    Args:
        results: list of model result dicts from latest.json.

    Returns:
        DataFrame with columns: Model, MAE, Stdev, Boundary Crossings,
        Safety Impacts, Total Cost (USD).
    """
    rows = []
    for entry in results:
        summary = entry.get("summary") or {}
        rows.append(
            {
                "Model": entry.get("model", "—"),
                "MAE": summary.get("overall_mae", float("nan")),
                "Stdev": summary.get("overall_stdev", float("nan")),
                "Boundary Crossings": summary.get("foods_with_boundary_crossing", 0),
                "Safety Impacts": summary.get("foods_with_safety_impact", 0),
                "Total Cost (USD)": summary.get("total_cost_usd", 0.0),
            }
        )
    return pd.DataFrame(rows)


def extract_run_info(results: list[dict]) -> dict:
    """Extract run-level metadata from raw JSON results.

    Args:
        results: list of model result dicts from latest.json.

    Returns:
        Dict with keys: temperature, n_runs, n_models, n_foods.
        Missing values default to sensible sentinels (0 / "—").
    """
    n_models = len(results)
    if not results:
        return {"temperature": "—", "n_runs": 0, "n_models": 0, "n_foods": 0}

    first = results[0]
    temperature = first.get("temperature", "—")

    foods = first.get("foods") or []
    n_foods = len(foods)

    # n_runs is a run-level constant (same for every food). Use the first food
    # that reports n_valid > 0 so a failed first food doesn't mask the real count.
    n_runs = 0
    for food in foods:
        n = food.get("ph_stats", {}).get("n_valid")
        if n is not None and n > 0:
            n_runs = n
            break
    if n_runs == 0:
        for food in foods:
            ph = food.get("ph_values") or []
            if ph:
                n_runs = len(ph)
                break

    return {
        "temperature": temperature,
        "n_runs": n_runs,
        "n_models": n_models,
        "n_foods": n_foods,
    }


def generate_key_finding(results: list[dict], log_threshold: float) -> dict:
    """Aggregate safety impact data for Section 9 narrative text.

    Iterates all foods across all models and takes the worst-case GP stats
    per unique food name (highest log_increase_max across models).

    A food is classified as:
    - **crossing**: variance flips the safety conclusion (lo < threshold <= hi).
    - **above**: consistently above threshold regardless of variance (lo >= threshold).

    Args:
        results: Full results list from latest.json.
        log_threshold: Safety threshold (log CFU/g).

    Returns:
        Dict with keys:
        - ``n_crossing`` (int): foods where variance flips the conclusion.
        - ``n_above`` (int): foods consistently above threshold.
        - ``n_total`` (int): total unique foods with valid GP data.
        - ``worst_food_name`` (str | None): crossing food with largest range,
          or None when there are no crossing foods.
        - ``worst_food_range`` (float): that food's log_increase_range (0.0 if none).
        - ``has_impacts`` (bool): True when n_crossing > 0 or n_above > 0.
    """
    # Aggregate worst-case GP stats per food_name across all models.
    food_stats: dict[str, dict] = {}
    for entry in results:
        for food in entry.get("foods") or []:
            name = food.get("food_name")
            if not name:
                continue
            gp = food.get("growth_propagation") or {}
            lo = gp.get("log_increase_min")
            hi = gp.get("log_increase_max")
            if lo is None or hi is None:
                continue
            rng = gp.get("log_increase_range", hi - lo)
            prev = food_stats.get(name)
            # Keep the worst-case (highest max) across models for this food.
            if prev is None or hi > prev["hi"]:
                food_stats[name] = {"lo": lo, "hi": hi, "range": rng}

    n_total = len(food_stats)

    # Crossing: variance flips the conclusion (some runs safe, some not).
    crossing = {
        name: s for name, s in food_stats.items()
        if s["lo"] < log_threshold <= s["hi"]
    }
    # Above: consistently unsafe regardless of variance.
    above = {
        name: s for name, s in food_stats.items()
        if s["lo"] >= log_threshold
    }

    n_crossing = len(crossing)
    n_above = len(above)

    # "Most affected by variance" = crossing food with the largest range.
    worst_food_name: str | None = None
    worst_food_range = 0.0
    if crossing:
        worst_food_name = max(crossing, key=lambda n: crossing[n]["range"])
        worst_food_range = crossing[worst_food_name]["range"]

    return {
        "n_crossing": n_crossing,
        "n_above": n_above,
        "n_total": n_total,
        "worst_food_name": worst_food_name,
        "worst_food_range": worst_food_range,
        "has_impacts": (n_crossing + n_above) > 0,
    }


def find_food_by_name(foods: list[dict], food_name: str | None) -> dict | None:
    """Return the first food dict whose food_name matches, or None.

    Args:
        foods: List of food dicts from the model result.
        food_name: The food_name string to look up.  A ``None`` argument
                   always returns ``None`` (fail-closed: avoids accidentally
                   matching foods whose ``food_name`` key is absent).

    Returns:
        The matching food dict, or None if not found.
    """
    if food_name is None:
        return None
    return next((f for f in foods if f.get("food_name") == food_name), None)


def _gp_is_impacted(food: dict, threshold: float) -> bool:
    """Return True only when the food has valid GP data and max >= threshold.

    Mirrors the guard in growth_propagation_chart so the metric count and the
    chart's bar colors always agree (both require non-None min AND max).
    """
    gp = food.get("growth_propagation") or {}
    lo = gp.get("log_increase_min")
    hi = gp.get("log_increase_max")
    return lo is not None and hi is not None and hi >= threshold


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

st.title("Exp 1.1 — pH Stochasticity")
st.caption(
    "LLMs return different pH values for the same food each time you ask. "
    "For foods near safety boundaries, this variance alone can flip the safety conclusion. "
    "That's why RAG grounding is necessary."
)

# Respect sidebar run selection (app.py stores it in session_state).
selected_run = st.session_state.get(f"selected_run:{_EXPERIMENT_ID}")
if selected_run:
    results, _ = load_run_by_timestamp(_EXPERIMENT_ID, selected_run)
else:
    results, _ = load_latest_results(_EXPERIMENT_ID)

if not results:
    st.info(
        "No results found for Experiment 1.1. "
        "Run the experiment from the **Run Experiments** page first."
    )
    st.stop()

# ---------------------------------------------------------------------------
# Section 1: Run information
# ---------------------------------------------------------------------------

st.header("Run Information")

run_info = extract_run_info(results)

col1, col2, col3, col4 = st.columns(4)
col1.metric("LLM Temperature", run_info["temperature"])
col2.metric("Runs per food", run_info["n_runs"])
col3.metric("Models tested", run_info["n_models"])
col4.metric("Foods", run_info["n_foods"])

# ---------------------------------------------------------------------------
# Section 2: Summary table
# ---------------------------------------------------------------------------

st.header("Model Summary")

summary_df = build_summary_df(results)

st.dataframe(
    summary_df,
    use_container_width=True,
    column_config={
        "Model": st.column_config.TextColumn("Model"),
        "MAE": st.column_config.NumberColumn("MAE", format="%.3f"),
        "Stdev": st.column_config.NumberColumn("Stdev", format="%.3f"),
        "Boundary Crossings": st.column_config.NumberColumn("Boundary Crossings"),
        "Safety Impacts": st.column_config.NumberColumn("Safety Impacts"),
        "Total Cost (USD)": st.column_config.NumberColumn("Total Cost (USD)", format="$%.4f"),
    },
    hide_index=True,
)

# ---------------------------------------------------------------------------
# Section 3: Violin plots of pH distributions (the key chart)
# ---------------------------------------------------------------------------

st.header("pH Distributions per Food")
st.caption(
    "Each violin shows the spread of pH values returned by the LLM across repeated runs. "
    "The horizontal dash (—) marks the FDA reference pH. "
    "Foods are ordered left → right by increasing variance."
)

model_names = [r.get("model") or "—" for r in results]
if len(results) > 1:
    selected_model = st.selectbox("Select model", model_names, key="violin_model")
    model_foods = next(
        (r.get("foods") or [] for r in results if (r.get("model") or "—") == selected_model),
        [],
    )
else:
    model_foods = results[0].get("foods") or []

if model_foods:
    st.plotly_chart(ph_violin_chart(model_foods), use_container_width=True)
else:
    st.info("No food data available for the selected model.")

# ---------------------------------------------------------------------------
# Section 4: MAE by food (bar chart)
# ---------------------------------------------------------------------------

st.header("MAE by Food")
st.caption(
    "Mean Absolute Error between LLM mean pH and the FDA reference. "
    "The dashed line marks the 0.5 threshold above which pH error becomes food-safety relevant."
)

st.plotly_chart(mae_by_food_chart(results), use_container_width=True)

# ---------------------------------------------------------------------------
# Section 5: Growth propagation impact chart
# ---------------------------------------------------------------------------

st.header("Growth Propagation Impact")
st.caption(
    "Each dot shows the mean log CFU/g growth increase per food, with error bars spanning "
    "the min–max range across Monte Carlo runs. Colors indicate whether the range is fully "
    "below (green), crosses (amber), or fully above (red) the safety threshold."
)

log_threshold = st.slider(
    "Log growth threshold (CFU/g)",
    min_value=0.1,
    max_value=3.0,
    value=1.0,
    step=0.1,
    help="Foods whose maximum sampled growth reaches or exceeds this threshold are flagged red.",
)

if len(results) > 1:
    gp_model = st.selectbox("Select model", model_names, key="gp_model")
    gp_foods = next(
        (r.get("foods") or [] for r in results if (r.get("model") or "—") == gp_model),
        [],
    )
else:
    gp_foods = results[0].get("foods") or []

n_impacted = sum(1 for f in gp_foods if _gp_is_impacted(f, log_threshold))
st.metric("Safety-impacted foods", n_impacted)

st.plotly_chart(
    growth_propagation_dot_errorbar(gp_foods, log_threshold),
    use_container_width=True,
)

# ---------------------------------------------------------------------------
# Section 6: Model comparison (multi-model only)
# ---------------------------------------------------------------------------

if len(results) > 1:
    st.header("Model Comparison")
    st.info(
        "Even the best model has non-zero stdev at temperature > 0. "
        "RAG grounding reduces variance by anchoring pH values to validated references."
    )

    col_mae, col_stdev = st.columns(2)
    with col_mae:
        st.plotly_chart(
            model_comparison_bars(results, "overall_mae", "MAE"),
            use_container_width=True,
        )
    with col_stdev:
        st.plotly_chart(
            model_comparison_bars(results, "overall_stdev", "Stdev"),
            use_container_width=True,
        )

# ---------------------------------------------------------------------------
# Section 8: Per-food deep dive
# ---------------------------------------------------------------------------

st.header("Per-Food Deep Dive")
st.caption(
    "Select a food to inspect individual run details: pH distribution, "
    "raw LLM responses, and growth propagation data."
)

if len(results) > 1:
    dive_model = st.selectbox("Model", model_names, key="dive_model")
    dive_foods = next(
        (r.get("foods") or [] for r in results if (r.get("model") or "—") == dive_model),
        [],
    )
else:
    dive_foods = results[0].get("foods") or []

food_names_list = [f.get("food_name", "?") for f in dive_foods]

if not food_names_list:
    st.info("No food data available for the selected model.")
else:
    selected_food_name = st.selectbox("Food", food_names_list, key="dive_food")
    selected_food = find_food_by_name(dive_foods, selected_food_name)

    if selected_food is not None:
        ph_vals = selected_food.get("ph_values") or []
        ref_ph = selected_food.get("reference_ph")

        # Row 1: histogram (left) + box plot (right).
        col_hist, col_box = st.columns(2)
        with col_hist:
            st.plotly_chart(
                ph_deep_dive_histogram(ph_vals, selected_food_name, reference_ph=ref_ph),
                use_container_width=True,
            )
        with col_box:
            st.plotly_chart(
                ph_deep_dive_boxplot(ph_vals, selected_food_name, reference_ph=ref_ph),
                use_container_width=True,
            )

        st.divider()

        # Row 2: Monte Carlo trial scatter (full width).
        st.caption("**Probabilistic Analysis**")
        st.plotly_chart(
            ph_deep_dive_scatter(ph_vals, selected_food_name, reference_ph=ref_ph),
            use_container_width=True,
        )

        # Growth propagation summary (if available).
        gp = selected_food.get("growth_propagation") or {}
        gp_min = gp.get("log_increase_min")
        gp_max = gp.get("log_increase_max")
        if gp_min is not None and gp_max is not None:
            gp_mean = gp.get("log_increase_mean")
            mean_str = f"{gp_mean:.3f}" if gp_mean is not None else "—"
            st.caption("**Log growth increase distribution (across Monte Carlo runs)**")
            st.markdown(
                f"- Min: **{gp_min:.3f}** log CFU/g  \n"
                f"- Mean: **{mean_str}** log CFU/g  \n"
                f"- Max: **{gp_max:.3f}** log CFU/g"
            )

        # Raw LLM responses expander.
        raw_runs = selected_food.get("raw_runs") or []
        if raw_runs:
            with st.expander(f"Raw LLM responses ({len(raw_runs)} runs)"):
                for i, run in enumerate(raw_runs):
                    st.markdown(f"**Run {i + 1}**")
                    st.text(run.get("raw_response") or "(no response)")
                    meta_parts = []
                    latency = run.get("latency_s")
                    error = run.get("error")
                    if latency is not None:
                        meta_parts.append(f"Latency: {latency:.2f}s")
                    if error:
                        meta_parts.append(f"Error: {error}")
                    if meta_parts:
                        st.caption(" · ".join(meta_parts))
                    st.divider()

# ---------------------------------------------------------------------------
# Section 9: Key finding
# ---------------------------------------------------------------------------

st.header("Key Finding")

finding = generate_key_finding(results, log_threshold)
n_crossing = finding["n_crossing"]
n_above = finding["n_above"]
n_total = finding["n_total"]
worst = finding["worst_food_name"]
worst_range = finding["worst_food_range"]

if finding["has_impacts"]:
    parts: list[str] = []

    if n_crossing > 0:
        crossing_detail = (
            f"LLM pH variance **flipped the safety conclusion** for "
            f"**{n_crossing}** food{'s' if n_crossing > 1 else ''} "
            f"(log growth threshold: {log_threshold:.1f} CFU/g) — "
            "some runs fell below the threshold while others exceeded it."
        )
        if worst:
            crossing_detail += (
                f" The most affected was **{worst}** "
                f"(growth range: {worst_range:.3f} log CFU/g across sampled pHs)."
            )
        parts.append(crossing_detail)

    if n_above > 0:
        parts.append(
            f"**{n_above}** food{'s' if n_above > 1 else ''} "
            f"{'are' if n_above > 1 else 'is'} **consistently above** the threshold "
            "regardless of pH variance — unsafe in every run."
        )

    parts.append(
        "RAG grounding eliminates LLM pH variance by anchoring values to "
        "validated FDA references, removing stochastic safety flip-flops."
    )

    st.warning(" ".join(parts))
else:
    st.success(
        f"No safety impacts detected across {n_total} foods at the current threshold "
        f"({log_threshold:.1f} log CFU/g). "
        "RAG grounding eliminates LLM pH variance by anchoring values to "
        "validated FDA references."
    )
