"""
Retrieval Service

Queries the vector store and returns results with confidence scoring.
Optionally applies reranking for improved relevance.
"""

from pydantic import BaseModel, Field

from app.config import settings
from app.rag.vector_store import VectorStore, get_vector_store
from app.rag.reranker import BaseReranker, NoOpReranker
from app.models.enums import RetrievalConfidenceLevel


class RetrievalResult(BaseModel):
    """Single retrieval result with confidence."""
    content: str = Field(description="Retrieved text content")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score (0-1)")
    confidence_level: RetrievalConfidenceLevel = Field(description="Confidence classification")
    source: str | None = Field(default=None, description="Source document")
    metadata: dict = Field(default_factory=dict, description="Additional metadata")
    doc_id: str | None = Field(default=None, description="Document ID")
    
    # Raw scores for debugging/analysis
    distance: float | None = Field(default=None, description="Raw vector distance")
    rerank_score: float | None = Field(default=None, description="Reranker score if applied")


class RetrievalResponse(BaseModel):
    """Response from a retrieval query."""
    query: str = Field(description="Original query")
    results: list[RetrievalResult] = Field(default_factory=list, description="Retrieved results")
    top_result: RetrievalResult | None = Field(default=None, description="Best result if above threshold")
    has_confident_result: bool = Field(default=False, description="Whether any result meets threshold")
    reranker_used: str | None = Field(default=None, description="Reranker model if used")


class RetrievalService:
    """
    Service for retrieving grounded information from the vector store.
    
    Features:
    - Cosine similarity with normalized embeddings
    - Configurable confidence thresholds
    - Optional reranking with cross-encoders
    
    Usage:
        service = RetrievalService()
        response = service.query("raw chicken pH")
        if response.has_confident_result:
            print(response.top_result.content)
    """
    
    def __init__(
        self,
        vector_store: VectorStore | None = None,
        reranker: BaseReranker | None = None,
        global_threshold: float | None = None,
    ):
        """
        Initialize retrieval service.
        
        Args:
            vector_store: VectorStore instance (uses global if not provided)
            reranker: Optional reranker (None = no reranking)
            global_threshold: Minimum confidence threshold (uses config if not provided)
        """
        self._store = vector_store or get_vector_store()
        self._reranker = reranker
        self._global_threshold = global_threshold or settings.global_min_confidence
    
    def _cosine_distance_to_confidence(self, distance: float) -> float:
        """
        Convert cosine distance to confidence score.
        
        ChromaDB cosine distance = 1 - cosine_similarity
        So: confidence = cosine_similarity = 1 - distance
        
        For normalized vectors:
        - distance 0 = identical (confidence 1.0)
        - distance 1 = orthogonal (confidence 0.0)
        - distance 2 = opposite (confidence -1.0, clamped to 0)
        """
        confidence = 1.0 - distance
        return max(0.0, min(1.0, confidence))
    
    def _classify_confidence(
        self,
        confidence: float,
        threshold: float | None = None,
    ) -> RetrievalConfidenceLevel:
        """Classify confidence into levels."""
        threshold = threshold or self._global_threshold
        
        if confidence >= 0.85:
            return RetrievalConfidenceLevel.HIGH
        elif confidence >= threshold:
            return RetrievalConfidenceLevel.MEDIUM
        elif confidence > 0.0:
            return RetrievalConfidenceLevel.LOW
        else:
            return RetrievalConfidenceLevel.FAILED
    
    def query(
        self,
        query_text: str,
        doc_type: str | None = None,
        n_results: int = 5,
        threshold: float | None = None,
        where: dict | None = None,
        use_reranker: bool = True,
    ) -> RetrievalResponse:
        """
        Query the vector store.
        
        Args:
            query_text: Query string
            doc_type: Optional document type filter
            n_results: Number of results to retrieve
            threshold: Confidence threshold (uses global if not provided)
            where: Additional metadata filter
            use_reranker: Whether to apply reranker (if configured)
            
        Returns:
            RetrievalResponse with results and confidence info
        """
        threshold = threshold or self._global_threshold
        
        # Fetch more results if reranking (reranker will filter)
        fetch_n = n_results * 3 if (self._reranker and use_reranker) else n_results
        
        # Query vector store
        raw_results = self._store.query(
            query_text=query_text,
            n_results=fetch_n,
            doc_type=doc_type,
            where=where,
        )
        
        # Apply reranker if configured
        reranker_used = None
        if self._reranker and use_reranker and raw_results:
            reranker_used = self._reranker.model_name
            raw_results = self._apply_reranker(query_text, raw_results, n_results)
        
        # Convert to RetrievalResults
        results = []
        for raw in raw_results[:n_results]:
            distance = raw.get("distance", 1.0)
            confidence = self._cosine_distance_to_confidence(distance)
            
            results.append(RetrievalResult(
                content=raw["document"],
                confidence=confidence,
                confidence_level=self._classify_confidence(confidence, threshold),
                source=raw.get("metadata", {}).get("source"),
                metadata=raw.get("metadata", {}),
                doc_id=raw.get("id"),
                distance=distance,
                rerank_score=raw.get("rerank_score"),
            ))
        
        # Sort by confidence (highest first)
        results.sort(key=lambda r: r.confidence, reverse=True)
        
        # Determine top result
        top_result = None
        has_confident_result = False
        
        if results and results[0].confidence >= threshold:
            top_result = results[0]
            has_confident_result = True
        
        return RetrievalResponse(
            query=query_text,
            results=results,
            top_result=top_result,
            has_confident_result=has_confident_result,
            reranker_used=reranker_used,
        )
    
    def _apply_reranker(
        self,
        query: str,
        raw_results: list[dict],
        top_k: int,
    ) -> list[dict]:
        """Apply reranker to raw results."""
        documents = [r["document"] for r in raw_results]
        reranked = self._reranker.rerank(query, documents, top_k=top_k)
        
        # Reorder raw_results based on reranker output
        reordered = []
        for rr in reranked:
            result = raw_results[rr.index].copy()
            result["rerank_score"] = rr.score
            reordered.append(result)
        
        return reordered
    
    def query_food_properties(
        self,
        food_description: str,
        n_results: int = 3,
    ) -> RetrievalResponse:
        """
        Query for food physicochemical properties.
        
        Uses the food_properties confidence threshold.
        """
        return self.query(
            query_text=f"{food_description} pH water activity properties",
            doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
            n_results=n_results,
            threshold=settings.food_properties_confidence,
        )
    
    def query_pathogen_hazards(
        self,
        food_description: str,
        n_results: int = 3,
    ) -> RetrievalResponse:
        """
        Query for pathogen hazards associated with a food.
        
        Uses the pathogen_hazards confidence threshold.
        """
        return self.query(
            query_text=f"{food_description} pathogen bacteria hazard contamination",
            doc_type=VectorStore.TYPE_PATHOGEN_HAZARDS,
            n_results=n_results,
            threshold=settings.pathogen_hazards_confidence,
        )
    
    def query_conservative_values(
        self,
        parameter: str,
        context: str | None = None,
        n_results: int = 3,
    ) -> RetrievalResponse:
        """
        Query for conservative default values.
        """
        query = f"conservative default {parameter}"
        if context:
            query += f" {context}"
        
        return self.query(
            query_text=query,
            doc_type=VectorStore.TYPE_CONSERVATIVE_VALUES,
            n_results=n_results,
        )


# =============================================================================
# SINGLETON
# =============================================================================

_service: RetrievalService | None = None


def get_retrieval_service() -> RetrievalService:
    """Get or create the global RetrievalService instance."""
    global _service
    if _service is None:
        _service = RetrievalService()
    return _service


def reset_retrieval_service() -> None:
    """Reset the global service (for testing)."""
    global _service
    _service = None