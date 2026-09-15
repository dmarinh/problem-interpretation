"""
Experiment runner — subprocess plumbing for the Streamlit runner page.

Keeps process-management concerns out of the UI so the page file stays
focused on layout and state. All functions here are pure or return
handles; no Streamlit imports.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

from benchmarks.config import BENCHMARKS_ROOT

EXPERIMENTS_DIR = BENCHMARKS_ROOT / "experiments"

# Ollama models have api_key_env_var=None and api_base set. They are available
# when the local Ollama daemon is reachable — we use OLLAMA_HOST as the proxy
# (the variable LiteLLM reads). If unset, we still treat Ollama models as
# available because api_base defaults to localhost; the subprocess will fail
# fast if the daemon isn't running.
_OLLAMA_ENV_VAR = "OLLAMA_HOST"
_EXPERIMENT_ID_RE = re.compile(r"^exp_[a-z0-9_]+$")


def get_available_experiments() -> list[dict]:
    """Scan `benchmarks/experiments/` for `exp_*.py` files.

    Returns a list of ``{"id": str, "name": str, "filepath": Path}``,
    sorted by experiment id.
    """
    if not EXPERIMENTS_DIR.is_dir():
        return []

    experiments = []
    for path in sorted(EXPERIMENTS_DIR.glob("exp_*.py")):
        experiment_id = path.stem
        experiments.append(
            {
                "id": experiment_id,
                "name": humanize_experiment_id(experiment_id),
                "filepath": path,
            }
        )
    return experiments


def check_model_availability(models: list[dict]) -> list[dict]:
    """Return each model with an added ``available`` boolean field.

    A model is available when:
      - its ``api_key_env_var`` is set in the environment, OR
      - it has no ``api_key_env_var`` (local model) and Ollama is reachable
        via ``OLLAMA_HOST`` or the default ``api_base``.
    """
    enriched = []
    for model in models:
        enriched.append({**model, "available": _is_available(model)})
    return enriched


def run_experiment(
    experiment_id: str,
    models: list[str],
    runs: int,
    no_mlflow: bool = False,
    extra_args: dict[str, str] | None = None,
) -> subprocess.Popen:
    """Launch an experiment as a subprocess and return the live handle.

    Builds and executes::

        python -m benchmarks.experiments.<experiment_id> --runs N --models "A,B,C" \
            [--no-mlflow] [<extra_args key-value pairs>]

    Args:
        experiment_id: Must match ``exp_[a-z0-9_]+``.
        models: Model names to pass via ``--models``.
        runs: Number of runs per query.
        no_mlflow: If True, append ``--no-mlflow``.
        extra_args: Optional experiment-specific CLI flags, e.g.
                    ``{"--temperature": "0.7", "--log-threshold": "1.0"}``.
                    Each key-value pair is appended as two consecutive args.

    The caller is responsible for streaming ``stdout`` and awaiting
    termination. We intentionally return a ``Popen`` (not
    ``CompletedProcess``) so the runner page can render progress live.

    This function is intentionally synchronous — ``Popen`` returns
    immediately with a live process handle. Do not wrap it in
    ``asyncio.to_thread``; the caller streams ``stdout`` via a synchronous
    loop in the Streamlit page.
    """
    if not _EXPERIMENT_ID_RE.fullmatch(experiment_id):
        raise ValueError(
            f"Invalid experiment_id {experiment_id!r}. "
            "Must match exp_[a-z0-9_]+ (lowercase alphanumeric and underscores only)."
        )
    cmd = [
        sys.executable,
        "-m",
        f"benchmarks.experiments.{experiment_id}",
        "--runs",
        str(runs),
    ]
    if models:
        cmd.extend(["--models", ",".join(models)])
    if no_mlflow:
        cmd.append("--no-mlflow")
    for flag, value in (extra_args or {}).items():
        if not value:
            raise ValueError(
                f"extra_args value for {flag!r} must be a non-empty string; got {value!r}. "
                "An empty value would corrupt the CLI invocation by causing the next flag "
                "to be consumed as this argument's value."
            )
        cmd.extend([flag, value])

    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        text=True,
        cwd=BENCHMARKS_ROOT.parent,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_available(model: dict) -> bool:
    env_var = model.get("api_key_env_var")
    if env_var is None:
        # Local Ollama model — available if OLLAMA_HOST is set, or assume
        # default localhost endpoint is reachable (cheap optimism; failure
        # surfaces in the subprocess output).
        return (
            os.getenv(_OLLAMA_ENV_VAR) is not None or model.get("api_base") is not None
        )
    return bool(os.getenv(env_var))


def humanize_experiment_id(experiment_id: str) -> str:
    """Turn `exp_3_1_model_comparison` into `Exp 3.1 — Model Comparison`."""
    parts = experiment_id.split("_")
    if len(parts) < 2 or parts[0] != "exp":
        return experiment_id

    # Reconstruct version number from digit-only parts after the "exp" prefix.
    version_parts: list[str] = []
    idx = 1
    while idx < len(parts) and parts[idx].isdigit():
        version_parts.append(parts[idx])
        idx += 1

    version = ".".join(version_parts) if version_parts else ""
    tail = " ".join(parts[idx:]).title()
    if version and tail:
        return f"Exp {version} — {tail}"
    if version:
        return f"Exp {version}"
    return tail or experiment_id
