"""Unit tests for benchmarks.visualizations.lib.charts."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import pytest

from benchmarks.visualizations.lib import charts


@pytest.fixture
def summary_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "model": "GPT-4o",
                "accuracy": 0.95,
                "consistency": 0.98,
                "cost_per_call_usd": 0.005,
                "latency_p50_s": 1.1,
                "latency_p95_s": 2.3,
                "input_tokens": 10000,
                "output_tokens": 5000,
                "tier_easy": 1.0,
                "tier_medium": 0.9,
                "tier_hard": 0.85,
            },
            {
                "model": "Qwen 2.5 14B",
                "accuracy": 0.80,
                "consistency": 1.0,
                "cost_per_call_usd": 0.0,
                "latency_p50_s": 25.0,
                "latency_p95_s": 110.0,
                "input_tokens": 90000,
                "output_tokens": 6000,
                "tier_easy": 0.97,
                "tier_medium": 0.85,
                "tier_hard": 0.60,
            },
        ]
    )


@pytest.fixture
def results_list() -> list[dict]:
    return [
        {
            "model": "GPT-4o",
            "queries": [
                {
                    "query_id": "E1",
                    "field_scores": {"model_type": True},
                    "model_type_ok": True,
                },
                {
                    "query_id": "M1",
                    "field_scores": {"model_type": True},
                    "model_type_ok": True,
                },
            ],
            "summary": {
                "field_accuracy": {
                    "food_description": 0.95,
                    "model_type": 1.0,
                    "pathogen": 1.0,
                }
            },
        },
        {
            "model": "Qwen 2.5 14B",
            "queries": [
                {
                    "query_id": "E1",
                    "field_scores": {"model_type": True},
                    "model_type_ok": True,
                },
                {
                    "query_id": "M1",
                    "field_scores": {"model_type": True},
                    "model_type_ok": False,
                },
            ],
            "summary": {
                "field_accuracy": {
                    "food_description": 1.0,
                    "model_type": 0.5,
                    "temperature": 0.9,
                }
            },
        },
    ]


def test_cost_vs_accuracy_scatter_axes_and_thresholds(summary_df):
    fig = charts.cost_vs_accuracy_scatter(summary_df)
    assert isinstance(fig, go.Figure)
    assert fig.layout.xaxis.type == "log"
    assert "Cost" in fig.layout.xaxis.title.text
    assert "Accuracy" in fig.layout.yaxis.title.text
    # Threshold lines: one horizontal at 90%, one vertical at $0.001.
    shapes = fig.layout.shapes
    assert any(s.type == "line" and s.y0 == s.y1 == 90 for s in shapes)
    assert any(s.type == "line" and s.x0 == s.x1 == charts.COST_THRESHOLD for s in shapes)


def test_cost_vs_accuracy_scatter_points_are_labeled(summary_df):
    """Spec 3a: points labeled with model name (text mode)."""
    fig = charts.cost_vs_accuracy_scatter(summary_df)
    labeled_models: set[str] = set()
    for trace in fig.data:
        if getattr(trace, "text", None) is not None:
            labeled_models.update(t for t in trace.text if t)
    assert labeled_models == set(summary_df["model"])


def test_cost_vs_accuracy_scatter_handles_zero_cost_with_log_floor(summary_df):
    """Zero-cost models must not disappear under log scale — nudged to a floor."""
    fig = charts.cost_vs_accuracy_scatter(summary_df)
    # Collect every x value plotted across all traces.
    plotted_x: list[float] = []
    for trace in fig.data:
        if getattr(trace, "x", None) is not None:
            plotted_x.extend(trace.x)
    # Same number of points as input rows (no silent drops).
    assert len(plotted_x) == len(summary_df)
    # All values strictly positive so log scale can render them.
    assert all(x > 0 for x in plotted_x)


def test_cost_vs_accuracy_scatter_has_quadrant_annotations(summary_df):
    """Spec 3a: Sweet spot / Frontier zone / Inadequate annotations present."""
    fig = charts.cost_vs_accuracy_scatter(summary_df)
    texts = " ".join(a.text for a in fig.layout.annotations if a.text)
    assert "Sweet spot" in texts
    assert "Frontier zone" in texts
    assert "Inadequate" in texts


def test_cost_vs_accuracy_scatter_empty_df_does_not_crash():
    """Empty results should still produce a figure with threshold lines."""
    empty = pd.DataFrame(
        columns=[
            "model",
            "accuracy",
            "consistency",
            "cost_per_call_usd",
        ]
    )
    fig = charts.cost_vs_accuracy_scatter(empty)
    assert isinstance(fig, go.Figure)
    # No points plotted — every trace is empty.
    for trace in fig.data:
        assert not list(getattr(trace, "x", []) or [])


def test_accuracy_by_tier_bars_trace_per_model(summary_df):
    fig = charts.accuracy_by_tier_bars(summary_df)
    assert len(fig.data) == len(summary_df)
    for trace in fig.data:
        assert list(trace.x) == ["Easy", "Medium", "Hard"]
    assert fig.layout.barmode == "group"


def test_accuracy_by_tier_bars_values_in_percent(summary_df):
    """Y values must be scaled 0-100, not 0-1, and match the source df."""
    fig = charts.accuracy_by_tier_bars(summary_df)
    for trace, (_, row) in zip(fig.data, summary_df.iterrows()):
        assert list(trace.y) == [
            row["tier_easy"] * 100,
            row["tier_medium"] * 100,
            row["tier_hard"] * 100,
        ]
    # Y-axis capped at 105 to leave label headroom above 100%.
    assert tuple(fig.layout.yaxis.range) == (0, 105)


def test_accuracy_by_tier_bars_models_get_distinct_colors(summary_df):
    """When all models share a tier, qualitative palette ensures distinct colors.

    Both fixture models resolve to Tier 4 (same tier), so the chart falls back
    to the qualitative palette and assigns each model a different color.
    If higher-tier API models are added back to MODELS, the chart switches to
    the tier-based palette instead.
    """
    fig = charts.accuracy_by_tier_bars(summary_df)
    color_by_name = {t.name: t.marker.color for t in fig.data}
    # Both models must have a color assigned.
    assert color_by_name["GPT-4o"] is not None
    assert color_by_name["Qwen 2.5 14B"] is not None
    # Colors must differ so models are visually distinguishable.
    assert color_by_name["GPT-4o"] != color_by_name["Qwen 2.5 14B"]


def _tier_bar_df(*models):
    """Build a minimal accuracy_by_tier_bars-compatible DataFrame."""
    return pd.DataFrame(
        [
            {
                "model": m,
                "accuracy": 0.8,
                "consistency": 0.9,
                "cost_per_call_usd": 0.0,
                "latency_p50_s": 5.0,
                "latency_p95_s": 20.0,
                "input_tokens": 5000,
                "output_tokens": 500,
                "tier_easy": 0.9,
                "tier_medium": 0.8,
                "tier_hard": 0.6,
            }
            for m in models
        ]
    )


def test_accuracy_by_tier_bars_one_per_tier_uses_tier_palette(monkeypatch):
    """When each model is in a distinct tier, tier-based colors are applied."""
    monkeypatch.setitem(charts._MODEL_TIER, "ModelA", 1)
    monkeypatch.setitem(charts._MODEL_TIER, "ModelB", 2)
    df = _tier_bar_df("ModelA", "ModelB")
    fig = charts.accuracy_by_tier_bars(df)
    color_by_name = {t.name: t.marker.color for t in fig.data}
    assert color_by_name["ModelA"] == charts.TIER_COLORS[1]
    assert color_by_name["ModelB"] == charts.TIER_COLORS[2]


def test_accuracy_by_tier_bars_mixed_tier_collision_uses_qualitative(monkeypatch):
    """Mixed tiers with multiple models in the same tier → qualitative palette.

    Scenario: one Tier 1 API model + two Tier 4 local models.
    The two Tier 4 models would collide on gray, so qualitative colors are
    assigned to all three models instead.
    """
    monkeypatch.setitem(charts._MODEL_TIER, "FrontierModel", 1)
    monkeypatch.setitem(charts._MODEL_TIER, "LocalA", 4)
    monkeypatch.setitem(charts._MODEL_TIER, "LocalB", 4)
    df = _tier_bar_df("FrontierModel", "LocalA", "LocalB")
    fig = charts.accuracy_by_tier_bars(df)
    color_by_name = {t.name: t.marker.color for t in fig.data}
    # All three must have different colors.
    colors = list(color_by_name.values())
    assert len(set(colors)) == 3, f"Expected 3 distinct colors, got: {colors}"
    # None of them should be the collision color (gray).
    assert charts.TIER_COLORS[4] not in colors


def test_accuracy_by_tier_bars_single_row(summary_df):
    """Single-model df still produces one grouped-bar trace with all 3 tiers."""
    fig = charts.accuracy_by_tier_bars(summary_df.head(1))
    assert len(fig.data) == 1
    assert list(fig.data[0].x) == ["Easy", "Medium", "Hard"]


def test_field_accuracy_heatmap_dimensions(results_list):
    fig = charts.field_accuracy_heatmap(results_list)
    assert len(fig.data) == 1
    heatmap = fig.data[0]
    assert list(heatmap.y) == ["GPT-4o", "Qwen 2.5 14B"]
    # Union of fields across both models.
    assert set(heatmap.x) == {"food_description", "model_type", "pathogen", "temperature"}


def test_field_accuracy_heatmap_missing_cells_are_none(results_list):
    """Models without a given field get None (blank cell), not 0."""
    fig = charts.field_accuracy_heatmap(results_list)
    heatmap = fig.data[0]
    fields = list(heatmap.x)
    z_by_model = dict(zip(heatmap.y, heatmap.z))
    # GPT-4o has no "temperature" field in its summary → should be None.
    gpt_temp = z_by_model["GPT-4o"][fields.index("temperature")]
    assert gpt_temp is None
    # Qwen has no "pathogen" field → None.
    qwen_pathogen = z_by_model["Qwen 2.5 14B"][fields.index("pathogen")]
    assert qwen_pathogen is None


def test_field_accuracy_heatmap_colorscale_step_thresholds():
    """Spec §Accuracy coloring: step thresholds at 70% (amber) and 90% (green).

    The colorscale must use discrete steps — not a continuous gradient — so
    that a cell at 89% reads amber and a cell at 90% reads green.
    """
    results = [
        {
            "model": "GPT-4o",
            "queries": [],
            "summary": {"field_accuracy": {"food_description": 1.0}},
        }
    ]
    fig = charts.field_accuracy_heatmap(results)
    colorscale = list(fig.data[0].colorscale)

    # Endpoints stay anchored.
    assert colorscale[0][1].lower() == "#d62728"   # 0% → red
    assert colorscale[-1][1].lower() == "#2ca02c"  # 100% → green

    # Amber step: a breakpoint at exactly 0.7 must exist and be amber.
    amber_at_70 = next((s for s in colorscale if s[0] == 0.7), None)
    assert amber_at_70 is not None, "Expected a breakpoint at 0.7 for amber threshold"
    assert amber_at_70[1].lower() == "#ffc107"

    # Green step: a breakpoint at exactly 0.9 must exist and be green.
    green_at_90 = next((s for s in colorscale if s[0] == 0.9), None)
    assert green_at_90 is not None, "Expected a breakpoint at 0.9 for green threshold"
    assert green_at_90[1].lower() == "#2ca02c"


def test_field_accuracy_heatmap_colorscale_below_amber_is_red():
    """A value just below 70% (0.6999) must still map to red, not amber.

    The step implementation achieves this by repeating red at 0.6999 and
    starting amber at exactly 0.7. This test confirms that breakpoint pair
    is present so the discontinuity is at 70%, not at some intermediate value.
    """
    results = [
        {
            "model": "GPT-4o",
            "queries": [],
            "summary": {"field_accuracy": {"food_description": 1.0}},
        }
    ]
    fig = charts.field_accuracy_heatmap(results)
    colorscale = list(fig.data[0].colorscale)

    # The colorscale must include a red entry at 0.6999 (the "close" side of the
    # amber boundary) — this is what makes the step hard rather than a gradient.
    red_at_6999 = next((s for s in colorscale if s[0] == 0.6999), None)
    assert red_at_6999 is not None, (
        "Expected a red breakpoint at 0.6999 to create a hard step at 70%"
    )
    assert red_at_6999[1].lower() == "#d62728"


def test_field_accuracy_heatmap_colorscale_below_green_is_amber():
    """A value just below 90% (0.8999) must still map to amber, not green.

    The step is achieved by repeating amber at 0.8999 and starting green at
    exactly 0.9. This test confirms that pairing exists.
    """
    results = [
        {
            "model": "GPT-4o",
            "queries": [],
            "summary": {"field_accuracy": {"food_description": 1.0}},
        }
    ]
    fig = charts.field_accuracy_heatmap(results)
    colorscale = list(fig.data[0].colorscale)

    amber_at_8999 = next((s for s in colorscale if s[0] == 0.8999), None)
    assert amber_at_8999 is not None, (
        "Expected an amber breakpoint at 0.8999 to create a hard step at 90%"
    )
    assert amber_at_8999[1].lower() == "#ffc107"


def test_field_accuracy_heatmap_colorscale_zmin_zmax():
    """zmin=0 / zmax=1 must be set; without them the colorscale relative
    positions would not map to the absolute accuracy values 0.0–1.0.
    """
    results = [
        {
            "model": "GPT-4o",
            "queries": [],
            "summary": {"field_accuracy": {"food_description": 0.85}},
        }
    ]
    fig = charts.field_accuracy_heatmap(results)
    heatmap = fig.data[0]
    assert heatmap.zmin == 0, "zmin must be 0 for colorscale positions to be absolute"
    assert heatmap.zmax == 1, "zmax must be 1 for colorscale positions to be absolute"


def test_field_accuracy_heatmap_colorscale_has_exactly_six_stops():
    """Exactly 6 colorscale stops implement the two-step-threshold pattern.

    The expected structure is:
        [0.0, red], [0.6999, red], [0.7, amber], [0.8999, amber], [0.9, green], [1.0, green]

    Fewer stops would merge a step with a gradient; more would be unexpected.
    """
    results = [
        {
            "model": "GPT-4o",
            "queries": [],
            "summary": {"field_accuracy": {"food_description": 1.0}},
        }
    ]
    fig = charts.field_accuracy_heatmap(results)
    colorscale = list(fig.data[0].colorscale)
    assert len(colorscale) == 6, (
        f"Expected 6 colorscale stops for a two-threshold step function, got {len(colorscale)}"
    )


def test_model_type_matrix_failure_flags_title(results_list):
    fig = charts.model_type_matrix(results_list)
    assert fig.layout.title.font.color == "#D62728"
    assert set(fig.data[0].x) == {"E1", "M1"}


def test_model_type_matrix_all_fail_flags_red_title():
    """Title turns red when every model fails — not just partial failures."""
    results = [
        {
            "model": "M1",
            "queries": [
                {
                    "query_id": "Q1",
                    "field_scores": {"model_type": True},
                    "model_type_ok": False,
                }
            ],
            "summary": {"field_accuracy": {}},
        },
        {
            "model": "M2",
            "queries": [
                {
                    "query_id": "Q1",
                    "field_scores": {"model_type": True},
                    "model_type_ok": False,
                }
            ],
            "summary": {"field_accuracy": {}},
        },
    ]
    fig = charts.model_type_matrix(results)
    assert fig.layout.title.font.color == "#D62728"
    # Cells are all zero (fail).
    assert all(cell == 0 for row in fig.data[0].z for cell in row)


def test_model_type_matrix_skips_queries_without_model_type_in_truth():
    """Queries where model_type isn't in ground truth must not appear."""
    results = [
        {
            "model": "M1",
            "queries": [
                {
                    "query_id": "Q_with",
                    "field_scores": {"model_type": True},
                    "model_type_ok": True,
                },
                {
                    "query_id": "Q_without",
                    "field_scores": {"pathogen": True},  # no model_type key
                },
            ],
            "summary": {"field_accuracy": {}},
        }
    ]
    fig = charts.model_type_matrix(results)
    assert list(fig.data[0].x) == ["Q_with"]


def test_model_type_matrix_missing_ok_field_fails_closed():
    """Safety-critical: if model_type_ok is absent, treat as failure, not pass.

    Why: field_scores["model_type"] being True only means the field was scored
    in ground truth (presence marker), not that the model got it right.
    A malformed result missing model_type_ok must never show as a green cell.
    """
    results = [
        {
            "model": "M1",
            "queries": [
                {
                    "query_id": "Q1",
                    "field_scores": {"model_type": True},
                    # No model_type_ok key on purpose.
                }
            ],
            "summary": {"field_accuracy": {}},
        }
    ]
    fig = charts.model_type_matrix(results)
    assert fig.data[0].z[0][0] == 0
    assert fig.layout.title.font.color == "#D62728"


def test_model_type_matrix_all_pass_keeps_default_title():
    results = [
        {
            "model": "GPT-4o",
            "queries": [
                {
                    "query_id": "E1",
                    "field_scores": {"model_type": True},
                    "model_type_ok": True,
                }
            ],
            "summary": {"field_accuracy": {}},
        }
    ]
    fig = charts.model_type_matrix(results)
    assert fig.layout.title.font.color != "#D62728"


def test_latency_comparison_has_p50_and_p95_traces(summary_df):
    fig = charts.latency_comparison_bars(summary_df)
    names = {trace.name for trace in fig.data}
    assert {"P50", "P95"} <= names
    shapes = fig.layout.shapes
    assert any(s.y0 == s.y1 == charts.LATENCY_INTERACTIVE_S for s in shapes)
    assert any(s.y0 == s.y1 == charts.LATENCY_BATCH_S for s in shapes)


def test_latency_comparison_threshold_annotations_labelled(summary_df):
    """Spec 3e: threshold lines are labelled ('Interactive' / 'Batch')."""
    fig = charts.latency_comparison_bars(summary_df)
    texts = " ".join(a.text for a in fig.layout.annotations if a.text)
    assert "Interactive" in texts
    assert "Batch" in texts


def test_latency_comparison_values_and_axis_titles(summary_df):
    """Y values equal source df and axes are labelled."""
    fig = charts.latency_comparison_bars(summary_df)
    p50 = next(t for t in fig.data if t.name == "P50")
    p95 = next(t for t in fig.data if t.name == "P95")
    assert list(p50.y) == list(summary_df["latency_p50_s"])
    assert list(p95.y) == list(summary_df["latency_p95_s"])
    assert "Latency" in fig.layout.yaxis.title.text
    assert "Model" in fig.layout.xaxis.title.text
    assert fig.layout.barmode == "group"


def test_token_usage_has_stacked_bars_and_cost_line(summary_df):
    fig = charts.token_usage_bars(summary_df)
    trace_names = {t.name for t in fig.data}
    assert {"Input tokens", "Output tokens", "Cost per call"} <= trace_names
    assert fig.layout.barmode == "stack"

    # Token bar heights must sum to total_input + total_output for each model.
    input_trace = next(t for t in fig.data if t.name == "Input tokens")
    output_trace = next(t for t in fig.data if t.name == "Output tokens")
    for i, model in enumerate(summary_df["model"]):
        row = summary_df[summary_df["model"] == model].iloc[0]
        assert input_trace.y[i] + output_trace.y[i] == row["input_tokens"] + row["output_tokens"]


def test_token_usage_cost_line_on_secondary_axis(summary_df):
    """Cost-per-call trace must bind to the secondary (right) y-axis."""
    fig = charts.token_usage_bars(summary_df)
    cost = next(t for t in fig.data if t.name == "Cost per call")
    # make_subplots puts the secondary-y trace on 'y2'.
    assert cost.yaxis == "y2"
    assert list(cost.x) == list(summary_df["model"])
    assert list(cost.y) == list(summary_df["cost_per_call_usd"])


def test_token_usage_secondary_axis_title_mentions_cost(summary_df):
    fig = charts.token_usage_bars(summary_df)
    # The secondary y-axis is yaxis2 in make_subplots output.
    assert "Cost" in fig.layout.yaxis2.title.text
    assert "Tokens" in fig.layout.yaxis.title.text


# ---------------------------------------------------------------------------
# ph_violin_chart (Exp 1.1 — Section 3)
# ---------------------------------------------------------------------------

import copy as _copy

# Base food dicts — kept as module-level constants only for use in fixture
# factories below.  Never pass these directly to the chart; always use the
# fixture or _all_foods() so mutations inside ph_violin_chart can't bleed
# between tests.
_FOOD_HIGH_STDEV = {
    "food_id": "F01",
    "food_name": "chicken",
    "difficulty": "easy",
    "reference_ph": 6.3,
    "ph_values": [5.5, 6.0, 6.5, 7.0, 7.5, 8.0],
    "ph_stats": {"stdev": 0.9},
}
_FOOD_LOW_STDEV = {
    "food_id": "F02",
    "food_name": "tomato",
    "difficulty": "medium",
    "reference_ph": 4.2,
    "ph_values": [4.1, 4.2, 4.2, 4.3],
    "ph_stats": {"stdev": 0.08},
}
_FOOD_NEAR_BOUNDARY = {
    "food_id": "F03",
    "food_name": "salsa",
    "difficulty": "hard",
    "reference_ph": 4.5,
    "ph_values": [4.3, 4.5, 4.6, 4.7, 4.9],
    "ph_stats": {"stdev": 0.22},
}


@pytest.fixture()
def all_foods():
    """Deep-copied list of all three test foods — isolates tests from mutations."""
    return _copy.deepcopy([_FOOD_HIGH_STDEV, _FOOD_LOW_STDEV, _FOOD_NEAR_BOUNDARY])


def test_ph_violin_chart_returns_figure(all_foods):
    fig = charts.ph_violin_chart(all_foods)
    assert isinstance(fig, go.Figure)


def test_ph_violin_chart_one_violin_per_food(all_foods):
    """Each food must produce exactly one Violin trace."""
    fig = charts.ph_violin_chart(all_foods)
    violin_traces = [t for t in fig.data if isinstance(t, go.Violin)]
    assert len(violin_traces) == len(all_foods)


def test_ph_violin_chart_violins_ordered_by_stdev(all_foods):
    """Foods must appear left-to-right in ascending stdev order.

    Expected order: tomato (0.08) → salsa (0.22) → chicken (0.9).
    """
    fig = charts.ph_violin_chart(all_foods)
    violin_traces = [t for t in fig.data if isinstance(t, go.Violin)]
    # x is a tuple of repeated food names; take the first element of each.
    food_order = [t.x[0] for t in violin_traces]
    assert food_order == ["tomato", "salsa", "chicken"]


def test_ph_violin_chart_reference_ph_scatter_present(all_foods):
    """A Scatter trace carrying reference pH markers must be present.

    Both x (food names) and y (reference pH values) must be in stdev-ascending
    order so each marker sits above the correct violin.
    """
    fig = charts.ph_violin_chart(all_foods)
    scatter_traces = [t for t in fig.data if isinstance(t, go.Scatter)]
    assert len(scatter_traces) == 1
    ref_trace = scatter_traces[0]
    # y-values in stdev-ascending order: tomato → salsa → chicken.
    expected_refs = [
        _FOOD_LOW_STDEV["reference_ph"],      # tomato — lowest stdev
        _FOOD_NEAR_BOUNDARY["reference_ph"],  # salsa
        _FOOD_HIGH_STDEV["reference_ph"],     # chicken — highest stdev
    ]
    assert list(ref_trace.y) == expected_refs
    # x-values must align with y-values so each marker is over the correct violin.
    assert list(ref_trace.x) == ["tomato", "salsa", "chicken"]


def test_ph_violin_chart_no_ph_46_boundary_line(all_foods):
    """pH 4.6 safety boundary must NOT appear (removed from violin chart)."""
    fig = charts.ph_violin_chart(all_foods)
    shapes = fig.layout.shapes
    boundary_shapes = [
        s for s in shapes
        if s.type == "line" and s.y0 == s.y1 == charts.PH_SAFETY_BOUNDARY
    ]
    assert not boundary_shapes, "pH 4.6 boundary line must not be present"


def test_ph_violin_chart_uniform_color_applied(all_foods):
    """Violin fill color must be the uniform deep-dive purple for all foods."""
    fig = charts.ph_violin_chart(all_foods)
    violin_traces = [t for t in fig.data if isinstance(t, go.Violin)]
    for trace in violin_traces:
        assert trace.fillcolor == charts._DEEP_DIVE_COLOR


def test_ph_violin_chart_no_legend():
    """Violin traces must all have showlegend=False (no difficulty legend)."""
    food_a = {**_copy.deepcopy(_FOOD_LOW_STDEV), "food_id": "X1",
              "food_name": "apple",
              "ph_stats": {"stdev": 0.1}}
    food_b = {**_copy.deepcopy(_FOOD_LOW_STDEV), "food_id": "X2",
              "food_name": "pear",
              "ph_stats": {"stdev": 0.2}}
    fig = charts.ph_violin_chart([food_a, food_b])
    violin_traces = [t for t in fig.data if isinstance(t, go.Violin)]
    for trace in violin_traces:
        assert trace.showlegend is False


def test_ph_violin_chart_violinmode_is_overlay(all_foods):
    """Spec §3: violinmode must be 'overlay' so each food's violin occupies its
    own categorical slot without stacking or grouping."""
    fig = charts.ph_violin_chart(all_foods)
    assert fig.layout.violinmode == "overlay"


def test_ph_violin_chart_empty_foods_does_not_crash():
    """Empty food list returns a figure with no violin traces.

    The Scatter trace (for reference pH markers) is always present but empty.
    """
    fig = charts.ph_violin_chart([])
    assert isinstance(fig, go.Figure)
    assert not any(isinstance(t, go.Violin) for t in fig.data)
    scatter_traces = [t for t in fig.data if isinstance(t, go.Scatter)]
    assert len(scatter_traces) == 1
    assert list(scatter_traces[0].x) == []
    assert list(scatter_traces[0].y) == []


def test_ph_violin_chart_food_with_empty_ph_values_adds_degenerate_violin():
    """A food with an empty ph_values list adds a Violin trace with x=[] and y=[].

    Plotly renders nothing visible for it, but the trace IS present in fig.data.
    The name 'degenerate' documents that this is the actual behaviour, not a skip.
    """
    food_empty = {**_copy.deepcopy(_FOOD_LOW_STDEV), "ph_values": []}
    fig = charts.ph_violin_chart([food_empty])
    assert isinstance(fig, go.Figure)
    violin_traces = [t for t in fig.data if isinstance(t, go.Violin)]
    assert len(violin_traces) == 1
    assert list(violin_traces[0].x) == []
    assert list(violin_traces[0].y) == []


def test_ph_violin_chart_food_missing_reference_ph_does_not_crash():
    """A food with reference_ph=None must not crash and must not put None in scatter y.

    The x-value must also align correctly with the y-value (same food name).
    """
    food_no_ref = {**_copy.deepcopy(_FOOD_LOW_STDEV), "reference_ph": None}
    food_with_ref = _copy.deepcopy(_FOOD_HIGH_STDEV)
    fig = charts.ph_violin_chart([food_no_ref, food_with_ref])
    assert isinstance(fig, go.Figure)
    scatter_traces = [t for t in fig.data if isinstance(t, go.Scatter)]
    assert len(scatter_traces) == 1
    # Only chicken has a real reference_ph — tomato (None) must be excluded.
    assert None not in list(scatter_traces[0].y)
    assert len(scatter_traces[0].y) == 1
    assert list(scatter_traces[0].x) == ["chicken"]
    assert list(scatter_traces[0].y) == [food_with_ref["reference_ph"]]


def test_ph_violin_chart_food_missing_ph_stats_key_defaults_to_zero_stdev():
    """A food with no ph_stats key sorts to position 0 (stdev defaults to 0.0)."""
    food_no_stats = {
        "food_id": "F99",
        "food_name": "mystery",
        "difficulty": "easy",
        "reference_ph": 6.0,
        "ph_values": [5.8, 6.0, 6.2],
        # ph_stats key intentionally absent
    }
    food_with_stats = _copy.deepcopy(_FOOD_NEAR_BOUNDARY)  # stdev=0.22
    fig = charts.ph_violin_chart([food_with_stats, food_no_stats])
    violin_traces = [t for t in fig.data if isinstance(t, go.Violin)]
    assert violin_traces[0].x[0] == "mystery"  # 0.0 < 0.22 → leftmost
    assert violin_traces[1].x[0] == "salsa"


def test_ph_violin_chart_any_difficulty_uses_uniform_color():
    """Any difficulty value (including unknown) must use the uniform purple color."""
    food = {**_copy.deepcopy(_FOOD_LOW_STDEV), "difficulty": "extreme"}
    fig = charts.ph_violin_chart([food])
    violin = next(t for t in fig.data if isinstance(t, go.Violin))
    assert violin.fillcolor == charts._DEEP_DIVE_COLOR


def test_ph_violin_chart_axes_labelled(all_foods):
    fig = charts.ph_violin_chart(all_foods)
    assert "pH" in fig.layout.yaxis.title.text
    assert "Food" in fig.layout.xaxis.title.text


def test_ph_violin_chart_all_foods_missing_reference_ph_renders_empty_scatter():
    """When every food has reference_ph=None, the Scatter trace must be present
    but empty (x=[], y=[]).  No None values must appear in the scatter y-data.

    This is a fail-closed variant: the chart should not crash or produce NaN
    markers when the entire reference_ph column is absent from the data.
    """
    food_a = {**_copy.deepcopy(_FOOD_LOW_STDEV), "reference_ph": None}
    food_b = {**_copy.deepcopy(_FOOD_NEAR_BOUNDARY), "reference_ph": None}
    fig = charts.ph_violin_chart([food_a, food_b])
    assert isinstance(fig, go.Figure)
    # Violin traces must still appear — two foods, two violins.
    violin_traces = [t for t in fig.data if isinstance(t, go.Violin)]
    assert len(violin_traces) == 2
    # Scatter trace must exist but have no points.
    scatter_traces = [t for t in fig.data if isinstance(t, go.Scatter)]
    assert len(scatter_traces) == 1
    assert list(scatter_traces[0].x) == []
    assert list(scatter_traces[0].y) == []
    assert None not in list(scatter_traces[0].y)


# ---------------------------------------------------------------------------
# mae_by_food_chart (Exp 1.1 — Section 4)
# ---------------------------------------------------------------------------

def _make_results(foods_per_model: list[tuple[str, list[dict]]]) -> list[dict]:
    """Build a minimal results list for mae_by_food_chart tests.

    Deep-copies food dicts so tests cannot mutate shared module-level fixtures.
    """
    import copy
    return [
        {"model": model, "foods": copy.deepcopy(foods)}
        for model, foods in foods_per_model
    ]


_MAE_FOOD_EASY = {
    "food_name": "chicken",
    "difficulty": "easy",
    "ph_stats": {"mae": 0.3},
}
_MAE_FOOD_MEDIUM = {
    "food_name": "tomato",
    "difficulty": "medium",
    "ph_stats": {"mae": 0.7},
}
_MAE_FOOD_HARD = {
    "food_name": "salsa",
    "difficulty": "hard",
    "ph_stats": {"mae": 1.2},
}


class TestMaeByFoodChartSingleModel:
    def _fig(self, foods=None):
        if foods is None:
            foods = [_MAE_FOOD_EASY, _MAE_FOOD_MEDIUM, _MAE_FOOD_HARD]
        return charts.mae_by_food_chart(_make_results([("ModelA", foods)]))

    def test_returns_figure(self):
        assert isinstance(self._fig(), go.Figure)

    def test_single_bar_trace(self):
        """Single-model: one Bar trace for all foods (no difficulty grouping)."""
        fig = self._fig()
        bar_traces = [t for t in fig.data if isinstance(t, go.Bar)]
        assert len(bar_traces) == 1

    def test_bar_name_is_mae(self):
        fig = self._fig()
        bar = next(t for t in fig.data if isinstance(t, go.Bar))
        assert bar.name == "MAE"

    def test_uniform_color_applied(self):
        fig = self._fig()
        bar = next(t for t in fig.data if isinstance(t, go.Bar))
        assert bar.marker.color == charts._DEEP_DIVE_COLOR

    def test_mae_values_correct(self):
        """Y values must match ph_stats.mae for each food."""
        fig = self._fig()
        all_y = [y for t in fig.data if isinstance(t, go.Bar) for y in t.y]
        assert pytest.approx(sorted(all_y)) == sorted([0.3, 0.7, 1.2])

    def test_mae_x_labels_match_all_foods(self):
        """All food names must appear in the single bar trace."""
        fig = self._fig()
        bar = next(t for t in fig.data if isinstance(t, go.Bar))
        assert list(bar.x) == ["chicken", "tomato", "salsa"]
        assert pytest.approx(list(bar.y)) == [0.3, 0.7, 1.2]

    def test_safety_threshold_line_at_0_5(self):
        fig = self._fig()
        shapes = fig.layout.shapes
        threshold_lines = [
            s for s in shapes
            if s.type == "line" and s.y0 == s.y1 == charts.MAE_SAFETY_THRESHOLD
        ]
        assert threshold_lines, "MAE=0.5 threshold line not found"

    def test_barmode_is_group(self):
        assert self._fig().layout.barmode == "group"

    def test_legend_title_empty_for_single_model(self):
        legend = self._fig().layout.legend
        assert legend.title is None or legend.title.text in ("", None)

    def test_missing_mae_defaults_to_zero(self):
        """Food with no mae field must not crash; defaults to 0.0."""
        food_no_mae = {"food_name": "mystery", "difficulty": "easy", "ph_stats": {}}
        fig = charts.mae_by_food_chart(_make_results([("M", [food_no_mae])]))
        bar_traces = [t for t in fig.data if isinstance(t, go.Bar)]
        assert list(bar_traces[0].y) == [0.0]

    def test_food_missing_ph_stats_key_defaults_to_zero(self):
        food_no_stats = {"food_name": "mystery", "difficulty": "easy"}
        fig = charts.mae_by_food_chart(_make_results([("M", [food_no_stats])]))
        bar_traces = [t for t in fig.data if isinstance(t, go.Bar)]
        assert list(bar_traces[0].y) == [0.0]

    def test_single_food_produces_one_trace(self):
        """Single food produces one bar trace."""
        fig = charts.mae_by_food_chart(_make_results([("M", [_MAE_FOOD_EASY])]))
        bar_traces = [t for t in fig.data if isinstance(t, go.Bar)]
        assert len(bar_traces) == 1

    def test_empty_foods_list_one_empty_trace(self):
        fig = charts.mae_by_food_chart(_make_results([("M", [])]))
        bar_traces = [t for t in fig.data if isinstance(t, go.Bar)]
        assert len(bar_traces) == 1
        assert len(bar_traces[0].x) == 0

    def test_food_with_unknown_difficulty_is_still_shown(self):
        """Foods with any difficulty value are shown (difficulty is ignored)."""
        food_unknown = {"food_name": "mystery", "difficulty": None, "ph_stats": {"mae": 0.5}}
        fig = charts.mae_by_food_chart(_make_results([("M", [food_unknown])]))
        bar_traces = [t for t in fig.data if isinstance(t, go.Bar)]
        assert len(bar_traces) == 1
        assert list(bar_traces[0].x) == ["mystery"]


class TestMaeByFoodChartEmptyResults:
    def test_empty_results_returns_figure(self):
        """mae_by_food_chart([]) must return a Figure without raising."""
        fig = charts.mae_by_food_chart([])
        assert isinstance(fig, go.Figure)

    def test_empty_results_no_bar_traces(self):
        """Empty results must produce no Bar traces (chart is truly empty)."""
        fig = charts.mae_by_food_chart([])
        bar_traces = [t for t in fig.data if isinstance(t, go.Bar)]
        assert not bar_traces

    def test_empty_results_title_mentions_no_data(self):
        """Title must indicate the absent data so the chart is self-describing."""
        fig = charts.mae_by_food_chart([])
        assert "no data" in fig.layout.title.text.lower()


class TestMaeByFoodChartMultiModel:
    def _fig(self):
        results = _make_results([
            ("ModelA", [_MAE_FOOD_EASY, _MAE_FOOD_MEDIUM]),
            ("ModelB", [_MAE_FOOD_EASY, _MAE_FOOD_MEDIUM]),
        ])
        return charts.mae_by_food_chart(results)

    def test_one_trace_per_model(self):
        """Multi-model: one Bar trace per model."""
        fig = self._fig()
        bar_traces = [t for t in fig.data if isinstance(t, go.Bar)]
        assert len(bar_traces) == 2

    def test_trace_names_are_model_names(self):
        fig = self._fig()
        names = {t.name for t in fig.data if isinstance(t, go.Bar)}
        assert names == {"ModelA", "ModelB"}

    def test_models_get_distinct_colors(self):
        fig = self._fig()
        colors = [t.marker.color for t in fig.data if isinstance(t, go.Bar)]
        assert colors[0] != colors[1], "Multi-model bars must have distinct colors"

    def test_legend_title_is_model_for_multi_model(self):
        assert self._fig().layout.legend.title.text == "Model"

    def test_safety_threshold_line_present(self):
        fig = self._fig()
        threshold_lines = [
            s for s in fig.layout.shapes
            if s.type == "line" and s.y0 == s.y1 == charts.MAE_SAFETY_THRESHOLD
        ]
        assert threshold_lines


# ---------------------------------------------------------------------------
# boundary_crossing_histogram (Exp 1.1 — Section 6)
# ---------------------------------------------------------------------------

_PH_SAMPLES_CROSSING = [4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9]
# 4 values ≤ 4.6 (4.3, 4.4, 4.5, 4.6) → 57%; 3 values > 4.6 (4.7, 4.8, 4.9) → 43%


class TestBoundaryCrossingHistogram:
    def test_returns_figure(self):
        fig = charts.boundary_crossing_histogram(_PH_SAMPLES_CROSSING, "salsa")
        assert isinstance(fig, go.Figure)

    def test_histogram_trace_present(self):
        fig = charts.boundary_crossing_histogram(_PH_SAMPLES_CROSSING, "salsa")
        hist_traces = [t for t in fig.data if isinstance(t, go.Histogram)]
        assert len(hist_traces) == 1

    def test_ph_values_in_histogram(self):
        fig = charts.boundary_crossing_histogram(_PH_SAMPLES_CROSSING, "salsa")
        hist = next(t for t in fig.data if isinstance(t, go.Histogram))
        assert list(hist.x) == _PH_SAMPLES_CROSSING

    def test_ph_46_boundary_line_present_and_red(self):
        """pH 4.6 vertical line must be present and red."""
        fig = charts.boundary_crossing_histogram(_PH_SAMPLES_CROSSING, "salsa")
        vlines = [s for s in fig.layout.shapes if s.type == "line" and s.x0 == s.x1]
        boundary = [s for s in vlines if s.x0 == charts.PH_SAFETY_BOUNDARY]
        assert boundary, "pH 4.6 vertical line not found"
        assert boundary[0].line.color == "#D62728"

    def test_reference_ph_line_present_when_provided(self):
        fig = charts.boundary_crossing_histogram(_PH_SAMPLES_CROSSING, "salsa", reference_ph=4.5)
        vlines = [s for s in fig.layout.shapes if s.type == "line" and s.x0 == s.x1]
        ref_line = next((s for s in vlines if s.x0 == 4.5), None)
        assert ref_line is not None, "Reference pH vertical line not found"
        assert ref_line.line.color == "black", "Reference line must be black"
        assert ref_line.line.dash == "dash", "Reference line must be dashed"

    def test_no_reference_line_when_not_provided(self):
        """When reference_ph is None, only the safety boundary line is added."""
        fig = charts.boundary_crossing_histogram(_PH_SAMPLES_CROSSING, "salsa")
        vlines = [s for s in fig.layout.shapes if s.type == "line" and s.x0 == s.x1]
        # Only the 4.6 boundary line — no second line.
        assert len(vlines) == 1
        assert vlines[0].x0 == charts.PH_SAFETY_BOUNDARY

    def test_fraction_annotation_present(self):
        """Annotation on the 4.6 line must reference pH 4.6 and contain fractions."""
        fig = charts.boundary_crossing_histogram(_PH_SAMPLES_CROSSING, "salsa")
        annotation_texts = " ".join(a.text for a in fig.layout.annotations if a.text)
        assert "pH 4.6" in annotation_texts, "Boundary annotation must mention 'pH 4.6'"
        assert "%" in annotation_texts, "Boundary annotation must contain percentage values"

    def test_fraction_values_are_correct(self):
        """4 of 7 samples ≤ 4.6 → 57%; 3 of 7 > 4.6 → 43%.

        Checks the boundary annotation specifically (not joined across all annotations)
        so the assertion is robust against annotation reordering and extra annotations.
        Annotation format: "pH 4.6 ({pct_below:.0f}% ≤ / {pct_above:.0f}% >)"
        """
        fig = charts.boundary_crossing_histogram(_PH_SAMPLES_CROSSING, "salsa")
        boundary_annotation = next(
            a.text for a in fig.layout.annotations if a.text and "pH 4.6" in a.text
        )
        # 4 of 7 samples ≤ 4.6 (57%) must appear on the ≤ side.
        assert "57% ≤" in boundary_annotation, (
            f"Expected '57% ≤' on the safe side; got: {boundary_annotation!r}"
        )
        # 3 of 7 samples > 4.6 (43%) must appear on the > side.
        assert "43% >" in boundary_annotation, (
            f"Expected '43% >' on the risk side; got: {boundary_annotation!r}"
        )

    def test_title_contains_food_name(self):
        fig = charts.boundary_crossing_histogram(_PH_SAMPLES_CROSSING, "salsa")
        assert "salsa" in fig.layout.title.text

    def test_empty_ph_values_does_not_crash(self):
        """Empty sample list must return a figure without raising."""
        fig = charts.boundary_crossing_histogram([], "mystery")
        assert isinstance(fig, go.Figure)

    def test_all_samples_below_boundary(self):
        """All samples ≤ 4.6: below side = 100%, above side = 0%."""
        samples = [3.5, 4.0, 4.6]
        fig = charts.boundary_crossing_histogram(samples, "pickle")
        annotation = next(
            a.text for a in fig.layout.annotations if a.text and "pH 4.6" in a.text
        )
        assert "100% ≤" in annotation, f"Expected '100% ≤'; got: {annotation!r}"
        assert "0% >" in annotation, f"Expected '0% >'; got: {annotation!r}"

    def test_all_samples_above_boundary(self):
        """All samples > 4.6: below side = 0%, above side = 100%."""
        samples = [4.7, 4.8, 5.0]
        fig = charts.boundary_crossing_histogram(samples, "high-acid")
        annotation = next(
            a.text for a in fig.layout.annotations if a.text and "pH 4.6" in a.text
        )
        assert "0% ≤" in annotation, f"Expected '0% ≤'; got: {annotation!r}"
        assert "100% >" in annotation, f"Expected '100% >'; got: {annotation!r}"


# ---------------------------------------------------------------------------
# growth_propagation_chart (Exp 1.1 — Section 5)
# ---------------------------------------------------------------------------

# Base food dicts for growth propagation tests — always deep-copy before use.
_GP_FOOD_SAFE = {
    "food_name": "pickles",
    "growth_propagation": {
        "log_increase_min": 0.1,
        "log_increase_max": 0.4,
        "log_increase_range": 0.3,
    },
}
_GP_FOOD_IMPACTED = {
    "food_name": "chicken",
    "growth_propagation": {
        "log_increase_min": 0.8,
        "log_increase_max": 1.5,
        "log_increase_range": 0.7,
    },
}
_GP_FOOD_STRADDLING = {
    "food_name": "salsa",
    "growth_propagation": {
        "log_increase_min": 0.7,
        "log_increase_max": 1.0,  # exactly at default threshold
        "log_increase_range": 0.3,
    },
}
_GP_FOOD_NO_GP = {
    "food_name": "mystery",
    # No growth_propagation key — must be skipped.
}
_LOG_THRESHOLD = 1.0


@pytest.fixture()
def gp_foods():
    """Deep-copied list of GP test foods."""
    return _copy.deepcopy([_GP_FOOD_SAFE, _GP_FOOD_IMPACTED, _GP_FOOD_STRADDLING])


class TestGrowthPropagationChart:
    def test_returns_figure(self, gp_foods):
        fig = charts.growth_propagation_chart(gp_foods, _LOG_THRESHOLD)
        assert isinstance(fig, go.Figure)

    def test_empty_gp_data_returns_empty_figure(self):
        """When no foods have growth_propagation data, return a titled empty figure."""
        fig = charts.growth_propagation_chart([], _LOG_THRESHOLD)
        assert isinstance(fig, go.Figure)
        assert not fig.data or not any(isinstance(t, go.Bar) for t in fig.data)
        assert "no data" in fig.layout.title.text.lower()

    def test_foods_without_gp_key_are_skipped(self):
        """Foods missing growth_propagation must be silently excluded (fail-closed)."""
        foods = _copy.deepcopy([_GP_FOOD_NO_GP, _GP_FOOD_SAFE])
        fig = charts.growth_propagation_chart(foods, _LOG_THRESHOLD)
        bars = [t for t in fig.data if isinstance(t, go.Bar)]
        all_food_names = [name for b in bars for name in b.y]
        assert all_food_names == ["pickles"]

    def test_bars_are_horizontal(self, gp_foods):
        fig = charts.growth_propagation_chart(gp_foods, _LOG_THRESHOLD)
        bar = next(t for t in fig.data if isinstance(t, go.Bar))
        assert bar.orientation == "h"

    def test_bar_base_is_log_increase_min(self, gp_foods):
        """Each bar must start at log_increase_min (base), not at zero."""
        fig = charts.growth_propagation_chart(gp_foods, _LOG_THRESHOLD)
        bars = [t for t in fig.data if isinstance(t, go.Bar)]
        food_mins = {
            "pickles": 0.1,
            "chicken": 0.8,
            "salsa": 0.7,
        }
        for bar in bars:
            for name, base in zip(bar.y, bar.base):
                assert pytest.approx(base) == food_mins[name], (
                    f"{name}: expected base={food_mins[name]}, got {base}"
                )

    def test_bar_width_is_log_increase_range(self, gp_foods):
        """Bar x-width = log_increase_max - log_increase_min (non-negative)."""
        fig = charts.growth_propagation_chart(gp_foods, _LOG_THRESHOLD)
        bars = [t for t in fig.data if isinstance(t, go.Bar)]
        food_widths = {
            "pickles": 0.3,   # 0.4 - 0.1
            "chicken": 0.7,   # 1.5 - 0.8
            "salsa": 0.3,     # 1.0 - 0.7
        }
        for bar in bars:
            for name, width in zip(bar.y, bar.x):
                assert pytest.approx(width, abs=1e-6) == food_widths[name], (
                    f"{name}: expected width={food_widths[name]}, got {width}"
                )

    def test_three_color_categories(self, gp_foods):
        """Bars use three colors: green (below), amber (crossing), red (above)."""
        fig = charts.growth_propagation_chart(gp_foods, _LOG_THRESHOLD)
        bars = [t for t in fig.data if isinstance(t, go.Bar)]
        color_by_food = {}
        for bar in bars:
            for name in bar.y:
                color_by_food[name] = bar.marker.color
        # chicken: min=0.8 < 1.0 <= max=1.5 → crossing (amber)
        assert color_by_food["chicken"] == charts._GP_COLOR_CROSSING, "chicken must be amber (crossing)"
        # salsa: min=0.7 < 1.0 <= max=1.0 → crossing (amber)
        assert color_by_food["salsa"] == charts._GP_COLOR_CROSSING, "salsa must be amber (crossing)"
        # pickles: max=0.4 < 1.0 → below (green)
        assert color_by_food["pickles"] == charts._GP_COLOR_BELOW, "pickles must be green (below)"

    def test_fully_above_threshold_is_red(self):
        """A food with min >= threshold must be red (fully above)."""
        food = {
            "food_name": "dangerous",
            "growth_propagation": {
                "log_increase_min": 1.5,
                "log_increase_max": 2.0,
            },
        }
        fig = charts.growth_propagation_chart([food], _LOG_THRESHOLD)
        bar = next(t for t in fig.data if isinstance(t, go.Bar))
        assert bar.marker.color == charts._GP_COLOR_ABOVE

    def test_safe_bars_are_green(self, gp_foods):
        """Bars where log_increase_max < threshold must be green."""
        fig = charts.growth_propagation_chart(gp_foods, _LOG_THRESHOLD)
        bars = [t for t in fig.data if isinstance(t, go.Bar)]
        color_by_food = {}
        for bar in bars:
            for name in bar.y:
                color_by_food[name] = bar.marker.color
        assert color_by_food["pickles"] == charts._GP_COLOR_BELOW, "pickles must be green"

    def test_threshold_line_is_present_and_red(self, gp_foods):
        """Vertical threshold line must appear at log_threshold in red.

        Note: ``add_vline(x=v)`` in Plotly stores the shape with ``xref="x"``
        and ``x0 == x1 == v`` (data-space).  This assertion relies on that
        behavior (verified against Plotly ≥5.x).
        """
        fig = charts.growth_propagation_chart(gp_foods, _LOG_THRESHOLD)
        vlines = [s for s in fig.layout.shapes if s.type == "line" and s.x0 == s.x1]
        threshold_lines = [s for s in vlines if s.x0 == pytest.approx(_LOG_THRESHOLD)]
        assert threshold_lines, f"No vertical line found at x={_LOG_THRESHOLD}"
        assert threshold_lines[0].line.color == "#D62728"

    def test_impacted_bars_sorted_to_top(self, gp_foods):
        """Impacted foods must appear at the TOP of the Y axis.

        In Plotly horizontal bar charts the LAST trace renders at the top.
        With the fixture (one safe food, two crossing), pickles must be in
        the first trace and crossing foods in a later trace.
        """
        fig = charts.growth_propagation_chart(gp_foods, _LOG_THRESHOLD)
        bars = [t for t in fig.data if isinstance(t, go.Bar)]
        food_order = [name for b in bars for name in b.y]
        assert food_order[0] == "pickles", (
            f"Safe food must be first (chart bottom); got order: {food_order}"
        )
        impacted = {"chicken", "salsa"}
        assert set(food_order[1:]) == impacted, (
            f"Impacted foods must be last; got: {food_order[1:]}"
        )

    def test_exact_threshold_boundary_is_crossing(self):
        """A bar where log_increase_max == log_threshold and min < threshold
        must be amber (crossing), not green.

        This is the safety-critical boundary: a food whose worst-case growth
        exactly reaches the threshold must be flagged.
        """
        food_at_boundary = {
            "food_name": "boundary_food",
            "growth_propagation": {
                "log_increase_min": 0.5,
                "log_increase_max": _LOG_THRESHOLD,  # exactly at threshold
            },
        }
        fig = charts.growth_propagation_chart([food_at_boundary], _LOG_THRESHOLD)
        bar = next(t for t in fig.data if isinstance(t, go.Bar))
        color = bar.marker.color
        assert color == charts._GP_COLOR_CROSSING, (
            f"log_increase_max == log_threshold (min < threshold) must be amber; got {color!r}"
        )

    def test_changing_threshold_changes_colors(self):
        """Raising the threshold above all maxima makes all bars green."""
        foods = _copy.deepcopy([_GP_FOOD_IMPACTED])  # min=0.8, max=1.5
        fig_low = charts.growth_propagation_chart(foods, 1.0)
        fig_high = charts.growth_propagation_chart(foods, 2.0)
        bar_low = next(t for t in fig_low.data if isinstance(t, go.Bar))
        bar_high = next(t for t in fig_high.data if isinstance(t, go.Bar))
        # At threshold=1.0: chicken (min=0.8, max=1.5) crosses → amber.
        assert bar_low.marker.color == charts._GP_COLOR_CROSSING
        # At threshold=2.0: chicken (max=1.5) is below threshold → green.
        assert bar_high.marker.color == charts._GP_COLOR_BELOW

    def test_food_with_partial_gp_is_skipped(self):
        """GP data with only log_increase_min (no max) must be excluded (fail-closed).

        A half-populated GP record must never be assumed safe — skip it rather
        than defaulting log_increase_max to 0 or assuming no growth.
        """
        food_no_max = {
            "food_name": "partial_food",
            "growth_propagation": {"log_increase_min": 0.5},  # no log_increase_max
        }
        fig = charts.growth_propagation_chart([food_no_max], _LOG_THRESHOLD)
        # No bar should be rendered (food excluded).
        bar_traces = [t for t in fig.data if isinstance(t, go.Bar)]
        assert not bar_traces or list(bar_traces[0].y) == [], (
            "Food with missing log_increase_max must be excluded from the chart"
        )

    def test_food_with_only_max_no_min_is_skipped(self):
        """GP data with only log_increase_max (no min) must also be excluded."""
        food_no_min = {
            "food_name": "partial_food2",
            "growth_propagation": {"log_increase_max": 1.5},  # no log_increase_min
        }
        fig = charts.growth_propagation_chart([food_no_min], _LOG_THRESHOLD)
        bar_traces = [t for t in fig.data if isinstance(t, go.Bar)]
        assert not bar_traces or list(bar_traces[0].y) == [], (
            "Food with missing log_increase_min must be excluded from the chart"
        )

    def test_food_with_inverted_range_is_skipped(self):
        """A food where log_increase_max < log_increase_min is corrupted data.

        It must be excluded rather than silently rendered as a zero-width bar,
        which would be invisible and potentially miscounted as safe.
        """
        food_inverted = {
            "food_name": "corrupted_food",
            "growth_propagation": {
                "log_increase_min": 1.5,
                "log_increase_max": 0.5,  # inverted: max < min
            },
        }
        fig = charts.growth_propagation_chart([food_inverted], _LOG_THRESHOLD)
        bar_traces = [t for t in fig.data if isinstance(t, go.Bar)]
        assert not bar_traces or list(bar_traces[0].y) == [], (
            "Food with inverted range (max < min) must be excluded from the chart"
        )

    def test_all_foods_safe_no_red_bars(self):
        """When no bar reaches the threshold, all bars are green."""
        foods = _copy.deepcopy([_GP_FOOD_SAFE])  # max=0.4
        fig = charts.growth_propagation_chart(foods, 2.0)
        bar = next(t for t in fig.data if isinstance(t, go.Bar))
        # Normalise: Plotly may return a scalar string for a single-bar trace.
        colors = bar.marker.color
        if isinstance(colors, str):
            colors = [colors]
        assert all(c == "#2CA02C" for c in colors)

    def test_all_foods_impacted_no_green_bars(self):
        """When every bar reaches the threshold, all bars are red."""
        foods = _copy.deepcopy([_GP_FOOD_IMPACTED])  # max=1.5
        fig = charts.growth_propagation_chart(foods, 0.5)
        bar = next(t for t in fig.data if isinstance(t, go.Bar))
        # Normalise: Plotly may return a scalar string for a single-bar trace.
        colors = bar.marker.color
        if isinstance(colors, str):
            colors = [colors]
        assert all(c == "#D62728" for c in colors)

    def test_title_contains_threshold_value(self, gp_foods):
        """Figure title must include the threshold so it's self-documenting.

        The implementation formats with ``f"{log_threshold:.1f}"`` so 1.0 → "1.0".
        """
        fig = charts.growth_propagation_chart(gp_foods, _LOG_THRESHOLD)
        assert "1.0" in fig.layout.title.text

    def test_axes_labelled(self, gp_foods):
        fig = charts.growth_propagation_chart(gp_foods, _LOG_THRESHOLD)
        assert "log" in fig.layout.xaxis.title.text.lower()
        assert "food" in fig.layout.yaxis.title.text.lower()

    def test_only_foods_missing_gp_all_skipped_returns_empty(self):
        """All foods lack growth_propagation → same empty-state as no foods."""
        foods = _copy.deepcopy([_GP_FOOD_NO_GP, _GP_FOOD_NO_GP])
        fig = charts.growth_propagation_chart(foods, _LOG_THRESHOLD)
        assert "no data" in fig.layout.title.text.lower()


# ---------------------------------------------------------------------------
# model_comparison_bars (Exp 1.1 — Section 7)
# ---------------------------------------------------------------------------

def _make_comparison_results(models: list[tuple[str, float, float]]) -> list[dict]:
    """Build a minimal results list for model_comparison_bars tests.

    Each tuple is (model_name, overall_mae, overall_stdev).
    """
    return [
        {
            "model": name,
            "summary": {"overall_mae": mae, "overall_stdev": stdev},
        }
        for name, mae, stdev in models
    ]


class TestModelComparisonBars:
    def _two_model_results(self):
        return _make_comparison_results([("ModelA", 0.4, 0.2), ("ModelB", 0.7, 0.5)])

    def test_returns_figure(self):
        fig = charts.model_comparison_bars(self._two_model_results(), "overall_mae", "MAE")
        assert isinstance(fig, go.Figure)

    def test_one_bar_per_model(self):
        """One Bar trace with N x-values — one per model."""
        fig = charts.model_comparison_bars(self._two_model_results(), "overall_mae", "MAE")
        bars = [t for t in fig.data if isinstance(t, go.Bar)]
        assert len(bars) == 1
        assert len(bars[0].x) == 2

    def test_bar_x_values_are_model_names(self):
        fig = charts.model_comparison_bars(self._two_model_results(), "overall_mae", "MAE")
        bar = next(t for t in fig.data if isinstance(t, go.Bar))
        assert list(bar.x) == ["ModelA", "ModelB"]

    def test_bar_y_values_match_metric(self):
        """Y values must come from the specified summary metric."""
        fig = charts.model_comparison_bars(self._two_model_results(), "overall_mae", "MAE")
        bar = next(t for t in fig.data if isinstance(t, go.Bar))
        assert list(bar.y) == pytest.approx([0.4, 0.7])

    def test_stdev_metric_reads_correct_field(self):
        """Requesting overall_stdev returns the stdev values, not MAE."""
        fig = charts.model_comparison_bars(self._two_model_results(), "overall_stdev", "Stdev")
        bar = next(t for t in fig.data if isinstance(t, go.Bar))
        assert list(bar.y) == pytest.approx([0.2, 0.5])

    def test_models_get_distinct_colors(self):
        """All models in the same tier → qualitative palette → distinct colors."""
        fig = charts.model_comparison_bars(self._two_model_results(), "overall_mae", "MAE")
        bar = next(t for t in fig.data if isinstance(t, go.Bar))
        colors = list(bar.marker.color)
        assert colors[0] != colors[1], "Each model must receive a distinct color"

    def test_title_includes_metric_label(self):
        fig = charts.model_comparison_bars(self._two_model_results(), "overall_mae", "MAE")
        assert "MAE" in fig.layout.title.text

    def test_title_falls_back_to_metric_key_when_no_label(self):
        """When metric_label is empty, the metric key itself appears in the title."""
        fig = charts.model_comparison_bars(self._two_model_results(), "overall_mae")
        assert "overall_mae" in fig.layout.title.text

    def test_axes_labelled(self):
        fig = charts.model_comparison_bars(self._two_model_results(), "overall_mae", "MAE")
        assert "Model" in fig.layout.xaxis.title.text
        assert "MAE" in fig.layout.yaxis.title.text

    def test_missing_metric_defaults_to_nan(self):
        """A model whose summary lacks the requested metric gets NaN (not a crash)."""
        import math
        # Build a result with the metric key absent from the start rather than
        # mutating the dict in-place, to stay consistent with the defensive
        # deep-copy pattern used elsewhere in this file.
        results = [{"model": "ModelA", "summary": {"overall_stdev": 0.2}}]
        fig = charts.model_comparison_bars(results, "overall_mae", "MAE")
        bar = next(t for t in fig.data if isinstance(t, go.Bar))
        assert math.isnan(bar.y[0])

    def test_no_summary_key_defaults_to_nan(self):
        """A model with no 'summary' key at all must not crash; value is NaN.

        Pins the r.get("summary", {}) default so a future refactor removing it
        would be caught immediately.
        """
        import math
        results = [{"model": "ModelA"}]  # no "summary" key at all
        fig = charts.model_comparison_bars(results, "overall_mae", "MAE")
        bar = next(t for t in fig.data if isinstance(t, go.Bar))
        assert math.isnan(bar.y[0])

    def test_empty_results_returns_empty_figure(self):
        fig = charts.model_comparison_bars([], "overall_mae", "MAE")
        assert isinstance(fig, go.Figure)
        bars = [t for t in fig.data if isinstance(t, go.Bar)]
        assert not bars
        assert "no data" in fig.layout.title.text.lower()

    def test_single_model_renders_without_error(self):
        results = _make_comparison_results([("OnlyModel", 0.3, 0.1)])
        fig = charts.model_comparison_bars(results, "overall_mae", "MAE")
        bar = next(t for t in fig.data if isinstance(t, go.Bar))
        assert list(bar.x) == ["OnlyModel"]
        assert list(bar.y) == pytest.approx([0.3])

    def test_showlegend_is_false(self):
        """Model names appear on the X axis — the legend is intentionally hidden."""
        fig = charts.model_comparison_bars(self._two_model_results(), "overall_mae", "MAE")
        bar = next(t for t in fig.data if isinstance(t, go.Bar))
        assert bar.showlegend is False

    def test_models_get_distinct_colors_tier_palette(self, monkeypatch):
        """When each model is in a distinct tier, tier-based colors are applied."""
        monkeypatch.setitem(charts._MODEL_TIER, "ModelA", 1)
        monkeypatch.setitem(charts._MODEL_TIER, "ModelB", 2)
        results = _make_comparison_results([("ModelA", 0.4, 0.2), ("ModelB", 0.7, 0.5)])
        fig = charts.model_comparison_bars(results, "overall_mae", "MAE")
        bar = next(t for t in fig.data if isinstance(t, go.Bar))
        colors = list(bar.marker.color)
        assert colors[0] == charts.TIER_COLORS[1]
        assert colors[1] == charts.TIER_COLORS[2]
