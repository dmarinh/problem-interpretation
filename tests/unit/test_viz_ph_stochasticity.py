"""
Unit tests for pages/4_ph_stochasticity.py (Phases 1, 5 & 6)

Pure helper functions are duplicated here to avoid importing the Streamlit
page module directly (it executes UI code on import). This mirrors the pattern
used in test_viz_overview.py and test_viz_runner_page.py.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Inline copies of the pure helpers from pages/4_ph_stochasticity.py
# Keep these in sync with the page implementation.
# ---------------------------------------------------------------------------


def generate_key_finding(results: list[dict], log_threshold: float) -> dict:
    """Inline copy — keep in sync with pages/4_ph_stochasticity.py."""
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
            if prev is None or hi > prev["hi"]:
                food_stats[name] = {"lo": lo, "hi": hi, "range": rng}

    n_total = len(food_stats)
    crossing = {
        name: s for name, s in food_stats.items()
        if s["lo"] < log_threshold <= s["hi"]
    }
    above = {
        name: s for name, s in food_stats.items()
        if s["lo"] >= log_threshold
    }

    n_crossing = len(crossing)
    n_above = len(above)

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
    """Return first food dict whose food_name matches, or None.

    A None food_name arg always returns None (fail-closed).
    """
    if food_name is None:
        return None
    return next((f for f in foods if f.get("food_name") == food_name), None)


def build_summary_df(results: list[dict]) -> pd.DataFrame:
    """One-row-per-model summary DataFrame from raw JSON results."""
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
    """Extract run-level metadata from raw JSON results."""
    n_models = len(results)
    if not results:
        return {"temperature": "—", "n_runs": 0, "n_models": 0, "n_foods": 0}

    first = results[0]
    temperature = first.get("temperature", "—")

    foods = first.get("foods") or []
    n_foods = len(foods)

    # Use the first food with n_valid > 0 to avoid a failed first food masking the count.
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_FOOD = {
    "food_id": "F01",
    "food_name": "chicken",
    "difficulty": "easy",
    "reference_ph": 6.3,
    "reference_ph_range": [6.2, 6.4],
    "ph_values": [6.5, 7.0, 7.8, 7.0, 7.0],
    "ph_stats": {
        "n_valid": 5,
        "mean": 7.06,
        "stdev": 0.44,
        "mae": 0.76,
        "boundary_crossing_rate": 0.0,
    },
    "growth_propagation": {
        "n_computed": 5,
        "log_increase_min": 1.497,
        "log_increase_max": 1.75,
        "log_increase_mean": 1.62,
        "log_increase_stdev": 0.10,
        "log_increase_range": 0.25,
        "crosses_log_threshold": False,
    },
    "raw_runs": [],
    "cost_usd": 0.0,
}

FAKE_MODEL_RESULT = {
    "model": "TestModel",
    "litellm_model": "ollama/test",
    "temperature": 0.7,
    "foods": [FAKE_FOOD],
    "summary": {
        "overall_mae": 0.76,
        "overall_stdev": 0.44,
        "foods_with_boundary_crossing": 0,
        "foods_with_safety_impact": 1,
        "total_cost_usd": 0.012,
    },
}


# ---------------------------------------------------------------------------
# build_summary_df
# ---------------------------------------------------------------------------


class TestBuildSummaryDf:
    def test_single_model(self):
        df = build_summary_df([FAKE_MODEL_RESULT])
        assert len(df) == 1
        assert df.iloc[0]["Model"] == "TestModel"
        assert df.iloc[0]["MAE"] == pytest.approx(0.76)
        assert df.iloc[0]["Stdev"] == pytest.approx(0.44)
        assert df.iloc[0]["Boundary Crossings"] == 0
        assert df.iloc[0]["Safety Impacts"] == 1
        assert df.iloc[0]["Total Cost (USD)"] == pytest.approx(0.012)

    def test_multiple_models(self):
        second = {**FAKE_MODEL_RESULT, "model": "SecondModel"}
        df = build_summary_df([FAKE_MODEL_RESULT, second])
        assert len(df) == 2
        assert list(df["Model"]) == ["TestModel", "SecondModel"]

    def test_empty_results(self):
        df = build_summary_df([])
        assert df.empty

    def test_missing_summary_fields_default_gracefully(self):
        """Missing summary fields must not raise — they default to NaN or 0."""
        entry = {"model": "Partial", "summary": {}}
        df = build_summary_df([entry])
        assert df.iloc[0]["Model"] == "Partial"
        assert df.iloc[0]["Boundary Crossings"] == 0
        assert df.iloc[0]["Safety Impacts"] == 0
        assert df.iloc[0]["Total Cost (USD)"] == 0.0
        assert math.isnan(df.iloc[0]["MAE"])
        assert math.isnan(df.iloc[0]["Stdev"])

    def test_missing_summary_key_entirely(self):
        """Entry with no 'summary' key at all must not raise."""
        entry = {"model": "NoSummary"}
        df = build_summary_df([entry])
        assert df.iloc[0]["Model"] == "NoSummary"
        assert df.iloc[0]["Boundary Crossings"] == 0

    def test_missing_model_name_defaults_to_dash(self):
        entry = {"summary": FAKE_MODEL_RESULT["summary"]}
        df = build_summary_df([entry])
        assert df.iloc[0]["Model"] == "—"

    def test_columns_are_correct(self):
        df = build_summary_df([FAKE_MODEL_RESULT])
        expected = {
            "Model",
            "MAE",
            "Stdev",
            "Boundary Crossings",
            "Safety Impacts",
            "Total Cost (USD)",
        }
        assert set(df.columns) == expected


# ---------------------------------------------------------------------------
# extract_run_info
# ---------------------------------------------------------------------------


class TestExtractRunInfo:
    def test_single_model_result(self):
        info = extract_run_info([FAKE_MODEL_RESULT])
        assert info["temperature"] == 0.7
        assert info["n_runs"] == 5  # from ph_stats.n_valid
        assert info["n_models"] == 1
        assert info["n_foods"] == 1

    def test_empty_results(self):
        info = extract_run_info([])
        assert info["temperature"] == "—"
        assert info["n_runs"] == 0
        assert info["n_models"] == 0
        assert info["n_foods"] == 0

    def test_multiple_models_counts_correctly(self):
        second = {**FAKE_MODEL_RESULT, "model": "B"}
        info = extract_run_info([FAKE_MODEL_RESULT, second])
        assert info["n_models"] == 2

    def test_n_foods_from_first_model(self):
        extra_food = {**FAKE_FOOD, "food_id": "F02", "food_name": "tomato"}
        two_foods_result = {**FAKE_MODEL_RESULT, "foods": [FAKE_FOOD, extra_food]}
        info = extract_run_info([two_foods_result])
        assert info["n_foods"] == 2

    def test_missing_temperature_defaults_to_dash(self):
        entry = {k: v for k, v in FAKE_MODEL_RESULT.items() if k != "temperature"}
        info = extract_run_info([entry])
        assert info["temperature"] == "—"

    def test_n_runs_falls_back_to_ph_values_length(self):
        """When ph_stats has no n_valid, fall back to len(ph_values)."""
        food_no_n_valid = {
            **FAKE_FOOD,
            "ph_values": [6.5, 7.0, 7.2],
            "ph_stats": {"mean": 6.9},  # no n_valid
        }
        result = {**FAKE_MODEL_RESULT, "foods": [food_no_n_valid]}
        info = extract_run_info([result])
        assert info["n_runs"] == 3

    def test_missing_foods_key(self):
        """Entry with no foods key must not raise."""
        entry = {"model": "A", "temperature": 0.5}
        info = extract_run_info([entry])
        assert info["n_foods"] == 0
        assert info["n_runs"] == 0

    def test_n_runs_skips_failed_first_food(self):
        """First food has n_valid=0 (all runs failed); second has n_valid=5."""
        failed_food = {**FAKE_FOOD, "food_id": "F00", "ph_stats": {"n_valid": 0}}
        good_food = {**FAKE_FOOD, "food_id": "F01", "ph_stats": {"n_valid": 5}}
        result = {**FAKE_MODEL_RESULT, "foods": [failed_food, good_food]}
        info = extract_run_info([result])
        assert info["n_runs"] == 5

    def test_n_runs_no_ph_stats_key(self):
        """Food with no ph_stats at all falls back to len(ph_values)."""
        food_no_stats = {"food_id": "F99", "ph_values": [6.0, 6.5]}
        result = {**FAKE_MODEL_RESULT, "foods": [food_no_stats]}
        info = extract_run_info([result])
        assert info["n_runs"] == 2

    def test_n_runs_empty_ph_values(self):
        """Food with empty ph_values and no n_valid gives n_runs=0."""
        food_empty = {"food_id": "F99", "ph_values": [], "ph_stats": {}}
        result = {**FAKE_MODEL_RESULT, "foods": [food_empty]}
        info = extract_run_info([result])
        assert info["n_runs"] == 0


# ---------------------------------------------------------------------------
# DIFFICULTY_COLORS constant
# ---------------------------------------------------------------------------


class TestDifficultyColors:
    def test_all_tiers_present(self):
        from benchmarks.visualizations.lib.charts import DIFFICULTY_COLORS

        assert set(DIFFICULTY_COLORS.keys()) == {"easy", "medium", "hard"}

    def test_color_values_are_hex(self):
        from benchmarks.visualizations.lib.charts import DIFFICULTY_COLORS

        for tier, color in DIFFICULTY_COLORS.items():
            assert color.startswith("#"), f"{tier} color {color!r} is not a hex string"
            assert len(color) == 7, f"{tier} color {color!r} is not a 7-char hex"

    def test_semantic_color_assignments(self):
        """Spec §Colors: easy=green, medium=amber, hard=red."""
        from benchmarks.visualizations.lib.charts import DIFFICULTY_COLORS

        assert DIFFICULTY_COLORS["easy"] == "#2CA02C"
        assert DIFFICULTY_COLORS["medium"] == "#FFC107"
        assert DIFFICULTY_COLORS["hard"] == "#D62728"


# ---------------------------------------------------------------------------
# find_food_by_name (Phase 5 — Section 8 helper)
# ---------------------------------------------------------------------------

_FOOD_CHICKEN = {**FAKE_FOOD, "food_name": "chicken", "food_id": "F01"}
_FOOD_TOMATO = {**FAKE_FOOD, "food_name": "tomato", "food_id": "F02"}
_FOOD_SALSA = {**FAKE_FOOD, "food_name": "salsa", "food_id": "F03"}


class TestFindFoodByName:
    def test_finds_existing_food(self):
        food = find_food_by_name([_FOOD_CHICKEN, _FOOD_TOMATO], "chicken")
        assert food is not None
        assert food["food_name"] == "chicken"

    def test_returns_none_when_not_found(self):
        assert find_food_by_name([_FOOD_CHICKEN, _FOOD_TOMATO], "salsa") is None

    def test_empty_list_returns_none(self):
        assert find_food_by_name([], "chicken") is None

    def test_returns_first_match_on_duplicate_names(self):
        """When two foods share a name (edge case), first occurrence is returned."""
        food_a = {**FAKE_FOOD, "food_name": "chicken", "food_id": "FIRST"}
        food_b = {**FAKE_FOOD, "food_name": "chicken", "food_id": "SECOND"}
        result = find_food_by_name([food_a, food_b], "chicken")
        assert result["food_id"] == "FIRST"

    def test_single_food_list_match(self):
        result = find_food_by_name([_FOOD_SALSA], "salsa")
        assert result is not None
        assert result["food_id"] == "F03"

    def test_single_food_list_no_match(self):
        assert find_food_by_name([_FOOD_SALSA], "chicken") is None

    def test_food_with_missing_food_name_key_is_skipped(self):
        """A food dict without a food_name key must not be matched (not crash)."""
        food_no_name = {"food_id": "F99", "ph_values": [6.0]}
        result = find_food_by_name([food_no_name, _FOOD_CHICKEN], "chicken")
        assert result is not None
        assert result["food_name"] == "chicken"

    def test_food_name_none_does_not_match_string(self):
        """A food with food_name=None must not match a real name string."""
        food_none_name = {**FAKE_FOOD, "food_name": None}
        result = find_food_by_name([food_none_name], "chicken")
        assert result is None

    def test_case_sensitive_match(self):
        """food_name lookup does not normalise case — 'Chicken' != 'chicken'."""
        result = find_food_by_name([_FOOD_CHICKEN], "Chicken")
        assert result is None

    def test_none_arg_returns_none_not_food_missing_key(self):
        """Passing None as the search arg must return None (fail-closed).

        The implementation uses .get("food_name") which returns None for missing
        keys.  Without a None-arg guard, find_food_by_name(foods, None) would
        accidentally match the first food that has no food_name key.
        """
        food_no_key = {"food_id": "F99"}  # no food_name key → .get() returns None
        result = find_food_by_name([food_no_key, _FOOD_CHICKEN], None)
        assert result is None, (
            "None food_name arg must not match a food with a missing food_name key"
        )


# ---------------------------------------------------------------------------
# generate_key_finding (Phase 6 — Section 9)
# ---------------------------------------------------------------------------

_THRESHOLD = 1.0

# Food helpers: GP data as nested dicts for generate_key_finding tests.
def _food(name: str, hi: float, lo: float, rng: float | None = None) -> dict:
    """Build a minimal food dict with growth_propagation data."""
    return {
        "food_name": name,
        "growth_propagation": {
            "log_increase_min": lo,
            "log_increase_max": hi,
            "log_increase_range": rng if rng is not None else hi - lo,
        },
    }


def _result(model: str, *foods: dict) -> dict:
    """Build a minimal model result dict."""
    return {"model": model, "foods": list(foods)}


class TestGenerateKeyFinding:
    def test_no_impacts_has_impacts_false(self):
        """All foods below threshold → has_impacts=False."""
        result = _result("M", _food("pickle", hi=0.4, lo=0.1))
        finding = generate_key_finding([result], _THRESHOLD)
        assert finding["has_impacts"] is False
        assert finding["n_crossing"] == 0
        assert finding["n_above"] == 0

    def test_no_impacts_worst_food_is_none(self):
        result = _result("M", _food("pickle", hi=0.4, lo=0.1))
        finding = generate_key_finding([result], _THRESHOLD)
        assert finding["worst_food_name"] is None
        assert finding["worst_food_range"] == 0.0

    def test_single_crossing_food(self):
        """Food with lo < threshold <= hi is crossing."""
        result = _result("M", _food("chicken", hi=1.5, lo=0.8, rng=0.7))
        finding = generate_key_finding([result], _THRESHOLD)
        assert finding["has_impacts"] is True
        assert finding["n_crossing"] == 1
        assert finding["n_above"] == 0
        assert finding["n_total"] == 1
        assert finding["worst_food_name"] == "chicken"
        assert finding["worst_food_range"] == pytest.approx(0.7)

    def test_single_above_food(self):
        """Food with lo >= threshold is above (not crossing)."""
        result = _result("M", _food("chicken", hi=1.8, lo=1.5, rng=0.3))
        finding = generate_key_finding([result], _THRESHOLD)
        assert finding["has_impacts"] is True
        assert finding["n_crossing"] == 0
        assert finding["n_above"] == 1
        # worst_food_name only considers crossing foods.
        assert finding["worst_food_name"] is None

    def test_exact_threshold_boundary_counts_as_crossing(self):
        """Food with lo < threshold and hi == threshold is crossing (>= not >)."""
        result = _result("M", _food("boundary_food", hi=_THRESHOLD, lo=0.5))
        finding = generate_key_finding([result], _THRESHOLD)
        assert finding["has_impacts"] is True
        assert finding["n_crossing"] == 1

    def test_worst_food_is_largest_range_among_crossing(self):
        """worst_food_name is chosen by range among crossing foods only."""
        # chicken: lo=1.5, hi=1.8 → above (not crossing) — excluded from worst pick
        # salsa:   lo=0.4, hi=1.2 → crossing, range=0.8 → worst
        r = _result(
            "M",
            _food("chicken", hi=1.8, lo=1.5, rng=0.3),
            _food("salsa", hi=1.2, lo=0.4, rng=0.8),
        )
        finding = generate_key_finding([r], _THRESHOLD)
        assert finding["worst_food_name"] == "salsa"
        assert finding["worst_food_range"] == pytest.approx(0.8)

    def test_n_total_counts_only_foods_with_valid_gp(self):
        """Foods without growth_propagation are excluded from n_total."""
        food_no_gp = {"food_name": "mystery"}  # no growth_propagation
        r = _result("M", _food("chicken", hi=1.5, lo=0.8), food_no_gp)
        finding = generate_key_finding([r], _THRESHOLD)
        assert finding["n_total"] == 1  # only chicken counted

    def test_foods_with_partial_gp_excluded_from_total(self):
        """Foods with only log_increase_min (no max) are excluded (fail-closed)."""
        food_partial = {
            "food_name": "partial",
            "growth_propagation": {"log_increase_min": 0.5},
        }
        r = _result("M", food_partial)
        finding = generate_key_finding([r], _THRESHOLD)
        assert finding["n_total"] == 0
        assert finding["n_crossing"] == 0
        assert finding["n_above"] == 0

    def test_empty_results_returns_zero_counts(self):
        finding = generate_key_finding([], _THRESHOLD)
        assert finding["n_crossing"] == 0
        assert finding["n_above"] == 0
        assert finding["n_total"] == 0
        assert finding["has_impacts"] is False
        assert finding["worst_food_name"] is None

    def test_multi_model_aggregates_worst_case_per_food(self):
        """Same food across two models: keep the higher log_increase_max.

        ModelA: chicken hi=0.8 (below threshold)
        ModelB: chicken hi=1.3 (crossing — lo=0.5 < 1.0 <= 1.3) → worst case wins
        """
        r_a = _result("ModelA", _food("chicken", hi=0.8, lo=0.3))
        r_b = _result("ModelB", _food("chicken", hi=1.3, lo=0.5))
        finding = generate_key_finding([r_a, r_b], _THRESHOLD)
        assert finding["n_crossing"] == 1  # chicken counted once, crossing
        assert finding["n_total"] == 1
        # Range must come from ModelB (the winner).
        assert finding["worst_food_range"] == pytest.approx(0.8)  # 1.3 - 0.5

    def test_multi_model_deduplicates_food_names(self):
        """The same food appearing in two models counts as one unique food."""
        r_a = _result("ModelA", _food("chicken", hi=1.5, lo=0.8))
        r_b = _result("ModelB", _food("chicken", hi=1.2, lo=0.6))
        finding = generate_key_finding([r_a, r_b], _THRESHOLD)
        assert finding["n_total"] == 1

    def test_mixed_foods_correct_counts(self):
        """Three foods: one crossing, one above, one safe."""
        r = _result(
            "M",
            _food("chicken", hi=1.5, lo=0.8),   # crossing
            _food("milk", hi=1.8, lo=1.5),       # above
            _food("pickle", hi=0.4, lo=0.1),     # below
        )
        finding = generate_key_finding([r], _THRESHOLD)
        assert finding["n_crossing"] == 1
        assert finding["n_above"] == 1
        assert finding["n_total"] == 3
        assert finding["worst_food_name"] == "chicken"

    def test_log_increase_range_falls_back_to_hi_minus_lo(self):
        """When log_increase_range key is absent, range is computed as hi - lo."""
        food = {
            "food_name": "computed",
            "growth_propagation": {
                "log_increase_min": 0.5,
                "log_increase_max": 1.5,
                # no log_increase_range key
            },
        }
        r = _result("M", food)
        finding = generate_key_finding([r], _THRESHOLD)
        assert finding["worst_food_range"] == pytest.approx(1.0)  # 1.5 - 0.5

    def test_winner_range_replaces_losers_explicit_range(self):
        """When ModelB wins the hi comparison, its log_increase_range replaces
        ModelA's — not ModelA's explicit range field.

        ModelA: hi=0.8 (loser), explicit log_increase_range=2.0 (large but irrelevant).
        ModelB: hi=1.3 (winner), lo=0.5 → crossing, explicit log_increase_range=0.3.
        Result must show 0.3, proving the winner's range is used, not the loser's.
        """
        food_a = {
            "food_name": "chicken",
            "growth_propagation": {
                "log_increase_min": 0.1,
                "log_increase_max": 0.8,
                "log_increase_range": 2.0,  # large but ModelA loses on hi
            },
        }
        food_b = {
            "food_name": "chicken",
            "growth_propagation": {
                "log_increase_min": 0.5,
                "log_increase_max": 1.3,
                "log_increase_range": 0.3,  # ModelB wins on hi → range=0.3 must win
            },
        }
        r_a = _result("ModelA", food_a)
        r_b = _result("ModelB", food_b)
        finding = generate_key_finding([r_a, r_b], _THRESHOLD)
        assert finding["worst_food_range"] == pytest.approx(0.3)

    def test_unnamed_foods_skipped_not_bucketed(self):
        """Foods with missing or falsy food_name must be excluded entirely."""
        food_no_name = {
            "growth_propagation": {
                "log_increase_min": 0.5,
                "log_increase_max": 2.0,  # would dominate if counted
                "log_increase_range": 1.5,
            }
        }
        food_named = _food("chicken", hi=1.2, lo=0.8, rng=0.4)
        r = _result("M", food_no_name, food_named)
        finding = generate_key_finding([r], _THRESHOLD)
        # Only named food counts; unnamed is skipped.
        assert finding["n_total"] == 1
        assert finding["worst_food_name"] == "chicken"
        assert finding["worst_food_range"] == pytest.approx(0.4)
        assert "?" not in (finding["worst_food_name"] or "")
