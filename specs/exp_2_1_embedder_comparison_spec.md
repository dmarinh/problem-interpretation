# Experiment Spec — Embedder Comparison for PTM Retrieval

This document is the working spec for a new benchmark in the PTM benchmark suite. It is written to be opened in a fresh Claude session and worked through interactively, in the same back-and-forth style that produced the FoodEx2 bridge work — checkpoint-by-checkpoint, sketch first, code only after design is approved.

---

## 1. Purpose

PTM's grounding service uses an embedding model to retrieve food properties (pH, water activity) and pathogen hazards from the RAG store. The current production embedder is `all-MiniLM-L6-v2`. Recent investigation surfaced strong evidence that this embedder is the bottleneck for several known retrieval failures — species names not matching category-level reference rows, property-axis cues dominating food-type cues at retrieval time. An empirical Approach B experiment (text-suffix enrichment of category-level rows) failed across the board, with the chicken aw query regressing from 0.7289 to 0.6651 and species queries (turkey, duck, lamb, pheasant) consistently below the 0.62 retrieval gate.

This experiment determines whether a different embedder fixes these failures — and if so, which one, and at what cost. The outcome decides which embedder ships in production. The result will be presented in an upcoming demo, so the experiment must produce a clear comparison chart that stands on its own.

The experiment is **not** a substitute for the FoodEx2 Tier 3 bridge. The bridge addresses an audit-honesty concern (explicit species-to-category citation chain) that no embedder change replaces. The experiment determines whether the bridge needs to fire often, occasionally, or rarely.

---

## 2. What this experiment is and is not

**Is:** an offline retrieval-quality benchmark. For each candidate embedder, re-embed the existing food_properties and pathogen_hazards CSVs into a separate ChromaDB collection, then run a fixed query corpus and measure cosine scores against the documents the queries should match.

**Is not:** an integration test against the live API. We are not regenerating audits. We are measuring raw retrieval quality on labelled query-document pairs at the embedder layer only.

**Not in scope for this experiment:** changing thresholds, modifying the rerank pipeline, modifying the audit shape, modifying the bridge. Those are independent decisions and the data from this experiment may inform them, but they are out of scope here.

**In scope:** evaluating 3-5 candidate embedders against a curated ground-truth query corpus drawn from the test journal and sensitivity-analysis queries, plus a small set of additional species probes (turkey, duck, lamb, pheasant, etc.). Producing a comparison artefact suitable for the demo.

---

## 3. Architectural position in the benchmark suite

This experiment will live alongside `exp_1_1_ph_stochasticity` and `exp_3_1_model_comparison` in the existing benchmark suite, following their conventions:

```
benchmarks/
├── datasets/
│   ├── extraction_queries.json
│   ├── ph_aw_foods.json
│   ├── realistic_queries.json
│   └── retrieval_queries.json                  # NEW — ground-truth corpus for this experiment
├── experiments/
│   ├── exp_1_1_ph_stochasticity.py
│   ├── exp_2_1_embedder_comparison.py          # NEW — this experiment
│   ├── exp_3_1_model_comparison.py
│   └── exp_4_1_realistic_robustness.py
├── results/
│   ├── exp_1_1_ph_stochasticity/
│   ├── exp_2_1_embedder_comparison/             # NEW — output directory
│   │   ├── results_YYYYMMDD_HHMMSS.json
│   │   ├── summary_YYYYMMDD_HHMMSS.csv
│   │   ├── latest.json
│   │   └── latest.csv
│   ├── exp_3_1_model_comparison/
│   └── exp_4_1_realistic_robustness/
├── visualizations/
│   ├── common.py
│   ├── config.py                                # EMBEDDERS constant added here
│   └── pages/
│       └── 4_embedder_comparison.py             # NEW — Streamlit viewer page
└── README.md
```

Naming convention: 1.x = data-quality, **2.x = retrieval-quality (this experiment fills this slot)**, 3.x = LLM-quality, 4.x = robustness. The `exp_2_1` slot is currently empty in the existing tree, so this experiment fits cleanly. Confirm with Daniel at checkpoint 1 if a different number is preferred.

Once added, the runner page (`3_run_experiments.py`) will pick it up automatically because the runner scans the `experiments/` folder for `exp_*.py` files.

---

## 4. Candidate embedders

Initial proposed shortlist for the demo (3 minimum, 5 maximum). Daniel to confirm or revise during checkpoint 1.

| ID | HF model name | Params | Dim | Why include |
|----|---------------|--------|-----|-------------|
| `minilm-l6-v2` | `sentence-transformers/all-MiniLM-L6-v2` | 22M | 384 | **Baseline (current production)**. Must be included for like-for-like comparison. |
| `mpnet-base-v2` | `sentence-transformers/all-mpnet-base-v2` | 110M | 768 | The mainstream SBERT upgrade. 5× larger, generally considered the strongest English-only general-purpose sentence embedder in the SBERT family. |
| `bge-small-en-v1.5` | `BAAI/bge-small-en-v1.5` | 33M | 384 | MiniLM-comparable size, retrieval-optimised (vs general semantic similarity). Currently top of MTEB benchmark for its size class. |
| `bge-base-en-v1.5` | `BAAI/bge-base-en-v1.5` | 109M | 768 | mpnet-comparable size, retrieval-optimised. Likely the strongest single candidate. |
| `e5-small-v2` | `intfloat/e5-small-v2` | 33M | 384 | Microsoft's retrieval-tuned family. Uses prefix instructions ("query: " / "passage: ") which the experiment harness must handle if included. |

Three caveats Daniel may want to weigh:

- **e5 prefix instructions.** e5 models are trained with `query: ` and `passage: ` prefixes prepended to inputs. Using them without prefixes degrades performance. If e5 is included, the harness needs a small per-embedder hook for input formatting. Adds complexity. Could be deferred to a v2 of this experiment.
- **Domain-specific food-science embedders.** None known to be strong off-the-shelf. Out of scope unless Daniel knows of one.
- **API-based embedders** (OpenAI text-embedding-3-small/large, Cohere, Voyage). Out of scope for an MVP — adds API-cost considerations and runtime dependency. Worth flagging as a "v2 of this experiment" item if the open-weight models prove insufficient.

The MVP shortlist I'd lean toward: **minilm-l6 (baseline), bge-small (same size as MiniLM, retrieval-tuned), bge-base (larger retrieval-tuned), mpnet-base (larger general-purpose)**. Four embedders, two model sizes × two training objectives, makes for a clean 2×2 demo chart.

---

## 5. Ground-truth query corpus

The experiment needs labelled `(query, expected_document_id)` pairs. Source these from three places:

1. **Existing test journal queries (Q01–Q17).** The simple-query session that exercises pH/aw retrieval against known food_properties rows. Each query has a known correct retrieval document from the test journal. Approximately 8-12 of the 17 queries are retrieval-relevant (those that should match a food_properties row).

2. **Sensitivity-analysis queries with confirmed retrieval expectations.** From `sensitivity_analysis_queries.md`, the queries A1, A2, B1, B2, C1 with known expected matches. The audits already captured during Tier 3 testing record the doc_id that should match for each query (e.g., B1 → `food_properties_24` chicken for pH, `food_properties_26` fresh poultry for aw).

3. **Species probe queries.** Short ad-hoc queries designed to exercise the species-to-category bridge in retrieval. Suggested set: turkey, duck, goose, pheasant, lamb, mutton, pork, veal, salmon, tuna, oyster, scallop. For each, the expected match is the relevant category-level row (`fresh poultry`, `fresh meat`, `fish fresh most` if it exists, `fresh poultry`, etc.).

Total target: 30–40 query-document pairs covering pH retrieval, aw retrieval, and pathogen-hazard retrieval. The exact count is finalised at checkpoint 1.

The corpus lives in `benchmarks/datasets/retrieval_queries.json`. Suggested schema:

**Note for checkpoint 2:** `benchmarks/datasets/realistic_queries.json` already exists in the tree and may contain queries reusable for this corpus — open it before drafting `retrieval_queries.json` from scratch. Possible outcomes: (a) reuse `realistic_queries.json` directly if its structure fits, (b) extend it with the species probes and add `expected_doc_id` annotations, (c) keep `retrieval_queries.json` as a separate file specifically for retrieval-evaluation purposes. Daniel's call.

```json
{
  "version": "1.0",
  "queries": [
    {
      "id": "Q01",
      "query": "fresh chicken portions pH acidity",
      "field": "ph",
      "expected_doc_id": "food_properties_24",
      "expected_doc_text_hint": "chicken (poultry): pH range 6.2 to 6.4",
      "tier": "easy",
      "source": "test_journal_Q01"
    },
    {
      "id": "SP01",
      "query": "turkey portions pH acidity",
      "field": "ph",
      "expected_doc_id": "food_properties_24",
      "expected_doc_text_hint": "chicken (poultry): pH range 6.2 to 6.4",
      "tier": "hard",
      "source": "species_probe",
      "comment": "Bridge case: turkey has no own row; expected match is the chicken category-level row"
    }
  ]
}
```

The `expected_doc_id` is the doc_id the retrieval should rank first. The `tier` field (easy/medium/hard) lets the comparison chart stratify results by query difficulty, mirroring the convention from exp_3_1 and exp_1_1. The `expected_doc_text_hint` is for human verification — the experiment harness checks `expected_doc_id` only.

**Open question for checkpoint 1:** for queries where multiple doc_ids would be acceptable (e.g., a turkey query could match either chicken pH or fresh poultry pH if both existed), should the schema support a list of acceptable doc_ids, or one canonical answer? Recommend list-of-acceptable for flexibility, with the first one being the canonical-best match.

---

## 6. Experiment script structure

The script `benchmarks/experiments/exp_2_1_embedder_comparison.py` follows the same skeleton as `exp_1_1_ph_stochasticity.py` and `exp_3_1_model_comparison.py`. Key adaptations:

### Skeleton (mirroring exp_1_1)

```
1. Module docstring with METRICS GUIDE explaining what each metric means
2. Imports + path setup (PROJECT_ROOT, dotenv)
3. EXPERIMENT_ID = "exp_2_1_embedder_comparison"
4. No token tracking (different from exp_1_1 — embedders are local, no cost beyond compute)
5. load_queries() — reads retrieval_queries.json
6. configure_embedder(embedder_config) — instantiates the embedder; wraps the SentenceTransformer load
7. embed_corpus(embedder, documents) — embeds the food_properties + pathogen_hazards corpus into a temporary collection
8. run_query(embedder, collection, query) — embeds query, searches collection, returns top-K with scores
9. score_query(retrieved, expected_doc_id) — produces per-query metrics: top1_correct, top3_correct, top1_score, expected_doc_rank, expected_doc_score
10. compute_embedder_stats(query_results) — aggregates per-embedder metrics
11. run_experiment(embedders, queries) — main loop
12. save_results, log_to_mlflow, print_summary, main, argparse
```

### Per-query metrics

For each (embedder, query) pair, record:

- `top1_doc_id` — the doc_id ranked #1
- `top1_score` — cosine similarity of the #1 result
- `top3_doc_ids` — list of top-3 doc_ids
- `expected_doc_id` — from corpus
- `expected_rank` — 1-indexed rank of expected doc in retrieval (or null if not in top-K)
- `expected_score` — cosine similarity of the expected doc (or null)
- `correct@1` — boolean (top1_doc_id == expected_doc_id)
- `correct@3` — boolean (expected_doc_id in top3_doc_ids)
- `score_above_062` — boolean (does expected_score clear the current 0.62 gate?)
- `score_above_070` — boolean (does expected_score clear the 0.70 Tier 1 gate?)

### Per-embedder summary metrics

- `top1_accuracy` — fraction of queries where the top-1 result was correct
- `top3_accuracy` — fraction in top-3
- `mean_expected_score` — average cosine of the expected doc across queries
- `gate_062_pass_rate` — fraction of queries where the expected doc score ≥ 0.62
- `gate_070_pass_rate` — fraction where ≥ 0.70
- `mean_query_latency_ms` — embed + search latency
- `embedder_load_time_s` — one-time model load (relevant for cold-start cost)
- `corpus_embed_time_s` — one-time corpus embed
- Stratified accuracy by tier (easy / medium / hard) — same as exp_3_1

### Critical implementation note: corpus isolation per embedder

Each embedder runs against its own ChromaDB collection — embedders produce different-dimension vectors, so they cannot share storage. The harness must:

1. Create a fresh collection per embedder (named e.g. `experiment_minilm_l6_v2`)
2. Embed the food_properties + pathogen_hazards corpus into that collection
3. Run all queries against that collection
4. Drop the collection after the embedder's queries are done (or keep all collections; document the choice; storage cost is ~5MB per embedder so keeping is fine)

Use a temporary ChromaDB instance under `benchmarks/results/exp_2_1_embedder_comparison/_chroma/` rather than the production ChromaDB store, so this experiment never touches the live RAG.

### CLI shape (mirrors exp_1_1)

```
python -m benchmarks.experiments.exp_2_1_embedder_comparison
python -m benchmarks.experiments.exp_2_1_embedder_comparison --embedders minilm-l6-v2,bge-base-en-v1.5
python -m benchmarks.experiments.exp_2_1_embedder_comparison --queries-subset hard
python -m benchmarks.experiments.exp_2_1_embedder_comparison --top-k 5
python -m benchmarks.experiments.exp_2_1_embedder_comparison --no-mlflow
```

---

## 7. Configuration: `benchmarks/visualizations/config.py`

Add an `EMBEDDERS` constant alongside the existing `MODELS`. Note the location — the existing `config.py` lives under `benchmarks/visualizations/`, not directly under `benchmarks/`. Confirm at checkpoint 1 that this is the right place to add `EMBEDDERS` (or whether `MODELS` is imported from somewhere else and a different file is canonical).

Suggested shape (mirrors `MODELS`):

```python
EMBEDDERS = [
    {
        "id": "minilm-l6-v2",
        "name": "all-MiniLM-L6-v2 (baseline)",
        "hf_model": "sentence-transformers/all-MiniLM-L6-v2",
        "dim": 384,
        "params_m": 22,
        "is_baseline": True,
        "input_prefix_query": None,    # for e5; None means no prefix
        "input_prefix_passage": None,
    },
    {
        "id": "bge-small-en-v1.5",
        "name": "BGE small EN v1.5",
        "hf_model": "BAAI/bge-small-en-v1.5",
        "dim": 384,
        "params_m": 33,
        "is_baseline": False,
        "input_prefix_query": None,
        "input_prefix_passage": None,
    },
    # ... etc
]
```

The `is_baseline` flag is used by the viewer to highlight the baseline row. The two `input_prefix_*` slots are forward-looking for e5 support; can stay `None` for the MVP shortlist.

---

## 8. Streamlit viewer page

Mirroring the structure of `exp_3_1_model_comparison.py`'s viewer, the page tells a clear story for the demo:

> "Here's the retrieval problem we identified. Here are the candidate embedders. Here's how each one performs on the queries that matter. Here's the recommendation."

### Section 1 — Run information
Timestamp, embedders tested, query count, corpus size.

### Section 2 — Summary table
One row per embedder. Columns: name, tier (size class), top-1 accuracy, top-3 accuracy, gate@0.62 pass rate, gate@0.70 pass rate, mean expected score, mean query latency, baseline comparison column (Δ vs minilm-l6-v2). Sort by top-1 accuracy descending. Highlight the baseline row.

### Section 3 — The decision chart (THE KEY CHART)
Scatter plot. X-axis: embedder size (params, log scale). Y-axis: top-1 accuracy. One point per embedder, labelled with name. Colour by training objective (general vs retrieval-optimised). Horizontal dashed line at the baseline's top-1 accuracy. Horizontal dashed line at the desired threshold (0.90 or wherever Daniel sets it). The visual should make it obvious whether any candidate clearly dominates the baseline.

### Section 4 — Score distribution by query
Box plot or strip plot. X-axis: embedder. Y-axis: expected_doc_score (cosine). Horizontal lines at 0.62 and 0.70 (current Tier 2 and Tier 1 gates). One marker per query per embedder; jittered for legibility. The visual answers: "for this embedder, where do the expected-doc scores actually cluster?" Knife-edge results around the gate are visible at a glance.

### Section 5 — Accuracy by tier
Grouped bar chart. X-axis: tier (easy/medium/hard). Y-axis: top-1 accuracy. One bar per embedder, grouped by tier. Mirrors exp_3_1's tier chart.

### Section 6 — Gate pass-rate comparison
Two grouped bar charts side by side. Left: fraction of queries where expected_score ≥ 0.62 (Tier 2 gate). Right: fraction ≥ 0.70 (Tier 1 gate). One bar per embedder. Annotated with the count.

### Section 7 — Per-query breakdown (deep dive)
Dropdown to select a query. Shows the query text, expected doc, and a table: one row per embedder with columns (top-1 doc, top-1 score, expected rank, expected score, correct@1). Click-through to expand the top-3 retrieved docs for diagnosis.

### Section 8 — Failure analysis
Auto-generated text:
- "Queries where the baseline fails but at least one candidate succeeds: [N]. Examples: [...]"
- "Queries where all embedders fail: [N]. These are likely candidates for the FoodEx2 bridge fallback."
- "Queries where the baseline succeeds but a candidate fails: [N]. Switching costs."

### Section 9 — Recommendation
Auto-generated:
- "Recommended for production: [embedder with best top-1 accuracy among those with mean latency < threshold and acceptable load time]"
- "Marginal improvement vs. baseline: [Δ top-1, Δ gate-pass-rate]"
- "Cost of the change: re-embedding corpus, rebuilding ChromaDB store, regression-testing existing audits"

---

## 9. Working approach for the new session

This experiment is being built in a fresh Claude session. The interaction style follows the FoodEx2 bridge work's convention: checkpoint-by-checkpoint, sketch first, code only after design is approved. The expected sequence:

**Checkpoint 1 — design sketch (no code).** The session reads:
- This spec document
- `exp_1_1_ph_stochasticity.py` (skeleton reference)
- `exp_3_1_model_comparison.py` (skeleton reference)
- `visualization_specs.md` (viewer page conventions)
- `benchmarks/visualizations/config.py` (current MODELS shape)
- The relevant PTM context: `ptm_context.md` §5 (retrieval architecture)

The session produces a sketch covering: final embedder shortlist, final query corpus structure, draft `EMBEDDERS` config block, draft script section list, draft viewer page section list. It surfaces any gap or ambiguity from this spec for Daniel to resolve. No code yet. Wait for approval.

**Checkpoint 2 — query corpus.** The session compiles the query corpus from the journal/sensitivity sources plus species probes, writes `retrieval_queries.json`, and shows Daniel the full list before any retrieval code is written. Daniel approves or revises. The corpus is the experiment's foundation; it is finalised before anything else.

**Checkpoint 3 — failing tests.** The session writes test files for the harness (corpus loading, per-query scoring, per-embedder aggregation) that fail because the implementation doesn't exist. Daniel reviews the test list before implementation.

**Checkpoint 4 — implementation passes tests.** Including: embedder load, corpus embed into isolated ChromaDB collection, query loop, per-query metrics, per-embedder summary, JSON+CSV save, MLflow integration, summary print.

**Checkpoint 5 — first run on real data.** Run with the full embedder shortlist against the full query corpus. Capture timings, scores, accuracy. Daniel reviews the raw output and the structure of `latest.json`. Adjust if anything is off.

**Checkpoint 6 — Streamlit viewer page.** Build `4_embedder_comparison.py` mirroring exp_3_1's viewer conventions. Verify all 9 sections render against the real `latest.json`.

**Checkpoint 7 — demo polish.** Final adjustments to chart annotations, recommendation text, table formatting. Confirm the page tells the story Daniel wants for the advisory-board demo.

After checkpoint 7, Daniel returns to the main session to finish Tier 3 (restrict the bridge to category-level rows only, add an environment-variable switch to enable/disable Tier 3 in production). The embedder experiment's outcome informs how often Tier 3 will fire in practice and therefore how much weight the bridge's correctness needs to carry.

---

## 10. Working preferences (Daniel's, per `ptm_context.md` §1.4)

- Simple over DRY. Readable code. No premature abstractions. If two functions need similar logic with small variations, duplicate rather than abstract.
- Plan-first for non-trivial changes. Sketch the design, agree it, then code.
- Ask clarifying questions rather than make assumptions. Especially around: the final embedder shortlist, the query corpus contents, anything that touches the existing benchmark `config.py`.
- No fake metrics. If a query has no clean expected document, mark it as such in the corpus rather than picking an arbitrary one.
- TDD: failing tests before implementation; the test list is itself a design checkpoint.

---

## 11. Critical findings already on the table

These came out of recent investigation and inform the experiment's design:

1. **The current MiniLM-L6 produces "fresh poultry" at cosine 0.6042 against "fresh chicken portions" — below the 0.70 Tier 1 gate even for the canonical case.** The chicken row clears the Tier 2 gate at 0.6912, but only narrowly. Baseline retrieval is fragile.

2. **For non-chicken poultry queries (turkey, duck, lamb, pheasant), MiniLM consistently lands on completely unrelated documents** for pH retrieval — chili sauce acidified, beets canned acidified, acidophilus milk. The query expansion ("...pH acidity") pulls toward acidic-food rows independently of food-type. This is the strongest single signal that the embedder is the bottleneck rather than the data.

3. **The Approach B text-suffix enrichment experiment (run 2026-05-07) failed across the board.** Enriching the fresh poultry row's embedded text with species names hurt the canonical chicken aw case (Δ = -0.064) and did not lift any species query above the 0.62 gate. Pheasant aw came closest at 0.6134.

4. **Tier 3 (FoodEx2 bridge) is implemented and working** on a feature branch. It currently fires for any query whose food matches the FoodEx2 taxonomy and whose category has any food_properties rows; it inherits values via conservative-bound-across-rows (a known weakness — see point 5). The bridge's existence does not depend on the outcome of this experiment.

5. **An open architectural decision (deferred until after this experiment):** restrict Tier 3 to inheriting only from explicit category-level rows in food_properties (`fresh poultry`, `fresh meat`, `cured meat`, `fish fresh most`, etc.) and remove the conservative-bound-across-arbitrary-rows logic. The Tier 3 bridge becomes a transparent citation chain rather than an intelligent guesser. The decision will be taken in the main session after this embedder experiment concludes — the experiment's data may shift the calculation about how often Tier 3 needs to fire and therefore how strict the restriction should be.

These findings are the experiment's motivation. They should appear in the eventual demo narrative as the "why we ran this" framing.

---

## 12. Out-of-scope, but worth noting

These are deliberately deferred and should not be attempted in this experiment:

- **Cross-encoder rerank tuning.** The reranker is a separate stage from the embedder and has its own threshold/architecture decisions. Out of scope.
- **API-based embedders** (OpenAI, Cohere, Voyage). MVP is open-weight only. Worth a v2 of this experiment if open-weight options are insufficient.
- **Domain-fine-tuning** of an embedder on PTM's corpus. Larger investigation.
- **Hybrid retrieval** (BM25 + dense). Possibly informative but architecturally invasive.
- **Threshold recalibration** (the planned Session 2 work). Independent question; this experiment's data feeds into it but does not preempt it.

---

## 13. Definition of done

The experiment is complete when:

1. `exp_2_1_embedder_comparison.py` runs end-to-end against the full shortlist, produces `latest.json` and `latest.csv`.
2. The Streamlit viewer page renders all 9 sections cleanly against the real results.
3. Daniel can demo the page to the advisory board: open the dashboard, navigate to the page, and walk through the recommendation in <5 minutes.
4. The recommendation answers: "Should production switch from MiniLM-L6 to [X], and at what cost?"
5. The data informs the open architectural decision about Tier 3 restriction strictness.

---
