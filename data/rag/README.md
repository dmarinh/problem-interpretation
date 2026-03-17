# RAG Data Files

This folder contains processed CSV files ready for ingestion into the RAG vector store.

## Files

| File | Records | Description | Source |
|------|---------|-------------|--------|
| `food_properties.csv` | 259 | Food pH and water activity values | FDA-PH-2007, IFT-2003 |
| `pathogen_aw_limits.csv` | 14 | Pathogen growth limits (aw, temp) | IFT-2003-T32 |
| `pathogen_characteristics.csv` | 30 | CDC epidemiology (illnesses, deaths) | CDC-2011-T3 |
| `pathogen_transmission_details.csv` | 27 | Transmission routes, % foodborne | CDC-2011-A1 |
| `pathogen_food_associations.csv` | 46 | Food category to pathogen mapping | IFT-2003-T1 |
| `food_pathogen_hazards.csv` | 60 | Direct food→pathogen→severity lookup | CDC-2011-T3 |
| `tcs_classification_tables.csv` | 25 | TCS classification rules (Tables A & B) | IFT-2003-TA/TB |

## Source ID Convention

All files use standardized `source_id` column. See `../sources/source_references.csv` for full citations.

## Ingestion

Run: `python scripts/bootstrap_rag.py --data-dir data/rag`

## Document Format

Each CSV row is transformed into a semantic document with embedded source tag:

```
"Vibrio vulnificus: 96 annual illnesses, 36 deaths, case fatality rate 34.8% [CDC-2011-T3]"
```
