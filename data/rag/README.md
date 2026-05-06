# RAG Data Files

This folder contains processed CSV files ready for ingestion into the RAG vector store.

## Files for RAG Ingestion

| File | Records | Description | Source |
|------|---------|-------------|--------|
| `food_properties.csv` | 253 | Food pH and water activity values | FDA-PH-2007, IFT-2003 |
| `pathogen_aw_limits.csv` | 14 | Pathogen growth limits (aw, temp) | IFT-2003-T32 |
| `pathogen_characteristics.csv` | 30 | CDC epidemiology (illnesses, deaths) — 8 pathogens updated to 2019, 22 retain 2011 | CDC-2019-T1T2, CDC-2011-T3 |
| `pathogen_transmission_details.csv` | 27 | Transmission routes, % foodborne | CDC-2011-A1 |
| `pathogen_food_associations.csv` | 46 | Food category to pathogen mapping | IFT-2003-T1 |
| `food_pathogen_hazards.csv` | 56 | Direct food→pathogen→severity lookup | CDC-2019-T1T2, CDC-2011-T3 |
| `tcs_classification_tables.csv` | 25 | TCS classification rules (Tables A & B) | IFT-2003-TA/TB |

## Backup Files (NOT for RAG Ingestion)

Pre-modification snapshots kept for rollback. **Do not ingest into RAG.**

| File | Created | Purpose |
|------|---------|---------|
| `pathogen_characteristics_backup_20260429.csv` | 2026-04-29 | Pre-2019-merge snapshot |
| `food_pathogen_hazards_backup_20260429.csv` | 2026-04-29 | Pre-2019-merge snapshot |

## Pathogen Characteristics File — Data Vintage

`pathogen_characteristics.csv` contains **30 pathogens** with the most current data available. Contains `data_year` and `notes` columns for provenance.

| Data Year | Pathogens | Source |
|-----------|-----------|--------|
| **2019** | 8 pathogens (Campylobacter, C. perfringens, STEC O157, STEC non-O157, Listeria, Salmonella nontyphoidal, Toxoplasma, Norovirus) | Scallan Walter et al. 2025 (EID 31:4) |
| **2011** | 22 pathogens | Scallan et al. 2011 (EID 17:1) |

**Key changes applied (2011 → 2019):**
- Campylobacter deaths: 76 → 197 (+159%)
- Salmonella deaths: 378 → 238 (-37%)
- Toxoplasma deaths: 327 → 44 (-87%)
- Toxoplasma illnesses: retained as 2011 value (2019 paper did not estimate illnesses for Toxoplasma)

**food_pathogen_hazards.csv** `annual_deaths_us` column updated for the same 7 pathogens (40 rows).

## Source ID Convention

Most files use a standardized `source_id` column. `food_properties.csv` is the exception: it uses per-field `ph_source_id` and `aw_source_id` columns so that the authority for pH values and the authority for water activity values can differ. The ingestion loader merges these into a single comma-separated `source_id` in ChromaDB metadata (e.g., `"FDA-PH-2007,IFT-2003-T31"` for the 4 dual-source rows).

See `../sources/source_references.csv` for full citations.

## Ingestion

Run: `python -m cli.rag_admin`

This will run the default bootstrap command, which automatically ingests all the RAG data sources into the vector store. Here are some of the other available options you can use with this script:

Load and clear existing data first: python -m cli.rag_admin --clear
Load and run test queries to verify: python -m cli.rag_admin --verify
Simply verify an already populated DB: python -m cli.rag_admin verify
Check stats containing document counts: python -m cli.rag_admin status

**Note:** The ingestion script uses explicit file paths — backup files (`*_backup_*.csv`) and any other non-canonical CSVs in this directory are not ingested.

## Document Format

Each CSV row is transformed into a semantic document with embedded source tag:

```
"Campylobacter spp.: 1,872,423 annual illnesses, 197 deaths, hospitalization rate 22.1% [CDC-2019-T1T2]"
"Vibrio vulnificus: 96 annual illnesses, 36 deaths, case fatality rate 34.8% [CDC-2011-T3]"
```
