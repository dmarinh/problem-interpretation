"""
Unit tests for the overview page helpers.

Tests the best_cost_efficient_model computation with edge cases
for green (>= 90%), amber (>= 70%), and red (< 70%) accuracy thresholds.
"""

import pandas as pd


# ---------------------------------------------------------------------------
# Streamlit page files execute UI calls on import, so we can't import
# best_cost_efficient_model directly. We duplicate the pure helpers here.
# The page file's copies are authoritative; these tests ensure the LOGIC is
# correct. If the functions are ever moved to lib/, update the import.
# ---------------------------------------------------------------------------

_COMPARISON_COLS = {"accuracy", "cost_per_call_usd", "model"}


def _is_comparison_df(df: pd.DataFrame) -> bool:
    """Mirror of the function in pages/1_overview.py."""
    return df is not None and not df.empty and _COMPARISON_COLS.issubset(df.columns)


def best_cost_efficient_model(df: pd.DataFrame) -> str | None:
    """Mirror of the function in pages/1_overview.py."""
    if not _is_comparison_df(df):
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

    def test_per_food_schema_returns_none(self):
        """A DataFrame from Exp 1.1 (per-food columns, no 'accuracy') must return
        None instead of raising KeyError.

        This guards against the overview page crashing when experiments with
        different CSV schemas (like pH stochasticity) are loaded alongside
        model-comparison experiments.
        """
        df = pd.DataFrame([
            {"model": "GPT-4o", "food_name": "chicken", "ph_mae": 0.3,
             "boundary_crossing_rate": 0.0, "crosses_safety_threshold": False},
        ])
        assert best_cost_efficient_model(df) is None

    def test_missing_only_accuracy_column_returns_none(self):
        """DataFrame with cost but no accuracy column must return None."""
        df = pd.DataFrame([
            {"model": "X", "cost_per_call_usd": 0.0005},
        ])
        assert best_cost_efficient_model(df) is None

    def test_missing_only_cost_column_returns_none(self):
        """DataFrame with accuracy but no cost column must return None."""
        df = pd.DataFrame([
            {"model": "X", "accuracy": 0.9},
        ])
        assert best_cost_efficient_model(df) is None
