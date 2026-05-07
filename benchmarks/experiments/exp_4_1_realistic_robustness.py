# -*- coding: utf-8 -*-
"""
Experiment 4.1: Realistic Robustness Benchmark

Tests whether LLMs reliably extract all required fields from realistic,
ambiguous food-safety queries. Unlike exp_3_3 (which scores against expert
ground truth), this experiment uses per-check pass/fail scoring, making it
suitable for queries where the "correct" value is inherently ambiguous.

The motivating case: one query where frontier models extract duration from
"35-day shelf life" but some open-source models fail to populate it at all.

Dataset starts with one query and is designed to grow over time.

Usage:
    python -m benchmarks.experiments.exp_4_1_realistic_robustness
    python -m benchmarks.experiments.exp_4_1_realistic_robustness --runs 10
    python -m benchmarks.experiments.exp_4_1_realistic_robustness --models "GPT-4o,Gemma3 12B"
    python -m benchmarks.experiments.exp_4_1_realistic_robustness --no-mlflow
"""

import asyncio
import argparse
import csv
import json
import os
import math
import shutil
import sys
import time
import threading
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Setup: project root on path, load .env
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from benchmarks.config import MODELS, DATASETS_DIR, RESULTS_DIR


# ---------------------------------------------------------------------------
# Token and cost tracking via acompletion wrapper
#
# Monkey-patches litellm.acompletion to capture token usage and cost before
# Instructor consumes the raw response object. Call install_token_tracking()
# once at startup; collect_and_clear_tokens() around each timed extraction.
# ---------------------------------------------------------------------------

_token_log: list[dict] = []
_token_log_lock = threading.Lock()
_original_acompletion = None


def install_token_tracking():
    """Wrap litellm.acompletion to capture tokens and cost from every API call.

    Uses litellm.completion_cost() for accurate per-model pricing.
    Safe to call multiple times (idempotent).
    """
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
    """Return captured token/cost entries and reset the log."""
    global _token_log
    with _token_log_lock:
        entries = list(_token_log)
        _token_log = []
    return entries


# ---------------------------------------------------------------------------
# Load queries
# ---------------------------------------------------------------------------

def load_queries() -> list[dict]:
    path = DATASETS_DIR / "realistic_queries.json"
    with open(path) as f:
        data = json.load(f)
    return data["queries"]


# ---------------------------------------------------------------------------
# Configure the system to use a specific model
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

    instructor_mode = model_config.get("instructor_mode")

    reset_llm_client()
    client_module._client = LLMClient(
        model=model_config["litellm_model"],
        api_key=api_key,
        api_base=model_config.get("api_base"),
        instructor_mode=instructor_mode,
    )


# ---------------------------------------------------------------------------
# Run extraction N times for a single query
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
    """Convert an ExtractedScenario to a flat dict for check scoring.

    Matches the shape produced by exp_3_3 for consistency.
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
# Scoring — pure functions, one per check kind plus a dispatcher
#
# Four check kinds are defined here, matching exactly what R1 uses.
# Add new kinds only when a future query demands one.
# ---------------------------------------------------------------------------

def _check_populated(value) -> bool:
    """True if value is present and not None or empty string.

    Numeric 0 and boolean False count as populated.
    """
    if value is None:
        return False
    if isinstance(value, str) and value == "":
        return False
    return True


def _check_populated_and_contains(value, any_of: list[str]) -> bool:
    """True if populated and str(value).lower() contains at least one substring."""
    if not _check_populated(value):
        return False
    s = str(value).lower()
    return any(sub.lower() in s for sub in any_of)


def _check_equals(value, expected_value: str) -> bool:
    """True if populated and str(value).lower() == expected_value.lower()."""
    if not _check_populated(value):
        return False
    return str(value).lower() == expected_value.lower()


def _evaluate_sub_check(sub_check: dict, extraction: dict) -> bool:
    value = extraction.get(sub_check["field"])
    kind = sub_check["kind"]
    if kind == "populated":
        return _check_populated(value)
    elif kind == "populated_and_contains":
        return _check_populated_and_contains(value, sub_check["any_of"])
    elif kind == "equals":
        return _check_equals(value, sub_check["value"])
    else:
        raise ValueError(f"Unknown sub-check kind: {kind}")


def evaluate_check(check: dict, extraction: dict) -> bool:
    """Evaluate a single check against a flattened extraction dict."""
    kind = check["kind"]
    if kind == "populated":
        return _check_populated(extraction.get(check["field"]))
    elif kind == "populated_and_contains":
        return _check_populated_and_contains(extraction.get(check["field"]), check["any_of"])
    elif kind == "equals":
        return _check_equals(extraction.get(check["field"]), check["value"])
    elif kind == "any_of_populated":
        return any(_evaluate_sub_check(sub, extraction) for sub in check["fields"])
    else:
        raise ValueError(f"Unknown check kind: {kind}")


def score_run(extraction, checks: list[dict]) -> dict:
    """Return {check_id: bool} for one run. All False if extraction is None."""
    if extraction is None:
        return {c["id"]: False for c in checks}
    return {c["id"]: evaluate_check(c, extraction) for c in checks}


# ---------------------------------------------------------------------------
# Console output helpers
# ---------------------------------------------------------------------------

def _print_query_block(
    query: dict,
    run_records: list[dict],
    checks: list[dict],
    pass_rate_per_check: dict,
):
    """Print per-run check table for one query. Builds all lines, prints at once."""
    check_ids = [c["id"] for c in checks]
    col_w = max((len(cid) for cid in check_ids), default=4) + 2

    lines = []
    lines.append(f"\n  Query {query['id']}: \"{query['text'][:65]}...\"")

    header = f"  {'Run':<5}"
    for cid in check_ids:
        header += f"  {cid:<{col_w}}"
    lines.append(header)
    lines.append("  " + "-" * (5 + (col_w + 2) * len(check_ids)))

    for r in run_records:
        row = f"  {r['run'] + 1:<5}"
        for cid in check_ids:
            cell = "OK" if r["check_results"][cid] else "X"
            row += f"  {cell:<{col_w}}"
        lines.append(row)

    lines.append("  " + "-" * (5 + (col_w + 2) * len(check_ids)))
    summary_row = f"  {'Mean':<5}"
    for cid in check_ids:
        rate_str = f"{pass_rate_per_check[cid]:.0%}"
        summary_row += f"  {rate_str:<{col_w}}"
    lines.append(summary_row)

    print("\n".join(lines))


def print_comparison_table(all_results: list[dict]):
    """Print final cross-model comparison table. Builds all lines, prints at once."""
    all_check_ids: list[str] = []
    seen: set[str] = set()
    for r in all_results:
        for cid in r["summary"]["mean_check_pass_rate_per_check"]:
            if cid not in seen:
                all_check_ids.append(cid)
                seen.add(cid)

    col_w = max((len(cid) for cid in all_check_ids), default=4) + 2

    lines = []
    lines.append(f"\n{'='*85}")
    lines.append("  FINAL COMPARISON: ALL MODELS")
    lines.append(f"{'='*85}\n")

    header = f"  {'Model':<22} {'overall%':>9} {'schema%':>8} {'lat_p50':>8} {'$/call':>9}"
    for cid in all_check_ids:
        header += f"  {cid:<{col_w}}"
    lines.append(header)
    lines.append("  " + "-" * (22 + 9 + 8 + 8 + 9 + 4 + (col_w + 2) * len(all_check_ids)))

    for r in all_results:
        s = r["summary"]
        cost_str = f"${s['actual_cost_per_call_usd']:.5f}" if s["actual_cost_per_call_usd"] > 0 else "    n/a"
        row = (
            f"  {r['model']:<22} "
            f"{s['mean_overall_pass_rate']:>8.0%} "
            f"{s['schema_compliance']:>7.0%} "
            f"{s['latency_p50_s']:>6.1f}s "
            f"{cost_str:>9}"
        )
        for cid in all_check_ids:
            rate = s["mean_check_pass_rate_per_check"].get(cid, 0.0)
            row += f"  {f'{rate:.0%}':<{col_w}}"
        lines.append(row)

    print("\n".join(lines))


# ---------------------------------------------------------------------------
# Run the full experiment
# ---------------------------------------------------------------------------

async def run_experiment(models: list[dict], queries: list[dict], n_runs: int) -> list[dict]:
    install_token_tracking()
    all_results = []

    for model in models:
        model_name = model["name"]
        model_id = model["litellm_model"]
        mode = model.get("instructor_mode") or "TOOLS"

        header_lines = [
            f"\n{'='*60}",
            f"  Model: {model_name}",
            f"  LiteLLM ID: {model_id}",
            f"  Instructor mode: {mode}",
            f"{'='*60}",
        ]
        print("\n".join(header_lines))

        configure_model(model)

        all_latencies: list[float] = []
        total_attempts = 0
        total_successes = 0
        total_input_tokens = 0
        total_output_tokens = 0
        total_cost = 0.0
        query_results = []

        for query in queries:
            qid = query["id"]
            checks = query["checks"]

            runs = await extract_n_times(query["text"], n_runs)

            run_records = []
            for r in runs:
                check_results = score_run(r["extraction"], checks)
                run_records.append({
                    "run": r["run"],
                    "extraction": r["extraction"],
                    "check_results": check_results,
                    "latency_s": r["latency_s"],
                    "input_tokens": r["input_tokens"],
                    "output_tokens": r["output_tokens"],
                    "cost_usd": r["cost_usd"],
                    "error": r["error"],
                })

            n_extractions = sum(1 for r in run_records if r["extraction"] is not None)
            run_latencies = [r["latency_s"] for r in run_records if r["extraction"] is not None]
            all_latencies.extend(run_latencies)

            # Denominator is all runs (including failed extractions), not just valid ones.
            # score_run returns all-False when extraction is None, so failed runs are
            # correctly penalised in the pass rate rather than excluded from it.
            pass_rate_per_check: dict[str, float] = {}
            for check in checks:
                cid = check["id"]
                passes = sum(1 for r in run_records if r["check_results"][cid])
                pass_rate_per_check[cid] = passes / len(run_records) if run_records else 0.0

            overall_pass_rate = (
                sum(pass_rate_per_check.values()) / len(pass_rate_per_check)
                if pass_rate_per_check else 0.0
            )

            mean_latency = sum(run_latencies) / len(run_latencies) if run_latencies else 0.0
            run_input = sum(r["input_tokens"] for r in run_records)
            run_output = sum(r["output_tokens"] for r in run_records)
            run_cost = sum(r["cost_usd"] for r in run_records)

            total_attempts += len(run_records)
            total_successes += n_extractions
            total_input_tokens += run_input
            total_output_tokens += run_output
            total_cost += run_cost

            _print_query_block(query, run_records, checks, pass_rate_per_check)

            query_results.append({
                "query_id": qid,
                "query_text": query["text"],
                "runs": run_records,
                "n_runs": len(run_records),
                "n_extractions": n_extractions,
                "pass_rate_per_check": {k: round(v, 3) for k, v in pass_rate_per_check.items()},
                "overall_pass_rate": round(overall_pass_rate, 3),
                "mean_latency_s": round(mean_latency, 3),
                "total_cost_usd": round(run_cost, 6),
                "total_input_tokens": run_input,
                "total_output_tokens": run_output,
            })

        # Per-model aggregation
        sorted_lat = sorted(all_latencies) if all_latencies else [0.0]
        n_lat = len(sorted_lat)
        lat_p50 = sorted_lat[n_lat // 2]
        lat_p95 = sorted_lat[min(math.ceil(n_lat * 0.95) - 1, n_lat - 1)]
        lat_mean = sum(sorted_lat) / n_lat

        schema_compliance = total_successes / total_attempts if total_attempts > 0 else 0.0
        actual_cost_per_call = total_cost / total_successes if total_successes > 0 else 0.0

        all_cids: list[str] = []
        seen_cids: set[str] = set()
        for qr in query_results:
            for cid in qr["pass_rate_per_check"]:
                if cid not in seen_cids:
                    all_cids.append(cid)
                    seen_cids.add(cid)

        # Simple macro-average across queries; each query weighted equally.
        mean_check_pass_rate: dict[str, float] = {}
        for cid in all_cids:
            rates = [qr["pass_rate_per_check"].get(cid, 0.0) for qr in query_results]
            mean_check_pass_rate[cid] = round(sum(rates) / len(rates), 3)

        mean_overall = (
            sum(qr["overall_pass_rate"] for qr in query_results) / len(query_results)
            if query_results else 0.0
        )

        summary = {
            "mean_overall_pass_rate": round(mean_overall, 3),
            "mean_check_pass_rate_per_check": mean_check_pass_rate,
            "schema_compliance": round(schema_compliance, 3),
            "latency_p50_s": round(lat_p50, 2),
            "latency_p95_s": round(lat_p95, 2),
            "latency_mean_s": round(lat_mean, 2),
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "actual_cost_per_call_usd": round(actual_cost_per_call, 6),
            "total_cost_usd": round(total_cost, 4),
        }

        cost_str = f"${summary['actual_cost_per_call_usd']:.5f}" if summary["actual_cost_per_call_usd"] > 0 else "$0.00000"
        print(
            f"\n  Model {model_name}: "
            f"overall={summary['mean_overall_pass_rate']:.0%} "
            f"schema={summary['schema_compliance']:.0%} "
            f"lat_p50={summary['latency_p50_s']:.1f}s "
            f"$/call={cost_str}"
        )

        all_results.append({
            "model": model_name,
            "litellm_model": model_id,
            "instructor_mode": mode,
            "queries": query_results,
            "summary": summary,
        })

    return all_results


# ---------------------------------------------------------------------------
# Save results — timestamped files + "latest" copies
# ---------------------------------------------------------------------------

def save_results(results: list[dict], queries: list[dict], n_runs: int, run_timestamp: str) -> Path:
    out_dir = RESULTS_DIR / "exp_4_1_realistic_robustness"
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / f"results_{run_timestamp}.json"
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    # Ordered list of (query_id, check_id) pairs for consistent column ordering
    check_columns: list[tuple[str, str]] = []
    for q in queries:
        for c in q["checks"]:
            check_columns.append((q["id"], c["id"]))

    rows = []
    for r in results:
        s = r["summary"]
        row: dict = {
            "model": r["model"],
            "instructor_mode": r.get("instructor_mode", "TOOLS"),
            "n_queries": len(r["queries"]),
            "n_runs_per_query": n_runs,
            "mean_overall_pass_rate": s["mean_overall_pass_rate"],
            "schema_compliance": s["schema_compliance"],
            "latency_p50_s": s["latency_p50_s"],
            "latency_p95_s": s["latency_p95_s"],
            "latency_mean_s": s["latency_mean_s"],
            "cost_per_call_usd": s["actual_cost_per_call_usd"],
            "total_cost_usd": s["total_cost_usd"],
            "input_tokens": s["total_input_tokens"],
            "output_tokens": s["total_output_tokens"],
        }
        for qid, cid in check_columns:
            col = f"{qid}_{cid}"
            qr = next((q for q in r["queries"] if q["query_id"] == qid), None)
            row[col] = qr["pass_rate_per_check"].get(cid, "") if qr else ""
        rows.append(row)

    if not rows:
        print("\n  No results to save.")
        return out_dir

    csv_path = out_dir / f"summary_{run_timestamp}.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    shutil.copy2(json_path, out_dir / "latest.json")
    shutil.copy2(csv_path, out_dir / "latest.csv")

    print(f"\n  Results saved to {out_dir}/")
    print(f"    {json_path.name}  -- full data")
    print(f"    {csv_path.name}   -- unified summary")
    print(f"    latest.json / latest.csv -- most recent run")

    return out_dir


# ---------------------------------------------------------------------------
# MLflow tracking (optional)
# ---------------------------------------------------------------------------

def log_to_mlflow(
    results: list[dict],
    out_dir: Path,
    n_runs: int,
    n_queries: int,
    run_timestamp: str,
):
    try:
        import mlflow
    except ImportError:
        print("\n  MLflow not installed -- skipping tracking.")
        print("  Install with: pip install mlflow")
        return

    db_path = PROJECT_ROOT / "mlruns.db"
    mlflow.set_tracking_uri(f"sqlite:///{db_path}")
    mlflow.set_experiment("exp_4_1_realistic_robustness")

    with mlflow.start_run(run_name=f"run_{run_timestamp}"):
        mlflow.log_param("n_runs_per_query", n_runs)
        mlflow.log_param("n_queries", n_queries)
        mlflow.log_param("models", ", ".join(r["model"] for r in results))
        mlflow.log_param("timestamp", run_timestamp)

        for r in results:
            prefix = r["model"].replace(" ", "_").replace(".", "_").lower()
            s = r["summary"]

            mlflow.log_metric(f"{prefix}/mean_overall_pass_rate", s["mean_overall_pass_rate"])
            mlflow.log_metric(f"{prefix}/schema_compliance", s["schema_compliance"])
            mlflow.log_metric(f"{prefix}/latency_p50", s["latency_p50_s"])
            mlflow.log_metric(f"{prefix}/latency_p95", s["latency_p95_s"])
            mlflow.log_metric(f"{prefix}/cost_per_call", s["actual_cost_per_call_usd"])
            mlflow.log_metric(f"{prefix}/total_cost", s["total_cost_usd"])

            for qr in r["queries"]:
                for cid, rate in qr["pass_rate_per_check"].items():
                    mlflow.log_metric(f"{prefix}/{qr['query_id']}_{cid}", rate)

        mlflow.log_artifact(str(out_dir / f"results_{run_timestamp}.json"))
        mlflow.log_artifact(str(out_dir / f"summary_{run_timestamp}.csv"))

    print(f"\n  MLflow: run logged. View with:")
    print(f"    mlflow ui --backend-store-uri sqlite:///{db_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(description="Exp 4.1: Realistic Robustness Benchmark")
    parser.add_argument("--runs", type=int, default=5,
                        help="Extraction runs per query per model (default: 5)")
    parser.add_argument("--models", type=str, default=None,
                        help="Comma-separated model names (default: all with available keys)")
    parser.add_argument("--no-mlflow", action="store_true",
                        help="Disable MLflow tracking even if installed")
    args = parser.parse_args()

    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"\n{'#'*70}")
    print(f"  EXPERIMENT 4.1: REALISTIC ROBUSTNESS BENCHMARK")
    print(f"  Per-field extraction check scoring on realistic queries")
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
    out_dir = save_results(results, queries, args.runs, run_timestamp)
    print_comparison_table(results)

    if not args.no_mlflow:
        log_to_mlflow(results, out_dir, args.runs, len(queries), run_timestamp)


if __name__ == "__main__":
    asyncio.run(main())
