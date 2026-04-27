#!/usr/bin/env python3
"""
RAG Knowledge Base Administration

A command-line tool for managing the RAG vector store.

Usage:
    python -m cli.rag_admin              # Default: full bootstrap (ingest all sources)
    python -m cli.rag_admin --clear      # Clear database before loading
    python -m cli.rag_admin --verify     # Run verification queries after loading
    python -m cli.rag_admin status       # Show database statistics only
    python -m cli.rag_admin verify       # Run verification queries only
    python -m cli.rag_admin clear        # Clear database only

For debugging:
    Run this file directly - main() executes with default settings.
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.stdout.reconfigure(encoding="utf-8")

from app.rag.vector_store import VectorStore, get_vector_store, reset_vector_store
from app.rag.ingestion import IngestionPipeline
from app.rag.data_sources import load_all_sources, load_source_references


# Default paths
DEFAULT_DATA_DIR = project_root / "data" / "rag"
DEFAULT_SOURCES_DIR = project_root / "data" / "sources"


def print_header(title: str) -> None:
    """Print a formatted section header."""
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def print_subheader(title: str) -> None:
    """Print a formatted subsection header."""
    print("\n" + "-" * 60)
    print(title)
    print("-" * 60)


def cmd_status(store: VectorStore) -> None:
    """Show database statistics."""
    print_header("DATABASE STATUS")
    
    total = store.get_count()
    food_props = store.get_count(VectorStore.TYPE_FOOD_PROPERTIES)
    pathogen = store.get_count(VectorStore.TYPE_PATHOGEN_HAZARDS)
    defaults = store.get_count(VectorStore.TYPE_CONSERVATIVE_VALUES)
    
    print(f"\n  Total documents:        {total}")
    print(f"  Food properties:        {food_props}")
    print(f"  Pathogen hazards:       {pathogen}")
    print(f"  TCS classification:     {defaults}")
    
    if total == 0:
        print("\n  ⚠️  Database is empty. Run bootstrap to load data.")


def cmd_verify(store: VectorStore) -> int:
    """Run verification queries against the database."""
    print_header("VERIFICATION QUERIES")

    test_queries = [
        ("chicken pH", VectorStore.TYPE_FOOD_PROPERTIES, ["chicken"]),
        ("Salmonella water activity", VectorStore.TYPE_PATHOGEN_HAZARDS, ["salmonella"]),
        ("most dangerous pathogen raw chicken", VectorStore.TYPE_PATHOGEN_HAZARDS, ["chicken", "salmonella"]),
        ("Listeria case fatality rate deaths", VectorStore.TYPE_PATHOGEN_HAZARDS, ["listeria", "fatality"]),
        ("Vibrio vulnificus mortality", VectorStore.TYPE_PATHOGEN_HAZARDS, ["vibrio", "vulnificus"]),
        ("norovirus foodborne transmission", VectorStore.TYPE_PATHOGEN_HAZARDS, ["norovirus", "foodborne"]),
        ("TCS pH 6.0 water activity 0.95", VectorStore.TYPE_CONSERVATIVE_VALUES, ["tcs", "classification"]),
    ]

    passed = 0
    failed = 0

    for query, doc_type, expected_terms in test_queries:
        results = store.query(query, n_results=1, doc_type=doc_type)

        if not results:
            print(f"\n  ❌ FAIL: '{query}' - No results")
            failed += 1
            continue

        top = results[0]
        content_lower = top["document"].lower()
        found_terms = [t for t in expected_terms if t.lower() in content_lower]

        if found_terms:
            distance = top.get("distance", 0)
            confidence = 1.0 / (1.0 + distance) if distance else 1.0
            print(f"\n  ✅ PASS: '{query}'")
            print(f"     Confidence: {confidence:.3f}")
            preview = top["document"][:70] + "..." if len(top["document"]) > 70 else top["document"]
            print(f"     Result: {preview}")
            passed += 1
        else:
            print(f"\n  ❌ FAIL: '{query}'")
            print(f"     Expected: {expected_terms}")
            preview = top["document"][:70] + "..." if len(top["document"]) > 70 else top["document"]
            print(f"     Got: {preview}")
            failed += 1

    # --- Audit-row consistency guard ---
    # Each entry: (food_name, field, expected_value)
    # Values corrected in the 2026-04-17 audit (changelog entries #8, #15, #17).
    # If any mismatch is detected the store contains stale pre-audit data —
    # run `python -m cli.rag_admin --clear` to re-bootstrap from the CSV.
    AUDIT_CHECKS = [
        ("chicken",     "ph_min", "6.2"),
        ("chicken",     "ph_max", "6.4"),
        ("bread white", "aw_min", "0.94"),
        ("bread white", "aw_max", "0.97"),
        ("maple syrup", "aw_min", "0.85"),
        ("maple syrup", "aw_max", "0.85"),
    ]

    print_subheader("AUDIT-ROW CONSISTENCY CHECK")

    for food_name, field, expected in AUDIT_CHECKS:
        docs = store.get_documents(
            where={"food_name": food_name, "type": VectorStore.TYPE_FOOD_PROPERTIES}
        )

        if not docs:
            print(f"\n  ❌ FAIL: '{food_name}' — not found in store")
            failed += 1
            continue

        if len(docs) > 1:
            ids = [d["id"] for d in docs]
            print(f"\n  ❌ FAIL: '{food_name}' — {len(docs)} duplicate entries (expected 1)")
            print(f"     IDs: {ids}")
            print(f"     Run --clear to re-bootstrap from the CSV.")
            failed += 1
            # Still check field value so the user sees both problems at once.

        actual = docs[0]["metadata"].get(field, "")
        if actual == expected:
            print(f"\n  ✅ PASS: {food_name}.{field} = {actual}")
            passed += 1
        else:
            print(f"\n  ❌ FAIL: {food_name}.{field}")
            print(f"     CSV (expected): {expected}")
            print(f"     RAG (actual):   {actual}")
            print(f"     Run --clear to re-bootstrap from the CSV.")
            failed += 1

    print_subheader("SUMMARY")
    print(f"\n  Passed: {passed}")
    print(f"  Failed: {failed}")

    return 0 if failed == 0 else 1


def cmd_clear(store: VectorStore) -> None:
    """Clear the vector store."""
    print_header("CLEARING DATABASE")
    before = store.get_count()
    store.clear()
    after = store.get_count()
    print(f"\n  ✅ Store wiped: {before} documents deleted, {after} remaining.")


def cmd_bootstrap(
    store: VectorStore, 
    data_dir: Path, 
    sources_dir: Path,
    clear_first: bool = False, 
    verify_after: bool = False
) -> int:
    """Load all data sources into the vector store."""
    print_header("RAG DATABASE BOOTSTRAP")
    
    print(f"\n  Data directory:    {data_dir}")
    print(f"  Sources directory: {sources_dir}")
    
    if not data_dir.exists():
        print(f"\n  ❌ ERROR: Data directory not found: {data_dir}")
        print("\n  Please ensure the following files exist:")
        print("    - food_properties.csv")
        print("    - pathogen_aw_limits.csv")
        print("    - pathogen_characteristics.csv")
        print("    - pathogen_transmission_details.csv")
        print("    - pathogen_food_associations.csv")
        print("    - food_pathogen_hazards.csv")
        print("    - tcs_classification_tables.csv")
        return 1
    
    if clear_first:
        print("\n  Clearing existing database...")
        before = store.get_count()
        store.clear()
        after = store.get_count()
        print(f"  ✅ Store wiped: {before} documents deleted, {after} remaining.")
    
    # Load source references for citation info
    print("\n  Loading source references...")
    sources = load_source_references(sources_dir)
    print(f"  ✅ Loaded {len(sources)} source definitions")
    
    # Create pipeline and load all sources
    pipeline = IngestionPipeline(vector_store=store)
    
    print_subheader("LOADING DATA SOURCES")
    
    results = load_all_sources(pipeline, data_dir)
    
    total_chunks = 0
    total_records = 0
    all_success = True
    
    for result in results:
        status = "✅" if result.success else "❌"
        print(f"\n  {status} {result.source_name}")
        print(f"     Records: {result.records_processed}, Chunks: {result.chunks_loaded}")
        if result.error:
            print(f"     Error: {result.error}")
            all_success = False
        total_chunks += result.chunks_loaded
        total_records += result.records_processed
    
    print_subheader("LOAD SUMMARY")
    print(f"\n  Total records processed: {total_records}")
    print(f"  Total chunks ingested:   {total_chunks}")

    # Write manifest so SystemAudit can stamp every future request
    pipeline.write_manifest(data_dir, total_chunks)
    print("\n  ✅ Ingestion manifest written to data/vector_store/ingest_manifest.json")

    # Show status
    cmd_status(store)
    
    # Optionally verify
    if verify_after:
        return cmd_verify(store)
    
    print("\n" + "=" * 60)
    print("BOOTSTRAP COMPLETE")
    print("=" * 60)
    
    return 0 if all_success else 1


def main(
    clear: bool = False,
    verify: bool = False,
    data_dir: Path = None,
    sources_dir: Path = None,
    command: str = None,
) -> int:
    """Main entry point.
    
    Args:
        clear: Clear database before loading
        verify: Run verification after loading
        data_dir: Path to data/rag/ directory
        sources_dir: Path to data/sources/ directory
        command: Subcommand (status, verify, clear, or None for bootstrap)
    
    Returns:
        Exit code (0 = success)
    """
    if data_dir is None:
        data_dir = DEFAULT_DATA_DIR
    if sources_dir is None:
        sources_dir = DEFAULT_SOURCES_DIR
    
    # Initialize vector store
    reset_vector_store()
    store = get_vector_store()
    store.initialize()
    
    # Handle subcommands
    if command == "status":
        cmd_status(store)
        return 0
    
    elif command == "verify":
        return cmd_verify(store)
    
    elif command == "clear":
        cmd_clear(store)
        return 0
    
    else:
        # Default: bootstrap (load all sources)
        return cmd_bootstrap(
            store=store,
            data_dir=data_dir,
            sources_dir=sources_dir,
            clear_first=clear,
            verify_after=verify,
        )


def cli() -> int:
    """Parse command-line arguments and run."""
    parser = argparse.ArgumentParser(
        description="RAG Knowledge Base Administration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m cli.rag_admin                    # Load all sources
  python -m cli.rag_admin --clear            # Clear and reload
  python -m cli.rag_admin --clear --verify   # Clear, reload, and verify
  python -m cli.rag_admin status             # Show database stats
  python -m cli.rag_admin verify             # Run verification queries
  python -m cli.rag_admin clear              # Clear database
        """
    )
    
    parser.add_argument(
        "command",
        nargs="?",
        choices=["status", "verify", "clear"],
        help="Subcommand (default: bootstrap/load all sources)"
    )
    
    parser.add_argument(
        "--clear", "-c",
        action="store_true",
        help="Clear existing database before loading"
    )
    
    parser.add_argument(
        "--verify", "-v",
        action="store_true",
        help="Run verification queries after loading"
    )
    
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=f"Path to RAG data directory (default: {DEFAULT_DATA_DIR})"
    )
    
    parser.add_argument(
        "--sources-dir",
        type=Path,
        default=DEFAULT_SOURCES_DIR,
        help=f"Path to sources directory (default: {DEFAULT_SOURCES_DIR})"
    )
    
    args = parser.parse_args()
    
    return main(
        clear=args.clear,
        verify=args.verify,
        data_dir=args.data_dir,
        sources_dir=args.sources_dir,
        command=args.command,
    )


if __name__ == "__main__":
    sys.exit(cli())
