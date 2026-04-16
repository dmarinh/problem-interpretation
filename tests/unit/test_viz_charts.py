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
