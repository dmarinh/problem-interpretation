"""
Embedding Models

Abstraction layer for different embedding providers.
All embeddings are normalized by default for consistent similarity computation.
"""

from abc import ABC, abstractmethod

import numpy as np


class BaseEmbedding(ABC):
    """
    Abstract base class for embedding models.
    
    All implementations must:
    - Return normalized vectors (unit length)
    - Report their dimensionality
    """
    
    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a list of documents.
        
        Args:
            texts: List of document texts
            
        Returns:
            List of embedding vectors (normalized)
        """
        pass
    
    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """
        Embed a single query.
        
        Args:
            text: Query text
            
        Returns:
            Embedding vector (normalized)
        """
        pass
    
    @property
    @abstractmethod
    def dimension(self) -> int:
        """Embedding dimension."""
        pass
    
    @property
    @abstractmethod
    def model_name(self) -> str:
        """Model identifier."""
        pass
    
    @staticmethod
    def normalize(vectors: np.ndarray) -> np.ndarray:
        """
        L2 normalize vectors to unit length.
        
        Args:
            vectors: Array of shape (n, dim)
            
        Returns:
            Normalized vectors of shape (n, dim)
        """
        if vectors.ndim == 1:
            vectors = vectors.reshape(1, -1)
        
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        # Avoid division by zero
        norms = np.where(norms == 0, 1, norms)
        return vectors / norms


class SentenceTransformerEmbedding(BaseEmbedding):
    """
    Embedding using sentence-transformers models.
    
    Popular models:
    - all-MiniLM-L6-v2: Fast, 384d
    - all-mpnet-base-v2: Better quality, 768d
    - multi-qa-MiniLM-L6-cos-v1: Optimized for QA
    """
    
    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        normalize: bool = True,
        device: str | None = None,
    ):
        """
        Initialize embedding model.
        
        Args:
            model_name: Sentence-transformers model name
            normalize: Whether to normalize embeddings (recommended: True)
            device: Device to use ('cpu', 'cuda', or None for auto)
        """
        from sentence_transformers import SentenceTransformer
        
        self._model_name = model_name
        self._normalize = normalize
        self._model = SentenceTransformer(model_name, device=device)
        self._dimension = self._model.get_sentence_embedding_dimension()
    
    @property
    def dimension(self) -> int:
        return self._dimension
    
    @property
    def model_name(self) -> str:
        return self._model_name
    
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed documents with normalization."""
        if not texts:
            return []
        
        vectors = self._model.encode(
            texts,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        
        if self._normalize:
            vectors = self.normalize(vectors)
        
        return vectors.tolist()
    
    def embed_query(self, text: str) -> list[float]:
        """Embed a single query with normalization."""
        vector = self._model.encode(
            text,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        
        if self._normalize:
            vector = self.normalize(vector.reshape(1, -1))[0]
        
        return vector.tolist()


class ChromaEmbeddingAdapter:
    """
    Adapter to make our embedding classes compatible with ChromaDB.
    
    ChromaDB expects an object with __call__ method.
    """
    
    def __init__(self, embedding: BaseEmbedding):
        self._embedding = embedding
    
    def name(self) -> str:
        """ChromaDB uses this for logging/identification."""
        return self._embedding.model_name

    def __call__(self, input: list[str]) -> list[list[float]]:
        """ChromaDB calls this for both documents and queries."""
        return self._embedding.embed_documents(input)

    def embed_query(self, input: str) -> list[list[float]]:
        """ChromaDB calls this for embedding queries. Returns batch format."""
        return [self._embedding.embed_query(input)]
    
    def embed_documents(self, input: list[str]) -> list[list[float]]:
        """ChromaDB may also call this directly."""
        return self._embedding.embed_documents(input)


# =============================================================================
# FACTORY
# =============================================================================

def create_embedding(
    model_name: str = "all-MiniLM-L6-v2",
    normalize: bool = True,
) -> BaseEmbedding:
    """
    Factory function to create embedding models.
    
    Args:
        model_name: Model identifier
        normalize: Whether to normalize embeddings
        
    Returns:
        Embedding instance
    """
    # For now, only sentence-transformers supported
    # Add OpenAI, Cohere, etc. here later
    return SentenceTransformerEmbedding(
        model_name=model_name,
        normalize=normalize,
    )