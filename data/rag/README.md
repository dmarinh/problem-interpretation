# RAG Data Files

This folder contains processed CSV files ready for ingestion into the RAG vector store.

## Files for RAG Ingestion

| File | Records | Description | Source |
|------|---------|-------------|--------|
| `food_properties.csv` | 259 | Food pH and water activity values | FDA-PH-2007, IFT-2003 |
| `pathogen_aw_limits.csv` | 14 | Pathogen growth limits (aw, temp) | IFT-2003-T32 |
| `pathogen_characteristics.csv` | 30 | CDC epidemiology (illnesses, deaths) - **merged 2019+2011** | CDC-2019-T1T2, CDC-2011-T3 |
| `pathogen_transmission_details.csv` | 27 | Transmission routes, % foodborne | CDC-2011-A1 |
| `pathogen_food_associations.csv` | 46 | Food category to pathogen mapping | IFT-2003-T1 |
| `food_pathogen_hazards.csv` | 60 | Direct food→pathogen→severity lookup | CDC-2011-T3 |
| `tcs_classification_tables.csv` | 25 | TCS classification rules (Tables A & B) | IFT-2003-TA/TB |

## Reference Files (NOT for RAG Ingestion)

These files are kept for historical reference and data provenance only. **Do not ingest into RAG.**

| File | Records | Description | Purpose |
|------|---------|-------------|---------|
| `pathogen_characteristics_cdc2019.csv` | 8 | CDC 2019 data only (7 major pathogens) | Reference extract |
| `pathogen_characteristics_cdc2011.csv` | 30 | CDC 2011 data only (31 pathogens) | Historical reference |

## Merged Pathogen Characteristics File

The primary `pathogen_characteristics.csv` contains **30 pathogens** with the most current data available:

| Data Year | Pathogens | Source |
|-----------|-----------|--------|
| **2019** | 8 pathogens | Scallan Walter et al. 2025 |
| **2011** | 22 pathogens | Scallan et al. 2011 |

**Columns added for provenance:**
- `data_year` — `2019` or `2011` indicating data vintage
- `notes` — Explains update status

**Key changes (2011 → 2019):**
- Campylobacter deaths: 76 → 197 (+159%)
- Salmonella deaths: 378 → 238 (-37%)
- Toxoplasma deaths: 327 → 44 (-87%)

## Source ID Convention

All files use standardized `source_id` column. See `../sources/source_references.csv` for full citations.

## Ingestion

Run: `python -m cli.rag_admin`

This will run the default bootstrap command, which automatically ingests all the RAG data sources into the vector store. Here are some of the other available options you can use with this script:

Load and clear existing data first: python -m cli.rag_admin --clear
Load and run test queries to verify: python -m cli.rag_admin --verify
Simply verify an already populated DB: python -m cli.rag_admin verify
Check stats containing document counts: python -m cli.rag_admin status

**Note:** The ingestion script should skip files matching `*_cdc2011.csv` and `*_cdc2019.csv` patterns.

## Document Format

Each CSV row is transformed into a semantic document with embedded source tag:

```
"Campylobacter spp.: 1,872,423 annual illnesses, 197 deaths, hospitalization rate 22.1% [CDC-2019-T1T2]"
"Vibrio vulnificus: 96 annual illnesses, 36 deaths, case fatality rate 34.8% [CDC-2011-T3]"
```
