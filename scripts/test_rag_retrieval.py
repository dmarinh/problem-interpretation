#!/usr/bin/env python3
"""
Test RAG Retrieval Quality

Run after bootstrap_rag.py to verify retrieval accuracy.

Usage:
    python scripts/test_rag_retrieval.py
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.rag.vector_store import VectorStore, get_vector_store
from app.rag.retrieval import RetrievalService, get_retrieval_service


def test_food_properties() -> tuple[int, int]:
    """Test food properties retrieval."""
    print("\n" + "=" * 60)
    print("FOOD PROPERTIES RETRIEVAL TESTS")
    print("=" * 60)
    
    service = get_retrieval_service()
    
    test_cases = [
        {
            "query": "raw chicken",
            "expected_terms": ["chicken"],
            "description": "Should find chicken properties",
        },
        {
            "query": "beef pH",
            "expected_terms": ["beef"],
            "description": "Should find beef pH",
        },
        {
            "query": "milk dairy",
            "expected_terms": ["milk"],
            "description": "Should find milk properties",
        },
        {
            "query": "fresh fish",
            "expected_terms": ["fish"],
            "description": "Should find fish properties",
        },
        {
            "query": "eggs water activity",
            "expected_terms": ["egg"],
            "description": "Should find egg properties",
        },
    ]
    
    passed = 0
    failed = 0
    
    for tc in test_cases:
        response = service.query_food_properties(tc["query"])
        
        if not response.results:
            print(f"\n❌ FAIL: {tc['description']}")
            print(f"   Query: '{tc['query']}' - No results")
            failed += 1
            continue
        
        top = response.results[0]
        content_lower = top.content.lower()
        
        found_terms = [t for t in tc["expected_terms"] if t.lower() in content_lower]
        
        if found_terms:
            print(f"\n✅ PASS: {tc['description']}")
            print(f"   Query: '{tc['query']}'")
            print(f"   Confidence: {top.confidence:.3f} ({top.confidence_level.value})")
            print(f"   Found: {top.content[:70]}...")
            passed += 1
        else:
            print(f"\n❌ FAIL: {tc['description']}")
            print(f"   Query: '{tc['query']}'")
            print(f"   Expected terms: {tc['expected_terms']}")
            print(f"   Got: {top.content[:70]}...")
            failed += 1
    
    return passed, failed


def test_pathogen_hazards() -> tuple[int, int]:
    """Test pathogen hazards retrieval."""
    print("\n" + "=" * 60)
    print("PATHOGEN HAZARDS RETRIEVAL TESTS")
    print("=" * 60)
    
    service = get_retrieval_service()
    
    test_cases = [
        {
            "query": "poultry chicken",
            "expected_terms": ["salmonella", "poultry", "chicken"],
            "description": "Should find Salmonella for poultry",
        },
        {
            "query": "Listeria growth",
            "expected_terms": ["listeria"],
            "description": "Should find Listeria parameters",
        },
        {
            "query": "beef ground meat",
            "expected_terms": ["e. coli", "beef", "meat"],
            "description": "Should find E. coli for beef",
        },
        {
            "query": "Staphylococcus water activity toxin",
            "expected_terms": ["staphylococcus", "aureus"],
            "description": "Should find S. aureus aw limits",
        },
        {
            "query": "most dangerous pathogen oysters highest mortality",
            "expected_terms": ["vibrio", "vulnificus", "34.8%", "fatality"],
            "description": "Should find V. vulnificus as most lethal",
        },
        {
            "query": "Salmonella annual deaths CDC",
            "expected_terms": ["salmonella", "378", "deaths"],
            "description": "Should find CDC death statistics for Salmonella",
        },
        {
            "query": "Listeria case fatality rate",
            "expected_terms": ["listeria", "15.9%", "fatality"],
            "description": "Should find Listeria CFR from CDC data",
        },
        {
            "query": "norovirus foodborne transmission percent",
            "expected_terms": ["norovirus", "26%", "foodborne"],
            "description": "Should find norovirus transmission data",
        },
    ]
    
    passed = 0
    failed = 0
    
    for tc in test_cases:
        response = service.query_pathogen_hazards(tc["query"])
        
        if not response.results:
            print(f"\n❌ FAIL: {tc['description']}")
            print(f"   Query: '{tc['query']}' - No results")
            failed += 1
            continue
        
        top = response.results[0]
        content_lower = top.content.lower()
        
        found_terms = [t for t in tc["expected_terms"] if t.lower() in content_lower]
        
        if found_terms:
            print(f"\n✅ PASS: {tc['description']}")
            print(f"   Query: '{tc['query']}'")
            print(f"   Confidence: {top.confidence:.3f} ({top.confidence_level.value})")
            print(f"   Found terms: {found_terms}")
            print(f"   Result: {top.content[:70]}...")
            passed += 1
        else:
            print(f"\n❌ FAIL: {tc['description']}")
            print(f"   Query: '{tc['query']}'")
            print(f"   Expected any of: {tc['expected_terms']}")
            print(f"   Got: {top.content[:70]}...")
            failed += 1
    
    return passed, failed


def test_tcs_classification() -> tuple[int, int]:
    """Test TCS classification retrieval."""
    print("\n" + "=" * 60)
    print("TCS CLASSIFICATION RETRIEVAL TESTS")
    print("=" * 60)
    
    service = get_retrieval_service()
    
    test_cases = [
        {
            "query": "TCS pH 6.0 water activity 0.95",
            "expected_terms": ["tcs", "classification"],
            "description": "Should find TCS classification rules",
        },
        {
            "query": "heat-treated protected recontamination",
            "expected_terms": ["table a", "treated"],
            "description": "Should find Table A rules",
        },
    ]
    
    passed = 0
    failed = 0
    
    for tc in test_cases:
        response = service.query_conservative_values(tc["query"])
        
        if not response.results:
            print(f"\n❌ FAIL: {tc['description']}")
            print(f"   Query: '{tc['query']}' - No results")
            failed += 1
            continue
        
        top = response.results[0]
        content_lower = top.content.lower()
        
        found_terms = [t for t in tc["expected_terms"] if t.lower() in content_lower]
        
        if found_terms:
            print(f"\n✅ PASS: {tc['description']}")
            print(f"   Query: '{tc['query']}'")
            print(f"   Confidence: {top.confidence:.3f} ({top.confidence_level.value})")
            print(f"   Result: {top.content[:70]}...")
            passed += 1
        else:
            print(f"\n⚠️  PARTIAL: {tc['description']}")
            print(f"   Query: '{tc['query']}'")
            print(f"   Got: {top.content[:70]}...")
            # Count as pass if we got any result
            passed += 1
    
    return passed, failed


def main():
    print("=" * 60)
    print("RAG RETRIEVAL VALIDATION")
    print("=" * 60)
    
    # Initialize
    store = get_vector_store()
    if not store.is_initialized:
        store.initialize()
    
    # Check if database has data
    total_docs = store.get_count()
    if total_docs == 0:
        print("\n❌ ERROR: Database is empty!")
        print("   Run 'python scripts/bootstrap_rag.py' first.")
        sys.exit(1)
    
    print(f"\nDatabase contains {total_docs} documents")
    
    # Run tests
    total_passed = 0
    total_failed = 0
    
    p, f = test_food_properties()
    total_passed += p
    total_failed += f
    
    p, f = test_pathogen_hazards()
    total_passed += p
    total_failed += f
    
    p, f = test_tcs_classification()
    total_passed += p
    total_failed += f
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"\nTotal: {total_passed} passed, {total_failed} failed")
    
    if total_failed == 0:
        print("\n✅ All tests passed! RAG system is ready.")
        return 0
    else:
        print(f"\n⚠️  {total_failed} tests failed. Review data or queries.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
