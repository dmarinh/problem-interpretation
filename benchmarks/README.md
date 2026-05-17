# Benchmark Suite

Reproducible experiments for design decision justification. Each experiment
proves a specific claim about the system's architecture by generating
quantitative evidence that can be reviewed in the Streamlit dashboard.

## Structure

```
benchmarks/
├── config.py                           # Models, embedders, shared paths
├── datasets/
│   ├── extraction_queries.json         # 20 queries with expert ground truth
│   ├── ph_aw_foods.json               # 15 foods across 3 difficulty tiers
│   └── retrieval_queries.json         # 30 retrieval ground-truth queries (Exp 2.1)
├── experiments/
│   ├── exp_1_1_ph_stochasticity.py    # pH stochasticity Monte Carlo
│   ├── exp_2_1_embedder_comparison.py  # Sentence-transformer embedder selection
│   └── exp_3_1_model_comparison.py     # LLM model selection benchmark
├── results/                            # Timestamped outputs
│   ├── exp_1_1_ph_stochasticity/
│   │   ├── results_YYYYMMDD_HHMMSS.json
│   │   └── latest.json
│   ├── exp_2_1_embedder_comparison/
│   │   ├── results_YYYYMMDD_HHMMSS.json  # Full data (dict, not list)
│   │   ├── summary_YYYYMMDD_HHMMSS.csv   # One row per embedder
│   │   ├── latest.json / latest.csv
│   │   └── _chroma/<embedder_id>/         # Isolated ChromaDB (safe to delete)
│   └── exp_3_1_model_comparison/
│       ├── results_YYYYMMDD_HHMMSS.json
│       ├── summary_YYYYMMDD_HHMMSS.csv
│       ├── latest.json
│       └── latest.csv
└── visualizations/                     # Streamlit dashboard
    ├── app.py                          # Entry point
    ├── lib/                            # Charts, data loading, runner
    └── pages/                          # Dashboard pages
```

## Experiments

### Exp 2.1 — Embedder Comparison

**Claim:** The production embedder (all-MiniLM-L6-v2) may under-perform on
species-name queries (e.g. "cod" → codfish category row) because general-purpose
training doesn't prioritise food-type cues over property-axis cues (pH, aw).

**What it does:** Evaluates four sentence-transformer models in a 2×2 design
(size: 384-dim / 768-dim × objective: general / retrieval-optimised) against a
stratified corpus of 30 ground-truth retrieval queries. Each embedder gets its
own isolated ChromaDB collection; the production store is never touched.

**Strata:**
- `easy` (10): specific-food row exists in the knowledge base — should be near 100% for all embedders.
- `medium` (10): only a category-level row exists — the diagnostic stratum where embedder choice matters.
- `hard` (6): negative controls — no matching row should clear the confidence threshold (false-positive test).
- `pathogen` (4): hazard retrieval with `data_type=food_pathogen_hazard` filter.

**Key metrics:** top-1 accuracy, top-3 accuracy, gate pass rate, mean expected
cosine score (per stratum and overall), model load time, corpus embed time,
per-query latency.

```bash
# Dry run — baseline embedder only, 3 easy queries
python -m benchmarks.experiments.exp_2_1_embedder_comparison \
    --embedders minilm-l6-v2 --queries-subset easy --top-k 5

# Full 2x2 run (downloads ~500 MB of models on first run)
python -m benchmarks.experiments.exp_2_1_embedder_comparison

# Two specific candidates
python -m benchmarks.experiments.exp_2_1_embedder_comparison \
    --embedders minilm-l6-v2,bge-base-en-v1.5

# Skip MLflow tracking
python -m benchmarks.experiments.exp_2_1_embedder_comparison --no-mlflow
```

**Embedder IDs:** `minilm-l6-v2` (baseline), `bge-small-en-v1.5`, `bge-base-en-v1.5`, `mpnet-base-v2`

**Prerequisites:** `sentence-transformers` and `chromadb` (already in project deps).
No API keys required — runs fully offline after model download.

---

### Exp 1.1 — pH Stochasticity

**Claim:** LLM pH retrieval is unreliable without RAG grounding.

**What it does:** A Monte Carlo simulation. For each of 15 foods, it asks
each LLM "What is the pH of [food]?" N times and records the distribution
of answers. It then compares these to authoritative FDA reference values and
propagates the pH variance through a ComBase growth model.

**Why it matters:** pH 4.6 is the most critical threshold in food safety
(FDA 21 CFR 114.3). If an LLM returns pH 4.3 half the time and pH 5.0 the
other half, the safety conclusion flips randomly. This experiment quantifies
exactly how often that happens and how much growth prediction changes as a
result.

**Key metrics:** MAE (mean absolute error vs. reference pH), stdev (spread
across runs), boundary crossing rate (fraction of runs on the wrong side of
pH 4.6), and growth propagation impact (log CFU/g change from pH variance).

```bash
# Quick test (1 run per food, default temperature 0.7)
python -m benchmarks.experiments.exp_1_1_ph_stochasticity --runs 1

# Full run
python -m benchmarks.experiments.exp_1_1_ph_stochasticity --runs 20

# Custom temperature and growth threshold
python -m benchmarks.experiments.exp_1_1_ph_stochasticity --runs 10 \
    --temperature 0.5 --log-threshold 1.5

# Specific models only
python -m benchmarks.experiments.exp_1_1_ph_stochasticity --models "GPT-4o"

# Skip MLflow tracking
python -m benchmarks.experiments.exp_1_1_ph_stochasticity --no-mlflow
```

### Exp 3.1 — Model Comparison

**Claim:** Model choice affects extraction accuracy, cost, and latency in
ways that matter for production deployment.

**What it does:** Runs the real `SemanticParser` (same code path, same system
prompt, same Pydantic schema as production) against 20 expert-annotated
food-safety queries across multiple LLMs. Each query is run N times to
measure both accuracy and consistency.

**Why it matters:** The system needs an LLM that reliably extracts
structured food-safety parameters (pathogen, temperature, duration, model
type) from natural language. A wrong model type classification reverses the
direction of conservative bias, which is a safety-critical failure. This
experiment identifies which models meet the accuracy/cost/latency trade-off.

**Key metrics:** Overall accuracy (% of fields correct), consistency
(% of runs producing the same answer), model type accuracy (safety-critical),
field-level accuracy heatmap, cost per call, and P50/P95 latency.

```bash
# Quick smoke test (1 run per query)
python -m benchmarks.experiments.exp_3_1_model_comparison --runs 1

# Full run
python -m benchmarks.experiments.exp_3_1_model_comparison --runs 20

# Test specific models only
python -m benchmarks.experiments.exp_3_1_model_comparison --models "GPT-4o,GPT-4o-mini"

# Skip MLflow tracking
python -m benchmarks.experiments.exp_3_1_model_comparison --no-mlflow
```

## Prerequisites

- API keys in `.env`:
  ```
  OPENAI_API_KEY=sk-...
  ANTHROPIC_API_KEY=sk-ant-...
  ```
- The project's `app/` package must be importable
- Edit `config.py` to match your available models

## Experiment tracking with MLflow

MLflow is optional but recommended. It lets you compare runs across time.

```bash
pip install mlflow
python -m benchmarks.experiments.exp_3_1_model_comparison
mlflow ui --backend-store-uri sqlite:///mlruns.db
```

All runs are stored locally in `mlruns.db` (SQLite, no server or account needed).
If MLflow is not installed, experiments run normally and save results
to timestamped files only.

## Visualization dashboard

```bash
streamlit run benchmarks/visualizations/app.py
```
```powershell
python -m streamlit run benchmarks/visualizations/app.py
```

Pages: Overview, Model Comparison (Exp 3.1), Run Experiments,
pH Stochasticity (Exp 1.1), Embedder Comparison (Exp 2.1).
