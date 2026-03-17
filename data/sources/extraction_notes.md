# RAG Knowledge Base - Extraction Notes

This document describes how data was extracted from source documents, any transformations applied, and known limitations.

---

## Extraction Date

**2026-03-11**

---

## File: `food_properties.csv`

### Source Tables
- **Table 3-1** (p. 21): "Approximate aw values of selected food categories"
- **Table 3-3** (p. 22): "pH ranges of some common foods"
- **FDA pH List** (supplementary): Approximate pH of Foods and Food Products

### Extraction Method
1. Manual transcription from PDF document
2. Cross-referenced values between tables where food items appeared in both
3. Standardized food names to lowercase with underscores

### Transformations Applied

| Transformation | Reason |
|----------------|--------|
| Food names normalized | Original had inconsistent capitalization |
| Ranges preserved as min/max | Enables range-based queries |
| Category field added | Groups related foods for retrieval |
| Empty values for missing data | Some foods have pH but no aw, or vice versa |

### Known Limitations

1. **Incomplete aw coverage**: Table 3-1 provides category-level aw (e.g., "fresh meat 0.99-1.00") rather than specific food aw
2. **pH ranges are approximate**: Document explicitly states "considerable variation exists between varieties, condition of growing and processing methods"
3. **Limited condiment data**: IFT/FDA report focused on TCS foods; condiments supplemented from FDA pH list
4. **No cooked food distinction**: Most values are for raw/fresh state; cooked foods may differ

### Data Quality Flags

| Food Item | Issue | Mitigation |
|-----------|-------|------------|
| maple syrup | aw estimated from similar products | Marked in notes column |
| condiments | From secondary source | Marked with "FDA pH list" in source_table |

---

## File: `pathogen_aw_limits.csv`

### Source Table
- **Table 3-2** (p. 22): "Approximate aw values for growth of selected pathogens in food"

### Extraction Method
1. Direct transcription from table
2. Preserved exact values as published

### Transformations Applied

| Transformation | Reason |
|----------------|--------|
| Pathogen names standardized | Consistent formatting |
| ">0.99" preserved as text | Cannot represent in numeric field |
| Separate rows for S. aureus growth vs toxin | Different aw limits for each |

### Known Limitations

1. **Solute-dependent**: Document notes aw limits vary with different humectants (e.g., NaCl vs glycerol)
2. **Temperature-dependent**: Values assume optimal temperature; limits change at suboptimal temps
3. **Strain variation**: Values are general; specific strains may differ

### Important Notes from Source

> "It should be noted that many bacterial pathogens are controlled at water activities well above 0.86 and only S. aureus can grow and produce toxin below aw 0.90."

> "When formulating foods using aw as the primary control mechanism for pathogens, it is useful to employ microbiological challenge testing to verify the effectiveness of the reduced aw when target aw is near the growth limit for the organism of concern."

---

## File: `tcs_classification_tables.csv`

### Source Tables
- **Table A** (p. 13): "Control of spores: Product treated to control vegetative cells and protected from recontamination"
- **Table B** (p. 13): "Control of vegetative cells and spores: Product not treated or treated but not protected from recontamination"

### Extraction Method
1. Converted 2D matrix format to flat CSV rows
2. Each cell in original matrix becomes one row
3. Added aw and pH range boundaries explicitly

### Transformations Applied

| Transformation | Reason |
|----------------|--------|
| Matrix → rows | Enables database queries |
| "?" symbol → "PA" | Product Assessment required (per document text) |
| Boundary values explicit | Original used category labels only |

### Classification Definitions

| Classification | Meaning |
|----------------|---------|
| Non-TCS | Food does NOT require time/temperature control for safety |
| PA | Product Assessment required - may or may not be TCS |
| TCS | Food REQUIRES time/temperature control for safety |

### Usage Notes

1. **Table A** applies when: Food was heat-treated to destroy vegetative cells AND packaged to prevent recontamination
2. **Table B** applies when: Food was NOT treated OR was treated but NOT protected from recontamination
3. **PA classification**: Food should be treated as TCS until product assessment demonstrates safety

---

## File: `pathogen_food_associations.csv`

### Source Table
- **Table 1** (p. 11): "Pathogens of concern and control methods for various product categories"

### Extraction Method
1. Expanded multi-pathogen cells into individual rows
2. Preserved control methods as semicolon-separated list
3. Captured footnotes as notes

### Transformations Applied

| Transformation | Reason |
|----------------|--------|
| One row per pathogen-food pair | Enables specific queries |
| Control methods as list | Multiple methods often apply |
| Footnote indicators resolved | Replaced superscripts with inline notes |

### Footnotes Preserved

| Original | Resolved Note |
|----------|---------------|
| Superscript 2 | "Only concern in anoxic environments" (C. botulinum) |
| Superscript 4 | "In pasteurized products, all pre-processing vegetative pathogens would be controlled" |
| Superscript 5 | "Only a concern in anoxic environments" (spores) |

---

## General Notes

### What Was NOT Extracted

1. **Chapter text/prose**: Only structured tables were extracted
2. **References/citations**: Available in source document
3. **Challenge testing protocols**: Chapters 6-7 contain protocols but not structured data
4. **Product-specific case studies**: Chapter 8 examples not suitable for RAG

### Validation Performed

1. Spot-checked 10 random values against source PDF
2. Verified pH ranges align between Table 3-3 and FDA pH list where overlapping
3. Confirmed pathogen aw limits match values cited in Chapter 3 prose

### Recommended Validation Before Production

1. [ ] Independent review of all extracted values against source
2. [ ] Cross-reference with additional sources (ICMSF, ComBase)
3. [ ] Consult food microbiologist for edge cases
4. [ ] Add confidence scores to values with high variability

---

## Update Procedure

When updating this knowledge base:

1. Document new source in `sources.md`
2. Add extraction notes to this file
3. Mark extraction date on all new data
4. Preserve original data files before overwriting
5. Update version history in `sources.md`
