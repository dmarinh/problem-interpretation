"""
Vector Store

ChromaDB-based vector store for document embeddings.
Supports persistent storage and semantic search with cosine similarity.
"""

from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import settings
from app.rag.embeddings import BaseEmbedding, ChromaEmbeddingAdapter, create_embedding


class VectorStore:
    """
    ChromaDB vector store wrapper.
    
    Uses a single collection with metadata filtering for different document types:
    - food_properties: pH, aw, typical characteristics
    - pathogen_hazards: pathogen-food associations, risks
    - conservative_values: worst-case defaults
    
    Uses cosine distance for similarity (requires normalized embeddings).
    
    Usage:
        store = VectorStore()
        store.initialize()
        results = store.query("raw chicken pH", doc_type="food_properties")
    """
    
    # Single collection name
    COLLECTION_NAME = "knowledge_base"
    
    # Document types (for metadata filtering)
    TYPE_FOOD_PROPERTIES = "food_properties"
    TYPE_PATHOGEN_HAZARDS = "pathogen_hazards"
    TYPE_CONSERVATIVE_VALUES = "conservative_values"
    
    ALL_TYPES = [TYPE_FOOD_PROPERTIES, TYPE_PATHOGEN_HAZARDS, TYPE_CONSERVATIVE_VALUES]
    
    # Distance metric
    DISTANCE_METRIC = "cosine"
    
    def __init__(
        self,
        persist_directory: Path | None = None,
        embedding: BaseEmbedding | None = None,
    ):
        """
        Initialize vector store.
        
        Args:
            persist_directory: Path for persistent storage
            embedding: Embedding model (creates default if not provided)
        """
        self._persist_dir = persist_directory or settings.vector_store_path
        self._embedding = embedding
        self._client: chromadb.ClientAPI | None = None
        self._collection: chromadb.Collection | None = None
    
    def initialize(self) -> None:
        """
        Initialize the vector store and create collection.
        
        Must be called before any operations.
        """
        # Ensure directory exists
        if self._persist_dir:
            Path(self._persist_dir).mkdir(parents=True, exist_ok=True)
        
        # Initialize ChromaDB client
        self._client = chromadb.PersistentClient(
            path=str(self._persist_dir),
            settings=ChromaSettings(
                anonymized_telemetry=False,
            ),
        )
        
        # Initialize embedding if not provided
        if self._embedding is None:
            self._embedding = create_embedding(
                model_name=settings.embedding_model,
                normalize=True,
            )
        
        # Create adapter for ChromaDB
        embedding_function = ChromaEmbeddingAdapter(self._embedding)
        
        # Create or get collection with cosine distance
        self._collection = self._client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            embedding_function=embedding_function,
            metadata={"hnsw:space": self.DISTANCE_METRIC},
        )
    
    @property
    def is_initialized(self) -> bool:
        """Check if store is initialized."""
        return self._client is not None and self._collection is not None
    
    @property
    def embedding(self) -> BaseEmbedding | None:
        """Get the embedding model."""
        return self._embedding
    
    @property
    def distance_metric(self) -> str:
        """Get the distance metric."""
        return self.DISTANCE_METRIC
    
    def _ensure_initialized(self) -> None:
        """Raise if not initialized."""
        if not self.is_initialized:
            raise RuntimeError("VectorStore not initialized. Call initialize() first.")
    
    def add_documents(
        self,
        documents: list[str],
        doc_type: str,
        metadatas: list[dict] | None = None,
        ids: list[str] | None = None,
    ) -> None:
        """
        Add documents to the store.
        
        Args:
            documents: List of document texts
            doc_type: Document type (food_properties, pathogen_hazards, etc.)
            metadatas: Optional additional metadata for each document
            ids: Optional IDs (generated if not provided)
        """
        self._ensure_initialized()
        
        if ids is None:
            existing_count = self._collection.count()
            ids = [f"{doc_type}_{existing_count + i}" for i in range(len(documents))]
        
        # Add doc_type to metadata
        if metadatas is None:
            metadatas = [{"type": doc_type} for _ in documents]
        else:
            metadatas = [{**m, "type": doc_type} for m in metadatas]
        
        self._collection.add(
            documents=documents,
            metadatas=metadatas,
            ids=ids,
        )
    
    def query(
        self,
        query_text: str,
        n_results: int = 5,
        doc_type: str | None = None,
        where: dict | None = None,
    ) -> list[dict]:
        """
        Query for similar documents.
        
        Args:
            query_text: Query string
            n_results: Number of results to return
            doc_type: Optional filter by document type
            where: Optional additional metadata filter
            
        Returns:
            List of results with 'document', 'metadata', 'distance', 'id'
        """
        self._ensure_initialized()
        
        # Build filter
        query_filter = None
        if doc_type or where:
            query_filter = {}
            if doc_type:
                query_filter["type"] = doc_type
            if where:
                query_filter.update(where)
        
        results = self._collection.query(
            query_texts=[query_text],
            n_results=n_results,
            where=query_filter if query_filter else None,
        )
        
        # Flatten results into list of dicts
        output = []
        if results and results["documents"] and results["documents"][0]:
            for i in range(len(results["documents"][0])):
                output.append({
                    "document": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "distance": results["distances"][0][i] if results["distances"] else None,
                    "id": results["ids"][0][i] if results["ids"] else None,
                })
        
        return output
    
    def get_count(self, doc_type: str | None = None) -> int:
        """
        Get number of documents.
        
        Args:
            doc_type: Optional filter by type (None = all documents)
        """
        self._ensure_initialized()
        
        if doc_type is None:
            return self._collection.count()
        
        # Count by type requires a query
        results = self._collection.get(
            where={"type": doc_type},
        )
        return len(results["ids"]) if results["ids"] else 0
    
    def clear(self, doc_type: str | None = None) -> None:
        """
        Clear documents.
        
        Args:
            doc_type: Optional type to clear (None = all documents)
        """
        self._ensure_initialized()
        
        if doc_type is None:
            # Delete and recreate collection
            self._client.delete_collection(self.COLLECTION_NAME)
            embedding_function = ChromaEmbeddingAdapter(self._embedding)
            self._collection = self._client.get_or_create_collection(
                name=self.COLLECTION_NAME,
                embedding_function=embedding_function,
                metadata={"hnsw:space": self.DISTANCE_METRIC},
            )
        else:
            # Delete by type
            results = self._collection.get(where={"type": doc_type})
            if results["ids"]:
                self._collection.delete(ids=results["ids"])


# =============================================================================
# SINGLETON
# =============================================================================

_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    """Get or create the global VectorStore instance."""
    global _store
    if _store is None:
        _store = VectorStore()
    return _store


def reset_vector_store() -> None:
    """Reset the global store (for testing)."""
    global _store
    _store = None