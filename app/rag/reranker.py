"""
Reranker Models

Cross-encoder rerankers for improving retrieval quality.
Applied after initial vector search to reorder results.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class RerankResult:
    """Result from reranking."""
    index: int
    score: float
    text: str


class BaseReranker(ABC):
    """Abstract base class for rerankers."""
    
    @abstractmethod
    def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int | None = None,
    ) -> list[RerankResult]:
        pass
    
    @property
    @abstractmethod
    def model_name(self) -> str:
        pass


class NoOpReranker(BaseReranker):
    """Pass-through reranker that preserves original order."""
    
    @property
    def model_name(self) -> str:
        return "noop"
    
    def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int | None = None,
    ) -> list[RerankResult]:
        results = [
            RerankResult(index=i, score=1.0 - (i * 0.01), text=doc)
            for i, doc in enumerate(documents)
        ]
        if top_k is not None:
            results = results[:top_k]
        return results


class CrossEncoderReranker(BaseReranker):
    """Reranker using cross-encoder models."""
    
    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        device: str | None = None,
    ):
        from sentence_transformers import CrossEncoder
        
        self._model_name = model_name
        self._model = CrossEncoder(model_name, device=device)
    
    @property
    def model_name(self) -> str:
        return self._model_name
    
    def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int | None = None,
    ) -> list[RerankResult]:
        if not documents:
            return []
        
        pairs = [[query, doc] for doc in documents]
        scores = self._model.predict(pairs, show_progress_bar=False)
        
        results = [
            RerankResult(index=i, score=float(score), text=doc)
            for i, (doc, score) in enumerate(zip(documents, scores))
        ]
        results.sort(key=lambda r: r.score, reverse=True)
        
        if top_k is not None:
            results = results[:top_k]
        return results


def create_reranker(
    model_name: str | None = None,
    enabled: bool = True,
) -> BaseReranker:
    """Factory function to create rerankers."""
    if not enabled or model_name == "noop":
        return NoOpReranker()
    return CrossEncoderReranker(
        model_name=model_name or "cross-encoder/ms-marco-MiniLM-L-6-v2",
    )