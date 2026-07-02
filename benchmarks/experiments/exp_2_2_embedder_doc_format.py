# -*- coding: utf-8 -*-
"""
Experiment 2.2: Embedder x Doc Text Format for PTM Retrieval Quality

A two-factor benchmark: 4 embedders x 3 doc text formats = 12 cells.
Primary metric: MRR (Mean Reciprocal Rank) over positive queries.
Hard-stratum FPR (must be 0.0 for a cell to be eligible for the decision rule).

Doc text formats:
  terse   — space-joined tokens, no connective language, notes verbatim.
  current — exact production output from food_safety.py (verified 2026-05-16).
  verbose — natural-language sentences, no unstated claims added.

======================================================================
METRICS GUIDE
======================================================================

1. MRR (Mean Reciprocal Rank) — PRIMARY
   Computed over positive queries only (negative controls excluded).
   RR for a query = 1/rank of first acceptable doc above threshold, or 0.
   MRR = mean(RR) across positive queries.
   Per-stratum MRR reported separately for easy, medium, pathogen.
   The medium stratum is the key signal: it exercises category-level
   fallback (species probes). See corpus metric_notes for composition caveat.

2. HARD FPR (False Positive Rate on negative controls)
   Fraction of hard-stratum queries where any doc clears the threshold.
   Requirement for decision rule: hard_fpr = 0.0.
   Reported with Type-1 / Type-2 breakdown:
     Type-1: class-noun grounding a specific-row value (unambiguously wrong).
     Type-2: class-noun grounding a category-level row (design-rejected but
             contestable — see corpus hard-stratum notes and specs/lessons.md).

3. THRESHOLD CALIBRATION
   Per-cell, per-production-tier: F1 maximization sweep 0.30-0.90 step 0.01.
   Reports optimal_threshold, f1_at_optimal, f1_at_production.

4. SECONDARY: top-1 accuracy, gate pass rate, mean expected score
   See exp_2_1 METRICS GUIDE for definitions.

======================================================================
PATHOGEN STRATUM NOTE
======================================================================
The pathogen stratum is a sanity check, not a discriminator. The production
query reformulation and all three doc text formats contain the token "hazard",
providing a lexical anchor all embedders exploit. Pathogen-stratum results
confirm harness wiring but cannot rank embedder/format combinations.

======================================================================
HARD-STRATUM FAILURE TAXONOMY
======================================================================
Type-1 failures (H05-H08, H11): class-noun queries grounding specific-row
values — unambiguously wrong because no defensible answer exists.
Type-2 failures (H12): class-noun queries grounding category-level values —
the matched doc would be conservative-correct if the query were less ambiguous;
rejected here on audit-honesty grounds.
Type-0 (real-food absences, H01-H04, H09-H10): species not in KB at the
embedder layer; these typically pass all embedders and confirm the KB boundary.

======================================================================

Usage:
    python -m benchmarks.experiments.exp_2_2_embedder_doc_format
    python -m benchmarks.experiments.exp_2_2_embedder_doc_format --embedders minilm-l6-v2
    python -m benchmarks.experiments.exp_2_2_embedder_doc_format --formats terse,current
    python -m benchmarks.experiments.exp_2_2_embedder_doc_format --queries-subset hard
    python -m benchmarks.experiments.exp_2_2_embedder_doc_format --no-mlflow
"""

import argparse
import csv
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass

from benchmarks.config import EMBEDDERS, DATASETS_DIR, RESULTS_DIR
from app.config import settings

EXPERIMENT_ID = "exp_2_2_embedder_doc_format"
DOC_FORMAT_IDS = ["terse", "current", "verbose"]
DEFAULT_TOP_K = 10

# FPR ceiling for threshold calibration.
# PTM's audit-honesty regime makes false positives strictly costlier than false
# negatives: a FP silently grounds pH/aw from an unrelated doc, while a FN falls
# back to a conservative default that is auditable and explicable. 5% means ~1 FP
# per 20 negative-control queries — low enough for audit-log reviewers to investigate
# each instance. 1% makes most cells unviable on a 12-query hard stratum (1 FP =
# 8.3% > ceiling). 10–20% shifts detection burden to downstream consumers. 5% is a
# defensible compromise; revisit if the hard stratum expands beyond ~30 queries.
FPR_CEILING = 0.05

# MRR floor on the easy stratum for a cell to be eligible for the decision rule.
# Easy queries are exact-species probes against food_properties rows that exist in
# the KB — a retrieval system that cannot reliably rank these at the top has a
# fundamental vocabulary gap that doc-format tuning alone cannot fix.
MRR_EASY_FLOOR = 0.95

# Category-level food names (from category_level_rows.csv).
# A hard-stratum FP whose top-1 match is in this set is a Type-2 failure
# (class-noun grounding a category-level row — design-rejected but contestable).
# All other hard-stratum FPs are Type-1 (specific-row match — unambiguously wrong).
_CATEGORY_LEVEL_FOOD_NAMES = frozenset({
    "fresh poultry",
    "fresh meat",
    "cured meat",
    "fish fresh most",
    "eggs",
})


# ---------------------------------------------------------------------------
# Step 1: Load corpus
# ---------------------------------------------------------------------------

def load_corpus() -> list[dict]:
    path = DATASETS_DIR / "retrieval_queries.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data["queries"]


# ---------------------------------------------------------------------------
# Step 2: Query reformulation — mirrors production RetrievalService exactly.
# Format builders in this file must match exp_2_2_gate3_dryrun.py.
# If production strings change, update here and in the gate3 script.
# ---------------------------------------------------------------------------

_FIELD_TO_SUFFIX = {
    "ph_aw_combined": "pH water activity properties",
    "ph":             "pH acidity",
    "water_activity": "water activity aw moisture",
    "pathogen":       "food hazard",
}


def _format_query(entry: dict) -> str:
    return f"{entry['food_description']} {_FIELD_TO_SUFFIX[entry['field']]}"


def _get_threshold(production_tier: str) -> float:
    return {
        "tier_1":           settings.food_properties_confidence,
        "tier_2":           settings.food_properties_fallback_confidence,
        "pathogen_stage_1": settings.pathogen_hazards_confidence,
    }[production_tier]


# ---------------------------------------------------------------------------
# Step 3: Doc format builders
#
# Duplicated from exp_2_2_gate3_dryrun.py — intentionally self-contained
# so this experiment can evolve independently of the verification artifact.
# If a format changes, update BOTH files and re-embed all affected cells.
# ---------------------------------------------------------------------------

# --- Format A: Terse ---

def _build_food_properties_terse(data_dir: Path) -> list[dict]:
    import csv as _csv
    docs = []
    with open(data_dir / "food_properties.csv", "r", encoding="utf-8") as f:
        reader = _csv.DictReader(f)
        row_idx = 0
        for row in reader:
            if not row.get("food_name") or row["food_name"].startswith("#"):
                continue
            tokens = [row["food_name"], row["food_category"]]
            if row.get("ph_min") and row.get("ph_max"):
                tokens.append(f"pH {row['ph_min']}" if row["ph_min"] == row["ph_max"]
                              else f"pH {row['ph_min']} {row['ph_max']}")
            elif row.get("ph_min"):
                tokens.append(f"pH {row['ph_min']}")
            if row.get("aw_min") and row.get("aw_max"):
                tokens.append(f"aw {row['aw_min']}" if row["aw_min"] == row["aw_max"]
                              else f"aw {row['aw_min']} {row['aw_max']}")
            elif row.get("aw_min"):
                tokens.append(f"aw {row['aw_min']}")
            if row.get("notes"):
                tokens.append(row["notes"])
            ph_source = row.get("ph_source_id", "").strip()
            aw_source = row.get("aw_source_id", "").strip()
            all_sources = list(dict.fromkeys(s for s in [ph_source, aw_source] if s))
            for sid in all_sources:
                tokens.append(f"[{sid}]")
            docs.append({
                "id": f"food_properties_{row_idx}", "text": " ".join(tokens),
                "metadata": {
                    "food_name": row["food_name"], "food_category": row["food_category"],
                    "ph_min": row.get("ph_min", ""), "ph_max": row.get("ph_max", ""),
                    "aw_min": row.get("aw_min", ""), "aw_max": row.get("aw_max", ""),
                    "source_id": ",".join(all_sources), "type": "food_properties",
                },
            })
            row_idx += 1
    return docs


def _build_pathogen_hazards_terse(data_dir: Path) -> list[dict]:
    import csv as _csv
    docs = []
    with open(data_dir / "food_pathogen_hazards.csv", "r", encoding="utf-8") as f:
        reader = _csv.DictReader(f)
        row_idx = 0
        for row in reader:
            if not row.get("food_name"):
                continue
            source_id = row.get("source_id", "")
            primary_label = "primary hazard" if row.get("primary_hazard") == "yes" else "secondary hazard"
            tokens = [
                row["food_name"], row["food_category"], row["pathogen"],
                f"CFR {row['case_fatality_rate']}", f"deaths {row['annual_deaths_us']}",
                primary_label, f"control {row['control_methods']}",
            ]
            if row.get("notes"):
                tokens.append(row["notes"])
            if source_id:
                tokens.append(f"[{source_id}]")
            docs.append({
                "id": f"pathogen_hazards_{row_idx}", "text": " ".join(tokens),
                "metadata": {
                    "food_name": row["food_name"], "food_category": row["food_category"],
                    "pathogen": row["pathogen"], "case_fatality_rate": row["case_fatality_rate"],
                    "annual_deaths_us": row["annual_deaths_us"], "primary_hazard": row["primary_hazard"],
                    "data_type": "food_pathogen_hazard", "source_id": source_id, "type": "pathogen_hazards",
                },
            })
            row_idx += 1
    return docs


# --- Format B: Current (character-for-character verified against production 2026-05-16) ---

def _build_food_properties_current(data_dir: Path) -> list[dict]:
    import csv as _csv
    docs = []
    with open(data_dir / "food_properties.csv", "r", encoding="utf-8") as f:
        reader = _csv.DictReader(f)
        row_idx = 0
        for row in reader:
            if not row.get("food_name") or row["food_name"].startswith("#"):
                continue
            parts = [f"{row['food_name']} ({row['food_category']})"]
            if row.get("ph_min") and row.get("ph_max"):
                parts.append(f"pH {row['ph_min']}" if row["ph_min"] == row["ph_max"]
                             else f"pH range {row['ph_min']} to {row['ph_max']}")
            elif row.get("ph_min"):
                parts.append(f"pH {row['ph_min']}")
            if row.get("aw_min") and row.get("aw_max"):
                parts.append(f"water activity {row['aw_min']}" if row["aw_min"] == row["aw_max"]
                             else f"water activity {row['aw_min']} to {row['aw_max']}")
            elif row.get("aw_min"):
                parts.append(f"water activity {row['aw_min']}")
            if row.get("notes"):
                parts.append(row["notes"])
            doc = (": ".join(parts[:2]) + ". " + ". ".join(parts[2:])
                   if len(parts) > 2 else ": ".join(parts))
            ph_source = row.get("ph_source_id", "").strip()
            aw_source = row.get("aw_source_id", "").strip()
            all_sources = list(dict.fromkeys(s for s in [ph_source, aw_source] if s))
            for sid in all_sources:
                doc += f" [{sid}]"
            docs.append({
                "id": f"food_properties_{row_idx}", "text": doc,
                "metadata": {
                    "food_name": row["food_name"], "food_category": row["food_category"],
                    "ph_min": row.get("ph_min", ""), "ph_max": row.get("ph_max", ""),
                    "aw_min": row.get("aw_min", ""), "aw_max": row.get("aw_max", ""),
                    "source_id": ",".join(all_sources), "type": "food_properties",
                },
            })
            row_idx += 1
    return docs


def _build_pathogen_hazards_current(data_dir: Path) -> list[dict]:
    import csv as _csv
    docs = []
    with open(data_dir / "food_pathogen_hazards.csv", "r", encoding="utf-8") as f:
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
                "id": f"pathogen_hazards_{row_idx}", "text": doc,
                "metadata": {
                    "food_name": row["food_name"], "food_category": row["food_category"],
                    "pathogen": row["pathogen"], "case_fatality_rate": row["case_fatality_rate"],
                    "annual_deaths_us": row["annual_deaths_us"], "primary_hazard": row["primary_hazard"],
                    "data_type": "food_pathogen_hazard", "source_id": source_id, "type": "pathogen_hazards",
                },
            })
            row_idx += 1
    return docs


# --- Format C: Verbose ---

def _build_food_properties_verbose(data_dir: Path) -> list[dict]:
    import csv as _csv
    docs = []
    with open(data_dir / "food_properties.csv", "r", encoding="utf-8") as f:
        reader = _csv.DictReader(f)
        row_idx = 0
        for row in reader:
            if not row.get("food_name") or row["food_name"].startswith("#"):
                continue
            food_label = row["food_name"][:1].upper() + row["food_name"][1:]
            sentences = [f"{food_label} is a {row['food_category']} product."]
            if row.get("ph_min") and row.get("ph_max"):
                sentences.append(f"Its pH is {row['ph_min']}." if row["ph_min"] == row["ph_max"]
                                 else f"Its pH ranges from {row['ph_min']} to {row['ph_max']}.")
            elif row.get("ph_min"):
                sentences.append(f"Its pH is {row['ph_min']}.")
            if row.get("aw_min") and row.get("aw_max"):
                sentences.append(f"Its water activity is {row['aw_min']}." if row["aw_min"] == row["aw_max"]
                                 else f"Its water activity ranges from {row['aw_min']} to {row['aw_max']}.")
            elif row.get("aw_min"):
                sentences.append(f"Its water activity is {row['aw_min']}.")
            if row.get("notes"):
                sentences.append(f"Note: {row['notes']}.")
            ph_source = row.get("ph_source_id", "").strip()
            aw_source = row.get("aw_source_id", "").strip()
            all_sources = list(dict.fromkeys(s for s in [ph_source, aw_source] if s))
            if all_sources:
                sentences.append(" ".join(f"[{sid}]" for sid in all_sources))
            docs.append({
                "id": f"food_properties_{row_idx}", "text": " ".join(sentences),
                "metadata": {
                    "food_name": row["food_name"], "food_category": row["food_category"],
                    "ph_min": row.get("ph_min", ""), "ph_max": row.get("ph_max", ""),
                    "aw_min": row.get("aw_min", ""), "aw_max": row.get("aw_max", ""),
                    "source_id": ",".join(all_sources), "type": "food_properties",
                },
            })
            row_idx += 1
    return docs


def _build_pathogen_hazards_verbose(data_dir: Path) -> list[dict]:
    import csv as _csv
    docs = []
    with open(data_dir / "food_pathogen_hazards.csv", "r", encoding="utf-8") as f:
        reader = _csv.DictReader(f)
        row_idx = 0
        for row in reader:
            if not row.get("food_name"):
                continue
            source_id = row.get("source_id", "")
            food_label = row["food_name"][:1].upper() + row["food_name"][1:]
            primary_label = "a primary" if row.get("primary_hazard") == "yes" else "a secondary"
            doc = (
                f"{food_label} ({row['food_category']}) is associated with {primary_label} "
                f"food safety hazard: {row['pathogen']}. "
                f"Case fatality rate is {row['case_fatality_rate']}, with an estimated "
                f"{row['annual_deaths_us']} annual US deaths. "
                f"Recommended controls include {row['control_methods']}."
            )
            if row.get("notes"):
                doc += f" {row['notes']}"
            if source_id:
                doc += f" [{source_id}]"
            docs.append({
                "id": f"pathogen_hazards_{row_idx}", "text": doc,
                "metadata": {
                    "food_name": row["food_name"], "food_category": row["food_category"],
                    "pathogen": row["pathogen"], "case_fatality_rate": row["case_fatality_rate"],
                    "annual_deaths_us": row["annual_deaths_us"], "primary_hazard": row["primary_hazard"],
                    "data_type": "food_pathogen_hazard", "source_id": source_id, "type": "pathogen_hazards",
                },
            })
            row_idx += 1
    return docs


# --- Dispatch ---

_DOC_FORMAT_BUILDERS: dict[str, tuple] = {
    "terse":   (_build_food_properties_terse,   _build_pathogen_hazards_terse),
    "current": (_build_food_properties_current,  _build_pathogen_hazards_current),
    "verbose": (_build_food_properties_verbose,  _build_pathogen_hazards_verbose),
}


def build_corpus_docs(format_id: str, data_dir: Path) -> list[dict]:
    fp_builder, ph_builder = _DOC_FORMAT_BUILDERS[format_id]
    return fp_builder(data_dir) + ph_builder(data_dir)


# ---------------------------------------------------------------------------
# Step 4: Embedder loading
# ---------------------------------------------------------------------------

def load_embedder(embedder_config: dict) -> tuple:
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
    start = time.perf_counter()
    ef = SentenceTransformerEmbeddingFunction(
        model_name=embedder_config["hf_model"],
        normalize_embeddings=True,
    )
    return ef, round(time.perf_counter() - start, 2)


# ---------------------------------------------------------------------------
# Step 5: Cell collection builder
# ---------------------------------------------------------------------------

def build_cell_collection(
    embedder_config: dict,
    format_id: str,
    docs: list[dict],
    ef,
    chroma_dir: Path,
) -> tuple:
    """
    Ingest docs into an isolated ChromaDB collection for one (embedder x format) cell.
    ef is already loaded — pass the same instance across all format cells per embedder.
    NEVER touches data/vector_store/ (production store).
    """
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    cell_id = f"{embedder_config['id']}_{format_id}"
    cell_path = chroma_dir / cell_id
    cell_path.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(
        path=str(cell_path),
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    collection_name = f"ptm_exp_2_2_{cell_id}"
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass
    collection = client.create_collection(
        collection_name,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )

    start = time.perf_counter()
    batch_size = 100
    for i in range(0, len(docs), batch_size):
        batch = docs[i:i + batch_size]
        collection.add(
            ids=[d["id"] for d in batch],
            documents=[d["text"] for d in batch],
            metadatas=[d["metadata"] for d in batch],
        )
    return collection, round(time.perf_counter() - start, 2)


# ---------------------------------------------------------------------------
# Step 6: Query helpers
# ---------------------------------------------------------------------------

def _query_collection(
    collection,
    query_text: str,
    top_k: int,
    where_filter: dict | None,
) -> list[dict]:
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
                "doc_id":    raw["ids"][0][i],
                "score":     score,
            })
    return sorted(results, key=lambda r: r["score"], reverse=True)


def _build_where_filter(field: str) -> dict | None:
    if field == "pathogen":
        return {"$and": [{"type": "pathogen_hazards"}, {"data_type": "food_pathogen_hazard"}]}
    return {"type": "food_properties"}


# ---------------------------------------------------------------------------
# Step 7: Per-query metric calculation (v2 — adds reciprocal_rank)
# ---------------------------------------------------------------------------

def _score_query_result(
    top_k: list[dict],
    entry: dict,
    threshold: float,
) -> dict:
    acceptable = entry["acceptable_food_names"]
    is_negative = len(acceptable) == 0
    canonical = acceptable[0] if acceptable else None

    top1 = top_k[0] if top_k else None
    top3 = top_k[:3]

    if is_negative:
        top1_score = top1["score"] if top1 else 0.0
        correct_at_1 = top1_score < threshold
        reciprocal_rank = None  # negative controls excluded from MRR
        expected_score = None
        expected_rank = None
        gate_passed = correct_at_1
    else:
        correct_at_1 = (
            top1 is not None
            and top1["food_name"] in acceptable
            and top1["score"] >= threshold
        )

        # Reciprocal rank: 1/rank of first acceptable doc above threshold
        rr = 0.0
        for rank, r in enumerate(top_k, 1):
            if r["food_name"] in acceptable and r["score"] >= threshold:
                rr = 1.0 / rank
                break
        reciprocal_rank = rr

        expected_score = None
        expected_rank = None
        for i, r in enumerate(top_k):
            if r["food_name"] == canonical:
                expected_score = r["score"]
                expected_rank = i + 1
                break

        gate_passed = expected_score is not None and expected_score >= threshold

    # pure_reciprocal_rank: rank-based, threshold-invariant (1/rank of canonical doc).
    # None for negatives (excluded from MRR). 0.0 for positives where canonical not retrieved.
    if is_negative:
        pure_reciprocal_rank = None
    else:
        pure_reciprocal_rank = round(1.0 / expected_rank, 6) if expected_rank else 0.0

    return {
        "top1_doc_id":           top1["doc_id"] if top1 else None,
        "top1_food_name":        top1["food_name"] if top1 else None,
        "top1_score":            round(top1["score"], 6) if top1 else None,
        "top3_food_names":       [r["food_name"] for r in top3],
        "canonical_food_name":   canonical,
        "acceptable_food_names": acceptable,
        "is_negative":           is_negative,
        "expected_rank":         expected_rank,
        "expected_score":        round(expected_score, 6) if expected_score is not None else None,
        "pure_reciprocal_rank":  pure_reciprocal_rank,
        "reciprocal_rank":       round(reciprocal_rank, 6) if reciprocal_rank is not None else None,
        "correct_at_1":          correct_at_1,
        "gate_passed":           gate_passed,
    }


_ERRORED_SCORED_FIELDS = {
    "top1_doc_id": None, "top1_food_name": None, "top1_score": None,
    "top3_food_names": [], "canonical_food_name": None,
    "acceptable_food_names": [], "is_negative": None,
    "expected_rank": None, "expected_score": None,
    "pure_reciprocal_rank": None, "reciprocal_rank": None,
    "correct_at_1": None, "gate_passed": None,
}


def _recompute_query_at_threshold(record: dict, threshold: float) -> dict:
    """
    Recompute threshold-dependent fields (correct_at_1, gate_passed, reciprocal_rank)
    at a different threshold, using stored top1_score and expected_score/expected_rank.

    reciprocal_rank is approximated: we only store top1 and the canonical doc's score;
    scores at intermediate ranks are unavailable without re-querying ChromaDB. The
    approximation assumes no other acceptable doc appears above the canonical's rank —
    correct for single-acceptable-name queries; may undercount for multi-name queries.
    """
    if record.get("error"):
        return record

    is_negative   = record.get("is_negative", False)
    top1_score    = record.get("top1_score") or 0.0
    top1_food     = record.get("top1_food_name")
    acceptable    = record.get("acceptable_food_names") or []
    exp_score     = record.get("expected_score")
    exp_rank      = record.get("expected_rank")

    if is_negative:
        correct_at_1     = top1_score < threshold
        reciprocal_rank  = None
        gate_passed      = correct_at_1
    else:
        top1_above = top1_score >= threshold
        top1_match = top1_food in acceptable if top1_food else False

        if top1_match and top1_above:
            correct_at_1    = True
            reciprocal_rank = 1.0
        else:
            correct_at_1    = False
            if exp_score is not None and exp_rank is not None and exp_score >= threshold:
                reciprocal_rank = round(1.0 / exp_rank, 6)
            else:
                reciprocal_rank = 0.0

        gate_passed = exp_score is not None and exp_score >= threshold

    return {
        **record,
        "threshold_used":  threshold,
        "correct_at_1":    correct_at_1,
        "gate_passed":     gate_passed,
        "reciprocal_rank": reciprocal_rank,
    }


# ---------------------------------------------------------------------------
# Step 8: Threshold calibration sweep
# ---------------------------------------------------------------------------

def _threshold_sweep(query_results: list[dict], production_tier: str) -> dict:
    """
    FPR-constrained threshold calibration.

    Sweep 0.30–0.90 (step 0.01). For each threshold compute TP, FP, FN, TN, F1,
    FPR (= FP / (FP + TN)). A threshold is *viable* if FPR ≤ FPR_CEILING.
    optimal_threshold = argmax F1 over viable thresholds, or null if none are viable.

    Returns the full sweep curve plus calibration summary.
    """
    tier_qs = [r for r in query_results if r.get("production_tier") == production_tier
               and r.get("error") is None]
    if not tier_qs:
        return {
            "optimal_threshold": None, "viable": False,
            "f1_at_optimal": None, "fpr_at_optimal": None,
            "f1_at_production": None, "fpr_at_production": None,
            "production_threshold": None, "sweep": [],
        }

    production_threshold = _get_threshold(production_tier)
    n_negatives_in_tier  = sum(1 for r in tier_qs if r.get("is_negative"))
    n_positives_in_tier  = len(tier_qs) - n_negatives_in_tier
    thresholds = [round(0.30 + i * 0.01, 2) for i in range(61)]  # 0.30..0.90

    sweep = []
    prod_f1 = prod_fpr = 0.0

    for t in thresholds:
        tp = fp = fn = tn = 0
        for r in tier_qs:
            top1_score = r.get("top1_score") or 0.0
            top1_above = top1_score >= t
            if r.get("is_negative"):
                if top1_above:
                    fp += 1
                else:
                    tn += 1
            else:
                top1_correct = r.get("top1_food_name") in (r.get("acceptable_food_names") or [])
                if top1_correct and top1_above:
                    tp += 1
                elif top1_above and not top1_correct:
                    fp += 1
                else:
                    fn += 1

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1  = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0

        sweep.append({
            "threshold": t,
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "f1": round(f1, 4), "fpr": round(fpr, 4),
        })

        if abs(t - production_threshold) < 0.005:
            prod_f1 = f1
            prod_fpr = fpr

    # If no negative-control queries are present in this tier, FPR is undefined (0/0).
    # Returning viable=None signals a corpus coverage gap, not a calibration failure.
    if n_negatives_in_tier == 0:
        return {
            "viable":               None,
            "optimal_threshold":    None,
            "reason":               "FPR_undefined_no_negatives_in_tier",
            "n_positives_in_tier":  n_positives_in_tier,
            "n_negatives_in_tier":  0,
            "f1_at_optimal":        None,
            "fpr_at_optimal":       None,
            "f1_at_production":     round(prod_f1, 4),
            "fpr_at_production":    None,
            "production_threshold": production_threshold,
            "sweep":                sweep,
        }

    # Viable = any sweep point satisfies FPR_CEILING
    viable_points = [s for s in sweep if s["fpr"] <= FPR_CEILING]

    if viable_points:
        best = max(viable_points, key=lambda s: s["f1"])
        optimal_threshold = best["threshold"]
        f1_at_optimal  = best["f1"]
        fpr_at_optimal = best["fpr"]
        viable: bool | None = True
    else:
        optimal_threshold = None
        f1_at_optimal  = None
        fpr_at_optimal = None
        viable = False

    return {
        "optimal_threshold":  optimal_threshold,
        "viable":             viable,
        "f1_at_optimal":      f1_at_optimal,
        "fpr_at_optimal":     fpr_at_optimal,
        "f1_at_production":   round(prod_f1, 4),
        "fpr_at_production":  round(prod_fpr, 4),
        "production_threshold": production_threshold,
        "sweep":              sweep,
    }


# ---------------------------------------------------------------------------
# Step 9: Per-cell summary aggregation
# ---------------------------------------------------------------------------

def _compute_cell_summary(query_results: list[dict]) -> dict:
    """Aggregate per-query results into per-cell summary metrics."""
    valid = [r for r in query_results if r.get("error") is None]
    if not valid:
        return {}

    positive = [r for r in valid if not r.get("is_negative")]
    negative = [r for r in valid if r.get("is_negative")]

    # Pure MRR — rank-based, threshold-invariant (uses pure_reciprocal_rank)
    pure_rr_values = [r["pure_reciprocal_rank"] for r in positive
                      if r.get("pure_reciprocal_rank") is not None]
    mrr_overall = round(sum(pure_rr_values) / len(pure_rr_values), 4) if pure_rr_values else None

    mrr_by_stratum: dict[str, float] = {}
    for stratum in ("easy", "medium", "pathogen"):
        s_rr = [r["pure_reciprocal_rank"] for r in positive
                if r.get("tier") == stratum and r.get("pure_reciprocal_rank") is not None]
        if s_rr:
            mrr_by_stratum[stratum] = round(sum(s_rr) / len(s_rr), 4)

    # Gate-filtered MRR — threshold-dependent (uses reciprocal_rank)
    gf_rr_values = [r["reciprocal_rank"] for r in positive if r.get("reciprocal_rank") is not None]
    mrr_gate_filtered = round(sum(gf_rr_values) / len(gf_rr_values), 4) if gf_rr_values else None

    mrr_gate_filtered_by_stratum: dict[str, float] = {}
    for stratum in ("easy", "medium", "pathogen"):
        s_rr = [r["reciprocal_rank"] for r in positive
                if r.get("tier") == stratum and r.get("reciprocal_rank") is not None]
        if s_rr:
            mrr_gate_filtered_by_stratum[stratum] = round(sum(s_rr) / len(s_rr), 4)

    # Top-1 accuracy and gate pass rate — positive only
    top1_acc   = round(sum(r["correct_at_1"] for r in positive) / len(positive), 4) if positive else None
    gate_rate  = round(sum(r["gate_passed"]  for r in positive) / len(positive), 4) if positive else None

    top1_by_stratum: dict[str, float] = {}
    for stratum in ("easy", "medium", "pathogen"):
        sq = [r for r in valid if r.get("tier") == stratum]
        if sq:
            top1_by_stratum[stratum] = round(sum(r["correct_at_1"] for r in sq) / len(sq), 4)

    # Hard-stratum negative controls: correct_at_1 means top1_score < threshold (inverted polarity)
    hard_neg_qs = [r for r in valid if r.get("tier") == "hard"]
    hard_ncpr = (
        round(sum(r["correct_at_1"] for r in hard_neg_qs) / len(hard_neg_qs), 4)
        if hard_neg_qs else None
    )

    # Mean expected score — positive queries with non-null expected_score
    pos_scores = [r["expected_score"] for r in positive if r["expected_score"] is not None]
    mean_score = round(sum(pos_scores) / len(pos_scores), 4) if pos_scores else None

    # Hard FPR with Type-1/Type-2 classification
    n_hard = len(negative)
    fp_all = [r for r in negative if not r["correct_at_1"]]
    fp_type2 = [r for r in fp_all if r.get("top1_food_name") in _CATEGORY_LEVEL_FOOD_NAMES]
    fp_type1 = [r for r in fp_all if r.get("top1_food_name") not in _CATEGORY_LEVEL_FOOD_NAMES]
    hard_fpr       = round(len(fp_all) / n_hard, 4)   if n_hard else 0.0
    hard_fpr_type1 = round(len(fp_type1) / n_hard, 4) if n_hard else 0.0
    hard_fpr_type2 = round(len(fp_type2) / n_hard, 4) if n_hard else 0.0

    # Threshold calibration (per production tier) — FPR-constrained objective
    threshold_calibration = {
        tier: _threshold_sweep(query_results, tier)
        for tier in ("tier_1", "tier_2", "pathogen_stage_1")
    }

    # Tri-state viability: "true" = all tiers defined-viable, "partial" = some undefined FPR
    # (corpus coverage gap, not a failure), "false" = any tier actively not viable.
    cal_viabilities = [threshold_calibration[t]["viable"] for t in ("tier_1", "tier_2", "pathogen_stage_1")]
    if any(v is False for v in cal_viabilities):
        viable_at_calibrated: str = "false"
    elif any(v is None for v in cal_viabilities):
        viable_at_calibrated = "partial"
    else:
        viable_at_calibrated = "true"

    latencies = [r.get("latency_ms", 0) for r in query_results]

    return {
        "mrr":                             mrr_overall,
        "mrr_by_stratum":                  mrr_by_stratum,
        "mrr_gate_filtered":               mrr_gate_filtered,
        "mrr_gate_filtered_by_stratum":    mrr_gate_filtered_by_stratum,
        "top1_accuracy":                   top1_acc,
        "top1_by_stratum":                 top1_by_stratum,
        "hard_negative_control_pass_rate": hard_ncpr,
        "gate_pass_rate":                  gate_rate,
        "mean_expected_score":             mean_score,
        "hard_fpr":                        hard_fpr,
        "hard_fpr_type1":                  hard_fpr_type1,
        "hard_fpr_type2":                  hard_fpr_type2,
        "n_positive_queries":              len(positive),
        "n_hard_queries":                  n_hard,
        "n_errored_queries":               len(query_results) - len(valid),
        "mean_query_latency_ms":           round(sum(latencies) / len(latencies), 1) if latencies else 0.0,
        "viable_at_calibrated_threshold":  viable_at_calibrated,
        "threshold_calibration":           threshold_calibration,
    }


# ---------------------------------------------------------------------------
# Step 10: Run all corpus queries against one cell
# ---------------------------------------------------------------------------

def run_cell_queries(collection, corpus: list[dict], top_k: int) -> list[dict]:
    results = []
    for entry in corpus:
        threshold = _get_threshold(entry["production_tier"])
        query_text = _format_query(entry)
        where_filter = _build_where_filter(entry["field"])

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

        results.append({
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
        })
    return results


# ---------------------------------------------------------------------------
# Step 11: Run the full 12-cell experiment
# ---------------------------------------------------------------------------

def run_experiment(
    embedders: list[dict],
    format_ids: list[str],
    corpus: list[dict],
    data_dir: Path,
    chroma_dir: Path,
    top_k: int = DEFAULT_TOP_K,
) -> list[dict]:
    """
    Outer loop: embedder → format, loading each embedder once and reusing
    the SentenceTransformerEmbeddingFunction across all format cells for that embedder.
    """
    all_cells = []

    for emb in embedders:
        eid = emb["id"]
        print(f"\n{'='*65}")
        print(f"  Embedder: {emb['name']}  ({emb['params_m']}M params, {emb['dim']}-dim)")
        print(f"{'='*65}")

        print(f"  Loading model...", end="", flush=True)
        ef, load_time = load_embedder(emb)
        print(f" {load_time:.1f}s")

        for format_id in format_ids:
            print(f"\n  Format: {format_id}")
            print(f"    Building corpus docs...", end="", flush=True)
            docs = build_corpus_docs(format_id, data_dir)
            print(f" {len(docs)} docs")

            print(f"    Ingesting into ChromaDB...", end="", flush=True)
            collection, embed_time = build_cell_collection(emb, format_id, docs, ef, chroma_dir)
            print(f" {embed_time:.1f}s")

            print(f"    Running {len(corpus)} queries...", end="", flush=True)
            query_results = run_cell_queries(collection, corpus, top_k)
            summary = _compute_cell_summary(query_results)
            print(
                f" MRR={summary.get('mrr') or 0:.3f}"
                f"  hard_fpr={summary.get('hard_fpr') or 0:.3f}"
                + ("  SAFE" if summary.get("hard_fpr", 1) == 0.0 else "")
            )

            mrr_s = summary.get("mrr_by_stratum", {})
            print(
                f"      easy={_fmt_pct(mrr_s.get('easy'))}  "
                f"medium={_fmt_pct(mrr_s.get('medium'))}  "
                f"pathogen={_fmt_pct(mrr_s.get('pathogen'))}"
            )

            all_cells.append({
                "cell_id":             f"{eid}_{format_id}",
                "embedder_id":         eid,
                "embedder_name":       emb["name"],
                "embedder_hf_model":   emb["hf_model"],
                "embedder_dim":        emb["dim"],
                "embedder_params_m":   emb["params_m"],
                "embedder_is_baseline": emb.get("is_baseline", False),
                "embedder_training_objective": emb.get("training_objective", "general"),
                "format_id":           format_id,
                "load_time_s":         load_time,
                "embed_time_s":        embed_time,
                "queries":             query_results,
                "summary":             summary,
            })

    return all_cells


# ---------------------------------------------------------------------------
# Step 12: Format helper
# ---------------------------------------------------------------------------

def _fmt_pct(x: float | None, width: int = 0) -> str:
    s = f"{x:.0%}" if x is not None else "n/a"
    return s.rjust(width) if width else s


# ---------------------------------------------------------------------------
# Step 13: Save results
# ---------------------------------------------------------------------------

def save_results(
    cells: list[dict],
    corpus: list[dict],
    run_timestamp: str,
) -> Path:
    out_dir = RESULTS_DIR / EXPERIMENT_ID
    out_dir.mkdir(parents=True, exist_ok=True)

    stratum_counts = {
        stratum: sum(1 for q in corpus if q["tier"] == stratum)
        for stratum in ("easy", "medium", "hard", "pathogen")
    }

    output = {
        "experiment_id": EXPERIMENT_ID,
        "description":   (
            "2-factor retrieval benchmark: 4 embedders x 3 doc text formats = 12 cells. "
            "Primary metric: MRR over positive queries. Hard FPR = 0.0 required for "
            "decision-rule eligibility. Pathogen stratum is a sanity check (lexical anchor "
            "'hazard' present in all formats). Hard-stratum FPs classified Type-1 "
            "(specific-row match) vs Type-2 (category-level match)."
        ),
        "timestamp":     run_timestamp,
        "corpus": {
            "version":        "2.0",
            "total_queries":  len(corpus),
            "stratum_counts": stratum_counts,
        },
        "doc_formats": DOC_FORMAT_IDS,
        "cells":         cells,
        "recommendation": compute_recommendation(cells),
    }

    json_path = out_dir / f"results_{run_timestamp}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)

    # Summary CSV — one row per cell
    rows = []
    for cell in cells:
        s  = cell["summary"]
        ta = s.get("top1_by_stratum", {})
        ms = s.get("mrr_by_stratum", {})
        tc = s.get("threshold_calibration", {})

        def _cal(tier: str, key: str):
            return tc.get(tier, {}).get(key, "")

        gfms = s.get("mrr_gate_filtered_by_stratum", {})
        rows.append({
            "cell_id":              cell["cell_id"],
            "embedder_id":          cell["embedder_id"],
            "embedder_name":        cell["embedder_name"],
            "format_id":            cell["format_id"],
            "embedder_dim":         cell["embedder_dim"],
            "embedder_params_m":    cell["embedder_params_m"],
            "is_baseline":          cell["embedder_is_baseline"],
            "training_objective":   cell["embedder_training_objective"],
            "mrr":                  s.get("mrr", ""),
            "mrr_easy":             ms.get("easy", ""),
            "mrr_medium":           ms.get("medium", ""),
            "mrr_pathogen":         ms.get("pathogen", ""),
            "mrr_gate_filtered":         s.get("mrr_gate_filtered", ""),
            "mrr_gate_filtered_easy":    gfms.get("easy", ""),
            "mrr_gate_filtered_medium":  gfms.get("medium", ""),
            "mrr_gate_filtered_pathogen": gfms.get("pathogen", ""),
            "hard_fpr":             s.get("hard_fpr", ""),
            "hard_fpr_type1":       s.get("hard_fpr_type1", ""),
            "hard_fpr_type2":       s.get("hard_fpr_type2", ""),
            "top1_accuracy":        s.get("top1_accuracy", ""),
            "top1_easy":            ta.get("easy", ""),
            "top1_medium":          ta.get("medium", ""),
            "hard_negative_control_pass_rate": s.get("hard_negative_control_pass_rate", ""),
            "top1_pathogen":        ta.get("pathogen", ""),
            "gate_pass_rate":       s.get("gate_pass_rate", ""),
            "mean_expected_score":  s.get("mean_expected_score", ""),
            "n_positive_queries":   s.get("n_positive_queries", ""),
            "n_hard_queries":       s.get("n_hard_queries", ""),
            "n_errored_queries":    s.get("n_errored_queries", 0),
            "mean_query_latency_ms": s.get("mean_query_latency_ms", ""),
            "load_time_s":          cell["load_time_s"],
            "embed_time_s":         cell["embed_time_s"],
            "cal_tier1_optimal":    _cal("tier_1", "optimal_threshold"),
            "cal_tier1_f1_optimal": _cal("tier_1", "f1_at_optimal"),
            "cal_tier1_f1_prod":    _cal("tier_1", "f1_at_production"),
            "viable_at_calibrated":    s.get("viable_at_calibrated_threshold", ""),
            "cal_tier1_viable":        _cal("tier_1", "viable"),
            "cal_tier1_optimal":       _cal("tier_1", "optimal_threshold"),
            "cal_tier1_f1_optimal":    _cal("tier_1", "f1_at_optimal"),
            "cal_tier1_fpr_optimal":   _cal("tier_1", "fpr_at_optimal"),
            "cal_tier1_f1_prod":       _cal("tier_1", "f1_at_production"),
            "cal_tier1_fpr_prod":      _cal("tier_1", "fpr_at_production"),
            "cal_tier2_viable":        _cal("tier_2", "viable"),
            "cal_tier2_optimal":       _cal("tier_2", "optimal_threshold"),
            "cal_tier2_f1_optimal":    _cal("tier_2", "f1_at_optimal"),
            "cal_tier2_fpr_optimal":   _cal("tier_2", "fpr_at_optimal"),
            "cal_tier2_f1_prod":       _cal("tier_2", "f1_at_production"),
            "cal_tier2_fpr_prod":      _cal("tier_2", "fpr_at_production"),
            "cal_pathogen_viable":     _cal("pathogen_stage_1", "viable"),
            "cal_pathogen_optimal":    _cal("pathogen_stage_1", "optimal_threshold"),
            "cal_pathogen_f1_optimal": _cal("pathogen_stage_1", "f1_at_optimal"),
            "cal_pathogen_fpr_optimal": _cal("pathogen_stage_1", "fpr_at_optimal"),
            "cal_pathogen_f1_prod":    _cal("pathogen_stage_1", "f1_at_production"),
            "cal_pathogen_fpr_prod":   _cal("pathogen_stage_1", "fpr_at_production"),
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
    print(f"    {json_path.name}  -- full data (one cell per embedder x format)")
    print(f"    {csv_path.name}   -- summary ({len(rows)} rows)")
    print(f"    latest.json / latest.csv -- copies of most recent run")

    return out_dir


# ---------------------------------------------------------------------------
# Step 14: Recommendation (single source of truth — imported by dashboard)
# ---------------------------------------------------------------------------

def compute_recommendation(cells: list[dict]) -> dict:
    """
    Return a structured recommendation dict for the 2-factor (embedder x format) design.

    Baseline cell: minilm-l6-v2 x current (the production configuration).

    Viability criteria (all three must hold):
      1. viable_at_calibrated_threshold in ("true", "partial") — "true" = all tiers have
         a defined FPR that meets the ceiling; "partial" = some tiers have undefined FPR
         because no negative-control queries route through them (corpus coverage gap, not
         a failure — calibration is still meaningful for tiers that have negatives).
      2. mrr_by_stratum["easy"] >= MRR_EASY_FLOOR (pure rank-based MRR, threshold-invariant;
         exact-species probes that must reliably rank near the top).
      3. n_errored_queries == 0 (no retrieval failures during the sweep).

    Tiebreak among viable cells within ΔMRR = 0.02: lower latency, smaller model,
    then format proximity to production ("current" > "verbose" > "terse").

    Action values:
      "baseline_only"   — only the baseline cell was evaluated
      "no_baseline"     — baseline cell not present in results
      "no_viable_cells" — no candidate meets all viability criteria; surfaces closest
                          cell and whether the failure is fundamental (no FPR-viable
                          operating point exists) or repairable (FPR ceiling met but
                          MRR below floor — may improve with corpus expansion or tuning)
      "keep_baseline"   — best viable candidate does not improve MRR over baseline
      "switch"          — a viable candidate improves MRR; switching is justified
    """
    _FORMAT_PROXIMITY = {"current": 0, "verbose": 1, "terse": 2}

    baseline = next(
        (c for c in cells if c["embedder_id"] == "minilm-l6-v2" and c["format_id"] == "current"),
        None,
    )
    candidates = [c for c in cells
                  if not (c["embedder_id"] == "minilm-l6-v2" and c["format_id"] == "current")]

    if baseline is None:
        return {"action": "no_baseline", "baseline": None, "best_cell": None, "delta_mrr": None}

    if not candidates:
        b = baseline.get("summary", {})
        return {
            "action":    "baseline_only",
            "baseline":  {"cell_id": baseline["cell_id"], "mrr": b.get("mrr")},
            "best_cell": None, "delta_mrr": None,
        }

    baseline_mrr = baseline.get("summary", {}).get("mrr") or 0.0

    def _is_viable(cell: dict) -> bool:
        s = cell.get("summary", {})
        return (
            s.get("viable_at_calibrated_threshold") in ("true", "partial")
            and (s.get("mrr_by_stratum", {}).get("easy") or 0.0) >= MRR_EASY_FLOOR
            and s.get("n_errored_queries", 1) == 0
        )

    viable_cells = [c for c in candidates if _is_viable(c)]

    if not viable_cells:
        # Surface the closest candidate and the failure mode.
        # "Fundamental" = no tier has ANY FPR-viable operating point.
        # "Repairable"  = all tiers have a viable point but MRR is below the floor.
        def _closest_key(c):
            s = c.get("summary", {})
            all_viable = s.get("viable_at_calibrated_threshold") in ("true", "partial")
            easy_mrr   = s.get("mrr_by_stratum", {}).get("easy") or 0.0
            return (all_viable, easy_mrr)

        closest = max(candidates, key=_closest_key)
        cs = closest.get("summary", {})
        cal_viable = cs.get("viable_at_calibrated_threshold") in ("true", "partial")
        easy_mrr   = cs.get("mrr_by_stratum", {}).get("easy") or 0.0

        if not cal_viable:
            failure_reason = "fpr_ceiling_unmet"
            is_fundamental = True
            note = (
                f"Closest candidate {closest['cell_id']} has no operating point where "
                f"FPR <= {FPR_CEILING:.0%} across all tiers. The embedder matches too "
                "broadly at the current calibrated thresholds. Switching would introduce "
                "false positives in production. This failure is fundamental — it cannot "
                "be resolved by corpus expansion or threshold tuning alone; a different "
                "embedder or higher threshold regime is required."
            )
        else:
            failure_reason = "mrr_below_floor"
            is_fundamental = False
            note = (
                f"Closest candidate {closest['cell_id']} meets the FPR ceiling but "
                f"mrr_easy={easy_mrr:.3f} < MRR_EASY_FLOOR={MRR_EASY_FLOOR}. The "
                "retrieval system misses exact-species probes at the calibrated threshold. "
                "This failure may be repairable: a richer corpus, more positive probes, "
                "or lower MRR floor (if the floor was set too aggressively) could unblock."
            )

        return {
            "action":    "no_viable_cells",
            "baseline":  {"cell_id": baseline["cell_id"], "mrr": baseline_mrr},
            "best_cell": None,
            "delta_mrr": None,
            "closest_cell": {
                "cell_id":        closest["cell_id"],
                "failure_reason": failure_reason,
                "is_fundamental": is_fundamental,
                "mrr":            cs.get("mrr"),
                "mrr_easy":       easy_mrr,
                "viable_at_calibrated_threshold": cal_viable,
            },
            "note": note,
        }

    # Rank viable candidates; tiebreak within ΔMRR = 0.02
    best = max(viable_cells, key=lambda c: c.get("summary", {}).get("mrr") or 0.0)
    best_mrr = best.get("summary", {}).get("mrr") or 0.0

    within_band = [
        c for c in viable_cells
        if (c.get("summary", {}).get("mrr") or 0.0) >= best_mrr - 0.02
    ]
    if len(within_band) > 1:
        best = min(
            within_band,
            key=lambda c: (
                c.get("summary", {}).get("mean_query_latency_ms") or 9999,
                c.get("embedder_params_m") or 9999,
                _FORMAT_PROXIMITY.get(c.get("format_id"), 9),
            ),
        )
        best_mrr = best.get("summary", {}).get("mrr") or 0.0

    delta = round(best_mrr - baseline_mrr, 4)

    return {
        "action":     "switch" if delta > 0 else "keep_baseline",
        "baseline":   {"cell_id": baseline["cell_id"], "mrr": baseline_mrr},
        "best_cell":  {"cell_id": best["cell_id"], "mrr": best_mrr},
        "delta_mrr":  delta,
    }


# ---------------------------------------------------------------------------
# Step 14b: Recalibrate from existing results (no ChromaDB queries)
# ---------------------------------------------------------------------------

def _backfill_pure_rr(record: dict) -> dict:
    """Add pure_reciprocal_rank when loading older per-query records that predate the field."""
    if "pure_reciprocal_rank" in record:
        return record
    is_negative = record.get("is_negative", False)
    if is_negative:
        return {**record, "pure_reciprocal_rank": None}
    exp_rank = record.get("expected_rank")
    pure_rr = round(1.0 / exp_rank, 6) if exp_rank else 0.0
    return {**record, "pure_reciprocal_rank": pure_rr}


def recalibrate_from_results(results_path: Path) -> list[dict]:
    """
    Reload per-query scores from a previous sweep and recompute threshold calibration
    with the FPR-constrained objective. No ChromaDB queries — operates entirely on
    stored top1_score, top1_food_name, expected_score, expected_rank values.

    Per-query threshold-dependent fields (correct_at_1, gate_passed, reciprocal_rank)
    are approximated at the new calibrated thresholds; see _recompute_query_at_threshold
    for the approximation assumptions.
    """
    with open(results_path, encoding="utf-8") as f:
        data = json.load(f)

    prior_ts = data.get("timestamp", "unknown")
    print(f"\n  Recalibrating results from: {prior_ts}")
    print(f"  Source: {results_path.name}  ({len(data['cells'])} cells)")
    print(f"  New calibration objective: FPR <= {FPR_CEILING:.0%} ceiling\n")

    recalibrated = []
    for cell in data["cells"]:
        # Backfill pure_reciprocal_rank for records that predate the field
        queries = [_backfill_pure_rr(r) for r in cell["queries"]]
        eid     = cell["embedder_id"]
        fmt     = cell["format_id"]

        # Step 1: recompute calibration with the new objective
        new_cal = {
            tier: _threshold_sweep(queries, tier)
            for tier in ("tier_1", "tier_2", "pathogen_stage_1")
        }

        # Step 2: determine effective threshold per tier
        # Defined-viable tier → use calibrated optimal; undefined or not-viable → production
        tier_thresholds: dict[str, float] = {}
        for tier, cal in new_cal.items():
            if cal["viable"] is True and cal["optimal_threshold"] is not None:
                tier_thresholds[tier] = cal["optimal_threshold"]
            else:
                tier_thresholds[tier] = _get_threshold(tier)

        # Step 3: recompute per-query fields at calibrated thresholds
        recomputed_queries = [
            _recompute_query_at_threshold(
                r, tier_thresholds.get(r.get("production_tier"), r.get("threshold_used", 0.70))
            )
            for r in queries
        ]

        # Step 4: recompute cell summary (internally re-derives calibration; same
        # result because top1_score is unchanged)
        new_summary = _compute_cell_summary(recomputed_queries)
        vat = new_summary.get("viable_at_calibrated_threshold", "false")
        viable_str = {"true": "VIABLE", "partial": "PARTIAL", "false": "not-viable"}.get(vat, "?")

        mrr_s = new_summary.get("mrr_by_stratum", {})
        print(
            f"  {eid} x {fmt:<8} "
            f"MRR={new_summary.get('mrr') or 0:.3f} "
            f"easy={mrr_s.get('easy') or 0:.3f} "
            f"hard_fpr={new_summary.get('hard_fpr') or 0:.3f} "
            f"{viable_str}"
        )

        recalibrated.append({
            **cell,
            "queries": recomputed_queries,
            "summary": new_summary,
        })

    return recalibrated


# ---------------------------------------------------------------------------
# Step 15: Print summary
# ---------------------------------------------------------------------------

def print_summary(cells: list[dict]):
    lines = []
    lines.append(f"\n{'='*80}")
    lines.append("  SUMMARY: EMBEDDER x DOC TEXT FORMAT (Experiment 2.2)")
    lines.append(f"{'='*80}\n")

    # 12-cell grid: MRR and calibration viability
    lines.append(
        f"  {'Cell':<38} {'MRR':>6} {'MRR-easy':>9} {'HardFPR':>8} "
        f"{'Top1':>6} {'Viable?':>8}"
    )
    lines.append("  " + "-" * 80)
    for cell in cells:
        s  = cell["summary"]
        ms = s.get("mrr_by_stratum", {})
        is_baseline = cell["embedder_id"] == "minilm-l6-v2" and cell["format_id"] == "current"
        marker  = "* " if is_baseline else "  "
        vat = s.get("viable_at_calibrated_threshold")
        viable = {"true": "YES", "partial": "PART", "false": "no"}.get(vat, "no")
        lines.append(
            f"  {marker}{cell['cell_id']:<36} "
            f"{_fmt_pct(s.get('mrr'), 5)} "
            f"{_fmt_pct(ms.get('easy'), 8)} "
            f"{s.get('hard_fpr', '?'):>8.4f} "
            f"{_fmt_pct(s.get('top1_accuracy'), 5)} "
            f"{viable:>8}"
        )
    lines.append(
        f"  * = baseline (production: minilm-l6-v2 x current)  "
        f"Viable = FPR<={FPR_CEILING:.0%} at all tiers AND mrr_easy>={MRR_EASY_FLOOR}"
    )

    # Format-within-embedder MRR comparison (answers question 2)
    lines.append(f"\n  FORMAT SENSITIVITY — MRR by format within each embedder")
    lines.append(f"  (measures whether format matters more or less than embedder choice)")
    lines.append(f"  {'Embedder':<34} {'terse':>7} {'current':>8} {'verbose':>8} {'delta':>7}")
    lines.append("  " + "-" * 68)

    embedder_ids = list(dict.fromkeys(c["embedder_id"] for c in cells))
    for eid in embedder_ids:
        emb_cells = {c["format_id"]: c for c in cells if c["embedder_id"] == eid}
        mrr_vals = {fid: (emb_cells[fid]["summary"].get("mrr") or 0.0) for fid in DOC_FORMAT_IDS if fid in emb_cells}
        delta = round(max(mrr_vals.values()) - min(mrr_vals.values()), 3) if len(mrr_vals) > 1 else 0.0
        name = next(c["embedder_name"] for c in cells if c["embedder_id"] == eid)
        lines.append(
            f"  {name:<34} "
            f"{_fmt_pct(mrr_vals.get('terse'), 6)} "
            f"{_fmt_pct(mrr_vals.get('current'), 7)} "
            f"{_fmt_pct(mrr_vals.get('verbose'), 7)} "
            f"{delta:>7.3f}"
        )

    # Hard FPR summary (answers question 1)
    lines.append(f"\n  HARD FPR SUMMARY (v2 corpus, 12 negative-control queries)")
    lines.append(f"  {'Cell':<38} {'FPR':>6} {'Type1':>7} {'Type2':>7}")
    lines.append("  " + "-" * 60)
    for cell in cells:
        s = cell["summary"]
        lines.append(
            f"  {cell['cell_id']:<38} "
            f"{s.get('hard_fpr', '?'):>6.4f} "
            f"{s.get('hard_fpr_type1', '?'):>7.4f} "
            f"{s.get('hard_fpr_type2', '?'):>7.4f}"
        )
    lines.append(f"  Type-1: specific-row FP (unambiguously wrong)")
    lines.append(f"  Type-2: category-row FP (design-rejected but contestable — see H12 note)")

    # Recommendation
    lines.append(f"\n  {'='*65}")
    rec = compute_recommendation(cells)
    action = rec["action"]
    if action == "baseline_only":
        lines.append("  Recommendation: Only the baseline cell was evaluated.")
    elif action == "no_baseline":
        lines.append("  Recommendation: Baseline cell (minilm-l6-v2 x current) not found.")
    elif action == "no_viable_cells":
        cc = rec.get("closest_cell", {})
        fundamental = cc.get("is_fundamental", True)
        severity = "fundamental" if fundamental else "repairable"
        lines.append(
            f"  Recommendation: Do not switch ({severity} failure).\n"
            f"  No candidate meets FPR<={FPR_CEILING:.0%} + mrr_easy>={MRR_EASY_FLOOR}.\n"
            f"  Closest: {cc.get('cell_id')}  "
            f"mrr_easy={cc.get('mrr_easy') or 0:.3f}  "
            f"viable_fpr={'YES' if cc.get('viable_at_calibrated_threshold') else 'no'}\n"
            f"  Failure: {cc.get('failure_reason')}"
        )
    elif action == "keep_baseline":
        lines.append(
            f"  Recommendation: Keep baseline. Best viable cell {rec['best_cell']['cell_id']} "
            f"does not improve MRR (delta = {rec['delta_mrr']:+.3f})."
        )
    else:  # switch
        lines.append(f"  Recommendation: Switch to {rec['best_cell']['cell_id']}")
        lines.append(f"  Delta MRR vs baseline: {rec['delta_mrr']:+.3f}")
        lines.append(f"  Cost: re-embed corpus with new format + rebuild ChromaDB store")
    lines.append(f"  {'='*65}")

    print("\n".join(lines), flush=True)


# ---------------------------------------------------------------------------
# Step 16: MLflow tracking (optional)
# ---------------------------------------------------------------------------

def log_to_mlflow(cells: list[dict], out_dir: Path, run_timestamp: str):
    try:
        import mlflow
    except ImportError:
        print("\n  MLflow not installed -- skipping.")
        return

    db_path = PROJECT_ROOT / "mlruns.db"
    mlflow.set_tracking_uri(f"sqlite:///{db_path}")
    mlflow.set_experiment(EXPERIMENT_ID)

    with mlflow.start_run(run_name=f"run_{run_timestamp}"):
        mlflow.log_param("n_cells",       len(cells))
        mlflow.log_param("n_embedders",   len(set(c["embedder_id"] for c in cells)))
        mlflow.log_param("doc_formats",   ",".join(DOC_FORMAT_IDS))
        mlflow.log_param("n_queries",     len(cells[0]["queries"]) if cells else 0)
        mlflow.log_param("timestamp",     run_timestamp)

        for cell in cells:
            prefix = cell["cell_id"].replace("-", "_").replace(".", "_")
            s = cell["summary"]
            ms = s.get("mrr_by_stratum", {})
            if s.get("mrr") is not None:
                mlflow.log_metric(f"{prefix}/mrr",         s["mrr"])
            for stratum, mrr_val in ms.items():
                mlflow.log_metric(f"{prefix}/mrr_{stratum}", mrr_val)
            mlflow.log_metric(f"{prefix}/hard_fpr",       s.get("hard_fpr", 0))
            mlflow.log_metric(f"{prefix}/hard_fpr_type1", s.get("hard_fpr_type1", 0))
            mlflow.log_metric(f"{prefix}/hard_fpr_type2", s.get("hard_fpr_type2", 0))
            if s.get("top1_accuracy") is not None:
                mlflow.log_metric(f"{prefix}/top1_accuracy", s["top1_accuracy"])
            mlflow.log_metric(f"{prefix}/embed_time_s",   cell["embed_time_s"])

        mlflow.log_artifact(str(out_dir / f"results_{run_timestamp}.json"))
        mlflow.log_artifact(str(out_dir / f"summary_{run_timestamp}.csv"))

    print(f"\n  MLflow: run logged. View with:")
    print(f"    mlflow ui --backend-store-uri sqlite:///{db_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global FPR_CEILING  # may be overridden by --fpr-ceiling; declared here so all uses below see it
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")

    parser = argparse.ArgumentParser(description="Exp 2.2: Embedder x Doc Text Format")
    parser.add_argument(
        "--embedders", type=str, default=None,
        help="Comma-separated embedder IDs (default: all). "
             "IDs: minilm-l6-v2, bge-small-en-v1.5, bge-base-en-v1.5, mpnet-base-v2"
    )
    parser.add_argument(
        "--formats", type=str, default=None,
        help=f"Comma-separated format IDs (default: all). IDs: {', '.join(DOC_FORMAT_IDS)}"
    )
    parser.add_argument(
        "--queries-subset", type=str, default=None, metavar="TIER",
        help="Only run queries of this tier (easy/medium/hard/pathogen)"
    )
    parser.add_argument(
        "--top-k", type=int, default=DEFAULT_TOP_K,
        help=f"Results retrieved per query (default: {DEFAULT_TOP_K})"
    )
    parser.add_argument(
        "--no-mlflow", action="store_true", help="Disable MLflow tracking"
    )
    parser.add_argument(
        "--recalibrate", action="store_true",
        help=(
            "Recompute FPR-constrained threshold calibration from the existing "
            "latest.json without re-running ChromaDB queries. Updates latest.json "
            "and latest.csv in place."
        ),
    )
    parser.add_argument(
        "--fpr-ceiling", type=float, default=None,
        help=f"Override FPR_CEILING for this run (default: {FPR_CEILING}). "
             "Does NOT change the module constant; only affects this invocation.",
    )
    args = parser.parse_args()

    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if args.fpr_ceiling is not None:
        FPR_CEILING = args.fpr_ceiling
        print(f"  [override] FPR_CEILING = {FPR_CEILING}")

    # -----------------------------------------------------------------------
    # --recalibrate path: operate on existing per-query data, no ChromaDB
    # -----------------------------------------------------------------------
    if args.recalibrate:
        results_path = RESULTS_DIR / EXPERIMENT_ID / "latest.json"
        if not results_path.exists():
            print(f"  X No existing results at {results_path}. Run without --recalibrate first.")
            sys.exit(1)

        print(f"\n{'#'*72}")
        print(f"  EXPERIMENT 2.2: FPR-CONSTRAINED RECALIBRATION")
        print(f"  Objective: FPR <= {FPR_CEILING:.0%} ceiling (replaces F1-only maximisation)")
        print(f"  Run: {run_timestamp}")
        print(f"{'#'*72}")

        corpus = load_corpus()
        cells  = recalibrate_from_results(results_path)
        out_dir = save_results(cells, corpus, run_timestamp)
        print_summary(cells)

        if not args.no_mlflow:
            log_to_mlflow(cells, out_dir, run_timestamp)
        return

    # -----------------------------------------------------------------------
    # Full sweep path
    # -----------------------------------------------------------------------
    print(f"\n{'#'*72}")
    print(f"  EXPERIMENT 2.2: EMBEDDER x DOC TEXT FORMAT")
    print(f"  Retrieval quality across {len(EMBEDDERS)} embedders x {len(DOC_FORMAT_IDS)} formats = "
          f"{len(EMBEDDERS) * len(DOC_FORMAT_IDS)} cells")
    print(f"  Run: {run_timestamp}")
    print(f"{'#'*72}")

    # Select embedders
    embedders = EMBEDDERS
    if args.embedders:
        ids = {s.strip() for s in args.embedders.split(",")}
        embedders = [e for e in EMBEDDERS if e["id"] in ids]
        not_found = ids - {e["id"] for e in embedders}
        if not_found:
            print(f"  !! Unknown embedder IDs: {not_found}")
        if not embedders:
            print("  X No embedders selected. Exiting.")
            sys.exit(1)

    # Select formats
    format_ids = DOC_FORMAT_IDS
    if args.formats:
        format_ids = [f.strip() for f in args.formats.split(",") if f.strip() in DOC_FORMAT_IDS]
        invalid = {f.strip() for f in args.formats.split(",")} - set(DOC_FORMAT_IDS)
        if invalid:
            print(f"  !! Unknown format IDs: {invalid}")
        if not format_ids:
            print("  X No valid formats selected. Exiting.")
            sys.exit(1)

    # Load corpus
    corpus = load_corpus()
    if args.queries_subset:
        corpus = [q for q in corpus if q["tier"] == args.queries_subset]
        if not corpus:
            print(f"  X No queries for tier '{args.queries_subset}'.")
            sys.exit(1)

    data_dir = PROJECT_ROOT / "data" / "rag"
    chroma_dir = RESULTS_DIR / EXPERIMENT_ID / "_chroma"
    chroma_dir.mkdir(parents=True, exist_ok=True)

    n_cells = len(embedders) * len(format_ids)
    print(f"\n  Embedders:   {[e['id'] for e in embedders]}")
    print(f"  Formats:     {format_ids}")
    print(f"  Cells:       {n_cells}")
    print(f"  Corpus:      {len(corpus)} queries")
    if args.queries_subset:
        print(f"  Subset:      tier={args.queries_subset}")
    print(f"  Top-K:       {args.top_k}")
    print(f"  Chroma dir:  {chroma_dir}")
    print(f"\n  WARNING: Production store at data/vector_store/ is NOT touched.")

    cells = run_experiment(embedders, format_ids, corpus, data_dir, chroma_dir, args.top_k)

    out_dir = save_results(cells, corpus, run_timestamp)
    print_summary(cells)

    if not args.no_mlflow:
        log_to_mlflow(cells, out_dir, run_timestamp)


if __name__ == "__main__":
    main()
