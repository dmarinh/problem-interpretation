"""
Verification script for organism audit attribution fix.

Confirms that the pathogen retrieval's attributed_field="organism" is set,
so the audit lookup selects the pathogen retrieval (not the pH retrieval)
for the organism field.

Usage:
    python scripts/verify_organism_audit.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()


async def main():
    from app.rag.vector_store import get_vector_store
    from app.rag.retrieval import get_retrieval_service, reset_retrieval_service
    from app.models.extraction import (
        ExtractedScenario,
        ExtractedTemperature,
        ExtractedDuration,
        ExtractedEnvironmentalConditions,
        ExtractedFoodProperties,
    )
    from app.services.grounding.grounding_service import GroundingService

    # Boot vector store
    store = get_vector_store()
    store.initialize()

    reset_retrieval_service()
    retrieval = get_retrieval_service()

    service = GroundingService(
        retrieval_service=retrieval,
        use_llm_extraction=False,
    )

    def make_scenario(food: str) -> ExtractedScenario:
        return ExtractedScenario(
            food_description=food,
            food_properties=ExtractedFoodProperties(),
            environmental_conditions=ExtractedEnvironmentalConditions(),
            temperature=ExtractedTemperature(),
            duration=ExtractedDuration(),
        )

    print("=" * 65)
    print("ORGANISM AUDIT ATTRIBUTION FIX VERIFICATION")
    print("=" * 65)

    for label, food in [("RICE", "cooked rice"), ("CHICKEN", "raw chicken")]:
        print(f"\n--- {label}: '{food}' ---")
        scenario = make_scenario(food)
        grounded = await service.ground_scenario(scenario)

        retrievals = grounded.retrievals
        print(f"  grounded.retrievals count: {len(retrievals)}")
        for i, r in enumerate(retrievals):
            print(f"  [{i}] attributed_field={r.attributed_field!r}  query={r.query!r}")

        organism_prov = grounded.provenance.get("organism")
        if organism_prov:
            print(f"  organism.source: {organism_prov.source.value}")
            print(f"  organism.extraction_method: {organism_prov.extraction_method}")
        else:
            print("  organism: not grounded")

        # Simulate audit lookup
        is_rag = organism_prov and organism_prov.source.value in ("rag_retrieval", "rag_retrieval_fallback")
        if is_rag and retrievals:
            r = next((v for v in retrievals if v.attributed_field == "organism"), None)
            if r:
                print(f"  audit -> Priority 1 (attributed_field): query={r.query!r}")
            else:
                r = retrievals[0]
                if "pathogen" in "organism" or "organism" == "organism":
                    r = next((v for v in retrievals if "pathogen" in v.query.lower()), r)
                print(f"  audit -> Priority 2 (heuristic): query={r.query!r}")

            # Check: is the selected retrieval a pathogen doc?
            is_pathogen_doc = r.chunk_id and "pathogen" in r.chunk_id if r.chunk_id else False
            if r.retrieved_text:
                is_pathogen_doc = "hazard" in r.retrieved_text.lower() or "pathogen" in r.retrieved_text.lower()
            print(f"  selected doc id: {r.chunk_id}")
            print(f"  selected text preview: {(r.retrieved_text or '')[:80]}")

    print("\n" + "=" * 65)
    print("DONE")


asyncio.run(main())
