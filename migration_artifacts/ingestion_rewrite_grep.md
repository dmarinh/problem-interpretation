# Ingestion Rewrite Grep Audit

**Generated:** 2026-05-04  
**Scope:** `app/` and `tests/` Python files  
**Purpose:** Confirm all notes-parser symbols are deleted and per-field schema symbols land only where expected.

---

## Deleted symbols — must appear nowhere

| Symbol | Occurrences |
|---|---|
| `_BRACKET_RE` | 0 |
| `_PROSE_RE` | 0 |
| `_parse_extra_source_ids` | 0 |
| `import re` (in `food_safety.py`) | 0 |

---

## Retained symbols — expected locations only

### `_valid_source_ids`

| File | Line | Role |
|---|---|---|
| `app/rag/data_sources/food_safety.py` | 33 | definition (`@lru_cache`) |
| `app/rag/data_sources/food_safety.py` | 119 | called inside `load_food_properties` loop |
| `tests/unit/test_ingestion.py` | 199 | monkeypatched in `_patch()` helper |
| `tests/unit/test_ingestion.py` | 377 | monkeypatched in `test_row_count_sanity_check` |

### `EXPECTED_FOOD_PROPERTIES_COUNT`

| File | Line | Role |
|---|---|---|
| `app/rag/data_sources/food_safety.py` | 56 | constant definition (value: 252) |
| `app/rag/data_sources/food_safety.py` | 169 | sanity check condition |
| `app/rag/data_sources/food_safety.py` | 171, 173 | error message strings |
| `tests/unit/test_ingestion.py` | 198 | monkeypatched in `_patch()` helper |

### `ph_source_id` / `aw_source_id` (food_safety.py)

| Line | Usage |
|---|---|
| 109–110 | read from CSV row via `row.get("ph_source_id")` / `row.get("aw_source_id")` |
| 123, 128 | validation error messages (empty-source-id check) |
| 132, 137 | validation error messages (unknown-source-id check) |

---

## Residual `source_id` references in food_safety.py

Lines 216–526 reference a bare `source_id` column — these belong to the **other** loader functions in the same file (`load_pathogen_hazards`, `load_aw_limits`, `load_tcs_classification`, `load_source_references`, `load_regulatory_guidelines`). Those CSVs still use a single `source_id` column and were not part of this migration. No action required.

---

## Test suite result

`pytest` — 782 passed, 0 failed (run 2026-05-04).
