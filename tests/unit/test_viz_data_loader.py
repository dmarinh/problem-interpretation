"""
Unit tests for benchmarks.visualizations.lib.data_loader

Uses tmp_path fixtures with fake results to test all loader functions
without depending on real experiment output.
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from benchmarks.config import RESULTS_DIR as REAL_RESULTS_DIR
from benchmarks.visualizations.lib import data_loader


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_RESULTS = [
    {
        "model": "FakeModel",
        "queries": [],
        "summary": {"overall_accuracy": 0.95, "model_type_accuracy": 1.0},
    }
]

FAKE_CSV_CONTENT = (
    "model,accuracy,cost_per_call_usd\n"
    "FakeModel,0.95,0.001\n"
)


@pytest.fixture()
def results_dir(tmp_path, monkeypatch):
    """Create a fake RESULTS_DIR with one experiment."""
    monkeypatch.setattr(data_loader, "RESULTS_DIR", tmp_path)
    return tmp_path


def _create_experiment(results_dir, experiment_id, timestamps=None, create_latest=True):
    """Helper to populate a fake experiment directory."""
    exp_dir = results_dir / experiment_id
    exp_dir.mkdir(parents=True, exist_ok=True)

    if create_latest:
        (exp_dir / "latest.json").write_text(json.dumps(FAKE_RESULTS))
        (exp_dir / "latest.csv").write_text(FAKE_CSV_CONTENT)

    for ts in timestamps or []:
        (exp_dir / f"results_{ts}.json").write_text(json.dumps(FAKE_RESULTS))
        (exp_dir / f"summary_{ts}.csv").write_text(FAKE_CSV_CONTENT)

    return exp_dir


# ---------------------------------------------------------------------------
# load_latest_results
# ---------------------------------------------------------------------------


class TestLoadLatestResults:
    def test_missing_experiment_dir(self, results_dir):
        result_json, result_df = data_loader.load_latest_results("nonexistent")
        assert result_json is None
        assert result_df is None

    def test_loads_valid_results(self, results_dir):
        _create_experiment(results_dir, "exp_test")
        result_json, result_df = data_loader.load_latest_results("exp_test")
        assert result_json == FAKE_RESULTS
        assert isinstance(result_df, pd.DataFrame)
        assert len(result_df) == 1
        assert result_df.iloc[0]["model"] == "FakeModel"

    def test_malformed_json(self, results_dir):
        exp_dir = results_dir / "exp_bad"
        exp_dir.mkdir()
        (exp_dir / "latest.json").write_text("{bad json!!")
        (exp_dir / "latest.csv").write_text(FAKE_CSV_CONTENT)

        result_json, result_df = data_loader.load_latest_results("exp_bad")
        assert result_json is None
        assert result_df is None

    def test_empty_json_file(self, results_dir):
        exp_dir = results_dir / "exp_empty_json"
        exp_dir.mkdir()
        (exp_dir / "latest.json").write_text("")

        result_json, result_df = data_loader.load_latest_results("exp_empty_json")
        assert result_json is None
        assert result_df is None

    def test_malformed_csv(self, results_dir, monkeypatch):
        """CSV that pandas cannot parse triggers _load_csv_safe error path."""
        exp_dir = results_dir / "exp_bad_csv"
        exp_dir.mkdir()
        (exp_dir / "latest.json").write_text(json.dumps(FAKE_RESULTS))
        (exp_dir / "latest.csv").write_text(FAKE_CSV_CONTENT)

        # Force pd.read_csv to raise so we exercise the error path reliably
        def _raise(*args, **kwargs):
            raise pd.errors.ParserError("synthetic parse failure")

        monkeypatch.setattr(pd, "read_csv", _raise)

        result_json, result_df = data_loader.load_latest_results("exp_bad_csv")
        assert result_json == FAKE_RESULTS
        assert result_df is None

    def test_json_exists_but_csv_missing(self, results_dir):
        exp_dir = results_dir / "exp_no_csv"
        exp_dir.mkdir()
        (exp_dir / "latest.json").write_text(json.dumps(FAKE_RESULTS))

        result_json, result_df = data_loader.load_latest_results("exp_no_csv")
        assert result_json == FAKE_RESULTS
        assert result_df is None


# ---------------------------------------------------------------------------
# load_run_by_timestamp
# ---------------------------------------------------------------------------


class TestLoadRunByTimestamp:
    def test_missing_timestamp(self, results_dir):
        _create_experiment(results_dir, "exp_test", timestamps=["20260410_113632"])
        result_json, result_df = data_loader.load_run_by_timestamp(
            "exp_test", "99999999_999999"
        )
        assert result_json is None
        assert result_df is None

    def test_loads_specific_run(self, results_dir):
        _create_experiment(results_dir, "exp_test", timestamps=["20260410_113632"])
        result_json, result_df = data_loader.load_run_by_timestamp(
            "exp_test", "20260410_113632"
        )
        assert result_json == FAKE_RESULTS
        assert isinstance(result_df, pd.DataFrame)

    def test_malformed_json(self, results_dir):
        exp_dir = results_dir / "exp_bad_ts"
        exp_dir.mkdir()
        (exp_dir / "results_20260410_113632.json").write_text("{corrupt!!")
        (exp_dir / "summary_20260410_113632.csv").write_text(FAKE_CSV_CONTENT)

        result_json, result_df = data_loader.load_run_by_timestamp(
            "exp_bad_ts", "20260410_113632"
        )
        assert result_json is None
        assert result_df is None


# ---------------------------------------------------------------------------
# list_available_runs
# ---------------------------------------------------------------------------


class TestListAvailableRuns:
    def test_missing_experiment_dir(self, results_dir):
        assert data_loader.list_available_runs("nonexistent") == []

    def test_sorts_newest_first(self, results_dir):
        timestamps = ["20260408_100000", "20260410_113632", "20260409_120000"]
        _create_experiment(results_dir, "exp_test", timestamps=timestamps)

        runs = data_loader.list_available_runs("exp_test")
        ts_list = [r["timestamp"] for r in runs]
        assert ts_list == ["20260410_113632", "20260409_120000", "20260408_100000"]

    def test_returns_filepath(self, results_dir):
        _create_experiment(results_dir, "exp_test", timestamps=["20260410_113632"])
        runs = data_loader.list_available_runs("exp_test")
        assert len(runs) == 1
        assert runs[0]["filepath"].name == "results_20260410_113632.json"

    def test_ignores_non_timestamp_filenames(self, results_dir):
        exp_dir = _create_experiment(results_dir, "exp_test", timestamps=["20260410_113632"])
        (exp_dir / "results_badname.json").write_text("{}")
        (exp_dir / "results_.json").write_text("{}")

        runs = data_loader.list_available_runs("exp_test")
        assert len(runs) == 1
        assert runs[0]["timestamp"] == "20260410_113632"


# ---------------------------------------------------------------------------
# list_experiments_with_results
# ---------------------------------------------------------------------------


class TestListExperimentsWithResults:
    def test_empty_results_dir(self, results_dir):
        assert data_loader.list_experiments_with_results() == []

    def test_experiment_with_results(self, results_dir):
        _create_experiment(
            results_dir,
            "exp_3_3_model_comparison",
            timestamps=["20260410_113632"],
        )

        experiments = data_loader.list_experiments_with_results()
        assert len(experiments) == 1
        exp = experiments[0]
        assert exp["experiment_id"] == "exp_3_3_model_comparison"
        assert exp["has_results"] is True
        assert exp["latest_timestamp"] == "20260410_113632"

    def test_experiment_without_results(self, results_dir):
        (results_dir / "exp_empty").mkdir()
        experiments = data_loader.list_experiments_with_results()
        assert len(experiments) == 1
        assert experiments[0]["has_results"] is False
        assert experiments[0]["latest_timestamp"] is None

    def test_ignores_hidden_dirs(self, results_dir):
        (results_dir / ".gitkeep").mkdir()
        _create_experiment(results_dir, "exp_test", timestamps=["20260410_113632"])

        experiments = data_loader.list_experiments_with_results()
        assert all(e["experiment_id"] != ".gitkeep" for e in experiments)

    def test_results_dir_does_not_exist(self, tmp_path, monkeypatch):
        nonexistent = tmp_path / "no_such_dir"
        monkeypatch.setattr(data_loader, "RESULTS_DIR", nonexistent)
        assert data_loader.list_experiments_with_results() == []

    def test_ignores_plain_files_in_results_dir(self, results_dir):
        (results_dir / ".gitkeep").write_text("")
        _create_experiment(results_dir, "exp_test", timestamps=["20260410_113632"])

        experiments = data_loader.list_experiments_with_results()
        ids = [e["experiment_id"] for e in experiments]
        assert ".gitkeep" not in ids
        assert "exp_test" in ids


# ---------------------------------------------------------------------------
# load_config_models
# ---------------------------------------------------------------------------


class TestLoadConfigModels:
    def test_returns_list_of_dicts(self):
        models = data_loader.load_config_models()
        assert isinstance(models, list)
        assert len(models) > 0
        assert all(isinstance(m, dict) for m in models)
        assert all("name" in m for m in models)
        assert all("tier" in m for m in models)

    def test_returns_copy(self):
        """Modifying the returned list should not affect the config."""
        models = data_loader.load_config_models()
        models.clear()
        assert len(data_loader.load_config_models()) > 0

    def test_returns_deep_copy(self):
        """Mutating an inner dict should not affect the config."""
        models = data_loader.load_config_models()
        original_name = models[0]["name"]
        models[0]["name"] = "MUTATED"
        assert data_loader.load_config_models()[0]["name"] == original_name


# ---------------------------------------------------------------------------
# Integration: real exp_3_3_model_comparison results
# ---------------------------------------------------------------------------

_REAL_EXP_DIR = REAL_RESULTS_DIR / "exp_3_3_model_comparison"
_has_real_results = (_REAL_EXP_DIR / "latest.json").exists()


@pytest.mark.skipif(not _has_real_results, reason="No real exp_3_3 results on disk")
class TestRealExp33Results:
    """Run loaders against the real exp_3_3_model_comparison results."""

    def test_load_latest_results(self):
        results, df = data_loader.load_latest_results("exp_3_3_model_comparison")
        assert results is not None
        assert isinstance(results, list)
        assert len(results) >= 1
        assert "model" in results[0]
        assert "summary" in results[0]
        assert isinstance(df, pd.DataFrame)
        assert len(df) >= 1

    def test_list_available_runs(self):
        runs = data_loader.list_available_runs("exp_3_3_model_comparison")
        assert len(runs) >= 1
        for run in runs:
            assert "timestamp" in run
            assert Path(run["filepath"]).exists()

    def test_list_experiments_includes_exp_3_3(self):
        experiments = data_loader.list_experiments_with_results()
        ids = [e["experiment_id"] for e in experiments]
        assert "exp_3_3_model_comparison" in ids
        exp = next(e for e in experiments if e["experiment_id"] == "exp_3_3_model_comparison")
        assert exp["has_results"] is True
        assert exp["latest_timestamp"] is not None
