# CSV Migration Diff — food_properties.csv

**Migration date:** 2026-05-04  
**From schema:** `food_name, food_category, ph_min, ph_max, aw_min, aw_max, notes, source_id`  
**To schema:** `food_name, food_category, ph_min, ph_max, ph_source_id, aw_min, aw_max, aw_source_id, notes`  

---

## 1. Summary

| Change | Value |
|---|---|
| Total rows | 252 |
| Single-source rows (ph_source_id = aw_source_id = old source_id) | 248 |
| Multi-source rows (per-field attribution from reviewed report) | 4 |
| Notes fields cleaned (attribution fragments stripped) | 4 |
| Columns added | 2 (`ph_source_id`, `aw_source_id`) |
| Columns removed | 1 (`source_id`) |
| Registry-rejected deferred rows | 0 |

**Information loss note:** The four multi-source rows' notes previously carried
table-level citation references (e.g., `IFT-2003-T31 Table 3-1`). The new schema
attributes at source_id level only; table-level granularity is not preserved. If
finer-grained citation is needed in future, that requires a separate schema extension
(e.g., a `ph_source_table` column).

## 2. Sample single-source rows (before / after)

Five representative rows showing the column rename from `source_id` to
per-field `ph_source_id` / `aw_source_id`. Notes are unchanged for all
single-source rows.

### row_index 0 — butter

**Before:**

| column | value |
|---|---|
| `food_name` | butter |
| `food_category` | dairy |
| `ph_min` | 6.1 |
| `ph_max` | 6.4 |
| `aw_min` | *(empty)* |
| `aw_max` | *(empty)* |
| `notes` | Fresh butter |
| `source_id` | IFT-2003-T33 |

**After:**

| column | value |
|---|---|
| `food_name` | butter |
| `food_category` | dairy |
| `ph_min` | 6.1 |
| `ph_max` | 6.4 |
| `ph_source_id` | IFT-2003-T33 |
| `aw_min` | *(empty)* |
| `aw_max` | *(empty)* |
| `aw_source_id` | *(empty)* |
| `notes` | Fresh butter |

### row_index 1 — buttermilk

**Before:**

| column | value |
|---|---|
| `food_name` | buttermilk |
| `food_category` | dairy |
| `ph_min` | 4.41 |
| `ph_max` | 4.83 |
| `aw_min` | *(empty)* |
| `aw_max` | *(empty)* |
| `notes` | Cultured |
| `source_id` | FDA-PH-2007 |

**After:**

| column | value |
|---|---|
| `food_name` | buttermilk |
| `food_category` | dairy |
| `ph_min` | 4.41 |
| `ph_max` | 4.83 |
| `ph_source_id` | FDA-PH-2007 |
| `aw_min` | *(empty)* |
| `aw_max` | *(empty)* |
| `aw_source_id` | *(empty)* |
| `notes` | Cultured |

### row_index 18 — natural cheeses

**Before:**

| column | value |
|---|---|
| `food_name` | natural cheeses |
| `food_category` | dairy |
| `ph_min` | *(empty)* |
| `ph_max` | *(empty)* |
| `aw_min` | 0.95 |
| `aw_max` | 1.0 |
| `notes` | Variable by type |
| `source_id` | IFT-2003-T31 |

**After:**

| column | value |
|---|---|
| `food_name` | natural cheeses |
| `food_category` | dairy |
| `ph_min` | *(empty)* |
| `ph_max` | *(empty)* |
| `ph_source_id` | *(empty)* |
| `aw_min` | 0.95 |
| `aw_max` | 1.0 |
| `aw_source_id` | IFT-2003-T31 |
| `notes` | Variable by type |

### row_index 19 — sweetened condensed milk

**Before:**

| column | value |
|---|---|
| `food_name` | sweetened condensed milk |
| `food_category` | dairy |
| `ph_min` | *(empty)* |
| `ph_max` | *(empty)* |
| `aw_min` | 0.83 |
| `aw_max` | 0.83 |
| `notes` | Shelf stable |
| `source_id` | IFT-2003-T31 |

**After:**

| column | value |
|---|---|
| `food_name` | sweetened condensed milk |
| `food_category` | dairy |
| `ph_min` | *(empty)* |
| `ph_max` | *(empty)* |
| `ph_source_id` | *(empty)* |
| `aw_min` | 0.83 |
| `aw_max` | 0.83 |
| `aw_source_id` | IFT-2003-T31 |
| `notes` | Shelf stable |

## 3. Multi-source rows (before / after)

All four rows identified in `migration_artifacts/multi_source_rows.md`.
Per-field source attribution comes from the reviewed `proposed ph_source_id`
and `proposed aw_source_id` columns. Notes attribution fragments are stripped.

### row_index 14 — cheese parmesan

**Before:**

| column | value |
|---|---|
| `food_name` | cheese parmesan |
| `food_category` | dairy |
| `ph_min` | 5.2 |
| `ph_max` | 5.3 |
| `aw_min` | 0.68 |
| `aw_max` | 0.76 |
| `notes` | Hard aged cheese; pH from FDA-PH-2007, aw from IFT-2003-T31 Table 3-1 |
| `source_id` | FDA-PH-2007 |

**After:**

| column | value |
|---|---|
| `food_name` | cheese parmesan |
| `food_category` | dairy |
| `ph_min` | 5.2 |
| `ph_max` | 5.3 |
| `ph_source_id` | FDA-PH-2007 |
| `aw_min` | 0.68 |
| `aw_max` | 0.76 |
| `aw_source_id` | IFT-2003-T31 |
| `notes` | Hard aged cheese |

### row_index 211 — bread white

**Before:**

| column | value |
|---|---|
| `food_name` | bread white |
| `food_category` | grain |
| `ph_min` | 5.0 |
| `ph_max` | 6.2 |
| `aw_min` | 0.94 |
| `aw_max` | 0.97 |
| `notes` | White bread; pH from FDA-PH-2007, aw 0.94-0.97 from IFT-2003-T31 Table 3-1 |
| `source_id` | FDA-PH-2007 |

**After:**

| column | value |
|---|---|
| `food_name` | bread white |
| `food_category` | grain |
| `ph_min` | 5.0 |
| `ph_max` | 6.2 |
| `ph_source_id` | FDA-PH-2007 |
| `aw_min` | 0.94 |
| `aw_max` | 0.97 |
| `aw_source_id` | IFT-2003-T31 |
| `notes` | White bread |

### row_index 233 — honey

**Before:**

| column | value |
|---|---|
| `food_name` | honey |
| `food_category` | sweetener |
| `ph_min` | 3.7 |
| `ph_max` | 4.2 |
| `aw_min` | 0.75 |
| `aw_max` | 0.75 |
| `notes` | Raw honey; pH from FDA-PH-2007, aw 0.75 from IFT-2003-T31 Table 3-1 |
| `source_id` | FDA-PH-2007 |

**After:**

| column | value |
|---|---|
| `food_name` | honey |
| `food_category` | sweetener |
| `ph_min` | 3.7 |
| `ph_max` | 4.2 |
| `ph_source_id` | FDA-PH-2007 |
| `aw_min` | 0.75 |
| `aw_max` | 0.75 |
| `aw_source_id` | IFT-2003-T31 |
| `notes` | Raw honey |

### row_index 234 — maple syrup

**Before:**

| column | value |
|---|---|
| `food_name` | maple syrup |
| `food_category` | sweetener |
| `ph_min` | 5.15 |
| `ph_max` | 5.15 |
| `aw_min` | 0.85 |
| `aw_max` | 0.85 |
| `notes` | Pure maple syrup; pH from FDA-PH-2007, aw 0.85 from IFT-2003-T31 Table 3-1 |
| `source_id` | FDA-PH-2007 |

**After:**

| column | value |
|---|---|
| `food_name` | maple syrup |
| `food_category` | sweetener |
| `ph_min` | 5.15 |
| `ph_max` | 5.15 |
| `ph_source_id` | FDA-PH-2007 |
| `aw_min` | 0.85 |
| `aw_max` | 0.85 |
| `aw_source_id` | IFT-2003-T31 |
| `notes` | Pure maple syrup |

## 4. Deferred for separate registry/data work

None. The discovery report (`migration_artifacts/multi_source_rows.md`)
found zero registry-rejected candidates in Section 3a. No rows required deferral.

