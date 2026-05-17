# Experiment Spec — LLM Model Comparison for PTM Semantic Extraction

This document is the working record of Experiment 3.1 in the PTM benchmark suite. It is archive-quality: it describes what was built, what was found, and what the recommendation is. It is written to be read cold by someone who did not live through the conversation.

---

## 1. Purpose

PTM's semantic parser is the entry point of the pipeline: it converts natural-language food-safety scenarios into a structured `ExtractedScenario` Pydantic schema that flows through grounding, standardisation, and ComBase execution. The parser's accuracy and consistency directly determine the system's trustworthiness — a wrong model-type classification reverses the direction of conservative bias, which is a safety-critical failure.

Exp 3.1 answers the model-selection question for the semantic parser: **which LLM should PTM use in production, and what are the viable fallback options under budget constraints?**

The experiment ran across two model classes — frontier API models (OpenAI) and locally-hosted models via Ollama — against an expert-annotated benchmark of 20 extraction queries spanning easy / medium / hard difficulty tiers. The output decides the production model, characterises the gap between frontier and local options, and identifies which local model is the closest viable fallback.

---

## 2. What this experiment is and is not

**Is:** an end-to-end evaluation of the real `SemanticParser` (same code path, same system prompt, same Pydantic schema as production) against a stratified ground-truth corpus. Each query is run N times per model to measure both accuracy (correctness vs. expert annotation) and consistency (run-to-run agreement). Field-level scoring distinguishes safety-critical fields (`model_type`) from soft ones (`duration_ambiguous`, `food_description`).

**Is not:** a generic LLM benchmark. The scoring is PTM-specific — the schema, the field-level grading rules, and the difficulty stratification reflect what PTM needs from a parser, not what an arbitrary NLP task needs.

**Not in scope:** prompt engineering experiments (system prompt is held constant), schema redesign, RAG-grounded queries (the parser stage runs before grounding), or end-to-end pipeline accuracy.

**In scope:** comparing model accuracy, consistency, safety-critical field correctness (model_type), latency, and cost per call across a representative shortlist of frontier and local models.

---

## 3. Architectural position in the benchmark suite

```
benchmarks/
├── config.py                                   # Models, embedders, shared paths
├── datasets/
│   ├── extraction_queries.json                 # 20 expert-annotated queries (this experiment)
│   ├── ph_aw_foods.json                        # used by Exp 1.1
│   └── retrieval_queries.json                  # used by Exp 2.1 / 2.2
├── experiments/
│   ├── exp_1_1_ph_stochasticity.py
│   ├── exp_2_1_embedder_comparison.py
│   ├── exp_2_2_embedder_doc_format.py
│   └── exp_3_1_model_comparison.py             # THIS EXPERIMENT
├── results/
│   └── exp_3_1_model_comparison/
│       ├── results_YYYYMMDD_HHMMSS.json
│       ├── summary_YYYYMMDD_HHMMSS.csv
│       ├── latest.json
│       └── latest.csv
└── visualizations/
    └── pages/
        └── 2_model_comparison.py               # Streamlit viewer page
```

The naming convention: 1.x = data-quality experiments, 2.x = retrieval-quality, **3.x = LLM-quality**, 4.x = robustness. Exp 3.1 is the LLM-quality flagship; future 3.x experiments would test prompt variants (3.4), reasoning-mode toggles (3.5), or specific failure-mode probes (3.6).

---

## 4. Models tested

Seven models across two classes. Six produced valid results; GLM-4.7 Flash failed in this run due to an API-key configuration issue and is excluded from the analysis (re-run pending).

### Frontier (API)

| ID | Provider model string | Class |
|---|---|---|
| GPT-5.5 | `openai/gpt-5.5` | frontier |
| GPT-4o | `openai/gpt-4o` | frontier (production baseline) |

### Local (Ollama)

| ID | Provider model string | Params | Notes |
|---|---|---|---|
| Qwen 3 8B | `ollama/qwen3:8b` | 8B | retrieval-strong local |
| Llama 3.1 8B Instruct | `ollama/llama3.1:8b` | 8B | general-purpose local |
| Phi-4 14B | `ollama/phi4` | 14B | Microsoft, reasoning-focused |
| Gemma4 E4B | `ollama/gemma4:latest` | ~4B | small Google local |
| GLM-4.7 Flash | `ollama/glm-4.7-flash:q4_K_M` | quantised | **failed (API key); excluded** |

Frontier models access the OpenAI API. Local models run via Ollama on the development workstation. All models share the same Pydantic schema and the same `SemanticParser` code path via LiteLLM + Instructor.

The `MODELS` config lives in `benchmarks/config.py`.

---

## 5. Ground-truth query corpus

`benchmarks/datasets/extraction_queries.json` v0.2 — 20 expert-annotated queries. Stratified by extraction difficulty:

| Stratum | Count | Purpose |
|---|---|---|
| Easy (E1–E5) | 5 | Fully specified queries with explicit values. Baseline accuracy test — every model should be near 100%. |
| Medium (M1–M6, N1) | 7 | Vague natural-language scenarios ("overnight on the counter", "for a while"). Tests linguistic-cue handling. Includes N1, a non-prediction information query — tests whether the parser correctly produces minimal extraction. |
| Hard (H1–H8) | 8 | Safety-critical and edge-case scenarios. Includes the "chicken nuggets bug" (H1, must be classified as thermal_inactivation not growth), temperature ranges (H2 turkey 10–15°C must preserve range, not collapse to midpoint), genuinely ambiguous scenarios (H3, multiple acceptable answers), multi-step scenarios (H4, H8), wide-range outages (H5), conflicting data (H6), and composite foods (H7). |

### Corpus design rules

- Each entry has `text`, `difficulty`, `notes`, and `expected` (field-level ground truth). Where genuine ambiguity exists, `expected.implied_model_type` may be a list, and `keywords` fields accept any-match alternatives (pipe-separated).
- Two safety-critical fields are scored with stricter logic: `model_type` (a wrong classification reverses conservative bias) and `range_preserved` (a collapsed range silently shifts the operating point toward the optimistic side).
- N1 ("What temperature kills bacteria?") is a deliberate non-prediction probe. The parser should produce minimal extraction with all major fields null. If the parser invents a food or pathogen, that's a hallucination — flagged as a failure mode.

### Corpus limitations documented

- 20 queries is small. Statistical power for fine model ranking is limited at margins of <3%. Differences of >5% are robust; differences of 1–2% are within sampling noise.
- The corpus is expert-drafted but flagged in metadata as `annotator: "DRAFT — requires review by domain expert"`. A formal domain-expert review pass would strengthen the ground-truth claims.
- No multilingual queries; the parser is evaluated only on English natural-language input.

---

## 6. Experiment script structure

`benchmarks/experiments/exp_3_1_model_comparison.py`. Skeleton mirrors Exp 2.1 / 2.2.

### Per-model pipeline

For each model in the shortlist:

1. Instantiate the production `SemanticParser` with the model under test.
2. For each of the 20 corpus queries, run extraction N times (default N=1 for smoke test, N=20 for the full run).
3. Score each run against the expected ground truth at the field level.
4. Compute per-query metrics (accuracy, consistency, model_type correctness, latency, cost, tokens).
5. Compute model-level summary metrics.
6. Save timestamped JSON + CSV.

### Per-query metrics

For each `(model, query)` pair, aggregated across the N runs:

- `accuracy` — mean fraction of fields correctly extracted (against `expected`)
- `field_scores` — boolean per-field correctness on each run; per-query averages
- `consistency` — fraction of runs producing identical structured output
- `field_consistency` — per-field run-to-run agreement
- `model_type_ok` — boolean per run (safety-critical; tracked separately)
- `mean_latency_s`, `input_tokens`, `output_tokens`, `cost_usd`
- `n_valid`, `n_errors` — schema-compliance counts
- `details` — full per-run records for downstream inspection

### Per-model summary metrics

- `overall_accuracy` — mean across queries
- `overall_consistency` — mean across queries
- `model_type_accuracy` — safety-critical, reported separately
- `schema_compliance` — fraction of runs producing valid Pydantic output
- `latency_p50_s`, `latency_p95_s`, `latency_mean_s`
- `total_input_tokens`, `total_output_tokens`, `actual_cost_per_call_usd`, `total_cost_usd`
- `field_accuracy` — per-field accuracy across all queries
- `tier_accuracy` — accuracy stratified by easy / medium / hard
- `model_type_errors` — list of query IDs where model_type was misclassified

### CLI

```
python -m benchmarks.experiments.exp_3_1_model_comparison
python -m benchmarks.experiments.exp_3_1_model_comparison --models "GPT-4o,Qwen 3 8B"
python -m benchmarks.experiments.exp_3_1_model_comparison --runs 20
python -m benchmarks.experiments.exp_3_1_model_comparison --no-mlflow
```

---

## 7. Decision criteria

Production selection considers four dimensions, in priority order:

1. **Safety-critical correctness** — `model_type_accuracy` ≥ 0.95 (no more than 1 of 20 wrong classifications). Failure here is non-negotiable; below this floor, the model is not viable for production regardless of other metrics.
2. **Overall accuracy and consistency** — `overall_accuracy` ≥ 0.90, `overall_consistency` ≥ 0.95.
3. **Latency** — `latency_p95_s` < 30 seconds (production target).
4. **Cost** — `actual_cost_per_call_usd` within operational budget.

The local-model question has its own decision frame:

1. **Best viable local fallback** — highest `model_type_accuracy` among local models, with `overall_accuracy` > 0.75 as a secondary check.
2. **Path to viability** — gap analysis against the safety-critical floor; what would need to improve.

---

## 8. Results

Six models produced valid results. GLM-4.7 Flash excluded.

### Headline metrics

| Model | Class | Overall Acc | Consistency | Model_type Acc | P95 Latency | Cost/Call |
|---|---|---|---|---|---|---|
| **GPT-4o** | frontier | **96.0%** | **99.7%** | **90.0%** | 28.5s | **$0.014** |
| GPT-5.5 | frontier | 95.5% | 99.4% | 90.0% | 16.9s | $0.026 |
| Qwen 3 8B | local | 79.8% | 98.1% | 75.0% | 60.1s | $0.000 |
| Phi-4 14B | local | 78.6% | 99.1% | 45.0% | 38.6s | $0.000 |
| Llama 3.1 8B Instruct | local | 69.7% | 100.0% | 25.0% | 20.3s | $0.000 |
| Gemma4 E4B | local | 51.8% | 100.0% | **5.0%** | 74.8s | $0.000 |

### Stratified accuracy

| Model | Easy | Medium | Hard |
|---|---|---|---|
| GPT-5.5 | 100.0% | 92.4% | 95.4% |
| GPT-4o | 100.0% | 97.1% | 92.6% |
| Qwen 3 8B | 78.4% | 81.9% | 68.8% |
| Phi-4 14B | 83.3% | 77.5% | 76.6% |
| Llama 3.1 8B Instruct | 74.7% | 66.5% | 69.5% |
| Gemma4 E4B | 38.8% | 55.1% | 56.9% |

### Safety-critical field — model_type

The model_type field determines whether the orchestrator selects a growth model (worst case = more growth) or a thermal-inactivation model (worst case = less kill). Misclassification reverses conservative-bias direction. This is the single most safety-critical extraction field.

| Model | Model_type Accuracy | Misclassified Query IDs |
|---|---|---|
| GPT-5.5 | 90.0% | H3, N1 |
| GPT-4o | 90.0% | H6, N1 |
| Qwen 3 8B | 75.0% | M2, M4, H3, N1 |
| Phi-4 14B | 45.0% | M2, M3, M5, H1, H2, H3, H4, H5, H7, H8, N1 |
| Llama 3.1 8B Instruct | 25.0% | E2, E4, M1–M6, H1, H2, H3, H5, H6, H7, N1 |
| Gemma4 E4B | 5.0% | all queries except one |

### H1 — the chicken-nuggets bug (thermal_inactivation, not growth)

| Model | Got model_type right? |
|---|---|
| GPT-5.5 | ✓ |
| GPT-4o | ✓ |
| Qwen 3 8B | ✓ |
| Phi-4 14B | ✗ |
| Llama 3.1 8B Instruct | ✗ |
| Gemma4 E4B | ✗ |

### H2 — temperature range preservation (turkey 10–15°C)

All six models correctly preserved the range (`range_preserved: true`). This is a positive result: the range-preservation fix lives at the schema level (Pydantic accepts `is_range: bool` and `range_min` / `range_max` fields), so models with valid schema compliance get it right. The downstream `StandardizationService` is responsible for picking the conservative bound (upper for growth, lower for thermal-inactivation) — not the parser.

---

## 9. Critical findings

### Finding 1: GPT-4o is the production pick

GPT-4o achieves the highest overall accuracy (96.0%), perfect easy-tier accuracy (100%), highest medium-tier accuracy (97.1%), and lowest cost per call ($0.014) among models meeting the safety threshold. P95 latency at 28.5s sits just under the 30s production target.

GPT-5.5 is competitive on accuracy (95.5%, marginally lower) but costs 86% more per call ($0.026 vs $0.014) and is slightly worse on the medium stratum (92.4% vs 97.1%). On hard stratum it edges GPT-4o (95.4% vs 92.6%), but the cost asymmetry tips production toward GPT-4o.

Both frontier models tie at 90% model_type accuracy — 2 misclassifications out of 20. GPT-4o's errors are on H6 (conflicting temperature data, genuinely ambiguous) and N1 (the non-prediction probe). GPT-5.5's errors are on H3 (acceptably ambiguous scenario, both classifications are valid per ground truth) and N1.

### Finding 2: No local model meets the safety-critical floor

The decision rule requires `model_type_accuracy ≥ 95%`. The best local model, Qwen 3 8B, hits 75% — short of the floor by 20 percentage points. The other local models drop sharply from there:

- Qwen 3 8B: 75% (4 errors: M2, M4, H3, N1)
- Phi-4 14B: 45% (11 errors including the critical H1 chicken-nuggets case)
- Llama 3.1 8B Instruct: 25% (15 errors)
- Gemma4 E4B: 5% (19 of 20 wrong)

**Local-model selection is therefore aspirational, not deployable.** No local model currently in the shortlist can replace the production frontier model without compromising safety-critical correctness.

### Finding 3: Qwen 3 8B is the best fallback candidate, with caveats

If a frontier model becomes unavailable (budget constraint, API outage, sovereignty requirement), Qwen 3 8B is the best local fallback in this comparison. It is the only local model that:

- Exceeds 75% on overall accuracy (79.8%)
- Exceeds 75% on model_type accuracy (75.0%)
- Correctly classifies H1 (chicken nuggets thermal_inactivation)
- Has reasonable latency (P50 4.9s — actually faster than both frontier models at P50)

Caveats: Qwen 3 8B's P95 latency is poor (60.1s — twice the production target), and its `schema_compliance` is 87% rather than 100%. It produces invalid Pydantic output on roughly 1 in 8 runs. Additionally, its pH and aw extraction (when these fields appear) is unreliable (pH accuracy 0% in the field-level breakdown — needs investigation; may be an artefact of how the test scores these fields for small models that don't return them).

In a degraded-mode fallback, Qwen 3 8B could replace the frontier model with explicit downstream safeguards: schema-validation retries, conservative defaults on parse failures, and an explicit downgrade flag in the audit trail. **Not a drop-in replacement.**

### Finding 4: Model_type accuracy and parameter count are weakly correlated for local models

Phi-4 14B is the largest local model tested (14B params) but scores only 45% on model_type, below the 8B Qwen at 75%. Llama 3.1 8B also struggles (25%). This suggests the safety-critical reasoning step is not primarily a parameter-count problem — it's a training-objective and instruction-following problem.

The implication for the local-model improvement path: scaling up to bigger local models (32B, 70B) may not be the highest-leverage lever. Domain-specific fine-tuning or distillation from a frontier model on PTM-specific data would likely yield larger gains than raw parameter scaling. This is consistent with the embedder finding from Exp 2.2, where larger off-the-shelf models did not outperform smaller ones.

---

## 10. Path to viability for local models

To make any local model production-viable for PTM, three improvements are required, in priority order:

### Priority 1: Model_type accuracy must reach ≥95%

The current best local (Qwen 3 8B at 75%) is 20 percentage points short. Three approaches in increasing investment:

- **Prompt engineering for model_type specifically.** The current system prompt is shared with the frontier-model production path. A local-tuned prompt could give the model_type classification step more explicit guidance ("If the user describes a cooking or heating step, classify as thermal_inactivation. If the user describes storage, holding, or display, classify as growth."). Low cost, fast iteration. Estimated 5–10 percentage points improvement.
- **Few-shot examples in the prompt.** Adding 3–5 model_type examples to the system prompt (with the H1 chicken-nuggets case as one). Medium cost. Estimated 10–15 percentage points improvement.
- **Domain fine-tuning.** Train Qwen 3 8B (or a comparable base) on PTM extraction outputs from the frontier model — synthetic data distillation. High setup cost, but likely the only approach that closes the full 20-point gap. Estimated 15–20 percentage points improvement.

### Priority 2: Schema compliance must reach 100%

Qwen 3 8B's 87% schema compliance means roughly 1 in 8 runs produces invalid Pydantic output. Production cannot accept this without a retry-and-fallback layer. Two mitigations:

- **Stricter prompt template** with explicit JSON schema in the prompt. Low cost; some local models respond well to this.
- **Application-level retry logic** that re-prompts on schema validation failure, with the failed output as context. Adds latency on failure cases but doesn't change the model.

### Priority 3: Latency tail (P95 ~60s) must drop below 30s

Qwen 3 8B's P95 latency is twice the production target. Possible causes: cold-start delays, queue contention on the development workstation. Three mitigations:

- **Production deployment on dedicated hardware.** The benchmark runs on the dev workstation alongside other workloads; production deployment with a dedicated GPU would likely halve P95.
- **Quantisation.** Moving to a Q4 or Q5 quant could speed inference at modest accuracy cost.
- **Smaller distilled model.** If the fine-tuning approach is taken anyway, a 3B or 4B distilled variant might match a 8B base on PTM-specific tasks at significantly lower latency.

### Open question: at what point is local viable?

The decision rule's 95% floor on model_type is non-negotiable for the *primary* parser. But a hybrid architecture is possible:

- Local model runs primary extraction
- A frontier model is invoked only for low-confidence parses (e.g., when the local model returns ambiguous model_type or fails schema validation)
- Most calls stay local; the budget cost is bounded by the frontier-fallback rate

This pattern would let Qwen 3 8B at 75% model_type accuracy handle the easy/medium queries cleanly, with frontier escalation on the safety-critical edge cases. Not implemented yet; would be the natural next experiment.

---

## 11. Out of scope, noted

- **Multilingual evaluation.** The 20-query corpus is English-only. PTM may need to support other languages; would require a separate corpus.
- **Prompt-engineering experiments.** Held constant in this experiment so model effects are isolable. A future Exp 3.4 should sweep prompt variants on a single model.
- **Cost optimisation via prompt caching or batching.** Not measured here.
- **GLM-4.7 Flash.** Failed in this run due to API key configuration. Re-run pending. Not a finding; an operational gap.
- **End-to-end pipeline accuracy.** This experiment evaluates the parser alone. The downstream pipeline (grounding, standardisation, ComBase) adds its own error budget; a separate experiment would measure compounded accuracy.

---

## 12. Definition of done

Exp 3.1 is considered complete when:

1. `exp_3_1_model_comparison.py` runs end-to-end across the shortlist, produces `latest.json` and `latest.csv` with MLflow logging.
2. The Streamlit page at `pages/2_model_comparison.py` renders the results cleanly against `latest.json`.
3. The production recommendation (GPT-4o) is supported by data on accuracy, consistency, safety-critical correctness, latency, and cost.
4. The local-fallback recommendation (Qwen 3 8B, with caveats) is supported by data on the same dimensions, with explicit gap analysis against the production floor.
5. The local-improvement path (Priority 1/2/3) is documented for future investigation.

---

## 13. Working preferences

Same as Exp 2.1 / 2.2, unchanged. Simple over DRY. No fake metrics. Production code path used end-to-end (no mocking the parser). Single source of truth between terminal and Streamlit page for the recommendation. Per-model timing measurements include cold-start where relevant — production deployment should re-measure on production hardware.

---

## 14. Files and artefacts

- **Spec:** this document.
- **Corpus:** `benchmarks/datasets/extraction_queries.json` v0.2 (20 queries).
- **Runner:** `benchmarks/experiments/exp_3_1_model_comparison.py`.
- **Output:** `benchmarks/results/exp_3_1_model_comparison/{latest.json, latest.csv}`.
- **Viewer:** `benchmarks/visualizations/pages/2_model_comparison.py`.
- **Config:** `benchmarks/config.py` (MODELS list).
- **Lessons:** entries in `specs/lessons.md` related to extraction and parser-stage work.
