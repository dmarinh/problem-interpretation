"""
Test RAG evaluation and experiments.

Usage:
    python scripts/test_rag_evaluation.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.rag.experiments import ExperimentRunner, ExperimentConfig


def main():
    runner = ExperimentRunner(
        log_dir=Path("data/experiments"),
        primary_metric="mrr",
    )
    
    # Experiment 1: Baseline (no reranker)
    print("Running baseline experiment...")
    config1 = ExperimentConfig(
        name="baseline",
        embedding_model="all-MiniLM-L6-v2",
        reranker_enabled=False,
    )
    run1 = runner.run(config1)
    runner.log_result(run1)
    print(f"  MRR: {run1.result.mrr:.4f}")
    print(f"  nDCG@5: {run1.result.ndcg_at_5:.4f}")
    print()
    
    # Experiment 2: With reranker
    print("Running experiment with reranker...")
    config2 = ExperimentConfig(
        name="with_reranker",
        embedding_model="all-MiniLM-L6-v2",
        reranker_enabled=True,
        reranker_model="cross-encoder/ms-marco-MiniLM-L-6-v2",
    )
    run2 = runner.run(config2)
    runner.log_result(run2)
    print(f"  MRR: {run2.result.mrr:.4f}")
    print(f"  nDCG@5: {run2.result.ndcg_at_5:.4f}")
    print()
    
    # Comparison
    print("=" * 60)
    print("COMPARISON")
    print("=" * 60)
    print(runner.compare_runs())
    print()
    
    best = runner.get_best_run()
    print(f"Best run: {best.config.name} (MRR: {best.result.mrr:.4f})")


if __name__ == "__main__":
    main()