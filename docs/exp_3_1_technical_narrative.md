# PTM Model Selection — Technical Narrative (Exp 3.1)

For Daniel and future Claude sessions. Comprehensive record of the model-comparison experiment, the findings that survived, the local-model improvement path, and the unresolved questions. Read this first when picking up the LLM-quality workstream.

---

## 1. The starting question

PTM's semantic parser converts natural-language scenarios into structured `ExtractedScenario` Pydantic objects. The parser sits at the entry of the pipeline; errors here propagate downstream and can reverse the system's conservative-bias direction (a misclassified thermal scenario gets treated as growth, picking the wrong worst-case bound).

The model behind the parser was production-set at GPT-4o based on early development. As the project moves toward a public-facing MVP, three things motivated a formal evaluation:

1. **Validate the production choice empirically.** Is GPT-4o still the right pick now that newer frontier models exist?
2. **Characterise the budget-constrained alternative.** If frontier API access becomes a budget constraint (likely for the long-term deployment plan), what's the best viable local model?
3. **Identify the improvement path for local models.** What would it take to make a local model production-viable?

Exp 3.1 was designed to answer all three.

---

## 2. The design

End-to-end evaluation of the **real** `SemanticParser` (production code path, production system prompt, production Pydantic schema) against a 20-query expert-annotated corpus. Seven models tested, one excluded due to API-key configuration. Each query run 20 times per model to measure both accuracy (correctness) and consistency (run-to-run agreement).

Two structural choices worth flagging:

- **Production code path, no mocking.** The benchmark calls `SemanticParser` exactly as production would. This makes the measurements representative; it also means a parser bug surfaces in both production and the benchmark, which is the right behaviour.
- **Field-level scoring with safety-critical distinction.** The `model_type` field gets its own tracking (`model_type_accuracy`, `model_type_errors`). A wrong model_type classification reverses conservative-bias direction — it's not just one more field, it's the single most dangerous error mode. Range preservation (`range_preserved`) gets similar treatment.

The 20 queries span easy / medium / hard difficulty tiers and include adversarial cases drawn from PTM's known failure history:

- **H1 — the chicken-nuggets bug.** "Chicken nuggets reached about 68°C instead of 74°C, held for roughly 8 minutes. Are they safe?" Must classify as `thermal_inactivation`. A `growth` classification flips the safety verdict.
- **H2 — temperature range.** "The refrigeration chamber for the turkey broke. It was between 10 and 15 degrees for about 4 hours." Must extract as a range with `is_range=true`, not collapse to a midpoint.
- **N1 — non-prediction probe.** "What temperature kills bacteria?" Tests whether the parser produces minimal extraction on information queries. If it invents a food or pathogen, that's hallucination.

---

## 3. Results

### Headline metrics

| Model | Class | Overall | Consistency | model_type | P95 lat | Cost/call |
|---|---|---|---|---|---|---|
| **GPT-4o** | frontier | **96.0%** | **99.7%** | **90.0%** | 28.5s | **$0.014** |
| GPT-5.5 | frontier | 95.5% | 99.4% | 90.0% | 16.9s | $0.026 |
| Qwen 3 8B | local | 79.8% | 98.1% | 75.0% | 60.1s | $0.000 |
| Phi-4 14B | local | 78.6% | 99.1% | 45.0% | 38.6s | $0.000 |
| Llama 3.1 8B Instruct | local | 69.7% | 100.0% | 25.0% | 20.3s | $0.000 |
| Gemma4 E4B | local | 51.8% | 100.0% | 5.0% | 74.8s | $0.000 |

GLM-4.7 Flash excluded (API key configuration issue, re-run pending).

### Stratified accuracy

| Model | Easy | Medium | Hard |
|---|---|---|---|
| GPT-5.5 | 100.0% | 92.4% | 95.4% |
| GPT-4o | 100.0% | 97.1% | 92.6% |
| Qwen 3 8B | 78.4% | 81.9% | 68.8% |
| Phi-4 14B | 83.3% | 77.5% | 76.6% |
| Llama 3.1 8B Instruct | 74.7% | 66.5% | 69.5% |
| Gemma4 E4B | 38.8% | 55.1% | 56.9% |

### model_type errors per model

| Model | n | Misclassified IDs |
|---|---|---|
| GPT-5.5 | 2 | H3, N1 |
| GPT-4o | 2 | H6, N1 |
| Qwen 3 8B | 5 | M2, M4, H3, N1 |
| Phi-4 14B | 11 | M2, M3, M5, H1, H2, H3, H4, H5, H7, H8, N1 |
| Llama 3.1 8B Instruct | 15 | E2, E4, M1–M6, H1, H2, H3, H5, H6, H7, N1 |
| Gemma4 E4B | 19 | almost everything |

### H1 specifically — the chicken-nuggets safety-critical case

| Model | Got it right? |
|---|---|
| GPT-5.5 | ✓ |
| GPT-4o | ✓ |
| Qwen 3 8B | ✓ |
| Phi-4 14B | ✗ |
| Llama 3.1 8B Instruct | ✗ |
| Gemma4 E4B | ✗ |

### H2 specifically — temperature range preservation

All six models correctly preserved the range. The Pydantic schema makes this hard to get wrong if schema compliance is intact — `is_range: bool` plus `range_min` and `range_max` is a simple structured request. The conservative-bound selection happens downstream in `StandardizationService`, not in the parser.

---

## 4. Findings

### Finding 1: GPT-4o is the production recommendation

GPT-4o wins on accuracy (96.0% — highest of all six), perfect easy-tier (100%), highest medium-tier (97.1%), cheapest per call ($0.014, vs GPT-5.5 at $0.026), and meets the safety-critical floor (90% model_type — tied with GPT-5.5). P95 latency at 28.5s sits just under the 30s target.

GPT-5.5 is close on accuracy (95.5%) and slightly better on hard-tier (95.4% vs 92.6%), but the cost asymmetry (86% more per call) and weaker medium-tier accuracy tip the production decision toward GPT-4o. **No reason to switch from the current production model.**

### Finding 2: No local model meets the safety-critical floor

The decision rule requires `model_type_accuracy ≥ 95%`. Best local: Qwen 3 8B at 75%. Gap: 20 percentage points.

Other local models drop sharply: Phi-4 14B at 45%, Llama 3.1 8B at 25%, Gemma4 E4B at 5%. **None are deployable** for the primary parser role under the current decision rule.

### Finding 3: Qwen 3 8B is the best fallback candidate

In a budget-constrained or sovereignty-constrained scenario where frontier APIs are unavailable, Qwen 3 8B is the closest viable fallback:

- Highest local model_type accuracy (75% — vs 45% / 25% / 5% for the others)
- Highest local overall accuracy among non-Phi candidates (79.8%)
- Correctly handles H1 (chicken nuggets — gets the safety-critical thermal_inactivation classification right)
- Fast at P50 (4.9s — faster than both frontier models)

Caveats that prevent drop-in replacement:

- **Schema compliance only 87%.** Roughly 1 in 8 calls produces invalid Pydantic output. Production cannot accept this without an application-level retry layer.
- **P95 latency 60.1s.** Twice the 30s production target. Likely cause: dev-workstation contention (shared GPU with other workloads).
- **pH/aw field accuracy 0%.** In the field-level breakdown, Qwen 3 8B scores 0% on pH and 50% on aw. Needs investigation; may be an artefact of how the test scores fields the model omits entirely, or a genuine inability to extract numeric values when they appear in compound clauses. Not safety-critical for parser-stage work (RAG grounds these fields later), but worth understanding.
- **Misclassifies M2, M4, H3, N1 on model_type.** M2 and M4 are vague conversational scenarios; H3 is genuinely ambiguous; N1 is the non-prediction probe. The error pattern suggests Qwen 3 8B is overconfident on vague inputs — it classifies even when classification isn't warranted.

### Finding 4: Parameter count is not the bottleneck

Phi-4 14B is the largest local model tested but scores 45% on model_type — substantially below Qwen 3 8B at 75%. This is consistent with the embedder finding from Exp 2.2, where larger off-the-shelf models did not outperform smaller ones on the PTM-specific task.

The implication: **scaling up local model size is unlikely to be the highest-leverage improvement lever.** A 32B or 70B local model would consume substantially more resources without a clear path to the 95% safety floor.

### Finding 5: Consistency is high across all models

Run-to-run consistency on identical inputs is 98–100% for every model. Even Gemma4 (5% accuracy on model_type) is 100% consistent — it gets it wrong, but it gets it wrong the same way every time. This means the failures are systematic, not stochastic. Important consequence for fine-tuning: a model that consistently misclassifies has a learnable error pattern; a model that randomly fluctuates does not.

### Finding 6: N1 trips every model

The non-prediction probe ("What temperature kills bacteria?") trips every single model on the `model_type` field. The parser is producing a model_type classification even when the query isn't asking for a prediction. This is a prompt-design issue, not a model-capability issue — the system prompt likely doesn't tell the parser "if this isn't a prediction request, return null for model_type". Worth fixing in the next prompt iteration; the fix is universal across models.

---

## 5. Local-model improvement path

To make a local model production-viable, three improvements are needed, in priority order. Estimated impact in parentheses.

### Priority 1: model_type accuracy must reach ≥95% (currently 75% on Qwen)

Gap: 20 percentage points. Three approaches in increasing investment:

- **Prompt engineering for model_type specifically.** Inject explicit classification guidance for the local model variant ("If the user describes cooking, heating, or pasteurisation, classify as thermal_inactivation. If the user describes storage, holding, display, or temperature abuse, classify as growth."). Cost: low. Estimated gain: 5–10 points.
- **Few-shot examples in the prompt.** Add 3–5 model_type examples with explicit reasoning, including the H1 chicken-nuggets case. Cost: medium. Estimated gain: 10–15 points.
- **Domain fine-tuning via synthetic distillation.** Generate ~1000 PTM-style queries, get GPT-4o to extract them, train Qwen 3 8B on the (query, extraction) pairs. Cost: ~1–2 weeks of work plus GPU time. Estimated gain: 15–20 points — likely the only path to clearing 95%.

The fine-tuning approach is also the basis for a smaller distilled model (3B or 4B) that could match Qwen 3 8B's accuracy at significantly lower latency. The 60s P95 latency on Qwen would not survive on hardware that has to also run the rest of the application.

### Priority 2: Schema compliance must reach 100% (currently 87% on Qwen)

Three mitigations:

- **Stricter prompt template.** Include the JSON schema explicitly in the prompt. Some local models respond well to this; tested briefly during the 2.2 work, gave a small lift.
- **Application-level retry logic.** Re-prompt on Pydantic validation failure, with the failed output as context. Adds latency on failure cases.
- **Use Instructor in "structured-output" mode** with json_schema-enforced inference where supported. Currently using TOOLS mode for the frontier models; some local models support a different mode that's more constrained.

### Priority 3: P95 latency must drop below 30s (currently 60s on Qwen)

Most likely a hardware/contention issue rather than a model issue:

- **Production deployment on dedicated hardware.** The benchmark runs on Daniel's dev workstation (8GB VRAM, sharing GPU with other workloads). Production hardware would likely halve P95.
- **Quantisation.** Q4 or Q5 quantisation could speed inference at modest accuracy cost. Worth testing as part of the same benchmark.
- **Distilled smaller model.** If priority 1's fine-tuning route is taken, a 3B/4B distilled model would likely solve this naturally.

### A different path: hybrid architecture

Rather than making any single local model viable for the entire parser role, a hybrid pattern is possible:

- Local model (Qwen 3 8B + better prompting) handles primary extraction
- A "confidence gate" detects ambiguous outputs — schema validation failure, low-confidence model_type, hard-tier query patterns
- Frontier model (GPT-4o) is invoked only on the gate-flagged subset
- Most calls stay local; cost is bounded by the frontier-fallback rate

Estimated fallback rate: ~20–30% based on Qwen 3 8B's current error pattern. If true, this halves API costs vs frontier-only while preserving safety-critical correctness on the cases that need it. **Probably the most pragmatic next step** if local-only viability proves to be 6+ months out.

This is the natural next experiment (Exp 3.4 or 3.5).

---

## 6. Things worth knowing about the experiment itself

### What worked well

- **Production code path, end-to-end.** Calling the real `SemanticParser` avoided the "the test passes but production behaves differently" trap. Worth keeping for future model-comparison experiments.
- **Field-level scoring with safety-critical distinction.** Without `model_type_accuracy` as a separately-tracked metric, GPT-4o and Phi-4 14B look like (96% vs 78.6% overall) a 17-point gap. With model_type tracked, it's (90% vs 45%) a 45-point gap. The right metric for the production decision is the safety-critical one.
- **20 runs per query.** Sufficient to characterise consistency. Below this (e.g., N=5), small-sample noise would obscure the consistency rankings.

### What was less effective

- **N1 (non-prediction probe) is in the corpus but the parser isn't designed to handle it.** Every model gets model_type wrong on N1. The N1 result tells us about prompt design, not about the model. Should be flagged as a "prompt-design failure mode" in the corpus metadata rather than scored as a per-model error.
- **The 0% pH accuracy on Qwen 3 8B is suspicious.** Could be a genuine model limitation or could be an artefact of how the test scores fields the model doesn't return (returning null might be scored differently than returning an incorrect value). Worth a one-hour investigation.
- **GLM-4.7 Flash failed silently in this run.** API key configuration issue; the experiment continued and logged a malformed-result row instead of stopping. Worth adding a startup-check that validates each model can return at least one valid response before committing to the full run.

### What was not measured

- **End-to-end pipeline accuracy.** The parser is one stage; grounding, standardisation, and ComBase execution all add their own error budgets. A pipeline-level accuracy number would be lower than the parser-level one.
- **Cold-start vs warm-cache latency.** Frontier model latency includes network round-trip; local model latency includes model load time on first call. Both effects are partly captured in P95 but not isolated.
- **Cost projections at production scale.** Per-call cost is reported but scaling to (e.g.) 1000 calls/day depends on user behaviour that this experiment doesn't model.

---

## 7. What the data does and doesn't support

**Supports:**

- "GPT-4o is the right production model under current cost and accuracy constraints."
- "No local model in the shortlist is currently viable as a primary parser."
- "Qwen 3 8B is the closest local fallback, with non-trivial caveats."
- "Larger local models are not automatically better for PTM-specific reasoning."
- "Model_type classification is the bottleneck for local viability, not other fields."

**Does not support:**

- "A fine-tuned Qwen will hit 95% model_type accuracy." (This is a hypothesis, not yet tested.)
- "GPT-5.5 is worse than GPT-4o." (They are within sampling noise on overall accuracy; the production tie-break is cost.)
- "Schema compliance issues are systematic for local models." (Only Qwen showed schema problems; the others were at 100%. Pattern is single-model, not class-wide.)

---

## 8. The unresolved questions, ranked

1. **Does a fine-tuned local model reach the 95% floor?** Highest-value open question. Requires building the synthetic distillation pipeline. ~1–2 weeks of work for a first iteration.
2. **Is the hybrid (local-primary + frontier-fallback) architecture viable?** Smaller experiment, can be prototyped in a few days. Should be informed by the answer to #1 — if fine-tuning closes the gap, hybrid is unnecessary; if not, hybrid is the pragmatic path.
3. **What's the right prompt for the local-model variant?** N=1 prompt-engineering experiment on a single local model would tell us how much of the 20-point gap is prompt-design vs model-capability.
4. **GLM-4.7 Flash re-run** to fill the gap in the comparison.
5. **N1 prompt-design fix.** Add explicit handling for non-prediction queries in the system prompt and re-measure.
6. **pH field investigation on Qwen 3 8B.** One-hour debug session to understand the 0% pH accuracy.

---

## 9. Files and artefacts

- **Spec:** `exp_3_1_model_comparison_spec.md`.
- **Corpus:** `benchmarks/datasets/extraction_queries.json` v0.2 (20 queries).
- **Runner:** `benchmarks/experiments/exp_3_1_model_comparison.py`.
- **Output:** `benchmarks/results/exp_3_1_model_comparison/{latest.json, latest.csv}`.
- **Viewer:** `benchmarks/visualizations/pages/2_model_comparison.py`.
- **Config:** `benchmarks/config.py` (MODELS list).

The LLM-quality workstream remains open on the six questions in §8. The production decision (GPT-4o) is locked. The local-fallback recommendation (Qwen 3 8B with caveats) is locked. The improvement path (fine-tuning, then hybrid) is identified but not yet executed.
