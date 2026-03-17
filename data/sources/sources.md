# RAG Knowledge Base - Data Sources

This document tracks all official sources used to populate the RAG knowledge base for the Predictive Microbiology Translation Module.

---

## Primary Epidemiology Source

### CDC Scallan et al. 2011

| Field | Value |
|-------|-------|
| **Title** | Foodborne Illness Acquired in the United States—Major Pathogens |
| **Authors** | Elaine Scallan, Robert M. Hoekstra, Frederick J. Angulo, Robert V. Tauxe, Marc-Alain Widdowson, Sharon L. Roy, Jeffery L. Jones, Patricia M. Griffin |
| **Journal** | Emerging Infectious Diseases |
| **Volume/Issue** | Vol. 17, No. 1, January 2011 |
| **DOI** | 10.3201/eid1701.P11101 |
| **Publisher** | Centers for Disease Control and Prevention |
| **URL** | https://wwwnc.cdc.gov/eid/article/17/1/p1-1101_article |
| **Local File** | `data/sources/p1-1101-combined.pdf` |
| **Extraction Date** | 2026-03-12 |
| **Format** | PDF with Technical Appendices |
| **Status** | Authoritative - Official CDC peer-reviewed publication |

#### Data Extracted

| Table/Appendix | Content | Output File |
|----------------|---------|-------------|
| Table 2 | Annual illnesses by pathogen with 90% credible intervals | `pathogen_characteristics.csv` |
| Table 3 | Annual hospitalizations and deaths by pathogen | `pathogen_characteristics.csv` |
| Technical Appendix 1 | Transmission routes, percent foodborne, data sources | `pathogen_transmission_details.csv` |

#### Key Statistics (31 Pathogens, US 2006 population)

| Metric | Total | Top Contributors |
|--------|-------|------------------|
| **Annual Illnesses** | 9.4 million (90% CrI: 6.6-12.7M) | Norovirus 58%, Salmonella 11%, C. perfringens 10% |
| **Annual Hospitalizations** | 55,961 (90% CrI: 39,534-75,741) | Salmonella 35%, Norovirus 26%, Campylobacter 15% |
| **Annual Deaths** | 1,351 (90% CrI: 712-2,268) | Salmonella 28%, T. gondii 24%, Listeria 19%, Norovirus 11% |

#### Highest Case Fatality Rates (from Table 3)

| Pathogen | Death Rate | Annual Deaths | Notes |
|----------|------------|---------------|-------|
| Vibrio vulnificus | 34.8% | 36 | Highest CFR of any foodborne pathogen |
| Clostridium botulinum | 17.3% | 9 | Neurotoxin producer |
| Listeria monocytogenes | 15.9% | 255 | Third leading cause of death |
| Mycobacterium bovis | 4.7% | 3 | Unpasteurized dairy |
| Hepatitis A virus | 2.4% | 7 | Viral |
| Yersinia enterocolitica | 2.0% | 29 | Psychrotrophic |

#### Citation Format

**APA:**
```
Scallan, E., Hoekstra, R. M., Angulo, F. J., Tauxe, R. V., Widdowson, M. A., Roy, S. L., 
Jones, J. L., & Griffin, P. M. (2011). Foodborne illness acquired in the United States—
major pathogens. Emerging Infectious Diseases, 17(1), 7-15. 
https://doi.org/10.3201/eid1701.P11101
```

---

## Primary Food Safety Source

### IFT/FDA Report: Evaluation and Definition of Potentially Hazardous Foods

| Field | Value |
|-------|-------|
| **Title** | Evaluation and Definition of Potentially Hazardous Foods |
| **Authors** | Institute of Food Technologists Scientific and Technical Panel |
| **Publisher** | Comprehensive Reviews in Food Science and Food Safety, Vol. 2 (Supplement) |
| **Date** | December 31, 2001 (Published 2003) |
| **Commissioned by** | U.S. Food and Drug Administration (FDA) |
| **Contract** | IFT/FDA Contract No. 223-98-2333, Task Order No. 4 |
| **URL** | https://www.fda.gov/files/food/published/Evaluation-and-Definition-of-Potentially-Hazardous-Foods.pdf |
| **Local File** | `data/sources/Evaluation-and-Definition-of-Potentially-Hazardous-Foods.pdf` |
| **Access Date** | 2026-03-11 |
| **Format** | PDF (108 pages) |
| **Status** | Authoritative - FDA-commissioned peer-reviewed scientific report |

#### Data Extracted

| Table/Section | Content | Output File |
|---------------|---------|-------------|
| Table 3-1 | Water activity (aw) values for food categories | `food_properties.csv` |
| Table 3-2 | Minimum aw for pathogen growth | `pathogen_aw_limits.csv` |
| Table 3-3 | pH ranges of common foods | `food_properties.csv` |
| Table 1 | Pathogens of concern by food category | `pathogen_food_associations.csv` |
| Figure 1, Tables A & B | pH/aw interaction for TCS classification | `tcs_classification_tables.csv` |

---

## Derived Data: Food-Pathogen Hazard Mappings

### food_pathogen_hazards.csv

| Field | Value |
|-------|-------|
| **Purpose** | Direct mapping from specific foods to pathogens with official CDC metrics |
| **Derived From** | IFT/FDA Table 1 + CDC Scallan 2011 epidemiology data |
| **Records** | 60+ food-pathogen combinations |
| **Key Feature** | Enables "most dangerous pathogen for X" queries using official death rates |

#### Structure

| Column | Description |
|--------|-------------|
| food_name | Specific food item (e.g., "chicken raw", "oysters raw") |
| food_category | Category (meat, poultry, shellfish, etc.) |
| pathogen | Specific pathogen name |
| severity_score | 1-5 scale (5 = most dangerous) |
| mortality_rate | From Bad Bug Book |
| primary_hazard | "yes" if this is the primary concern for this food |
| control_methods | How to control this hazard |
| notes | Additional context |

#### How It Solves the "Most Dangerous" Query

**Query**: "What's the most dangerous pathogen for raw chicken?"

**RAG retrieval** returns multiple documents like:
```
Hazard for chicken raw: Listeria monocytogenes (severity 5/5, mortality 15-30%, secondary hazard)
Hazard for chicken raw: Salmonella spp. (severity 3/5, mortality <1%, primary hazard)
Hazard for chicken raw: Campylobacter jejuni (severity 2/5, mortality <1%, primary hazard)
```

**Answer**: Listeria monocytogenes is the most dangerous (severity 5, mortality 15-30%), though Salmonella and Campylobacter are more common (primary hazards).

---

## Tertiary Source

### FDA Bad Bug Book (2nd Edition)

| Field | Value |
|-------|-------|
| **Title** | Bad Bug Book: Foodborne Pathogenic Microorganisms and Natural Toxins Handbook |
| **Publisher** | U.S. Food and Drug Administration, Center for Food Safety and Applied Nutrition |
| **Edition** | 2nd Edition |
| **Date** | 2012 |
| **Editors** | Keith A. Lampel, Ph.D. (Editor); Sufian Al-Khaldi, Ph.D. (Co-editor); Susan Mary Cahill, B.S. (Co-editor) |
| **URL** | https://www.fda.gov/food/foodborne-pathogens/bad-bug-book-2nd-edition |
| **Local File** | `data/sources/Bad-Bug-Book-2nd-Edition-_PDF_.pdf` |
| **Extraction Date** | 2026-03-12 |
| **Format** | PDF |
| **Status** | Authoritative - Official FDA publication |

#### Data Extracted

| Content | Output File | Source Pages |
|---------|-------------|--------------|
| Pathogen growth parameters (temperature, pH, aw) | `pathogen_characteristics.csv` | Various chapters |
| Infectious doses | `pathogen_characteristics.csv` | Individual pathogen chapters |
| Mortality and hospitalization rates | `pathogen_characteristics.csv` | Individual pathogen chapters |
| Vulnerable population information | `pathogen_characteristics.csv` | Individual pathogen chapters |
| Special characteristics (psychrotrophic, spore-forming, toxin-producing) | `pathogen_characteristics.csv` | Individual pathogen chapters |

#### Pathogen Chapter Page References

| Pathogen | BBB Pages | Key Data Extracted |
|----------|-----------|-------------------|
| Salmonella spp. | 12-19 | Infective dose (as low as 1 cell), mortality <1%, typhoid 10% |
| Campylobacter jejuni | 20-25 | Infective dose 500-10000, Guillain-Barré risk 1/2000 |
| Yersinia enterocolitica | 26-31 | Psychrotrophic, pork association |
| Shigella spp. | 32-37 | Very low dose (10-100), Shiga toxin |
| Vibrio parahaemolyticus | 38-43 | Halophilic, aw min 0.94 |
| Cronobacter sakazakii | 50-55 | Neonatal mortality 40-80% |
| Vibrio vulnificus | 66-71 | 35% septicemia mortality, 10°C min temp |
| E. coli O157:H7 (EHEC) | 76-83 | Dose 10-100, HUS 3-5% mortality |
| Staphylococcus aureus | 122-129 | aw min 0.83, preformed toxin |
| Clostridium perfringens | 130-135 | Temp range 15-50°C, spore-forming |
| Bacillus cereus | 136-141 | Temp range 4-55°C, two toxin types |
| Listeria monocytogenes | 142-149 | Grows below 1°C, 15-30% case fatality |
| Clostridium botulinum | 158-165 | Nanogram toxin dose, 5-10% mortality |

#### Note on Extraction

The Bad Bug Book contains narrative descriptions of pathogen characteristics. Values were extracted via `pdftotext` and structured into CSV format. Severity scores (1-5 scale) were derived from:
- Mortality rate (highest weight): 5 = >10%, 4 = 3-10%, 3 = 1-3%, 2 = <1%
- Hospitalization rate: high = +1
- Infectious dose (lower = more dangerous): very low (<100) = +1
- Vulnerable population impact severity

#### Citation Format

**APA:**
```
Food and Drug Administration. (2012). Bad Bug Book: Foodborne Pathogenic Microorganisms 
and Natural Toxins Handbook (2nd ed.). Center for Food Safety and Applied Nutrition.
```

#### Citation Format

**APA:**
```
Institute of Food Technologists. (2003). Evaluation and definition of potentially 
hazardous foods. Comprehensive Reviews in Food Science and Food Safety, 2(Supplement), 
1-108. https://doi.org/10.1111/j.1541-4337.2003.tb00051.x
```

**Chicago:**
```
Institute of Food Technologists. "Evaluation and Definition of Potentially Hazardous 
Foods." Comprehensive Reviews in Food Science and Food Safety 2, Supplement (2003): 1-108.
```

---

## Secondary Source

### FDA/CFSAN: Approximate pH of Foods and Food Products

| Field | Value |
|-------|-------|
| **Title** | Approximate pH of Foods and Food Products |
| **Publisher** | FDA Center for Food Safety and Applied Nutrition (CFSAN) |
| **Date** | April 2007 |
| **Original URL** | http://www.cfsan.fda.gov/~comm/lacf-phs.html (archived) |
| **Archive URL** | https://www.healthycanning.com/wp-content/uploads/pH-FDAapproximatepHoffoodslacf-phs.pdf |
| **Local File** | `data/sources/pH-FDAapproximatepHoffoodslacf-phs.pdf` |
| **Access Date** | 2026-03-12 |
| **Format** | PDF (13 pages) |
| **Status** | Authoritative - Official FDA publication |

#### Data Extracted

| Content | Usage |
|---------|-------|
| pH values for ~400 foods | Primary source for `food_properties.csv` pH values |
| Comprehensive coverage of fruits, vegetables, dairy, meats, fish, shellfish, grains, condiments | Expanded from 92 to 259 food items |

#### Key Categories Added from FDA pH List

| Category | Items Added | Examples |
|----------|-------------|----------|
| Shellfish | 12 | conch, squid, octopus, mussels, scallops |
| Fish | 15 | bass, bluefish, codfish, flounder, haddock, mackerel, sardines |
| Fruits | 35 | avocados, blackberries, cherries, cranberry juice, guava, kumquat, lychee, nectarines, pomegranate |
| Vegetables | 45 | artichokes, bamboo shoots, beans (multiple types), cactus, fennel, hearts of palm, tomatillo |
| Grains | 12 | barley, oatmeal, rice (brown/white/wild), pasta types |
| Dairy | 8 | multiple cheese types, cream varieties, milk types |
| Condiments | 10 | chili sauce, curry paste, enchilada sauce, fish sauce, salsa, worcestershire |

#### Citation Format

**APA:**
```
U.S. Food and Drug Administration, Center for Food Safety and Applied Nutrition. (2007). 
Approximate pH of foods and food products. FDA/CFSAN.
```

---

## Source Evaluation Criteria

All sources included in this knowledge base meet the following criteria:

1. **Official/Government Source**: Published by or commissioned by FDA, USDA, or equivalent regulatory body
2. **Peer-Reviewed**: Reviewed by scientific experts in food safety/microbiology
3. **Citable**: Has clear authorship, publication date, and permanent reference
4. **Current**: Represents current scientific consensus (or explicitly dated historical data)
5. **Publicly Accessible**: Available without paywall for verification

---

## Sources NOT Used (and Why)

| Source | Reason for Exclusion |
|--------|---------------------|
| Wikipedia | Not primary source; may change |
| Blog posts / Extension websites | Secondary interpretations; may have errors |
| Textbooks (without page citation) | Cannot verify specific values |
| Training data knowledge | Not citable; cannot verify accuracy |
| ComBase database | Requires registration; data format not suitable for direct extraction |

---

## Planned Future Sources

| Source | Status | Data Type |
|--------|--------|-----------|
| USDA FSIS Directives | Not yet acquired | Meat/poultry safety parameters |
| Codex Alimentarius | Not yet acquired | International standards |
| ICMSF Books | Requires purchase | Comprehensive microbiology data |
| ComBase | Requires API integration | Growth/inactivation model parameters |

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-03-11 | Initial extraction from IFT/FDA report |
| 1.1 | 2026-03-12 | Added pathogen_characteristics.csv from Bad Bug Book; fixed CSV format (removed comment headers); added severity scoring for pathogen ranking |
| 1.2 | 2026-03-12 | Expanded food_properties.csv from 92 to 259 items using complete FDA pH list; added comprehensive shellfish, fish, fruits, vegetables, grains, condiments coverage |
| 1.3 | 2026-03-12 | Added food_pathogen_hazards.csv - denormalized table linking specific foods directly to pathogens with severity scores; enables "most dangerous pathogen for X" queries |

---

## Contact

For questions about data provenance or to report errors, contact the project maintainer.
