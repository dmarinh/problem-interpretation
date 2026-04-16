"""
Unit tests for the overview page helpers.

Tests the best_cost_efficient_model computation with edge cases
for green (>= 90%), amber (>= 70%), and red (< 70%) accuracy thresholds.
"""

import pandas as pd


# ---------------------------------------------------------------------------
# Streamlit page files execute UI calls on import, so we can't import
# best_cost_efficient_model directly. We duplicate the pure helper here.
# The page file's copy is authoritative; this test ensures the LOGIC is
# correct. If the function is ever moved to lib/, update the import.
# ---------------------------------------------------------------------------


def best_cost_efficient_model(df: pd.DataFrame) -> str | None:
    """Mirror of the function in pages/1_overview.py."""
    if df is None or df.empty:
        return None

    affordable = df[df["cost_per_call_usd"] < 0.001]
    if affordable.empty:
        return None

    best_idx = affordable["accuracy"].idxmax()
    return affordable.loc[best_idx, "model"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _make_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["model", "accuracy", "cost_per_call_usd"])


class TestBestCostEfficientModel:
    def test_none_dataframe(self):
        assert best_cost_efficient_model(None) is None

    def test_empty_dataframe(self):
        assert best_cost_efficient_model(pd.DataFrame()) is None

    def test_no_models_under_threshold(self):
        """All models cost >= $0.001 — no cost-efficient pick."""
        df = _make_df([
            {"model": "Expensive-A", "accuracy": 0.95, "cost_per_call_usd": 0.005},
            {"model": "Expensive-B", "accuracy": 0.90, "cost_per_call_usd": 0.001},
        ])
        assert best_cost_efficient_model(df) is None

    def test_single_affordable_model(self):
        df = _make_df([
            {"model": "Cheap", "accuracy": 0.85, "cost_per_call_usd": 0.0003},
            {"model": "Expensive", "accuracy": 0.95, "cost_per_call_usd": 0.005},
        ])
        assert best_cost_efficient_model(df) == "Cheap"

    def test_picks_highest_accuracy_among_affordable(self):
        df = _make_df([
            {"model": "Cheap-Low", "accuracy": 0.70, "cost_per_call_usd": 0.0001},
            {"model": "Cheap-High", "accuracy": 0.88, "cost_per_call_usd": 0.0003},
            {"model": "Expensive", "accuracy": 0.99, "cost_per_call_usd": 0.02},
        ])
        assert best_cost_efficient_model(df) == "Cheap-High"

    def test_green_accuracy(self):
        """Model with >= 90% accuracy and under cost threshold."""
        df = _make_df([
            {"model": "Green", "accuracy": 0.92, "cost_per_call_usd": 0.0005},
        ])
        assert best_cost_efficient_model(df) == "Green"

    def test_amber_accuracy(self):
        """Model with 70-90% accuracy and under cost threshold."""
        df = _make_df([
            {"model": "Amber", "accuracy": 0.75, "cost_per_call_usd": 0.0002},
        ])
        assert best_cost_efficient_model(df) == "Amber"

    def test_red_accuracy(self):
        """Model with < 70% accuracy — still returned if it's the only affordable one."""
        df = _make_df([
            {"model": "Red", "accuracy": 0.55, "cost_per_call_usd": 0.0001},
        ])
        assert best_cost_efficient_model(df) == "Red"

    def test_zero_cost_models(self):
        """Ollama models with $0 cost should qualify."""
        df = _make_df([
            {"model": "Ollama-14B", "accuracy": 0.91, "cost_per_call_usd": 0.0},
            {"model": "Ollama-7B", "accuracy": 0.80, "cost_per_call_usd": 0.0},
        ])
        assert best_cost_efficient_model(df) == "Ollama-14B"

    def test_boundary_cost_exactly_0001(self):
        """Cost of exactly $0.001 should NOT qualify (strictly less than)."""
        df = _make_df([
            {"model": "Boundary", "accuracy": 0.95, "cost_per_call_usd": 0.001},
        ])
        assert best_cost_efficient_model(df) is None

    def test_boundary_cost_just_under(self):
        """Cost of $0.000999 should qualify."""
        df = _make_df([
            {"model": "JustUnder", "accuracy": 0.90, "cost_per_call_usd": 0.000999},
        ])
        assert best_cost_efficient_model(df) == "JustUnder"
