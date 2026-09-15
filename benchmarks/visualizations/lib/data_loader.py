"""
Data loader for benchmark results.

Pure functions to load results from disk, independent of UI.
All functions return None / empty list gracefully when files are missing.
"""

import copy
import json
import logging
import re
from pathlib import Path

import pandas as pd

from benchmarks.config import MODELS, RESULTS_DIR

logger = logging.getLogger(__name__)

# Timestamp pattern used in result filenames: YYYYMMDD_HHMMSS
_TIMESTAMP_RE = re.compile(r"(\d{8}_\d{6})")


def load_latest_results(
    experiment_id: str,
) -> tuple[list | None, pd.DataFrame | None]:
    """Load latest.json and latest.csv for an experiment.

    Args:
        experiment_id: e.g., "exp_3_1_model_comparison"

    Returns:
        (results_list, summary_dataframe) or (None, None) if no results exist.
        The results list contains one dict per model with queries and summary.
    """
    exp_dir = RESULTS_DIR / experiment_id

    json_path = exp_dir / "latest.json"
    csv_path = exp_dir / "latest.csv"

    if not json_path.exists():
        return None, None

    results_dict = _load_json_safe(json_path)
    if results_dict is None:
        return None, None
    if not isinstance(results_dict, list):
        logger.warning(
            "Expected a JSON list in %s, got %s — file may be malformed",
            json_path,
            type(results_dict).__name__,
        )
        return None, None

    summary_df = _load_csv_safe(csv_path)
    return results_dict, summary_df


def load_run_by_timestamp(
    experiment_id: str, timestamp: str
) -> tuple[list | None, pd.DataFrame | None]:
    """Load a specific timestamped run.

    Args:
        experiment_id: e.g., "exp_3_1_model_comparison"
        timestamp: e.g., "20260410_113632"

    Returns:
        (results_list, summary_dataframe) or (None, None) if not found.
    """
    exp_dir = RESULTS_DIR / experiment_id

    json_path = exp_dir / f"results_{timestamp}.json"
    csv_path = exp_dir / f"summary_{timestamp}.csv"

    if not json_path.exists():
        return None, None

    results_dict = _load_json_safe(json_path)
    if results_dict is None:
        return None, None
    if not isinstance(results_dict, list):
        logger.warning(
            "Expected a JSON list in %s, got %s — file may be malformed",
            json_path,
            type(results_dict).__name__,
        )
        return None, None

    summary_df = _load_csv_safe(csv_path)
    return results_dict, summary_df


def list_available_runs(experiment_id: str) -> list[dict]:
    """List all runs for an experiment.

    Returns list of {"timestamp": str, "filepath": Path} sorted newest first.
    """
    exp_dir = RESULTS_DIR / experiment_id
    if not exp_dir.is_dir():
        return []

    runs = []
    for path in exp_dir.glob("results_*.json"):
        match = _TIMESTAMP_RE.search(path.stem)
        if match:
            runs.append({"timestamp": match.group(1), "filepath": path})

    runs.sort(key=lambda r: r["timestamp"], reverse=True)
    return runs


def list_experiments_with_results() -> list[dict]:
    """Scan results/ directory for experiments that have results.

    Returns list of {"experiment_id": str, "has_results": bool, "latest_timestamp": str | None}.
    """
    if not RESULTS_DIR.is_dir():
        return []

    experiments = []
    for entry in sorted(RESULTS_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue

        has_results = (entry / "latest.json").exists()
        latest_timestamp = None

        if has_results:
            runs = list_available_runs(entry.name)
            if runs:
                latest_timestamp = runs[0]["timestamp"]

        experiments.append(
            {
                "experiment_id": entry.name,
                "has_results": has_results,
                "latest_timestamp": latest_timestamp,
            }
        )

    return experiments


def load_config_models() -> list[dict]:
    """Load MODELS from config.py. Used by the runner page."""
    return copy.deepcopy(MODELS)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_json_safe(path: Path) -> dict | list | None:
    """Load JSON with graceful error handling."""
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load %s: %s", path, exc)
        return None


def _load_csv_safe(path: Path) -> pd.DataFrame | None:
    """Load CSV with graceful error handling."""
    if not path.exists():
        return None
    try:
        return pd.read_csv(path)
    except (pd.errors.ParserError, OSError, ValueError) as exc:
        logger.warning("Failed to load %s: %s", path, exc)
        return None
