"""
Food safety data loaders for RAG knowledge base.

Loads and transforms food safety data from CSV files into semantic documents
for vector store ingestion. Each loader:
1. Reads domain-specific CSV data
2. Transforms rows into natural language documents
3. Appends source tags for LLM citation awareness
4. Ingests into vector store with structured metadata

Sources:
  - CDC Scallan et al. 2011: Foodborne illness epidemiology
  - CDC 2019 (Tack et al.): Updated death estimates for major pathogens
  - IFT/FDA 2003: Evaluation and Definition of Potentially Hazardous Foods
  - FDA/CFSAN 2007: Approximate pH of Foods and Food Products
  - FDA Bad Bug Book 2nd Edition (2012)
"""

import csv
import re
from functools import lru_cache
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from app.rag.vector_store import VectorStore
from app.rag.ingestion import IngestionPipeline

# Path to the authoritative source ID registry, relative to this file.
_SOURCE_REF_CSV = Path(__file__).parent.parent.parent.parent / "data" / "sources" / "source_references.csv"

# Two patterns that appear in notes fields when a row's values come from two sources
# (changelog entries #14-17).  Bracket style: [IFT-2003-T31].
# Prose style: "aw 0.94-0.97 from IFT-2003-T31 Table 3-1".
_BRACKET_RE = re.compile(r'\[([A-Z]{2,}-\d{4}[A-Z0-9\-]*)\]')
_PROSE_RE = re.compile(r'\bfrom\s+([A-Z]{2,}-\d{4}[A-Z0-9\-]*)')


@lru_cache(maxsize=1)
def _valid_source_ids() -> frozenset:
    """Return the set of registered source IDs, loaded once per process."""
    if not _SOURCE_REF_CSV.exists():
        return frozenset()
    with open(_SOURCE_REF_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return frozenset(row["source_id"] for row in reader if row.get("source_id"))


def _parse_extra_source_ids(notes: str, valid_ids: frozenset) -> list[str]:
    """
    Extract additional source IDs embedded in a notes field and validate against
    the registry.  Returns only IDs that appear in valid_ids so table references
    like "Table 3-1" are not misidentified as source identifiers.
    """
    candidates: set[str] = set()
    for m in _BRACKET_RE.finditer(notes):
        candidates.add(m.group(1))
    for m in _PROSE_RE.finditer(notes):
        candidates.add(m.group(1))
    return [sid for sid in candidates if sid in valid_ids]


@dataclass
class LoadResult:
    """Result of a data loading operation."""
    source_name: str
    chunks_loaded: int
    records_processed: int
    success: bool
    error: Optional[str] = None


def load_food_properties(pipeline: IngestionPipeline, data_dir: Path) -> LoadResult:
    """Load food pH and water activity values.
    
    Source: FDA pH List (FDA-PH-2007), IFT/FDA Tables 3-1, 3-3
    """
    file_path = data_dir / "food_properties.csv"
    
    if not file_path.exists():
        return LoadResult("food_properties", 0, 0, False, f"File not found: {file_path}")
    
    chunks = 0
    records = 0
    
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("food_name") or row["food_name"].startswith("#"):
                continue
            
            records += 1
            
            # Build semantic document
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
            
            doc = ": ".join(parts[:2]) + ". " + ". ".join(parts[2:]) if len(parts) > 2 else ": ".join(parts)
            
            # Merge column source_id with any secondary sources cited in notes.
            # Some rows carry values from two references but the schema has one
            # source_id column; the secondary appears in notes as prose or bracket
            # style (changelog entries #14-17).  Stored comma-separated so the
            # grounding service, which already splits on comma, picks them both up.
            source_id = row.get("source_id", "")
            notes_text = row.get("notes", "")
            extra = _parse_extra_source_ids(notes_text, _valid_source_ids())
            all_source_ids = list(dict.fromkeys(([source_id] if source_id else []) + extra))
            merged_source_id = ",".join(all_source_ids)

            for sid in all_source_ids:
                doc += f" [{sid}]"

            result = pipeline.ingest_text(
                text=doc,
                doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
                metadata={
                    "food_name": row["food_name"],
                    "food_category": row["food_category"],
                    "ph_min": row.get("ph_min", ""),
                    "ph_max": row.get("ph_max", ""),
                    "aw_min": row.get("aw_min", ""),
                    "aw_max": row.get("aw_max", ""),
                    "source_id": merged_source_id,
                },
                source=f"food_properties:{row['food_name']}",
            )
            
            if result["success"]:
                chunks += result["chunks"]
    
    return LoadResult("food_properties", chunks, records, True)


def load_pathogen_aw_limits(pipeline: IngestionPipeline, data_dir: Path) -> LoadResult:
    """Load pathogen water activity growth limits.
    
    Source: IFT/FDA Table 3-2 (IFT-2003-T32)
    """
    file_path = data_dir / "pathogen_aw_limits.csv"
    
    if not file_path.exists():
        return LoadResult("pathogen_aw_limits", 0, 0, False, f"File not found: {file_path}")
    
    chunks = 0
    records = 0
    
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("pathogen") or row["pathogen"].startswith("#"):
                continue
            
            records += 1
            
            # Build semantic document
            parts = [f"{row['pathogen']} growth parameters"]
            
            if row.get("aw_min"):
                parts.append(f"minimum water activity for growth is {row['aw_min']}")
            if row.get("aw_opt"):
                parts.append(f"optimum water activity {row['aw_opt']}")
            if row.get("aw_max"):
                parts.append(f"maximum water activity {row['aw_max']}")
            if row.get("notes"):
                parts.append(row["notes"])
            
            doc = ": ".join(parts[:2]) + ". " + ". ".join(parts[2:])
            
            # Append source tag
            source_id = row.get("source_id", "")
            if source_id:
                doc += f" [{source_id}]"
            
            result = pipeline.ingest_text(
                text=doc,
                doc_type=VectorStore.TYPE_PATHOGEN_HAZARDS,
                metadata={
                    "pathogen": row["pathogen"],
                    "data_type": "growth_parameters",
                    "aw_min": row.get("aw_min", ""),
                    "source_id": source_id,
                },
                source=f"pathogen_aw:{row['pathogen']}",
            )
            
            if result["success"]:
                chunks += result["chunks"]
    
    return LoadResult("pathogen_aw_limits", chunks, records, True)


def load_pathogen_characteristics(pipeline: IngestionPipeline, data_dir: Path) -> LoadResult:
    """Load pathogen epidemiology data from CDC sources.

    Source: CDC Scallan et al. 2011, Tables 2-3 (CDC-2011-T3)
            CDC Tack et al. 2019, updated death estimates (CDC-2019)
    """
    file_path = data_dir / "pathogen_characteristics.csv"
    
    if not file_path.exists():
        return LoadResult("pathogen_characteristics", 0, 0, False, f"File not found: {file_path}")
    
    chunks = 0
    records = 0
    
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("pathogen"):
                continue
            
            records += 1
            source_id = row.get("source_id", "")
            data_year = row.get("data_year", "")
            year_label = f" ({data_year} data)" if data_year else ""

            # Build comprehensive semantic document
            parts = [f"{row['pathogen']} epidemiology"]

            if row.get("annual_illnesses"):
                cri = row.get('illnesses_90pct_cri', 'unknown')
                parts.append(f"{row['annual_illnesses']} annual US illnesses (90% CrI: {cri}){year_label}")

            if row.get("annual_hospitalizations"):
                parts.append(f"{row['annual_hospitalizations']} annual hospitalizations{year_label}")
                if row.get("hospitalization_rate_pct"):
                    parts.append(f"hospitalization rate {row['hospitalization_rate_pct']}%")

            if row.get("annual_deaths"):
                cri = row.get('deaths_90pct_cri', 'unknown')
                parts.append(f"{row['annual_deaths']} annual deaths (90% CrI: {cri}){year_label}")
                if row.get("death_rate_pct"):
                    parts.append(f"case fatality rate {row['death_rate_pct']}%")

            if row.get("percent_foodborne"):
                parts.append(f"{row['percent_foodborne']}% foodborne transmission")

            doc = ": ".join(parts[:2]) + ". " + ". ".join(parts[2:])

            if row.get("notes"):
                doc += f" Note: {row['notes']}."

            if source_id:
                doc += f" [{source_id}]"

            result = pipeline.ingest_text(
                text=doc,
                doc_type=VectorStore.TYPE_PATHOGEN_HAZARDS,
                metadata={
                    "pathogen": row["pathogen"],
                    "data_type": "cdc_epidemiology",
                    "data_year": data_year,
                    "annual_illnesses": row.get("annual_illnesses", ""),
                    "annual_hospitalizations": row.get("annual_hospitalizations", ""),
                    "annual_deaths": row.get("annual_deaths", ""),
                    "hospitalization_rate_pct": row.get("hospitalization_rate_pct", ""),
                    "death_rate_pct": row.get("death_rate_pct", ""),
                    "percent_foodborne": row.get("percent_foodborne", ""),
                    "source_id": source_id,
                },
                source=f"pathogen_cdc:{row['pathogen']}",
            )
            
            if result["success"]:
                chunks += result["chunks"]
    
    return LoadResult("pathogen_characteristics", chunks, records, True)


def load_pathogen_transmission(pipeline: IngestionPipeline, data_dir: Path) -> LoadResult:
    """Load pathogen transmission route details from CDC appendix.
    
    Source: CDC Scallan et al. 2011, Technical Appendix 1 (CDC-2011-A1)
    """
    file_path = data_dir / "pathogen_transmission_details.csv"
    
    if not file_path.exists():
        return LoadResult("pathogen_transmission", 0, 0, False, f"File not found: {file_path}")
    
    chunks = 0
    records = 0
    
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("pathogen"):
                continue
            
            records += 1
            source_id = row.get("source_id", "")
            
            doc = (
                f"{row['pathogen']} transmission: {row['percent_foodborne']}% foodborne "
                f"(basis: {row['foodborne_basis']}). "
            )
            if row.get("non_foodborne_routes"):
                doc += f"Non-food routes: {row['non_foodborne_routes']}. "
            if row.get("comments"):
                doc += row["comments"]
            
            if source_id:
                doc += f" [{source_id}]"
            
            result = pipeline.ingest_text(
                text=doc,
                doc_type=VectorStore.TYPE_PATHOGEN_HAZARDS,
                metadata={
                    "pathogen": row["pathogen"],
                    "data_type": "transmission_routes",
                    "percent_foodborne": row["percent_foodborne"],
                    "non_foodborne_routes": row.get("non_foodborne_routes", ""),
                    "source_id": source_id,
                },
                source=f"pathogen_transmission:{row['pathogen']}",
            )
            
            if result["success"]:
                chunks += result["chunks"]
    
    return LoadResult("pathogen_transmission", chunks, records, True)


def load_pathogen_food_associations(pipeline: IngestionPipeline, data_dir: Path) -> LoadResult:
    """Load pathogen-food category associations.
    
    Source: IFT/FDA Table 1 (IFT-2003-T1)
    """
    file_path = data_dir / "pathogen_food_associations.csv"
    
    if not file_path.exists():
        return LoadResult("pathogen_food_associations", 0, 0, False, f"File not found: {file_path}")
    
    chunks = 0
    records = 0
    
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("food_category") or row["food_category"].startswith("#"):
                continue
            
            records += 1
            source_id = row.get("source_id", "")
            
            doc = (
                f"{row['pathogen']} is a pathogen of concern for {row['food_category']}. "
                f"Control methods include: {row['control_methods']}. "
            )
            if row.get("notes"):
                doc += row["notes"]
            
            if source_id:
                doc += f" [{source_id}]"
            
            result = pipeline.ingest_text(
                text=doc,
                doc_type=VectorStore.TYPE_PATHOGEN_HAZARDS,
                metadata={
                    "pathogen": row["pathogen"],
                    "food_category": row["food_category"],
                    "data_type": "food_association",
                    "source_id": source_id,
                },
                source=f"pathogen_food:{row['pathogen']}:{row['food_category']}",
            )
            
            if result["success"]:
                chunks += result["chunks"]
    
    return LoadResult("pathogen_food_associations", chunks, records, True)


def load_food_pathogen_hazards(pipeline: IngestionPipeline, data_dir: Path) -> LoadResult:
    """Load direct food-to-pathogen hazard mappings with CDC severity metrics.

    Source: Derived from CDC Scallan 2011 & CDC Tack 2019 + IFT/FDA Table 1
    """
    file_path = data_dir / "food_pathogen_hazards.csv"
    
    if not file_path.exists():
        return LoadResult("food_pathogen_hazards", 0, 0, False, f"File not found: {file_path}")
    
    chunks = 0
    records = 0
    
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("food_name"):
                continue
            
            records += 1
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
            
            result = pipeline.ingest_text(
                text=doc,
                doc_type=VectorStore.TYPE_PATHOGEN_HAZARDS,
                metadata={
                    "food_name": row["food_name"],
                    "food_category": row["food_category"],
                    "pathogen": row["pathogen"],
                    "case_fatality_rate": row["case_fatality_rate"],
                    "annual_deaths_us": row["annual_deaths_us"],
                    "primary_hazard": row["primary_hazard"],
                    "data_type": "food_pathogen_hazard",
                    "source_id": source_id,
                },
                source=f"food_hazard:{row['food_name']}:{row['pathogen']}",
            )
            
            if result["success"]:
                chunks += result["chunks"]
    
    return LoadResult("food_pathogen_hazards", chunks, records, True)


def load_tcs_classification(pipeline: IngestionPipeline, data_dir: Path) -> LoadResult:
    """Load TCS (Time/Temperature Control for Safety) classification tables.
    
    Source: IFT/FDA Tables A & B (IFT-2003-TA, IFT-2003-TB)
    """
    file_path = data_dir / "tcs_classification_tables.csv"
    
    if not file_path.exists():
        return LoadResult("tcs_classification", 0, 0, False, f"File not found: {file_path}")
    
    chunks = 0
    records = 0
    
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("table_type") or row["table_type"].startswith("#"):
                continue
            
            records += 1
            source_id = row.get("source_id", "")
            
            table_desc = (
                "heat-treated and protected from recontamination" 
                if row["table_type"] == "A" 
                else "not treated or not protected from recontamination"
            )
            
            doc = (
                f"TCS Classification (Table {row['table_type']} - {table_desc}): "
                f"For foods with pH {row['ph_min']}-{row['ph_max']} and "
                f"water activity {row['aw_min']}-{row['aw_max']}, "
                f"classification is {row['classification']}. "
                f"{row['notes']}"
            )
            
            if source_id:
                doc += f" [{source_id}]"
            
            result = pipeline.ingest_text(
                text=doc,
                doc_type=VectorStore.TYPE_CONSERVATIVE_VALUES,
                metadata={
                    "table_type": row["table_type"],
                    "classification": row["classification"],
                    "ph_min": row["ph_min"],
                    "ph_max": row["ph_max"],
                    "aw_min": row["aw_min"],
                    "aw_max": row["aw_max"],
                    "data_type": "tcs_classification",
                    "source_id": source_id,
                },
                source=f"tcs:{row['table_type']}:{row['aw_category']}:{row['ph_category']}",
            )
            
            if result["success"]:
                chunks += result["chunks"]
    
    return LoadResult("tcs_classification", chunks, records, True)


def load_all_sources(pipeline: IngestionPipeline, data_dir: Path) -> list[LoadResult]:
    """Load all food safety data sources.
    
    Args:
        pipeline: IngestionPipeline instance
        data_dir: Path to data/rag/ directory
    
    Returns:
        List of LoadResult for each source
    """
    loaders = [
        ("Food properties", load_food_properties),
        ("Pathogen aw limits", load_pathogen_aw_limits),
        ("Pathogen characteristics (CDC)", load_pathogen_characteristics),
        ("Pathogen transmission", load_pathogen_transmission),
        ("Pathogen-food associations", load_pathogen_food_associations),
        ("Food-pathogen hazards", load_food_pathogen_hazards),
        ("TCS classification", load_tcs_classification),
    ]
    
    results = []
    for name, loader_func in loaders:
        result = loader_func(pipeline, data_dir)
        results.append(result)
    
    return results
