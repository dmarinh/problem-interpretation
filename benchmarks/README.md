# Benchmark Suite

Reproducible experiments for design decision justification.

## Structure

```
benchmarks/
├── config.py                           # Models to evaluate, paths
├── datasets/
│   └── extraction_queries.json         # 20 queries with expert ground truth
├── experiments/
│   └── exp_3_3_model_comparison.py     # LLM model selection benchmark
├── results/                            # Timestamped outputs
│   └── exp_3_3_model_comparison/
│       ├── results_YYYYMMDD_HHMMSS.json
│       ├── summary_YYYYMMDD_HHMMSS.csv
│       ├── latest.json
│       └── latest.csv
└── visualizations/                     # (future) Streamlit dashboard
```

## Running

```bash
# Quick smoke test (1 run per query)
python -m benchmarks.experiments.exp_3_3_model_comparison --runs 1

# Full run
python -m benchmarks.experiments.exp_3_3_model_comparison --runs 20

# Test specific models only
python -m benchmarks.experiments.exp_3_3_model_comparison --models "GPT-4o,GPT-4o-mini"

# Skip MLflow tracking
python -m benchmarks.experiments.exp_3_3_model_comparison --no-mlflow
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
python -m benchmarks.experiments.exp_3_3_model_comparison
mlflow ui --backend-store-uri sqlite:///mlruns.db
```

All runs are stored locally in `mlruns.db` (SQLite, no server or account needed).
If MLflow is not installed, experiments run normally and save results
to timestamped files only.
