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

import pandas as pd

# Mirror of _RESULTS_PAGE from pages/3_run_experiments.py
_RESULTS_PAGE: dict[str, tuple[str, str]] = {
    "exp_1_1_ph_stochasticity": (
        "pages/4_ph_stochasticity.py",
        "View pH Stochasticity Results",
    ),
    "exp_3_3_model_comparison": (
        "pages/2_model_comparison.py",
        "View Results in Model Comparison",
    ),
}


def _run_history_row(run_df: pd.DataFrame | None) -> tuple[str, str, str]:
    """Mirror of the run-history cell logic from pages/3_run_experiments.py.

    Returns (models_str, col2_val, col3_val) where the meaning of col2/col3
    depends on schema:
      - Comparison schema (exp_3_3): col2=best accuracy %, col3=total cost/call $
      - Per-food schema (exp_1_1):   col2=mean ph_mae (3dp), col3=safety impact count
      - Unknown / missing:            col2="—", col3="—"

    Keep in sync with pages/3_run_experiments.py run-history loop.
    """
    if run_df is not None and not run_df.empty and "model" in run_df.columns:
        models_str = ", ".join(sorted(run_df["model"].unique().tolist()))
        if "accuracy" in run_df.columns and "cost_per_call_usd" in run_df.columns:
            col2_val = f"{run_df['accuracy'].max():.1%}"
            total_cost = run_df["cost_per_call_usd"].sum()
            col3_val = f"${total_cost:.5f}"
        elif "ph_mae" in run_df.columns:
            col2_val = f"{run_df['ph_mae'].mean():.3f}"
            n_impacted = (
                int(run_df["crosses_safety_threshold"].sum())
                if "crosses_safety_threshold" in run_df.columns
                else 0
            )
            col3_val = str(n_impacted)
        else:
            col2_val = col3_val = "—"
    else:
        models_str = col2_val = col3_val = "—"
    return models_str, col2_val, col3_val


def _column_labels(is_per_food: bool) -> tuple[str, str]:
    """Mirror of the column-label logic from pages/3_run_experiments.py."""
    if is_per_food:
        return "Avg MAE", "Safety impacts"
    return "Best accuracy", "Total cost/call"


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


# ---------------------------------------------------------------------------
# run_experiment — extra_args (Phase 6)
# experiment_runner.py has no Streamlit imports so it can be imported directly.
# ---------------------------------------------------------------------------

import subprocess as _subprocess

from benchmarks.visualizations.lib.experiment_runner import run_experiment


def _capture_cmd(monkeypatch, **kwargs) -> list[str]:
    """Patch subprocess.Popen and return the cmd list that would be executed.

    Module-level so it can be reused by any test class that exercises
    run_experiment without spawning a real process.
    """
    captured: list[list[str]] = []

    class _FakePopen:
        stdout = iter([])
        returncode = 0
        def wait(self):
            pass

    def _fake_popen(cmd, **popen_kwargs):
        captured.append(list(cmd))
        return _FakePopen()

    monkeypatch.setattr(_subprocess, "Popen", _fake_popen)
    run_experiment(**kwargs)
    return captured[0]


class TestRunExperimentExtraArgs:
    """Verify that extra_args are appended correctly to the subprocess command."""

    def test_extra_args_appended_to_command(self, monkeypatch):
        """--temperature and --log-threshold must appear in the command."""
        cmd = _capture_cmd(
            monkeypatch,
            experiment_id="exp_1_1_ph_stochasticity",
            models=["ModelA"],
            runs=5,
            extra_args={"--temperature": "0.7", "--log-threshold": "1.0"},
        )
        assert "--temperature" in cmd
        assert "0.7" in cmd
        assert "--log-threshold" in cmd
        assert "1.0" in cmd

    def test_extra_args_appear_after_models_flag(self, monkeypatch):
        """Extra args must come after --models (the last standard flag).

        Checking against --models (not just --runs) prevents regressions where
        extra args slip between standard flags and corrupt the invocation.
        """
        cmd = _capture_cmd(
            monkeypatch,
            experiment_id="exp_1_1_ph_stochasticity",
            models=["ModelA"],
            runs=3,
            extra_args={"--temperature": "0.5"},
        )
        models_idx = cmd.index("--models")
        temp_idx = cmd.index("--temperature")
        assert temp_idx > models_idx

    def test_extra_args_key_value_are_consecutive(self, monkeypatch):
        """Each flag and its value must be adjacent in the command list."""
        cmd = _capture_cmd(
            monkeypatch,
            experiment_id="exp_1_1_ph_stochasticity",
            models=[],
            runs=1,
            extra_args={"--temperature": "0.9"},
        )
        temp_idx = cmd.index("--temperature")
        assert cmd[temp_idx + 1] == "0.9"

    def test_no_extra_args_does_not_add_flags(self, monkeypatch):
        """Omitting extra_args (None) must not add any unexpected flags."""
        cmd = _capture_cmd(
            monkeypatch,
            experiment_id="exp_1_1_ph_stochasticity",
            models=["ModelA"],
            runs=5,
            extra_args=None,
        )
        assert "--temperature" not in cmd
        assert "--log-threshold" not in cmd

    def test_empty_extra_args_dict_does_not_add_flags(self, monkeypatch):
        """An empty dict extra_args must behave identically to None."""
        cmd = _capture_cmd(
            monkeypatch,
            experiment_id="exp_1_1_ph_stochasticity",
            models=["ModelA"],
            runs=5,
            extra_args={},
        )
        assert "--temperature" not in cmd
        assert "--log-threshold" not in cmd

    def test_multiple_extra_args_all_present(self, monkeypatch):
        """All key-value pairs in extra_args must appear in the command."""
        cmd = _capture_cmd(
            monkeypatch,
            experiment_id="exp_1_1_ph_stochasticity",
            models=[],
            runs=1,
            extra_args={"--temperature": "0.7", "--log-threshold": "2.0"},
        )
        assert "--temperature" in cmd and cmd[cmd.index("--temperature") + 1] == "0.7"
        assert "--log-threshold" in cmd and cmd[cmd.index("--log-threshold") + 1] == "2.0"

    def test_empty_string_value_raises_value_error(self, monkeypatch):
        """An empty-string value in extra_args must raise ValueError.

        Allowing it would silently corrupt the CLI: the next flag would be
        consumed as the value for --temperature, breaking the invocation.
        """
        with pytest.raises(
            ValueError,
            match=r"non-empty string.*--temperature|--temperature.*non-empty string",
        ):
            _capture_cmd(
                monkeypatch,
                experiment_id="exp_1_1_ph_stochasticity",
                models=[],
                runs=1,
                extra_args={"--temperature": ""},
            )


# ---------------------------------------------------------------------------
# _RESULTS_PAGE mapping (post-run navigation link)
# ---------------------------------------------------------------------------


class TestResultsPageMapping:
    def test_exp_1_1_links_to_ph_stochasticity_page(self):
        page, label = _RESULTS_PAGE["exp_1_1_ph_stochasticity"]
        assert "4_ph_stochasticity" in page
        assert label  # non-empty label

    def test_exp_3_3_links_to_model_comparison_page(self):
        page, label = _RESULTS_PAGE["exp_3_3_model_comparison"]
        assert "2_model_comparison" in page
        assert label

    def test_unknown_experiment_falls_back_to_model_comparison(self):
        page, label = _RESULTS_PAGE.get(
            "exp_99_unknown",
            ("pages/2_model_comparison.py", "View Results"),
        )
        assert "2_model_comparison" in page


# ---------------------------------------------------------------------------
# Run history schema branching
# ---------------------------------------------------------------------------


def _make_comparison_run_df(models: list[str]) -> pd.DataFrame:
    """Per-model CSV schema (Exp 3.3)."""
    return pd.DataFrame([
        {"model": m, "accuracy": 0.85 + i * 0.05, "cost_per_call_usd": 0.001 * (i + 1)}
        for i, m in enumerate(models)
    ])


def _make_per_food_run_df(
    models: list[str],
    foods: list[str],
    ph_mae: float = 0.3,
    crosses_safety_threshold: bool = False,
) -> pd.DataFrame:
    """Per-food CSV schema (Exp 1.1).

    Includes crosses_safety_threshold so _run_history_row can compute the
    safety-impact count without falling back to the 0-default path.
    """
    rows = []
    for m in models:
        for f in foods:
            rows.append({
                "model": m,
                "food_name": f,
                "ph_mae": ph_mae,
                "boundary_crossing_rate": 0.0,
                "crosses_safety_threshold": crosses_safety_threshold,
            })
    return pd.DataFrame(rows)


class TestRunHistorySchema:
    # --- comparison schema (exp_3_3) ---

    def test_comparison_schema_extracts_all_fields(self):
        """Per-model CSV (exp_3_3) must yield model names, accuracy %, and cost $."""
        df = _make_comparison_run_df(["ModelA", "ModelB"])
        models_str, col2, col3 = _run_history_row(df)
        assert "ModelA" in models_str
        assert "ModelB" in models_str
        assert col2.endswith("%")
        assert col3.startswith("$")

    def test_comparison_schema_model_names_sorted(self):
        """Model names must be sorted so the display is deterministic."""
        df = _make_comparison_run_df(["Zebra", "Alpha"])
        models_str, _, _ = _run_history_row(df)
        assert models_str == "Alpha, Zebra"

    def test_comparison_schema_best_accuracy_is_max(self):
        """col2 must reflect the highest accuracy row, not mean or first."""
        df = pd.DataFrame([
            {"model": "A", "accuracy": 0.70, "cost_per_call_usd": 0.001},
            {"model": "B", "accuracy": 0.92, "cost_per_call_usd": 0.002},
        ])
        _, col2, _ = _run_history_row(df)
        assert col2 == "92.0%"

    def test_comparison_schema_total_cost_is_sum(self):
        """col3 must be the sum of all models' cost_per_call_usd."""
        df = pd.DataFrame([
            {"model": "A", "accuracy": 0.80, "cost_per_call_usd": 0.001},
            {"model": "B", "accuracy": 0.85, "cost_per_call_usd": 0.002},
        ])
        _, _, col3 = _run_history_row(df)
        assert col3 == "$0.00300"

    # --- per-food schema (exp_1_1) ---

    def test_per_food_schema_shows_mae_and_impact_count(self):
        """Per-food CSV (exp_1_1) must show mean MAE and safety impact count."""
        df = _make_per_food_run_df(["GPT-4o"], ["chicken", "salsa"], ph_mae=0.45)
        models_str, col2, col3 = _run_history_row(df)
        assert models_str == "GPT-4o"
        assert col2 == "0.450"           # mean ph_mae formatted to 3dp
        assert col3 == "0"               # crosses_safety_threshold=False → count 0

    def test_per_food_schema_safety_impact_count(self):
        """Safety impacts count is the number of rows where crosses_safety_threshold=True."""
        df = _make_per_food_run_df(
            ["GPT-4o"], ["chicken", "salsa", "pickle"],
            crosses_safety_threshold=True,
        )
        _, _, col3 = _run_history_row(df)
        assert col3 == "3"  # all 3 food rows flag True

    def test_per_food_schema_mae_mean_across_foods(self):
        """Mean MAE is computed across all food rows, not just first."""
        df = pd.DataFrame([
            {"model": "GPT-4o", "food_name": "chicken", "ph_mae": 0.2, "crosses_safety_threshold": False},
            {"model": "GPT-4o", "food_name": "salsa",   "ph_mae": 0.4, "crosses_safety_threshold": False},
        ])
        _, col2, _ = _run_history_row(df)
        assert col2 == "0.300"  # (0.2 + 0.4) / 2

    def test_per_food_schema_no_crosses_column_defaults_to_zero_impacts(self):
        """If crosses_safety_threshold column is absent, safety impact count must be 0."""
        df = pd.DataFrame([
            {"model": "GPT-4o", "food_name": "chicken", "ph_mae": 0.3},
        ])
        _, _, col3 = _run_history_row(df)
        assert col3 == "0"

    def test_per_food_schema_deduplicates_model_names(self):
        """Each model appears once even though it has one row per food."""
        df = _make_per_food_run_df(["GPT-4o", "Llama"], ["chicken", "salsa", "pickle"])
        models_str, _, _ = _run_history_row(df)
        assert models_str.count("GPT-4o") == 1
        assert models_str.count("Llama") == 1

    # --- unknown / missing data ---

    def test_none_df_returns_all_dashes(self):
        models_str, col2, col3 = _run_history_row(None)
        assert models_str == col2 == col3 == "—"

    def test_empty_df_returns_all_dashes(self):
        models_str, col2, col3 = _run_history_row(pd.DataFrame())
        assert models_str == col2 == col3 == "—"

    def test_df_missing_model_column_returns_all_dashes(self):
        """A malformed CSV without a 'model' column must not crash."""
        df = pd.DataFrame([{"food_name": "chicken"}])
        models_str, col2, col3 = _run_history_row(df)
        assert models_str == col2 == col3 == "—"

    def test_df_with_model_but_unknown_schema_returns_dashes_for_metrics(self):
        """A CSV with a model column but neither accuracy nor ph_mae falls through to '—'."""
        df = pd.DataFrame([{"model": "X", "some_other_col": 1.0}])
        models_str, col2, col3 = _run_history_row(df)
        assert models_str == "X"
        assert col2 == "—"
        assert col3 == "—"


# ---------------------------------------------------------------------------
# Column label switching (is_per_food flag → Avg MAE / Safety impacts)
# ---------------------------------------------------------------------------


class TestColumnLabels:
    def test_comparison_flag_returns_accuracy_cost_headers(self):
        col2_label, col3_label = _column_labels(is_per_food=False)
        assert col2_label == "Best accuracy"
        assert col3_label == "Total cost/call"

    def test_per_food_flag_returns_mae_safety_headers(self):
        col2_label, col3_label = _column_labels(is_per_food=True)
        assert col2_label == "Avg MAE"
        assert col3_label == "Safety impacts"
