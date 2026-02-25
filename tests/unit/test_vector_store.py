"""
Unit tests for vector store.
"""

import pytest
from pathlib import Path
import tempfile
import shutil

from app.rag.vector_store import VectorStore, get_vector_store, reset_vector_store


@pytest.fixture
def temp_store() -> VectorStore:
    """Create a temporary vector store."""
    temp_dir = Path(tempfile.mkdtemp())
    store = VectorStore(persist_directory=temp_dir)
    store.initialize()
    yield store
    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestVectorStore:
    """Tests for VectorStore."""
    
    def test_initialize(self, temp_store):
        """Should initialize successfully."""
        assert temp_store.is_initialized is True
    
    def test_add_and_query(self, temp_store):
        """Should add documents and query them."""
        temp_store.add_documents(
            documents=[
                "Raw chicken has pH between 5.9 and 6.2",
                "Raw chicken has water activity of 0.99",
                "Beef has pH between 5.4 and 5.8",
            ],
            doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
            metadatas=[
                {"food": "chicken"},
                {"food": "chicken"},
                {"food": "beef"},
            ],
        )
        
        results = temp_store.query(
            query_text="chicken pH",
            n_results=2,
        )
        
        assert len(results) == 2
        assert "chicken" in results[0]["document"].lower()
    
    def test_query_by_type(self, temp_store):
        """Should filter by document type."""
        temp_store.add_documents(
            documents=["Chicken pH is 6.0"],
            doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
        )
        temp_store.add_documents(
            documents=["Salmonella is common in chicken"],
            doc_type=VectorStore.TYPE_PATHOGEN_HAZARDS,
        )
        
        results = temp_store.query(
            query_text="chicken",
            doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
        )
        
        assert len(results) == 1
        assert "ph" in results[0]["document"].lower()
    
    def test_query_with_metadata_filter(self, temp_store):
        """Should filter by additional metadata."""
        temp_store.add_documents(
            documents=[
                "Chicken pH is 6.0",
                "Beef pH is 5.5",
            ],
            doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
            metadatas=[
                {"food": "chicken"},
                {"food": "beef"},
            ],
        )
        
        results = temp_store.query(
            query_text="pH value",
            where={"food": "chicken"},
        )
        
        assert len(results) == 1
        assert "chicken" in results[0]["document"].lower()
    
    def test_get_count_all(self, temp_store):
        """Should count all documents."""
        assert temp_store.get_count() == 0
        
        temp_store.add_documents(
            documents=["doc1", "doc2"],
            doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
        )
        temp_store.add_documents(
            documents=["doc3"],
            doc_type=VectorStore.TYPE_PATHOGEN_HAZARDS,
        )
        
        assert temp_store.get_count() == 3
    
    def test_get_count_by_type(self, temp_store):
        """Should count documents by type."""
        temp_store.add_documents(
            documents=["doc1", "doc2"],
            doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
        )
        temp_store.add_documents(
            documents=["doc3"],
            doc_type=VectorStore.TYPE_PATHOGEN_HAZARDS,
        )
        
        assert temp_store.get_count(VectorStore.TYPE_FOOD_PROPERTIES) == 2
        assert temp_store.get_count(VectorStore.TYPE_PATHOGEN_HAZARDS) == 1
        assert temp_store.get_count(VectorStore.TYPE_CONSERVATIVE_VALUES) == 0
    
    def test_clear_all(self, temp_store):
        """Should clear all documents."""
        temp_store.add_documents(
            documents=["doc1"],
            doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
        )
        temp_store.add_documents(
            documents=["doc2"],
            doc_type=VectorStore.TYPE_PATHOGEN_HAZARDS,
        )
        
        assert temp_store.get_count() == 2
        
        temp_store.clear()
        
        assert temp_store.get_count() == 0
    
    def test_clear_by_type(self, temp_store):
        """Should clear only specified type."""
        temp_store.add_documents(
            documents=["doc1"],
            doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
        )
        temp_store.add_documents(
            documents=["doc2"],
            doc_type=VectorStore.TYPE_PATHOGEN_HAZARDS,
        )
        
        temp_store.clear(doc_type=VectorStore.TYPE_FOOD_PROPERTIES)
        
        assert temp_store.get_count(VectorStore.TYPE_FOOD_PROPERTIES) == 0
        assert temp_store.get_count(VectorStore.TYPE_PATHOGEN_HAZARDS) == 1
    
    def test_not_initialized_raises(self):
        """Should raise if not initialized."""
        store = VectorStore()
        
        with pytest.raises(RuntimeError, match="not initialized"):
            store.add_documents(
                documents=["doc"],
                doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
            )


class TestVectorStoreSingleton:
    """Tests for singleton management."""
    
    def test_get_returns_instance(self):
        """get_vector_store should return a store."""
        reset_vector_store()
        store = get_vector_store()
        
        assert isinstance(store, VectorStore)
    
    def test_get_returns_same_instance(self):
        """get_vector_store should return singleton."""
        reset_vector_store()
        store1 = get_vector_store()
        store2 = get_vector_store()
        
        assert store1 is store2