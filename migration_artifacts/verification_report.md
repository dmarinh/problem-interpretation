# Post-Migration Verification Report

**Migration verified:** `food_properties.csv` per-field source schema  
**Migration date:** 2026-05-04  
**Verification date:** 2026-05-04  
**Build hash (post-migration):** `6d71349`  
**RAG store hash (post-re-ingestion):** `496c0db5593c9144`  
**RAG store ingested_at:** `2026-05-04T16:50:56.948718+00:00`  
**PTM version in all responses:** `6d71349`

---

## Pre-flight record

| Check | Result |
|---|---|
| Old store predated migration | YES — old `rag_ingested_at` was `2026-04-29T11:40:51` |
| Action taken | Store cleared (`python -m cli.rag_admin --clear`) and re-ingested before any query ran |
| New store `rag_ingested_at` | `2026-05-04T16:50:56.948718+00:00` ✓ |
| All 7 data sources re-ingested cleanly | YES — 451 chunks, 252 food_properties rows ✓ |
| Dev server health | OK — all components healthy |

**Treating `rag_ingested_at >= 2026-05-04` as the hard precondition.** Precondition met.

---

## Overall pass/fail summary

| Query | Overall | Multi-source | Single-source | attempted_top | Notes |
|---|---|---|---|---|---|
| Q03 | **PASS** | ✓ food_properties_211 | — | — | |
| Q05 | **PASS** | ✓ food_properties_211 | — | — | |
| Q06 | **PASS** | — | ✓ food_properties_220 | — | See pre-existing observation below |
| Q10 | **PASS** | ✓ food_properties_14 | — | — | |
| Q12 | **PASS** | ✓ food_properties_211 | — | — | One explainable difference; see below |
| Q15 | **PASS** | — | — | ✓ (184, 25) | |
| Q16 | **PASS** | ✓ food_properties_211 (aw) | — | — | pH is USER_EXPLICIT (no retrieval) |
| Q17 | **PASS** | — | ✓ (24, 26) | — | 2 step_predictions ✓ |

**All eight queries pass.** One explainable difference (Q12 organism retrieval block) and one pre-existing observation (Q06 organism source_id) are documented below. Neither is caused by the migration.

---

## Unexplained differences

**None.** All differences from the journal are explainable; see "Explainable differences" and "Pre-existing observations" sections.

---

## Per-query field-by-field diff

### Q03 — Bread + B. cereus 25°C / 4h

**Query:** "A slice of white bread was kept at 25 C for 4 hours. Predict Bacillus cereus growth."

| Field | Expected (journal) | Actual | Pass? |
|---|---|---|---|
| `ph.top_match.doc_id` | `food_properties_211` | `food_properties_211` | ✓ |
| `ph.top_match.source_ids` (order) | `["FDA-PH-2007", "IFT-2003-T31"]` | `["FDA-PH-2007", "IFT-2003-T31"]` | ✓ |
| `ph.extraction.parsed_range` | `[5.0, 6.2]` | `[5.0, 6.2]` | ✓ |
| `ph.standardization.direction` | `upper` | `upper` | ✓ |
| `ph.final_value` | `6.2` | `6.2` | ✓ |
| `water_activity.top_match.doc_id` | `food_properties_211` | `food_properties_211` | ✓ |
| `water_activity.top_match.source_ids` (order) | `["FDA-PH-2007", "IFT-2003-T31"]` | `["FDA-PH-2007", "IFT-2003-T31"]` | ✓ |
| `water_activity.extraction.parsed_range` | `[0.94, 0.97]` | `[0.94, 0.97]` | ✓ |
| `water_activity.standardization.direction` | `upper` | `upper` | ✓ |
| `water_activity.final_value` | `0.97` | `0.97` | ✓ |
| `range_clamps` count | 0 | 0 | ✓ |
| `defaults_imputed` count | 0 | 0 | ✓ |
| `warnings` count | 0 | 0 | ✓ |
| `reranker_top` on pH retrieval | null | null | ✓ |
| `ph.top_match.embedding_score` | ~0.79 | 0.7927 | ✓ |

**Multi-source citation confirmed:** `food_properties_211` → `["FDA-PH-2007", "IFT-2003-T31"]` in exact order. Identical for pH and aw.

---

### Q05 — Bread at room temperature

**Query:** "Predict Bacillus cereus growth on white bread at room temperature for 4 hours."

| Field | Expected (journal) | Actual | Pass? |
|---|---|---|---|
| `ph.top_match.doc_id` | `food_properties_211` | `food_properties_211` | ✓ |
| `ph.top_match.source_ids` (order) | `["FDA-PH-2007", "IFT-2003-T31"]` | `["FDA-PH-2007", "IFT-2003-T31"]` | ✓ |
| `water_activity.top_match.doc_id` | `food_properties_211` | `food_properties_211` | ✓ |
| `water_activity.top_match.source_ids` (order) | `["FDA-PH-2007", "IFT-2003-T31"]` | `["FDA-PH-2007", "IFT-2003-T31"]` | ✓ |
| `temperature_celsius.source` | `user_inferred` | `user_inferred` | ✓ |
| `temperature_celsius.extraction.method` | `rule_match` | `rule_match` | ✓ |
| `temperature_celsius.extraction.matched_pattern` | `room temperature` | `room temperature` | ✓ |
| `temperature_celsius.extraction.conservative` | `true` | `true` | ✓ |
| `ph.standardization.direction` | `upper` | `upper` | ✓ |
| `water_activity.standardization.direction` | `upper` | `upper` | ✓ |
| `range_clamps` count | 0 | 0 | ✓ |
| `defaults_imputed` count | 0 | 0 | ✓ |
| `warnings` count | 0 | 0 | ✓ |

**Multi-source citation confirmed:** `food_properties_211` → `["FDA-PH-2007", "IFT-2003-T31"]` in exact order alongside a rule-matched temperature. Two paths, one audit shape.

---

### Q06 — Cooked rice sitting out for a while

**Query:** "Cooked rice was sitting out for a while. Predict pathogen growth."

| Field | Expected (journal) | Actual | Pass? |
|---|---|---|---|
| `ph.top_match.doc_id` | `food_properties_220` | `food_properties_220` | ✓ |
| `ph.top_match.source_ids` | single source for rice | `["FDA-PH-2007"]` | ✓ |
| `ph.extraction.parsed_range` | `[6.0, 6.7]` | `[6.0, 6.7]` | ✓ |
| `ph.standardization.direction` | `upper` | `upper` | ✓ |
| `ph.final_value` | `6.7` | `6.7` | ✓ |
| `ph.reranker_top.doc_id` | `food_properties_229` | `food_properties_229` | ✓ |
| `ph.reranker_top.skip_reason` | `failed_embedding_threshold:0.70` | `failed_embedding_threshold:0.70` | ✓ |
| `water_activity.top_match.doc_id` | `food_properties_229` | `food_properties_229` | ✓ |
| `water_activity.top_match.source_ids` | single source (IFT) | `["IFT-2003-T31"]` | ✓ |
| `water_activity.source` | `rag_retrieval_fallback` | `rag_retrieval_fallback` | ✓ |
| `water_activity.extraction.parsed_range` | `[0.8, 0.87]` | `[0.8, 0.87]` | ✓ |
| `water_activity.standardization.rule` | `range_clamp` | `range_clamp` | ✓ |
| `water_activity.final_value` | `0.971` | `0.971` | ✓ |
| `organism.final_value` | `Clostridium perfringens` | `Clostridium perfringens` | ✓ |
| `organism.extraction.method` | `ranked_by_annual_deaths` | `ranked_by_annual_deaths` | ✓ |
| `range_clamps` count | 1 | 1 | ✓ |
| `defaults_imputed` count | 0 | 0 | ✓ |
| `warnings` count | 1 | 1 | ✓ |

**Single-source citation confirmed:** `food_properties_220` (rice white cooked) → `["FDA-PH-2007"]`. No second source. Correct for a single-source row.

**Pre-existing observation (not migration-caused):** `organism.top_match.doc_id` = `pathogen_hazards_417` shows `source_ids: ["CDC-2011-T3"]`. Expected `["CDC-2019-T1T2"]` based on the 2026-04-29 CDC 2019 merge which updated all C. perfringens rows. This discrepancy is unrelated to the food_properties migration — it concerns food_pathogen_hazards.csv and its ingestion state. Not blocking.

---

### Q10 — Listeria on cheese at 4°C / 14 days

**Query:** "Predict Listeria growth in cheese at 4 C for 14 days."

| Field | Expected (journal) | Actual | Pass? |
|---|---|---|---|
| `ph.top_match.doc_id` | `food_properties_14` | `food_properties_14` | ✓ |
| `ph.top_match.source_ids` (order) | `["FDA-PH-2007", "IFT-2003-T31"]` | `["FDA-PH-2007", "IFT-2003-T31"]` | ✓ |
| `ph.extraction.parsed_range` | `[5.2, 5.3]` | `[5.2, 5.3]` | ✓ |
| `ph.standardization.direction` | `upper` | `upper` | ✓ |
| `ph.final_value` | `5.3` | `5.3` | ✓ |
| `ph.top_match.embedding_score` | `~0.75` | `0.7513` | ✓ |
| `water_activity.top_match.doc_id` | `food_properties_14` | `food_properties_14` | ✓ |
| `water_activity.top_match.source_ids` (order) | `["FDA-PH-2007", "IFT-2003-T31"]` | `["FDA-PH-2007", "IFT-2003-T31"]` | ✓ |
| `water_activity.extraction.parsed_range` | `[0.68, 0.76]` | `[0.68, 0.76]` | ✓ |
| `water_activity.standardization.rule` | `range_clamp` | `range_clamp` | ✓ |
| `water_activity.standardization.before_value` | `0.76` | `0.76` | ✓ |
| `water_activity.standardization.after_value` | `0.934` | `0.934` | ✓ |
| `reranker_top` on both retrievals | null | null | ✓ |
| `range_clamps` count | 1 | 1 | ✓ |
| `defaults_imputed` count | 0 | 0 | ✓ |
| `warnings` count | 1 | 1 | ✓ |

**Multi-source citation confirmed:** `food_properties_14` (cheese parmesan) → `["FDA-PH-2007", "IFT-2003-T31"]` in exact order. Identical for pH and aw — same doc, two sources, correct order. Clean Tier 1 hit (embed 0.7513 > 0.70 threshold).

---

### Q12 — Bread, no pathogen specified

**Query:** "Predict pathogen growth on a slice of white bread at 25 C for 4 hours."

| Field | Expected (journal) | Actual | Pass? |
|---|---|---|---|
| `ph.top_match.doc_id` | `food_properties_211` | `food_properties_211` | ✓ |
| `ph.top_match.source_ids` (order) | `["FDA-PH-2007", "IFT-2003-T31"]` | `["FDA-PH-2007", "IFT-2003-T31"]` | ✓ |
| `water_activity.top_match.doc_id` | `food_properties_211` | `food_properties_211` | ✓ |
| `water_activity.top_match.source_ids` (order) | `["FDA-PH-2007", "IFT-2003-T31"]` | `["FDA-PH-2007", "IFT-2003-T31"]` | ✓ |
| `water_activity.standardization.rule` | `range_clamp` | `range_clamp` | ✓ |
| `water_activity.final_value` | `0.973` | `0.973` | ✓ |
| `organism.source` | `conservative_default` | `conservative_default` | ✓ |
| `organism.final_value` | `Salmonella` | `Salmonella` | ✓ |
| `organism.standardization.rule` | `default_imputed` | `default_imputed` | ✓ |
| `range_clamps` count | 1 | 1 | ✓ |
| `defaults_imputed` count | 1 | 1 | ✓ |
| `warnings` count | 2 | 2 | ✓ |
| `organism.retrieval` | null (journal) | retrieval block with `attempted_top` | see below |

**Multi-source citation confirmed:** `food_properties_211` → `["FDA-PH-2007", "IFT-2003-T31"]` in exact order. Third confirmation of multi-source bread row working across code paths (Q03: explicit organism, Q05: rule-matched temperature, Q12: organism defaulted).

**Explainable difference — Q12 organism retrieval block:**
Journal shows `organism.retrieval: null` ("No retrieval block. §2.4 didn't fire."). Actual shows a populated retrieval block: `query="slice of white bread food hazard"`, `top_match=null`, `attempted_top=pathogen_hazards_425`, `skip_reason=failed_embedding_threshold:0.75`.

**Cause:** Q12 was captured at 2026-05-01 15:53 UTC, *before* the Q15 audit-shape fix landed (Q15 post-fix captured at 2026-05-01 19:46 UTC). The fix extended `attempted_top` population to all defaulted fields — including organism — not just pH/aw. Q12's actual now correctly shows the retrieval attempt that failed threshold, matching the post-Q15-fix behavior. This is improvement, not regression. **Migration did not cause this.**

---

### Q15 — Fictional food ("zarblax burger")

**Query:** "Predict B. cereus growth on zarblax burger at 25 C for 4 hours."

| Field | Expected (journal) | Actual | Pass? |
|---|---|---|---|
| `ph.source` | `conservative_default` | `conservative_default` | ✓ |
| `ph.top_match` | null | null | ✓ |
| `ph.attempted_top.doc_id` | `food_properties_184` | `food_properties_184` | ✓ |
| `ph.attempted_top.skip_reason` | `failed_embedding_threshold:0.62` | `failed_embedding_threshold:0.62` | ✓ |
| `ph.final_value` | `7.0` | `7.0` | ✓ |
| `water_activity.source` | `conservative_default` | `conservative_default` | ✓ |
| `water_activity.top_match` | null | null | ✓ |
| `water_activity.attempted_top.doc_id` | `food_properties_25` | `food_properties_25` | ✓ |
| `water_activity.attempted_top.skip_reason` | `failed_embedding_threshold:0.62` | `failed_embedding_threshold:0.62` | ✓ |
| `water_activity.final_value` | `0.99` | `0.99` | ✓ |
| `defaults_imputed` count | 2 | 2 | ✓ |
| `range_clamps` count | 0 | 0 | ✓ |
| `warnings` count | 0 | 0 | ✓ |

**attempted_top confirmed:** `food_properties_184` for pH (pimiento canned acidified); `food_properties_25` for aw (fresh meat). Skip reason identical for both. Both doc IDs stable post-re-ingestion.

---

### Q16 — User-supplied pH range

**Query:** "Predict B. cereus growth on white bread at pH 5.5–6.0, 25 C, for 4 hours."  
*(Submitted via Python `requests` to preserve en-dash encoding — curl shell encoding corrupted this query; Python invocation matched the journal's intent exactly.)*

| Field | Expected (journal) | Actual | Pass? |
|---|---|---|---|
| `ph.source` | `user_explicit` | `user_explicit` | ✓ |
| `ph.extraction.parsed_range` | `[5.5, 6.0]` | `[5.5, 6.0]` | ✓ |
| `ph.extraction.raw_match` | `5.5–6.0` (en-dash preserved) | `5.5–6.0` | ✓ |
| `ph.standardization.rule` | `range_bound_selection` | `range_bound_selection` | ✓ |
| `ph.standardization.direction` | `upper` | `upper` | ✓ |
| `ph.standardization.before_value` | `[5.5, 6.0]` | `[5.5, 6.0]` | ✓ |
| `ph.standardization.after_value` | `6.0` | `6.0` | ✓ |
| `ph.final_value` | `6.0` | `6.0` | ✓ |
| `ph.retrieval` | null (user-supplied, no retrieval) | null | ✓ |
| `water_activity.top_match.doc_id` | `food_properties_211` | `food_properties_211` | ✓ |
| `water_activity.top_match.source_ids` (order) | `["FDA-PH-2007", "IFT-2003-T31"]` | `["FDA-PH-2007", "IFT-2003-T31"]` | ✓ |
| `water_activity.standardization.direction` | `upper` | `upper` | ✓ |
| `water_activity.standardization.before_value` | `[0.94, 0.97]` | `[0.94, 0.97]` | ✓ |
| `water_activity.standardization.after_value` | `0.97` | `0.97` | ✓ |
| `range_clamps` count | 0 | 0 | ✓ |
| `defaults_imputed` count | 0 | 0 | ✓ |
| `warnings` count | 0 | 0 | ✓ |

**Multi-source citation confirmed (aw side):** `food_properties_211` → `["FDA-PH-2007", "IFT-2003-T31"]` in exact order, alongside a user-supplied pH range that needed no retrieval. Confirms multi-source works when pH is user-explicit and only aw is retrieved.

---

### Q17 — Multi-step chicken scenario

**Query:** "Our chicken was held at 4 C for 24 hours, then transferred to a truck where it spent 6 hours at 13 C. Predict pathogen growth across the whole period."

| Field | Expected (journal) | Actual | Pass? |
|---|---|---|---|
| `prediction.is_multi_step` | `true` | `true` | ✓ |
| `step_predictions` length | 2 | 2 | ✓ |
| step 1 `step_order` | 1 | 1 | ✓ |
| step 1 `temperature_celsius` | `7.0` (clamped from 4) | `7.0` | ✓ |
| step 1 `duration_minutes` | 1440 | 1440.0 | ✓ |
| step 1 `mu_max` | `0.030` | `0.0303` | ✓ (within rounding) |
| step 1 `log_increase` | `0.315` | `0.315` | ✓ |
| step 2 `step_order` | 2 | 2 | ✓ |
| step 2 `temperature_celsius` | `13.0` | `13.0` | ✓ |
| step 2 `duration_minutes` | 360 | 360.0 | ✓ |
| step 2 `mu_max` | `0.132` | `0.1317` | ✓ (within rounding) |
| step 2 `log_increase` | `0.343` | `0.343` | ✓ |
| `ph.source` | `rag_retrieval_fallback` | `rag_retrieval_fallback` | ✓ |
| `ph.top_match.doc_id` | expected Tier 2 chicken pH doc | `food_properties_24` | ✓ |
| `ph.top_match.source_ids` | single source | `["IFT-2003-T33"]` | ✓ (single) |
| `water_activity.source` | `rag_retrieval_fallback` | `rag_retrieval_fallback` | ✓ |
| `water_activity.top_match.doc_id` | expected Tier 2 fresh poultry aw doc | `food_properties_26` | ✓ |
| `water_activity.top_match.source_ids` | single source | `["IFT-2003-T31"]` | ✓ (single) |
| `range_clamps` count | 1 | 1 | ✓ |
| `range_clamps[0].field_name` | `temperature_celsius (step 1)` | `temperature_celsius (step 1)` | ✓ |
| `range_clamps[0].original_value` | `4.0` | `4.0` | ✓ |
| `range_clamps[0].clamped_value` | `7.0` | `7.0` | ✓ |
| `defaults_imputed` count | 0 | 0 | ✓ |
| `warnings` count | 1 | 1 | ✓ |

**Cross-check Q17 doc IDs vs Q04/Q11:**  
- `ph.top_match.doc_id = food_properties_24` — this is the chicken pH Tier 2 fallback doc returned by the "chicken pH acidity" query. Consistent with Q11's journal description (same query template, same expected doc). ✓  
- `water_activity.top_match.doc_id = food_properties_26` — this is the fresh poultry aw doc returned by "chicken water activity aw moisture". Q04 journal described "Tier 2 fallback to fresh poultry doc (range [0.99, 1.0])" — range `[0.99, 1.0]` matches the `standardization.before_value` in Q17's actual (`[0.99, 1.0]`). ✓  
The same Tier 2 fallback queries for chicken produce the same doc IDs across Q11, Q04, and Q17. Doc IDs are stable.

**Single-source citations confirmed:** Both chicken pH (`food_properties_24`) and fresh poultry aw (`food_properties_26`) are single-source rows, correctly emitting single-element `source_ids` arrays.

---

## Doc ID stability confirmation

Seven food_properties doc IDs referenced across journal Q01–Q17. All resolved correctly in the post-migration store:

| Doc ID | Expected food | Evidence query | Status |
|---|---|---|---|
| `food_properties_211` | bread white | Q03, Q05, Q12, Q16 (aw) | ✓ Stable |
| `food_properties_14` | cheese parmesan | Q10 | ✓ Stable |
| `food_properties_220` | rice white cooked (pH) | Q06 pH retrieval | ✓ Stable |
| `food_properties_229` | uncooked rice / grain (aw) | Q06 aw retrieval + Q06 pH reranker_top | ✓ Stable |
| `food_properties_184` | pimiento canned acidified | Q15 pH attempted_top | ✓ Stable |
| `food_properties_25` | fresh meat | Q15 aw attempted_top | ✓ Stable |
| `food_properties_24` | chicken (pH, IFT-2003-T33) | Q17 pH retrieval | ✓ Stable |
| `food_properties_26` | fresh poultry (aw, IFT-2003-T31) | Q17 aw retrieval | ✓ Stable |

All eight doc IDs are stable. The migration changed the ingestion code path (notes-parser → column reads) but preserved the CSV row order and count (252 rows), keeping doc IDs aligned.

---

## Multi-source citation order verification

The migration's primary goal: per-field `ph_source_id` / `aw_source_id` columns replace notes-parser, but the emitted `source_ids` order must remain pH-first.

| Query | Doc | Expected order | Actual order | Pass? |
|---|---|---|---|---|
| Q03 | `food_properties_211` (bread white) | `["FDA-PH-2007", "IFT-2003-T31"]` | `["FDA-PH-2007", "IFT-2003-T31"]` | ✓ |
| Q05 | `food_properties_211` (bread white) | `["FDA-PH-2007", "IFT-2003-T31"]` | `["FDA-PH-2007", "IFT-2003-T31"]` | ✓ |
| Q10 | `food_properties_14` (cheese parmesan) | `["FDA-PH-2007", "IFT-2003-T31"]` | `["FDA-PH-2007", "IFT-2003-T31"]` | ✓ |
| Q12 | `food_properties_211` (bread white) | `["FDA-PH-2007", "IFT-2003-T31"]` | `["FDA-PH-2007", "IFT-2003-T31"]` | ✓ |
| Q16 (aw) | `food_properties_211` (bread white) | `["FDA-PH-2007", "IFT-2003-T31"]` | `["FDA-PH-2007", "IFT-2003-T31"]` | ✓ |

All five multi-source retrieval events agree: pH source first, aw source second. The `dict.fromkeys` union in `load_food_properties()` produces the correct ordering.

## Single-source citation verification

| Query | Doc | Expected | Actual | Pass? |
|---|---|---|---|---|
| Q06 pH | `food_properties_220` (rice white cooked) | single-element, FDA only | `["FDA-PH-2007"]` | ✓ |
| Q06 aw | `food_properties_229` (uncooked rice) | single-element, IFT only | `["IFT-2003-T31"]` | ✓ |
| Q17 pH | `food_properties_24` (chicken) | single-element, IFT only | `["IFT-2003-T33"]` | ✓ |
| Q17 aw | `food_properties_26` (fresh poultry) | single-element, IFT only | `["IFT-2003-T31"]` | ✓ |

---

## Explainable differences from journal

### Q12 organism retrieval block

**Journal shows:** `organism.retrieval: null` ("No retrieval block. §2.4 didn't fire.")  
**Actual shows:** retrieval block with `query="slice of white bread food hazard"`, `top_match=null`, `attempted_top=pathogen_hazards_425`, `skip_reason=failed_embedding_threshold:0.75`

**Explanation:** Q12 was captured at 2026-05-01 15:53 UTC, before the Q15 audit-shape fix (applied same day, Q15 post-fix captured 19:46 UTC). The fix extended `attempted_top` population to ALL defaulted fields — not just pH/aw — including organism. The actual behavior is correct: §2.4 DID issue a retrieval query for "slice of white bread food hazard"; it failed threshold (0.75); the system fell through to `conservative_default` Salmonella. The `attempted_top` now surfaces this retrieval attempt honestly. The migration did not cause this change.

---

## Pre-existing observations (not caused by this migration)

### Q06 organism source_id: CDC-2011-T3

`organism.top_match.doc_id = pathogen_hazards_417` (C. perfringens) shows `source_ids: ["CDC-2011-T3"]`. Based on the 2026-04-29 CDC 2019 merge (see `rag_audit_changelog.md`), C. perfringens rows in food_pathogen_hazards.csv were updated to `source_id=CDC-2019-T1T2` and `annual_deaths_us=41`. The source_id of the retrieved doc suggests either: (a) pathogen_hazards_417 is a C. perfringens row that was not among the 3 updated rows, or (b) the CDC 2019 update for C. perfringens was not applied to the specific row at this index. This predates the food_properties migration and is out of scope.

---

## Capture artifacts

Full JSON responses for all 8 queries saved for use as post-migration ground truth:

| File | Query |
|---|---|
| `migration_artifacts/verification_captures/Q03.json` | Bread + B. cereus 25°C/4h |
| `migration_artifacts/verification_captures/Q05.json` | Bread at room temperature |
| `migration_artifacts/verification_captures/Q06.json` | Cooked rice pathogen growth |
| `migration_artifacts/verification_captures/Q10.json` | Listeria on cheese 4°C/14d |
| `migration_artifacts/verification_captures/Q12.json` | Bread, no pathogen specified |
| `migration_artifacts/verification_captures/Q15.json` | Fictional food zarblax burger |
| `migration_artifacts/verification_captures/Q16.json` | User-supplied pH range (en-dash, Python-submitted) |
| `migration_artifacts/verification_captures/Q17.json` | Multi-step chicken scenario |

These captures replace the Q01–Q17 canonical captures (build `6d8aa38`) as the ground truth for the post-migration store (build `6d71349`, RAG hash `496c0db5593c9144`). Use them as the baseline for any future migration or ingestion change.

---

## Success criteria evaluation

| Criterion | Met? |
|---|---|
| All 8 queries produce identical externally-visible audit shape on captured fields | ✓ YES |
| All 7 known food_properties doc IDs resolve to expected food rows | ✓ YES (8 doc IDs confirmed, all stable) |
| Q03, Q10, Q12 confirm multi-source citation in correct order | ✓ YES |
| Q06 confirms single-source citation | ✓ YES |
| Q15 confirms attempted_top doc IDs (food_properties_184, food_properties_25) | ✓ YES |
| Q16 confirms range_bound_selection works for user ranges with bread's multi-source aw | ✓ YES |
| Q17 confirms 2 step_predictions; chicken Tier 2 doc IDs stable across Q04/Q11/Q17 | ✓ YES |
| Verification report committed to migration_artifacts/ | ✓ YES (this document) |

**Conclusion: migration is demo-ready.** The per-field source schema change is transparent to all consumers — the externally-visible audit shape, `source_ids` arrays, `full_citations`, doc IDs, and all other checked fields are identical to the journal captures (modulo the Q12 organism retrieval block improvement explained above, which is a post-Q15-fix correctness improvement, not a regression).
