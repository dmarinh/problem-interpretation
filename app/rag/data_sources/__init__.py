"""
Domain-specific data loaders for RAG knowledge base.

This module contains loaders that transform domain data (food safety, pathogen info)
into semantic documents for vector store ingestion.

Distinct from app/rag/loaders/ which contains generic format parsers (CSV, PDF, etc).
"""

from .food_safety import (
    load_food_properties,
    load_pathogen_aw_limits,
    load_pathogen_characteristics,
    load_pathogen_transmission,
    load_pathogen_food_associations,
    load_food_pathogen_hazards,
    load_tcs_classification,
    load_all_sources,
)

from .citations import (
    load_source_references,
    format_citation,
)

__all__ = [
    # Food safety loaders
    "load_food_properties",
    "load_pathogen_aw_limits",
    "load_pathogen_characteristics",
    "load_pathogen_transmission",
    "load_pathogen_food_associations",
    "load_food_pathogen_hazards",
    "load_tcs_classification",
    "load_all_sources",
    # Citation utilities
    "load_source_references",
    "format_citation",
]
