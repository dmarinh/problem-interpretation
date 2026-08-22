"""
Experiment 5.1: Organism Clarification Gate — Fire Rate by Category

Background — the organism clarification gate this experiment measures:
when the pipeline can't ground a pathogen for the food in a query, it used
to always fail the request outright. Two phases changed that:
  - A1a (the "ask" half): when the failure reason is one a follow-up
    question could plausibly fix, the API returns
    status="awaiting_clarification" instead of failing, naming which
    OrganismGroundingFailureStage caused it and offering the user a
    pathogen to pick from.
  - A1b (the "answer" half): a second request carrying the user's reply
    lets the pipeline resolve the pathogen and complete the prediction,
    or fail closed if the reply doesn't resolve to something valid.
  - A1c does not exist yet. It would be a follow-up round (asking again
    if the first answer still doesn't resolve things) -- not built,
    because whether it's worth building depends on how often the gate
    fires and why. That's what this experiment answers.

Question: how often does the gate fire, and with which
OrganismGroundingFailureStage? A low overall rate means the gate is a
graceful edge-case exit and building A1c is not urgent. A high
FOOD_UNRECOGNISED rate means the taxonomy bridge is failing on foods it
should resolve, and the gate is masking a retrieval bug -- fix the bridge,
not the gate. A high CATEGORY_HAS_NO_HAZARD_DATA rate means we're at
IFT-2003-T1's (the hazard data source's) coverage ceiling -- a data
boundary no amount of asking fixes, and expanding hazard-data coverage
would be the real next step, not A1c. The stage split is the finding; the
bare rate is not.

This runs the REAL production pipeline (real GroundingService, real
ComBaseModelRegistry, real taxonomy bridge, real vector store at
data/vector_store/, live LLM calls via the real SemanticParser) -- no
mocking. Each query is one call to Orchestrator.translate(), and the
measured outcome is built from the same fields the API response exposes
(TranslationResponse.status, TranslationResponse.clarification.stage),
never internal state (no metadata, no field_audit, no verbose=true).

═══════════════════════════════════════════════════════════════════════
CORPUS
═══════════════════════════════════════════════════════════════════════

Some background on the data this corpus is drawn from, for a reader new
to this project:

  - FoodEx2 is a food classification standard published by EFSA (the
    European Food Safety Authority). This project uses it as a lookup
    table: given a free-text food description from a user, the "taxonomy
    bridge" fuzzy-matches it against FoodEx2's ~2,900 known food names to
    figure out what category of food is being discussed.
  - ptm_category is this project's OWN simplification on top of FoodEx2:
    every one of the ~2,900 FoodEx2 entries is additionally tagged with
    one of 11 broad buckets (meat, dairy, grain, condiment, beverage,
    etc.) in data/rag/food_taxonomy.csv. This experiment stratifies by
    ptm_category, not by the finer-grained FoodEx2 codes.
  - IFT-2003-T1 is the citation for a table (Table 1) published by the
    Institute of Food Technologists in 2003 listing which pathogens are
    associated with which food categories. This project uses it as the
    fallback source for "what pathogen is typically a concern for this
    kind of food" when nothing more specific is known. It does not cover
    every ptm_category -- see below.

Foods are sampled from data/rag/food_taxonomy.csv (2,917 FoodEx2 entries),
stratified by ptm_category with a fixed seed (see SEED / N_PER_CATEGORY
below). A fixed n is drawn per category regardless of that category's
share of the 2,917 rows -- condiment (425 rows) and beverage (182 rows)
are ~21% of the taxonomy by construction (both ptm_categories carry an
explicit "No IFT match" row in ift_category_alignment.csv -- i.e. the
IFT-2003-T1 table simply has no entry for "condiment" or "beverage" as a
category, a gap in the source data, not something this project chose), so
a query-count-weighted sample would report ~21% CATEGORY_HAS_NO_HAZARD_DATA
as if it were a finding about gate behaviour, when it is really an
artifact of taxonomy composition (more condiment/beverage rows exist in
the taxonomy than, say, egg rows). Reporting per-category, with equal n
per category, avoids that.

Each sampled food_name is wrapped in exactly one scenario template so only
the food varies:

    "{food} left out at room temperature for 3 hours"

This project predicts one of three things for a food safety scenario:
bacterial GROWTH (multiplication over time), THERMAL_INACTIVATION (death
from heat), or NON_THERMAL_SURVIVAL (death/survival from other stresses
like acidity). "Left out at room temperature" is a storage scenario with
no cooking and no acidic/preserving ingredient mentioned, so it always
resolves to GROWTH -- the simplest, most common of the three, and the one
that requires the least additional information from the user. Combined
with never naming a pathogen explicitly, this is the plainest possible
path through the pipeline, isolating the organism gate (the thing being
measured) from every other clarifiable/non-clarifiable failure mode this
pipeline has (e.g. failures specific to the other two prediction types,
or failures caused by an unusual scenario shape).

The corpus is generated once (see build_corpus / --regenerate-corpus) and
persisted to benchmarks/datasets/clarification_gate_foods.json. The seed
and per-category n are fixed before the first run; changing either is a
new run (new corpus file via --regenerate-corpus), never an in-place edit
of a completed run's corpus -- see the module docstring's non-goals.

═══════════════════════════════════════════════════════════════════════
OUTCOME CLASSIFICATION (per query) -- always exactly one of three
═══════════════════════════════════════════════════════════════════════

Note on terminology: this codebase calls the pathogen/microorganism being
predicted for (e.g. "Salmonella", "Listeria monocytogenes") the "organism".
"Grounding" the organism means figuring out which specific pathogen applies
to this food -- either the user said so directly, or it's looked up from
data tied to the food/category. A prediction cannot run without one, so if
grounding fails, something has to give: fail the request, ask the user, or
(before this project added the clarification gate) silently guess -- which
is exactly the behaviour this gate was built to replace.

Every query run by this experiment lands in exactly one of three buckets:

  "answered"       -- response.success is True. The pipeline resolved the
                      organism (either directly from the query, or via a
                      fallback lookup, or the gate never had to fire) and
                      completed a full prediction.
  "clarification"  -- response.status == "awaiting_clarification". This is
                      the gate firing: organism grounding failed, but for a
                      reason a follow-up question could fix. Subdivided by
                      response.clarification.stage
                      (food_unrecognised / category_has_no_hazard_data --
                      the only two stages that are "fixable by asking";
                      see the module docstring's Background section).
  "other_failure"  -- response.success is False and status is not
                      awaiting_clarification -- a hard failure the gate
                      does NOT catch. Covers organism-grounding failures
                      that no question would fix (bridge_disabled,
                      internal_no_mappable_candidate), an organism that
                      WAS identified but isn't supported by this pipeline's
                      prediction models, the LLM misclassifying the query
                      as not being a food-safety request at all, and any
                      unhandled error for that query (network issue, LLM
                      timeout, etc).

These three sum to n for every category -- enforced by construction (every
query lands in exactly one bucket) and checked in the summary.

═══════════════════════════════════════════════════════════════════════
COST CONTROL
═══════════════════════════════════════════════════════════════════════

Each query in this experiment triggers a real call to the production
pipeline (Orchestrator.translate(), see build_orchestrator() below), which
in turn calls a real LLM (e.g. GPT-4o -- whatever LLM_MODEL is configured
in .env) twice per query:
  1. classify_intent -- decides whether the query is even a food-safety
     prediction request (as opposed to, say, a general question).
  2. extract_scenario -- parses the free-text query into structured fields
     (food description, temperature, duration, any pathogen mentioned,
     etc.) that the rest of the pipeline works with.
No other stage of the pipeline calls an LLM for this scenario shape: the
retrieval step that looks up food properties (pH, water activity) works by
comparing text embeddings, not by calling an LLM, and the organism-fallback
lookup (deciding which pathogen to suggest for a food category) is a
deterministic ranking over a CSV file, not a model call. So the cost of
this experiment is exactly "2 LLM calls x number of queries", and nothing
else. Token usage and dollar cost per call are captured by intercepting
every LLM call (see install_token_tracking() below) using the same
technique benchmarks/experiments/exp_3_1_model_comparison.py uses, and
summed per query.

Use --dry-run to print the corpus size and a cost estimate (using the
observed per-call cost from the most recent exp_3_1 run for the currently
configured LLM_MODEL, if available) WITHOUT calling any LLM -- i.e. this
is free to run and safe to run repeatedly while tuning corpus size.

Every query's result is cached at benchmarks/results/
exp_5_1_clarification_fire_rate/_cache.json (a JSON dict keyed by corpus
entry id), written to disk immediately after every query completes -- so
if the script is interrupted partway through, or run again later, already-
answered queries are read from this file instead of paying for another LLM
call. Pass --force to ignore the cache and re-query everything (this WILL
re-bill every query -- use it deliberately, not by habit).

═══════════════════════════════════════════════════════════════════════
NON-GOALS
═══════════════════════════════════════════════════════════════════════

No fixes to anything this experiment reveals. No A1c (multi-round). No
corpus tuning after seeing results -- the seed and strata are fixed before
the first real (non-dry-run) invocation; a changed seed or n is a new run
(new corpus file), reported as such, never a silent overwrite.

═══════════════════════════════════════════════════════════════════════
EXPERIMENT TRACKING
═══════════════════════════════════════════════════════════════════════

Results are saved in two ways:

1. Local files: benchmarks/results/exp_5_1_clarification_fire_rate/
   - results_YYYYMMDD_HHMMSS.json  -- full per-query data + per-category summary
   - summary_YYYYMMDD_HHMMSS.csv   -- one row per category
   - latest.json / latest.csv      -- copies of most recent run
   - _cache.json                    -- persistent per-query cache (not timestamped)

2. MLflow (if installed): tracks parameters, metrics, and artifacts.
   Install: pip install mlflow
   View:    mlflow ui --backend-store-uri sqlite:///mlruns.db

═══════════════════════════════════════════════════════════════════════

Usage:
    python -m benchmarks.experiments.exp_5_1_clarification_fire_rate --dry-run
    python -m benchmarks.experiments.exp_5_1_clarification_fire_rate
    python -m benchmarks.experiments.exp_5_1_clarification_fire_rate --n-per-category 20
    python -m benchmarks.experiments.exp_5_1_clarification_fire_rate --regenerate-corpus
    python -m benchmarks.experiments.exp_5_1_clarification_fire_rate --force
    python -m benchmarks.experiments.exp_5_1_clarification_fire_rate --no-mlflow
"""

import argparse
import asyncio
import csv
import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Setup: project root on path, load .env
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from benchmarks.config import DATASETS_DIR, RESULTS_DIR

EXPERIMENT_ID = "exp_5_1_clarification_fire_rate"

# Fixed before the first real run. A changed value is a new run (regenerate
# the corpus file explicitly via --regenerate-corpus) -- never an in-place
# edit of an existing corpus after seeing results.
SEED = 42
N_PER_CATEGORY = 15

SCENARIO_TEMPLATE = "{food} left out at room temperature for 3 hours"

FOOD_TAXONOMY_PATH = PROJECT_ROOT / "data" / "rag" / "food_taxonomy.csv"
CORPUS_PATH = DATASETS_DIR / "clarification_gate_foods.json"

# Fallback used only when no exp_3_1 result is available to read an observed
# per-call cost from (--dry-run cost estimate). Deliberately conservative
# (roughly 15% above the highest observed extract_scenario cost for GPT-4o
# in benchmarks/results/exp_3_1_model_comparison/latest.json at time of
# writing) so an unavailable reference doesn't produce an under-estimate.
_FALLBACK_COST_PER_CALL_USD = 0.008


# ---------------------------------------------------------------------------
# Step 1: Token and cost tracking via acompletion wrapper
#
# "litellm" is the library this project uses to actually talk to whichever
# LLM provider is configured (OpenAI, Anthropic, etc.) -- every LLM call
# in the codebase eventually goes through litellm.acompletion(), regardless
# of which provider is behind it. This function replaces
# ("monkey-patches") that function with a wrapper that first calls the
# real one, then inspects the response for token counts and computes a
# dollar cost via litellm's own pricing table, before returning the
# response completely unchanged to whatever called it. This way, every
# LLM call made anywhere in the pipeline during this experiment (by code
# this script doesn't control the internals of) gets its cost captured
# automatically, without changing any production code.
#
# Identical mechanism to exp_3_1_model_comparison.py -- duplicated rather
# than imported so this experiment has no dependency on that module's
# internals and can evolve independently. See that file for the rationale.
# ---------------------------------------------------------------------------

_token_log: list[dict] = []
_token_log_lock = threading.Lock()
_original_acompletion = None


def install_token_tracking():
    """Wrap litellm.acompletion to capture tokens and cost from every API call."""
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
# Step 2: Corpus -- stratified sample from food_taxonomy.csv, fixed seed
# ---------------------------------------------------------------------------


def _load_taxonomy_rows() -> list[dict]:
    with open(FOOD_TAXONOMY_PATH, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def build_corpus(seed: int = SEED, n_per_category: int = N_PER_CATEGORY) -> dict:
    """
    Stratified sample of food_name by ptm_category, fixed seed.

    Categories are derived from the CSV itself (never hardcoded) so the
    corpus stays correct if the taxonomy gains or loses a category. When a
    category has fewer than n_per_category rows, every row in it is used
    (sample size < n_per_category for that category only -- reported as-is,
    not padded).
    """
    import random

    rows = _load_taxonomy_rows()
    by_category: dict[str, list[dict]] = {}
    for row in rows:
        cat = row.get("ptm_category", "").strip()
        if cat:
            by_category.setdefault(cat, []).append(row)

    rng = random.Random(seed)
    entries = []
    qid = 0
    for cat in sorted(by_category):
        pool = by_category[cat]
        k = min(n_per_category, len(pool))
        sampled = rng.sample(pool, k)
        for row in sampled:
            food = row["food_name"].strip()
            entries.append(
                {
                    "id": f"q{qid:04d}",
                    "ptm_category": cat,
                    "food_name": food,
                    "foodex2_code": row.get("foodex2_code", ""),
                    "query_text": SCENARIO_TEMPLATE.format(food=food),
                }
            )
            qid += 1

    return {
        "seed": seed,
        "n_per_category": n_per_category,
        "scenario_template": SCENARIO_TEMPLATE,
        "generated_at": datetime.now().isoformat(),
        "source_csv": str(FOOD_TAXONOMY_PATH.relative_to(PROJECT_ROOT)),
        "source_csv_row_count": len(rows),
        "categories": sorted(by_category),
        "entries": entries,
    }


def save_corpus(corpus: dict) -> None:
    DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    with open(CORPUS_PATH, "w", encoding="utf-8") as f:
        json.dump(corpus, f, indent=2, ensure_ascii=False)


def load_or_build_corpus(regenerate: bool = False) -> dict:
    if not regenerate and CORPUS_PATH.exists():
        with open(CORPUS_PATH, encoding="utf-8") as f:
            return json.load(f)
    corpus = build_corpus()
    save_corpus(corpus)
    return corpus


# ---------------------------------------------------------------------------
# Step 3: Cache -- per-query results, keyed by corpus entry id
# ---------------------------------------------------------------------------


def _cache_path() -> Path:
    return RESULTS_DIR / EXPERIMENT_ID / "_cache.json"


def load_cache() -> dict:
    path = _cache_path()
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_cache(cache: dict) -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Step 4: Orchestrator wiring -- real production services, no mocking
#
# "Orchestrator" is this project's top-level pipeline runner: given a raw
# text query, its translate() method runs, in order: intent classification
# (is this even a food-safety question?) -> scenario extraction (parse out
# food/temperature/duration/pathogen) -> RAG grounding (look up missing
# details like pH, water activity, or a likely pathogen from reference
# data) -> standardization (fill in remaining defaults, apply the organism
# clarification gate this experiment measures) -> a numeric prediction from
# "ComBase" (the predictive-microbiology model database/equations this
# whole project wraps -- a growth/inactivation-rate model per pathogen).
#
# This function builds a real Orchestrator wired to the SAME services and
# data the live API server uses -- nothing here is a test double or a
# cut-down variant. That's a deliberate choice: this experiment exists to
# measure current PRODUCTION behaviour, not to test a modified version of
# it.
# ---------------------------------------------------------------------------


def build_orchestrator():
    """
    Build a real Orchestrator with real dependencies: the real
    GroundingService (which does the RAG lookups against the real vector
    store at data/vector_store/, and the real "taxonomy bridge" that maps
    a food description to a FoodEx2 category), the real StandardizationService
    (which reads from the real ComBase model registry -- the loaded
    predictive-microbiology model data), and the real SemanticParser (which
    makes live LLM calls using whatever LLM_MODEL is configured in .env).

    Why this function exists at all: normally, a FastAPI web server has a
    "startup" hook (see the `lifespan` function in app/main.py) that runs
    once when the server process starts, before any request is handled. It
    does two things this standalone script has to replicate by hand, since
    there is no web server here to run that hook automatically:
      1. Load data/combase_models.csv into the ComBase engine (the numeric
         model coefficients used for every prediction).
      2. Call VectorStore.initialize() on the RAG vector store (opens the
         on-disk ChromaDB database used for similarity search).
    Skipping either of these doesn't raise an error immediately -- both
    objects can be constructed just fine in their "not yet loaded" state.
    The failure only shows up later, deep inside the first real query, as
    a runtime error (e.g. "VectorStore not initialized. Call initialize()
    first."). This bit the author of this script once already -- see the
    2026-07-17 entry in specs/lessons.md for the full story and the $2.35
    it cost to notice.
    """
    from app.core.orchestrator import Orchestrator
    from app.rag.vector_store import get_vector_store
    from predictive.engines.combase.engine import get_combase_engine

    engine = get_combase_engine()
    if not engine.is_available:
        csv_path = PROJECT_ROOT / "data" / "combase_models.csv"
        engine.load_models(csv_path)

    store = get_vector_store()
    if not store.is_initialized:
        store.initialize()

    return Orchestrator()


# ---------------------------------------------------------------------------
# Step 5: Run one query -- measured from the API response shape only
#
# "TranslationResponse" is the Pydantic model this project's real HTTP
# endpoint (POST /api/v1/translate) returns as JSON. Building one here
# (rather than reading internal Python objects like TranslationResult or
# SessionState directly) means "status" and "clarification.stage" are read
# from exactly the same fields an external API caller would see -- nothing
# from deeper internal state (no metadata, no field_audit, no verbose=true
# detail) sneaks into how a query gets classified below.
# ---------------------------------------------------------------------------


async def run_one_query(orchestrator, entry: dict) -> dict:
    from app.api.schemas.translation import (
        ClarificationInfo,
        TranslationResponse,
    )

    collect_and_clear_tokens()
    start = time.perf_counter()
    error: str | None = None
    try:
        result = await orchestrator.translate(entry["query_text"])
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        result = None
    latency_s = round(time.perf_counter() - start, 3)

    tokens = collect_and_clear_tokens()
    input_tokens = sum(t["input_tokens"] for t in tokens)
    output_tokens = sum(t["output_tokens"] for t in tokens)
    cost_usd = sum(t["cost_usd"] for t in tokens)

    if result is None:
        return {
            "id": entry["id"],
            "ptm_category": entry["ptm_category"],
            "food_name": entry["food_name"],
            "outcome": "other_failure",
            "status": None,
            "success": False,
            "clarification_stage": None,
            "error": error,
            "latency_s": latency_s,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost_usd, 6),
        }

    question = result.state.clarification_question
    clarification = None
    if question is not None:
        clarification = ClarificationInfo(
            reason=question.reason,
            stage=question.stage,
            question=question.question,
        )

    response = TranslationResponse(
        success=result.success,
        session_id=result.state.session_id,
        status=result.state.status,
        created_at=result.state.created_at,
        completed_at=datetime.utcnow(),
        original_query=entry["query_text"],
        error=result.error if not result.success else None,
        clarification=clarification,
    )

    if response.status.value == "awaiting_clarification":
        outcome = "clarification"
    elif response.success:
        outcome = "answered"
    else:
        outcome = "other_failure"

    return {
        "id": entry["id"],
        "ptm_category": entry["ptm_category"],
        "food_name": entry["food_name"],
        "outcome": outcome,
        "status": response.status.value,
        "success": response.success,
        "clarification_stage": (
            response.clarification.stage.value if response.clarification else None
        ),
        "error": response.error,
        "latency_s": latency_s,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost_usd, 6),
    }


# ---------------------------------------------------------------------------
# Step 6: Run the full experiment (cache-aware)
# ---------------------------------------------------------------------------


async def run_experiment(corpus: dict, force: bool = False) -> tuple[list[dict], float]:
    """
    Returns (results, fresh_cost_usd) -- fresh_cost_usd sums ONLY entries
    actually billed in this invocation, never a cache hit's historical cost.
    """
    install_token_tracking()
    orchestrator = build_orchestrator()

    cache = {} if force else load_cache()
    results: list[dict] = []
    entries = corpus["entries"]
    n_cached = 0
    fresh_cost_usd = 0.0

    for i, entry in enumerate(entries):
        qid = entry["id"]
        cached = cache.get(qid)
        # Each corpus entry has a short id like "q0003", used as the cache
        # key. But that id is just a position in the sampling order -- it
        # does NOT uniquely identify a food. If someone reruns this script
        # with a different --n-per-category or --seed, build_corpus()
        # samples a DIFFERENT set of foods, and "q0003" can end up meaning
        # a completely different food than it did in the cached run. Python's
        # random.sample() does not guarantee that a smaller sample is a
        # subset of a larger one from the same seed, so this isn't a rare
        # edge case -- it's the normal outcome of changing either flag.
        # Before trusting a cache hit, double check it's still describing
        # the same food as the current corpus; if not, treat it as a miss
        # (re-query, re-bill) rather than silently returning a stale,
        # wrongly-labeled result under the right id but the wrong food.
        if cached is not None and cached.get("food_name") == entry["food_name"]:
            results.append(cached)
            n_cached += 1
            continue
        if cached is not None:
            print(
                f"  !! Cache id {qid} was for {cached.get('food_name')!r}, "
                f"current corpus has {entry['food_name']!r} -- re-querying "
                f"(different --seed/--n-per-category since that entry was cached)."
            )

        print(
            f"  [{i + 1}/{len(entries)}] ({entry['ptm_category']}) "
            f"{entry['food_name'][:50]!r}...",
            end="",
            flush=True,
        )
        record = await run_one_query(orchestrator, entry)
        outcome_flag = {
            "answered": "OK",
            "clarification": "?",
            "other_failure": "X",
        }[record["outcome"]]
        stage = record["clarification_stage"]
        print(
            f" {outcome_flag} {record['outcome']}"
            + (f" [{stage}]" if stage else "")
            + f"  ({record['latency_s']}s, ${record['cost_usd']:.5f})"
        )

        results.append(record)
        fresh_cost_usd += record.get("cost_usd", 0.0)
        cache[qid] = record
        save_cache(cache)  # write-through: an interrupted run keeps its progress

    if n_cached:
        print(f"\n  {n_cached}/{len(entries)} queries served from cache (no re-bill).")

    return results, fresh_cost_usd


# ---------------------------------------------------------------------------
# Step 7: Per-category summary
# ---------------------------------------------------------------------------


def summarize(results: list[dict], categories: list[str]) -> dict:
    """
    Per-category breakdown. answered + clarification + other_failure == n
    for every category, by construction (checked below, not just claimed).
    """
    per_category = {}
    for cat in categories:
        cat_results = [r for r in results if r["ptm_category"] == cat]
        n = len(cat_results)
        answered = sum(1 for r in cat_results if r["outcome"] == "answered")
        clar = [r for r in cat_results if r["outcome"] == "clarification"]
        other = sum(1 for r in cat_results if r["outcome"] == "other_failure")

        stage_counts: dict[str, int] = {}
        for r in clar:
            stage = r["clarification_stage"] or "unknown"
            stage_counts[stage] = stage_counts.get(stage, 0) + 1

        # Sanity check, not a formality: every query's outcome is computed
        # in run_one_query() as exactly one of "answered"/"clarification"/
        # "other_failure" (an if/elif/else, so it can't be zero or two of
        # them by construction there) -- this assert re-confirms that this
        # aggregation step didn't accidentally drop or double-count a
        # result while grouping by category.
        assert answered + len(clar) + other == n, (
            f"{cat}: {answered} + {len(clar)} + {other} != {n} "
            f"-- every query must land in exactly one outcome bucket"
        )

        per_category[cat] = {
            "n": n,
            "answered": answered,
            "answered_rate": round(answered / n, 3) if n else None,
            "clarification_total": len(clar),
            "clarification_rate": round(len(clar) / n, 3) if n else None,
            "clarification_by_stage": stage_counts,
            "other_failure": other,
            "other_failure_rate": round(other / n, 3) if n else None,
        }

    total_n = len(results)
    total_answered = sum(1 for r in results if r["outcome"] == "answered")
    total_clar = sum(1 for r in results if r["outcome"] == "clarification")
    total_other = sum(1 for r in results if r["outcome"] == "other_failure")
    total_stage_counts: dict[str, int] = {}
    for r in results:
        if r["outcome"] == "clarification":
            stage = r["clarification_stage"] or "unknown"
            total_stage_counts[stage] = total_stage_counts.get(stage, 0) + 1

    return {
        "per_category": per_category,
        # "Taxonomy-weighted", NOT "user-weighted" -- an important distinction
        # for whoever reads this next. This total treats every ptm_category
        # as equally important, because the corpus draws the same n from
        # each one (see build_corpus() and the module docstring's CORPUS
        # section). That is NOT the same as how often real users would ask
        # about each category. For example: if condiment questions make up
        # 2% of real user traffic but this experiment samples condiment at
        # the same rate as, say, meat (which might be 40% of real traffic),
        # then this total's clarification rate is pulled toward whatever
        # condiment's rate is by far more than 2% -- it does not represent
        # what a real user population would experience. Read the per-category
        # rows for the real signal; treat this total as "how the gate
        # behaves averaged across the taxonomy's own categories", not "how
        # often a user hits it".
        "taxonomy_weighted_overall": {
            "n": total_n,
            "answered_rate": round(total_answered / total_n, 3) if total_n else None,
            "clarification_rate": round(total_clar / total_n, 3) if total_n else None,
            "clarification_by_stage": total_stage_counts,
            "other_failure_rate": round(total_other / total_n, 3) if total_n else None,
        },
    }


# ---------------------------------------------------------------------------
# Step 8: Cost estimate (--dry-run)
# ---------------------------------------------------------------------------


def _observed_cost_per_call() -> tuple[float, str]:
    """
    Best-effort observed per-call cost for the currently configured
    LLM_MODEL, read from the most recent exp_3_1_model_comparison run.
    Falls back to a fixed conservative constant if unavailable.

    Returns (cost_per_call_usd, source_description).
    """
    from app.config import settings

    latest = RESULTS_DIR / "exp_3_1_model_comparison" / "latest.json"
    if latest.exists():
        try:
            with open(latest, encoding="utf-8") as f:
                data = json.load(f)
            for r in data:
                if settings.llm_model.lower() in r.get("litellm_model", "").lower():
                    cost = r["summary"]["actual_cost_per_call_usd"]
                    if cost > 0:
                        return (
                            cost,
                            f"observed exp_3_1 extract_scenario cost for {r['model']}",
                        )
        except Exception:
            pass
    return (
        _FALLBACK_COST_PER_CALL_USD,
        "fallback constant (no matching exp_3_1 observation found)",
    )


def print_dry_run(corpus: dict) -> None:
    from app.config import settings

    n = len(corpus["entries"])
    per_call_extract, source = _observed_cost_per_call()
    # classify_intent's prompt+schema are both smaller than extract_scenario's;
    # no observed figure is tracked separately, so this uses a fixed fraction
    # as a rough (deliberately not precise) addition rather than pretending
    # to a precision the estimate doesn't have.
    per_call_classify = per_call_extract * 0.3
    per_query_cost = per_call_extract + per_call_classify
    total_calls = n * 2
    total_cost = n * per_query_cost

    print(f"\n{'=' * 60}")
    print("  DRY RUN -- no LLM calls made")
    print(f"{'=' * 60}")
    print(
        f"  Corpus:            {n} queries across {len(corpus['categories'])} categories"
    )
    print(f"  n per category:    {corpus['n_per_category']}")
    print(f"  Seed:              {corpus['seed']}")
    print(f"  LLM_MODEL:         {settings.llm_model}")
    print("  Calls per query:   2 (classify_intent + extract_scenario)")
    print(f"  Total LLM calls:   {total_calls}")
    print(f"  Cost/call source:  {source}")
    print(f"  Est. cost/query:   ${per_query_cost:.5f}")
    print(f"  Est. TOTAL cost:   ${total_cost:.2f}")
    cached = load_cache()
    already_cached = sum(1 for e in corpus["entries"] if e["id"] in cached)
    if already_cached:
        remaining = n - already_cached
        print(
            f"  Already cached:    {already_cached}/{n} queries "
            f"(re-run would only bill {remaining} query(ies), "
            f"~${remaining * per_query_cost:.2f})"
        )
    print(f"{'=' * 60}\n")


# ---------------------------------------------------------------------------
# Step 9: Save results
# ---------------------------------------------------------------------------


def save_results(
    results: list[dict], corpus: dict, summary: dict, run_timestamp: str
) -> Path:
    out_dir = RESULTS_DIR / EXPERIMENT_ID
    out_dir.mkdir(parents=True, exist_ok=True)

    output = {
        "experiment_id": EXPERIMENT_ID,
        "timestamp": run_timestamp,
        "corpus": {
            "seed": corpus["seed"],
            "n_per_category": corpus["n_per_category"],
            "scenario_template": corpus["scenario_template"],
            "categories": corpus["categories"],
            "total_queries": len(corpus["entries"]),
        },
        "summary": summary,
        "queries": results,
    }

    json_path = out_dir / f"results_{run_timestamp}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)

    csv_path = out_dir / f"summary_{run_timestamp}.csv"
    rows = []
    for cat, s in summary["per_category"].items():
        rows.append(
            {
                "ptm_category": cat,
                "n": s["n"],
                "answered": s["answered"],
                "answered_rate": s["answered_rate"],
                "clarification_total": s["clarification_total"],
                "clarification_rate": s["clarification_rate"],
                "clarification_food_unrecognised": s["clarification_by_stage"].get(
                    "food_unrecognised", 0
                ),
                "clarification_category_has_no_hazard_data": s[
                    "clarification_by_stage"
                ].get("category_has_no_hazard_data", 0),
                "other_failure": s["other_failure"],
                "other_failure_rate": s["other_failure_rate"],
            }
        )
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    import shutil

    shutil.copy2(json_path, out_dir / "latest.json")
    shutil.copy2(csv_path, out_dir / "latest.csv")

    print(f"\n  Results saved to {out_dir}/")
    print(f"    {json_path.name}  -- full per-query data")
    print(f"    {csv_path.name}   -- per-category summary")
    print("    latest.json / latest.csv -- most recent run")

    return out_dir


# ---------------------------------------------------------------------------
# Step 10: MLflow tracking (optional)
# ---------------------------------------------------------------------------


def log_to_mlflow(summary: dict, out_dir: Path, run_timestamp: str, corpus: dict):
    try:
        import mlflow
    except ImportError:
        print("\n  MLflow not installed -- skipping tracking.")
        return

    db_path = PROJECT_ROOT / "mlruns.db"
    mlflow.set_tracking_uri(f"sqlite:///{db_path}")
    mlflow.set_experiment(EXPERIMENT_ID)

    with mlflow.start_run(run_name=f"run_{run_timestamp}"):
        mlflow.log_param("seed", corpus["seed"])
        mlflow.log_param("n_per_category", corpus["n_per_category"])
        mlflow.log_param("n_categories", len(corpus["categories"]))
        mlflow.log_param("scenario_template", corpus["scenario_template"])
        mlflow.log_param("timestamp", run_timestamp)

        overall = summary["taxonomy_weighted_overall"]
        mlflow.log_metric(
            "taxonomy_weighted/answered_rate", overall["answered_rate"] or 0
        )
        mlflow.log_metric(
            "taxonomy_weighted/clarification_rate", overall["clarification_rate"] or 0
        )
        mlflow.log_metric(
            "taxonomy_weighted/other_failure_rate", overall["other_failure_rate"] or 0
        )
        for stage, count in overall["clarification_by_stage"].items():
            mlflow.log_metric(f"taxonomy_weighted/stage_{stage}", count)

        for cat, s in summary["per_category"].items():
            mlflow.log_metric(f"{cat}/answered_rate", s["answered_rate"] or 0)
            mlflow.log_metric(f"{cat}/clarification_rate", s["clarification_rate"] or 0)
            mlflow.log_metric(f"{cat}/other_failure_rate", s["other_failure_rate"] or 0)

        mlflow.log_artifact(str(out_dir / f"results_{run_timestamp}.json"))
        mlflow.log_artifact(str(out_dir / f"summary_{run_timestamp}.csv"))

    print("\n  MLflow: run logged. View with:")
    print(f"    mlflow ui --backend-store-uri sqlite:///{db_path}")


# ---------------------------------------------------------------------------
# Step 11: Print summary
# ---------------------------------------------------------------------------


def _fmt_pct(x, width: int = 0) -> str:
    s = f"{x:.0%}" if x is not None else "n/a"
    return s.rjust(width) if width else s


def print_summary(summary: dict):
    print(f"\n{'=' * 90}")
    print("  SUMMARY: CLARIFICATION GATE FIRE RATE (Experiment 5.1)")
    print(f"{'=' * 90}\n")

    header = (
        f"  {'Category':<12} {'n':>4} {'Answered':>9} {'Clarify':>8} "
        f"{'FOOD_UNREC':>11} {'CAT_NO_HAZ':>11} {'Other':>7}"
    )
    print(header)
    print("  " + "-" * 86)

    for cat, s in summary["per_category"].items():
        stages = s["clarification_by_stage"]
        print(
            f"  {cat:<12} {s['n']:>4} "
            f"{_fmt_pct(s['answered_rate'], 8)} "
            f"{_fmt_pct(s['clarification_rate'], 7)} "
            f"{stages.get('food_unrecognised', 0):>11} "
            f"{stages.get('category_has_no_hazard_data', 0):>11} "
            f"{_fmt_pct(s['other_failure_rate'], 6)}"
        )

    overall = summary["taxonomy_weighted_overall"]
    print("  " + "-" * 86)
    print(
        f"  {'TOTAL':<12} {overall['n']:>4} "
        f"{_fmt_pct(overall['answered_rate'], 8)} "
        f"{_fmt_pct(overall['clarification_rate'], 7)} "
        f"{overall['clarification_by_stage'].get('food_unrecognised', 0):>11} "
        f"{overall['clarification_by_stage'].get('category_has_no_hazard_data', 0):>11} "
        f"{_fmt_pct(overall['other_failure_rate'], 6)}"
    )
    print(
        "\n  NOTE: TOTAL is taxonomy-weighted (equal n per category), not "
        "user-weighted -- it does not\n"
        "  estimate how often real users would trigger the gate. Read the "
        "per-category rows first."
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main():
    parser = argparse.ArgumentParser(
        description="Exp 5.1: Clarification Gate Fire Rate"
    )
    parser.add_argument(
        "--n-per-category",
        type=int,
        default=N_PER_CATEGORY,
        help=f"Foods sampled per ptm_category (default: {N_PER_CATEGORY})",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=SEED,
        help=f"Sampling seed (default: {SEED})",
    )
    parser.add_argument(
        "--regenerate-corpus",
        action="store_true",
        help="Regenerate the corpus file even if one already exists "
        "(new seed/n-per-category -> report as a separate run)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore the cache and re-query every entry (re-bills)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print corpus size and cost estimate; make no LLM calls",
    )
    parser.add_argument(
        "--no-mlflow",
        action="store_true",
        help="Disable MLflow tracking even if installed",
    )
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:
        pass

    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"\n{'#' * 70}")
    print("  EXPERIMENT 5.1: CLARIFICATION GATE FIRE RATE")
    print("  How often does the organism clarification gate fire, and why?")
    print(f"  Run: {run_timestamp}")
    print(f"{'#' * 70}")

    regenerate = args.regenerate_corpus or (
        args.n_per_category != N_PER_CATEGORY or args.seed != SEED
    )
    if regenerate and CORPUS_PATH.exists() and not args.regenerate_corpus:
        print(
            f"\n  NOTE: --n-per-category/--seed differ from the persisted corpus's "
            f"defaults; regenerating {CORPUS_PATH.name} for this run "
            f"(this is a separate run, not an edit of the prior one)."
        )
    corpus = (
        build_corpus(args.seed, args.n_per_category)
        if regenerate
        else load_or_build_corpus()
    )
    if regenerate:
        save_corpus(corpus)

    print(f"\n  Corpus:      {len(corpus['entries'])} queries")
    print(f"  Categories:  {corpus['categories']}")
    print(f"  n/category:  {corpus['n_per_category']}")
    print(f"  Seed:        {corpus['seed']}")
    print(f"  Template:    {corpus['scenario_template']!r}")

    if args.dry_run:
        print_dry_run(corpus)
        return

    print("\n  Running against the REAL production pipeline (live LLM calls).")
    results, fresh_cost_usd = await run_experiment(corpus, force=args.force)

    summary = summarize(results, corpus["categories"])
    out_dir = save_results(results, corpus, summary, run_timestamp)
    print_summary(summary)

    print(f"\n  Total spend this run (cache hits excluded): ${fresh_cost_usd:.4f}")

    if not args.no_mlflow:
        log_to_mlflow(summary, out_dir, run_timestamp, corpus)


if __name__ == "__main__":
    asyncio.run(main())
