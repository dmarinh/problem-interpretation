"""
Experiment 3.3: LLM Model Comparison for Semantic Extraction

Compares candidate LLMs on the task that matters: extracting food safety
scenarios from natural language using the REAL SemanticParser — the same
code path, same system prompt, same Pydantic schema as production.

═══════════════════════════════════════════════════════════════════════
METRICS GUIDE — How to read the results
═══════════════════════════════════════════════════════════════════════

1. OVERALL ACCURACY (0–100%)
   What: Fraction of ground truth fields that the extraction got right,
         averaged across all queries.
   How:  For each query, we check each relevant field (food_description,
         model_type, pathogen, temperature, duration, etc.) against expert
         ground truth. Each field scores 1 (correct) or 0 (wrong).
         Query accuracy = correct fields / total fields.
         Overall = mean of all query accuracies.
   Read: 90% means the model gets 9 out of 10 fields right on average.
         Compare across models to find the most accurate.

2. OVERALL CONSISTENCY (0–100%)
   What: How reproducible are the extractions? If we run the same query
         N times, how often does each field produce the same value?
   How:  For each field, we count how often the most common value appears
         across N runs. E.g., if "raw chicken" appears in 19/20 runs,
         consistency for that field = 95%.
         Overall = mean across all tracked fields.
   Read: 100% = perfectly deterministic. <90% = the parser gives different
         answers for the same input, which undermines reproducibility —
         the core thesis of the project.

3. MODEL TYPE ACCURACY (0–100%)
   What: How often the parser correctly classifies growth vs. thermal
         inactivation vs. non-thermal survival.
   Why:  THIS IS THE MOST IMPORTANT METRIC. A model type error reverses
         the direction of conservative bias. If a cooking query is
         classified as growth, the system pushes temperature UP (more
         growth = worse), but for inactivation it should push DOWN
         (less kill = worse). Wrong classification makes unsafe food
         look safe. This is a safety-critical failure.
   How:  Fraction of queries where implied_model_type matches ground truth.
   Read: Anything below 100% is a serious concern. A model that scores
         95% on accuracy but 80% on model type is WORSE than one that
         scores 85% accuracy with 100% model type.

4. SCHEMA COMPLIANCE (0–100%)
   What: How often does the LLM produce a valid ExtractedScenario object
         without errors?
   How:  (successful extractions) / (total attempts) across all runs.
         A failed extraction means Instructor couldn't parse the LLM output
         into the Pydantic schema — the LLM produced invalid JSON, wrong
         types, or violated field constraints.
   Read: <95% means the model struggles with structured output. This adds
         latency (Instructor retries) and unreliability. Open-source models
         often score lower here than commercial APIs.

5. LATENCY — P50 and P95 (seconds)
   What: How long each extraction call takes.
   P50:  The median — half the calls are faster, half are slower.
         This is the "typical" user experience.
   P95:  The 95th percentile — only 5% of calls are slower than this.
         This is the "worst case the user will regularly experience."
   Read: For interactive use, P95 < 3s is acceptable. P95 > 5s feels
         broken. P50 matters for batch processing cost.

6. ACTUAL COST PER CALL (USD)
   What: Real cost of one extraction, based on actual token usage.
   How:  We intercept every LiteLLM API call to capture the response
         object. Cost is computed by litellm.completion_cost(), which
         maintains its own pricing table for all known models — we don't
         need to track prices ourselves. It handles provider-specific
         input/output pricing automatically.
   Read: Compare across models. A model that's 5% less accurate but 20×
         cheaper may be the right choice for batch processing.
   Note: For unknown models (e.g., custom Ollama), cost returns 0.
         Some reasoning models consume additional "thinking" tokens
         that may not appear in standard usage fields — cost may be
         an underestimate for those models.

7. ACCURACY BY DIFFICULTY TIER
   What: Accuracy broken down by query difficulty (easy/medium/hard).
   Why:  A cheap model might ace easy queries but fail on hard ones.
         This tells you whether you could use a cheaper model for
         simple queries and reserve the expensive model for complex ones.
   Read: If easy=100% and hard=60%, the model is struggling with
         ambiguity, range preservation, or model type classification.

8. ACCURACY BY FIELD
   What: For each extraction field (food, model_type, pathogen, temp,
         duration, range, etc.), what % of queries did the model get right?
   Why:  Identifies systematic weaknesses. A model that always misses
         duration but nails temperature has a specific, addressable flaw.
   Read: model_type and range_preserved are the most important columns.

═══════════════════════════════════════════════════════════════════════
EXPERIMENT TRACKING
═══════════════════════════════════════════════════════════════════════

Results are saved in two ways:

1. Local files: benchmarks/results/exp_3_3_model_comparison/
   - results_YYYYMMDD_HHMMSS.json  — full data, timestamped
   - summary_YYYYMMDD_HHMMSS.csv   — one row per model, all metrics
   - latest.json / latest.csv      — symlinks/copies to most recent

2. MLflow (if installed): tracks parameters, metrics, and artifacts
   so you can compare runs across time in the MLflow UI.
   Install: pip install mlflow
   View:    mlflow ui --backend-store-uri sqlite:///mlruns.db
   If MLflow is not installed, the experiment runs normally without it.

═══════════════════════════════════════════════════════════════════════

Usage:
    python -m benchmarks.experiments.exp_3_3_model_comparison
    python -m benchmarks.experiments.exp_3_3_model_comparison --runs 3
    python -m benchmarks.experiments.exp_3_3_model_comparison --models GPT-4o,GPT-4o-mini
    python -m benchmarks.experiments.exp_3_3_model_comparison --no-mlflow
"""

import asyncio
import argparse
import csv
import json
import os
import shutil
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Setup: project root on path, load .env
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from benchmarks.config import MODELS, DATASETS_DIR, RESULTS_DIR


# ---------------------------------------------------------------------------
# Step 1: Token and cost tracking via acompletion wrapper
#
# The problem: Instructor consumes the raw LiteLLM response object, so by
# the time we get back our Pydantic model, the token usage data is gone.
#
# The solution: We monkey-patch litellm.acompletion with a thin wrapper
# that captures the response object (including usage and cost) before
# Instructor processes it. This requires NO changes to app code.
#
# Cost is computed by litellm.completion_cost(), which maintains its own
# pricing table for all known models. We don't need to track prices
# ourselves — LiteLLM handles provider-specific input/output pricing,
# and updates when new models are released.
#
# Limitation: Some reasoning models (o1, etc.) consume "thinking" tokens
# that may not appear in standard usage fields. If the provider doesn't
# report them, our cost will be an underestimate.
# ---------------------------------------------------------------------------

_token_log: list[dict] = []
_original_acompletion = None


def install_token_tracking():
    """Wrap litellm.acompletion to capture tokens and cost from every API call.

    Uses litellm.completion_cost() for accurate per-model pricing.
    Call once at startup. Safe to call multiple times (idempotent).
    """
    global _original_acompletion
    import litellm

    if _original_acompletion is not None:
        return  # Already installed

    _original_acompletion = litellm.acompletion

    async def tracked_acompletion(*args, **kwargs):
        response = await _original_acompletion(*args, **kwargs)

        entry = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}

        # Capture token counts
        usage = getattr(response, "usage", None)
        if usage:
            entry["input_tokens"] = getattr(usage, "prompt_tokens", 0) or 0
            entry["output_tokens"] = getattr(usage, "completion_tokens", 0) or 0

        # Compute cost via LiteLLM's built-in pricing table.
        # This knows per-model input/output prices and stays up to date.
        # Falls back to 0 for unknown models (e.g., custom Ollama).
        try:
            entry["cost_usd"] = litellm.completion_cost(completion_response=response)
        except Exception:
            entry["cost_usd"] = 0.0

        _token_log.append(entry)
        return response

    # Replace globally — Instructor calls litellm.acompletion internally
    litellm.acompletion = tracked_acompletion


def collect_and_clear_tokens() -> list[dict]:
    """Return captured token/cost entries and reset the log."""
    global _token_log
    entries = list(_token_log)
    _token_log = []
    return entries


# ---------------------------------------------------------------------------
# Step 2: Load test queries
# ---------------------------------------------------------------------------

def load_queries() -> list[dict]:
    path = DATASETS_DIR / "extraction_queries.json"
    with open(path) as f:
        data = json.load(f)
    return data["queries"]


# ---------------------------------------------------------------------------
# Step 3: Configure the system to use a specific model
# ---------------------------------------------------------------------------

def configure_model(model_config: dict):
    from app.services.llm.client import LLMClient, reset_llm_client
    import app.services.llm.client as client_module

    api_key = None
    env_var = model_config.get("api_key_env_var")
    if env_var:
        api_key = os.getenv(env_var)
        if not api_key:
            raise ValueError(f"Environment variable '{env_var}' not set. Add it to .env")

    # instructor_mode controls how Instructor extracts structured data:
    #   None   -> tool/function calls (default, for OpenAI/Anthropic)
    #   "JSON" -> JSON-in-prompt (for local models that lack tool call support)
    # This is set per-model in config.py and passed through to LLMClient,
    # which uses it in extract() to configure Instructor's mode.
    instructor_mode = model_config.get("instructor_mode")

    reset_llm_client()
    client_module._client = LLMClient(
        model=model_config["litellm_model"],
        api_key=api_key,
        api_base=model_config.get("api_base"),
        instructor_mode=instructor_mode,
    )


# ---------------------------------------------------------------------------
# Step 4: Run extraction N times for a single query
# ---------------------------------------------------------------------------

async def extract_n_times(query_text: str, n_runs: int) -> list[dict]:
    from app.services.extraction.semantic_parser import SemanticParser

    parser = SemanticParser()
    results = []

    for i in range(n_runs):
        extraction = None
        error = None

        collect_and_clear_tokens()

        start = time.perf_counter()
        try:
            scenario = await parser.extract_scenario(query_text)
            extraction = scenario_to_dict(scenario)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
        latency = time.perf_counter() - start

        tokens = collect_and_clear_tokens()
        input_tokens = sum(t["input_tokens"] for t in tokens)
        output_tokens = sum(t["output_tokens"] for t in tokens)
        cost_usd = sum(t["cost_usd"] for t in tokens)

        results.append({
            "run": i,
            "extraction": extraction,
            "latency_s": round(latency, 3),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
            "error": error,
        })

    return results


def scenario_to_dict(scenario) -> dict:
    """Convert an ExtractedScenario to a flat dict for comparison.

    Captures all fields from the real schema:
      - ExtractedTemperature: value_celsius, description, is_range, range_min/max
      - ExtractedDuration: value_minutes, description, is_ambiguous, range_min/max
      - ExtractedEnvironmentalConditions: ph_value, water_activity
      - implied_model_type (as string)
    """
    d = {
        "food_description": scenario.food_description,
        "food_state": scenario.food_state,
        "pathogen_mentioned": scenario.pathogen_mentioned,
        "is_multi_step": scenario.is_multi_step,
    }

    mt = scenario.implied_model_type
    d["implied_model_type"] = mt.value if (mt is not None and hasattr(mt, "value")) else (str(mt) if mt else None)

    if not scenario.is_multi_step:
        temp = scenario.single_step_temperature
        d["temperature_value"] = temp.value_celsius
        d["temperature_description"] = temp.description
        d["temperature_is_range"] = temp.is_range
        d["temperature_range_min"] = temp.range_min_celsius
        d["temperature_range_max"] = temp.range_max_celsius

        dur = scenario.single_step_duration
        d["duration_minutes"] = dur.value_minutes
        d["duration_description"] = dur.description
        d["duration_is_ambiguous"] = dur.is_ambiguous
        d["duration_range_min"] = dur.range_min_minutes
        d["duration_range_max"] = dur.range_max_minutes
    else:
        steps = scenario.time_temperature_steps or []
        d["step_count"] = len(steps)
        for i, step in enumerate(steps):
            d[f"step_{i}_temp"] = step.temperature.value_celsius if step.temperature else None
            d[f"step_{i}_dur"] = step.duration.value_minutes if step.duration else None
            d[f"step_{i}_desc"] = step.description

    env = scenario.environmental_conditions
    if env:
        d["ph_value"] = env.ph_value
        d["water_activity"] = env.water_activity

    return d


# ---------------------------------------------------------------------------
# Step 5: Score an extraction against ground truth
# ---------------------------------------------------------------------------

def score_extraction(extraction: dict, expected: dict) -> dict:
    scores = {}
    details = []

    # --- Food description ---
    if "food_description" in expected and expected["food_description"] is not None:
        actual = (extraction.get("food_description") or "").lower()
        exp_options = [e.strip().lower() for e in expected["food_description"].split("|")]
        ok = any(exp in actual or actual in exp for exp in exp_options)
        scores["food_description"] = ok
        if not ok:
            details.append(f"food: expected one of {exp_options}, got '{actual}'")

    elif "food_description_should_contain" in expected:
        actual = (extraction.get("food_description") or "").lower()
        terms = expected["food_description_should_contain"]
        ok = any(t.lower() in actual for t in terms)
        scores["food_description"] = ok
        if not ok:
            details.append(f"food: expected any of {terms}, got '{actual}'")

    # --- Model type (SAFETY-CRITICAL) ---
    if "implied_model_type" in expected:
        actual_mt = (extraction.get("implied_model_type") or "").lower().replace(" ", "_")
        exp_mt = expected["implied_model_type"]

        if isinstance(exp_mt, list):
            acceptable = [m.lower().replace(" ", "_") for m in exp_mt]
            ok = actual_mt in acceptable
            if not ok:
                details.append(f"MODEL TYPE: expected one of {acceptable}, got '{actual_mt}' !! SAFETY-CRITICAL")
        elif exp_mt is None:
            ok = actual_mt == "" or extraction.get("implied_model_type") is None
            if not ok:
                details.append(f"MODEL TYPE: expected None, got '{actual_mt}'")
        else:
            expected_mt = exp_mt.lower().replace(" ", "_")
            ok = actual_mt == expected_mt
            if not ok:
                details.append(f"MODEL TYPE: expected '{expected_mt}', got '{actual_mt}' !! SAFETY-CRITICAL")

        scores["model_type"] = ok

    # --- Pathogen ---
    if "pathogen_mentioned" in expected:
        exp_path = expected["pathogen_mentioned"]
        act_path = extraction.get("pathogen_mentioned")
        if exp_path is None:
            ok = act_path is None
            if not ok:
                details.append(f"pathogen: expected None, got '{act_path}' (hallucination?)")
        elif act_path is None:
            ok = False
            details.append(f"pathogen: expected '{exp_path}', got None")
        else:
            ok = exp_path.lower() in act_path.lower() or act_path.lower() in exp_path.lower()
            if not ok:
                details.append(f"pathogen: expected '{exp_path}', got '{act_path}'")
        scores["pathogen"] = ok

    # --- Temperature value ---
    if "temperature_value" in expected:
        exp_val = expected["temperature_value"]
        act_val = extraction.get("temperature_value")

        if exp_val is not None:
            ok = act_val is not None and abs(act_val - exp_val) <= 2.0
            scores["temperature"] = ok
            if not ok:
                details.append(f"temp: expected {exp_val}°C, got {act_val}")
            if not ok and "temperature_value_alt" in expected:
                alt = expected["temperature_value_alt"]
                ok_alt = act_val is not None and abs(act_val - alt) <= 2.0
                if ok_alt:
                    scores["temperature"] = True
                    details = [d for d in details if not d.startswith("temp:")]
                    details.append(f"temp: got alt value {act_val}°C (acceptable)")
        else:
            desc = (extraction.get("temperature_description") or "").lower()
            keywords_str = expected.get("temperature_description_keywords", "")
            if keywords_str:
                keywords = [k.strip().lower() for k in keywords_str.split("|")]
                ok = any(k in desc for k in keywords)
            else:
                ok = True
            scores["temperature"] = ok or act_val is not None
            if not ok and act_val is None:
                details.append(f"temp: expected description with one of '{keywords_str}', got '{desc}'")

    # --- Temperature range preservation ---
    if "temperature_is_range" in expected and expected["temperature_is_range"]:
        exp_min = expected.get("temperature_range_min")
        exp_max = expected.get("temperature_range_max")
        act_is_range = extraction.get("temperature_is_range", False)
        act_min = extraction.get("temperature_range_min")
        act_max = extraction.get("temperature_range_max")
        act_val = extraction.get("temperature_value")

        if act_is_range and act_min is not None and act_max is not None:
            min_ok = abs(act_min - exp_min) <= 1.0 if exp_min is not None else True
            max_ok = abs(act_max - exp_max) <= 1.0 if exp_max is not None else True
            scores["range_preserved"] = min_ok and max_ok
            if not (min_ok and max_ok):
                details.append(f"range: expected {exp_min}-{exp_max}, got {act_min}-{act_max}")
        elif act_val is not None and exp_min is not None and exp_max is not None:
            midpoint = (exp_min + exp_max) / 2
            is_midpoint = abs(act_val - midpoint) < 1.0
            is_bound = abs(act_val - exp_max) < 1.0 or abs(act_val - exp_min) < 1.0
            if is_midpoint and not is_bound:
                scores["range_preserved"] = False
                details.append(f"RANGE COLLAPSED to midpoint {act_val}°C — should be {exp_min}-{exp_max}°C")
            else:
                scores["range_preserved"] = True
                details.append(f"range: collapsed to {act_val}°C (bound, acceptable)")
        else:
            scores["range_preserved"] = True

    # --- Duration ---
    if "duration_minutes" in expected:
        exp_dur = expected["duration_minutes"]
        act_dur = extraction.get("duration_minutes")

        if exp_dur is not None:
            if act_dur is not None and exp_dur > 0:
                ok = abs(act_dur - exp_dur) / exp_dur <= 0.15
            else:
                ok = act_dur is not None
            scores["duration"] = ok
            if not ok:
                details.append(f"duration: expected {exp_dur} min, got {act_dur}")
        else:
            desc = (extraction.get("duration_description") or "").lower()
            keywords_str = expected.get("duration_description_keywords", "")
            if keywords_str:
                keywords = [k.strip().lower() for k in keywords_str.split("|")]
                ok = any(k in desc for k in keywords)
            else:
                ok = True
            scores["duration"] = ok or act_dur is not None
            if not ok and act_dur is None:
                details.append(f"duration: expected description with one of '{keywords_str}', got '{desc}'")

    # --- Duration ambiguity ---
    if "duration_is_ambiguous" in expected:
        ok = extraction.get("duration_is_ambiguous") == expected["duration_is_ambiguous"]
        scores["duration_ambiguous"] = ok
        if not ok:
            details.append(f"duration_ambiguous: expected {expected['duration_is_ambiguous']}, got {extraction.get('duration_is_ambiguous')}")

    # --- Multi-step ---
    if "is_multi_step" in expected:
        ok = extraction.get("is_multi_step") == expected["is_multi_step"]
        scores["is_multi_step"] = ok
        if not ok:
            details.append(f"multi-step: expected {expected['is_multi_step']}, got {extraction.get('is_multi_step')}")

    if "expected_step_count" in expected:
        act_count = extraction.get("step_count", 0)
        ok = act_count == expected["expected_step_count"]
        scores["step_count"] = ok
        if not ok:
            details.append(f"steps: expected {expected['expected_step_count']}, got {act_count}")

    # --- pH ---
    if "ph_value" in expected and expected["ph_value"] is not None:
        act_ph = extraction.get("ph_value")
        ok = act_ph is not None and abs(act_ph - expected["ph_value"]) <= 0.3
        scores["ph"] = ok
        if not ok:
            details.append(f"pH: expected {expected['ph_value']}, got {act_ph}")

    # --- Water activity ---
    if "water_activity" in expected and expected["water_activity"] is not None:
        act_aw = extraction.get("water_activity")
        ok = act_aw is not None and abs(act_aw - expected["water_activity"]) <= 0.03
        scores["aw"] = ok
        if not ok:
            details.append(f"aw: expected {expected['water_activity']}, got {act_aw}")

    # --- Summary ---
    n_fields = len(scores)
    n_correct = sum(scores.values())
    accuracy = n_correct / n_fields if n_fields > 0 else 0.0

    return {
        "scores": scores,
        "accuracy": round(accuracy, 3),
        "model_type_ok": scores.get("model_type", True),
        "details": details,
    }


# ---------------------------------------------------------------------------
# Step 6: Measure consistency across N runs
# ---------------------------------------------------------------------------

def measure_consistency(extractions: list[dict]) -> dict:
    if not extractions:
        return {"field_consistency": {}, "overall": 0.0}

    fields = [
        "food_description", "implied_model_type", "pathogen_mentioned",
        "temperature_value", "temperature_is_range",
        "duration_minutes", "duration_is_ambiguous",
        "is_multi_step",
    ]

    field_consistency = {}
    for field in fields:
        values = [e.get(field) for e in extractions]
        counts = Counter(values)
        most_common_count = counts.most_common(1)[0][1]
        field_consistency[field] = round(most_common_count / len(values), 3)

    overall = sum(field_consistency.values()) / len(field_consistency)
    return {"field_consistency": field_consistency, "overall": round(overall, 3)}


# ---------------------------------------------------------------------------
# Step 7: Run the full experiment
# ---------------------------------------------------------------------------

async def run_experiment(models: list[dict], queries: list[dict], n_runs: int):
    install_token_tracking()
    all_results = []

    for model in models:
        model_name = model["name"]
        model_id = model["litellm_model"]
        mode = model.get("instructor_mode") or "TOOLS"
        print(f"\n{'='*60}")
        print(f"  Model: {model_name}")
        print(f"  LiteLLM ID: {model_id}")
        print(f"  Instructor mode: {mode}")
        print(f"{'='*60}")

        configure_model(model)

        model_results = {
            "model": model_name,
            "litellm_model": model_id,
            "instructor_mode": mode,
            "queries": [],
            "summary": {},
        }
        accuracies = []
        consistencies = []
        latencies = []
        model_type_errors = []
        total_attempts = 0
        total_successes = 0
        total_input_tokens = 0
        total_output_tokens = 0
        total_cost = 0.0
        field_results = defaultdict(list)

        for qi, query in enumerate(queries):
            qid = query["id"]
            print(f"\n  [{qi+1}/{len(queries)}] {qid}: {query['text'][:55]}...")

            runs = await extract_n_times(query["text"], n_runs)

            valid = [r["extraction"] for r in runs if r["extraction"] is not None]
            errors = [r["error"] for r in runs if r["error"] is not None]
            run_latencies = [r["latency_s"] for r in runs if r["extraction"] is not None]
            latencies.extend(run_latencies)

            total_attempts += len(runs)
            total_successes += len(valid)

            run_input_tokens = sum(r["input_tokens"] for r in runs)
            run_output_tokens = sum(r["output_tokens"] for r in runs)
            total_input_tokens += run_input_tokens
            total_output_tokens += run_output_tokens

            query_cost = sum(r["cost_usd"] for r in runs)
            total_cost += query_cost

            if not valid:
                print(f"    X All {n_runs} runs failed: {errors[0] if errors else '?'}")
                model_results["queries"].append({
                    "query_id": qid, "difficulty": query["difficulty"],
                    "accuracy": 0.0, "consistency": 0.0, "model_type_ok": False,
                })
                continue

            scoring = score_extraction(valid[0], query["expected"])
            accuracies.append(scoring["accuracy"])
            if not scoring["model_type_ok"]:
                model_type_errors.append(qid)

            for field_name, correct in scoring["scores"].items():
                field_results[field_name].append(correct)

            consistency = measure_consistency(valid)
            consistencies.append(consistency["overall"])

            mean_lat = sum(run_latencies) / len(run_latencies)
            avg_in = run_input_tokens // max(len(valid), 1)
            avg_out = run_output_tokens // max(len(valid), 1)

            status = "OK" if scoring["accuracy"] >= 0.8 else "~" if scoring["accuracy"] >= 0.5 else "X"
            mt_flag = " !!MT" if not scoring["model_type_ok"] else ""
            print(f"    {status} acc={scoring['accuracy']:.0%}  "
                  f"cons={consistency['overall']:.0%}  "
                  f"lat={mean_lat:.1f}s  "
                  f"tok={avg_in}→{avg_out}{mt_flag}")
            for detail in scoring["details"]:
                print(f"      → {detail}")

            model_results["queries"].append({
                "query_id": qid,
                "difficulty": query["difficulty"],
                "accuracy": scoring["accuracy"],
                "field_scores": scoring["scores"],
                "consistency": consistency["overall"],
                "field_consistency": consistency["field_consistency"],
                "model_type_ok": scoring["model_type_ok"],
                "mean_latency_s": round(mean_lat, 3),
                "input_tokens": run_input_tokens,
                "output_tokens": run_output_tokens,
                "cost_usd": round(query_cost, 6),
                "n_valid": len(valid),
                "n_errors": len(errors),
                "details": scoring["details"],
            })

        # --- Latency percentiles ---
        sorted_lat = sorted(latencies) if latencies else [0]
        n_lat = len(sorted_lat)
        lat_p50 = sorted_lat[n_lat // 2]
        lat_p95 = sorted_lat[int(n_lat * 0.95)]
        lat_mean = sum(sorted_lat) / n_lat

        schema_compliance = total_successes / total_attempts if total_attempts > 0 else 0
        actual_cost_per_call = total_cost / total_successes if total_successes > 0 else 0

        field_accuracy = {
            f: round(sum(v) / len(v), 3) if v else 0
            for f, v in sorted(field_results.items())
        }

        tier_accuracy = {}
        for tier in ["easy", "medium", "hard"]:
            tier_scores = [q["accuracy"] for q in model_results["queries"] if q["difficulty"] == tier]
            tier_accuracy[tier] = round(sum(tier_scores) / len(tier_scores), 3) if tier_scores else 0

        model_results["summary"] = {
            "overall_accuracy": round(sum(accuracies) / len(accuracies), 3) if accuracies else 0,
            "overall_consistency": round(sum(consistencies) / len(consistencies), 3) if consistencies else 0,
            "model_type_accuracy": round(
                sum(1 for q in model_results["queries"] if q.get("model_type_ok", False))
                / len(queries), 3
            ),
            "schema_compliance": round(schema_compliance, 3),
            "latency_p50_s": round(lat_p50, 2),
            "latency_p95_s": round(lat_p95, 2),
            "latency_mean_s": round(lat_mean, 2),
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "actual_cost_per_call_usd": round(actual_cost_per_call, 6),
            "total_cost_usd": round(total_cost, 4),
            "field_accuracy": field_accuracy,
            "tier_accuracy": tier_accuracy,
            "model_type_errors": model_type_errors,
        }

        all_results.append(model_results)

    return all_results


# ---------------------------------------------------------------------------
# Step 8: Save results — timestamped files + "latest" copy
# ---------------------------------------------------------------------------

def save_results(results: list[dict], run_timestamp: str) -> Path:
    out_dir = RESULTS_DIR / "exp_3_3_model_comparison"
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- Full results JSON (timestamped) ---
    json_path = out_dir / f"results_{run_timestamp}.json"
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    # --- Unified summary CSV (timestamped) ---
    #
    # One row per model. All metrics in one file:
    #   - Core metrics (accuracy, consistency, model_type, schema)
    #   - Latency (p50, p95, mean)
    #   - Cost (per call, total)
    #   - Tokens (input, output)
    #   - Tier accuracy (easy, medium, hard)
    #   - Field accuracy (one column per field)
    #
    csv_path = out_dir / f"summary_{run_timestamp}.csv"

    # Collect all field names across models (they may differ slightly)
    all_field_names = sorted(set(
        f for r in results for f in r["summary"]["field_accuracy"].keys()
    ))

    rows = []
    for r in results:
        s = r["summary"]
        row = {
            "model": r["model"],
            "instructor_mode": r.get("instructor_mode", "TOOLS"),
            "accuracy": s["overall_accuracy"],
            "consistency": s["overall_consistency"],
            "model_type_accuracy": s["model_type_accuracy"],
            "schema_compliance": s["schema_compliance"],
            "latency_p50_s": s["latency_p50_s"],
            "latency_p95_s": s["latency_p95_s"],
            "latency_mean_s": s["latency_mean_s"],
            "cost_per_call_usd": s["actual_cost_per_call_usd"],
            "total_cost_usd": s["total_cost_usd"],
            "input_tokens": s["total_input_tokens"],
            "output_tokens": s["total_output_tokens"],
            "tier_easy": s["tier_accuracy"].get("easy", ""),
            "tier_medium": s["tier_accuracy"].get("medium", ""),
            "tier_hard": s["tier_accuracy"].get("hard", ""),
        }
        # Add per-field accuracy columns
        for fname in all_field_names:
            row[f"field_{fname}"] = s["field_accuracy"].get(fname, "")
        rows.append(row)

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    # --- "Latest" copies for quick access ---
    latest_json = out_dir / "latest.json"
    latest_csv = out_dir / "latest.csv"
    shutil.copy2(json_path, latest_json)
    shutil.copy2(csv_path, latest_csv)

    print(f"\n  Results saved to {out_dir}/")
    print(f"    {json_path.name}  — full data")
    print(f"    {csv_path.name}   — unified summary")
    print(f"    latest.json / latest.csv — most recent run")

    return out_dir


# ---------------------------------------------------------------------------
# Step 9: MLflow tracking (optional)
#
# If MLflow is installed, we log:
#   - Parameters: models tested, n_runs, n_queries
#   - Metrics: all summary metrics, per model (prefixed with model name)
#   - Artifacts: the full results JSON and summary CSV
#
# If MLflow is not installed, this is silently skipped.
# Run `mlflow ui --backend-store-uri sqlite:///mlruns.db` to view past experiments.
# ---------------------------------------------------------------------------

def log_to_mlflow(results: list[dict], out_dir: Path,
                  n_runs: int, n_queries: int, run_timestamp: str):
    try:
        import mlflow
    except ImportError:
        print("\n  MLflow not installed — skipping tracking.")
        print("  Install with: pip install mlflow")
        return

    # Local SQLite backend — works on all platforms (including Windows),
    # and is the recommended approach since FileStore was deprecated Feb 2026.
    db_path = PROJECT_ROOT / "mlruns.db"
    mlflow.set_tracking_uri(f"sqlite:///{db_path}")
    mlflow.set_experiment("exp_3_3_model_comparison")

    with mlflow.start_run(run_name=f"run_{run_timestamp}"):
        # Parameters (shared across all models in this run)
        mlflow.log_param("n_runs_per_query", n_runs)
        mlflow.log_param("n_queries", n_queries)
        mlflow.log_param("models", ", ".join(r["model"] for r in results))
        mlflow.log_param("timestamp", run_timestamp)

        # Metrics — one set per model, prefixed with model name
        for r in results:
            model_prefix = r["model"].replace(" ", "_").replace(".", "_").lower()
            s = r["summary"]

            mlflow.log_metric(f"{model_prefix}/accuracy", s["overall_accuracy"])
            mlflow.log_metric(f"{model_prefix}/consistency", s["overall_consistency"])
            mlflow.log_metric(f"{model_prefix}/model_type_accuracy", s["model_type_accuracy"])
            mlflow.log_metric(f"{model_prefix}/schema_compliance", s["schema_compliance"])
            mlflow.log_metric(f"{model_prefix}/latency_p50", s["latency_p50_s"])
            mlflow.log_metric(f"{model_prefix}/latency_p95", s["latency_p95_s"])
            mlflow.log_metric(f"{model_prefix}/cost_per_call", s["actual_cost_per_call_usd"])
            mlflow.log_metric(f"{model_prefix}/total_cost", s["total_cost_usd"])

            for tier, acc in s["tier_accuracy"].items():
                mlflow.log_metric(f"{model_prefix}/tier_{tier}", acc)

            for field, acc in s["field_accuracy"].items():
                mlflow.log_metric(f"{model_prefix}/field_{field}", acc)

        # Artifacts — the full results files
        mlflow.log_artifact(str(out_dir / f"results_{run_timestamp}.json"))
        mlflow.log_artifact(str(out_dir / f"summary_{run_timestamp}.csv"))

    print(f"\n  MLflow: run logged. View with:")
    print(f"    mlflow ui --backend-store-uri sqlite:///{db_path}")


# ---------------------------------------------------------------------------
# Step 10: Print summary
# ---------------------------------------------------------------------------

def print_summary(results: list[dict]):
    # --- Main comparison table ---
    print(f"\n{'='*85}")
    print("  SUMMARY: LLM MODEL COMPARISON")
    print(f"{'='*85}\n")

    header = (f"  {'Model':<20} {'Acc.':>6} {'Cons.':>6} {'MT':>6} "
              f"{'Schema':>7} {'P50':>5} {'P95':>5} {'$/call':>8}")
    print(header)
    print("  " + "-" * 80)

    for r in results:
        s = r["summary"]
        cost_str = f"${s['actual_cost_per_call_usd']:.5f}" if s["actual_cost_per_call_usd"] > 0 else "  n/a"
        print(f"  {r['model']:<20} "
              f"{s['overall_accuracy']:>5.0%} "
              f"{s['overall_consistency']:>5.0%} "
              f"{s['model_type_accuracy']:>5.0%} "
              f"{s['schema_compliance']:>6.0%} "
              f"{s['latency_p50_s']:>4.1f}s "
              f"{s['latency_p95_s']:>4.1f}s "
              f"{cost_str:>8}")

    # --- Accuracy by difficulty tier ---
    print(f"\n  ACCURACY BY DIFFICULTY TIER")
    print(f"  {'Model':<20} {'Easy':>8} {'Medium':>8} {'Hard':>8}")
    print("  " + "-" * 46)
    for r in results:
        ta = r["summary"]["tier_accuracy"]
        print(f"  {r['model']:<20} "
              f"{ta.get('easy', 0):>7.0%} "
              f"{ta.get('medium', 0):>7.0%} "
              f"{ta.get('hard', 0):>7.0%}")

    # --- Field accuracy ---
    all_fields = sorted(set(f for r in results for f in r["summary"]["field_accuracy"]))
    if all_fields:
        display_fields = all_fields[:8]
        print(f"\n  ACCURACY BY FIELD")
        field_header = f"  {'Model':<20}" + "".join(f" {f[:12]:>12}" for f in display_fields)
        print(field_header)
        print("  " + "-" * (20 + 13 * len(display_fields)))
        for r in results:
            fa = r["summary"]["field_accuracy"]
            row = f"  {r['model']:<20}"
            for f in display_fields:
                val = fa.get(f, 0)
                row += f" {val:>11.0%}"
            print(row)

    # --- Model type errors ---
    print(f"\n  MODEL TYPE CLASSIFICATION (SAFETY-CRITICAL)")
    print("  " + "-" * 55)
    any_errors = False
    for r in results:
        errors = r["summary"]["model_type_errors"]
        if errors:
            print(f"  !! {r['model']}: errors on queries {errors}")
            any_errors = True
    if not any_errors:
        print("  OK All models classified all queries correctly.")

    # --- Token usage & cost ---
    print(f"\n  TOKEN USAGE & COST")
    print(f"  {'Model':<20} {'In tok':>10} {'Out tok':>10} {'$/call':>10} {'Total $':>10}")
    print("  " + "-" * 62)
    for r in results:
        s = r["summary"]
        print(f"  {r['model']:<20} "
              f"{s['total_input_tokens']:>10,} "
              f"{s['total_output_tokens']:>10,} "
              f"${s['actual_cost_per_call_usd']:>8.5f} "
              f"${s['total_cost_usd']:>9.4f}")

    # --- Recommendation ---
    print(f"\n  {'─'*55}")
    best = max(results, key=lambda r: (
        r["summary"]["model_type_accuracy"],
        r["summary"]["overall_accuracy"],
        r["summary"]["overall_consistency"],
    ))
    print(f"  Recommended (quality): {best['model']}")

    viable = [r for r in results
              if r["summary"]["model_type_accuracy"] >= 0.9
              and r["summary"]["overall_accuracy"] >= 0.6]
    if viable:
        cheapest = min(viable, key=lambda r: r["summary"]["actual_cost_per_call_usd"]
                       if r["summary"]["actual_cost_per_call_usd"] > 0 else float("inf"))
        if cheapest["model"] != best["model"]:
            print(f"  Recommended (cost):    {cheapest['model']}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(description="Exp 3.3: LLM Model Comparison")
    parser.add_argument("--runs", type=int, default=5,
                        help="Extraction runs per query per model (default: 5)")
    parser.add_argument("--models", type=str, default=None,
                        help="Comma-separated model names (default: all with available keys)")
    parser.add_argument("--no-mlflow", action="store_true",
                        help="Disable MLflow tracking even if installed")
    args = parser.parse_args()

    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"\n{'#'*70}")
    print(f"  EXPERIMENT 3.3: LLM MODEL COMPARISON")
    print(f"  Semantic extraction accuracy, consistency, and latency")
    print(f"  Run: {run_timestamp}")
    print(f"{'#'*70}")

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

    queries = load_queries()
    print(f"\n  Models: {[m['name'] for m in available]}")
    print(f"  Queries: {len(queries)}")
    print(f"  Runs per query: {args.runs}")
    print(f"  Total LLM calls: {len(available) * len(queries) * args.runs}")

    results = await run_experiment(available, queries, args.runs)
    out_dir = save_results(results, run_timestamp)
    print_summary(results)

    if not args.no_mlflow:
        log_to_mlflow(results, out_dir, args.runs, len(queries), run_timestamp)


if __name__ == "__main__":
    asyncio.run(main())
