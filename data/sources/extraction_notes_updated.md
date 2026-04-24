# RAG Knowledge Base — Extraction Notes

This document describes how data was extracted from source documents, any transformations applied, and known limitations.

---

## Extraction History

| Date | Action | By |
|------|--------|----|
| 2026-03-11 | Initial LLM extraction (Claude Opus 4.5) from all 5 source PDFs | Automated |
| 2026-04-17 | Full audit and correction pass | Claude Sonnet 4.6 (assisted) |

---

## Audit Summary (2026-04-17)

A systematic audit was conducted cross-checking all 7 CSV files against the 5 attached PDF source documents. The audit was performed by reading source tables directly from the PDFs and comparing each value with the corresponding CSV entry.

### Errors found

**food_properties.csv** had the most errors, consistent with the known LLM extraction failure modes identified in advance:

- **7 rows removed** (beef ripened, lamb, pork, turkey roasted, avocado vegetable duplicate, mayonnaise, salsa): these entries were not found in any of the 5 attached source documents. They were fabricated by the LLM from training data and incorrectly attributed to FDA-PH-2007.
- **Chicken pH corrected** from 6.5–6.7 (FDA-PH-2007) to **6.2–6.4 (IFT-2003-T33)**. This is the highest-impact single error: a 0.3 pH unit difference at pH 6.5 vs 6.2 changes predicted *Salmonella* and *Campylobacter* growth kinetics. The original value was from LLM training data, not any attached source.
- **4 WRONG_SOURCE corrections for meats**: butter, beef ground, ham, and veal all appear in IFT-2003 Table 3-3 with the correct values, but were attributed to FDA-PH-2007 (where they do not appear). This is classic LLM cross-source contamination—both PDFs were in the same context during extraction.
- **2 aw value corrections** (bread white min 0.93→0.94; maple syrup max 0.90→0.85): the LLM introduced small rounding errors in aw values and incorrectly attributed aw data to FDA-PH-2007, which does not contain any aw values at all.
- **4 source annotation fixes**: where a row has both pH (from FDA) and aw (from IFT), the notes field has been updated to clarify both sources, since the single `source_id` column cannot represent both.

**pathogen_aw_limits.csv**: one minor transcription note added for C. perfringens (optimum aw is a range 0.95–0.96 in source; CSV records only 0.95).

**pathogen_characteristics.csv**: all CDC 2011 values verified and correct. However, the file does **not** incorporate 2019 estimates from Scallan Walter et al. 2025, despite the source_references.csv containing entries for that source. A data_year column (specified in the schema) is absent. This remains an open item.

**pathogen_transmission_details.csv**: all 27 pathogen entries verified against CDC 2011 Technical Appendix 1. No errors found.

**tcs_classification_tables.csv, pathogen_food_associations.csv**: spot-checked against IFT-2003 Tables A, B, and 1. No errors found in verifiable portions.

**food_pathogen_hazards.csv**: `annual_deaths_us` values represent pathogen totals across all food sources, not food-specific deaths. This is not an extraction error but a potential interpretive issue for RAG queries about a specific food.

---

## File: `food_properties.csv`

### Source Tables
- **IFT-2003 Table 3-3** (p. 22): pH ranges of some common foods — MEATS, DAIRY, SOME FISH/SHELLFISH, SOME FRUITS/VEGETABLES
- **IFT-2003 Table 3-1** (p. 21): aw values of selected food categories
- **FDA pH List (FDA-PH-2007)**: Approximate pH of foods and food products (~400 foods, fruits/vegetables/seafood/grains/condiments) — **does not include raw meats (except a few seafood), and does not include aw values**

### Post-audit corrections (2026-04-17)
See `rag_audit_changelog.md` for full details. Net rows: 259 → 252.

### Known Limitations

1. **FDA pH list covers different foods than IFT Table 3-3**: The FDA list is stronger for fruits, vegetables, and seafood. IFT Table 3-3 is stronger for meats, poultry, dairy, and a smaller set of foods. When both sources exist for a food, they may give slightly different ranges because the underlying datasets differ.

2. **Chicken pH is now 6.2–6.4 (IFT)**: Note that some food science literature gives ranges as high as 6.5–6.7 for raw chicken at different stages post-slaughter. The IFT Table 3-3 value of 6.2–6.4 is the authoritative value for this knowledge base. If live queries require a broader range, an additional source should be identified.

3. **Raw meat gaps**: Lamb, pork, turkey, and beef ripened have been removed because no value was found in the attached source documents. A source such as USDA FoodData Central or ICMSF could provide these values in a future update.

4. **aw data is category-level**: Most aw values come from IFT Table 3-1 which gives categories (e.g., "fresh meat 0.99–1.00"), not food-specific values. The FDA pH list provides no aw data at all.

5. **Single source_id limitation**: Rows that have pH from one source and aw from another cannot be fully attributed in the current schema. Notes have been updated to flag these cases.

6. **No cooked/raw distinction for most foods**: Values are for the raw/natural state unless noted.

---

## File: `pathogen_aw_limits.csv`

### Source Table
- **IFT-2003 Table 3-2** (p. 22): Approximate aw values for growth of selected pathogens in food

### Post-audit corrections (2026-04-17)
One note updated (C. perfringens aw_opt). All other values verified correct.

### Known Limitations

1. **Solute-dependent**: aw limits vary with the humectant used. Values are general estimates.
2. **Temperature-dependent**: Values assume optimal temperature.

---

## File: `pathogen_characteristics.csv`

### Source
- **CDC 2011** (Scallan et al.): all 30 rows. Values verified correct.

### Open items (2026-04-17)
- 2019 estimates (Scallan Walter et al. 2025) not yet incorporated. Reference source CDC-2019-T1T2 is registered in source_references.csv but no rows use it.
- `data_year` and `notes` columns specified in schema are absent from this file.

---

## File: `pathogen_transmission_details.csv`

### Source
- **CDC 2011 Technical Appendix 1**: all 27 rows. Values verified correct.

---

## File: `pathogen_food_associations.csv`

### Source
- **IFT-2003 Table 1** (p. 11): Pathogens of concern and control methods

### Known Limitations
Full verification limited by PDF table structure (multi-cell entries with superscripts). Spot-checked entries appear correct.

---

## File: `tcs_classification_tables.csv`

### Source
- **IFT-2003 Tables A and B** (p. 13)

### Known Limitations
Full verification limited by PDF matrix layout. Spot-checked entries appear correct.

---

## File: `food_pathogen_hazards.csv`

### Sources
- Derived from IFT-2003 Table 1 + CDC 2011 Table 3
- `annual_deaths_us` = total US deaths from pathogen (all foods), not food-specific

### Known Limitations
1. Death values are pathogen totals, not food-specific.
2. Column names differ from documented schema.

---

## Recommended Process for Future Updates

1. **One PDF per extraction session**: never process multiple source PDFs in the same LLM context window. Cross-source contamination (IFT values attributed to FDA citations) is the most common error mode observed.

2. **Verification pass after extraction**: after LLM extraction, run a second LLM call with only the single source PDF, asking it to confirm each extracted value by quoting the exact source text.

3. **Human stratified spot-check**: minimum 5% sample across each source document and each food category. Specifically check: raw meats, fermented foods, condiments, and any food with pH near 4.6.

4. **Automated range checks before accepting output**: pH must be 0–14; aw must be 0–1.00; source_id must match a registered source.

5. **For aw data**: USDA FoodData Central provides food-specific aw measurements for many items and should be incorporated as a future source to replace the current category-level IFT estimates.
