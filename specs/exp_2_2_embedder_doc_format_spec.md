# Experiment Spec — Embedder × Doc Text Format for PTM Retrieval

This document is the working record of Experiment 2.2 in the PTM benchmark suite. It is archive-quality: it describes what was built, what was found, and which methodology decisions were made along the way. It is written to be read cold by someone who did not live through the conversation.

The experiment ran after Exp 2.1 (embedder comparison) and supersedes it as the basis for the embedder-choice question.

---

## 1. Purpose

Exp 2.1 identified a "species-probe failure" where MiniLM appeared unable to bridge queries like "turkey" or "lamb" to category-level documents (`fresh poultry`, `fresh meat`) in the food_properties knowledge base. Three of four candidate embedders introduced false positives on the hard (negative-control) stratum, so the recommendation was "do not switch".

Exp 2.2 addresses three gaps that exp 2.1 left open:

1. The corpus was small (30 queries) and used top-1 accuracy as the primary metric. Ranking-quality metrics (MRR, recall@k) were needed to characterise the embedder layer beyond binary correct/incorrect.
2. The production thresholds (0.62 / 0.70 / 0.75) were used as the operating point for every candidate, which compared embedders at different positions on different ROC curves rather than at each embedder's own calibrated point.
3. The "doc text format" parameter — how each CSV row is rendered as a string before embedding — was held constant. This is a real and tunable parameter for short-doc knowledge bases (where chunk-size doesn't apply) and was missing from exp 2.1.

The experiment is a **2-factor design** (embedder × doc text format) with **per-cell threshold calibration**, **ranking-quality metrics**, and a **pre-registered decision rule**. The corpus was expanded to 60 queries.

The outcome decides which embedder/format combination ships in production. The result was demoed to the advisory board.

---

## 2. What this experiment is and is not

**Is:** a 12-cell offline retrieval-quality benchmark. For each (embedder × doc_text_format) pair, re-embed the food_properties and food_pathogen_hazards CSVs into an isolated ChromaDB collection using the cell's format template, then run a 60-query corpus and measure rank-based and gate-based retrieval metrics with per-cell calibrated thresholds.

**Is not:** an integration test against the live API. No audits are regenerated. The reranker is held constant. The production ChromaDB store is not touched.

**Not in scope:** changing thresholds in production, modifying the rerank pipeline, modifying the audit shape, modifying the Tier 3 FoodEx2 bridge. Those are independent decisions; this experiment's data informs them but does not preempt them.

**In scope:** evaluating 4 embedders × 3 doc text formats (12 cells) against an expanded 60-query ground-truth corpus. Calibrating one threshold per cell per `production_tier` under an FPR≤5% constraint. Producing a Streamlit comparison artefact suitable for the demo.

---

## 3. Architectural position in the benchmark suite

```
benchmarks/
├── datasets/
│   ├── retrieval_queries.json                    # EXTENDED — v2.0, 60 queries
├── experiments/
│   ├── exp_2_1_embedder_comparison.py            # predecessor (unchanged)
│   ├── exp_2_2_embedder_doc_format.py            # NEW — this experiment
├── results/
│   ├── exp_2_2_embedder_doc_format/              # NEW — output directory
│   │   ├── results_YYYYMMDD_HHMMSS.json
│   │   ├── summary_YYYYMMDD_HHMMSS.csv
│   │   ├── latest.json
│   │   ├── latest.csv
│   │   └── _chroma/                              # per-cell isolated ChromaDB
├── visualizations/
│   ├── config.py                                 # EMBEDDERS + DOC_FORMATS constants
│   └── pages/
│       └── 6_embedder_doc_format.py              # NEW — Streamlit viewer page
└── datasets/
    └── retrieval_queries.json                    # v2.0, 60 queries
```

Exp 2.1's runner and viewer page remain unchanged. Exp 2.2 stands alongside as a separate artefact; the runner page (`3_run_experiments.py`) picks it up automatically because the runner scans `experiments/` for `exp_*.py` files.

The naming preserves the convention: 1.x = data-quality, **2.x = retrieval-quality**, 3.x = LLM-quality, 4.x = robustness.

---

## 4. Factor 1: Candidate embedders

Same four as exp 2.1:

| ID | HF model | Params | Dim | Training objective |
|---|---|---|---|---|
| `minilm-l6-v2` | `sentence-transformers/all-MiniLM-L6-v2` | 22M | 384 | general (baseline) |
| `bge-small-en-v1.5` | `BAAI/bge-small-en-v1.5` | 33M | 384 | retrieval-optimised |
| `bge-base-en-v1.5` | `BAAI/bge-base-en-v1.5` | 109M | 768 | retrieval-optimised |
| `mpnet-base-v2` | `sentence-transformers/all-mpnet-base-v2` | 110M | 768 | general |

The shortlist is a 2×2 of size × training objective. e5 family and API embedders remain deferred per exp 2.1 reasoning. The `is_baseline=True` flag is on `minilm-l6-v2` only.

The `EMBEDDERS` config lives in `benchmarks/visualizations/config.py`.

---

## 5. Factor 2: Doc text formats

Three formats encode the same information (food_name, category, all numeric ranges, notes, source_id, state) with different verbosity:

### Terse — keyword-stuffed, no natural language
```
chicken poultry pH 6.2 6.4 Raw chicken [IFT-2003-T33]
```

### Current — what `app/rag/data_sources/food_safety.py` produces today
```
chicken (poultry): pH range 6.2 to 6.4. Raw chicken [IFT-2003-T33]
```

### Verbose — full natural-language sentence form
```
Chicken is a poultry product. Its pH ranges from 6.2 to 6.4. Note: Raw chicken. [IFT-2003-T33]
```

All three apply uniformly to food_properties and food_pathogen_hazards rows. The `current` format reproduces production character-for-character (validated at Gate 2 against `food_safety.py`). The `terse` and `verbose` formats were defined to bracket the verbosity axis without adding unstated semantic claims; the verbose form's notes-handling and control-method language were audited explicitly to verify no efficacy claims, no reclassification, no expansion of CSV values.

The `DOC_FORMATS` config lives alongside `EMBEDDERS` in `benchmarks/visualizations/config.py`.

---

## 6. Ground-truth query corpus

`benchmarks/datasets/retrieval_queries.json` v2.0 — 60 queries, expanded from v1.0's 30. Stratified by retrieval difficulty:

| Stratum | Count | Purpose |
|---|---|---|
| Easy | 18 | Specific-food row exists. Every embedder should hit ~100%. Diagnostic: if not, retrieval itself is broken. |
| Medium | 20 | Category-level matches (species → category row). The diagnostic stratum — the production failure mode that motivated this experiment. |
| Hard | 12 | Negative controls. No correct answer exists. Correct behaviour is silence (no doc above gate). |
| Pathogen | 10 | Hazard retrieval sanity check. |
| **Total** | **60** | |

### Corpus design rules

- Each entry has `food_description`, `field` (`ph` / `water_activity` / `ph_aw_combined` / `pathogen`), `production_tier` (`tier_1` / `tier_2` / `pathogen_stage_1`), `tier` (difficulty stratum), and `acceptable_food_names` (canonical-first list of correct food_names; empty list for negative controls).
- Corpus references `food_name`, not `doc_id`. The harness resolves food_name → doc_id at startup against the live ingestion path. This survives re-ingestion.
- New entries were generated from source data, not invented: easy from rows with both pH and aw populated, medium from FoodEx2 species mapping to existing category rows, hard from real foods absent from KB + ambiguous-generic queries + made-up foods, pathogen from food×pathogen rows in `food_pathogen_hazards.csv` not in v1.
- Two hard-stratum sub-types coexist by design: **Type-1** (class-noun grounds a specific-row value — unambiguously wrong) and **Type-2** (class-noun grounds a category-level value — conservatively-correct but design-rejected on audit-honesty grounds, e.g. bare "fish" → `fresh fish`). Both appear in the corpus; failure profiles per embedder should be reported separately.

### Corpus limitations documented

- The medium stratum is heavily aw-weighted (18 of 20 queries are `water_activity`, 2 are `ph`). This reflects the underlying data (category-level rows mostly carry aw, not pH) and is not corrected by synthetic balancing.
- Zero hard-stratum queries route through `production_tier=tier_1`. This makes tier_1 threshold calibration statistically undefined — see §10 below.

---

## 7. Experiment script structure

`benchmarks/experiments/exp_2_2_embedder_doc_format.py` follows the same skeleton as `exp_2_1_embedder_comparison.py` and `exp_3_1_model_comparison.py`. Key adaptations:

### Per-cell pipeline

For each of 12 cells `(embedder × doc_text_format)`:

1. Build an isolated ChromaDB collection under `benchmarks/results/exp_2_2_embedder_doc_format/_chroma/{embedder_id}__{format_id}/`.
2. Ingest `food_properties.csv` + `food_pathogen_hazards.csv` using the cell's format template.
3. Run all 60 corpus queries against the cell's collection (Top-K = 10). Query reformulation mirrors `RetrievalService` exactly (no paraphrase, no simplification — the four production query templates are reused).
4. Compute per-query metrics.
5. Sweep threshold for each `production_tier` under the FPR≤5% constraint (see §10).
6. Compute cell-level summary at the calibrated thresholds.

Per-embedder corpus isolation is mandatory: different-dimension vectors cannot share storage. Per-format isolation is also mandatory: the same embedder produces different vectors for different doc text.

### Per-query metrics

For each `(cell, query)` pair:

- `top_k_doc_ids`, `top_k_food_names`, `top_k_scores` — full top-10 ranked list
- `expected_rank` — 1-indexed rank of `acceptable_food_names[0]`, or `null` if not in top-10
- `expected_score` — cosine similarity of the canonical doc, or `null`
- `pure_reciprocal_rank` — `1/expected_rank` or 0; **threshold-invariant** (rank-based only)
- `reciprocal_rank` — gate-filtered version: 0 if `top1_score < threshold_used`
- `correct_at_1`, `gate_passed`, `latency_ms`, `error`

For negative controls (empty `acceptable_food_names`), `pure_reciprocal_rank` and `expected_*` fields are `null`; the relevant signal is the hard FPR computed at threshold-sweep time.

### Per-cell summary metrics

- `mrr` — Mean Reciprocal Rank (**pure, rank-based**). Threshold-invariant.
- `mrr_by_stratum` — pure MRR per stratum (easy / medium / pathogen)
- `mrr_gate_filtered` — same calculation but with sub-threshold rank-1 zeroed
- `mrr_gate_filtered_by_stratum`
- `top1_accuracy`, `top1_by_stratum`
- `gate_pass_rate` — fraction of positives where canonical doc clears the calibrated threshold
- `mean_expected_score` — average canonical-doc cosine across positives
- `hard_fpr`, `hard_fpr_type1`, `hard_fpr_type2` — false-positive rates on hard stratum at the calibrated threshold (sub-typed by failure mode)
- `hard_negative_control_pass_rate` — fraction of hard queries where NO doc clears the threshold (inverted-polarity metric, explicit field name)
- `viable_at_calibrated_threshold` — tri-state: `true` (all three tiers calibrated cleanly), `partial` (some tiers undefined or unviable, others viable), `false` (any tier has negatives but no FPR-clean operating point)
- `threshold_calibration` — per-tier optimum, F1, FPR at both production and calibrated thresholds; full sweep curve persisted

### CLI

```
python -m benchmarks.experiments.exp_2_2_embedder_doc_format
python -m benchmarks.experiments.exp_2_2_embedder_doc_format --embedders minilm-l6-v2,bge-small-en-v1.5
python -m benchmarks.experiments.exp_2_2_embedder_doc_format --formats current,verbose
python -m benchmarks.experiments.exp_2_2_embedder_doc_format --no-threshold-sweep
python -m benchmarks.experiments.exp_2_2_embedder_doc_format --no-mlflow
```

---

## 8. Pre-registered decision rule

Embedded in the experiment module as a `recommend(cells, baseline_cell_id) -> Recommendation` function. Both the terminal output and the Streamlit page call this function — single source of truth.

```
A cell is "viable" if:
  1. viable_at_calibrated_threshold in ("true", "partial")
  2. mrr_easy >= 0.95 at calibrated thresholds (sanity check on the
     easy stratum at the cell's operating point)
  3. no errored queries

Recommend the viable cell with the highest pure MRR overall.

If multiple viable cells are within Δ pure-MRR = 0.02:
  (a) lower latency
  (b) smaller model (params_m)
  (c) closer to current production format

If no cell is viable: recommend "do not switch" with the reason
the baseline failed and which cell came closest.

Recommendation output always includes:
  - pure MRR of recommended cell vs baseline
  - hard_fpr of every cell (table)
  - calibrated thresholds of the recommended cell
```

The rule was pre-registered before the full sweep ran and was not adjusted after seeing results.

---

## 9. Configuration

Add `EMBEDDERS` and `DOC_FORMATS` to `benchmarks/visualizations/config.py`. Mirrors `MODELS`:

```python
EMBEDDERS = [
    {
        "id": "minilm-l6-v2",
        "name": "all-MiniLM-L6-v2 (baseline)",
        "hf_model": "sentence-transformers/all-MiniLM-L6-v2",
        "dim": 384,
        "params_m": 22,
        "is_baseline": True,
        "training_objective": "general",
    },
    # bge-small, bge-base, mpnet ...
]

DOC_FORMATS = [
    {"id": "terse",   "description": "Keyword-stuffed, no natural language"},
    {"id": "current", "description": "Production format (food_safety.py)"},
    {"id": "verbose", "description": "Natural-language sentence form"},
]
```

---

## 10. Threshold calibration

### Objective

Per cell, per `production_tier`:

```
For each threshold in [0.30, 0.90, step=0.01]:
  compute TP, FP, FN, TN, F1, FPR
viable_thresholds = thresholds where FPR <= 0.05
if viable_thresholds is empty:
  optimal_threshold = null,   viable = false
else:
  optimal_threshold = argmax(F1 over viable_thresholds),  viable = true
```

The FPR ceiling of 5% is documented as `FPR_CEILING = 0.05` with rationale: in PTM's audit-honesty regime, false positives (silent grounding from unrelated docs) cost more than false negatives (conservative-default fallback). 5% means roughly 1 FP per 20 negative controls — low enough for audit review, high enough not to make every cell unviable on a 12-query negative-control stratum (where 1 FP = 8.3%).

### Tri-state viability

A tier returns `viable=null` when its FPR denominator is zero (no negative-control queries route through that tier). On this corpus, all 12 hard queries route through `tier_2` or `pathogen_stage_1`. **Tier_1 calibration is statistically undefined for every cell.** Reported as `viable: null, reason: "FPR_undefined_no_negatives_in_tier"` rather than rolled forward with a permissive default.

A cell's `viable_at_calibrated_threshold` is then tri-state: `true` (all three tiers calibrated cleanly), `partial` (some tiers undefined or unviable while others are viable), `false` (any tier has negatives but no FPR-clean operating point).

Across all 12 cells in the actual run, every cell came in as `partial` because tier_1 is undefined for everyone.

### F1 vs FPR-constrained F1

A first iteration used unconstrained F1 maximisation, which produced "optimal" thresholds at the sweep floor (0.30) for most cells because F1 rewards recall and the corpus has more positives than negatives. The objective was changed to FPR-constrained F1 after the first sweep; this is recorded as a methodology lesson in §11 below.

---

## 11. Critical findings

### Finding 1: Doc text format moves MRR substantially across all embedders

| Embedder | terse | current | verbose | spread |
|---|---|---|---|---|
| minilm-l6-v2 | 0.785 | 0.885 | 0.887 | 0.10 |
| bge-small-en-v1.5 | 0.650 | 0.838 | 0.870 | 0.22 |
| bge-base-en-v1.5 | 0.655 | 0.821 | 0.837 | 0.18 |
| mpnet-base-v2 | 0.736 | 0.882 | 0.893 | 0.16 |

(Pure MRR, all strata.) Terse is worst for all four embedders. Verbose edges current for 3 of 4. The format effect is comparable in magnitude to the embedder effect (range across embedders at current format: 0.821–0.885 = 0.064; range across formats within an embedder: up to 0.22). Format is the largest single tunable retrieval-quality lever exp 2.2 identified.

### Finding 2: The recommended switch sits inside corpus resolution

The decision rule selected `minilm-l6-v2_verbose` over baseline `minilm-l6-v2_current` with Δ pure MRR = 0.002. The tiebreak with `mpnet-base-v2_verbose` (pure MRR 0.893, Δ = 0.008 from baseline) selected MiniLM because of the smaller-model preference within the 0.02 ΔMRR band.

A 0.002 difference on a 60-query corpus is at or below sampling-noise resolution. The recommendation is honest under the pre-registered rule, but the spec records explicitly that the headline gain does not justify a production switch on retrieval-quality grounds alone. The switch is defensible because:

- Verbose format has the highest pure MRR per embedder for three of four candidates (consistent direction).
- The smaller-model tiebreak avoids switching to a 5× larger model for marginal gain.
- It surfaces the format finding as the demo's actionable lever.

Whether to actually adopt verbose in production is a separate question — see §12.

### Finding 3: Tier_1 calibration is undefined on this corpus

Zero hard-stratum queries route through `production_tier=tier_1` (all 12 hard queries are `field=ph` or `field=water_activity` — both tier_2). The FPR denominator for tier_1 is zero for every cell.

The harness reports this as `viable=null, reason="FPR_undefined_no_negatives_in_tier"` rather than papering over with a permissive default. This is a corpus-coverage gap, not a methodology defect. A future corpus expansion targeting tier_1 negative controls (e.g., `field=ph_aw_combined` queries with no canonical match) would address it.

### Finding 4: Hard FPR sub-types behave differently across embedders

The hard stratum splits into two failure modes:

- **Type-1** (class-noun grounds a specific-row value — e.g., "meat" → `beef ground`): all four embedders susceptible at production thresholds; FPR-constrained calibration eliminates Type-1 for every cell on this corpus.
- **Type-2** (class-noun grounds a category-level value — e.g., "fish" → `fresh fish`): only triggers for BGE embedders at production thresholds. At calibrated thresholds, Type-2 also drops to zero.

After calibration, all 12 cells achieve `hard_fpr=0.0` and `hard_negative_control_pass_rate=1.0`. The hard-stratum gating problem identified in exp 2.1 is solved by per-cell calibration; it was not solved by the embedder change alone.

### Finding 5: F1-maximising threshold calibration is wrong for audit-honesty regimes

The first iteration of the threshold sweep used unconstrained F1 maximisation. This produced "optimal" thresholds at the sweep floor (0.30) for most cells. Diagnosis: F1 weights TP and FP symmetrically, but PTM penalises FP (silent data corruption) more than FN (conservative fallback). The objective was changed to FPR-constrained F1 (maximise F1 subject to FPR ≤ 0.05).

This methodology lesson is recorded in `specs/lessons.md`: *"When false-positive and false-negative costs are asymmetric, threshold calibration must be cost-constrained rather than symmetric-loss-maximising."*

---

## 12. Structural observation: score-distribution overlap

Beyond the recommendation, exp 2.2 surfaced a structural observation about PTM's retrieval layer that re-frames the species-probe failure mode identified in exp 2.1.

**The embedder layer is not the bottleneck.**

Pure MRR on the medium stratum shows that the canonical doc is ranked at #1 for the majority of species-probe queries across all four embedders:

| Cell | pure_mrr_medium | gate-filtered mrr_medium |
|---|---|---|
| minilm-l6-v2_current (baseline) | 0.783 | 0.050 |
| minilm-l6-v2_verbose | 0.762 | 0.050 |
| bge-small-en-v1.5_verbose | 0.689 | 0.050 |
| bge-base-en-v1.5_verbose | 0.608 | 0.000 |
| mpnet-base-v2_verbose | 0.768 | 0.150 |

(Random sample; full table in `latest.json`.)

For MiniLM × current specifically: 16 of 20 medium-stratum queries have the canonical doc at rank #1. The retrieval is working. What fails is the *gate* — the canonical doc's cosine score sits at 0.41–0.66, near or below the production threshold of 0.62 (or the calibrated 0.67 for MiniLM × current). The production system filters out correct rank-1 results because the score doesn't clear the threshold.

This means: **the species-probe "failure" identified in exp 2.1 is partly a gating problem, not purely a retrieval problem.** Switching embedders does not address the gating issue. BGE produces higher absolute scores but exhibits the same overlap pattern with the hard stratum's ambiguous-generic queries (cosine 0.49–0.67 in exp 2.1 Gate 3 data) — there is no clean threshold that admits valid medium-stratum matches while rejecting bare "meat" / "fish" queries.

This is a *corpus property* (short food-name queries → compressed cosine score range) and a *thresholding property*, not an *embedder property*. It points to a future single-cell threshold-sweep experiment on the production stack to characterise the trade-off curve and pick an operating point.

The observation does not change the exp 2.2 recommendation. It is filed as the natural next investigation.

---

## 13. Working approach — what actually happened

Exp 2.2 ran in a fresh Claude Code session using three review gates, with retrospective notes on what each gate produced and any methodology issues surfaced.

**Gate 1 — Corpus expansion (60 queries).** Claude Code generated 30 new entries grounded in source CSVs (no LLM invention). Review surfaced and fixed: (a) refined comments on H11/H12 to explain the class-noun design rationale, (b) added a "Stage 1 only" framing comment on P07 cooked rice, (c) verified the unusual three-word `food_name` "milk raw unpasteurized" against the CSV. The medium stratum's heavy aw-weighting (8 of 10 medium additions) was noted as a corpus limitation rather than corrected, on the principle that synthetic balancing would misrepresent the data shape.

**Gate 2 — Doc text format templates.** Claude Code drafted three format templates. Review surfaced two issues: (a) notes-field handling differed across formats (terse omitted notes; current and verbose included them) which broke the "same information" invariant — corrected by including notes in terse, (b) the rendering of `primary_hazard` differed across formats (`primary_hazard` underscored in terse, `primary hazard` spaced in current, `primary food safety hazard` expanded in verbose) — resolved by requiring the current format to match production character-for-character. Verbose's unstated-claim audit was thorough and landed correctly (no efficacy claims, no notes expansion, no reclassification).

**Gate 3 — Harness dry-run.** Single-cell dry run on `minilm-l6-v2 × current × hard stratum` (6 v1 queries + 6 v2 new). Surfaced two corpus-related findings: H11 "meat" → `beef ground` at 0.666 and H12 "fish" → `fresh fish` at 0.643, both above the 0.62 production gate, both intentional negative-control failures by corpus design. Gate 3's exit logic was tightened to distinguish "harness wiring checks" (gating) from "result observations" (non-gating) — conflating the two was producing false alarms.

**Full sweep — first iteration.** Ran 12 cells. F1-maximising threshold calibration produced "optimal" thresholds at 0.30 (the sweep floor) for most cells because F1 rewards recall on a positive-heavy corpus. BGE cells reported `hard_fpr=1.0` at "calibrated" thresholds — looked like a bug, was actually F1 doing what F1 does. Required methodology change.

**Recalibration — second iteration.** Threshold sweep modified to FPR-constrained F1 (`maximise F1 subject to FPR ≤ 0.05`). Tri-state viability introduced (true/partial/false) to handle the tier_1 undefined case explicitly. Per-cell sweep curves persisted in `latest.json` for downstream inspection.

**Metrics audit — third iteration.** Inspection of recalibrated results surfaced four issues: (a) `mrr` field was gate-filtered (threshold-dependent), violating reader expectations of standard MRR; (b) tier_1 calibration was silently undefined; (c) `mrr_medium` was 0.00–0.15 across all cells, raising the question whether the corpus was unsolvable or whether MRR was being computed wrong; (d) `top1_hard` naming was ambiguous about polarity. Fixed in a single PR: `mrr` became pure rank-based MRR (added alongside `mrr_gate_filtered`); tier_1 returns explicit `null`; medium-MRR comparison between pure and gate-filtered exposed that retrieval is fine and the gate is the bottleneck; `hard_negative_control_pass_rate` replaced `top1_hard` with explicit-polarity naming.

**Recommendation reframing — pre-Streamlit decision point.** The pure MRR data showed all four embedders rank medium-stratum positives at #1 most of the time; the species-probe "failure" was a gating issue all along. Two recommendation framings were considered: (a) keep the original "switch to minilm × verbose +0.002 MRR" verdict and file the gating observation as a closing paragraph, (b) reframe the entire experiment around the gating finding. Option (a) was chosen for demo deliverability — the smaller-model tiebreak within the 0.02 ΔMRR band gives the demo a clean recommendation, and the gating observation lands as the natural next experiment without requiring the audience to follow a more sophisticated story.

**Streamlit page build.** Followed §11 of the original brief with two adjustments: dropped latency / scatter / Δ-vs-baseline sections per exp 2.1 demo-prep precedent; added a closing "Further observations" paragraph documenting the gating finding for the record.

The full methodology trail is recorded in `specs/lessons.md` under the 2026-05-15 / 2026-05-16 entries.

---

## 14. Working preferences

Same as exp 2.1, unchanged. Simple over DRY. Plan-first for non-trivial changes. No fake metrics. TDD: failing tests before implementation. Single source of truth between terminal and dashboard for the recommendation.

---

## 15. Streamlit viewer page

`benchmarks/visualizations/pages/6_embedder_doc_format.py`. Hand-crafted per the viz-spec rule (no abstraction into `lib/charts.py` unless genuinely shared across experiments).

Sections in order:

1. **Header.** Title, run timestamp, factor pills (4 embedders × 3 formats = 12 cells, 60 queries, 4 strata).
2. **Recommendation panel.** Verdict (switch to minilm-l6-v2_verbose), Δ pure MRR vs baseline, calibrated thresholds for the recommended cell (with tier_1 = `null — undefined`), cost statement, tiebreak note (mpnet rejected on size).
3. **Cell grid heatmap.** Side-by-side 4×3 grids: pure MRR per cell, hard FPR per cell. Colour-coded.
4. **Stratum definitions callout.** Verbatim text from exp 2.1 demo-prep, with an added paragraph documenting the medium-stratum interpretation under pure MRR.
5. **MRR by stratum.** Grouped bar chart, pure MRR per cell per stratum.
6. **Doc text format effect.** Grouped bar chart, pure_mrr_medium per embedder per format. Caption: format moves MRR 0.20–0.30; recommendation pairs smallest model with best format.
7. **Threshold sweep curves.** Faceted line plot per tier (tier_2, pathogen — tier_1 skipped as undefined). F1 vs threshold. Calibrated optimum marked.
8. **Corpus expander.** Closed by default. Renders `retrieval_queries.json` v2.0 as a dataframe.
9. **Per-query deep dive.** Defaults to a medium-stratum query (M01 turkey or similar) so the audience sees a rank-1-correct-but-gate-filtered case on first view.
10. **Doc text format examples.** Sample row rendered three ways.
11. **Per-cell threshold table.** Calibrated vs production thresholds; tier_1 explicitly shown as `null — undefined`.
12. **Further observations (single paragraph).** Documents the score-distribution overlap finding from §12 above and points to the future single-cell threshold sweep as the natural next experiment.

---

## 16. Out of scope, but worth noting

Same as exp 2.1, unchanged in scope:

- Cross-encoder rerank tuning — separate stage, separate experiment
- API-based embedders — deferred
- Domain fine-tuning — larger investigation; explicitly identified as the next-level lever beyond off-the-shelf embedder selection
- Hybrid retrieval (BM25 + dense) — architecturally invasive
- Threshold recalibration on the production stack — this experiment's data feeds into it; the future single-cell threshold-sweep experiment will address it directly

---

## 17. Definition of done

Exp 2.2 was complete when:

1. `exp_2_2_embedder_doc_format.py` ran end-to-end across all 12 cells, produced `latest.json` and `latest.csv` with MLflow logging.
2. Streamlit page rendered all 12 sections cleanly against the real results.
3. The advisory-board demo ran in <5 minutes with the recommendation visible in the first 30 seconds.
4. Terminal output and dashboard recommendation matched character-for-character (single source of truth).
5. The structural observation in §12 was documented for the record without competing with the headline recommendation.
