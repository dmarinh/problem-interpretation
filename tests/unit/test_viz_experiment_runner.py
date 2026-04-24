"""Unit tests for benchmarks.visualizations.lib.experiment_runner."""

from __future__ import annotations

import sys

import pytest

from benchmarks.visualizations.lib import experiment_runner


# ---------------------------------------------------------------------------
# get_available_experiments
# ---------------------------------------------------------------------------


def test_get_available_experiments_finds_exp_3_3():
    experiments = experiment_runner.get_available_experiments()
    ids = [e["id"] for e in experiments]
    assert "exp_3_3_model_comparison" in ids

    exp = next(e for e in experiments if e["id"] == "exp_3_3_model_comparison")
    assert exp["filepath"].exists()
    assert "3.3" in exp["name"]


def test_get_available_experiments_returns_sorted_ids():
    experiments = experiment_runner.get_available_experiments()
    ids = [e["id"] for e in experiments]
    assert ids == sorted(ids)


def test_get_available_experiments_returns_empty_when_dir_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(experiment_runner, "EXPERIMENTS_DIR", tmp_path / "does_not_exist")
    assert experiment_runner.get_available_experiments() == []


def test_get_available_experiments_isolated_dir(monkeypatch, tmp_path):
    """Only matches exp_*.py, ignores unrelated files."""
    monkeypatch.setattr(experiment_runner, "EXPERIMENTS_DIR", tmp_path)
    (tmp_path / "exp_1_alpha.py").write_text("")
    (tmp_path / "exp_2_beta.py").write_text("")
    (tmp_path / "helper.py").write_text("")
    (tmp_path / "notes.md").write_text("")
    ids = [e["id"] for e in experiment_runner.get_available_experiments()]
    assert ids == ["exp_1_alpha", "exp_2_beta"]


def test_humanize_experiment_id_formats_version_and_title():
    assert (
        experiment_runner.humanize_experiment_id("exp_3_3_model_comparison")
        == "Exp 3.3 — Model Comparison"
    )
    assert experiment_runner.humanize_experiment_id("exp_1_ph_test") == "Exp 1 — Ph Test"
    # Version-only (no trailing name parts).
    assert experiment_runner.humanize_experiment_id("exp_4") == "Exp 4"
    # Unexpected shape falls back to the raw id rather than raising.
    assert experiment_runner.humanize_experiment_id("weird_name") == "weird_name"


# ---------------------------------------------------------------------------
# check_model_availability
# ---------------------------------------------------------------------------


def test_check_model_availability_env_var_set(monkeypatch):
    monkeypatch.setenv("TEST_KEY_PRESENT", "sk-abc")
    monkeypatch.delenv("TEST_KEY_MISSING", raising=False)

    models = [
        {"name": "Has key", "api_key_env_var": "TEST_KEY_PRESENT"},
        {"name": "Missing key", "api_key_env_var": "TEST_KEY_MISSING"},
    ]
    enriched = experiment_runner.check_model_availability(models)
    by_name = {m["name"]: m for m in enriched}
    assert by_name["Has key"]["available"] is True
    assert by_name["Missing key"]["available"] is False


def test_check_model_availability_ollama_with_api_base(monkeypatch):
    """Local models (no env var) are available when api_base is set."""
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    models = [
        {
            "name": "Qwen 2.5 14B",
            "api_key_env_var": None,
            "api_base": "http://localhost:11434",
        }
    ]
    enriched = experiment_runner.check_model_availability(models)
    assert enriched[0]["available"] is True


def test_check_model_availability_ollama_unavailable_when_no_env_and_no_api_base(monkeypatch):
    """Local model with neither OLLAMA_HOST nor api_base is not available."""
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    models = [{"name": "Bare local", "api_key_env_var": None, "api_base": None}]
    enriched = experiment_runner.check_model_availability(models)
    assert enriched[0]["available"] is False


def test_check_model_availability_ollama_available_via_ollama_host(monkeypatch):
    """OLLAMA_HOST alone (no api_base in model config) makes local model available."""
    monkeypatch.setenv("OLLAMA_HOST", "http://remote-ollama:11434")
    models = [{"name": "Hosted local", "api_key_env_var": None, "api_base": None}]
    enriched = experiment_runner.check_model_availability(models)
    assert enriched[0]["available"] is True


def test_check_model_availability_does_not_mutate_input():
    models = [{"name": "m", "api_key_env_var": "NOPE"}]
    experiment_runner.check_model_availability(models)
    assert "available" not in models[0]


# ---------------------------------------------------------------------------
# run_experiment (command building — the subprocess handle itself is
# exercised in integration tests gated on API keys)
# ---------------------------------------------------------------------------


def test_run_experiment_builds_expected_command(monkeypatch):
    captured: dict = {}

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs

    monkeypatch.setattr(experiment_runner.subprocess, "Popen", FakePopen)

    experiment_runner.run_experiment(
        experiment_id="exp_3_3_model_comparison",
        models=["GPT-4o", "GPT-4o-mini"],
        runs=3,
        no_mlflow=True,
    )

    cmd = captured["cmd"]
    assert cmd[0] == sys.executable
    assert cmd[1:3] == ["-m", "benchmarks.experiments.exp_3_3_model_comparison"]
    assert "--runs" in cmd and cmd[cmd.index("--runs") + 1] == "3"
    assert "--models" in cmd and cmd[cmd.index("--models") + 1] == "GPT-4o,GPT-4o-mini"
    assert "--no-mlflow" in cmd

    assert captured["kwargs"]["stdout"] == experiment_runner.subprocess.PIPE
    assert captured["kwargs"]["stderr"] == experiment_runner.subprocess.STDOUT
    assert captured["kwargs"]["bufsize"] == 1
    assert captured["kwargs"]["text"] is True


def test_run_experiment_omits_no_mlflow_by_default(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        experiment_runner.subprocess,
        "Popen",
        lambda cmd, **kw: captured.setdefault("cmd", cmd) or object(),
    )

    experiment_runner.run_experiment(
        experiment_id="exp_3_3_model_comparison",
        models=["GPT-4o"],
        runs=1,
    )

    assert "--no-mlflow" not in captured["cmd"]


def test_run_experiment_omits_models_flag_when_empty(monkeypatch):
    """Empty model list → let the experiment use its default (all available)."""
    captured: dict = {}
    monkeypatch.setattr(
        experiment_runner.subprocess,
        "Popen",
        lambda cmd, **kw: captured.setdefault("cmd", cmd) or object(),
    )

    experiment_runner.run_experiment(
        experiment_id="exp_3_3_model_comparison",
        models=[],
        runs=5,
    )

    assert "--models" not in captured["cmd"]
