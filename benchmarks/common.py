"""
Benchmark Common Utilities

Timing, result recording, statistical helpers, and experiment base class.
"""

import json
import csv
import time
import hashlib
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from statistics import mean, stdev, median

from benchmarks.config import RESULTS_DIR


# ---------------------------------------------------------------------------
# Run metadata — captures reproducibility context
# ---------------------------------------------------------------------------

@dataclass
class RunMetadata:
    """Metadata recorded with every experiment run."""
    experiment_id: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    git_commit: str = field(default_factory=lambda: _get_git_commit())
    python_version: str = field(default_factory=lambda: _get_python_version())
    config_hash: str = ""               # Hash of the config used
    duration_seconds: float = 0.0
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _get_git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "unknown"


def _get_python_version() -> str:
    import sys
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


# ---------------------------------------------------------------------------
# Timer context manager
# ---------------------------------------------------------------------------

class Timer:
    """Simple context manager for timing blocks."""

    def __init__(self):
        self.elapsed: float = 0.0
        self._start: float = 0.0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.elapsed = time.perf_counter() - self._start


# ---------------------------------------------------------------------------
# Result recording
# ---------------------------------------------------------------------------

def ensure_results_dir(experiment_id: str) -> Path:
    """Create and return the results directory for an experiment."""
    d = RESULTS_DIR / experiment_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_json(data: Any, path: Path) -> None:
    """Save data as JSON with readable formatting."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str, ensure_ascii=False)


def load_json(path: Path) -> Any:
    """Load JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_csv(rows: list[dict], path: Path) -> None:
    """Save list of dicts as CSV."""
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------

def consistency_rate(values: list[Any]) -> tuple[Any, float]:
    """Return (modal_value, proportion_of_mode) for a list of values.
    
    For measuring extraction reproducibility: what fraction of runs
    produced the most common value?
    """
    if not values:
        return None, 0.0
    from collections import Counter
    counts = Counter(_make_hashable(v) for v in values)
    modal_value, modal_count = counts.most_common(1)[0]
    return modal_value, modal_count / len(values)


def _make_hashable(v: Any) -> Any:
    """Convert a value to something hashable for counting."""
    if isinstance(v, dict):
        return json.dumps(v, sort_keys=True, default=str)
    if isinstance(v, list):
        return tuple(_make_hashable(x) for x in v)
    return v


def coefficient_of_variation(values: list[float]) -> float:
    """CV = stdev / mean. Returns 0 if mean is 0 or fewer than 2 values."""
    values = [v for v in values if v is not None]
    if len(values) < 2:
        return 0.0
    m = mean(values)
    if m == 0:
        return 0.0
    return stdev(values) / abs(m)


def numeric_accuracy(predicted: Optional[float], expected: Optional[float],
                     tolerance: float, is_percentage: bool = False) -> bool:
    """Check if predicted is within tolerance of expected.
    
    If is_percentage, tolerance is a fraction of expected (e.g., 0.15 = ±15%).
    Otherwise, tolerance is an absolute value.
    """
    if predicted is None and expected is None:
        return True
    if predicted is None or expected is None:
        return False
    if is_percentage:
        if expected == 0:
            return predicted == 0
        return abs(predicted - expected) / abs(expected) <= tolerance
    return abs(predicted - expected) <= tolerance


# ---------------------------------------------------------------------------
# Console output helpers
# ---------------------------------------------------------------------------

def print_header(title: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_subheader(title: str) -> None:
    print("\n" + "-" * 70)
    print(f"  {title}")
    print("-" * 70)


def print_table(headers: list[str], rows: list[list[str]],
                col_widths: Optional[list[int]] = None) -> None:
    """Print a simple aligned table to console."""
    if col_widths is None:
        col_widths = [
            max(len(str(h)), max((len(str(r[i])) for r in rows), default=0)) + 2
            for i, h in enumerate(headers)
        ]
    header_line = "".join(str(h).ljust(w) for h, w in zip(headers, col_widths))
    print(header_line)
    print("-" * sum(col_widths))
    for row in rows:
        print("".join(str(c).ljust(w) for c, w in zip(row, col_widths)))
