"""
Experiment Runner

Run and log RAG experiments with different configurations.
"""

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

from app.rag.vector_store import VectorStore
from app.rag.retrieval import RetrievalService
from app.rag.reranker import BaseReranker, create_reranker
from app.rag.embeddings import BaseEmbedding, create_embedding
from app.rag.evaluation import RAGEvaluator, EvaluationResult, get_synthetic_evaluation_dataset


logger = logging.getLogger(__name__)


@dataclass
class ExperimentConfig:
    """Configuration for an experiment."""
    name: str
    embedding_model: str = "all-MiniLM-L6-v2"
    reranker_model: str | None = None
    reranker_enabled: bool = False
    chunk_size: int = 512
    chunk_overlap: int = 50
    n_results: int = 10
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass 
class ExperimentRun:
    """Record of a single experiment run."""
    config: ExperimentConfig
    result: EvaluationResult
    timestamp: datetime
    duration_seconds: float
    
    def to_dict(self) -> dict:
        return {
            "config": self.config.to_dict(),
            "result": self.result.model_dump(),
            "timestamp": self.timestamp.isoformat(),
            "duration_seconds": self.duration_seconds,
        }


class ExperimentRunner:
    """
    Runner for RAG experiments.
    
    Usage:
        runner = ExperimentRunner()
        
        config = ExperimentConfig(
            name="baseline",
            embedding_model="all-MiniLM-L6-v2",
        )
        
        result = runner.run(config)
        runner.log_result(result)
    """
    
    def __init__(
        self,
        log_dir: Path | None = None,
        primary_metric: str = "mrr",
    ):
        """
        Initialize runner.
        
        Args:
            log_dir: Directory for experiment logs
            primary_metric: Primary metric for comparison
        """
        self._log_dir = log_dir or Path("data/experiments")
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._primary_metric = primary_metric
        self._runs: list[ExperimentRun] = []
    
    def run(
        self,
        config: ExperimentConfig,
        documents: list[dict] | None = None,
        queries: list[dict] | None = None,
    ) -> ExperimentRun:
        """
        Run an experiment.
        
        Args:
            config: Experiment configuration
            documents: Documents to index (uses synthetic if None)
            queries: Queries with relevance (uses synthetic if None)
            
        Returns:
            ExperimentRun with results
        """
        import time
        import tempfile
        import shutil
        
        start_time = time.time()
        
        # Use synthetic dataset if not provided
        if documents is None or queries is None:
            documents, queries = get_synthetic_evaluation_dataset()
        
        # Create temp directory for vector store
        temp_dir = Path(tempfile.mkdtemp())
        
        try:
            # Initialize components
            embedding = create_embedding(
                model_name=config.embedding_model,
                normalize=True,
            )
            
            store = VectorStore(
                persist_directory=temp_dir / "vectors",
                embedding=embedding,
            )
            store.initialize()
            
            # Index documents
            for doc in documents:
                store.add_documents(
                    documents=[doc["content"]],
                    doc_type=doc["type"],
                    metadatas=[doc.get("metadata", {})],
                    ids=[doc["id"]],
                )
            
            # Create reranker if enabled
            reranker = None
            if config.reranker_enabled:
                reranker = create_reranker(
                    model_name=config.reranker_model,
                    enabled=True,
                )
            
            # Create retrieval service
            service = RetrievalService(
                vector_store=store,
                reranker=reranker,
            )
            
            # Run evaluation
            evaluator = RAGEvaluator()
            
            # Add ground truth
            for query in queries:
                for doc_id in query["relevant_docs"]:
                    evaluator.add_ground_truth(
                        query_id=query["id"],
                        doc_id=doc_id,
                        relevance=1,
                    )
            
            # Run queries and add predictions
            for query in queries:
                response = service.query(
                    query_text=query["text"],
                    n_results=config.n_results,
                )
                
                for result in response.results:
                    if result.doc_id:
                        evaluator.add_prediction(
                            query_id=query["id"],
                            doc_id=result.doc_id,
                            score=result.confidence,
                        )
            
            # Compute metrics
            eval_result = evaluator.evaluate(config=config.to_dict())
            
            duration = time.time() - start_time
            
            run = ExperimentRun(
                config=config,
                result=eval_result,
                timestamp=datetime.utcnow(),
                duration_seconds=duration,
            )
            
            self._runs.append(run)
            
            return run
            
        finally:
            # Cleanup
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    def log_result(self, run: ExperimentRun) -> Path:
        """
        Log experiment result to file.
        
        Args:
            run: Experiment run to log
            
        Returns:
            Path to log file
        """
        filename = f"{run.timestamp.strftime('%Y%m%d_%H%M%S')}_{run.config.name}.json"
        log_path = self._log_dir / filename
        
        with open(log_path, "w") as f:
            json.dump(run.to_dict(), f, indent=2)
        
        logger.info(f"Logged experiment to {log_path}")
        return log_path
    
    def get_best_run(self) -> ExperimentRun | None:
        """Get the best run based on primary metric."""
        if not self._runs:
            return None
        
        return max(
            self._runs,
            key=lambda r: getattr(r.result, self._primary_metric.replace("@", "_at_")),
        )
    
    def compare_runs(self) -> str:
        """Generate comparison table of all runs."""
        if not self._runs:
            return "No runs to compare"
        
        lines = []
        header = f"{'Name':<20} {'MRR':<8} {'nDCG@5':<8} {'R@5':<8} {'P@5':<8}"
        lines.append(header)
        lines.append("-" * len(header))
        
        for run in self._runs:
            line = (
                f"{run.config.name:<20} "
                f"{run.result.mrr:<8.4f} "
                f"{run.result.ndcg_at_5:<8.4f} "
                f"{run.result.recall_at_5:<8.4f} "
                f"{run.result.precision_at_5:<8.4f}"
            )
            lines.append(line)
        
        return "\n".join(lines)