# RAG Data Sources: Architecture and Design

This document describes the architecture, design decisions, and technical implementation of the RAG (Retrieval-Augmented Generation) data ingestion system for the Predictive Microbiology Translation Module.

---

## Table of Contents

1. [Overview](#overview)
2. [Folder Structure](#folder-structure)
3. [Data Sources](#data-sources)
4. [Data Processing Pipeline](#data-processing-pipeline)
5. [Citation System](#citation-system)
6. [Technical Architecture](#technical-architecture)
7. [Administration Tool](#administration-tool)
8. [Design Decisions and Rationale](#design-decisions-and-rationale)
9. [Extending the System](#extending-the-system)
10. [Troubleshooting](#troubleshooting)

---

## Overview

The RAG system provides domain-specific knowledge retrieval for food safety and predictive microbiology queries. It transforms authoritative source documents (FDA, CDC publications) into a searchable vector database, enabling the LLM to ground its responses in verified, citable data.

### Key Principles

1. **Traceability**: Every fact in the system traces back to a specific source document, table, and page
2. **LLM Awareness**: Source tags are embedded in documents so the LLM can reason about source authority
3. **Separation of Concerns**: Raw sources, processed data, and vector storage are kept separate
4. **Maintainability**: Single-file loaders, standardized formats, and clear naming conventions

---

## Folder Structure

```
project_root/
├── app/
│   └── rag/
│       ├── loaders/                  # Generic format parsers
│       │   ├── csv_loader.py         # Parse any CSV file
│       │   ├── pdf_loader.py         # Parse any PDF file
│       │   └── ...
│       │
│       ├── data_sources/             # Domain-specific data loaders
│       │   ├── __init__.py           # Exports all loaders
│       │   ├── food_safety.py        # Food safety domain loaders
│       │   └── citations.py          # Citation utilities
│       │
│       ├── vector_store.py           # ChromaDB interface
│       ├── ingestion.py              # Ingestion pipeline
│       └── retrieval.py              # Query interface
│
├── cli/
│   └── rag_admin.py                  # Administration CLI tool
│
├── data/
│   ├── rag/                          # Processed data for ingestion
│   │   ├── README.md
│   │   ├── food_properties.csv
│   │   ├── pathogen_characteristics.csv
│   │   └── ...
│   │
│   ├── sources/                      # Reference materials
│   │   ├── source_references.csv     # Master citation table
│   │   ├── sources.md                # Source documentation
│   │   ├── extraction_notes.md       # Methodology notes
│   │   ├── CDC_Scallan_2011.pdf      # Original PDFs
│   │   └── ...
│   │
│   └── vector_store/                 # ChromaDB persistent storage
│
└── scripts/
    └── tests/
        └── test_rag_retrieval.py     # Retrieval validation
```

### Folder Purposes

| Folder | Purpose | Contents |
|--------|---------|----------|
| `app/rag/loaders/` | Generic format parsing | CSV, PDF, DOCX parsers (format-agnostic) |
| `app/rag/data_sources/` | Domain-specific transformation | Food safety loaders (domain-aware) |
| `data/rag/` | Ingestion-ready data | Processed CSVs with standardized schema |
| `data/sources/` | Reference archive | Original PDFs, citation metadata, documentation |
| `data/vector_store/` | Persistent storage | ChromaDB database files |

### Why Two Loader Locations?

The distinction between `loaders/` and `data_sources/` reflects two different responsibilities:

- **`loaders/`**: "How do I read this file format?" — Generic, reusable across domains
- **`data_sources/`**: "What does this data mean and how should it be represented?" — Domain-specific transformation logic

This separation allows the same CSV loader to be used for food properties, pathogen data, or any future domain, while the transformation logic remains domain-specific.

---

## Data Sources

### Primary Sources

| Source ID | Document | Authority | Content |
|-----------|----------|-----------|---------|
| `CDC-2011-T2/T3/A1` | Scallan et al. (2011) | CDC/EID Journal | Foodborne illness epidemiology |
| `IFT-2003-T1/T31-33/TA/TB` | IFT/FDA PHF Report | FDA-commissioned | Food safety parameters, TCS rules |
| `FDA-PH-2007` | FDA pH List | FDA/CFSAN | Food pH values |
| `FDA-BBB-2012` | Bad Bug Book 2nd Ed | FDA/CFSAN | Pathogen characteristics |

### Why These Sources?

1. **Authoritative**: All sources are from FDA, CDC, or FDA-commissioned research
2. **Peer-reviewed**: CDC data is from Emerging Infectious Diseases journal
3. **Comprehensive**: Together they cover food properties, pathogen behavior, and classification rules
4. **Citable**: All have DOIs or official URLs for verification

### Processed Data Files

| File | Records | Source | Purpose |
|------|---------|--------|---------|
| `food_properties.csv` | 259 | FDA-PH-2007, IFT-2003 | Food pH and water activity |
| `pathogen_aw_limits.csv` | 14 | IFT-2003-T32 | Pathogen growth limits |
| `pathogen_characteristics.csv` | 30 | CDC-2011-T3 | Epidemiology (illnesses, deaths) |
| `pathogen_transmission_details.csv` | 27 | CDC-2011-A1 | Transmission routes, % foodborne |
| `pathogen_food_associations.csv` | 46 | IFT-2003-T1 | Food category → pathogen mapping |
| `food_pathogen_hazards.csv` | 60 | Derived | Direct food → pathogen → severity |
| `tcs_classification_tables.csv` | 25 | IFT-2003-TA/TB | TCS classification rules |

### Why Processed CSVs Instead of Raw PDFs?

1. **Structured retrieval**: CSV rows become discrete, searchable chunks
2. **Consistent schema**: Standardized columns enable metadata filtering
3. **Quality control**: Human verification during extraction catches OCR errors
4. **Source tagging**: Each row carries its source_id for citation
5. **Semantic transformation**: Raw tables become natural language documents

---

## Data Processing Pipeline

### From PDF to Vector Store

```
┌─────────────────┐
│  Original PDF   │  (e.g., CDC_Scallan_2011.pdf)
│  data/sources/  │
└────────┬────────┘
         │ Manual extraction + verification
         ▼
┌─────────────────┐
│  Processed CSV  │  (e.g., pathogen_characteristics.csv)
│  data/rag/      │  Standardized schema, source_id column
└────────┬────────┘
         │ Domain loader (food_safety.py)
         ▼
┌─────────────────┐
│ Semantic Document│  "Listeria monocytogenes epidemiology:
│ + Source Tag     │   255 annual deaths, CFR 15.9% [CDC-2011-T3]"
└────────┬────────┘
         │ Embedding + Ingestion
         ▼
┌─────────────────┐
│  Vector Store   │  ChromaDB with metadata
│  data/vector_store/
└─────────────────┘
```

### Transformation Example

**Raw PDF table row:**
```
Listeria monocytogenes | 1,591 | 1,455 | 255 | 94.0 | 15.9
```

**Processed CSV row:**
```csv
pathogen,annual_illnesses,annual_hospitalizations,annual_deaths,hospitalization_rate_pct,death_rate_pct,source_id
Listeria monocytogenes,1591,1455,255,94.0,15.9,CDC-2011-T3
```

**Semantic document (ingested):**
```
Listeria monocytogenes epidemiology: 1591 annual US illnesses (90% CrI: 557-3161). 
1455 annual hospitalizations. hospitalization rate 94.0%. 255 annual deaths 
(90% CrI: 0-733). case fatality rate 15.9%. 99% foodborne transmission. [CDC-2011-T3]
```

**Stored in ChromaDB:**
- **Document**: The semantic text above (embedded for similarity search)
- **Metadata**: `{pathogen: "Listeria monocytogenes", annual_deaths: "255", source_id: "CDC-2011-T3", ...}`
- **Source**: `pathogen_cdc:Listeria monocytogenes`

---

## Citation System

### Design: Approach 4 (Hybrid)

We evaluated four approaches for source citation:

| Approach | Description | LLM Sees Source? |
|----------|-------------|------------------|
| 1. Source codes in CSV only | Normalized tables, lookup at query time | ❌ No |
| 2. Embed full citation in document | Full citation in every chunk | ✅ Yes |
| 3. Structured metadata only | Citation in metadata, app adds to response | ❌ No |
| **4. Hybrid (chosen)** | Short tag in document + full citation in metadata | ✅ Yes |

### Why Hybrid?

The key insight is that **the LLM needs to see the source** during reasoning, not just in post-processing:

1. **Epistemic reasoning**: When the LLM sees `[CDC-2011-T3]`, it knows this is authoritative CDC surveillance data, not an estimate
2. **Conflict resolution**: If two chunks disagree, the LLM can prefer the more authoritative source
3. **Appropriate hedging**: The LLM matches confidence language to source type
4. **Citation accuracy**: Full citation in metadata enables proper bibliography generation

### Source ID Convention

Format: `{AUTHORITY}-{YEAR}-{TABLE/SECTION}`

Examples:
- `CDC-2011-T3` — CDC Scallan 2011, Table 3
- `IFT-2003-T32` — IFT/FDA 2003 report, Table 3-2
- `FDA-BBB-2012` — FDA Bad Bug Book, 2nd Edition

### Citation Flow

```
┌─────────────────────────────────────────────────────────────┐
│                        RETRIEVAL                            │
│  ChromaDB returns:                                          │
│    document: "V. vulnificus: CFR 34.8% [CDC-2011-T3]"       │
│    metadata: {source_id: "CDC-2011-T3", ...}                │
└─────────────────────────────────────────────────────────────┘
                              │
               ┌──────────────┴──────────────┐
               ▼                              ▼
      ┌─────────────────┐            ┌─────────────────┐
      │     TO LLM      │            │   TO APP LAYER  │
      │  (text+source)  │            │ (full citations)│
      │                 │            │                 │
      │ "V. vulnificus: │            │ CDC-2011-T3 →   │
      │  CFR 34.8%      │            │ Scallan E, et al│
      │  [CDC-2011-T3]" │            │ (2011) EID...   │
      └────────┬────────┘            └────────┬────────┘
               │                              │
               ▼                              │
      ┌─────────────────┐                     │
      │    LLM OUTPUT   │                     │
      │                 │                     │
      │ "According to   │                     │
      │  CDC data, the  │                     │
      │  CFR is 34.8%   │                     │
      │  [CDC-2011-T3]" │                     │
      └────────┬────────┘                     │
               │                              │
               ▼                              ▼
      ┌─────────────────────────────────────────────┐
      │            CITATION EXPANSION               │
      │                                             │
      │  "According to CDC data, the CFR is 34.8%"  │
      │                                             │
      │  References:                                │
      │  [1] Scallan E, et al. (2011) EID 17(1)    │
      └─────────────────────────────────────────────┘
```

### Source References File

`data/sources/source_references.csv` is the master citation table:

```csv
source_id,short_name,document_title,authors,year,publisher,table_or_section,url,doi,access_date
CDC-2011-T3,CDC Scallan Table 3,Foodborne Illness Acquired in the United States—Major Pathogens,"Scallan E, Hoekstra RM, ...",2011,Emerging Infectious Diseases 17(1):7-15,Table 3,https://...,10.3201/eid1701.P11101,2026-03-12
```

This enables:
- `format_citation(source_id, style="short")` → "Scallan E et al. (2011), Table 3"
- `format_citation(source_id, style="full")` → Full bibliographic citation

---

## Technical Architecture

### Module Structure

```
app/rag/data_sources/
├── __init__.py          # Exports all public functions
├── food_safety.py       # Domain loaders
└── citations.py         # Citation utilities
```

### Key Components

#### LoadResult Dataclass

```python
@dataclass
class LoadResult:
    source_name: str
    chunks_loaded: int
    records_processed: int
    success: bool
    error: Optional[str] = None
```

Every loader returns a `LoadResult` for consistent error handling and reporting.

#### Loader Function Signature

```python
def load_food_properties(pipeline: IngestionPipeline, data_dir: Path) -> LoadResult:
    """Load food pH and water activity values.
    
    Source: FDA pH List (FDA-PH-2007), IFT/FDA Tables 3-1, 3-3
    """
```

All loaders follow this pattern:
1. Accept `pipeline` and `data_dir`
2. Return `LoadResult`
3. Document the source in docstring

#### Aggregator Function

```python
def load_all_sources(pipeline: IngestionPipeline, data_dir: Path) -> list[LoadResult]:
    """Load all food safety data sources."""
```

Single entry point for loading all sources, used by `rag_admin.py`.

### Vector Store Types

Three document types partition the collection:

```python
VectorStore.TYPE_FOOD_PROPERTIES      # "food_properties"
VectorStore.TYPE_PATHOGEN_HAZARDS     # "pathogen_hazards"  
VectorStore.TYPE_CONSERVATIVE_VALUES  # "conservative_values"
```

This enables targeted queries (e.g., search only food properties).

---

## Administration Tool

### Location and Usage

```bash
# Default: load all sources
python -m cli.rag_admin

# Clear and reload
python -m cli.rag_admin --clear

# Clear, reload, and verify
python -m cli.rag_admin --clear --verify

# Subcommands
python -m cli.rag_admin status    # Show database statistics
python -m cli.rag_admin verify    # Run verification queries
python -m cli.rag_admin clear     # Clear database
```

### Debugger-Friendly Design

The tool is designed for easy debugging:

```python
if __name__ == "__main__":
    # When run directly (e.g., in debugger), execute with defaults
    sys.exit(main())
```

Running `cli/rag_admin.py` directly (F5 in VS Code) executes full bootstrap with no arguments needed.

### Commands

| Command | Description |
|---------|-------------|
| (default) | Load all sources into vector store |
| `--clear` | Clear database before loading |
| `--verify` | Run verification queries after loading |
| `status` | Show document counts by type |
| `verify` | Run verification queries only |
| `clear` | Clear database only |

### Output Example

```
============================================================
RAG DATABASE BOOTSTRAP
============================================================

  Data directory:    data/rag
  Sources directory: data/sources

  Loading source references...
  ✅ Loaded 11 source definitions

------------------------------------------------------------
LOADING DATA SOURCES
------------------------------------------------------------

  ✅ food_properties
     Records: 259, Chunks: 259

  ✅ pathogen_characteristics
     Records: 30, Chunks: 30

  ...

------------------------------------------------------------
LOAD SUMMARY
------------------------------------------------------------

  Total records processed: 463
  Total chunks ingested:   463

============================================================
BOOTSTRAP COMPLETE
============================================================
```

---

## Design Decisions and Rationale

### Decision 1: CSV over Direct PDF Ingestion

**Choice**: Extract PDF data to CSV, then ingest CSV

**Rationale**:
- PDF tables are poorly structured for semantic search
- Manual extraction allows quality verification
- CSV schema standardization enables consistent metadata
- Source tags can be added per-row
- Easier to update individual records

**Trade-off**: Manual extraction effort vs. data quality

### Decision 2: Semantic Documents over Raw Data

**Choice**: Transform CSV rows to natural language before embedding

**Rationale**:
- Embedding models understand natural language better than tabular data
- Enables richer queries ("most dangerous pathogen" vs. exact column match)
- Context is preserved in each chunk
- Source attribution is inline

**Example**:
```
Raw:    Listeria,1591,1455,255,94.0,15.9
Semantic: "Listeria monocytogenes epidemiology: 1591 annual illnesses..."
```

### Decision 3: Source Tags in Document Text

**Choice**: Append `[SOURCE-ID]` to every document

**Rationale**:
- LLM sees source authority during reasoning
- Enables conflict resolution between sources
- Natural citation in LLM output
- Minimal document size increase (~10 chars)

**Alternative rejected**: Metadata-only citations (LLM cannot see them)

### Decision 4: Single Aggregator Function

**Choice**: `load_all_sources()` calls all individual loaders

**Rationale**:
- Single entry point for CLI and programmatic use
- Consistent error handling across loaders
- Easy to add new loaders (add to list)
- Individual loaders remain testable in isolation

### Decision 5: Separate `data/rag/` and `data/sources/`

**Choice**: Processed data separate from reference materials

**Rationale**:
- Clear ingestion boundary (only `data/rag/` is ingested)
- PDFs can be large; separation allows `.gitignore` flexibility
- Source references live with source documents
- Prevents accidental PDF ingestion

### Decision 6: LoadResult Dataclass

**Choice**: Structured return type for all loaders

**Rationale**:
- Consistent success/failure tracking
- Enables aggregated reporting
- Type-safe error handling
- Clear API contract

---

## Extending the System

### Adding a New Data Source

1. **Prepare the data**:
   ```
   data/sources/New_Source_2024.pdf          # Original document
   data/rag/new_source_data.csv              # Extracted data with source_id column
   ```

2. **Add source reference**:
   ```csv
   # In data/sources/source_references.csv
   NEW-2024-T1,New Source Table 1,Document Title,Authors,2024,Publisher,Table 1,https://...,10.xxxx/xxxxx,2024-01-01
   ```

3. **Create loader function** in `app/rag/data_sources/food_safety.py`:
   ```python
   def load_new_source(pipeline: IngestionPipeline, data_dir: Path) -> LoadResult:
       """Load new source data.
       
       Source: New Source 2024, Table 1 (NEW-2024-T1)
       """
       file_path = data_dir / "new_source_data.csv"
       # ... transformation logic ...
       return LoadResult("new_source", chunks, records, True)
   ```

4. **Register in aggregator**:
   ```python
   def load_all_sources(...):
       loaders = [
           # ... existing loaders ...
           ("New source", load_new_source),
       ]
   ```

5. **Update exports** in `__init__.py`

6. **Run bootstrap**:
   ```bash
   python -m cli.rag_admin --clear --verify
   ```

### Adding a New Domain

For a completely new domain (e.g., chemical hazards):

1. Create `app/rag/data_sources/chemical_safety.py`
2. Define new `VectorStore.TYPE_CHEMICAL_HAZARDS` if needed
3. Add to `__init__.py` exports
4. Create corresponding `data/rag/chemical_*.csv` files
5. Update `rag_admin.py` to include new domain

---

## Troubleshooting

### Common Issues

**"File not found" errors**:
- Check `data/rag/` contains all required CSV files
- Verify file names match loader expectations

**Empty query results**:
- Run `python -m cli.rag_admin status` to check document counts
- Run `python -m cli.rag_admin --clear` to reload

**Citation tags not appearing in LLM output**:
- Verify CSV has `source_id` column
- Check loader appends `[{source_id}]` to document text

**Metadata not filtering correctly**:
- Verify metadata keys match query filters
- Check `doc_type` parameter in queries

### Verification Queries

The `verify` command tests these queries:

| Query | Expected Result |
|-------|-----------------|
| "chicken pH" | Chicken food properties |
| "Salmonella water activity" | Salmonella growth parameters |
| "Listeria case fatality rate" | Listeria epidemiology with 15.9% |
| "Vibrio vulnificus mortality" | V. vulnificus with 34.8% CFR |
| "TCS pH 6.0 water activity 0.95" | TCS classification rule |

---

## References

### Source Documents

1. Scallan E, et al. (2011). Foodborne Illness Acquired in the United States—Major Pathogens. *Emerging Infectious Diseases*, 17(1):7-15. doi:10.3201/eid1701.P11101

2. Institute of Food Technologists. (2003). Evaluation and Definition of Potentially Hazardous Foods. *Comprehensive Reviews in Food Science and Food Safety*, 2(s1):1-108. doi:10.1111/j.1541-4337.2003.tb00052.x

3. FDA/CFSAN. (2007). Approximate pH of Foods and Food Products.

4. FDA/CFSAN. (2012). Bad Bug Book: Foodborne Pathogenic Microorganisms and Natural Toxins Handbook, 2nd Edition.

### Internal Documentation

- `data/sources/sources.md` — Detailed source documentation
- `data/sources/extraction_notes.md` — Data extraction methodology
- `data/rag/README.md` — Quick reference for data files

---

*Last updated: 2026-03-13*
