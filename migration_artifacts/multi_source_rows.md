# Multi-Source Row Discovery Report

**Source file:** `data/rag/food_properties.csv`  
**Parser baseline:** `app/rag/data_sources/food_safety.py` (`_BRACKET_RE`, `_PROSE_RE`) — pattern equality asserted at runtime  
**Generated:** 2026-05-04  
**Purpose:** Enumerate every row where the ingestion-layer notes-parser extracts one or more source IDs from the `notes` field beyond what the `source_id` column declares. Input artifact for the per-field source attribution schema migration.

---

## 1. Summary

| Metric | Count |
|---|---|
| Total data rows | 252 |
| Single-source rows (column only, no extras) | 248 |
| Multi-source rows (column + parsed extras) | 4 |
| Rows with registry-rejected candidates (Section 3a) | 0 |
| Rows with attribution-ambiguous extras (Section 3b) | 0 |

## 2. Multi-source rows

Rows requiring per-field `ph_source_id` and `aw_source_id` columns in the migrated CSV schema. Review `proposed ph_source_id` and `proposed aw_source_id` and correct before migration.

| row_index | food_name | category | source_id (column) | parsed extras (from notes) | notes (raw text) | proposed ph_source_id | proposed aw_source_id |
|---|---|---|---|---|---|---|---|
| 14 | cheese parmesan | dairy | FDA-PH-2007 | IFT-2003-T31 | Hard aged cheese; pH from FDA-PH-2007, aw from IFT-2003-T31 Table 3-1 | FDA-PH-2007 | IFT-2003-T31 |
| 211 | bread white | grain | FDA-PH-2007 | IFT-2003-T31 | White bread; pH from FDA-PH-2007, aw 0.94-0.97 from IFT-2003-T31 Table 3-1 | FDA-PH-2007 | IFT-2003-T31 |
| 233 | honey | sweetener | FDA-PH-2007 | IFT-2003-T31 | Raw honey; pH from FDA-PH-2007, aw 0.75 from IFT-2003-T31 Table 3-1 | FDA-PH-2007 | IFT-2003-T31 |
| 234 | maple syrup | sweetener | FDA-PH-2007 | IFT-2003-T31 | Pure maple syrup; pH from FDA-PH-2007, aw 0.85 from IFT-2003-T31 Table 3-1 | FDA-PH-2007 | IFT-2003-T31 |

## 3. Ambiguous and failed rows

### 3a. Registry-rejected candidates

None. Every string that matched the regex in a notes field was found in `source_references.csv`.

### 3b. Attribution-ambiguous rows

None. For every multi-source row, the notes prose unambiguously attributed each extra source to a specific field (`pH from` / `aw … from` patterns resolved cleanly).

