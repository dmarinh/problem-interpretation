# Sensitivity Analysis Query Design: Methodology and Representative Scenarios

## 1. User Classification Assessment

The proposed classification — **risk assessors, regulators, industry operators** — is a reasonable starting point but requires refinement. Based on how ComBase and predictive microbiology tools are actually used (as documented by ComBase's own stated use cases: food safety plans, HACCP plans, risk assessment, and food waste reduction), and the user categories identified in the project documentation, I propose the following revised classification:

### 1.1 Proposed User Categories

**Category A: Risk Assessors / Researchers**
These are scientists conducting formal Quantitative Microbiological Risk Assessments (QMRA). They work in government agencies (FDA, EFSA, FSANZ), universities, or contract research organisations. They typically have strong microbiology backgrounds and are familiar with predictive modelling concepts. Their queries tend to be more technical but still involve interpretation decisions (which pathogen to model, which model to use, how to handle data gaps). They are the most technically sophisticated users but still face ambiguity in scenario parameterisation.

**Category B: Regulatory Inspectors / Enforcement Officers**
These are field-level personnel from agencies like USDA-FSIS, local health departments, or EU Member State competent authorities. They encounter food safety deviations in real time during inspections — a broken cold chain, a temperature log showing excursions, a process deviation. Their queries are typically time-pressured and framed around specific incidents. They may have food science training but are not modelling specialists. This is a distinct category from "risk assessors" because their context, time pressure, and level of technical vocabulary are fundamentally different.

**Category C: Industry HACCP / Quality Assurance Personnel**
These are food safety managers, quality assurance technicians, or HACCP coordinators working within food manufacturing, processing, distribution, or retail/foodservice. They use predictive models to validate HACCP plans, assess the safety of process deviations, evaluate shelf life, and make accept/reject decisions on product batches. Their queries are the most operational and often the most ambiguous, because they arise from real production incidents where information is incomplete. This is where the highest volume of queries comes from in practice.

**Category D: Educators / Students (excluded from the core study)**
While your project documentation lists this as a user category, I recommend **excluding** them from the sensitivity analysis study. Their queries would introduce noise — they are learning, not making real decisions, and their variability reflects pedagogical context rather than genuine operational ambiguity. Mention them in the paper as a secondary audience but do not include them in the core variance decomposition.

### 1.2 Rationale for the Revised Classification

The key distinction between categories is not just "who they are" but **what decision they are making** and **under what constraints**:

| Category | Decision context | Time pressure | Technical depth | Ambiguity source |
|----------|-----------------|---------------|-----------------|------------------|
| A: Risk Assessors | Formal QMRA, policy | Low (weeks-months) | High | Scenario definition, data gaps |
| B: Inspectors | Incident response, compliance | High (minutes-hours) | Medium | Incomplete field data, vague reports |
| C: Industry QA | Batch disposition, HACCP deviation | Medium (hours-days) | Medium-Low | Production incidents, missing logs |

This classification matters for the sensitivity analysis because **the nature of ambiguity differs systematically across categories**, and you want to show that your system handles all three types.

---

## 2. Methodology for Query Design

### 2.1 Step-by-step approach

**Step 1: Source prioritisation.** Queries should be drawn from real-world sources wherever possible, in the following priority order:

1. **Published outbreak investigation reports** (CDC MMWR, EFSA outbreak reports, FDA recall notices) — these describe actual incidents with the imprecise language used by investigators
2. **Regulatory guidance documents** that contain worked examples (FDA Food Code, USDA-FSIS guidelines, HACCP guidance documents) — these contain canonical scenarios used in training
3. **Published risk assessments** that describe exposure scenarios (FDA/FSIS Listeria risk assessment, FAO/WHO Salmonella risk assessment) — these describe the parameterisation decisions risk assessors actually face
4. **Industry training materials and case studies** (e.g., from IFST, IFT short courses, FSPCA training) — these contain realistic scenarios designed to exercise decision-making
5. **Expert-constructed queries** (designed by the researcher based on domain knowledge) — used only when the above sources do not adequately cover a needed scenario type

**Step 2: Define the ambiguity dimensions.** Each query should contain at least one, and ideally two or more, of the following ambiguity types that your system is designed to resolve:

| Dimension | Description | Example |
|-----------|-------------|---------|
| **Hidden pH/aw** | Food is named but physicochemical properties are not stated | "chicken breast" without specifying pH 5.9–6.2 |
| **Vague temperature** | Temperature described qualitatively | "room temperature", "left in the car", "warm day" |
| **Vague duration** | Duration described imprecisely | "overnight", "a few hours", "most of the afternoon" |
| **Missing pathogen** | No specific organism mentioned | "Is it safe?" without naming a target hazard |
| **Optimistic bias potential** | Range given, where operator might choose favourable end | "between 8 and 15°C" |
| **Scenario type ambiguity** | Unclear whether growth, inactivation, or survival is the concern | "I reheated it but I'm not sure it got hot enough" |
| **Multi-step complexity** | Multiple time-temperature conditions in sequence | "Delivered cold, then sat on the counter, then refrigerated again" |

**Step 3: Minimum sample size.** For the paired human-vs-system study (Approach B), you need sufficient queries per category to detect meaningful differences in parameterisation variance. A power analysis depends on the expected effect size, but as a practical minimum for a pilot study publishable in a food safety journal:

- **Minimum 10 queries per user category** — this provides enough scenarios to compute meaningful coefficients of variation across participants
- **Target 15 queries per category** — provides better statistical power and allows dropping queries that prove uninformative
- **Each query should be parameterisable** — meaning it must lead to a ComBase model execution, not just an information request

For the Sobol sensitivity analysis (Approach A), the same queries can be used, but each query will be run multiple times with distributions assigned to each uncertain input. A minimum of 15–20 queries total (across categories) is standard for this type of analysis.

**Step 4: Balance across food types, pathogens, and scenario types.** The query set should cover:

- **Food types**: Meats (poultry, beef, pork), seafood, dairy, produce, composite/prepared foods, RTE foods
- **Scenario types**: Storage abuse, cooking adequacy, cooling deviations, cross-contamination, transport chain breaks
- **Pathogens (implied)**: Salmonella, Listeria monocytogenes, E. coli O157:H7, Clostridium perfringens, Staphylococcus aureus, Bacillus cereus — covering the major hazards
- **Ambiguity types**: Each ambiguity dimension should appear in at least 3 queries

**Step 5: Validate with domain experts.** Before using the queries in the study, have 2–3 food safety professionals review them for realism and representativeness. This is a standard practice in survey/scenario design and will strengthen the publication.

### 2.2 Rationale for this approach

The alternative — inventing all queries from scratch — would be methodologically weaker for three reasons. First, it introduces researcher bias: you would unconsciously design queries that your system handles well. Second, it lacks ecological validity: real-world food safety questions have a particular texture, vocabulary, and pattern of omission that is hard to replicate synthetically. Third, reviewers and the advisory board will ask "are these realistic?" and having sourced queries from published documents provides an immediate answer.

However, a purely literature-sourced approach is also insufficient, because published sources tend to use cleaner, more complete language than real operators use. The ideal approach is a **hybrid**: start from real documented scenarios and then deliberately degrade them — remove stated pH values, replace precise temperatures with vague descriptions, introduce the kind of imprecision that real users would bring. Each modification should be documented.

---

## 3. Representative Query Sets

### 3.1 Category A: Risk Assessors / Researchers

These queries reflect the types of exposure scenarios that risk assessors must parameterise when conducting formal QMRA. The ambiguity here is not in the language (which is relatively technical) but in the **scenario definition decisions**: which pathogen, which food matrix properties, which time-temperature profile to assume.

---

**A1. Ready-to-eat deli meat cold chain assessment**

> "We need to model L. monocytogenes growth in vacuum-packed sliced turkey deli meat during retail display. Assume typical retail refrigeration. The product has a 35-day shelf life. What growth can we expect?"

- **Source basis**: FDA/FSIS (2003) *Quantitative Assessment of Relative Risk to Public Health from Foodborne Listeria monocytogenes Among Selected Categories of Ready-to-Eat Foods*. The risk assessment models the exposure pathway for deli meats through retail storage. This query reflects a typical parameterisation task from that assessment.
- **Ambiguity dimensions**: Vague temperature ("typical retail refrigeration" — 4°C? 7°C? With excursions?), hidden aw (vacuum-packed turkey, not specified), duration stated but long (growth dynamics over 35 days are complex)
- **Parameterisation challenge for humans**: "Typical retail" varies enormously — FDA surveys show retail display temperatures range from 1°C to 10°C with a median around 4.4°C but a long upper tail. The risk assessor must decide whether to use the median, the 95th percentile, or a distribution.

**Insights after testing**

- What we learned: The system needed to understand three things — the pathogen, the storage temperature, and the time. It got the pathogen right immediately. The temperature ("typical retail refrigeration") was treated as 4°C, which is the standard fridge setpoint but is more optimistic than what real retail surveys show; we kept the value but flagged this as a scientific decision worth revisiting. The biggest issue was the time: the system didn't recognise "35-day shelf life" as a duration at all in its first form, and when we rephrased it to "for 35 days" it got the arithmetic wrong by a factor of 20

- What we fixed: We rewrote the instructions the system gives itself when reading user queries, with worked examples showing how to handle days, weeks, and shelf-life phrasings. We also added a safety check that warns when the system sees a number-and-unit phrase but fails to extract it.

- What this taught us: The fix relies on the AI model being capable enough to follow the instructions properly. We tested both GPT-4o (a frontier commercial model) and Gemma 4 (a smaller open-source model). GPT-4o now handles "35 days" → 50,400 minutes correctly. Gemma 4 still failed on the same input even after the fix — it returned no value at all rather than a wrong one, but either way the user gets no useful answer. This means the choice of underlying AI model matters: smaller open models are not yet reliable enough for this kind of precise quantitative work. The system is also now honest about how it got each value — when the AI inferred a number from context, the audit says so, instead of pretending the user typed it.

---

**A2. Salmonella in ground beef — consumer handling**

> "For the exposure assessment, we need to estimate Salmonella growth on ground beef from purchase to cooking. The consumer picks it up at the supermarket, drives home — assume a typical shopping trip — and stores it in the home refrigerator. Model the growth during the transport and home storage segments separately."

- **Source basis**: Adapted from USDA-FSIS (1998/2001) *Draft Risk Assessment of the Public Health Impact of Escherichia coli O157:H7 in Ground Beef*, and Cassin et al. (1998) *Quantitative risk assessment for Escherichia coli O157:H7 in ground beef hamburgers*. Both risk assessments required assumptions about consumer transport and home storage.
- **Ambiguity dimensions**: "Typical shopping trip" (20 minutes? 90 minutes? What ambient temperature?), "home refrigerator" (actual consumer fridges vary 2–10°C), pH and aw of ground beef not specified
- **Parameterisation challenge for humans**: Transport time and temperature data come from survey data with wide distributions. The risk assessor must make an explicit modelling choice about whether to use point estimates or distributions, and which percentile.


**Insights after testing**

- What we learned: Real risk-assessment queries often contain vague segments — phrases like "typical shopping trip" that experienced humans interpret loosely but the system cannot. The query failed because the transport leg had no usable duration. Worse, the failure response used to hide everything else the system had resolved successfully, leaving the user with no way to see what was working and what wasn't.
- What we fixed: Two things. First, the failure response now shows every field the system attempted, including the missing one — so the user can see clearly what to provide. Second, descriptive temperature phrases like "home refrigerator" now resolve through a deterministic rule list rather than the AI sometimes guessing 4°C from world knowledge — the answer is the same but the system can now explain consistently how it got there.
- What this taught us: The system works well when queries are precise, but it has no graceful path for vague segments. A future improvement would be to either ask the user for missing pieces conversationally, or to map common vague phrases ("shopping trip", "during transport") to defensible default values from published exposure-assessment studies.

---

**A3. Clostridium perfringens in institutional cooling**

> "Model C. perfringens growth during cooling of a large batch of cooked beef stew. The stew is at about 60°C at the end of cooking and needs to reach refrigeration temperature. We want to verify that the USDA cooling requirement is met — no more than 1 log increase of C. perfringens."

- **Source basis**: USDA-FSIS Stabilization Guidelines (Appendix B), which explicitly use ComBase C. perfringens Predictor for validating cooling processes. The 1-log criterion is the regulatory standard. School HACCP guidance from USDA also uses this exact scenario type. (USDA-FSIS, 2017, *FSIS Stabilization/Cooling Guideline for Meat and Poultry Products*)
- **Ambiguity dimensions**: Starting temperature is approximate ("about 60°C"), cooling profile is unspecified (linear? exponential? depends on container size, depth, cooling method), target endpoint not given precisely ("refrigeration temperature" — 4°C? 7°C?)
- **Parameterisation challenge for humans**: The cooling curve shape is critical. Real-world cooling is non-linear and depends on batch size, container type, ambient temperature, and whether active cooling is used. The operator must decide whether to model this as a single step, a linear decline, or a stepped profile.

---

**A4. Cross-contamination from raw poultry to RTE salad**

> "Estimate the risk from Salmonella transferred from raw chicken to a ready-to-eat salad via a cutting board in a domestic kitchen. Assume the salad is consumed within two hours of preparation. What bacterial load can we expect on the salad at consumption?"

- **Source basis**: FAO/WHO (2002) *Risk Assessments of Salmonella in Eggs and Broiler Chickens*; also Pérez-Rodríguez et al. (2008) *Quantitative Microbiological Risk Assessment for Salmonella in lettuce*. Cross-contamination transfer rates and subsequent growth on produce are core exposure assessment components.
- **Ambiguity dimensions**: Transfer rate from board to food (highly variable, 0.01%–10% in literature), salad temperature during the 2 hours (room temperature? served immediately from fridge?), salad pH/aw (mixed salad — lettuce pH ~6.0 but with dressing?), which Salmonella serovar
- **Parameterisation challenge for humans**: Cross-contamination modelling requires multiple assumptions that are often unstated. The risk assessor may default to conservative transfer rates without checking the literature, or may not account for growth on the salad during the 2-hour holding period.

---

**A5. Vibrio parahaemolyticus in oysters — harvest to consumption**

> "We're assessing V. parahaemolyticus risk in raw oysters harvested from a warm-water estuary in summer. Oysters are harvested in the morning, transported in ice to the processing plant, shucked, packed, and shipped to retail. Model the growth from harvest through consumption."

- **Source basis**: FDA (2005) *Quantitative Risk Assessment on the Public Health Impact of Pathogenic Vibrio parahaemolyticus in Raw Oysters*. This is one of the most detailed published QMRAs in food safety, and the scenario described is its core pathway.
- **Ambiguity dimensions**: "Warm-water estuary in summer" (28°C? 32°C? Varies by geography), harvest-to-ice time not specified, ice transport temperature assumed but not stated, post-shucking temperature chain incomplete, "consumption" timing undefined
- **Parameterisation challenge for humans**: Water temperature at harvest is the critical parameter and varies enormously. The risk assessor must decide on a representative value or distribution, and the Vibrio models are highly sensitive to initial temperature.

---

**A6. Listeria in soft cheese — pH evolution during ripening**

> "We need to assess whether L. monocytogenes can grow in a surface-ripened soft cheese during its shelf life. The cheese starts at pH 4.6 after production, but the surface pH rises during ripening. Storage is under standard retail conditions."

- **Source basis**: Adapted from FAO/WHO (2004) *Risk Assessment of Listeria monocytogenes in Ready-to-Eat Foods* and Schvartzman et al. (2011) *Modelling the fate of L. monocytogenes during manufacture and ripening of smeared cheese*. The pH evolution in surface-ripened cheeses is a well-known challenge for predictive modelling.
- **Ambiguity dimensions**: Initial pH stated but surface pH trajectory during ripening is not (can rise from 4.6 to 7.0+), aw not given, "standard retail conditions" is vague, which Listeria model applies (with or without lactic acid bacteria competition?)
- **Parameterisation challenge for humans**: This is a genuinely difficult scenario because the environment changes over time. The assessor must decide whether to model growth at the initial pH (conservative for Listeria? No — low pH inhibits growth) or at the final pH (which promotes growth). The correct answer involves a dynamic model, but most users will default to a single condition.

---

**A7. Bacillus cereus spore germination in cooked rice**

> "Cooked rice is held at a buffet for service. The rice was cooked to above 95°C, cooled to serving temperature, and placed on a heated display. We need to assess B. cereus risk assuming the rice is held for the service period."

- **Source basis**: This is a classic food safety scenario from the FDA Bad Bug Book (2012, 2nd edition) and is commonly used in HACCP training. B. cereus in rice is one of the most frequently cited examples in food safety textbooks.
- **Ambiguity dimensions**: "Serving temperature" not specified (warm buffet — 50°C? 60°C? Below 60°C is the danger zone), "service period" duration not given (1 hour? 4 hours?), cooling step before display is vague ("cooled to serving temperature" — how fast?), spore vs. vegetative cell dynamics
- **Parameterisation challenge for humans**: The critical question is whether the holding temperature is above or below the B. cereus growth range. Hot-held rice at 63°C+ is safe; at 50°C it is in the danger zone. An operator who assumes "warm display = hot enough" may dramatically underestimate risk.

---

**A8. E. coli O157:H7 survival in fermented sausage**

> "Evaluate the survival of E. coli O157:H7 during the manufacture of a dry fermented sausage. The product undergoes fermentation at around 24°C for two days, then drying at 13°C for three weeks. Final product pH is about 4.8 and water activity around 0.90."

- **Source basis**: Adapted from multiple published risk assessments and USDA-FSIS compliance guidelines for fermented sausages following the 1994 Jack in the Box outbreak. USDA-FSIS requires establishments to demonstrate a 5-log reduction of E. coli O157:H7 in fermented sausages.
- **Ambiguity dimensions**: Fermentation temperature is approximate ("around 24°C"), pH trajectory during fermentation not given (only final pH), aw trajectory not given (only final), initial contamination level not stated, competition from starter cultures not modelled
- **Parameterisation challenge for humans**: This is a survival/inactivation scenario, not a growth scenario, and the model type selection is non-trivial. The pH and aw change dynamically during fermentation. Users must decide whether to model the final conditions (underestimates survival during fermentation) or attempt a multi-step profile.

---

**A9. Staphylococcus aureus toxin production in custard**

> "A bakery produced custard-filled pastries. Due to an equipment failure, the filled pastries were held at ambient temperature for several hours before refrigeration. Assess whether S. aureus toxin production could have occurred."

- **Source basis**: S. aureus toxin production in custard and cream-filled pastries is a well-documented outbreak scenario, described in FDA's HACCP guidance Chapter 12 (*Pathogenic Bacteria Growth and Toxin Formation as a Result of Time and Temperature Abuse*) and multiple FDA Food Code references.
- **Ambiguity dimensions**: "Ambient temperature" (bakery kitchen — could be 25°C to 35°C), "several hours" (2? 6?), custard formulation determines pH and aw but is not specified, toxin production threshold (~10⁶ CFU/g) requires growth estimation
- **Parameterisation challenge for humans**: The concern is not just growth but toxin production, which requires reaching a threshold population. The operator must estimate both the growth rate and the time to reach toxigenic levels. "Several hours" is critically ambiguous — 3 hours vs. 6 hours may be the difference between safe and unsafe.

---

**A10. Salmonella in peanut butter — low aw survival**

> "We're evaluating the risk of Salmonella in peanut butter with a water activity of 0.20–0.30. The product has a 12-month shelf life at ambient storage. What survival and potential for growth should we model?"

- **Source basis**: The 2008–2009 Peanut Corporation of America Salmonella outbreak (CDC MMWR reports), which resulted in 714 illnesses and 9 deaths, made this a landmark risk assessment scenario. Survival of Salmonella in low-aw products is well-documented.
- **Ambiguity dimensions**: aw range given (0.20–0.30, but growth models typically do not cover this range — below minimum aw for Salmonella growth), "ambient storage" temperature, the key question is survival not growth (model type selection), 12-month duration is outside typical model validation ranges
- **Parameterisation challenge for humans**: This scenario tests whether the user recognises that no growth is expected (aw is far below the Salmonella minimum of ~0.94) but that survival occurs. The model type selection is the critical decision: running a growth model would give a misleading result.

---

### 3.2 Category B: Regulatory Inspectors / Enforcement Officers

These queries reflect real-time field situations where inspectors must make rapid assessments with incomplete information. The language is less technical and the information gaps are larger.

---

**B1. Cold chain break during transport — poultry**

> "During a routine inspection of a poultry distribution truck, I found the refrigeration unit had failed. The driver says it broke down about two hours ago. The truck thermometer reads 12°C now but we don't know what it was when it failed. The load is fresh chicken portions. Should I reject the load?"

- **Source basis**: This type of scenario is described in FDA Food Code Chapter 3 (Time/Temperature Control for Safety) and USDA-FSIS Compliance Guidance for Controlling Listeria monocytogenes in Post-Lethality Exposed Ready-to-Eat Meat and Poultry Products. Temperature abuse during transport is one of the most common inspection findings.
- **Ambiguity dimensions**: Temperature trajectory unknown (only current reading of 12°C), "about two hours" is imprecise, starting temperature unknown (was truck at 4°C before failure?), chicken portions (skin-on? boneless? affects surface exposure), no pathogen specified
- **Parameterisation challenge for humans**: The inspector must reconstruct a plausible temperature profile from a single data point. Most will either assume worst case (12°C for 2 hours) or try to estimate a ramp. The optimistic bias is strong — the driver has an incentive to understate the duration, and the inspector may give benefit of the doubt.

**Insights after testing**

- What we learned: The system handled the inspector's narrative well — it pulled the current truck temperature and the rough exposure duration straight from the language, retrieved chicken pH and water activity from the right reference sources, and produced a small predicted growth (about a tenth of a log) consistent with what food scientists would expect from a brief excursion at this temperature. Two things stood out. The pathogen field was filled by the system's "conservative default" rather than by a hazard lookup, but by coincidence the default value (Salmonella) is also the correct primary hazard for chicken — the underlying hazard retrieval narrowly missed its threshold and the right chicken-hazard documents came back as runners-up rather than as the chosen answer. And the truck broke down at some point during the past two hours, yet the system treated the whole window as if the chicken had sat at the current reading the entire time, which is a worst-case reading rather than an honest reflection of the unknown trajectory.

- What we fixed: Nothing this round. Both observations belong to work already filed elsewhere. The hazard-retrieval threshold is part of the retrieval calibration study that's underway and will set thresholds against ground-truth queries instead of the current hand-set value. The flat-versus-ramp trajectory is the planned multi-step scenario work, where the system would split a narrative like this into a cold-start segment and a warm-end segment instead of collapsing them into one block.

- What this taught us: Realistic inspector queries describe events with a hidden time-temperature shape — "broke down two hours ago" implies a cold start, a current end-state, and an unknown ramp between. The system currently collapses this into a single worst-case step, and on this query that produces a defensible answer, but it does so silently; a more honest version would either ask the inspector for the most likely trajectory or report best-case and worst-case predictions side by side. The query also exercised a known scope boundary: the inspector is asking "should I reject this load?" and the system can only answer "here is the predicted growth". Translating that prediction into a yes/no verdict is the next module's job.




---



**B2. Restaurant hot-holding deviation**

> "At a restaurant inspection, the chicken soup on the hot-holding line measured 48°C. The cook says it's been on the line since the start of lunch service, roughly two and a half hours. The soup was boiled before service."

- **Source basis**: FDA Food Code §3-501.16 specifies that TCS food must be held at 57°C (135°F) or above. This type of finding is among the most common critical violations cited in restaurant inspections. CDC epidemiological data identifies improper hot holding as a leading contributing factor to foodborne outbreaks.
- **Ambiguity dimensions**: Temperature at 48°C now, but what was the trajectory? ("Since start of lunch" — was it ever at correct hot-holding temperature?), "roughly two and a half hours" is imprecise, soup formulation (pH, aw) unknown, which pathogen is the concern? (C. perfringens is the primary hot-holding hazard, but Salmonella and S. aureus are also relevant)
- **Parameterisation challenge for humans**: The inspector must decide whether the food entered the danger zone gradually (cooling from proper hot-hold) or was placed at 48°C initially. The difference matters enormously for growth estimation. The 4-hour FDA Food Code time limit for TCS foods in the danger zone creates a regulatory decision framework, but the inspector still needs to estimate whether pathogens have reached unsafe levels.

**Insights after testing**

- What we learned: This query is built around a soup sitting at 48°C — too cold for safe hot-holding, too warm for safe storage — and the system's read of it surfaced three problems that compound. First, it picked Salmonella as the pathogen, because Salmonella is the system's fall-back when nothing better can be found, but the textbook concern at this temperature for a previously-boiled product is Clostridium perfringens (and to a lesser extent Staphylococcus aureus and Bacillus cereus) — sporeformers that survive boiling and germinate during slow cooling. The cook's mention that the soup was boiled before service is a strong cue toward those pathogens, but the system has no way to read the cue. Second, the requested temperature of 48°C falls outside the Salmonella growth model's valid range (which tops out at 40°C), so the system clamped the temperature down to 40°C. The clamp does get flagged, but it isn't honest about the fact that 40°C happens to be near Salmonella's optimum, while 48°C in reality is above it — so the predicted growth at the clamped temperature is faster than what would actually happen at the real temperature. The combination is awkward: the system reports a worrying growth number, but the pathogen and the temperature it modelled both differ from the physical scenario in ways the user has to reconstruct from the audit. Third, three of the five model inputs (the pathogen, the pH, and the water activity) were filled by the system's conservative defaults rather than from any evidence about chicken soup. The composite-food matching — "chicken soup" against the reference rows for "chicken" and "fresh poultry" — fell just below the retrieval thresholds, so the chicken-specific pH and water activity were not picked up even though they exist in the reference data.

- What we fixed: Nothing this round. Each finding belongs to work already on the roadmap. The composite-food retrieval gap is part of the retrieval calibration study underway, which will set thresholds against ground-truth queries. Scenario-aware pathogen selection (recognising that a hot-holding deviation calls for sporeformer hazards rather than the raw-food hazard list) is a future enhancement that does not yet have a design. The most actionable item is a top-level warning that fires when most of a prediction's inputs come from conservative defaults rather than from evidence — so that a user reading "1.9 log of Salmonella growth" can see at a glance that the prediction is built mainly on assumptions. That warning is already in the plan and this query is the clearest argument we have for prioritising it.

- What this taught us: When several defaults stack, the prediction at the bottom of the audit can look authoritative even though almost none of it is grounded. The system's audit transparently records each individual default, but it does not yet add up "this prediction is mostly assumption" into a single signal at the top. The query also showed that the system's pathogen-selection logic is food-centric — it picks the most common hazard for the named food in its raw state — and not scenario-centric. A cooked, then mishandled, product has different relevant hazards from the same product in its raw form, and the system currently cannot see the difference. Finally, the temperature-range clamp is a useful safety mechanism but it can quietly distort the meaning of a prediction when the clamp moves the modelled temperature toward or away from the chosen pathogen's growth optimum — the warning text should eventually say something about the direction of that distortion, not just that a clamp happened.

---

**B3. School cafeteria cooling failure**

> "A school cafeteria prepared a large batch of chili for tomorrow's lunch. When the night manager came in, the chili was found sitting on the counter — it hadn't been put in the walk-in cooler. It's been about five hours since cooking. The kitchen temperature is about 22 degrees."

- **Source basis**: This scenario is directly based on school HACCP guidance from USDA. C. perfringens in improperly cooled foods is the primary hazard in institutional settings. CDC reports that C. perfringens caused ~10% of domestically acquired foodborne illnesses (Scallan et al., 2011).
- **Ambiguity dimensions**: "About five hours" and "about 22 degrees" are both imprecise, starting temperature after cooking not stated (could be anywhere from 60°C to 80°C), container size and depth affect cooling rate, chili formulation (pH, aw) not specified, pathogen not named
- **Parameterisation challenge for humans**: This is a classic cooling scenario where C. perfringens is the primary concern. The operator must decide whether to model it as a single-step hold at 22°C for 5 hours (worst case) or try to model the cooling curve from cooking temperature. The latter requires assumptions about container size and ambient conditions that the inspector does not have.

---

**B4. Dairy processing deviation**

> "During a dairy plant inspection, I found that a batch of pasteurised milk was held in a balance tank at 8°C for approximately 6 hours before further processing, instead of being processed immediately. The plant says the milk was properly pasteurised. Is the batch still safe?"

- **Source basis**: Regulatory guidance on post-pasteurisation contamination and temperature control from FDA Grade "A" Pasteurized Milk Ordinance (PMO). Holding at elevated temperatures post-pasteurisation is a known risk factor for Listeria and psychrotrophic pathogen growth.
- **Ambiguity dimensions**: "Approximately 6 hours" and 8°C (above standard refrigeration), post-pasteurisation contamination risk uncertain (L. monocytogenes is the primary concern but recontamination depends on plant hygiene), milk pH (~6.6–6.8) and aw (~0.997) are relatively standard but not stated
- **Parameterisation challenge for humans**: The inspector must assess whether growth of post-pasteurisation contaminants (primarily L. monocytogenes) during the 6-hour hold at 8°C is significant. The answer depends on the assumed initial contamination level, which is unknown.

---

**B5. Retail display of smoked salmon**

> "On inspection, a deli counter was displaying smoked salmon that had been out for an unspecified time. The store manager says it was put out 'this morning'. The display case was not refrigerated — it was on ice, but the ice had mostly melted. I measured the fish surface at 11°C."

- **Source basis**: Smoked salmon and Listeria is a well-documented food safety concern, referenced extensively in the FAO/WHO Listeria risk assessment and in EU Regulation (EC) No 2073/2005 on microbiological criteria for foodstuffs.
- **Ambiguity dimensions**: Duration is vague ("this morning" — 2 hours? 6 hours?), temperature trajectory unknown (started on ice at ~0°C, now at 11°C), product specifications (hot-smoked vs. cold-smoked — very different pH and aw profiles), pathogen not specified (Listeria is the primary concern for smoked salmon)
- **Parameterisation challenge for humans**: The inspector must reconstruct the temperature history. Cold-smoked salmon typically has pH 5.8–6.3 and aw 0.96–0.97, making it highly supportive of Listeria growth. The transition from iced (~0°C) to 11°C creates a multi-step temperature profile that is difficult to parameterise without knowing the rate of ice melt.

---

**B6. Power outage at a supermarket**

> "A supermarket reported a power outage lasting approximately 3 hours. The backup generator failed to start. The manager says the refrigerated display cases were closed and 'stayed pretty cold'. I measured several products and got readings from 7 to 14°C. The store has a mixed display of dairy, deli meats, and fresh produce."

- **Source basis**: Power outage food safety guidance is provided by both FDA (Food Code) and USDA-FSIS (consumer guidance). This scenario represents one of the most common real-world food safety emergencies that inspectors face.
- **Ambiguity dimensions**: "Approximately 3 hours" is imprecise, temperature range is wide (7–14°C), multiple product categories with different risk profiles, starting temperatures unknown, "stayed pretty cold" is subjective and unreliable, no pathogen specified, must assess multiple product-pathogen combinations
- **Parameterisation challenge for humans**: This is a particularly challenging scenario because it requires multiple model runs for different products and pathogens, and the temperature trajectory is highly uncertain. Different products in the same case may have been at different temperatures depending on their position and thermal mass.

---

**B7. Thawing practice violation**

> "During an inspection at a catering company, I found several large frozen turkey breasts thawing on the counter. The kitchen staff said they were taken out of the freezer 'first thing this morning' — it's now mid-afternoon. The surface temperature reads 18°C but the core is still frozen."

- **Source basis**: Improper thawing is one of the CDC-identified contributing factors to foodborne outbreaks. FDA Food Code §3-501.13 specifies acceptable thawing methods. Counter-thawing of poultry is a frequently cited violation.
- **Ambiguity dimensions**: Duration from "first thing this morning" to "mid-afternoon" (~6–8 hours?), surface at 18°C but core frozen means a non-uniform temperature distribution, turkey breast pH and aw not stated, the pathogen concern (Salmonella on poultry surface), the differential surface/core temperature creates a modelling challenge
- **Parameterisation challenge for humans**: The critical zone is the surface, which has been in the danger zone for an unknown duration while the core remained frozen. Standard predictive models assume uniform temperature. The inspector must decide whether to model at the surface temperature for the full duration (very conservative) or try to account for the gradual warming.

---

**B8. Seafood processing — temperature deviation during brining**

> "At a smoked fish processor, I found that the brine tank temperature had risen to 15°C during an overnight brining step. The fish (salmon fillets) were in the brine for about 12 hours. Normal brining temperature should be below 5°C. The brine concentration is 'standard' according to the plant manager."

- **Source basis**: FDA Fish and Fishery Products Hazards and Controls Guidance, Chapter 12 (temperature abuse). This scenario combines temperature deviation with ambiguous product conditions.
- **Ambiguity dimensions**: "About 12 hours" is imprecise, brine concentration is vague ("standard" — 3.5%? 10%? 21%? Salt concentration determines aw), whether the temperature rose gradually or was at 15°C for the full period is unknown, starting fish temperature not given
- **Parameterisation challenge for humans**: Brine concentration is critical because it determines both aw and the pathogen growth potential. A saturated brine at 26% NaCl gives aw ~0.75 (inhibitory), while a light brine at 3.5% gives aw ~0.97 (growth-permissive). The inspector may not know how to convert salt percentage to water activity, which is exactly the kind of conversion your system is designed to handle.

---

**B9. Egg product handling at a breakfast buffet**

> "At a hotel breakfast buffet inspection, I found scrambled eggs at 52°C on the hot line. The chef says they were freshly made 'about an hour ago' and the warmer has been on the whole time. The eggs look and smell fine."

- **Source basis**: FDA Food Code §3-501.16(A)(1) requires hot holding at 57°C/135°F minimum. Scrambled eggs at hotel buffets are a common source of Salmonella outbreaks (CDC data).
- **Ambiguity dimensions**: "About an hour" is imprecise, eggs at 52°C (below safe hot-holding), unknown whether eggs started at proper temperature and cooled or were placed at 52°C, egg formulation may include dairy (affecting pH), "look and smell fine" is irrelevant for pathogen assessment but reflects how operators actually reason
- **Parameterisation challenge for humans**: Salmonella in eggs at 52°C will grow, but the duration matters. The inspector must decide the relevant pathogen and estimate whether 1 hour at 52°C allows significant growth. The "look and smell fine" comment reveals a common cognitive bias — sensory evaluation does not detect pathogen growth at levels that cause illness.

---

**B10. Sushi restaurant — raw fish temperature**

> "At a sushi restaurant, I checked the temperature of the fish case behind the counter. The tuna read 8°C and the salmon was at 6°C. The chef says the fish was received fresh this morning from the distributor and has been in the case all day. Is this acceptable for raw consumption?"

- **Source basis**: FDA Fish and Fishery Products Hazards and Controls Guidance, and FDA Food Code time/temperature requirements for raw fish at retail. Histamine formation in tuna (scombroid) and parasitic hazards are the primary concerns.
- **Ambiguity dimensions**: "All day" duration is vague (6–10+ hours), different fish species have different risk profiles (tuna: histamine-forming; salmon: Listeria, Anisakis), "received fresh this morning" doesn't specify delivery temperature, 8°C for tuna is above the 4.4°C/40°F FDA guidance, the concern is different for each species
- **Parameterisation challenge for humans**: The inspector faces a multi-hazard, multi-product assessment. For tuna, the primary concern is histamine (not modelled by standard growth models — it requires scombrotoxin-specific models). For salmon, the concern is Listeria growth. An inspector without deep knowledge may apply the same analysis to both, which would be incorrect.

---

### 3.3 Category C: Industry HACCP / Quality Assurance Personnel

These queries reflect real production incidents and operational decisions. The language is the least technical and the scenarios are the most operationally constrained.

---

**C1. Refrigeration breakdown — turkey processing**

> "The refrigeration chamber for our turkey storage broke down overnight. When we came in this morning, the temperature was reading 13°C. We think it failed sometime during the night — maybe around 2 AM based on the alarm log, but the alarm didn't trigger properly. The turkey portions have been there since yesterday afternoon. Can we still use them?"

- **Source basis**: This query is adapted directly from the informal project description you provided. It represents a realistic production incident.
- **Ambiguity dimensions**: Temperature trajectory unknown (gradual rise from 4°C to 13°C), failure time estimated ("maybe around 2 AM"), "since yesterday afternoon" is vague, turkey portions pH and aw not stated, strong accept/reject decision pressure (economic incentive to keep the batch)
- **Parameterisation challenge for humans**: This is the scenario where optimistic bias is strongest. The operator has financial incentive to minimise the estimated abuse time and maximise the estimated starting temperature. Your system should standardise this by using conservative assumptions.


**Testing insights**

Testing — follow-up: threshold experiment

- What we learned: We tested whether simply lowering the retrieval threshold would let species queries match the right reference rows. With the gate dropped from 0.62 to 0.50, the turkey query did get a "matched" result — but the document it matched was white bread, not poultry. The right rows were not in the embedding model's neighbourhood at any threshold.
- What we fixed: Reverted the threshold change. Two related improvements stayed on the roadmap: empirical threshold recalibration once a stronger embedder is selected, and a future "needs clarification" failure mode rather than silent defaulting.
- What this taught us: A separate taxonomy bridge was needed. The threshold experiment cleanly settled what would otherwise have been an architectural argument — the right reference rows were structurally out of reach for species-name queries, regardless of gate setting.


Testing — follow-up: taxonomy bridge implementation

- What we learned: A third retrieval tier was added behind the existing two: a deterministic taxonomy bridge built on EFSA FoodEx2 (~2,900 rows, single citeable authority). When the first two tiers miss, the bridge resolves the food to a category — turkey to poultry — and inherits property values from a row in the reference data whose food belongs to that category. The C1 query returned pH and water activity through the bridge, with both fields attributed to the taxonomic source chain in the audit.
- What we fixed: Added the bridge component, a small alias map for vocabulary mismatches (beef → bovine, lamb → sheep), and a composite-blocklist guard that prevents queries like "chicken soup" from being silently grounded against any single constituent's properties — composites continue to default until a separate composite-food strategy is settled.
- What this taught us: The species-to-category gap can only be closed by an explicit taxonomic claim, not by a similarity score. The audit gained a structured citation chain — turkey → FoodEx2 → poultry → IFT-2003 — which matters more for academic publication than for production retrieval. One concern raised at this round drove the next: the first version inherited values from any row in the resolved category, which is speculative for heterogeneous categories like vegetable.


Testing — follow-up: Approach B experiment

- What we learned: An alternative to the deterministic bridge was tested: enrich the embedded text of category-level reference rows with species lists, on the theory that turkey would then find fresh poultry through normal retrieval. Half-day experiment. The results rejected the approach. Turkey scored 0.578 against the enriched fresh-poultry row, well below the 0.62 gate. Worse, the canonical chicken query regressed by 0.064 — adding species names diluted the row's category signal.
- What we fixed: Discarded the experiment. Two findings were filed as separate work: the embedder appears to be the bottleneck (an embedder-comparison benchmark is now scoped as a separate experiment), and threshold recalibration may revisit once a stronger embedder is selected.
- What this taught us: Cheap experiments rejecting bad architectures pay for themselves. The empirical finding was that the embedding model weights property-axis cues ("pH acidity") more heavily than food-type cues, regardless of what the document text says. No threshold or text-level enrichment shifts that balance — the limitation lives in the embedder.


Testing — follow-up: bridge restriction and switch

- What we learned: The bridge's first version inherited the conservative bound across all rows in the resolved category — defensible for tight categories like poultry, speculative for heterogeneous ones like vegetable (which spans pH 2.3 to 6.7). The restriction confined inheritance to a curated list of five rows that the source authorities themselves framed as category-wide claims. State-awareness was added so that fresh and cured products of the same species would not be conflated. An environment variable was added so the bridge layer can be disabled at runtime. After re-test, the C1 water activity still resolves through the bridge, but pH now defaults — chicken's pH is a chicken measurement, not a poultry-wide claim, and the bridge no longer treats it as transferable. The default's reason text says so explicitly.
- What we fixed: Replaced the conservative-bound-across-arbitrary-rows logic with a curated lookup against five (food, category, state, field) combinations. Extended the audit's bridge-attempts mechanism to fire whenever no curated row matches, which is now the common case. Added PTM_TAXONOMY_BRIDGE_ENABLED for runtime toggling, with explicit startup logging of the active mode.
- What this taught us: The bridge is more conservative and more honest. Where the source authority published a category-wide claim, the bridge speaks with that authority. Where it did not, the bridge defaults and explicitly says it tried. The reach contracts; the trustworthiness improves. The broccoli criticism is closed: a broccoli query now defaults with bridge attribution rather than inheriting an arbitrary vegetable's measurements. Looking back across the arc — threshold experiment, bridge build, Approach B experiment, restriction — the architecture that landed is not the one we started with. Each rejected alternative either failed empirically or revealed a flaw that pushed the design further. The investigation closes here.

---

**C2. Cooking process deviation — chicken nuggets**

> "One of our oven lines had a temperature drop during a production run of breaded chicken nuggets. The oven thermocouples show the product core temp only reached 68°C instead of our target 74°C. The nuggets were in the oven for the normal time of 8 minutes. Do we need to discard the batch?"

- **Source basis**: USDA-FSIS Appendix A (Cooking Guideline for Meat and Poultry Products) provides time-temperature combinations for lethality. The 7-log Salmonella reduction requirement for poultry products is the regulatory standard. The question of whether alternative time-temperature combinations achieve equivalent lethality is a daily decision in poultry processing.
- **Ambiguity dimensions**: This is actually a relatively well-defined thermal inactivation problem, but the ambiguity is in whether 68°C for 8 minutes achieves the required lethality. The operator may not know the D- and z-values needed for the calculation. Product formulation (fat content, moisture content) affects thermal death kinetics.
- **Parameterisation challenge for humans**: The operator needs to determine whether the achieved time-temperature combination (68°C, 8 min) is equivalent to the target (74°C instantaneous). USDA-FSIS Appendix A tables provide this, but the operator must correctly identify the applicable table and interpolate. This is a model selection and lookup task, not just parameterisation.


**Insights after testing**

-What we learned: This query exercised the thermal inactivation model for the first time in the test journal, with valid ranges much narrower than the growth model (54.5–65°C for temperature, 0.997–1.0 for water activity). The bridge worked as designed — it resolved breaded chicken nuggets to poultry and supplied water activity from the curated fresh poultry row, with pH defaulting honestly because no curated pH row exists for that category. Two model-layer issues then dominated. The supplied water activity (0.99 from fresh poultry) was already too high for a cooked breaded product (real aw closer to 0.93–0.96) and was clamped upward to 0.997 to fit the thermal model's valid range — two moves that together over-state the moisture content. The product temperature of 68°C was clamped down to the model's upper limit of 65°C, where the secondary polynomial produced an extreme inactivation rate of -240 log per minute. A plausibility cap engaged and limited the reported decrease to -15 log, with an explicit warning naming the polynomial's boundary sensitivity. The final verdict ("Salmonella effectively eliminated") is operationally correct for 8 minutes at 65°C, but the path to that verdict involved two upward clamps and a physical-limit cap, all surfaced honestly in the audit.
-What we fixed: Nothing in this round. Each finding belongs to existing roadmap items. The composite-food / state-mismatch interaction (cooked breaded product inheriting raw fresh poultry's properties) is the same pattern as previous composite cases and remains tied to the future composite-food strategy. The polynomial's boundary behaviour is a known property of secondary models near their valid-range edges; the plausibility cap exists precisely to handle it. The cap's framing ("-15 log decrease") could read more cleanly as "saturation reached" for a publication-bound audit, but that is a copy-edit, not a structural fix.
-What this taught us: The bridge's restriction is doing what it should — supply only what is defensible, default everything else with honest attribution. Where things become awkward is one layer below: the inherited water activity is technically correct for the source authority's "fresh poultry" framing but does not reflect the queried food's processed state, and the model layer's clamps then compound the mismatch. State-aware bridging closes part of this gap (a "cooked breaded chicken" entry would inherit different properties), but the deeper issue is that the food-property reference data itself does not enumerate states beyond fresh and cured for poultry. The thermal inactivation model also revealed a class of finding the journal had not yet seen: polynomial secondary models behave wildly near their valid-range boundaries, and the plausibility cap is the load-bearing safety net that converts an unphysical raw output into a defensible reported value. Worth pinning as a separate concern from the bridge work.
-A separate finding on pathogen handling: This query, like several others in the journal, fired the system's "conservative default" of Salmonella because no pathogen was named and the hazard-retrieval step produced no confident match. The audit explicitly tried — "breaded chicken nuggets food hazard" was searched against the pathogen-hazard data — and the closest candidate (raw chicken Salmonella) scored 0.5143, well below the 0.75 retrieval gate. The default fired and produced an answer that is technically defensible for this query but obscures three problems we have now seen repeatedly. First, the path to the answer is "default fired" rather than "evidence retrieved", so even when the default lands on the correct primary hazard (as it did for raw chicken in B1) the audit reads as if the system had no evidence — which is true, but unhelpful. Second, the right hazard for cooked breaded products differs from the right hazard for raw chicken — Listeria recontamination and Clostridium perfringens spore germination during cooling are the cooked-poultry concerns, neither of which a Salmonella default would surface. Salmonella inheriting from raw-chicken hazard data, even if the embedder had retrieved that row successfully, would have been the same shape of state-mismatch we have already seen for water activity. Third, a stronger embedder would not solve this — it would surface the raw-chicken Salmonella row more confidently, producing the wrong-state answer with greater certainty rather than catching the scenario-aware question the user is implicitly asking. The decision after this round was to remove the default entirely. Pathogen is now treated symmetrically with duration: a missing pathogen produces a structured error response identifying it as a required field, the same way missing duration does today. The user re-submits with a pathogen specified. A future clarification module may eventually surface scenario-aware candidates interactively (cooked-poultry hazards for cooked-poultry queries, raw-poultry hazards for raw-poultry queries), but for now the architectural step is the simpler one: stop hiding the assumption. Across the previous captures (C1, B1, B2, duck, broccoli), the Salmonella default had fired silently in every one. Future re-runs of those queries will fail loudly until a pathogen is specified, which is the appropriate behaviour for a system whose audit is supposed to make every assumption visible.

---

**C3. Cooling validation — cooked ham**

> "We need to validate our cooling process for cooked bone-in hams. After the smokehouse, the hams are shower-cooled then placed in the blast chiller. It takes about 4 hours to go from 54°C to 27°C, and then another 8 hours to go from 27°C to 4°C. Does this meet the FSIS cooling requirements?"

- **Source basis**: USDA-FSIS Stabilization Guideline (Appendix B) explicitly defines the cooling requirement: no more than 1-log growth of C. perfringens during cooling from 54.4°C to 26.7°C, and continued cooling to 7.2°C with no more than total 0.5-log combined growth of C. perfringens and C. botulinum (non-proteolytic). This is a direct HACCP validation scenario.
- **Ambiguity dimensions**: The temperatures and times are relatively specific, but the trajectory between them is assumed linear (may not be — exponential cooling is more realistic), "about 4 hours" introduces some imprecision, ham pH and aw not given, the two-stage regulatory criterion requires careful application
- **Parameterisation challenge for humans**: The operator must correctly apply the two-stage FSIS criterion and know that C. perfringens is the target organism for the first stage. Many operators simply check whether the total cooling time is within the FDA "6 hours from 57°C to 5°C" guideline, which is a different (and less stringent) standard than the FSIS stabilisation requirement.

---

**C4. Shelf life extension assessment — RTE salad**

> "We want to extend the shelf life of our packaged Caesar salad from 7 to 12 days. The product is MAP packaged, stored at 4°C. The dressing is a creamy Caesar. What do we need to check from a pathogen growth standpoint?"

- **Source basis**: EU Regulation (EC) No 2073/2005 requires food business operators to conduct shelf life studies for RTE foods that support growth of L. monocytogenes. This type of query is common in product development and QA.
- **Ambiguity dimensions**: "4°C" is the target but actual cold chain temperatures include excursions, Caesar dressing pH and aw depend on recipe (creamy Caesar typically pH 4.0–4.5 but the salad overall is higher), MAP composition not specified, the relevant pathogen (Listeria) is not named, the question is open-ended ("what do we need to check?")
- **Parameterisation challenge for humans**: The QA manager must identify L. monocytogenes as the target hazard, estimate the product's physicochemical properties (composite food — lettuce pH ~6.0, dressing pH ~4.2, cheese, croutons — which pH applies?), and decide whether to use the dressing pH (optimistic) or the salad pH (conservative) for the model.

---

**C5. Temperature abuse during distribution — yoghurt**

> "Our distributor reported that one of their trucks had its cooling set to 10°C instead of 4°C for an estimated 6-hour delivery route. The load was Greek yoghurt with fruit on the bottom. Do we need to recall the affected batch?"

- **Source basis**: Temperature deviations during distribution are a common industry concern. Greek yoghurt typically has pH 3.8–4.4 and is generally considered a low-risk product for pathogen growth due to its acidity. However, fruit-on-bottom products create a higher pH microenvironment at the interface.
- **Ambiguity dimensions**: Temperature was steady at 10°C (clearer than many scenarios), duration is "estimated" 6 hours, Greek yoghurt pH and aw not given (operator may not know), the fruit layer has different pH than the yoghurt, the concern is whether the product moves from "no growth" to "growth" zone
- **Parameterisation challenge for humans**: The operator must determine whether 10°C for 6 hours allows pathogen growth in yoghurt. The answer depends critically on pH: at pH 4.0, most pathogens cannot grow even at 10°C. But the fruit layer may have a higher pH (4.5–5.0), creating a growth-permissive microenvironment. This subtlety is often missed.

---

**C6. Reformulation assessment — reduced-sodium deli meat**

> "We're reducing the sodium in our sliced cooked turkey breast from 2.0% to 1.2% for a 'lower sodium' label claim. Everything else stays the same — same cook process, same packaging, same shelf life of 45 days at 4°C. Do we need to redo our Listeria challenge study?"

- **Source basis**: Industry reformulation for sodium reduction is a major current trend. USDA-FSIS Compliance Guidance for Controlling Listeria monocytogenes in Post-Lethality Exposed RTE Meat and Poultry Products addresses the need for reassessing Listeria controls when product formulation changes. Salt content directly affects water activity.
- **Ambiguity dimensions**: How does reducing salt from 2.0% to 1.2% change aw? (Operator may not know the relationship), current aw not stated, what was the original challenge study result? pH of the turkey breast not given, other hurdles (lactate, diacetate?) not mentioned, the question is whether the formulation change crosses a growth boundary
- **Parameterisation challenge for humans**: The critical question is whether the aw change (from approximately 0.975 to 0.983) crosses a growth/no-growth boundary for Listeria under the other product conditions. This requires converting salt percentage to aw — exactly the kind of transformation your system's agentic approach is designed to perform.

---

**C7. Process water contamination — produce washing**

> "We detected Salmonella in our process water used for washing bagged lettuce. The water system has been sanitised and retested clean. We're trying to assess the risk for product that was processed in the 24 hours before the positive was found. The lettuce was washed, spin-dried, and packaged under MAP. Stored at 4°C."

- **Source basis**: Process water contamination in produce facilities is a well-documented food safety concern. The 2006 spinach E. coli O157:H7 outbreak and subsequent FDA guidance on leafy greens safety provide the regulatory context.
- **Ambiguity dimensions**: Salmonella concentration in the water unknown, transfer rate from water to lettuce unknown, washing and spin-drying may reduce but not eliminate contamination, MAP conditions not specified, lettuce pH (~6.0) and aw (~0.99) not stated, the 24-hour exposure window is broad, storage duration at 4°C not specified
- **Parameterisation challenge for humans**: This is a complex scenario requiring assumptions about initial contamination, transfer efficiency, and subsequent growth during storage. Most QA managers will not have the information needed to fully parameterise this and will make multiple unvalidated assumptions.

---

**C8. Canned food pH deviation**

> "A batch of our canned tomato sauce came back with a pH reading of 4.8 instead of our target of 4.2. The sauce is thermally processed in a retort. We normally classify this as an acid food. Does this pH deviation change the safety classification?"

- **Source basis**: FDA 21 CFR Part 113 (Thermally Processed Low-Acid Foods Packaged in Hermetically Sealed Containers) and Part 114 (Acidified Foods). The pH 4.6 boundary between acid and low-acid foods is one of the most critical regulatory thresholds in canned food safety.
- **Ambiguity dimensions**: The deviation (4.2 → 4.8) crosses the critical pH 4.6 threshold, which shifts the product from "acid food" to "low-acid food" — a fundamental regulatory classification change. The operator may not immediately recognise the significance. Retort processing parameters may or may not be adequate for a low-acid product.
- **Parameterisation challenge for humans**: This is primarily a classification problem (acid vs. low-acid) rather than a growth prediction problem, but the implications for Clostridium botulinum risk are severe. An operator who thinks "4.8 is close to 4.2, probably fine" is making a potentially lethal error. The system should flag the pH 4.6 boundary crossing.

---

**C9. Marinated chicken — conflicting temperature information**

> "We marinate chicken thighs in a walk-in cooler overnight. This morning, the floor staff said the cooler felt 'warm'. The digital display says 3°C but the product probe reads 9°C. The chicken has been marinating for about 14 hours. The marinade has vinegar and citrus juice. Should we proceed with production?"

- **Source basis**: This scenario reflects a real-world calibration/measurement discrepancy that occurs frequently in food processing. The conflicting temperature readings create a genuine decision dilemma.
- **Ambiguity dimensions**: Conflicting temperature data (3°C display vs. 9°C product probe — which to trust?), "about 14 hours" is imprecise, marinade composition vaguely described ("vinegar and citrus juice" — what pH does that create? What concentration?), chicken pH and aw not stated separately from marinade
- **Parameterisation challenge for humans**: The operator must decide which temperature reading to trust (the probe is more reliable than the ambient display, but they may choose the more favourable reading), estimate the marinade pH (vinegar + citrus suggests acidic, but how acidic?), and determine whether the combination of time, temperature, and pH is safe. Optimistic bias is likely: "the display says 3°C" provides psychological cover for proceeding.

---

**C10. Bakery cream filling — ambient exposure**

> "Our production line had a 2-hour stoppage due to a mechanical issue. The pastry cream was already prepared and sitting in the piping hopper at room temperature during the delay. The cream is a custard-base made with eggs and milk. Can we still use it?"

- **Source basis**: Custard and cream fillings are classified as TCS (Time/Temperature Control for Safety) foods under FDA Food Code. S. aureus toxin production in custard is a classic food safety hazard described in FDA HACCP guidance.
- **Ambiguity dimensions**: "Room temperature" in a bakery (could be 25°C to 32°C+ near ovens), "2-hour stoppage" is relatively precise but still uncertain, custard pH not specified (typically 6.0–6.8), aw not given (typically 0.97–0.99), the concern is both growth (S. aureus, Salmonella) and toxin production
- **Parameterisation challenge for humans**: The bakery operator may not consider custard a high-risk product ("it's just cream"). The decision often comes down to whether 2 hours at room temperature exceeds the FDA 4-hour TCS time limit — but the operator needs to factor in prior cumulative time at room temperature (preparation, cooling before the hopper, etc.), which may not be tracked.

---

## 4. Summary Statistics

| Property | Cat A (Risk Assessors) | Cat B (Inspectors) | Cat C (Industry QA) |
|----------|----------------------|--------------------|--------------------|
| Number of queries | 10 | 10 | 10 |
| Growth scenarios | 7 | 7 | 6 |
| Inactivation/survival scenarios | 2 | 0 | 2 |
| Classification/boundary scenarios | 1 | 0 | 2 |
| Multi-step temperature profiles | 4 | 4 | 3 |
| Hidden pH/aw | 8 | 9 | 9 |
| Vague temperature | 4 | 8 | 7 |
| Vague duration | 5 | 9 | 6 |
| Missing pathogen | 3 | 7 | 6 |
| Optimistic bias potential | 3 | 4 | 6 |
| Queries with literature source | 10 | 10 | 10 |

### Ambiguity dimension coverage (queries per dimension, total across all categories):

| Ambiguity dimension | Count |
|---------------------|-------|
| Hidden pH/aw | 26 |
| Vague temperature | 19 |
| Vague duration | 20 |
| Missing pathogen | 16 |
| Optimistic bias potential | 13 |
| Scenario type ambiguity | 5 |
| Multi-step complexity | 11 |

---

## 5. Notes on Use

**For the paired human study (Approach B):** Present each query set to participants from the matching category (risk assessors get Category A, inspectors get Category B, industry QA gets Category C). Ask each participant to provide: (a) the exact model input parameters they would use in ComBase (temperature, pH, aw, organism, duration, model type); and (b) a brief rationale for each choice. Measure inter-operator variability as the coefficient of variation for each parameter across participants. Then run the same queries through the Problem Translation Module and compare.

**For the Sobol sensitivity analysis (Approach A):** Use all 30 queries. For each, define plausible distributions for each uncertain parameter based on the ranges a human might reasonably choose. Use the variance decomposition to determine which input parameters contribute most to output variance for each query, and aggregate across the full set.

**For both approaches:** The queries should be reviewed and approved by at least 2 independent food safety experts before use in a study, to ensure ecological validity.

---

*Document prepared: 2026-03-20*
*Purpose: Sensitivity analysis study design for the Problem Translation Module*
