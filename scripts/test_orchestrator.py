"""
Manual test for orchestrator with real LLM and engine.

Usage:
    python scripts/test_orchestrator.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")


async def main():
    from app.core.orchestrator import Orchestrator
    from app.engines.combase.engine import ComBaseEngine
    from app.rag.vector_store import get_vector_store
    from app.rag.ingestion import IngestionPipeline
    
    # Initialize engine
    engine = ComBaseEngine()
    engine.load_models(Path("data/combase_models.csv"))
    print(f"Loaded {len(engine.registry)} ComBase models")
    
    # Initialize and populate vector store
    store = get_vector_store()
    store.initialize()
    
    pipeline = IngestionPipeline(vector_store=store)
    
    # Add some test data
    pipeline.ingest_text(
        "Raw chicken has pH 5.9-6.2 and water activity 0.99. "
        "Salmonella is commonly associated with raw poultry.",
        doc_type="food_properties",
        metadata={"food": "chicken"},
    )
    pipeline.ingest_text(
        "Salmonella grows between 5-47°C with optimal growth at 37°C. "
        "Common in poultry, eggs, and unpasteurized milk.",
        doc_type="pathogen_hazards",
        metadata={"pathogen": "salmonella"},
    )
    
    print(f"Vector store has {store.get_count()} documents")
    print()
    
    # Create orchestrator
    orchestrator = Orchestrator(combase_engine=engine)
    
    # Test queries
    test_queries = [
        "I left raw chicken on the counter for 3 hours at room temperature",
        "Cooked rice was left out overnight at 25°C",
        "Is salmon safe after 2 hours at 20C?",
    ]
    
    for query in test_queries:
        print("=" * 60)
        print(f"Query: {query}")
        print("=" * 60)
        
        result = await orchestrator.translate(query)
        
        if result.success:
            print(f"Status: SUCCESS")
            print(f"Organism: {result.execution_result.model_result.organism.value}")
            print(f"mu_max: {result.execution_result.model_result.mu_max:.4f} 1/h")
            print(f"Total log increase: {result.execution_result.total_log_increase:.2f}")
            
            if result.metadata:
                print(f"Overall confidence: {result.metadata.overall_confidence:.2f}")
                if result.metadata.bias_corrections:
                    print(f"Corrections applied: {len(result.metadata.bias_corrections)}")
                if result.metadata.warnings:
                    print(f"Warnings: {result.metadata.warnings}")
        else:
            print(f"Status: FAILED")
            print(f"Error: {result.error}")
        
        print()


if __name__ == "__main__":
    asyncio.run(main())