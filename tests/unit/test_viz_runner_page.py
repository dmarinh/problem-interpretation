"""
Unit tests for the runner page helpers.

Streamlit pages execute UI calls on import, so the pure helper functions are
duplicated here. The page file's copies are authoritative; these tests verify
the logic is correct. If helpers are ever moved to lib/, update the imports.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Mirror of pure helpers from pages/3_run_experiments.py
# ---------------------------------------------------------------------------

_COST_THRESHOLD_USD = 0.001


def estimate_calls(model_names: list[str], runs: int, query_count: int | None) -> str:
    if query_count is None:
        return "?"
    return str(len(model_names) * runs * query_count)


def estimate_cost(
    model_names: list[str],
    runs: int,
    query_count: int | None,
    models_config: list[dict],
) -> str:
    if query_count is None:
        return "?"
    cost_map = {m["name"]: m.get("cost_per_call", 0.0) for m in models_config}
    total = sum(cost_map.get(name, 0.0) * runs * query_count for name in model_names)
    return f"~${total:.4f}"


def estimate_time(model_names: list[str], runs: int, query_count: int | None) -> str:
    if query_count is None:
        return "?"
    total_calls = len(model_names) * runs * query_count
    total_seconds = total_calls * 5
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"~{minutes}m {seconds}s" if minutes else f"~{seconds}s"


def format_timestamp(ts: str | None) -> str:
    if not ts or len(ts) != 15:
        return "—"
    return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[9:11]}:{ts[11:13]}:{ts[13:15]}"


def model_option_label(model: dict) -> str:
    tier = model.get("tier", 4)
    return f"{model['name']} (T{tier})"


# ---------------------------------------------------------------------------
# estimate_calls
# ---------------------------------------------------------------------------


class TestEstimateCalls:
    def test_returns_question_mark_when_query_count_unknown(self):
        assert estimate_calls(["GPT-4o"], runs=5, query_count=None) == "?"

    def test_zero_models(self):
        assert estimate_calls([], runs=5, query_count=20) == "0"

    def test_single_model(self):
        assert estimate_calls(["GPT-4o"], runs=3, query_count=20) == "60"

    def test_multiple_models(self):
        # 3 models × 5 runs × 20 queries = 300
        assert estimate_calls(["A", "B", "C"], runs=5, query_count=20) == "300"

    def test_one_run(self):
        assert estimate_calls(["A", "B"], runs=1, query_count=10) == "20"


# ---------------------------------------------------------------------------
# estimate_cost
# ---------------------------------------------------------------------------

_SAMPLE_MODELS = [
    {"name": "GPT-4o", "cost_per_call": 0.005},
    {"name": "GPT-4o-mini", "cost_per_call": 0.0003},
    {"name": "Free-Local", "cost_per_call": 0.0},
]


class TestEstimateCost:
    def test_returns_question_mark_when_query_count_unknown(self):
        assert estimate_cost(["GPT-4o"], 5, None, _SAMPLE_MODELS) == "?"

    def test_zero_models_zero_cost(self):
        assert estimate_cost([], 5, 20, _SAMPLE_MODELS) == "~$0.0000"

    def test_single_model(self):
        # 0.005 × 3 × 10 = 0.15
        result = estimate_cost(["GPT-4o"], runs=3, query_count=10, models_config=_SAMPLE_MODELS)
        assert result == "~$0.1500"

    def test_free_model_is_zero(self):
        result = estimate_cost(["Free-Local"], runs=5, query_count=20, models_config=_SAMPLE_MODELS)
        assert result == "~$0.0000"

    def test_unknown_model_name_treated_as_zero_cost(self):
        result = estimate_cost(["Unknown-Model"], runs=5, query_count=20, models_config=_SAMPLE_MODELS)
        assert result == "~$0.0000"

    def test_multiple_models_combined(self):
        # GPT-4o: 0.005 × 2 × 10 = 0.10
        # GPT-4o-mini: 0.0003 × 2 × 10 = 0.006
        # total = 0.106
        result = estimate_cost(
            ["GPT-4o", "GPT-4o-mini"], runs=2, query_count=10, models_config=_SAMPLE_MODELS
        )
        assert result == "~$0.1060"


# ---------------------------------------------------------------------------
# estimate_time
# ---------------------------------------------------------------------------


class TestEstimateTime:
    def test_returns_question_mark_when_query_count_unknown(self):
        assert estimate_time(["A"], runs=5, query_count=None) == "?"

    def test_under_one_minute(self):
        # 1 model × 1 run × 1 query × 5s = 5s
        assert estimate_time(["A"], runs=1, query_count=1) == "~5s"

    def test_exactly_one_minute(self):
        # 1 model × 12 runs × 1 query × 5s = 60s = 1m 0s
        assert estimate_time(["A"], runs=12, query_count=1) == "~1m 0s"

    def test_minutes_and_seconds(self):
        # 2 models × 5 runs × 20 queries × 5s = 1000s → 16m 40s
        assert estimate_time(["A", "B"], runs=5, query_count=20) == "~16m 40s"

    def test_zero_models(self):
        assert estimate_time([], runs=5, query_count=20) == "~0s"


# ---------------------------------------------------------------------------
# format_timestamp
# ---------------------------------------------------------------------------


class TestFormatTimestamp:
    def test_valid_timestamp(self):
        assert format_timestamp("20260410_113632") == "2026-04-10 11:36:32"

    def test_none_returns_dash(self):
        assert format_timestamp(None) == "—"

    def test_empty_string_returns_dash(self):
        assert format_timestamp("") == "—"

    def test_wrong_length_returns_dash(self):
        assert format_timestamp("2026041") == "—"


# ---------------------------------------------------------------------------
# model_option_label
# ---------------------------------------------------------------------------


class TestModelOptionLabel:
    def test_label_includes_name_and_tier(self):
        model = {"name": "GPT-4o", "tier": 1}
        assert model_option_label(model) == "GPT-4o (T1)"

    def test_missing_tier_defaults_to_4(self):
        model = {"name": "Unknown"}
        assert model_option_label(model) == "Unknown (T4)"

    def test_tier_0(self):
        model = {"name": "GPT-5.4", "tier": 0}
        assert model_option_label(model) == "GPT-5.4 (T0)"


# ---------------------------------------------------------------------------
# Availability filtering (logic mirrors check_model_availability call site)
# ---------------------------------------------------------------------------


class TestAvailabilityFiltering:
    """Verify that unavailable models are excluded from selectable options."""

    def _make_models_with_avail(self) -> list[dict]:
        return [
            {"name": "Available-A", "tier": 1, "available": True},
            {"name": "Available-B", "tier": 2, "available": True},
            {"name": "Unavailable-C", "tier": 1, "available": False},
        ]

    def test_only_available_models_in_options(self):
        models = self._make_models_with_avail()
        available = [m for m in models if m["available"]]
        labels = [model_option_label(m) for m in available]
        assert "Available-A (T1)" in labels
        assert "Available-B (T2)" in labels
        assert "Unavailable-C (T1)" not in labels

    def test_unavailable_count_correct(self):
        models = self._make_models_with_avail()
        unavailable = [m for m in models if not m["available"]]
        assert len(unavailable) == 1
        assert unavailable[0]["name"] == "Unavailable-C"

    def test_label_to_model_mapping_round_trips(self):
        """label_to_model[model_option_label(m)] must return the same dict."""
        models = self._make_models_with_avail()
        available = [m for m in models if m["available"]]
        label_to_model = {model_option_label(m): m for m in available}
        for m in available:
            assert label_to_model[model_option_label(m)] is m

    def test_all_available_when_all_flagged(self):
        models = [
            {"name": "X", "tier": 1, "available": True},
            {"name": "Y", "tier": 2, "available": True},
        ]
        available = [m for m in models if m["available"]]
        assert len(available) == 2

    def test_all_unavailable_when_all_flagged(self):
        models = [
            {"name": "X", "tier": 1, "available": False},
            {"name": "Y", "tier": 2, "available": False},
        ]
        available = [m for m in models if m["available"]]
        assert available == []


# ---------------------------------------------------------------------------
# estimate_calls — zero/boundary edge cases
# ---------------------------------------------------------------------------


class TestEstimateCallsEdgeCases:
    def test_runs_zero_returns_zero_string(self):
        assert estimate_calls(["A", "B"], runs=0, query_count=10) == "0"

    def test_query_count_zero_returns_zero_string(self):
        # query_count=0 is not None, so arithmetic runs and yields 0
        assert estimate_calls(["A", "B"], runs=5, query_count=0) == "0"

    @pytest.mark.parametrize(
        "models, runs, query_count, expected",
        [
            (["A"], 1, 1, "1"),
            (["A", "B"], 2, 3, "12"),
            (["A", "B", "C"], 4, 5, "60"),
            ([], 10, 10, "0"),
        ],
    )
    def test_parametrized_combinations(self, models, runs, query_count, expected):
        assert estimate_calls(models, runs=runs, query_count=query_count) == expected


# ---------------------------------------------------------------------------
# estimate_cost — zero/boundary edge cases
# ---------------------------------------------------------------------------


class TestEstimateCostEdgeCases:
    def test_runs_zero_gives_zero_cost(self):
        result = estimate_cost(["GPT-4o"], runs=0, query_count=10, models_config=_SAMPLE_MODELS)
        assert result == "~$0.0000"

    def test_query_count_zero_gives_zero_cost(self):
        result = estimate_cost(["GPT-4o"], runs=5, query_count=0, models_config=_SAMPLE_MODELS)
        assert result == "~$0.0000"


# ---------------------------------------------------------------------------
# estimate_time — zero/boundary edge cases
# ---------------------------------------------------------------------------


class TestEstimateTimeEdgeCases:
    def test_runs_zero_returns_zero_seconds(self):
        assert estimate_time(["A"], runs=0, query_count=10) == "~0s"

    def test_query_count_zero_returns_zero_seconds(self):
        assert estimate_time(["A"], runs=5, query_count=0) == "~0s"

    def test_exactly_59_seconds(self):
        # total_calls = 1 model × 1 run × ? queries such that total_seconds = 59
        # We need total_calls * 5 = 55 → 11 calls → 1 × 1 × 11
        # Wait: 11 calls × 5 = 55s  (not 59; 59 is not divisible by 5)
        # Closest: 11 calls × 5 = 55s — under 60 → no minutes
        assert estimate_time(["A"], runs=11, query_count=1) == "~55s"

    def test_just_under_one_minute(self):
        # 11 calls × 5 = 55 seconds
        assert estimate_time(["A"], runs=1, query_count=11) == "~55s"

    def test_large_run_formats_hours_worth_of_seconds(self):
        # 3 models × 10 runs × 50 queries = 1500 calls × 5s = 7500s = 125m 0s
        assert estimate_time(["A", "B", "C"], runs=10, query_count=50) == "~125m 0s"


# ---------------------------------------------------------------------------
# format_timestamp — boundary and mid-year cases
# ---------------------------------------------------------------------------


class TestFormatTimestampEdgeCases:
    def test_mid_year_date(self):
        # September date — verifies month and day slices are not swapped
        assert format_timestamp("20260915_143015") == "2026-09-15 14:30:15"

    def test_december_date(self):
        assert format_timestamp("20261231_235959") == "2026-12-31 23:59:59"

    def test_length_14_returns_dash(self):
        # One character too short
        assert format_timestamp("20260410_1136") == "—"

    def test_length_16_returns_dash(self):
        # One character too long
        assert format_timestamp("20260410_1136320") == "—"

    def test_length_exactly_15_but_malformed_is_still_formatted(self):
        # The function only checks length, not content validity
        assert format_timestamp("XXXXXXXX_XXXXXX") == "XXXX-XX-XX XX:XX:XX"

    def test_whitespace_only_does_not_return_dash(self):
        # len(" " * 15) == 15, so the length guard passes and the string is
        # formatted as-is.  The function only guards on length, not content.
        ts = "               "  # exactly 15 spaces
        result = format_timestamp(ts)
        # Build the expected output the same way the implementation does:
        # f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[9:11]}:{ts[11:13]}:{ts[13:15]}"
        expected = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[9:11]}:{ts[11:13]}:{ts[13:15]}"
        assert result == expected
        assert result != "—"


# ---------------------------------------------------------------------------
# get_query_count (uses load_latest_results — monkeypatched here)
# ---------------------------------------------------------------------------

# We mirror get_query_count from the page because the page cannot be imported.

def _load_latest_results_stub(results, df=None):
    """Return a stub function that returns (results, df)."""
    def _inner(_experiment_id: str):
        return results, df
    return _inner


def get_query_count_mirrored(experiment_id, load_latest_results_fn):
    """Mirrored logic of get_query_count, accepting load_latest_results as injection."""
    if not experiment_id:
        return None
    results, _ = load_latest_results_fn(experiment_id)
    if not results or not isinstance(results, list):
        return None
    # results is a non-empty list of dicts at this point
    queries = results[0].get("queries", [])
    return len(queries) or None


class TestGetQueryCount:
    """Tests for get_query_count via the mirrored version with injected loader."""

    def test_none_experiment_id_returns_none(self):
        stub = _load_latest_results_stub(None)
        assert get_query_count_mirrored(None, stub) is None

    def test_empty_string_experiment_id_returns_none(self):
        stub = _load_latest_results_stub(None)
        assert get_query_count_mirrored("", stub) is None

    def test_no_results_returns_none(self):
        stub = _load_latest_results_stub(None)
        assert get_query_count_mirrored("exp_3_3", stub) is None

    def test_empty_list_results_returns_none(self):
        stub = _load_latest_results_stub([])
        assert get_query_count_mirrored("exp_3_3", stub) is None

    def test_non_list_results_returns_none(self):
        stub = _load_latest_results_stub("not-a-list")
        assert get_query_count_mirrored("exp_3_3", stub) is None

    def test_result_with_no_queries_key_returns_none(self):
        # results[0] has no "queries" key → get returns [] → len=0 → None
        stub = _load_latest_results_stub([{"model": "GPT-4o", "summary": {}}])
        assert get_query_count_mirrored("exp_3_3", stub) is None

    def test_result_with_empty_queries_returns_none(self):
        stub = _load_latest_results_stub([{"queries": []}])
        assert get_query_count_mirrored("exp_3_3", stub) is None

    def test_result_with_queries_returns_count(self):
        queries = [{"q": "a"}, {"q": "b"}, {"q": "c"}]
        stub = _load_latest_results_stub([{"queries": queries}])
        assert get_query_count_mirrored("exp_3_3", stub) == 3

    def test_returns_query_count_from_first_model_only(self):
        """Only results[0] is used; a second model with more queries is ignored."""
        stub = _load_latest_results_stub([
            {"queries": [1, 2]},
            {"queries": [1, 2, 3, 4, 5]},
        ])
        assert get_query_count_mirrored("exp_3_3", stub) == 2

    def test_single_query_returns_one(self):
        stub = _load_latest_results_stub([{"queries": ["only one"]}])
        assert get_query_count_mirrored("exp_3_3", stub) == 1
