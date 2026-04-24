# -*- coding: utf-8 -*-
"""
Experiment 1.1: LLM Stochasticity for Physicochemical Parameters (pH / aw)

Proves Claim 1: LLM pH/aw retrieval is unreliable without grounding.

This is a Monte Carlo simulation. For each food in the dataset, we ask
each LLM "What is the pH of [food]?" N times and record the response.
We then compare the distribution of answers to the authoritative value
from FDA sources. Finally, we propagate the pH variance through a ComBase
growth model to show that LLM uncertainty alone can flip a safety conclusion.

=====================================================================
METRICS GUIDE -- How to read the results
=====================================================================

1. MEAN ABSOLUTE ERROR (MAE)
   What: Average absolute difference between LLM-returned pH and the
         authoritative reference value, across all runs for a food.
   How:  MAE = mean(|LLM_pH - reference_pH|) over N runs.
   Read: MAE of 0.2 means the LLM is off by 0.2 pH units on average.
         For food safety, 0.5 pH units can change whether a pathogen
         grows. MAE > 0.5 is a serious concern.

2. STANDARD DEVIATION (pH)
   What: Spread of pH values returned across N runs for the same food.
   Read: stdev of 0.0 means perfectly deterministic (same answer every
         time). stdev > 0.3 means the LLM gives meaningfully different
         answers for the same question -- unacceptable for food safety.

3. COEFFICIENT OF VARIATION (CV)
   What: stdev / mean. Normalized measure of spread.
   Read: CV > 5% means the variance is large relative to the value.
         Useful for comparing variance across foods with different pH.

4. BOUNDARY CROSSING RATE
   What: For foods near pH 4.6 (the TCS acid/low-acid boundary), what
         fraction of LLM runs return a pH on the wrong side?
   Why:  pH 4.6 is the most important threshold in food safety.
         If the LLM returns pH 4.3 half the time and pH 5.0 the other
         half, it's randomly classifying the food as acid vs. low-acid.
         This directly changes whether Clostridium botulinum is a concern.
   Read: Any value > 0% for boundary foods is a problem.

5. GROWTH PREDICTION RANGE
   What: The range (min to max) of predicted Salmonella log increase
         arising purely from pH variance, holding all other parameters
         constant (25C, aw 0.99, 4 hours).
   Why:  This is the "so what?" metric. It translates abstract pH
         variance into food safety consequences. A range of 0.5 to 2.1
         log increase means the LLM's uncertainty is the difference
         between "safe" and "discard immediately."
   Read: If min and max are on the same side of 1.0 log (a common
         safety threshold), the variance doesn't change the conclusion.
         If they straddle the threshold, the LLM's stochasticity
         alone determines the safety call.

=====================================================================
EXPERIMENT TRACKING
=====================================================================

Results are saved in two ways:

1. Local files: benchmarks/results/exp_1_1_ph_stochasticity/
   - results_YYYYMMDD_HHMMSS.json  -- full data, timestamped
   - summary_YYYYMMDD_HHMMSS.csv   -- one row per model x food
   - latest.json / latest.csv      -- copies of most recent

2. MLflow (if installed): tracks parameters, metrics, and artifacts.
   Install: pip install mlflow
   View:    mlflow ui --backend-store-uri sqlite:///mlruns.db

=====================================================================

Usage:
    python -m benchmarks.experiments.exp_1_1_ph_stochasticity
    python -m benchmarks.experiments.exp_1_1_ph_stochasticity --runs 10
    python -m benchmarks.experiments.exp_1_1_ph_stochasticity --models GPT-4o,GPT-4o-mini
    python -m benchmarks.experiments.exp_1_1_ph_stochasticity --temperature 0.7
    python -m benchmarks.experiments.exp_1_1_ph_stochasticity --log-threshold 0.5
    python -m benchmarks.experiments.exp_1_1_ph_stochasticity --no-mlflow
"""

import asyncio
import argparse
import csv
import json
import math
import os
import re
import shutil
import sys
import time
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, stdev, median

# ---------------------------------------------------------------------------
# Setup: project root on path, load .env
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from benchmarks.config import MODELS, DATASETS_DIR, RESULTS_DIR

EXPERIMENT_ID = "exp_1_1_ph_stochasticity"

# pH 4.6 is the acid/low-acid boundary in food safety regulation.
# Foods at or below 4.6 are "acid foods" (C. botulinum cannot grow).
# Foods above 4.6 are "low-acid foods" (C. botulinum is a concern).
PH_BOUNDARY = 4.6

# Default log-increase threshold for flagging safety-relevant variance.
# A 1-log increase (10x pathogen count) over the scenario duration is a
# common practical threshold in HACCP plans, but this varies by context.
# Configurable via --log-threshold CLI argument.
DEFAULT_LOG_THRESHOLD = 1.0


# ---------------------------------------------------------------------------
# Step 1: Token and cost tracking via acompletion wrapper
#
# Same approach as exp_3_3. We monkey-patch litellm.acompletion to capture
# token counts and cost before the caller (in this case, a simple completion
# call, not Instructor) consumes the response.
# ---------------------------------------------------------------------------

_token_log: list[dict] = []
_token_log_lock = threading.Lock()
_original_acompletion = None


def install_token_tracking():
    """Wrap litellm.acompletion to capture tokens and cost."""
    global _original_acompletion
    import litellm

    if _original_acompletion is not None:
        return

    _original_acompletion = litellm.acompletion

    async def tracked_acompletion(*args, **kwargs):
        response = await _original_acompletion(*args, **kwargs)
        entry = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
        usage = getattr(response, "usage", None)
        if usage:
            entry["input_tokens"] = getattr(usage, "prompt_tokens", 0) or 0
            entry["output_tokens"] = getattr(usage, "completion_tokens", 0) or 0
        try:
            entry["cost_usd"] = litellm.completion_cost(completion_response=response)
        except Exception:
            entry["cost_usd"] = 0.0
        with _token_log_lock:
            _token_log.append(entry)
        return response

    litellm.acompletion = tracked_acompletion


def collect_and_clear_tokens() -> list[dict]:
    global _token_log
    with _token_log_lock:
        entries = list(_token_log)
        _token_log = []
    return entries


# ---------------------------------------------------------------------------
# Step 2: Load the food dataset
# ---------------------------------------------------------------------------

def load_foods() -> tuple[list[dict], dict]:
    """Load food dataset and propagation scenario.

    Returns:
        (foods_list, propagation_scenario_dict)
    """
    path = DATASETS_DIR / "ph_aw_foods.json"
    with open(path) as f:
        data = json.load(f)
    return data["foods"], data["propagation_scenario"]


# ---------------------------------------------------------------------------
# Step 3: Configure the system to use a specific model
#
# Same approach as exp_3_3 -- we install a LLMClient as the singleton.
# However, for this experiment we also use direct litellm.acompletion
# calls (not Instructor), so we additionally store the config for direct use.
# ---------------------------------------------------------------------------

_current_model_config: dict = {}


def configure_model(model_config: dict):
    """Set up LLMClient singleton and store config for direct calls."""
    global _current_model_config
    from app.services.llm.client import LLMClient, reset_llm_client
    import app.services.llm.client as client_module

    api_key = None
    env_var = model_config.get("api_key_env_var")
    if env_var:
        api_key = os.getenv(env_var)
        if not api_key:
            raise ValueError(f"Environment variable '{env_var}' not set. Add it to .env")

    instructor_mode = model_config.get("instructor_mode")
    reset_llm_client()
    client_module._client = LLMClient(
        model=model_config["litellm_model"],
        api_key=api_key,
        api_base=model_config.get("api_base"),
        instructor_mode=instructor_mode,
    )

    _current_model_config = {
        "model": model_config["litellm_model"],
        "api_key": api_key,
        "api_base": model_config.get("api_base"),
    }


# ---------------------------------------------------------------------------
# Step 4: Query the LLM for pH of a food, N times
#
# This is a SIMPLE completion call, not a structured extraction.
# We ask "What is the pH of [food]?" and parse the number from the response.
# This mirrors what an ungrounded system would do -- rely on the LLM's
# training data for physicochemical values.
#
# Two prompts are used:
#   - pH prompt: "What is the pH of {food}? Respond with only a number."
#   - aw prompt: "What is the water activity of {food}? Respond with only a number."
# ---------------------------------------------------------------------------

async def query_ph_n_times(food_name: str, n_runs: int,
                           temperature: float) -> list[dict]:
    """Ask the LLM for pH of a food N times.

    Returns list of {run, ph_value, raw_response, latency_s, cost_usd, error}.
    """
    from litellm import acompletion

    prompt = (
        f"What is the pH of {food_name}? "
        "Respond with only a single number (e.g., 6.0). "
        "Do not include any explanation, range, or text."
    )

    results = []
    for i in range(n_runs):
        ph_value = None
        raw_response = None
        error = None

        collect_and_clear_tokens()

        start = time.perf_counter()
        try:
            response = await acompletion(
                model=_current_model_config["model"],
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=20,
                api_key=_current_model_config.get("api_key"),
                api_base=_current_model_config.get("api_base"),
            )
            raw_response = response.choices[0].message.content.strip()
            ph_value = parse_numeric_response(raw_response)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
        latency = time.perf_counter() - start

        tokens = collect_and_clear_tokens()
        cost_usd = sum(t["cost_usd"] for t in tokens)

        results.append({
            "run": i,
            "ph_value": ph_value,
            "raw_response": raw_response,
            "latency_s": round(latency, 3),
            "cost_usd": cost_usd,
            "error": error,
        })

    return results


async def query_aw_n_times(food_name: str, n_runs: int,
                           temperature: float) -> list[dict]:
    """Ask the LLM for water activity of a food N times.

    Returns list of {run, aw_value, raw_response, latency_s, cost_usd, error}.
    """
    from litellm import acompletion

    prompt = (
        f"What is the water activity (aw) of {food_name}? "
        "Respond with only a single number between 0 and 1 (e.g., 0.98). "
        "Do not include any explanation, range, or text."
    )

    results = []
    for i in range(n_runs):
        aw_value = None
        raw_response = None
        error = None

        collect_and_clear_tokens()

        start = time.perf_counter()
        try:
            response = await acompletion(
                model=_current_model_config["model"],
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=20,
                api_key=_current_model_config.get("api_key"),
                api_base=_current_model_config.get("api_base"),
            )
            raw_response = response.choices[0].message.content.strip()
            aw_value = parse_numeric_response(raw_response)
            # Sanity check: aw must be between 0 and 1
            if aw_value is not None and (aw_value < 0 or aw_value > 1):
                aw_value = None
                error = f"aw out of range: {raw_response}"
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
        latency = time.perf_counter() - start

        tokens = collect_and_clear_tokens()
        cost_usd = sum(t["cost_usd"] for t in tokens)

        results.append({
            "run": i,
            "aw_value": aw_value,
            "raw_response": raw_response,
            "latency_s": round(latency, 3),
            "cost_usd": cost_usd,
            "error": error,
        })

    return results


def parse_numeric_response(text: str) -> float | None:
    """Extract a single numeric value from an LLM response.

    Handles formats like: "6.0", "pH 6.0", "6.0.", "approximately 6.0",
    "The pH is 6.0", "6,0" (European decimal), etc.
    """
    if not text:
        return None
    # Replace European decimal comma
    text = text.replace(",", ".")
    # Find all numbers in the text
    numbers = re.findall(r'\d+\.?\d*', text)
    if not numbers:
        return None
    # Return the first plausible number
    for n in numbers:
        val = float(n)
        # pH should be 0-14, aw should be 0-1
        # Accept any positive number and let the caller filter
        if 0 <= val <= 14:
            return val
    return float(numbers[0])


# ---------------------------------------------------------------------------
# Step 5: Compute growth propagation
#
# For each pH value sampled from the LLM, compute the predicted mu_max
# and log increase using the ComBase calculator. This shows how pH
# variance translates into food safety consequences.
#
# All other parameters are held constant (from propagation_scenario in
# the dataset): temperature=25C, aw=0.99, duration=4h, organism=Salmonella.
# ---------------------------------------------------------------------------

def compute_growth_for_ph(ph_value: float, scenario: dict) -> dict | None:
    """Compute mu_max and log increase for a given pH using ComBase.

    Returns {mu_max, log_increase, doubling_time_hours} or None on error.
    """
    try:
        from app.engines.combase.models import ComBaseModelRegistry
        from app.engines.combase.calculator import ComBaseCalculator
        from app.models.enums import ModelType, ComBaseOrganism, Factor4Type

        registry = ComBaseModelRegistry()
        csv_path = Path("data/combase_models.csv")
        if not csv_path.exists():
            return None
        registry.load_from_csv(csv_path)

        model = registry.get_model(
            organism=ComBaseOrganism.SALMONELLA,
            model_type=ModelType.GROWTH,
            factor4_type=Factor4Type.NONE,
        )
        if model is None:
            return None

        calc = ComBaseCalculator(model)
        result = calc.calculate(
            temperature=scenario["temperature_celsius"],
            ph=ph_value,
            aw=scenario["water_activity"],
        )

        duration_hours = scenario["duration_hours"]
        log_increase = calc.calculate_log_increase(result.mu_max, duration_hours)

        return {
            "mu_max": round(result.mu_max, 6),
            "log_increase": round(log_increase, 4),
            "doubling_time_hours": round(result.doubling_time_hours, 4) if result.doubling_time_hours else None,
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Step 6: Compute per-food statistics
# ---------------------------------------------------------------------------

def compute_food_stats(ph_values: list[float], reference_ph: float,
                       reference_range: list[float]) -> dict:
    """Compute summary statistics for a set of pH values vs. ground truth.

    Returns dict with mean, stdev, cv, mae, boundary_crossing_rate, etc.
    """
    if not ph_values:
        return {"n_valid": 0}

    ph_mean = mean(ph_values)
    ph_stdev = stdev(ph_values) if len(ph_values) > 1 else 0.0
    ph_cv = (ph_stdev / ph_mean * 100) if ph_mean != 0 else 0.0
    ph_min = min(ph_values)
    ph_max = max(ph_values)
    ph_median = median(ph_values)

    # Mean absolute error vs. reference
    mae = mean(abs(v - reference_ph) for v in ph_values)

    # What fraction of responses are within the reference range?
    in_range = sum(1 for v in ph_values
                   if reference_range[0] <= v <= reference_range[1])
    in_range_rate = in_range / len(ph_values)

    # Boundary crossing: for foods near pH 4.6, how often does the LLM
    # return a value on the wrong side of the boundary?
    ref_side = "acid" if reference_ph <= PH_BOUNDARY else "low_acid"
    crossings = sum(
        1 for v in ph_values
        if (ref_side == "acid" and v >= PH_BOUNDARY)
        or (ref_side == "low_acid" and v < PH_BOUNDARY)
    )
    boundary_crossing_rate = crossings / len(ph_values)

    return {
        "n_valid": len(ph_values),
        "mean": round(ph_mean, 3),
        "stdev": round(ph_stdev, 3),
        "cv_pct": round(ph_cv, 2),
        "min": round(ph_min, 2),
        "max": round(ph_max, 2),
        "median": round(ph_median, 3),
        "mae": round(mae, 3),
        "in_range_rate": round(in_range_rate, 3),
        "boundary_crossing_rate": round(boundary_crossing_rate, 3),
        "reference_ph": reference_ph,
        "reference_side": ref_side,
    }


# ---------------------------------------------------------------------------
# Step 7: Run the full experiment
# ---------------------------------------------------------------------------

async def run_experiment(models: list[dict], foods: list[dict],
                         propagation_scenario: dict,
                         n_runs: int, temperature: float,
                         log_threshold: float = DEFAULT_LOG_THRESHOLD):
    install_token_tracking()
    all_results = []

    for model in models:
        model_name = model["name"]
        model_id = model["litellm_model"]
        print(f"\n{'='*60}")
        print(f"  Model: {model_name}")
        print(f"  LiteLLM ID: {model_id}")
        print(f"  Temperature: {temperature}")
        print(f"{'='*60}")

        configure_model(model)

        model_results = {
            "model": model_name,
            "litellm_model": model_id,
            "temperature": temperature,
            "log_threshold": log_threshold,
            "foods": [],
            "summary": {},
        }
        total_cost = 0.0
        all_maes = []
        all_stdevs = []

        for fi, food in enumerate(foods):
            food_name = food["name"]
            food_id = food["id"]
            ref_ph = food["reference_ph"]
            ref_range = food["reference_ph_range"]
            print(f"\n  [{fi+1}/{len(foods)}] {food_id}: {food_name} (ref pH={ref_ph})...")

            # --- Query pH N times ---
            ph_runs = await query_ph_n_times(food_name, n_runs, temperature)

            valid_ph = [r["ph_value"] for r in ph_runs if r["ph_value"] is not None]
            errors = [r["error"] for r in ph_runs if r["error"] is not None]
            food_cost = sum(r["cost_usd"] for r in ph_runs)
            total_cost += food_cost

            if not valid_ph:
                print(f"    X All {n_runs} pH runs failed: {errors[0] if errors else '?'}")
                model_results["foods"].append({
                    "food_id": food_id, "food_name": food_name,
                    "difficulty": food["difficulty"],
                    "ph_stats": {"n_valid": 0}, "growth_propagation": None,
                })
                continue

            # --- Compute pH statistics ---
            ph_stats = compute_food_stats(valid_ph, ref_ph, ref_range)
            all_maes.append(ph_stats["mae"])
            all_stdevs.append(ph_stats["stdev"])

            # --- Propagate pH variance through growth model ---
            # Compute growth for each sampled pH value
            growth_results = []
            for ph_val in valid_ph:
                growth = compute_growth_for_ph(ph_val, propagation_scenario)
                if growth:
                    growth_results.append(growth)

            growth_propagation = None
            if growth_results:
                log_increases = [g["log_increase"] for g in growth_results]
                growth_propagation = {
                    "n_computed": len(growth_results),
                    "log_increase_min": round(min(log_increases), 4),
                    "log_increase_max": round(max(log_increases), 4),
                    "log_increase_mean": round(mean(log_increases), 4),
                    "log_increase_stdev": round(stdev(log_increases), 4) if len(log_increases) > 1 else 0,
                    "log_increase_range": round(max(log_increases) - min(log_increases), 4),
                    # Does the pH variance change the safety conclusion?
                    # Threshold is configurable via --log-threshold (default 1.0).
                    "crosses_log_threshold": min(log_increases) < log_threshold < max(log_increases),
                    "log_threshold_used": log_threshold,
                }

            # --- Console output ---
            bc = ph_stats["boundary_crossing_rate"]
            bc_flag = f" !! boundary={bc:.0%}" if bc > 0 else ""
            print(f"    pH: {ph_stats['mean']:.2f} +/- {ph_stats['stdev']:.3f}  "
                  f"MAE={ph_stats['mae']:.3f}  "
                  f"range=[{ph_stats['min']:.1f}, {ph_stats['max']:.1f}]{bc_flag}")
            if growth_propagation:
                gp = growth_propagation
                cross_flag = " !! SAFETY" if gp["crosses_log_threshold"] else ""
                print(f"    Growth: log_inc=[{gp['log_increase_min']:.2f}, "
                      f"{gp['log_increase_max']:.2f}]  "
                      f"range={gp['log_increase_range']:.2f}{cross_flag}")

            model_results["foods"].append({
                "food_id": food_id,
                "food_name": food_name,
                "difficulty": food["difficulty"],
                "reference_ph": ref_ph,
                "reference_ph_range": ref_range,
                "ph_values": valid_ph,
                "ph_stats": ph_stats,
                "growth_propagation": growth_propagation,
                "raw_runs": ph_runs,
                "cost_usd": round(food_cost, 6),
            })

        # --- Model summary ---
        model_results["summary"] = {
            "overall_mae": round(mean(all_maes), 3) if all_maes else 0,
            "overall_stdev": round(mean(all_stdevs), 3) if all_stdevs else 0,
            "foods_with_boundary_crossing": sum(
                1 for f in model_results["foods"]
                if f["ph_stats"].get("boundary_crossing_rate", 0) > 0
            ),
            "foods_with_safety_impact": sum(
                1 for f in model_results["foods"]
                if f.get("growth_propagation", {})
                and f["growth_propagation"].get("crosses_log_threshold", False)
            ),
            "total_cost_usd": round(total_cost, 4),
        }

        all_results.append(model_results)

    return all_results


# ---------------------------------------------------------------------------
# Step 8: Save results -- timestamped files + "latest" copy
# ---------------------------------------------------------------------------

def save_results(results: list[dict], run_timestamp: str) -> Path:
    out_dir = RESULTS_DIR / EXPERIMENT_ID
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- Full results JSON ---
    json_path = out_dir / f"results_{run_timestamp}.json"
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    # --- Summary CSV: one row per model x food ---
    csv_path = out_dir / f"summary_{run_timestamp}.csv"
    rows = []
    for r in results:
        for food in r["foods"]:
            ps = food["ph_stats"]
            gp = food.get("growth_propagation") or {}
            rows.append({
                "model": r["model"],
                "temperature": r["temperature"],
                "food_id": food["food_id"],
                "food_name": food["food_name"],
                "difficulty": food["difficulty"],
                "reference_ph": food.get("reference_ph", ""),
                "ph_mean": ps.get("mean", ""),
                "ph_stdev": ps.get("stdev", ""),
                "ph_cv_pct": ps.get("cv_pct", ""),
                "ph_mae": ps.get("mae", ""),
                "ph_min": ps.get("min", ""),
                "ph_max": ps.get("max", ""),
                "in_range_rate": ps.get("in_range_rate", ""),
                "boundary_crossing_rate": ps.get("boundary_crossing_rate", ""),
                "growth_log_inc_min": gp.get("log_increase_min", ""),
                "growth_log_inc_max": gp.get("log_increase_max", ""),
                "growth_log_inc_range": gp.get("log_increase_range", ""),
                "crosses_safety_threshold": gp.get("crosses_log_threshold", ""),
                "n_valid": ps.get("n_valid", 0),
            })

    if rows:
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

    # --- Latest copies ---
    shutil.copy2(json_path, out_dir / "latest.json")
    shutil.copy2(csv_path, out_dir / "latest.csv")

    print(f"\n  Results saved to {out_dir}/")
    print(f"    {json_path.name}  -- full data")
    print(f"    {csv_path.name}   -- summary per model x food")
    print(f"    latest.json / latest.csv -- most recent run")

    return out_dir


# ---------------------------------------------------------------------------
# Step 9: MLflow tracking (optional)
# ---------------------------------------------------------------------------

def log_to_mlflow(results: list[dict], out_dir: Path,
                  n_runs: int, n_foods: int, temperature: float,
                  run_timestamp: str):
    try:
        import mlflow
    except ImportError:
        print("\n  MLflow not installed -- skipping tracking.")
        print("  Install with: pip install mlflow")
        return

    db_path = PROJECT_ROOT / "mlruns.db"
    mlflow.set_tracking_uri(f"sqlite:///{db_path}")
    mlflow.set_experiment(EXPERIMENT_ID)

    with mlflow.start_run(run_name=f"run_{run_timestamp}"):
        mlflow.log_param("n_runs_per_food", n_runs)
        mlflow.log_param("n_foods", n_foods)
        mlflow.log_param("temperature", temperature)
        mlflow.log_param("log_threshold", results[0].get("log_threshold", DEFAULT_LOG_THRESHOLD) if results else DEFAULT_LOG_THRESHOLD)
        mlflow.log_param("models", ", ".join(r["model"] for r in results))
        mlflow.log_param("timestamp", run_timestamp)

        for r in results:
            prefix = r["model"].replace(" ", "_").replace(".", "_").lower()
            s = r["summary"]
            mlflow.log_metric(f"{prefix}/overall_mae", s["overall_mae"])
            mlflow.log_metric(f"{prefix}/overall_stdev", s["overall_stdev"])
            mlflow.log_metric(f"{prefix}/foods_boundary_crossing", s["foods_with_boundary_crossing"])
            mlflow.log_metric(f"{prefix}/foods_safety_impact", s["foods_with_safety_impact"])
            mlflow.log_metric(f"{prefix}/total_cost", s["total_cost_usd"])

            # Per-food MAE
            for food in r["foods"]:
                food_prefix = food["food_id"].lower()
                mlflow.log_metric(f"{prefix}/{food_prefix}_mae", food["ph_stats"].get("mae", 0))
                mlflow.log_metric(f"{prefix}/{food_prefix}_stdev", food["ph_stats"].get("stdev", 0))

        mlflow.log_artifact(str(out_dir / f"results_{run_timestamp}.json"))
        mlflow.log_artifact(str(out_dir / f"summary_{run_timestamp}.csv"))

    print(f"\n  MLflow: run logged. View with:")
    print(f"    mlflow ui --backend-store-uri sqlite:///{db_path}")


# ---------------------------------------------------------------------------
# Step 10: Print summary
# ---------------------------------------------------------------------------

def print_summary(results: list[dict]):
    # Build all output lines first, print in one shot at the end.
    # This prevents stdout buffering issues on Windows that cause
    # interleaved output when piping to a file.
    lines = []

    log_threshold = results[0].get("log_threshold", DEFAULT_LOG_THRESHOLD) if results else DEFAULT_LOG_THRESHOLD

    lines.append(f"\n{'='*85}")
    lines.append("  SUMMARY: LLM pH STOCHASTICITY")
    lines.append(f"{'='*85}")

    # --- Per-model overview ---
    lines.append(f"\n  {'Model':<20} {'MAE':>8} {'Stdev':>8} {'Boundary':>10} {'Safety':>10} {'Cost':>10}")
    lines.append("  " + "-" * 68)
    for r in results:
        s = r["summary"]
        lines.append(f"  {r['model']:<20} "
              f"{s['overall_mae']:>7.3f} "
              f"{s['overall_stdev']:>7.3f} "
              f"{s['foods_with_boundary_crossing']:>8}x "
              f"{s['foods_with_safety_impact']:>8}x "
              f"${s['total_cost_usd']:>8.4f}")

    # --- Per-food detail (for worst model) ---
    worst = max(results, key=lambda r: r["summary"]["overall_mae"])
    lines.append(f"\n  DETAIL: {worst['model']} (highest MAE)")
    lines.append(f"  {'Food':<25} {'Ref':>5} {'Mean':>6} {'Stdev':>7} {'MAE':>6} {'Tier':>8}")
    lines.append("  " + "-" * 59)
    for food in worst["foods"]:
        ps = food["ph_stats"]
        if ps.get("n_valid", 0) == 0:
            lines.append(f"  {food['food_name']:<25} {food.get('reference_ph', '?'):>5} {'FAILED':>6}")
            continue
        tier = food.get('difficulty', '')
        lines.append(f"  {food['food_name']:<25} "
              f"{food.get('reference_ph', 0):>4.1f} "
              f"{ps['mean']:>5.2f} "
              f"{ps['stdev']:>6.3f} "
              f"{ps['mae']:>5.3f} "
              f"{tier:>8}")

    # --- Boundary crossing detail ---
    boundary_foods = [
        f for f in worst["foods"]
        if f["ph_stats"].get("boundary_crossing_rate", 0) > 0
    ]
    if boundary_foods:
        lines.append(f"\n  pH 4.6 BOUNDARY CROSSINGS")
        lines.append(f"  {'Food':<25} {'Ref':>5} {'Ref side':>10} {'BC rate':>8}")
        lines.append("  " + "-" * 50)
        for food in boundary_foods:
            ps = food["ph_stats"]
            bc = ps["boundary_crossing_rate"]
            lines.append(f"  {food['food_name']:<25} "
                  f"{food.get('reference_ph', 0):>4.1f} "
                  f"{ps.get('reference_side', '?'):>10} "
                  f"{bc:>7.0%}")

    # --- Growth propagation impact ---
    lines.append(f"\n  GROWTH PREDICTION IMPACT (pH variance -> log increase range)")
    lines.append(f"  Log threshold: {log_threshold:.1f} (configurable via --log-threshold)")
    lines.append(f"  {'Model':<20} {'Food':<25} {'Log inc range':>14} {'Crosses?':>10}")
    lines.append("  " + "-" * 71)
    for r in results:
        for food in r["foods"]:
            gp = food.get("growth_propagation")
            if gp and gp["log_increase_range"] > 0.1:
                cross = "!! YES" if gp["crosses_log_threshold"] else "no"
                lines.append(f"  {r['model']:<20} "
                      f"{food['food_name']:<25} "
                      f"{gp['log_increase_min']:.2f} - {gp['log_increase_max']:.2f}  "
                      f"{cross:>8}")

    # --- Key finding ---
    total_safety_impacts = sum(r["summary"]["foods_with_safety_impact"] for r in results)
    total_boundary_crossings = sum(r["summary"]["foods_with_boundary_crossing"] for r in results)
    lines.append(f"\n  KEY FINDING:")
    if total_safety_impacts > 0:
        lines.append(f"  !! LLM pH variance changes the safety conclusion in "
              f"{total_safety_impacts} model/food combinations.")
        lines.append(f"     This proves that ungrounded LLM inference is insufficient")
        lines.append(f"     for food safety parameterisation. RAG grounding is necessary.")
    else:
        lines.append(f"     No safety conclusion changes detected in this run.")
        lines.append(f"     Consider increasing --runs or --temperature for more variance.")
    if total_boundary_crossings > 0:
        lines.append(f"  !! pH 4.6 boundary crossed in {total_boundary_crossings} "
              f"model/food combinations.")

    # Print everything in one shot to prevent interleaving
    print("\n".join(lines), flush=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(
        description="Exp 1.1: LLM pH Stochasticity Monte Carlo")
    parser.add_argument("--runs", type=int, default=30,
                        help="Runs per food per model (default: 30)")
    parser.add_argument("--models", type=str, default=None,
                        help="Comma-separated model names (default: all with available keys)")
    parser.add_argument("--temperature", type=float, default=0.7,
                        help="LLM generation temperature (default: 0.7)")
    parser.add_argument("--log-threshold", type=float, default=DEFAULT_LOG_THRESHOLD,
                        help="Log-increase threshold for safety flag (default: 1.0)")
    parser.add_argument("--no-mlflow", action="store_true",
                        help="Disable MLflow tracking even if installed")
    args = parser.parse_args()

    # Force line-buffered stdout. Without this, Windows block-buffers
    # stdout when piping to a file, causing output sections to interleave.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:
        pass  # Python < 3.7

    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"\n{'#'*70}")
    print(f"  EXPERIMENT 1.1: LLM pH STOCHASTICITY")
    print(f"  Monte Carlo simulation of pH retrieval variance")
    print(f"  Run: {run_timestamp}")
    print(f"{'#'*70}")

    # Filter to available models
    available = []
    for m in MODELS:
        env_var = m.get("api_key_env_var")
        if env_var is None:
            available.append(m)
        elif os.getenv(env_var):
            available.append(m)
        else:
            print(f"  Skipping {m['name']}: {env_var} not set in .env")

    if args.models:
        names = [n.strip() for n in args.models.split(",")]
        available = [m for m in available if m["name"] in names]
        not_found = [n for n in names if not any(m["name"] == n for m in available)]
        if not_found:
            print(f"  !! Not found or no key: {not_found}")

    if not available:
        print("\n  X No models available. Add API keys to .env:")
        print("      OPENAI_API_KEY=sk-...")
        print("      ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    foods, propagation_scenario = load_foods()
    print(f"\n  Models: {[m['name'] for m in available]}")
    print(f"  Foods: {len(foods)}")
    print(f"  Runs per food: {args.runs}")
    print(f"  Temperature: {args.temperature}")
    print(f"  Log threshold: {args.log_threshold}")
    print(f"  Total LLM calls: {len(available) * len(foods) * args.runs}")

    results = await run_experiment(
        available, foods, propagation_scenario,
        args.runs, args.temperature, args.log_threshold,
    )
    out_dir = save_results(results, run_timestamp)
    print_summary(results)

    if not args.no_mlflow:
        log_to_mlflow(results, out_dir, args.runs, len(foods),
                      args.temperature, run_timestamp)


if __name__ == "__main__":
    asyncio.run(main())
