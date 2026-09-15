"""
Reusable Plotly chart functions for benchmark visualization.

Each function returns a ``plotly.graph_objects.Figure`` built from the summary
DataFrame (``latest.csv``) or the raw results list (``latest.json``).
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from benchmarks.config import MODELS

# ---------------------------------------------------------------------------
# Visual design tokens (kept in sync with specs/visualization_specs.md)
# ---------------------------------------------------------------------------

TIER_COLORS = {
    0: "#2A5A86",  # latest frontier — slate blue
    1: "#4A7F9E",  # established frontier — lighter blue
    2: "#2A6347",  # cost-optimized — forest green
    3: "#A67B12",  # reasoning — dark amber
    4: "#6A6760",  # open source — neutral gray
}

# Difficulty tier colors for Exp 1.1 pH stochasticity (spec §Colors).
DIFFICULTY_COLORS = {
    "easy": "#2A6347",  # forest green
    "medium": "#A67B12",  # dark amber
    "hard": "#B84A2E",  # terracotta
}

# Qualitative palette for per-model coloring (used when models share a tier).
_QUALITATIVE = px.colors.qualitative.Plotly  # 10 distinct colors

ACCURACY_THRESHOLD = 0.90  # "acceptable" accuracy
COST_THRESHOLD = 0.001  # "production" cost per call (USD)
LATENCY_INTERACTIVE_S = 3.0
LATENCY_BATCH_S = 10.0

_MODEL_TIER = {m["name"]: m.get("tier", 4) for m in MODELS}


def _tier_for(model_name: str) -> int:
    return _MODEL_TIER.get(model_name, 4)


def _tier_color(model_name: str) -> str:
    return TIER_COLORS[_tier_for(model_name)]


def _model_color_map(model_names: list[str]) -> dict[str, str]:
    """Return a color map keyed by model name.

    Uses tier-based colors only when every model in the list belongs to a
    *different* tier — i.e. the tier palette maps 1-to-1 onto models without
    collision.  In any other case (all same tier, or mixed tiers where some
    tier has multiple models) the qualitative palette is used so every model
    gets a visually distinct color.
    """
    tier_list = [_tier_for(m) for m in model_names]
    all_unique_tiers = len(tier_list) == len(set(tier_list))
    if all_unique_tiers and len(set(tier_list)) > 1:
        # Each model is in a distinct tier: tier colors communicate grouping.
        return {m: _tier_color(m) for m in model_names}
    # Single tier, all same tier, or tier collisions: qualitative palette.
    return {m: _QUALITATIVE[i % len(_QUALITATIVE)] for i, m in enumerate(model_names)}


# ---------------------------------------------------------------------------
# Exp 1.1 — pH stochasticity charts
# ---------------------------------------------------------------------------

# FDA 21 CFR 114.3: foods with pH ≤ 4.6 inhibit C. botulinum growth.
# Values ABOVE this threshold are in the growth-risk zone.
PH_SAFETY_BOUNDARY = 4.6


def ph_violin_chart(foods: list[dict]) -> go.Figure:
    """Violin plot of pH distributions per food (Section 3 of Exp 1.1).

    Args:
        foods: List of food dicts from latest.json, each containing
               ``food_name``, ``ph_values``, ``ph_stats.stdev``,
               and ``reference_ph``.

    Returns:
        A ``go.Figure`` with:
        - One violin per food, ordered left → right by increasing stdev.
        - Uniform purple fill color.
        - Reference pH shown as a dashed horizontal line segment per food.
    """
    # Sort foods by stdev ascending so highest-variance foods appear on the right.
    sorted_foods = sorted(
        foods,
        key=lambda f: f.get("ph_stats", {}).get("stdev", 0.0),
    )

    fig = go.Figure()

    for food in sorted_foods:
        name = food.get("food_name", "?")
        ph_values = food.get("ph_values") or []

        fig.add_trace(
            go.Violin(
                y=ph_values,
                x=[name] * len(ph_values),
                name=name,
                showlegend=False,
                fillcolor=_DEEP_DIVE_COLOR,
                line_color=_DEEP_DIVE_COLOR,
                opacity=0.7,
                box_visible=True,
                meanline_visible=True,
                hovertemplate="<b>%{x}</b><br>pH: %{y:.2f}<extra></extra>",
            )
        )

    # --- reference pH markers (per-food dashed horizontal line segment) ------
    # Only include foods that have a real reference_ph value; None would produce
    # a silent gap in the scatter and a broken hover label (%{y:.2f} on None).
    ref_items = [
        (f.get("food_name", "?"), f.get("reference_ph"))
        for f in sorted_foods
        if f.get("reference_ph") is not None
    ]
    food_names_with_ref = [name for name, _ in ref_items]
    ref_phs = [ph for _, ph in ref_items]

    fig.add_trace(
        go.Scatter(
            x=food_names_with_ref,
            y=ref_phs,
            mode="markers",
            name="Reference pH",
            marker=dict(
                symbol="line-ew-open",
                size=28,
                color="black",
                line=dict(width=2.5, color="black"),
            ),
            hovertemplate="<b>%{x}</b><br>Reference pH: %{y:.2f}<extra></extra>",
        )
    )

    fig.update_layout(
        title="pH Distribution per Food (ordered by increasing variance)",
        xaxis_title="Food",
        yaxis_title="pH",
        violinmode="overlay",
        height=520,
    )
    return fig


MAE_SAFETY_THRESHOLD = 0.5  # MAE above this value is food-safety relevant


def mae_by_food_chart(results: list[dict]) -> go.Figure:
    """Bar chart of pH MAE per food (Section 4 of Exp 1.1).

    Single model: one bar per food, colored by difficulty tier.
    Multiple models: grouped bars per food, colored by model.

    Args:
        results: Full results list from latest.json (one entry per model).

    Returns:
        A ``go.Figure`` with a dashed threshold line at MAE = 0.5.
        Returns an empty titled figure when ``results`` is empty.
    """
    fig = go.Figure()

    if not results:
        fig.update_layout(title="MAE by Food — no data")
        return fig

    if len(results) == 1:
        foods = results[0].get("foods") or []
        fig.add_trace(
            go.Bar(
                name="MAE",
                x=[f.get("food_name", "?") for f in foods],
                y=[f.get("ph_stats", {}).get("mae", 0.0) for f in foods],
                marker_color=_DEEP_DIVE_COLOR,
                hovertemplate="%{x}<br>MAE: %{y:.3f}<extra></extra>",
                showlegend=False,
            )
        )
        legend_title = ""
    else:
        # Color by model — one trace per model, foods on x-axis.
        model_names = [r.get("model") or "?" for r in results]
        color_map = _model_color_map(model_names)
        for entry in results:
            model = entry.get("model") or "?"
            foods = entry.get("foods") or []
            fig.add_trace(
                go.Bar(
                    name=model,
                    x=[f.get("food_name", "?") for f in foods],
                    y=[f.get("ph_stats", {}).get("mae", 0.0) for f in foods],
                    marker_color=color_map.get(model, "#888888"),
                    meta=model,
                    hovertemplate="%{x}<br>MAE: %{y:.3f}<extra>%{meta}</extra>",
                )
            )
        legend_title = "Model"

    fig.add_hline(
        y=MAE_SAFETY_THRESHOLD,
        line_color="#B84A2E",
        line_dash="dash",
        line_width=2,
        annotation_text=f"Safety threshold ({MAE_SAFETY_THRESHOLD:.1f})",
        annotation_position="top right",
        annotation_font_color="#B84A2E",
    )

    fig.update_layout(
        title="MAE by Food (|LLM mean − Reference pH|)",
        xaxis_title="Food",
        yaxis_title="MAE",
        barmode="group",
        legend_title_text=legend_title,
        height=420,
    )
    return fig


LOG_GROWTH_THRESHOLD_DEFAULT = 1.0  # default log CFU/g threshold for safety impact


def growth_propagation_chart(foods: list[dict], log_threshold: float) -> go.Figure:
    """Horizontal bar chart showing log growth increase ranges per food (Section 5).

    Each bar spans [log_increase_min, log_increase_max].  A vertical line marks
    the safety threshold.  Bars use three colors:
    - Green: entire range below threshold (``log_increase_max < threshold``).
    - Amber: range crosses the threshold (``min < threshold <= max``).
    - Red: entire range above threshold (``log_increase_min >= threshold``).

    Args:
        foods: List of food dicts; only those containing a ``growth_propagation``
               sub-dict are included.  Foods without this key are silently skipped
               (fail-closed: missing data is not assumed safe).
        log_threshold: Log CFU/g value above which growth is considered a safety
                       impact.

    Returns:
        A ``go.Figure`` with horizontal bars and a vertical threshold line.
        Returns an empty titled figure when no foods have growth_propagation data.
    """
    # Extract foods that have valid growth_propagation data.
    gp_foods = []
    for food in foods:
        gp = food.get("growth_propagation")
        if not gp:
            continue
        lo = gp.get("log_increase_min")
        hi = gp.get("log_increase_max")
        if lo is None or hi is None or hi < lo:
            continue
        cat = _gp_category(lo, hi, log_threshold)
        gp_foods.append(
            {
                "food_name": food.get("food_name", "?"),
                "lo": lo,
                "hi": hi,
                "width": hi - lo,
                "category": cat,
            }
        )

    fig = go.Figure()

    if not gp_foods:
        fig.update_layout(title="Growth Propagation Impact — no data")
        return fig

    # Sort: below first (bottom), above last (top).
    gp_foods.sort(
        key=lambda d: (
            {"below": 0, "crossing": 1, "above": 2}[d["category"]],
            d["hi"],
        )
    )

    # One trace per category for legend entries.
    seen_cats: set[str] = set()
    for d in gp_foods:
        cat = d["category"]
        show_legend = cat not in seen_cats
        seen_cats.add(cat)

        fig.add_trace(
            go.Bar(
                y=[d["food_name"]],
                x=[d["width"]],
                base=[d["lo"]],
                orientation="h",
                marker_color=_GP_CATEGORY_COLOR[cat],
                name=_GP_CATEGORY_LABEL[cat],
                legendgroup=cat,
                showlegend=show_legend,
                hovertemplate=(
                    "<b>%{y}</b><br>"
                    f"Min: {d['lo']:.3f}<br>"
                    f"Max: {d['hi']:.3f}<br>"
                    "<extra></extra>"
                ),
            )
        )

    fig.add_vline(
        x=log_threshold,
        line_color="#B84A2E",
        line_width=2,
        annotation_text=f"Threshold ({log_threshold:.1f} log CFU/g)",
        annotation_position="top right",
        annotation_font_color="#B84A2E",
    )

    fig.update_layout(
        title=f"Growth Propagation Impact (threshold = {log_threshold:.1f} log CFU/g)",
        xaxis_title="Log increase (CFU/g)",
        yaxis_title="Food",
        height=max(300, 40 * len(gp_foods) + 150),
    )
    return fig


def model_comparison_bars(
    results: list[dict],
    metric: str,
    metric_label: str = "",
) -> go.Figure:
    """Bar chart comparing one summary metric across models (Section 7, Exp 1.1).

    Args:
        results: Full results list from latest.json (one entry per model).
        metric: Key within each entry's ``summary`` dict, e.g. ``"overall_mae"``
                or ``"overall_stdev"``.
        metric_label: Human-readable Y-axis label and title suffix.
                      Defaults to ``metric`` when empty.

    Returns:
        A ``go.Figure`` with one bar per model, colored by ``_model_color_map``.
        Returns an empty titled figure when ``results`` is empty.
    """
    label = metric_label or metric

    fig = go.Figure()

    if not results:
        fig.update_layout(title=f"Model Comparison — {label} (no data)")
        return fig

    model_names = [r.get("model") or "?" for r in results]
    color_map = _model_color_map(model_names)
    # color_map is built from the same model_names list, so every name is
    # guaranteed to be a key — direct lookup, no fallback needed.
    values = [r.get("summary", {}).get(metric, float("nan")) for r in results]
    colors = [color_map[m] for m in model_names]

    fig.add_trace(
        go.Bar(
            x=model_names,
            y=values,
            marker_color=colors,
            showlegend=False,
            hovertemplate="%{x}: %{y:.3f}<extra></extra>",
        )
    )

    fig.update_layout(
        title=f"Model Comparison — {label}",
        xaxis_title="Model",
        yaxis_title=label,
        height=380,
    )
    return fig


def boundary_crossing_histogram(
    ph_values: list[float],
    food_name: str,
    reference_ph: float | None = None,
) -> go.Figure:
    """Histogram of sampled pH values with the pH 4.6 safety boundary (Section 6).

    Args:
        ph_values: Raw pH samples from Monte Carlo runs.
        food_name: Display label for the chart title.
        reference_ph: Optional FDA reference pH; shown as a vertical dashed line.

    Returns:
        A ``go.Figure`` histogram with:
        - Red vertical line at pH 4.6.
        - Optional black dashed vertical line at reference_ph.
        - Annotation showing the fraction of samples on each side of 4.6.

    Note on annotation semantics:
        The annotation splits samples into "≤ 4.6" and "> 4.6" regardless of
        whether the food is acidic or low-acid. This is a raw split and does not
        directly correspond to ``boundary_crossing_rate`` from the experiment
        runner, which defines a "crossing" relative to the food's reference side
        (e.g., for an acid food the risky fraction is "> 4.6"; for a low-acid food
        it is "≤ 4.6"). Interpret the annotation in context of the food's reference pH.
    """
    fig = go.Figure()

    fig.add_trace(
        go.Histogram(
            x=ph_values,
            name="pH samples",
            marker_color="#2A5A86",
            opacity=0.75,
            hovertemplate="pH: %{x:.2f}<br>Count: %{y}<extra></extra>",
        )
    )

    # Fraction of samples on each side of the safety boundary.
    n_total = len(ph_values)
    if n_total > 0:
        n_below = sum(1 for v in ph_values if v <= PH_SAFETY_BOUNDARY)
        n_above = n_total - n_below
        pct_below = n_below / n_total * 100
        pct_above = n_above / n_total * 100
    else:
        pct_below = pct_above = 0.0

    # pH 4.6 safety boundary — terracotta vertical line.
    fig.add_vline(
        x=PH_SAFETY_BOUNDARY,
        line_color="#B84A2E",
        line_width=2,
        annotation_text=f"pH 4.6 ({pct_below:.0f}% ≤ / {pct_above:.0f}% >)",
        annotation_position="top right",
        annotation_font_color="#B84A2E",
    )

    # Reference pH — black dashed vertical line (if provided).
    if reference_ph is not None:
        fig.add_vline(
            x=reference_ph,
            line_color="black",
            line_dash="dash",
            line_width=1.5,
            annotation_text=f"Reference ({reference_ph:.2f})",
            annotation_position="top left",
        )

    fig.update_layout(
        title=f"pH Boundary Crossing — {food_name}",
        xaxis_title="pH",
        yaxis_title="Count",
        height=320,
        showlegend=False,
    )
    return fig


# ---------------------------------------------------------------------------
# Exp 1.1 — Per-food deep dive charts
# ---------------------------------------------------------------------------

# Slate-blue used for single-food deep dive charts.
_DEEP_DIVE_COLOR = "#2A5A86"


def ph_deep_dive_histogram(
    ph_values: list[float],
    food_name: str,
    reference_ph: float | None = None,
) -> go.Figure:
    """Histogram of pH values for a single food (deep dive row 1 left).

    Args:
        ph_values: Raw pH samples from Monte Carlo runs.
        food_name: Display label for the chart title.
        reference_ph: Optional FDA reference pH; shown as a vertical dashed line.

    Returns:
        A ``go.Figure`` histogram with reference pH line and padded y-axis.
    """
    fig = go.Figure()

    fig.add_trace(
        go.Histogram(
            x=ph_values,
            name="pH samples",
            marker_color=_DEEP_DIVE_COLOR,
            opacity=0.75,
            xbins=dict(size=0.05),
            hovertemplate="pH: %{x:.2f}<br>Count: %{y}<extra></extra>",
        )
    )

    if reference_ph is not None:
        fig.add_vline(
            x=reference_ph,
            line_color="black",
            line_dash="dash",
            line_width=1.5,
            annotation_text=f"Ref ({reference_ph:.2f})",
            annotation_position="top left",
        )

    # Widen x-axis range for visual breathing room around pH values.
    if ph_values:
        x_min = min(ph_values)
        x_max = max(ph_values)
        pad = max((x_max - x_min) * 0.3, 0.2)
        x_range = [x_min - pad, x_max + pad]
    else:
        x_range = None

    fig.update_layout(
        title=f"pH Distribution — {food_name}",
        xaxis_title="pH Value",
        xaxis=dict(range=x_range) if x_range else {},
        yaxis_title="count",
        height=320,
        showlegend=False,
        bargap=0.15,
    )
    return fig


def ph_deep_dive_boxplot(
    ph_values: list[float],
    food_name: str,
    reference_ph: float | None = None,
) -> go.Figure:
    """Box plot of pH values for a single food (deep dive row 1 right).

    Args:
        ph_values: Raw pH samples from Monte Carlo runs.
        food_name: Display label for the chart.
        reference_ph: Optional FDA reference pH; shown as a horizontal dashed line.

    Returns:
        A ``go.Figure`` box plot showing median, quartiles, whiskers, and outliers.
    """
    fig = go.Figure()

    fig.add_trace(
        go.Box(
            y=ph_values,
            x=[food_name] * len(ph_values),
            name=food_name,
            marker_color=_DEEP_DIVE_COLOR,
            fillcolor=_DEEP_DIVE_COLOR,
            opacity=0.6,
            boxmean=False,
            hovertemplate="pH: %{y:.2f}<extra></extra>",
        )
    )

    if reference_ph is not None:
        fig.add_hline(
            y=reference_ph,
            line_color="black",
            line_dash="dash",
            line_width=1.5,
            annotation_text=f"Ref ({reference_ph:.2f})",
            annotation_position="top right",
        )

    # Widen y-axis range for visual breathing room.
    if ph_values:
        y_min = min(ph_values)
        y_max = max(ph_values)
        pad = max((y_max - y_min) * 0.3, 0.2)
        y_range = [y_min - pad, y_max + pad]
    else:
        y_range = None

    fig.update_layout(
        title=f"pH Box Plot — {food_name}",
        xaxis_title="Food",
        yaxis_title="pH Value",
        yaxis=dict(range=y_range) if y_range else {},
        height=320,
        showlegend=False,
    )
    return fig


def ph_deep_dive_scatter(
    ph_values: list[float],
    food_name: str,
    reference_ph: float | None = None,
) -> go.Figure:
    """Strip/jitter scatter of individual pH trial values (deep dive row 2).

    Args:
        ph_values: Raw pH samples from Monte Carlo runs.
        food_name: Display label for the x-axis category.
        reference_ph: Optional FDA reference pH; shown as a horizontal dashed line.

    Returns:
        A ``go.Figure`` scatter plot with one dot per trial, jittered horizontally.
    """
    import random as _rng

    fig = go.Figure()

    # Add small horizontal jitter so overlapping points are visible.
    jitter = [_rng.gauss(0, 0.02) for _ in ph_values]
    x_positions = [0 + j for j in jitter]

    fig.add_trace(
        go.Scatter(
            x=x_positions,
            y=ph_values,
            mode="markers",
            name=food_name,
            marker=dict(color=_DEEP_DIVE_COLOR, size=8, opacity=0.7),
            hovertemplate="pH: %{y:.2f}<extra></extra>",
        )
    )

    if reference_ph is not None:
        fig.add_hline(
            y=reference_ph,
            line_color="black",
            line_dash="dash",
            line_width=1.5,
            annotation_text=f"Ref ({reference_ph:.2f})",
            annotation_position="top right",
        )

    fig.update_layout(
        title="Monte Carlo Trial Variation",
        xaxis=dict(
            tickvals=[0],
            ticktext=[food_name],
            title="Food",
        ),
        yaxis_title="pH Value",
        height=350,
        showlegend=True,
    )
    return fig


# ---------------------------------------------------------------------------
# Exp 1.1 — Growth propagation dot + error bar chart
# ---------------------------------------------------------------------------

# Three-category colors for growth propagation charts.
_GP_COLOR_BELOW = "#2A6347"  # fully below threshold — forest green
_GP_COLOR_CROSSING = (
    "#C49020"  # crosses threshold — amber (brighter than UI amber for chart legibility)
)
_GP_COLOR_ABOVE = "#B84A2E"  # fully above threshold — terracotta


def _gp_category(lo: float, hi: float, threshold: float) -> str:
    """Classify a food's growth range relative to the threshold."""
    if lo >= threshold:
        return "above"
    if hi >= threshold:
        return "crossing"
    return "below"


_GP_CATEGORY_COLOR = {
    "below": _GP_COLOR_BELOW,
    "crossing": _GP_COLOR_CROSSING,
    "above": _GP_COLOR_ABOVE,
}

_GP_CATEGORY_LABEL = {
    "below": "Below threshold",
    "crossing": "Crosses threshold",
    "above": "Above threshold",
}


def growth_propagation_dot_errorbar(
    foods: list[dict], log_threshold: float
) -> go.Figure:
    """Dot + error bar chart of mean log growth increase per food.

    Each food is shown as a dot at ``log_increase_mean`` with error bars
    spanning ``[log_increase_min, log_increase_max]``.  Colors follow the
    same three-category scheme as the bar chart.

    Args:
        foods: List of food dicts with ``growth_propagation`` sub-dict.
        log_threshold: Safety threshold (log CFU/g).

    Returns:
        A ``go.Figure`` with horizontal dot+error bars and a vertical threshold line.
    """
    gp_foods = []
    for food in foods:
        gp = food.get("growth_propagation")
        if not gp:
            continue
        lo = gp.get("log_increase_min")
        hi = gp.get("log_increase_max")
        mean = gp.get("log_increase_mean")
        if lo is None or hi is None or mean is None or hi < lo:
            continue
        cat = _gp_category(lo, hi, log_threshold)
        gp_foods.append(
            {
                "food_name": food.get("food_name", "?"),
                "lo": lo,
                "hi": hi,
                "mean": mean,
                "category": cat,
            }
        )

    fig = go.Figure()

    if not gp_foods:
        fig.update_layout(title="Growth Propagation (Dot + Error Bar) — no data")
        return fig

    # Sort same as bar chart: below first (bottom), above last (top).
    gp_foods.sort(
        key=lambda d: (
            {"below": 0, "crossing": 1, "above": 2}[d["category"]],
            d["hi"],
        )
    )

    # One trace per category for legend grouping.
    seen_cats: set[str] = set()
    for d in gp_foods:
        cat = d["category"]
        show_legend = cat not in seen_cats
        seen_cats.add(cat)

        fig.add_trace(
            go.Scatter(
                y=[d["food_name"]],
                x=[d["mean"]],
                error_x=dict(
                    type="data",
                    symmetric=False,
                    array=[d["hi"] - d["mean"]],
                    arrayminus=[d["mean"] - d["lo"]],
                    color=_GP_CATEGORY_COLOR[cat],
                    thickness=2,
                    width=6,
                ),
                mode="markers",
                name=_GP_CATEGORY_LABEL[cat],
                legendgroup=cat,
                showlegend=show_legend,
                marker=dict(
                    color=_GP_CATEGORY_COLOR[cat],
                    size=10,
                    symbol="circle",
                ),
                hovertemplate=(
                    "<b>%{y}</b><br>"
                    f"Mean: {d['mean']:.3f}<br>"
                    f"Min: {d['lo']:.3f}<br>"
                    f"Max: {d['hi']:.3f}<br>"
                    "<extra></extra>"
                ),
            )
        )

    fig.add_vline(
        x=log_threshold,
        line_color="#D62728",
        line_width=2,
        annotation_text=f"Threshold ({log_threshold:.1f})",
        annotation_position="top right",
        annotation_font_color="#D62728",
    )

    fig.update_layout(
        title=f"Growth Propagation — Dot + Error Bar (threshold = {log_threshold:.1f} log CFU/g)",
        xaxis_title="Log increase (CFU/g)",
        yaxis_title="Food",
        height=max(300, 40 * len(gp_foods) + 150),
    )
    return fig


# ---------------------------------------------------------------------------
# 3a — cost vs. accuracy scatter
# ---------------------------------------------------------------------------


def cost_vs_accuracy_scatter(df: pd.DataFrame) -> go.Figure:
    """Key decision chart: accuracy (%) vs. cost per call (log-USD).

    Colour encodes tier; marker size encodes consistency. Dashed threshold
    lines mark the 90% / $0.001 "production acceptable" quadrant.
    """
    data = df.copy()
    data["accuracy_pct"] = data["accuracy"] * 100
    # Log scale cannot plot zero — nudge free-of-charge models to a tiny floor.
    data["cost_plot"] = data["cost_per_call_usd"].replace(0, 1e-6)
    data["consistency_pct"] = data["consistency"] * 100
    data["tier"] = data["model"].map(_tier_for).astype(str)

    color_map = _model_color_map(data["model"].tolist())

    fig = px.scatter(
        data,
        x="cost_plot",
        y="accuracy_pct",
        color="model",
        color_discrete_map=color_map,
        size="consistency_pct",
        size_max=30,
        text="model",
        hover_data={
            "model": True,
            "cost_per_call_usd": ":.5f",
            "accuracy_pct": ":.1f",
            "consistency_pct": ":.1f",
            "cost_plot": False,
            "tier": True,
        },
    )
    fig.update_traces(textposition="top center")
    fig.update_xaxes(type="log", title="Cost per call (USD, log scale)")
    fig.update_yaxes(title="Accuracy (%)", range=[0, 105])

    fig.add_hline(
        y=ACCURACY_THRESHOLD * 100,
        line_dash="dash",
        line_color="#9A9793",
        annotation_text="Acceptable (90%)",
        annotation_position="bottom right",
    )
    fig.add_vline(
        x=COST_THRESHOLD,
        line_dash="dash",
        line_color="#9A9793",
        annotation_text="Production ($0.001)",
        annotation_position="top right",
    )

    # Quadrant labels as layout annotations (paper coords).
    for x, y, text in [
        (0.02, 0.97, "Sweet spot"),
        (0.97, 0.97, "Frontier zone"),
        (0.5, 0.05, "Inadequate"),
    ]:
        fig.add_annotation(
            xref="paper",
            yref="paper",
            x=x,
            y=y,
            text=f"<i>{text}</i>",
            showarrow=False,
            font=dict(color="#6A6760", size=11),
        )

    fig.update_layout(
        title="Cost vs. Accuracy",
        height=500,
        legend_title_text="Model",
    )
    return fig


# ---------------------------------------------------------------------------
# 3b — accuracy by difficulty tier
# ---------------------------------------------------------------------------


def accuracy_by_tier_bars(df: pd.DataFrame) -> go.Figure:
    """Grouped bar chart: X = difficulty tier, one bar per model."""
    tiers = [("Easy", "tier_easy"), ("Medium", "tier_medium"), ("Hard", "tier_hard")]

    model_names = df["model"].tolist()
    color_map = _model_color_map(model_names)

    fig = go.Figure()
    for _, row in df.iterrows():
        model = row["model"]
        fig.add_trace(
            go.Bar(
                name=model,
                x=[label for label, _ in tiers],
                y=[row[col] * 100 for _, col in tiers],
                marker_color=color_map[model],
                hovertemplate="%{x}: %{y:.1f}%<extra>" + model + "</extra>",
            )
        )

    fig.update_layout(
        title="Accuracy by difficulty tier",
        barmode="group",
        xaxis_title="Difficulty",
        yaxis_title="Accuracy (%)",
        yaxis=dict(range=[0, 105]),
        legend_title_text="Model",
    )
    return fig


# ---------------------------------------------------------------------------
# 3c — field accuracy heatmap
# ---------------------------------------------------------------------------


def field_accuracy_heatmap(results: list[dict]) -> go.Figure:
    """Heatmap: rows = models, columns = extraction fields.

    Values come from each model's ``summary.field_accuracy``. Field set is the
    union across all models; missing cells are shown blank.
    """
    models = [r["model"] for r in results]
    all_fields: list[str] = []
    seen: set[str] = set()
    for r in results:
        for field in r.get("summary", {}).get("field_accuracy", {}):
            if field not in seen:
                seen.add(field)
                all_fields.append(field)

    z = []
    text = []
    for r in results:
        field_acc = r.get("summary", {}).get("field_accuracy", {})
        z.append([field_acc.get(f) for f in all_fields])
        text.append(
            [f"{field_acc[f] * 100:.0f}%" if f in field_acc else "" for f in all_fields]
        )

    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=all_fields,
            y=models,
            text=text,
            texttemplate="%{text}",
            # Step-function colorscale matching spec accuracy thresholds:
            # < 70% → terracotta, 70–89% → amber, ≥ 90% → forest green.
            colorscale=[
                [0.0, "#B84A2E"],
                [0.6999, "#B84A2E"],
                [0.7, "#A67B12"],
                [0.8999, "#A67B12"],
                [0.9, "#2A6347"],
                [1.0, "#2A6347"],
            ],
            zmin=0,
            zmax=1,
            colorbar=dict(title="Accuracy", tickformat=".0%"),
            # Using %{text} (pre-formatted, blank for missing cells) avoids a
            # browser-side format error when z is None for absent fields.
            hovertemplate="%{y} · %{x}: %{text}<extra></extra>",
        )
    )
    fig.update_layout(
        title="Field-level accuracy",
        xaxis_title="Field",
        yaxis_title="Model",
        height=max(300, 40 * len(models) + 150),
    )
    return fig


# ---------------------------------------------------------------------------
# 3d — model type classification matrix (safety-critical)
# ---------------------------------------------------------------------------


def model_type_matrix(results: list[dict]) -> go.Figure:
    """Pass/fail cell per (model, query-with-model-type).

    Title turns red when any ``model_type_ok == false``.
    """
    models = [r["model"] for r in results]

    # Identify queries where model_type was in ground truth (i.e. field_scores
    # contains "model_type" for at least one model).
    query_ids: list[str] = []
    seen: set[str] = set()
    for r in results:
        for q in r.get("queries", []):
            if "model_type" in q.get("field_scores", {}) and q["query_id"] not in seen:
                seen.add(q["query_id"])
                query_ids.append(q["query_id"])

    # Build matrix: 1 = pass, 0 = fail, None = not applicable.
    z = []
    any_failure = False
    for r in results:
        row = []
        by_id = {q["query_id"]: q for q in r.get("queries", [])}
        for qid in query_ids:
            q = by_id.get(qid)
            if q is None or "model_type" not in q.get("field_scores", {}):
                row.append(None)
            else:
                # Safety-critical: missing model_type_ok fails closed, never
                # silently passes. field_scores["model_type"] marks presence
                # in ground truth, not correctness — do not fall back to it.
                ok = bool(q.get("model_type_ok", False))
                if not ok:
                    any_failure = True
                row.append(1 if ok else 0)
        z.append(row)

    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=query_ids,
            y=models,
            colorscale=[[0.0, "#B84A2E"], [1.0, "#2A6347"]],
            zmin=0,
            zmax=1,
            showscale=False,
            xgap=2,
            ygap=2,
            hovertemplate="%{y} · %{x}: %{z}<extra></extra>",
        )
    )

    title = "Model type classification (safety-critical)"
    title_color = "#B84A2E" if any_failure else "#1C1A17"
    fig.update_layout(
        title=dict(text=title, font=dict(color=title_color)),
        xaxis_title="Query",
        yaxis_title="Model",
        height=max(250, 35 * len(models) + 150),
    )
    return fig


# ---------------------------------------------------------------------------
# 3e — latency comparison (P50 vs P95)
# ---------------------------------------------------------------------------


def latency_comparison_bars(df: pd.DataFrame) -> go.Figure:
    """Side-by-side P50 and P95 latency bars per model."""
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            name="P50",
            x=df["model"],
            y=df["latency_p50_s"],
            marker_color="#2A5A86",
            hovertemplate="%{x}: %{y:.2f}s<extra>P50</extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            name="P95",
            x=df["model"],
            y=df["latency_p95_s"],
            marker_color="#90B8D4",
            hovertemplate="%{x}: %{y:.2f}s<extra>P95</extra>",
        )
    )

    fig.add_hline(
        y=LATENCY_INTERACTIVE_S,
        line_dash="dash",
        line_color="#2A6347",
        annotation_text="Interactive (3s)",
        annotation_position="top left",
    )
    fig.add_hline(
        y=LATENCY_BATCH_S,
        line_dash="dash",
        line_color="#A67B12",
        annotation_text="Batch acceptable (10s)",
        annotation_position="top left",
    )

    fig.update_layout(
        title="Latency comparison (P50 and P95)",
        barmode="group",
        xaxis_title="Model",
        yaxis_title="Latency (seconds)",
    )
    return fig


# ---------------------------------------------------------------------------
# 3f — token usage + cost per call
# ---------------------------------------------------------------------------


def token_usage_bars(df: pd.DataFrame) -> go.Figure:
    """Stacked input/output token bars with a secondary cost-per-call axis."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Bar(
            name="Input tokens",
            x=df["model"],
            y=df["input_tokens"],
            marker_color="#2A5A86",
            hovertemplate="%{x}: %{y:,}<extra>Input</extra>",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Bar(
            name="Output tokens",
            x=df["model"],
            y=df["output_tokens"],
            marker_color="#90B8D4",
            hovertemplate="%{x}: %{y:,}<extra>Output</extra>",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            name="Cost per call",
            x=df["model"],
            y=df["cost_per_call_usd"],
            mode="markers+lines",
            marker=dict(color="#B84A2E", size=10, symbol="diamond"),
            line=dict(color="#B84A2E", width=2),
            hovertemplate="%{x}: $%{y:.5f}<extra>Cost</extra>",
        ),
        secondary_y=True,
    )

    fig.update_layout(
        title="Token usage and cost per call",
        barmode="stack",
        xaxis_title="Model",
    )
    fig.update_yaxes(title_text="Tokens", secondary_y=False)
    fig.update_yaxes(
        title_text="Cost per call (USD)", secondary_y=True, tickformat="$.5f"
    )
    return fig
