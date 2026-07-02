# -*- coding: utf-8 -*-
"""
Experiment 2.1: Embedder Comparison for PTM Retrieval Quality

Determines whether a different sentence-transformer embedder fixes known
retrieval failures — species names not matching category-level rows,
property-axis cues (e.g. "pH") dominating food-type cues at retrieval time.

The current production embedder (all-MiniLM-L6-v2) is the baseline.
Four candidate embedders are evaluated in a 2x2 design:
  size (small 22-33M / base 109-110M) x training objective (general / retrieval).

======================================================================
METRICS GUIDE — How to read the results
======================================================================

1. TOP-1 ACCURACY (0-100%)
   What: Fraction of queries where the correct food's doc was ranked #1
         AND its cosine similarity cleared the production threshold.
   Why:  The production system takes the top-1 result above threshold.
         A miss here means the pipeline would retrieve the wrong doc.
   Read: 100% = every query retrieved the right doc above the gate.
         Focus on the MEDIUM stratum (species probes) — that is where
         the baseline fails and the question lives.

2. TOP-3 ACCURACY (0-100%)
   What: Fraction of queries where the correct food's doc was in the
         top-3 AND at least one top-3 result cleared the threshold.
   Read: Higher than top-1 = the right doc exists but ranking is off.
         If top-1 and top-3 are equal, ranking is not the problem.

3. GATE PASS RATE (0-100%)
   What: Fraction of queries where the canonical document's score clears
         the production threshold (0.62, 0.70, or 0.75 by tier).
   Why:  A doc can be ranked #1 but still fail the threshold gate.
         This metric shows how comfortably above (or below) the gate
         the canonical doc lands for each embedder.
   Read: gate_pass_rate > top1_accuracy implies ranking problems
         (right doc has high enough score but isn't ranked first).
         gate_pass_rate < top1_accuracy is structurally impossible
         (if a doc is ranked #1 and above threshold, gate passes).

4. MEAN EXPECTED SCORE (cosine similarity, 0-1)
   What: Average cosine similarity of the canonical doc across positive
         queries (negative controls excluded; N reported separately).
   Read: Higher = the canonical doc is more confidently matched.
         Calibration reference: current Tier 2 gate = 0.62, Tier 1 = 0.70.
         An embedder with mean_expected_score < 0.62 cannot clear the
         current gate reliably even if it ranks correctly.

5. TIER ACCURACY (stratified)
   Strata: easy (specific-food row exists), medium (category-level only),
           hard (negative controls — no doc should clear threshold),
           pathogen (food_pathogen_hazards retrieval).
   Read:  easy accuracy should be near 100% for all candidates.
          medium accuracy is where the meaningful variation is.
          hard accuracy measures false positive rate (inversed: 1.0 = no FPs).

6. LATENCY & LOAD TIMES
   embedder_load_time_s   — one-time model load (cold-start cost)
   corpus_embed_time_s    — one-time corpus embedding (500 docs ~1-10s)
   mean_query_latency_ms  — per-query embed + search; add to pipeline latency

======================================================================
EXPERIMENT TRACKING
======================================================================

Results are saved in two ways:

1. Local files: benchmarks/results/exp_2_1_embedder_comparison/
   - results_YYYYMMDD_HHMMSS.json  -- full data, one dict per embedder
   - summary_YYYYMMDD_HHMMSS.csv   -- one row per embedder, all metrics
   - latest.json / latest.csv      -- copies of most recent run

2. MLflow (if installed): tracks parameters, metrics, and artifacts.
   Install: pip install mlflow
   View:    mlflow ui --backend-store-uri sqlite:///mlruns.db

Per-embedder ChromaDB collections are persisted under:
   benchmarks/results/exp_2_1_embedder_comparison/_chroma/<embedder_id>/

These are safe to delete; they will be rebuilt on the next run.
NEVER touch the production store at data/vector_store/.

======================================================================

Usage:
    python -m benchmarks.experiments.exp_2_1_embedder_comparison
    python -m benchmarks.experiments.exp_2_1_embedder_comparison --embedders minilm-l6-v2,bge-base-en-v1.5
    python -m benchmarks.experiments.exp_2_1_embedder_comparison --queries-subset hard
    python -m benchmarks.experiments.exp_2_1_embedder_comparison --top-k 5
    python -m benchmarks.experiments.exp_2_1_embedder_comparison --no-mlflow
"""

import argparse
import csv
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Setup: project root on path, load .env
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.config import EMBEDDERS, DATASETS_DIR, RESULTS_DIR
from app.config import settings

EXPERIMENT_ID = "exp_2_1_embedder_comparison"

# Top-K results retrieved per query. Expected rank/score is null if the
# canonical doc is not in the top-K. K=10 gives enough depth to diagnose
# ranking problems without excessive ChromaDB overhead.
DEFAULT_TOP_K = 10


# ---------------------------------------------------------------------------
# Step 1: Load ground-truth corpus
# ---------------------------------------------------------------------------

def load_corpus() -> list[dict]:
    """Load the retrieval ground-truth corpus from retrieval_queries.json."""
    path = DATASETS_DIR / "retrieval_queries.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data["queries"]


# ---------------------------------------------------------------------------
# Step 2: Query reformulation — must mirror production RetrievalService exactly
#
# These strings must match app/rag/retrieval.py verbatim:
#   query_food_properties:    "{food} pH water activity properties"
#   query_food_ph:            "{food} pH acidity"
#   query_food_water_activity:"{food} water activity aw moisture"
#   query_pathogen_hazards:   "{food} food hazard"
#
# If the production strings change, update here in the same change.
# ---------------------------------------------------------------------------

_FIELD_TO_SUFFIX = {
    "ph_aw_combined": "pH water activity properties",
    "ph":             "pH acidity",
    "water_activity": "water activity aw moisture",
    "pathogen":       "food hazard",
}


def _format_query(entry: dict) -> str:
    """Reformulate a corpus entry into the production query string."""
    suffix = _FIELD_TO_SUFFIX[entry["field"]]
    return f"{entry['food_description']} {suffix}"


# ---------------------------------------------------------------------------
# Step 3: Threshold lookup — reads from settings, never hard-coded
# ---------------------------------------------------------------------------

def _get_threshold(production_tier: str) -> float:
    """Return the production cosine threshold for a given tier."""
    return {
        "tier_1":          settings.food_properties_confidence,
        "tier_2":          settings.food_properties_fallback_confidence,
        "pathogen_stage_1": settings.pathogen_hazards_confidence,
    }[production_tier]


# ---------------------------------------------------------------------------
# Step 4: Per-query metric calculation
# ---------------------------------------------------------------------------

def _score_query_result(
    top_k: list[dict],
    entry: dict,
    threshold: float,
) -> dict:
    """
    Score a single query's top-K results against the corpus entry.

    Args:
        top_k: Results sorted by score descending. Each element:
               {food_name: str, doc_id: str, score: float}
        entry: Corpus entry (id, acceptable_food_names, tier, etc.)
        threshold: Production cosine threshold for this query's tier.

    Returns:
        Dict with per-query metrics (see module METRICS GUIDE).
    """
    acceptable = entry["acceptable_food_names"]
    is_negative = len(acceptable) == 0
    canonical = acceptable[0] if acceptable else None

    top1 = top_k[0] if top_k else None
    top3 = top_k[:3]

    if is_negative:
        # Correct behaviour: no doc should clear the threshold.
        top1_score = top1["score"] if top1 else 0.0
        correct_at_1 = top1_score < threshold
        correct_at_3 = correct_at_1
        gate_passed = correct_at_1
        expected_score = None
        expected_rank = None
    else:
        # correct_at_1: top-1 food is acceptable AND its score >= threshold.
        correct_at_1 = (
            top1 is not None
            and top1["food_name"] in acceptable
            and top1["score"] >= threshold
        )

        # correct_at_3: any top-3 food is acceptable AND its score >= threshold.
        correct_at_3 = any(
            r["food_name"] in acceptable and r["score"] >= threshold
            for r in top3
        )

        # expected_rank / expected_score: position and score of the canonical
        # (first acceptable) doc in the full top-K list.
        expected_score = None
        expected_rank = None
        for i, r in enumerate(top_k):
            if r["food_name"] == canonical:
                expected_score = r["score"]
                expected_rank = i + 1
                break

        # gate_passed: canonical doc scored >= threshold.
        gate_passed = expected_score is not None and expected_score >= threshold

    return {
        "top1_doc_id":      top1["doc_id"] if top1 else None,
        "top1_food_name":   top1["food_name"] if top1 else None,
        "top1_score":       round(top1["score"], 6) if top1 else None,
        "top3_doc_ids":     [r["doc_id"] for r in top3],
        "top3_food_names":  [r["food_name"] for r in top3],
        "canonical_food_name": canonical,
        "expected_rank":    expected_rank,
        "expected_score":   round(expected_score, 6) if expected_score is not None else None,
        "correct_at_1":     correct_at_1,
        "correct_at_3":     correct_at_3,
        "gate_passed":      gate_passed,
    }


# ---------------------------------------------------------------------------
# Step 5: Per-embedder summary aggregation
# ---------------------------------------------------------------------------

def _compute_embedder_summary(query_results: list[dict]) -> dict:
    """
    Aggregate per-query results into per-embedder summary metrics.

    Errored queries (error != None) are counted separately and excluded from all
    accuracy denominators.  An all-error run returns None for accuracy metrics
    rather than inflating them with the trivial empty-result case.
    """
    n = len(query_results)
    if n == 0:
        return {}

    errored = [r for r in query_results if r.get("error") is not None]
    valid   = [r for r in query_results if r.get("error") is None]
    n_valid   = len(valid)
    n_errored = len(errored)

    positive_scores = [r["expected_score"] for r in valid if r["expected_score"] is not None]
    n_positive = len(positive_scores)

    tier_accuracy: dict[str, float] = {}
    for tier in ("easy", "medium", "hard", "pathogen"):
        tier_qs = [r for r in valid if r.get("tier") == tier]
        if tier_qs:
            tier_accuracy[tier] = round(
                sum(1 for r in tier_qs if r["correct_at_1"]) / len(tier_qs), 4
            )

    latencies = [r.get("latency_ms", 0) for r in query_results]

    return {
        "top1_accuracy":         round(sum(r["correct_at_1"] for r in valid) / n_valid, 6) if n_valid else None,
        "top3_accuracy":         round(sum(r["correct_at_3"] for r in valid) / n_valid, 6) if n_valid else None,
        "gate_pass_rate":        round(sum(r["gate_passed"]  for r in valid) / n_valid, 6) if n_valid else None,
        "mean_expected_score":   round(sum(positive_scores) / n_positive, 4) if n_positive else None,
        "n_positive_queries":    n_positive,
        "n_errored_queries":     n_errored,
        "mean_query_latency_ms": round(sum(latencies) / n, 1),
        "tier_accuracy":         tier_accuracy,
    }


# ---------------------------------------------------------------------------
# Step 6: Document building — mirrors food_safety.py text generation exactly
#
# Duplicated here (not imported) so the benchmark has no dependency on the
# production loader path and can evolve independently.  If food_safety.py
# changes document text generation, update here too and re-embed.
# ---------------------------------------------------------------------------

def _build_food_properties_docs(data_dir: Path) -> list[dict]:
    """
    Build document dicts for food_properties.csv.

    Returns list of {id, text, metadata} mirroring load_food_properties().
    """
    import csv as _csv
    docs = []
    file_path = data_dir / "food_properties.csv"
    with open(file_path, "r", encoding="utf-8") as f:
        reader = _csv.DictReader(f)
        row_idx = 0
        for row in reader:
            if not row.get("food_name") or row["food_name"].startswith("#"):
                continue

            parts = [f"{row['food_name']} ({row['food_category']})"]

            if row.get("ph_min") and row.get("ph_max"):
                if row["ph_min"] == row["ph_max"]:
                    parts.append(f"pH {row['ph_min']}")
                else:
                    parts.append(f"pH range {row['ph_min']} to {row['ph_max']}")
            elif row.get("ph_min"):
                parts.append(f"pH {row['ph_min']}")

            if row.get("aw_min") and row.get("aw_max"):
                if row["aw_min"] == row["aw_max"]:
                    parts.append(f"water activity {row['aw_min']}")
                else:
                    parts.append(f"water activity {row['aw_min']} to {row['aw_max']}")
            elif row.get("aw_min"):
                parts.append(f"water activity {row['aw_min']}")

            if row.get("notes"):
                parts.append(row["notes"])

            doc = (
                ": ".join(parts[:2]) + ". " + ". ".join(parts[2:])
                if len(parts) > 2
                else ": ".join(parts)
            )

            # Append source IDs (same as production)
            ph_source = row.get("ph_source_id", "").strip()
            aw_source = row.get("aw_source_id", "").strip()
            all_sources = list(dict.fromkeys(s for s in [ph_source, aw_source] if s))
            for sid in all_sources:
                doc += f" [{sid}]"

            merged_source_id = ",".join(all_sources)

            docs.append({
                "id":       f"food_properties_{row_idx}",
                "text":     doc,
                "metadata": {
                    "food_name":      row["food_name"],
                    "food_category":  row["food_category"],
                    "ph_min":         row.get("ph_min", ""),
                    "ph_max":         row.get("ph_max", ""),
                    "aw_min":         row.get("aw_min", ""),
                    "aw_max":         row.get("aw_max", ""),
                    "source_id":      merged_source_id,
                    "type":           "food_properties",     # VectorStore.TYPE_FOOD_PROPERTIES
                },
            })
            row_idx += 1

    return docs


def _build_pathogen_hazard_docs(data_dir: Path) -> list[dict]:
    """
    Build document dicts for food_pathogen_hazards.csv.

    Returns list of {id, text, metadata} mirroring load_food_pathogen_hazards().
    """
    import csv as _csv
    docs = []
    file_path = data_dir / "food_pathogen_hazards.csv"
    with open(file_path, "r", encoding="utf-8") as f:
        reader = _csv.DictReader(f)
        row_idx = 0
        for row in reader:
            if not row.get("food_name"):
                continue

            source_id = row.get("source_id", "")
            primary = "primary hazard" if row.get("primary_hazard") == "yes" else "secondary hazard"

            doc = (
                f"Hazard for {row['food_name']}: {row['pathogen']} "
                f"(case fatality rate {row['case_fatality_rate']}, "
                f"{row['annual_deaths_us']} annual US deaths, {primary}). "
                f"Control: {row['control_methods']}. "
            )
            if row.get("notes"):
                doc += row["notes"]
            if source_id:
                doc += f" [{source_id}]"

            docs.append({
                "id":       f"pathogen_hazards_{row_idx}",
                "text":     doc,
                "metadata": {
                    "food_name":          row["food_name"],
                    "food_category":      row["food_category"],
                    "pathogen":           row["pathogen"],
                    "case_fatality_rate": row["case_fatality_rate"],
                    "annual_deaths_us":   row["annual_deaths_us"],
                    "primary_hazard":     row["primary_hazard"],
                    "data_type":          "food_pathogen_hazard",  # Stage 1 filter key
                    "source_id":          source_id,
                    "type":               "pathogen_hazards",      # VectorStore.TYPE_PATHOGEN_HAZARDS
                },
            })
            row_idx += 1

    return docs


# ---------------------------------------------------------------------------
# Step 7: Format helper for nullable percentage values
# ---------------------------------------------------------------------------

def _fmt_pct(x: float | None, width: int = 0) -> str:
    """Format a 0-1 float as a percentage string, or 'n/a' when None."""
    s = f"{x:.0%}" if x is not None else "n/a"
    return s.rjust(width) if width else s


# ---------------------------------------------------------------------------
# Step 8: Load embedder + embed corpus into isolated collection
#
# Uses chromadb.utils.embedding_functions.SentenceTransformerEmbeddingFunction
# rather than a bespoke wrapper.  The built-in handles all three ChromaDB call
# signatures (__call__, embed_documents, embed_query) across versions and
# applies keyword-argument calling that bespoke wrappers miss.
# ---------------------------------------------------------------------------

def load_embedder(embedder_config: dict) -> tuple:
    """Load SentenceTransformerEmbeddingFunction and return (ef, load_time_s)."""
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

    start = time.perf_counter()
    ef = SentenceTransformerEmbeddingFunction(
        model_name=embedder_config["hf_model"],
        normalize_embeddings=True,
    )
    load_time = round(time.perf_counter() - start, 2)
    return ef, load_time


def embed_corpus(
    embedder_config: dict,
    ef,
    data_dir: Path,
    chroma_dir: Path,
) -> tuple:
    """
    Ingest food_properties + food_pathogen_hazards into an isolated collection.

    Returns (collection, food_name_to_doc_id, embed_time_s).

    The collection is persisted under chroma_dir/<embedder_id>/ for
    post-hoc diagnostics. Re-running drops and recreates the collection.

    NEVER writes to the production ChromaDB at data/vector_store/.
    """
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    collection_path = chroma_dir / embedder_config["id"]
    collection_path.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(
        path=str(collection_path),
        settings=ChromaSettings(anonymized_telemetry=False),
    )

    collection_name = "ptm_exp_2_1"
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass

    collection = client.create_collection(
        collection_name,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )

    food_docs = _build_food_properties_docs(data_dir)
    pathogen_docs = _build_pathogen_hazard_docs(data_dir)
    all_docs = food_docs + pathogen_docs

    start = time.perf_counter()
    # Add in batches to avoid potential ChromaDB batch size limits
    batch_size = 100
    for i in range(0, len(all_docs), batch_size):
        batch = all_docs[i: i + batch_size]
        collection.add(
            ids=[d["id"] for d in batch],
            documents=[d["text"] for d in batch],
            metadatas=[d["metadata"] for d in batch],
        )
    embed_time = round(time.perf_counter() - start, 2)

    # Build food_name → doc_id map for diagnostics
    food_name_to_doc_id = {d["metadata"]["food_name"]: d["id"] for d in all_docs}

    return collection, food_name_to_doc_id, embed_time


# ---------------------------------------------------------------------------
# Step 9: Run all corpus queries against a collection
# ---------------------------------------------------------------------------

def _query_collection(
    collection,
    query_text: str,
    top_k: int,
    where_filter: dict | None,
) -> list[dict]:
    """
    Query a ChromaDB collection and return top-K results.

    Returns list of {food_name, doc_id, score} sorted by score descending.
    Cosine distance → confidence: score = 1 - distance (ChromaDB convention).
    Raises on any ChromaDB error — caller must handle so the error is recorded
    rather than silently attributed as a zero-hit result.
    """
    raw = collection.query(
        query_texts=[query_text],
        n_results=top_k,
        where=where_filter if where_filter else None,
    )

    results = []
    if raw and raw["documents"] and raw["documents"][0]:
        for i in range(len(raw["documents"][0])):
            distance = raw["distances"][0][i] if raw["distances"] else 1.0
            score = max(0.0, min(1.0, 1.0 - distance))
            meta = raw["metadatas"][0][i] if raw["metadatas"] else {}
            results.append({
                "food_name": meta.get("food_name", ""),
                "doc_id":    raw["ids"][0][i] if raw["ids"] else None,
                "score":     score,
                "metadata":  meta,
            })

    return sorted(results, key=lambda r: r["score"], reverse=True)


def _build_where_filter(entry: dict) -> dict | None:
    """
    Build a ChromaDB where filter matching what RetrievalService.query() sends.

    Mirrors VectorStore.query() filter construction:
      single key  → plain dict
      multi key   → {"$and": [{k: v}, ...]}
    """
    field = entry["field"]
    if field == "pathogen":
        # doc_type="pathogen_hazards" + where={"data_type": "food_pathogen_hazard"}
        combined = {
            "type": "pathogen_hazards",
            "data_type": "food_pathogen_hazard",
        }
        return {"$and": [{k: v} for k, v in combined.items()]}
    else:
        # doc_type="food_properties"
        return {"type": "food_properties"}


_ERRORED_SCORED_FIELDS = {
    "top1_doc_id":       None,
    "top1_food_name":    None,
    "top1_score":        None,
    "top3_doc_ids":      [],
    "top3_food_names":   [],
    "canonical_food_name": None,
    "expected_rank":     None,
    "expected_score":    None,
    "correct_at_1":      None,
    "correct_at_3":      None,
    "gate_passed":       None,
}


def run_embedder_queries(
    collection,
    corpus: list[dict],
    top_k: int,
) -> list[dict]:
    """
    Run all corpus queries against a collection.  Returns per-query result dicts.

    Each record includes `error: str | None`.  When a ChromaDB exception fires,
    all scored fields are None so the failure is visible and cannot be mistaken
    for a correct answer.  Errored records are excluded from accuracy denominators
    in `_compute_embedder_summary`.
    """
    results = []
    for entry in corpus:
        threshold = _get_threshold(entry["production_tier"])
        query_text = _format_query(entry)
        where_filter = _build_where_filter(entry)

        start = time.perf_counter()
        error: str | None = None
        try:
            top_k_results = _query_collection(collection, query_text, top_k, where_filter)
            scored = _score_query_result(top_k_results, entry, threshold)
        except Exception as exc:
            error = str(exc)
            scored = dict(_ERRORED_SCORED_FIELDS)
            print(f"  !! Query error [{entry['id']}] {query_text!r}: {exc}", flush=True)
        latency_ms = round((time.perf_counter() - start) * 1000, 1)

        result = {
            "query_id":           entry["id"],
            "food_description":   entry["food_description"],
            "field":              entry["field"],
            "production_tier":    entry["production_tier"],
            "tier":               entry["tier"],
            "reformulated_query": query_text,
            "threshold_used":     threshold,
            "latency_ms":         latency_ms,
            "error":              error,
            **scored,
        }
        results.append(result)

    return results


# ---------------------------------------------------------------------------
# Step 10: Run the full experiment
# ---------------------------------------------------------------------------

def run_experiment(
    embedders: list[dict],
    corpus: list[dict],
    data_dir: Path,
    chroma_dir: Path,
    top_k: int = DEFAULT_TOP_K,
) -> list[dict]:
    """Run all embedders against the full corpus.  Returns list of embedder dicts."""
    all_results = []

    for emb in embedders:
        eid = emb["id"]
        print(f"\n{'='*60}")
        print(f"  Embedder: {emb['name']}")
        print(f"  Model:    {emb['hf_model']}")
        print(f"  Dim:      {emb['dim']}   Params: {emb['params_m']}M")
        print(f"{'='*60}")

        print(f"  Loading model...", end="", flush=True)
        ef, load_time = load_embedder(emb)
        print(f" {load_time:.1f}s")

        print(f"  Embedding corpus...", end="", flush=True)
        collection, food_name_to_doc_id, embed_time = embed_corpus(emb, ef, data_dir, chroma_dir)
        print(f" {embed_time:.1f}s  ({len(food_name_to_doc_id)} unique food_names)")

        print(f"  Running {len(corpus)} queries...")
        query_results = run_embedder_queries(collection, corpus, top_k)

        # Attach tier info for summary computation
        summary = _compute_embedder_summary(query_results)

        # Console progress
        acc  = summary.get("top1_accuracy")
        gate = summary.get("gate_pass_rate")
        nerr = summary.get("n_errored_queries", 0)
        print(f"  top1_accuracy={_fmt_pct(acc)}  gate_pass_rate={_fmt_pct(gate)}  "
              f"load={load_time:.1f}s  embed={embed_time:.1f}s"
              + (f"  errors={nerr}" if nerr else ""))
        tier_acc = summary.get("tier_accuracy", {})
        for tier in ("easy", "medium", "hard", "pathogen"):
            if tier in tier_acc:
                print(f"    {tier:<8}: {_fmt_pct(tier_acc[tier])}")

        all_results.append({
            "id":                   eid,
            "name":                 emb["name"],
            "hf_model":             emb["hf_model"],
            "dim":                  emb["dim"],
            "params_m":             emb["params_m"],
            "is_baseline":          emb.get("is_baseline", False),
            "training_objective":   emb.get("training_objective", "general"),
            "load_time_s":          load_time,
            "corpus_embed_time_s":  embed_time,
            "queries":              query_results,
            "summary":              summary,
        })

    return all_results


# ---------------------------------------------------------------------------
# Step 11: Save results
# ---------------------------------------------------------------------------

def save_results(
    embedder_results: list[dict],
    corpus: list[dict],
    run_timestamp: str,
) -> Path:
    out_dir = RESULTS_DIR / EXPERIMENT_ID
    out_dir.mkdir(parents=True, exist_ok=True)

    stratum_counts = {
        "easy":     sum(1 for q in corpus if q["tier"] == "easy"),
        "medium":   sum(1 for q in corpus if q["tier"] == "medium"),
        "hard":     sum(1 for q in corpus if q["tier"] == "hard"),
        "pathogen": sum(1 for q in corpus if q["tier"] == "pathogen"),
    }

    output = {
        "experiment_id": EXPERIMENT_ID,
        "timestamp":     run_timestamp,
        "corpus": {
            "version":       "1.0",
            "total_queries": len(corpus),
            "stratum_counts": stratum_counts,
        },
        "embedders": embedder_results,
    }

    json_path = out_dir / f"results_{run_timestamp}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)

    # Summary CSV — one row per embedder
    rows = []
    for emb in embedder_results:
        s = emb["summary"]
        ta = s.get("tier_accuracy", {})
        rows.append({
            "embedder_id":          emb["id"],
            "embedder_name":        emb["name"],
            "hf_model":             emb["hf_model"],
            "dim":                  emb["dim"],
            "params_m":             emb["params_m"],
            "is_baseline":          emb["is_baseline"],
            "training_objective":   emb["training_objective"],
            "top1_accuracy":        "" if s.get("top1_accuracy") is None else s["top1_accuracy"],
            "top3_accuracy":        "" if s.get("top3_accuracy") is None else s["top3_accuracy"],
            "gate_pass_rate":       "" if s.get("gate_pass_rate") is None else s["gate_pass_rate"],
            "mean_expected_score":  "" if s.get("mean_expected_score") is None else s["mean_expected_score"],
            "n_positive_queries":   s.get("n_positive_queries", ""),
            "n_errored_queries":    s.get("n_errored_queries", 0),
            "mean_query_latency_ms": s.get("mean_query_latency_ms", ""),
            "load_time_s":          emb["load_time_s"],
            "corpus_embed_time_s":  emb["corpus_embed_time_s"],
            "tier_easy":            ta.get("easy", ""),
            "tier_medium":          ta.get("medium", ""),
            "tier_hard":            ta.get("hard", ""),
            "tier_pathogen":        ta.get("pathogen", ""),
        })

    csv_path = out_dir / f"summary_{run_timestamp}.csv"
    if rows:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

    shutil.copy2(json_path, out_dir / "latest.json")
    shutil.copy2(csv_path,  out_dir / "latest.csv")

    print(f"\n  Results saved to {out_dir}/")
    print(f"    {json_path.name}  -- full data")
    print(f"    {csv_path.name}   -- summary per embedder")
    print(f"    latest.json / latest.csv -- most recent run")

    return out_dir


# ---------------------------------------------------------------------------
# Step 12: MLflow tracking (optional)
# ---------------------------------------------------------------------------

def log_to_mlflow(
    embedder_results: list[dict],
    out_dir: Path,
    run_timestamp: str,
):
    try:
        import mlflow
    except ImportError:
        print("\n  MLflow not installed -- skipping tracking.")
        return

    db_path = PROJECT_ROOT / "mlruns.db"
    mlflow.set_tracking_uri(f"sqlite:///{db_path}")
    mlflow.set_experiment(EXPERIMENT_ID)

    with mlflow.start_run(run_name=f"run_{run_timestamp}"):
        mlflow.log_param("n_embedders", len(embedder_results))
        mlflow.log_param("n_queries", len(embedder_results[0]["queries"]) if embedder_results else 0)
        mlflow.log_param("embedders", ", ".join(e["id"] for e in embedder_results))
        mlflow.log_param("timestamp", run_timestamp)

        for emb in embedder_results:
            prefix = emb["id"].replace("-", "_")
            s = emb["summary"]
            ta = s.get("tier_accuracy", {})

            mlflow.log_metric(f"{prefix}/top1_accuracy",       s.get("top1_accuracy", 0))
            mlflow.log_metric(f"{prefix}/top3_accuracy",       s.get("top3_accuracy", 0))
            mlflow.log_metric(f"{prefix}/gate_pass_rate",      s.get("gate_pass_rate", 0))
            if s.get("mean_expected_score") is not None:
                mlflow.log_metric(f"{prefix}/mean_expected_score", s["mean_expected_score"])
            mlflow.log_metric(f"{prefix}/load_time_s",         emb["load_time_s"])
            mlflow.log_metric(f"{prefix}/corpus_embed_time_s", emb["corpus_embed_time_s"])

            for tier, acc in ta.items():
                mlflow.log_metric(f"{prefix}/tier_{tier}", acc)

        mlflow.log_artifact(str(out_dir / f"results_{run_timestamp}.json"))
        mlflow.log_artifact(str(out_dir / f"summary_{run_timestamp}.csv"))

    print(f"\n  MLflow: run logged. View with:")
    print(f"    mlflow ui --backend-store-uri sqlite:///{db_path}")


# ---------------------------------------------------------------------------
# Recommendation logic (single source of truth — imported by dashboard too)
# ---------------------------------------------------------------------------

def compute_recommendation(embedder_results: list[dict]) -> dict:
    """Return a structured recommendation dict.

    Possible ``action`` values:
    - ``"baseline_only"``    — only one embedder (the baseline) was evaluated
    - ``"no_baseline"``      — no baseline embedder present in results
    - ``"no_safe_candidates"`` — every candidate has hard-stratum accuracy < 1.0
    - ``"keep_baseline"``    — best safe candidate does not improve on baseline
    - ``"switch"``           — a safe candidate improves top-1; switching is justified
    """
    baseline = next((e for e in embedder_results if e.get("is_baseline")), None)
    candidates = [e for e in embedder_results if not e.get("is_baseline", False)]

    if baseline is None:
        return {
            "action": "no_baseline",
            "baseline": None,
            "best_candidate": None,
            "delta": None,
        }

    if not candidates:
        return {
            "action": "baseline_only",
            "baseline": baseline,
            "best_candidate": None,
            "delta": None,
        }

    baseline_acc = baseline.get("summary", {}).get("top1_accuracy") or 0

    # Hard-stratum constraint: zero false positives required.
    safe_candidates = [
        e for e in candidates
        if e.get("summary", {}).get("tier_accuracy", {}).get("hard", 0) >= 1.0
    ]

    if not safe_candidates:
        return {
            "action": "no_safe_candidates",
            "baseline": baseline,
            "best_candidate": None,
            "delta": None,
        }

    best = max(safe_candidates, key=lambda e: e.get("summary", {}).get("top1_accuracy") or 0)
    best_acc = best.get("summary", {}).get("top1_accuracy") or 0
    delta = best_acc - baseline_acc

    return {
        "action": "switch" if delta > 0 else "keep_baseline",
        "baseline": baseline,
        "best_candidate": best,
        "delta": delta,
    }


# ---------------------------------------------------------------------------
# Step 13: Print summary
# ---------------------------------------------------------------------------

def print_summary(embedder_results: list[dict]):
    lines = []
    lines.append(f"\n{'='*80}")
    lines.append("  SUMMARY: EMBEDDER COMPARISON (Experiment 2.1)")
    lines.append(f"{'='*80}\n")

    header = (
        f"  {'Embedder':<30} {'Top-1':>7} {'Top-3':>7} {'Gate':>7} "
        f"{'MeanScore':>10} {'Load':>6} {'Embed':>6}"
    )
    lines.append(header)
    lines.append("  " + "-" * 78)

    for emb in embedder_results:
        s = emb["summary"]
        mean_s = s.get("mean_expected_score")
        mean_s_str = f"{mean_s:.4f}" if mean_s is not None else "  n/a"
        marker = " *" if emb["is_baseline"] else "  "
        lines.append(
            f"  {marker}{emb['name']:<28} "
            f"{_fmt_pct(s.get('top1_accuracy'), 6)} "
            f"{_fmt_pct(s.get('top3_accuracy'), 6)} "
            f"{_fmt_pct(s.get('gate_pass_rate'), 6)} "
            f"{mean_s_str:>10} "
            f"{emb['load_time_s']:>5.1f}s "
            f"{emb['corpus_embed_time_s']:>5.1f}s"
        )

    lines.append(f"  * = baseline (production)")

    lines.append(f"\n  ACCURACY BY STRATUM")
    lines.append(f"  {'Embedder':<30} {'Easy':>8} {'Medium':>8} {'Hard':>8} {'Pathogen':>10}")
    lines.append("  " + "-" * 68)
    for emb in embedder_results:
        ta = emb["summary"].get("tier_accuracy", {})
        marker = "*" if emb["is_baseline"] else " "
        lines.append(
            f"  {marker} {emb['name']:<28} "
            f"{_fmt_pct(ta.get('easy'), 7)} "
            f"{_fmt_pct(ta.get('medium'), 7)} "
            f"{_fmt_pct(ta.get('hard'), 7)} "
            f"{_fmt_pct(ta.get('pathogen'), 9)}"
        )

    # Recommendation
    lines.append(f"\n  {'='*60}")
    rec = compute_recommendation(embedder_results)
    action = rec["action"]
    if action == "baseline_only":
        lines.append("  Recommendation: Only the baseline was evaluated.")
    elif action == "no_baseline":
        lines.append("  Recommendation: No baseline embedder found — cannot compare.")
    elif action == "no_safe_candidates":
        lines.append(
            "  Recommendation: Do not switch — all candidates introduced false positives "
            "on the hard (negative-control) stratum. A false positive in production "
            "means an unrelated doc clears the confidence gate, causing silent data corruption."
        )
    elif action == "keep_baseline":
        best = rec["best_candidate"]
        lines.append(
            f"  Recommendation: Keep baseline (all-MiniLM-L6-v2). "
            f"Best safe candidate {best['name']} does not improve top-1 accuracy "
            f"(Δ = {rec['delta']:+.0%})."
        )
    else:  # switch
        best = rec["best_candidate"]
        lines.append(f"  Recommendation: Switch to {best['name']}")
        lines.append(f"  Delta top-1 accuracy vs baseline: {rec['delta']:+.0%}")
        lines.append(f"  Cost: re-embed corpus + rebuild ChromaDB store")
    lines.append(f"  {'='*60}")

    print("\n".join(lines), flush=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")

    parser = argparse.ArgumentParser(description="Exp 2.1: Embedder Comparison")
    parser.add_argument(
        "--embedders", type=str, default=None,
        help="Comma-separated embedder IDs (default: all). "
             "IDs: minilm-l6-v2, bge-small-en-v1.5, bge-base-en-v1.5, mpnet-base-v2"
    )
    parser.add_argument(
        "--queries-subset", type=str, default=None,
        metavar="TIER",
        help="Only run queries of this tier (easy/medium/hard/pathogen)"
    )
    parser.add_argument(
        "--top-k", type=int, default=DEFAULT_TOP_K,
        help=f"Results retrieved per query (default: {DEFAULT_TOP_K})"
    )
    parser.add_argument(
        "--no-mlflow", action="store_true",
        help="Disable MLflow tracking even if installed"
    )
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:
        pass

    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"\n{'#'*70}")
    print(f"  EXPERIMENT 2.1: EMBEDDER COMPARISON")
    print(f"  Retrieval quality across four candidate embedding models")
    print(f"  Run: {run_timestamp}")
    print(f"{'#'*70}")

    # Select embedders
    embedders = EMBEDDERS
    if args.embedders:
        ids = {s.strip() for s in args.embedders.split(",")}
        embedders = [e for e in EMBEDDERS if e["id"] in ids]
        not_found = ids - {e["id"] for e in embedders}
        if not_found:
            print(f"  !! Unknown embedder IDs: {not_found}")
            print(f"     Valid IDs: {[e['id'] for e in EMBEDDERS]}")
        if not embedders:
            print("  X No embedders selected. Exiting.")
            sys.exit(1)

    # Load corpus
    corpus = load_corpus()
    if args.queries_subset:
        corpus = [q for q in corpus if q["tier"] == args.queries_subset]
        if not corpus:
            print(f"  X No queries for tier '{args.queries_subset}'. "
                  f"Valid: easy, medium, hard, pathogen")
            sys.exit(1)

    data_dir = PROJECT_ROOT / "data" / "rag"
    chroma_dir = RESULTS_DIR / EXPERIMENT_ID / "_chroma"
    chroma_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n  Embedders:   {[e['id'] for e in embedders]}")
    print(f"  Corpus:      {len(corpus)} queries")
    if args.queries_subset:
        print(f"  Subset:      tier={args.queries_subset}")
    print(f"  Top-K:       {args.top_k}")
    print(f"  Chroma dir:  {chroma_dir}")
    print(f"  Data dir:    {data_dir}")
    print(f"\n  WARNING: Production store at data/vector_store/ is NOT touched.")

    embedder_results = run_experiment(embedders, corpus, data_dir, chroma_dir, args.top_k)

    out_dir = save_results(embedder_results, corpus, run_timestamp)
    print_summary(embedder_results)

    if not args.no_mlflow:
        log_to_mlflow(embedder_results, out_dir, run_timestamp)


if __name__ == "__main__":
    main()
