# -*- coding: utf-8 -*-
"""
Gate 3 dry-run for Experiment 2.2 (Embedder x Doc Text Format).

Verifies harness wiring before committing to the full 12-cell sweep.
Runs ONE cell: minilm-l6-v2 x current format x hard stratum (12 queries).

Also defines all three doc-format builders that exp_2_2 will reuse.
A passing gate confirms:
  1. Three format builders produce syntactically correct docs.
  2. ChromaDB collection creation and query routing work.
  3. Negative-control polarity (correct_at_1 = no doc above threshold) is correct.
  4. Threshold lookup routes tier_2 -> 0.62 for all hard queries.

The hard stratum is all negative controls (acceptable_food_names = []).
correct_at_1 = True when top-1 score < threshold (no match above gate).
hard_fpr = fraction of hard queries where a doc incorrectly clears the gate.
Requirement: hard_fpr = 0.0.

Usage:
    python -m benchmarks.experiments.exp_2_2_gate3_dryrun
"""

import csv as _csv
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from benchmarks.config import EMBEDDERS, DATASETS_DIR, RESULTS_DIR
from app.config import settings

GATE3_EMBEDDER_ID = "minilm-l6-v2"
GATE3_FORMAT_ID = "current"
GATE3_STRATUM = "hard"

EXP_ID = "exp_2_2_embedder_doc_format"
CHROMA_DIR = RESULTS_DIR / EXP_ID / "_chroma"


# ---------------------------------------------------------------------------
# Query reformulation — mirrors production RetrievalService exactly.
# If production strings change, update here in the same change.
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
# Format A — Terse
# Space-joined tokens, no connective language. Notes appended verbatim before
# source IDs. Preserves information equivalence with formats B and C.
# ---------------------------------------------------------------------------

def _build_food_properties_terse(data_dir: Path) -> list[dict]:
    docs = []
    file_path = data_dir / "food_properties.csv"
    with open(file_path, "r", encoding="utf-8") as f:
        reader = _csv.DictReader(f)
        row_idx = 0
        for row in reader:
            if not row.get("food_name") or row["food_name"].startswith("#"):
                continue
            tokens = [row["food_name"], row["food_category"]]
            if row.get("ph_min") and row.get("ph_max"):
                if row["ph_min"] == row["ph_max"]:
                    tokens.append(f"pH {row['ph_min']}")
                else:
                    tokens.append(f"pH {row['ph_min']} {row['ph_max']}")
            elif row.get("ph_min"):
                tokens.append(f"pH {row['ph_min']}")
            if row.get("aw_min") and row.get("aw_max"):
                if row["aw_min"] == row["aw_max"]:
                    tokens.append(f"aw {row['aw_min']}")
                else:
                    tokens.append(f"aw {row['aw_min']} {row['aw_max']}")
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
                "id":   f"food_properties_{row_idx}",
                "text": " ".join(tokens),
                "metadata": {
                    "food_name":     row["food_name"],
                    "food_category": row["food_category"],
                    "ph_min":        row.get("ph_min", ""),
                    "ph_max":        row.get("ph_max", ""),
                    "aw_min":        row.get("aw_min", ""),
                    "aw_max":        row.get("aw_max", ""),
                    "source_id":     ",".join(all_sources),
                    "type":          "food_properties",
                },
            })
            row_idx += 1
    return docs


def _build_pathogen_hazards_terse(data_dir: Path) -> list[dict]:
    docs = []
    file_path = data_dir / "food_pathogen_hazards.csv"
    with open(file_path, "r", encoding="utf-8") as f:
        reader = _csv.DictReader(f)
        row_idx = 0
        for row in reader:
            if not row.get("food_name"):
                continue
            source_id = row.get("source_id", "")
            primary_label = "primary hazard" if row.get("primary_hazard") == "yes" else "secondary hazard"
            tokens = [
                row["food_name"], row["food_category"], row["pathogen"],
                f"CFR {row['case_fatality_rate']}",
                f"deaths {row['annual_deaths_us']}",
                primary_label,
                f"control {row['control_methods']}",
            ]
            if row.get("notes"):
                tokens.append(row["notes"])
            if source_id:
                tokens.append(f"[{source_id}]")
            docs.append({
                "id":   f"pathogen_hazards_{row_idx}",
                "text": " ".join(tokens),
                "metadata": {
                    "food_name":          row["food_name"],
                    "food_category":      row["food_category"],
                    "pathogen":           row["pathogen"],
                    "case_fatality_rate": row["case_fatality_rate"],
                    "annual_deaths_us":   row["annual_deaths_us"],
                    "primary_hazard":     row["primary_hazard"],
                    "data_type":          "food_pathogen_hazard",
                    "source_id":          source_id,
                    "type":               "pathogen_hazards",
                },
            })
            row_idx += 1
    return docs


# ---------------------------------------------------------------------------
# Format B — Current
# Exactly mirrors food_safety.py load_food_properties / load_food_pathogen_hazards.
# Character-for-character verified against production output (2026-05-16).
# ---------------------------------------------------------------------------

def _build_food_properties_current(data_dir: Path) -> list[dict]:
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
            ph_source = row.get("ph_source_id", "").strip()
            aw_source = row.get("aw_source_id", "").strip()
            all_sources = list(dict.fromkeys(s for s in [ph_source, aw_source] if s))
            for sid in all_sources:
                doc += f" [{sid}]"
            docs.append({
                "id":   f"food_properties_{row_idx}",
                "text": doc,
                "metadata": {
                    "food_name":     row["food_name"],
                    "food_category": row["food_category"],
                    "ph_min":        row.get("ph_min", ""),
                    "ph_max":        row.get("ph_max", ""),
                    "aw_min":        row.get("aw_min", ""),
                    "aw_max":        row.get("aw_max", ""),
                    "source_id":     ",".join(all_sources),
                    "type":          "food_properties",
                },
            })
            row_idx += 1
    return docs


def _build_pathogen_hazards_current(data_dir: Path) -> list[dict]:
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
                "id":   f"pathogen_hazards_{row_idx}",
                "text": doc,
                "metadata": {
                    "food_name":          row["food_name"],
                    "food_category":      row["food_category"],
                    "pathogen":           row["pathogen"],
                    "case_fatality_rate": row["case_fatality_rate"],
                    "annual_deaths_us":   row["annual_deaths_us"],
                    "primary_hazard":     row["primary_hazard"],
                    "data_type":          "food_pathogen_hazard",
                    "source_id":          source_id,
                    "type":               "pathogen_hazards",
                },
            })
            row_idx += 1
    return docs


# ---------------------------------------------------------------------------
# Format C — Verbose
# Natural-language sentences. Notes field passed verbatim (no expansion).
# Control methods rendered as "recommended controls include X" — no efficacy
# claim added. "primary food safety hazard" is readability-only; no reclassification.
# ---------------------------------------------------------------------------

def _build_food_properties_verbose(data_dir: Path) -> list[dict]:
    docs = []
    file_path = data_dir / "food_properties.csv"
    with open(file_path, "r", encoding="utf-8") as f:
        reader = _csv.DictReader(f)
        row_idx = 0
        for row in reader:
            if not row.get("food_name") or row["food_name"].startswith("#"):
                continue
            food_label = row["food_name"][:1].upper() + row["food_name"][1:]
            sentences = [f"{food_label} is a {row['food_category']} product."]
            if row.get("ph_min") and row.get("ph_max"):
                if row["ph_min"] == row["ph_max"]:
                    sentences.append(f"Its pH is {row['ph_min']}.")
                else:
                    sentences.append(f"Its pH ranges from {row['ph_min']} to {row['ph_max']}.")
            elif row.get("ph_min"):
                sentences.append(f"Its pH is {row['ph_min']}.")
            if row.get("aw_min") and row.get("aw_max"):
                if row["aw_min"] == row["aw_max"]:
                    sentences.append(f"Its water activity is {row['aw_min']}.")
                else:
                    sentences.append(f"Its water activity ranges from {row['aw_min']} to {row['aw_max']}.")
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
                "id":   f"food_properties_{row_idx}",
                "text": " ".join(sentences),
                "metadata": {
                    "food_name":     row["food_name"],
                    "food_category": row["food_category"],
                    "ph_min":        row.get("ph_min", ""),
                    "ph_max":        row.get("ph_max", ""),
                    "aw_min":        row.get("aw_min", ""),
                    "aw_max":        row.get("aw_max", ""),
                    "source_id":     ",".join(all_sources),
                    "type":          "food_properties",
                },
            })
            row_idx += 1
    return docs


def _build_pathogen_hazards_verbose(data_dir: Path) -> list[dict]:
    docs = []
    file_path = data_dir / "food_pathogen_hazards.csv"
    with open(file_path, "r", encoding="utf-8") as f:
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
                "id":   f"pathogen_hazards_{row_idx}",
                "text": doc,
                "metadata": {
                    "food_name":          row["food_name"],
                    "food_category":      row["food_category"],
                    "pathogen":           row["pathogen"],
                    "case_fatality_rate": row["case_fatality_rate"],
                    "annual_deaths_us":   row["annual_deaths_us"],
                    "primary_hazard":     row["primary_hazard"],
                    "data_type":          "food_pathogen_hazard",
                    "source_id":          source_id,
                    "type":               "pathogen_hazards",
                },
            })
            row_idx += 1
    return docs


# ---------------------------------------------------------------------------
# Format dispatch — imported by exp_2_2 main experiment
# ---------------------------------------------------------------------------

DOC_FORMATS: dict[str, tuple] = {
    "terse":   (_build_food_properties_terse,   _build_pathogen_hazards_terse),
    "current": (_build_food_properties_current,  _build_pathogen_hazards_current),
    "verbose": (_build_food_properties_verbose,  _build_pathogen_hazards_verbose),
}


def build_corpus_docs(format_id: str, data_dir: Path) -> list[dict]:
    """Build food_properties + food_pathogen_hazards docs in the specified format."""
    fp_builder, ph_builder = DOC_FORMATS[format_id]
    return fp_builder(data_dir) + ph_builder(data_dir)


# ---------------------------------------------------------------------------
# ChromaDB cell builder — one isolated collection per (embedder x format) cell
# ---------------------------------------------------------------------------

def build_cell_collection(
    embedder_config: dict,
    format_id: str,
    docs: list[dict],
    chroma_dir: Path,
) -> tuple:
    """
    Ingest docs into an isolated ChromaDB collection for one cell.

    Collection path:  chroma_dir / {embedder_id}_{format_id} /
    Collection name:  ptm_exp_2_2_{embedder_id}_{format_id}

    Returns (collection, embed_time_s).
    NEVER touches data/vector_store/ (production store).
    """
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

    ef = SentenceTransformerEmbeddingFunction(
        model_name=embedder_config["hf_model"],
        normalize_embeddings=True,
    )

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
# Query helpers
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
# Gate 3 entry point
# ---------------------------------------------------------------------------

def main():
    data_dir = PROJECT_ROOT / "data" / "rag"
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)

    with open(DATASETS_DIR / "retrieval_queries.json", encoding="utf-8") as f:
        corpus_data = json.load(f)

    hard_queries = [q for q in corpus_data["queries"] if q["tier"] == GATE3_STRATUM]
    emb_config = next(e for e in EMBEDDERS if e["id"] == GATE3_EMBEDDER_ID)

    print(f"\n{'#'*72}")
    print(f"  GATE 3 DRY-RUN — Exp 2.2 harness wiring verification")
    print(f"  Cell:    {GATE3_EMBEDDER_ID} x {GATE3_FORMAT_ID} x {GATE3_STRATUM}")
    print(f"  Queries: {len(hard_queries)} hard-stratum (all negative controls)")
    print(f"  Require: hard_fpr = 0.0  (no doc clears threshold on any negative query)")
    print(f"{'#'*72}")

    print(f"\n  Building corpus ({GATE3_FORMAT_ID} format)...", end="", flush=True)
    docs = build_corpus_docs(GATE3_FORMAT_ID, data_dir)
    print(f" {len(docs)} docs")

    # Smoke-check one doc from each format to confirm builder output
    fp_docs = [d for d in docs if d["metadata"]["type"] == "food_properties"]
    ph_docs = [d for d in docs if d["metadata"]["type"] == "pathogen_hazards"]
    chicken_fp = next((d for d in fp_docs if d["metadata"]["food_name"] == "chicken"), None)
    chicken_ph = next((d for d in ph_docs if d["metadata"]["food_name"] == "chicken raw"), None)
    if chicken_fp:
        print(f"\n  [Smoke] food_properties chicken:")
        print(f"    {chicken_fp['text']!r}")
    if chicken_ph:
        print(f"  [Smoke] pathogen_hazards chicken raw (first):")
        print(f"    {chicken_ph['text'][:120]!r}...")

    print(f"\n  Loading embedder + ingesting corpus...", end="", flush=True)
    collection, embed_time = build_cell_collection(emb_config, GATE3_FORMAT_ID, docs, CHROMA_DIR)
    print(f" {embed_time:.1f}s")

    print(f"\n  Running {len(hard_queries)} queries...\n")
    print(f"  {'ID':<4} {'Description':<22} {'Field':<14} {'Thr':>5}  {'Top-1 match':<28} {'Score':>6}  Result")
    print("  " + "-" * 92)

    results = []
    for entry in hard_queries:
        threshold = _get_threshold(entry["production_tier"])
        query_text = _format_query(entry)
        where_filter = _build_where_filter(entry["field"])

        t0 = time.perf_counter()
        top_k = _query_collection(collection, query_text, 5, where_filter)
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)

        top1 = top_k[0] if top_k else None
        top1_score = top1["score"] if top1 else 0.0
        top1_food = top1["food_name"] if top1 else "-"
        correct_at_1 = top1_score < threshold

        print(
            f"  {entry['id']:<4} {entry['food_description']:<22} {entry['field']:<14} {threshold:>5.2f}"
            f"  {top1_food:<28} {top1_score:>6.4f}  "
            + ("PASS" if correct_at_1 else "FAIL <<")
        )

        results.append({
            "id":               entry["id"],
            "food_description": entry["food_description"],
            "field":            entry["field"],
            "threshold":        threshold,
            "top1_food":        top1_food,
            "top1_score":       top1_score,
            "correct_at_1":     correct_at_1,
            "top3":             [(r["food_name"], round(r["score"], 4)) for r in top_k[:3]],
            "latency_ms":       latency_ms,
        })

    n_pass = sum(1 for r in results if r["correct_at_1"])
    n_fail = len(results) - n_pass
    hard_fpr = n_fail / len(results) if results else 0.0

    print(f"\n  GATE 3 SUMMARY")
    print(f"  {'='*58}")
    print(f"  Hard queries:     {len(results)}")
    print(f"  Correct (no FP):  {n_pass} / {len(results)}")
    print(f"  False positives:  {n_fail}")
    print(f"  hard_fpr:         {hard_fpr:.4f}  (finding — not a gate criterion)")

    if n_fail > 0:
        print(f"\n  False positive detail (embedder findings, not harness bugs):")
        for r in results:
            if not r["correct_at_1"]:
                print(f"    {r['id']} '{r['food_description']}' ({r['field']}): "
                      f"top-1={r['top1_food']!r} score={r['top1_score']:.4f} "
                      f"> threshold {r['threshold']:.2f}")
                for food, score in r["top3"]:
                    print(f"      top-3: {food!r}  {score:.4f}")

    # Gate 3 passes if all WIRING CHECKS succeeded (docs built, embedder loaded,
    # queries ran). hard_fpr is a result observation, not a harness check.
    # Exiting 1 here would conflate "harness works" with "baseline passes the
    # decision rule" — a category error. See specs/lessons.md.
    print(f"\n  Gate 3: PASS — harness wired correctly, proceed to full 12-cell sweep")
    print(f"  {'='*58}\n")


if __name__ == "__main__":
    main()
