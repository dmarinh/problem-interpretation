"""
Manual test script for the full translation pipeline.

Usage:
    python scripts/test_full_pipeline.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()


async def main():
    from app.core.logging import setup_logging, get_logger
    setup_logging()
    logger = get_logger(__name__)
    
    from app.core.orchestrator import get_orchestrator, reset_orchestrator
    from app.engines.combase.engine import get_combase_engine
    from app.rag.vector_store import get_vector_store
    from app.rag.ingestion import IngestionPipeline
    from app.models.enums import ModelType
    
    print("=" * 70)
    print("FULL PIPELINE TEST")
    print("=" * 70)
    print()
    
    # Initialize ComBase engine
    engine = get_combase_engine()
    csv_path = Path("data/combase_models.csv")
    if csv_path.exists():
        count = engine.load_models(csv_path)
        print(f"✓ Loaded {count} ComBase models")
    else:
        print(f"✗ ComBase models not found at {csv_path}")
        return
    
    # Initialize vector store
    store = get_vector_store()
    store.initialize()
    print(f"✓ Vector store initialized")
    
    # Ingest test documents if empty
    if store.get_count() == 0:
        print("  Ingesting test documents...")
        pipeline = IngestionPipeline(vector_store=store)
        
        # Food properties
        pipeline.ingest_text(
            "Raw chicken has pH between 5.9 and 6.2, water activity 0.99. "
            "Should be stored below 4°C. High risk for Salmonella contamination.",
            doc_type="food_properties",
            metadata={"food": "chicken"},
        )
        pipeline.ingest_text(
            "Cooked rice has pH 6.0-6.6 and water activity 0.96-0.98. "
            "Risk of Bacillus cereus if left at room temperature.",
            doc_type="food_properties",
            metadata={"food": "rice"},
        )
        pipeline.ingest_text(
            "Ground beef has pH 5.4-5.8 and water activity 0.98. "
            "High risk for E. coli O157:H7 contamination.",
            doc_type="food_properties",
            metadata={"food": "beef"},
        )
        
        # Pathogen hazards
        pipeline.ingest_text(
            "Salmonella is commonly found in raw poultry, eggs, and unpasteurized milk. "
            "Growth temperature range 5-47°C with optimal growth at 37°C. "
            "Can cause severe foodborne illness.",
            doc_type="pathogen_hazards",
            metadata={"pathogen": "salmonella"},
        )
        pipeline.ingest_text(
            "Listeria monocytogenes can grow at refrigeration temperatures (0-4°C). "
            "Found in deli meats, soft cheeses, and ready-to-eat foods. "
            "Particularly dangerous for pregnant women.",
            doc_type="pathogen_hazards",
            metadata={"pathogen": "listeria"},
        )
        pipeline.ingest_text(
            "Bacillus cereus produces heat-stable toxins in cooked rice and pasta "
            "left at room temperature. Causes vomiting within 1-6 hours.",
            doc_type="pathogen_hazards",
            metadata={"pathogen": "bacillus"},
        )
        
        print(f"  ✓ Ingested {store.get_count()} documents")
    else:
        print(f"  Vector store has {store.get_count()} documents")
    
    print()
    
    # Reset orchestrator to pick up new components
    reset_orchestrator()
    orchestrator = get_orchestrator()
    
    # Test queries
    test_cases = [
        {
            "query": "I left raw chicken on the counter for 3 hours at room temperature",
            "model_type": ModelType.GROWTH,
        },
        {
            "query": "Cooked rice was sitting out overnight at about 25°C",
            "model_type": ModelType.GROWTH,
        },
        {
            "query": "Ground beef in my car for 2 hours on a warm day",
            "model_type": ModelType.GROWTH,
        },
        {
            "query": "Is deli turkey safe after being refrigerated for a week?",
            "model_type": ModelType.GROWTH,
        },
    ]
    
    for i, test in enumerate(test_cases, 1):
        print(f"TEST {i}: {test['query']}")
        print("-" * 70)
        
        try:
            result = await orchestrator.translate(
                user_input=test["query"],
                model_type=test["model_type"],
            )
            
            if result.success:
                print(f"✓ Status: SUCCESS")
                print(f"  Session ID: {result.state.session_id}")
                
                if result.execution_result:
                    er = result.execution_result
                    mr = er.model_result
                    print(f"  Organism: {mr.organism.name if mr.organism else 'Unknown'}")
                    print(f"  Temperature: {mr.temperature_used}°C")
                    print(f"  pH: {mr.ph_used}")
                    print(f"  Water Activity: {mr.aw_used}")
                    print(f"  Duration: {result.state.execution_payload.time_temperature_profile.total_duration_minutes} min")
                    print(f"  μ_max: {mr.mu_max:.4f} 1/h")
                    if mr.doubling_time_hours:
                        print(f"  Doubling Time: {mr.doubling_time_hours:.2f} h")
                    print(f"  Log Increase: {er.total_log_increase:.2f}")
                
                if result.metadata:
                    print(f"  Overall Confidence: {result.metadata.overall_confidence:.2f}")
                    if result.metadata.warnings:
                        print(f"  Warnings: {len(result.metadata.warnings)}")
                        for w in result.metadata.warnings[:3]:
                            print(f"    - {w[:80]}...")
            else:
                print(f"✗ Status: FAILED")
                print(f"  Error: {result.error}")
        
        except Exception as e:
            print(f"✗ Exception: {e}")
        
        print()
    
    print("=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())