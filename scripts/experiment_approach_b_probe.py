"""
Approach-B enrichment experiment probe.

Directly queries the RetrievalService with the same query strings the
GroundingService uses (Tier 1 + Tier 2) and reports raw embedding similarity
scores for each test food description.

Run: python scripts/experiment_approach_b_probe.py

The Tier 1/2 thresholds for reference:
  Tier 1 (food_properties_confidence):          0.70
  Tier 2 (food_properties_fallback_confidence): 0.62
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from app.rag.vector_store import get_vector_store, reset_vector_store
from app.rag.retrieval import get_retrieval_service, reset_retrieval_service
from app.config import settings

TIER1_THRESHOLD = settings.food_properties_confidence          # 0.70
TIER2_THRESHOLD = settings.food_properties_fallback_confidence # 0.62

# Test cases: (label, food_description_as_extracted_by_SemanticParser)
# food_description values match what SemanticParser would return for each query.
TEST_CASES = [
    ("C1 turkey",       "turkey portions"),
    ("B1 chicken",      "fresh chicken portions"),
    ("B2 chicken soup", "chicken soup"),
    ("Duck",            "duck"),
    ("Lamb",            "lamb"),
    ("Pheasant",        "pheasant breast"),
]

TIER1_LABEL = f">={TIER1_THRESHOLD:.2f} -> Tier 1 (rag_retrieval)"
TIER2_LABEL = f">={TIER2_THRESHOLD:.2f} -> Tier 2 (rag_retrieval_fallback)"
FAIL_LABEL  = f"<{TIER2_THRESHOLD:.2f}  -> default"


def score_label(score: float | None) -> str:
    if score is None:
        return "NO_RESULT"
    if score >= TIER1_THRESHOLD:
        return f"TIER1 ({score:.4f})"
    if score >= TIER2_THRESHOLD:
        return f"TIER2 ({score:.4f})"
    return f"FAIL  ({score:.4f})"


def top_score_and_doc(response) -> tuple[float | None, str | None, str | None]:
    """Return (similarity_score, doc_id, food_name) for the highest-scoring result."""
    if not response.results:
        return None, None, None
    top = response.results[0]
    food_name = top.metadata.get("food_name", "") if top.metadata else ""
    return top.confidence, top.doc_id, food_name


def main() -> None:
    reset_vector_store()
    store = get_vector_store()
    store.initialize()

    reset_retrieval_service()
    retrieval = get_retrieval_service()

    print(f"Thresholds: Tier 1 >= {TIER1_THRESHOLD}, Tier 2 >= {TIER2_THRESHOLD}")
    print(f"{'Case':<20} {'Query type':<10} {'Score label':<22} {'Top doc'}")
    print("-" * 90)

    for label, food_desc in TEST_CASES:
        # --- Tier 1: combined pH + aw query ---
        t1_resp = retrieval.query(
            query_text=f"{food_desc} pH water activity properties",
            doc_type="food_properties",
            n_results=3,
            threshold=0.0,  # no gate — report raw score
        )
        t1_sim, t1_doc, t1_food = top_score_and_doc(t1_resp)

        # --- Tier 2 pH ---
        t2_ph_resp = retrieval.query(
            query_text=f"{food_desc} pH acidity",
            doc_type="food_properties",
            n_results=3,
            threshold=0.0,
        )
        t2_ph_sim, t2_ph_doc, t2_ph_food = top_score_and_doc(t2_ph_resp)

        # --- Tier 2 aw ---
        t2_aw_resp = retrieval.query(
            query_text=f"{food_desc} water activity aw moisture",
            doc_type="food_properties",
            n_results=3,
            threshold=0.0,
        )
        t2_aw_sim, t2_aw_doc, t2_aw_food = top_score_and_doc(t2_aw_resp)

        print(f"{label:<20} {'Tier1':<10} {score_label(t1_sim):<22} {t1_doc} ({t1_food})")
        print(f"{'':20} {'Tier2-pH':<10} {score_label(t2_ph_sim):<22} {t2_ph_doc} ({t2_ph_food})")
        print(f"{'':20} {'Tier2-aw':<10} {score_label(t2_aw_sim):<22} {t2_aw_doc} ({t2_aw_food})")
        print()

    print("Legend:")
    print(f"  {TIER1_LABEL}")
    print(f"  {TIER2_LABEL}")
    print(f"  {FAIL_LABEL}")


if __name__ == "__main__":
    main()
