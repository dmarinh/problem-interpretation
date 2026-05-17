# PTM Retrieval Investigation — Technical Narrative (Exp 2.1 + Exp 2.2)

For Daniel and future Claude sessions. Comprehensive record of the two-experiment arc, the findings that survived, the methodology lessons, and the unresolved questions. Read this first when picking up the retrieval workstream.

---

## 1. The starting question

Production PTM uses `all-MiniLM-L6-v2` as the embedder for food-property and pathogen-hazard retrieval against a RAG store of ~310 short docs (253 food_properties + 56 food_pathogen_hazards). Three production thresholds gate the embedder's output: tier_1 (0.70, combined pH+aw retrieval), tier_2 (0.62, per-field retrieval), pathogen_stage_1 (0.75, hazard retrieval). Tier 2 is empirically calibrated; tier_1 and pathogen are conservative-by-intuition defaults.

A pre-experiment investigation (the "Approach B text-suffix" work) had identified that the production embedder appeared unable to bridge species-level queries ("turkey", "lamb", "duck") to category-level docs (`fresh poultry`, `fresh meat`). MiniLM scored unrelated docs above 0.62 — for "turkey pH acidity" it returned `curry paste acidified` at 0.566; for "lamb pH acidity" it returned `milk goat` at 0.592. The species-probe failure was the motivating problem.

Two experiments were run to address it: 2.1 asked "does a different embedder fix this?" and 2.2 — after 2.1's results raised more questions than they answered — asked "does the right combination of embedder and doc text format, with per-cell calibrated thresholds, fix this?".

---

## 2. Exp 2.1 — embedder comparison

### Design

- **Factors:** 4 embedders. minilm-l6-v2 (baseline, 22M), bge-small-en-v1.5 (33M, retrieval-optimised), bge-base-en-v1.5 (109M, retrieval-optimised), mpnet-base-v2 (110M, general). A 2×2 of size × training objective.
- **Doc text format:** held constant at production (whatever `app/rag/data_sources/food_safety.py` produces).
- **Thresholds:** held constant at production (0.70 / 0.62 / 0.75).
- **Corpus:** 30 ground-truth queries across four strata. Easy (10, specific-food rows exist), medium (10, species-probe queries needing category-level match), hard (6, negative controls including made-up foods), pathogen (4, hazard retrieval sanity).
- **Primary metric:** top-1 accuracy at production thresholds. Stratified by tier.
- **Decision rule:** switch to candidate X if (a) Δtop-1 > 0 vs baseline and (b) `tier_accuracy["hard"] == 1.0` (no false positives on negative controls).

### Results

| Embedder | top-1 | easy | medium | hard | pathogen |
|---|---|---|---|---|---|
| minilm-l6-v2 (baseline) | 70% | 80% | 30% | 100% | 100% |
| bge-small-en-v1.5 | 70% | 100% | 70% | 0% | 100% |
| bge-base-en-v1.5 | 57% | 80% | 50% | 0% | 100% |
| mpnet-base-v2 | 77% | 80% | 60% | 83% | 100% |

### Findings

1. **No candidate satisfied the decision rule.** All three candidates introduced false positives on the hard stratum. mpnet had the highest top-1 accuracy (77%, +7 over baseline) but with `hard_fpr=0.167` — one negative-control query falsely cleared the gate.
2. **BGE small was the strongest improvement on the medium stratum** (70% vs baseline 30%) and the only candidate to hit 100% on easy. But it dropped to 0% on hard — every negative control falsely matched.
3. **BGE base regressed.** Counter-intuitive but a known characteristic of BGE base on short-name queries: longer training context hurts on bare food names.
4. **Pathogen was always 100%** — a non-discriminating stratum. The query reformulation `"{food} food hazard"` and doc text `"Hazard for {food}: ..."` share the distinctive token `hazard`, providing a lexical anchor that all embedders exploit.
5. **Recommendation: do not switch.** The audit-honesty principle (silent grounding from unrelated docs is worse than conservative-default fallback) makes the hard-stratum FPR a non-negotiable constraint.

### Notable bug surfaced

The terminal output and the Streamlit dashboard initially printed contradictory recommendations: terminal said "switch to all-mpnet-base-v2 +7% MRR", dashboard said "do not switch — false positives on hard". The terminal used a weaker rule (Δtop-1 only); the dashboard used the full rule (Δtop-1 + hard==100%). Fixed by extracting a `recommend()` function as single source of truth between both surfaces. Lesson appended: *when two surfaces compute the same decision, the rule must live in one function imported by both*.

### What 2.1 left open

- Top-1 accuracy is a crude metric. Ignores rank order; conflates "retrieved nothing" with "retrieved wrong thing".
- All embedders were compared at the same production thresholds, which are calibrated for MiniLM. BGE's wider score distribution at the production threshold makes it look worse than it might be at its own calibrated threshold.
- Doc text format was never tested. For a short-doc RAG, this is the analogue of "chunk size" and is a real tunable parameter.
- The corpus (30 queries) was light on negative controls (6) and didn't include ambiguous-generic queries like bare "meat" or "fish".

These four gaps motivated 2.2.

---

## 3. Exp 2.2 — embedder × doc text format

### Design

- **Factor 1: embedder.** Same four as 2.1.
- **Factor 2: doc text format.** Three formats. Terse (`"chicken poultry pH 6.2 6.4 [IFT-2003-T33]"`), current (production-faithful: `"chicken (poultry): pH range 6.2 to 6.4. Raw chicken [IFT-2003-T33]"`), verbose (`"Chicken is a poultry product. Its pH ranges from 6.2 to 6.4. Note: Raw chicken. [IFT-2003-T33]"`). All three encode the same information; only verbosity varies.
- **Threshold calibration:** per-cell, per-tier. FPR-constrained F1 maximisation over 61 sweep points (threshold ∈ [0.30, 0.90] step 0.01). Cell viable iff FPR ≤ 0.05 at the F1-optimal threshold.
- **Corpus:** expanded to 60 queries (v2.0). Easy 18, medium 20, hard 12, pathogen 10. Generated from CSV sources, not LLM-invented. Two new hard-stratum sub-types: Type-1 class-noun → specific row (e.g., "meat" → `beef ground`), Type-2 class-noun → category row (e.g., "fish" → `fresh fish`).
- **Primary metric:** pure MRR (rank-based, threshold-invariant). Reported alongside `mrr_gate_filtered` (gate-filtered version) and per-stratum versions of both.
- **Decision rule (pre-registered):** switch to candidate X if (a) `viable_at_calibrated_threshold` is true or partial, (b) `mrr_easy ≥ 0.95`, (c) no errored queries, AND (d) highest pure MRR with tiebreaks on latency, model size, format proximity to production.

### Three review gates during execution

- **Gate 1 — Corpus.** 30 new entries reviewed before merge. Refinements: comments added on H11/H12 (ambiguous generics — class-noun rationale), comment on P07 cooked rice (Stage 1 only framing), verification of unusual three-word food_name "milk raw unpasteurized" against CSV.
- **Gate 2 — Format templates.** Notes-handling fixed (terse was omitting; corrected to include). Production-faithfulness verification on `primary_hazard` rendering.
- **Gate 3 — Dry run.** Single-cell mechanical verification. Exit logic tightened to distinguish wiring checks (gating) from result observations (non-gating). H11 "meat" → `beef ground` 0.666 and H12 "fish" → `fresh fish` 0.643 fired as designed.

### Three methodology iterations during analysis

- **Iteration 1 — F1-maximising calibration.** Produced "optimal" thresholds at 0.30 (the sweep floor) for most cells. Diagnosis: F1 weights TP and FP symmetrically; PTM's audit-honesty regime weights FP more heavily. **Changed to FPR-constrained F1** (maximise F1 subject to FPR ≤ 0.05).
- **Iteration 2 — Tri-state viability.** Zero hard-stratum queries route through tier_1 (all 12 are field=ph or field=water_activity, both tier_2). FPR denominator is zero for tier_1 → constraint undefined. Returns `viable=null` rather than silent permissive default. Cell viability becomes tri-state (true / partial / false). All 12 cells came in as `partial` because tier_1 is undefined for everyone.
- **Iteration 3 — MRR semantics audit.** The reported `mrr` was changing with threshold (e.g., BGE-small × verbose: 0.870 at production, 0.604 at calibrated). Standard MRR is rank-based and threshold-invariant. The harness had conflated ranking quality with gate-passing. Split into `mrr` (pure, rank-based, primary) and `mrr_gate_filtered` (kept for diagnostic value).

### Results — pure MRR (after all corrections)

| Cell | pure MRR | easy | medium | pathogen | gate-filtered MRR | hard FPR |
|---|---|---|---|---|---|---|
| minilm-l6-v2_terse | 0.785 | 0.963 | 0.543 | 1.000 | 0.299 | 0.000 |
| **minilm-l6-v2_current (baseline)** | 0.885 | 0.935 | **0.783** | 1.000 | 0.538 | 0.000 |
| minilm-l6-v2_verbose (recommended) | 0.887 | 0.963 | 0.762 | 1.000 | 0.590 | 0.000 |
| bge-small-en-v1.5_terse | 0.650 | 0.972 | 0.185 | 1.000 | 0.573 | 0.000 |
| bge-small-en-v1.5_current | 0.838 | 1.000 | 0.610 | 1.000 | 0.583 | 0.000 |
| bge-small-en-v1.5_verbose | 0.870 | 1.000 | 0.689 | 1.000 | 0.604 | 0.000 |
| bge-base-en-v1.5_terse | 0.655 | 0.972 | 0.197 | 1.000 | 0.594 | 0.000 |
| bge-base-en-v1.5_current | 0.821 | 0.944 | 0.621 | 1.000 | 0.562 | 0.000 |
| bge-base-en-v1.5_verbose | 0.837 | 1.000 | 0.608 | 1.000 | 0.583 | 0.000 |
| mpnet-base-v2_terse | 0.736 | 0.972 | 0.392 | 1.000 | 0.427 | 0.000 |
| mpnet-base-v2_current | 0.882 | 0.944 | 0.767 | 1.000 | 0.562 | 0.000 |
| mpnet-base-v2_verbose | 0.893 | 0.972 | 0.768 | 1.000 | 0.635 | 0.000 |

### Findings

**Finding 1: Doc text format moves MRR substantially across all embedders.**

| Embedder | terse→verbose pure MRR spread |
|---|---|
| minilm-l6-v2 | 0.10 |
| bge-small-en-v1.5 | 0.22 |
| bge-base-en-v1.5 | 0.18 |
| mpnet-base-v2 | 0.16 |

Terse is worst for all four. Verbose edges current for three of four. Format moves MRR comparably to embedder choice (range across embedders at current format: 0.064; range across formats within an embedder: up to 0.22). **Format is the largest single tunable retrieval-quality lever exp 2.2 identified.**

**Finding 2: The recommended switch sits inside corpus resolution.**

Decision rule selected `minilm-l6-v2_verbose` (pure MRR 0.887) over baseline `minilm-l6-v2_current` (0.885). ΔMRR = 0.002.

mpnet-base-v2_verbose has the highest pure MRR overall (0.893, Δ = 0.008) but the tiebreak within the 0.02 ΔMRR band selected MiniLM on smaller-model preference (22M vs 110M params).

**0.002 on a 60-query corpus is at or below sampling-noise resolution.** The recommendation is honest under the pre-registered rule but does not justify a production switch on retrieval-quality grounds alone. Should be treated as a demo-deliverable answer, not a production deployment trigger.

**Finding 3: After FPR-constrained calibration, every cell achieves hard_fpr=0.0.**

The hard-stratum gating problem identified in exp 2.1 is solved by per-cell threshold calibration, not by embedder change. Both Type-1 (class-noun → specific row) and Type-2 (class-noun → category row) failures drop to zero at calibrated thresholds.

**Finding 4: Tier_1 calibration is statistically undefined on this corpus.**

Zero hard-stratum queries route through tier_1. FPR denominator is zero for every cell. Reported as `viable=null` rather than papered over. Corpus-coverage gap, not methodology defect. Future fix: add tier_1 negative controls (e.g., `field=ph_aw_combined` queries with no canonical match).

**Finding 5: F1-maximising calibration is wrong for audit-honesty regimes.**

Symmetric loss functions optimise toward maximally permissive thresholds when negative controls are scarce. Fix: cost-asymmetric constraint (FPR ≤ 0.05 here). Recorded in `lessons.md`.

---

## 4. The structural observation — the actual answer

Beyond the recommendation, the pure-MRR data reveals that **the embedder layer is not the bottleneck**.

For MiniLM × current (the production baseline):
- 16 of 20 medium-stratum queries have the canonical doc at rank #1.
- 2 queries have it at rank #3.
- 2 queries have it outside top-K.
- Pure mrr_medium = 0.783.

But gate-filtered mrr_medium = 0.050. Only 1 of 20 medium queries actually clears the production gate of 0.62.

**The retrieval is working. The gate filters out correct rank-1 results because the cosine score sits at 0.41–0.66, below 0.62.**

This is a corpus property (short food-name queries → compressed cosine score range) and a threshold property, not an embedder property. BGE has higher absolute scores but exhibits the same overlap with the hard stratum's ambiguous-generic queries (0.49–0.67 from Gate 3). There is no clean threshold on this corpus that admits valid medium-stratum matches while rejecting bare "meat" or "fish" queries.

The species-probe "failure" identified in exp 2.1 was therefore a **thresholding problem**, not a retrieval problem, all along.

This re-frames the two-experiment arc: we spent two experiments evaluating embedder choice on what turned out to be a threshold-calibration question.

---

## 5. Why the recommendation still stands

Given Finding 2 and the structural observation, why not "do not switch"?

The decision was a deliberate framing call for demo deliverability:

- The pre-registered rule selects `minilm-l6-v2_verbose` unambiguously.
- Verbose has the highest pure_mrr_medium for the MiniLM family across all three formats (consistent direction).
- The smaller-model tiebreak avoids switching to a 5× larger model for marginal MRR gain.
- The Format finding (doc text moves MRR more than embedder) is the cleanest non-trivial result the experiment produces; recommending minilm × verbose centres it.
- The structural observation is preserved in the spec (§12), in the dashboard (closing paragraph), and in this narrative — but does not compete with the headline.

If you're inheriting this work and considering whether to actually deploy minilm × verbose to production, **do not**. The +0.002 MRR is noise, and verbose has not been validated against the reranker or against LLM downstream consumption. The defensible production action remains "keep current".

---

## 6. The audit-honesty trail — what we got right and wrong

### Right

- Pre-registered decision rules. The rule for 2.2 was set before the sweep ran and was not adjusted after results came in. The audit trail can verify the rule was applied as written.
- Single source of truth between terminal and dashboard. Fixed in 2.1 after the bug; held throughout 2.2.
- Tri-state viability over silent permissive defaults. When tier_1 had zero negative controls, the harness returns `null` and reports the corpus-coverage gap, rather than rolling forward with a meaningless 0.30 threshold.
- Negative-control polarity. The `hard_negative_control_pass_rate` is named to indicate inverted polarity, after `top1_hard` proved ambiguous.
- Two failure sub-types on the hard stratum. Type-1 vs Type-2 documented separately because they have different operational implications.

### Wrong (and fixed)

- F1-maximising calibration. Wrong objective for an asymmetric-cost regime. Caught when most cells optimised at the sweep floor.
- Gate-filtered MRR labelled as "MRR". Caught when MRR dropped 30% from threshold-only change.
- Field naming on `top1_hard`. Cosmetic but a documentation-bug-in-waiting. Renamed.

### Wrong (acknowledged, not fixed)

- Corpus does not cover tier_1 negative controls. Limits the calibration story for tier_1. Future corpus expansion can address.
- Medium stratum is heavily aw-weighted (18 of 20). Faithful reflection of the data, but means medium-MRR is mostly an aw-retrieval signal. Documented in the corpus description; not corrected by synthetic balancing.

---

## 7. The Format finding — what we know, what we don't

**Known:**
- Across all four embedders, terse < current ≤ verbose by pure MRR.
- Across the four embedders, mean spread terse→verbose is 0.165.
- The format effect is consistent in direction.

**Not known:**
- Whether verbose's gains survive the reranker. The reranker scores `(query, doc)` pairs with a cross-encoder. Longer, more natural-language docs change reranker behaviour. Not measured.
- Whether verbose's gains survive LLM downstream consumption. The grounded values feed into the LLM-generated audit. Token consumption rises with verbose docs.
- Whether the format effect interacts with threshold calibration. Verbose shifts the score distribution; the calibrated threshold for current may not be optimal for verbose.
- Whether verbose's gains generalise to a corpus expansion. The 60-query corpus is small.

**Action:** keep production on current. File "evaluate verbose end-to-end (retrieval + reranker + LLM + recalibrated thresholds)" as a follow-up. Do not ship verbose based on this benchmark alone.

---

## 8. The structural observation — what it implies for the roadmap

The species-probe failure is a gating problem. The most natural next experiment is a **single-cell threshold sweep on MiniLM × current**:

- One cell, no embedder change, no format change.
- Sweep threshold ∈ [0.40, 0.85] step 0.01.
- For each threshold, compute MRR (pure), gate-pass rate on positives, hard_fpr.
- Plot the precision-recall curve.
- Daniel picks an operating point.

Expected outcome: the curve will show a region around 0.50–0.55 where medium-stratum gate-pass rises substantially without hard_fpr exceeding 0.05. If so, **lowering the production threshold is the actionable lever**, not switching embedders.

Caveats:
- The score-distribution overlap may be tight enough that no threshold cleanly separates positives from Type-1 negatives (bare "meat" → `beef ground` at 0.666 is the hard-stratum top score for MiniLM × current). Likely the operating point trades some Type-1 FPR for medium gate-pass.
- Expanding the negative-control stratum (more Type-1 ambiguous generics: "poultry", "seafood", "produce", "dairy") would sharpen the curve and reduce sampling noise.
- This experiment is small. Half a day of code, ~1 hour of run time. Pair it with the corpus expansion suggested above.

---

## 9. Beyond off-the-shelf embedders

Both experiments tested off-the-shelf embedders trained on general English. None has the food-safety taxonomy encoded explicitly. The species-probe failure mode exists *because* no model has been trained on examples like `("turkey", "fresh poultry") → positive pair`.

The most direct way to inject that knowledge: **domain fine-tuning**. Take MiniLM (or any embedder), continue training it on contrastive pairs derived from `food_taxonomy.csv`:
- Positives: `("turkey", "fresh poultry")`, `("lamb", "fresh meat")`, `("salmon", "fish fresh most")` — the FoodEx2 taxonomy already encodes 2,917 such relationships.
- Negatives: random cross-category sampling.

A few hours on Daniel's GPU. The 60-query corpus from 2.2 serves as the eval set. Expected result: pure_mrr_medium > 0.95 across all medium-stratum queries, because the model now "knows" species belong to categories.

Risks: overfitting to FoodEx2 vocabulary at the expense of conversational queries. Mitigation: hold out a slice of FoodEx2 as eval; include the Q01–Q17 conversational queries as a sanity check.

This is the natural exp 2.3, **after** the single-cell threshold sweep clarifies whether the simpler fix (lower threshold) is sufficient.

---

## 10. Files and artefacts (locations for future sessions)

- **Spec:** `exp_2_2_embedder_doc_format_spec.md` (companion to this narrative).
- **Corpus:** `benchmarks/datasets/retrieval_queries.json` v2.0 (60 queries).
- **Runner:** `benchmarks/experiments/exp_2_2_embedder_doc_format.py`.
- **Output:** `benchmarks/results/exp_2_2_embedder_doc_format/{latest.json,latest.csv,_chroma/}`.
- **Viewer:** `benchmarks/visualizations/pages/6_embedder_doc_format.py`.
- **Config:** `benchmarks/visualizations/config.py` (EMBEDDERS + DOC_FORMATS).
- **Lessons:** entries in `specs/lessons.md` dated 2026-05-15 and 2026-05-16.

Exp 2.1 artefacts (predecessor): `exp_2_1_embedder_comparison.py`, `pages/5_embedder_comparison.py`, results under `benchmarks/results/exp_2_1_embedder_comparison/`.

---

## 11. The unresolved questions, ranked

1. **Should production lower the gate to ~0.50–0.55?** Highest-leverage open question. Single-cell threshold sweep answers it. ~half-day of work.
2. **Does domain fine-tuning fix the species-probe problem at the embedder level?** Cleaner solution if the threshold sweep doesn't yield a defensible operating point. ~1-2 days of work.
3. **Does verbose doc text survive downstream consumption?** Lower priority. Investigate only if the answer to (1) is "no defensible threshold" and the answer to (2) is "too costly for the gain".
4. **Does the corpus need tier_1 negative controls?** Yes, eventually, to make tier_1 calibration meaningful. Low priority unless tier_1 threshold becomes a production knob.
5. **Are the hard-stratum Type-1 and Type-2 patterns universal, or corpus-specific?** Worth knowing because the calibration story depends on distribution overlap. Expand the negative-control stratum and re-measure.

The two-experiment arc concluded with the demo. The retrieval workstream remains open on those five questions.
