# RAG Knowledge Base Audit Changelog

**Audit Date:** 2026-04-17  
**Auditor:** Claude Sonnet 4.6 (assisted audit against attached source PDFs)  
**Files audited:** 7 CSV files cross-checked against FDA-PH-2007, IFT-2003, CDC 2011, CDC 2025

---

## food_properties.csv — 17 changes (7 rows removed, 10 field corrections)

| # | Row (original) | food_name | Field | Old value | New value | Error type | Source basis |
|---|---|---|---|---|---|---|---|
| 1 | 0 | butter | source_id | FDA-PH-2007 | IFT-2003-T33 | WRONG_SOURCE | "Butter" not in FDA pH list; IFT Table 3-3 gives 6.1-6.4 |
| 2 | 21 | beef ground | source_id | FDA-PH-2007 | IFT-2003-T33 | WRONG_SOURCE | Ground beef not in FDA pH list; IFT Table 3-3 gives 5.1-6.2 (value correct) |
| 3 | 22 | beef ripened | ENTIRE ROW | pH 5.8-5.8, FDA-PH-2007 | REMOVED | NOT_IN_SOURCE | Aged/ripened beef absent from FDA pH list and IFT Table 3-3; LLM training data |
| 4 | 23 | ham | source_id | FDA-PH-2007 | IFT-2003-T33 | WRONG_SOURCE | Ham not in FDA pH list; IFT Table 3-3 gives 5.9-6.1 (value correct) |
| 5 | 24 | veal | source_id | FDA-PH-2007 | IFT-2003-T33 | WRONG_SOURCE | Veal not in FDA pH list; IFT Table 3-3 gives 6.0 (value correct) |
| 6 | 25 | lamb | ENTIRE ROW | pH 5.4-6.7, FDA-PH-2007 | REMOVED | NOT_IN_SOURCE | Raw lamb absent from FDA pH list and IFT Table 3-3; LLM training data |
| 7 | 26 | pork | ENTIRE ROW | pH 5.3-6.9, FDA-PH-2007 | REMOVED | NOT_IN_SOURCE | Raw pork absent from FDA pH list and IFT Table 3-3; LLM training data |
| 8 | 27 | chicken | ph_min, ph_max, source_id | pH 6.5-6.7, FDA-PH-2007 | **pH 6.2-6.4, IFT-2003-T33** | WRONG_VALUE + WRONG_SOURCE | Chicken not in FDA pH list. IFT Table 3-3 gives Chicken 6.2-6.4. CSV value 6.5-6.7 is from LLM training data. **HIGH IMPACT: Δ0.3 pH units, changes predicted growth rates.** |
| 9 | 28 | turkey roasted | ENTIRE ROW | pH 5.7-6.8, FDA-PH-2007 | REMOVED | NOT_IN_SOURCE | Turkey (roasted) absent from FDA pH list and IFT Table 3-3; LLM training data |
| 10 | 32 | fish fresh most | source_id | FDA-PH-2007 | IFT-2003-T33 | WRONG_SOURCE | Generic "Fish (most species) 6.6-6.8" is from IFT Table 3-3, not the FDA pH list |
| 11 | 72/130 | avocados (vegetable) | ENTIRE ROW | pH 6.27-6.58, FDA-PH-2007 (duplicate) | REMOVED | LLM_CONFLATION | Duplicate of fruit-category entry at row 72; avocado is a fruit |
| 12 | 247 | mayonnaise | ENTIRE ROW | pH 4.2-4.5, FDA-PH-2007 | REMOVED | NOT_IN_SOURCE | Mayonnaise absent from FDA pH list; LLM training data |
| 13 | 249 | salsa | ENTIRE ROW | pH 3.8-4.2, FDA-PH-2007 | REMOVED | NOT_IN_SOURCE | FDA pH list has "Salsa" entry with **no pH value**; LLM fabricated 3.8-4.2 |
| 14 | 14 | cheese parmesan | notes | "Hard aged cheese" | "Hard aged cheese; pH from FDA-PH-2007, aw from IFT-2003-T31 Table 3-1" | WRONG_SOURCE | FDA pH list provides pH only; aw 0.68-0.76 is from IFT-2003 Table 3-1. Schema allows only one source_id, so both sources noted in field. |
| 15 | 216 | bread white | aw_min, notes | aw_min=0.93 | **aw_min=0.94**; notes updated | TRANSCRIPTION + WRONG_SOURCE | IFT Table 3-1 gives white bread aw 0.94-0.97 (LLM wrote 0.93). FDA pH list has no aw data. |
| 16 | 238 | honey | notes | "Raw honey" | "Raw honey; pH from FDA-PH-2007, aw 0.75 from IFT-2003-T31 Table 3-1" | WRONG_SOURCE | FDA pH list provides pH only; aw 0.75 is from IFT-2003 Table 3-1. |
| 17 | 239 | maple syrup | aw_max, notes | aw_max=0.90 | **aw_max=0.85**; notes updated | WRONG_VALUE + WRONG_SOURCE | IFT Table 3-1 gives maple syrup aw=0.85 (single value). LLM widened to 0.85-0.90 from training data. FDA list has no aw data. |

**Summary:** 7 rows removed (beef ripened, lamb, pork, turkey roasted, avocados vegetable duplicate, mayonnaise, salsa). 10 field-level corrections. Net row count: 259 → 252.

---

## pathogen_aw_limits.csv — 1 note update

| # | food_name | Field | Old value | New value | Error type |
|---|---|---|---|---|---|
| 1 | Clostridium perfringens | notes | "Spore-forming" | "Spore-forming; aw_opt shown as lower bound of range 0.95-0.96 from source" | TRANSCRIPTION | IFT Table 3-2 gives optimum as "0.95 to 0.96"; CSV records only 0.95 |

---

## pathogen_characteristics.csv — No value corrections; 2 structural findings

**Finding 1 — Missing 2019 data:** All 30 rows use source_id `CDC-2011-T3`. The source_references.csv contains entries for CDC-2019-T1T2 and CDC-2019-A3 (Scallan Walter et al. 2025), but no row in pathogen_characteristics.csv references these sources. For 7 pathogens with updated 2019 estimates (Campylobacter, C. perfringens, L. monocytogenes, Norovirus, Salmonella nontyphoidal, STEC, Toxoplasma gondii), the data is significantly out of date. No correction made here because merging would require adding `data_year` and `notes` columns (schema change), which is outside the mandate of this audit.

**Finding 2 — Schema mismatch:** The documented schema specifies columns `data_year` and `notes` that are absent from the actual CSV. The actual CSV has extra columns (`illnesses_90pct_cri`, `hospitalizations_90pct_cri`, `deaths_90pct_cri`, `percent_travel_related`) not in the documented schema. The CDC 2011 values that ARE present have been verified as correct.

**2019 reference values for the 7 affected pathogens (for future update):**

| Pathogen | 2011 illnesses | 2019 illnesses | 2011 deaths | 2019 deaths | Source |
|---|---|---|---|---|---|
| Campylobacter spp. | 845,024 | 1,870,000 | 76 | 197 | CDC-2019-T1T2 |
| C. perfringens | 965,958 | 889,000 | 26 | 41 | CDC-2019-T1T2 |
| L. monocytogenes | 1,591 | 1,250 | 255 | 172 | CDC-2019-T1T2 |
| Norovirus | 5,461,731 | 5,540,000 | 149 | 174 | CDC-2019-T1T2 |
| Salmonella nontyphoidal | 1,027,561 | 1,280,000 | 378 | 238 | CDC-2019-T1T2 |
| STEC O157 | 63,153 | 86,200 | 20 | 40 | CDC-2019-T1T2 |
| Toxoplasma gondii | 86,686 (illnesses est.) | 848 hosp only | 327 | 44 | CDC-2019-T1T2 |

---

## pathogen_food_associations.csv — No corrections

Values verified against IFT-2003 Table 1 (text extraction partial due to PDF formatting). No errors identified in the content that could be verified.

---

## tcs_classification_tables.csv — No corrections

Values verified against IFT-2003 Tables A and B (text extraction partial). No errors identified in the verifiable portion.

---

## pathogen_transmission_details.csv — No corrections

Percent_foodborne values for 27 pathogens verified against CDC 2011 Table 2 and Technical Appendix 1. All values match.

---

## food_pathogen_hazards.csv — No value corrections; 1 methodological finding

**Finding — annual_deaths_us column is pathogen-total, not food-specific:** The value `annual_deaths_us` in every row reflects total US deaths from the pathogen across all food sources (e.g., 378 for all Salmonella deaths, not chicken-specific Salmonella deaths). This is not an extraction error—the value matches CDC 2011 Table 3—but it is potentially misleading in the context of a food-specific hazard lookup. The column should ideally be labelled `annual_deaths_us_all_foods` or the notes should clarify that it is a pathogen total, not a food-specific estimate.

**Additionally:** The actual column names (`case_fatality_rate`, `annual_deaths_us`, `source_id`) differ from the documented schema (`severity_score`, `mortality_rate`). This pre-existing inconsistency is not corrected here.

---

*This changelog was produced by cross-checking all CSV values against the 5 attached source PDFs: FDA-PH-2007, IFT-2003, CDC Scallan 2011, CDC Scallan Walter 2025, and FDA Bad Bug Book 2nd Edition.*

---

## Ingestion-layer workaround for multi-source rows (2026-04-27)

Rows whose `notes` field cite a secondary source (entries #14, #15, #16, #17 above) are handled at ingestion time: `load_food_properties()` parses `notes` for source IDs matching `[SOURCE-ID]` bracket style or `"from SOURCE-ID"` prose style, validates each candidate against `data/sources/source_references.csv`, and stores the union of the column `source_id` and any validated extras as a comma-separated string in the ChromaDB `source_id` metadata field.  This means retrieval audit blocks now report both sources (e.g., `source_ids: ["FDA-PH-2007", "IFT-2003-T31"]`) for multi-source rows.  Per-field attribution (which source supports pH vs aw) requires a schema migration and is explicitly deferred.
