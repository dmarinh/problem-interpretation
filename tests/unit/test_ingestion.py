"""
Unit tests for ingestion pipeline.
"""

import pytest
from pathlib import Path
import tempfile
import shutil

from app.rag.vector_store import VectorStore
from app.rag.ingestion import IngestionPipeline


@pytest.fixture
def temp_dir():
    """Create a temporary directory."""
    d = Path(tempfile.mkdtemp())
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def vector_store(temp_dir) -> VectorStore:
    """Create a temporary vector store."""
    store = VectorStore(persist_directory=temp_dir / "vector_store")
    store.initialize()
    return store


@pytest.fixture
def pipeline(vector_store) -> IngestionPipeline:
    """Create pipeline with temp store."""
    return IngestionPipeline(vector_store=vector_store)


class TestIngestionPipeline:
    """Tests for IngestionPipeline."""
    
    def test_ingest_text_file(self, pipeline, vector_store, temp_dir):
        """Should ingest a text file."""
        # Create test file
        test_file = temp_dir / "test.txt"
        test_file.write_text("This is test content about food safety.")
        
        result = pipeline.ingest_file(
            test_file,
            doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
        )
        
        assert result["success"] is True
        assert result["chunks"] >= 1
        assert vector_store.get_count() >= 1
    
    def test_ingest_csv_file(self, pipeline, vector_store, temp_dir):
        """Should ingest a CSV file."""
        test_file = temp_dir / "test.csv"
        test_file.write_text("food,ph,aw\nchicken,6.0,0.99\nbeef,5.5,0.98\n")
        
        result = pipeline.ingest_file(
            test_file,
            doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
        )
        
        assert result["success"] is True
        assert result["chunks"] == 2  # One per row
    
    def test_ingest_with_extra_metadata(self, pipeline, vector_store, temp_dir):
        """Should add extra metadata to all chunks."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("Content about chicken.")
        
        pipeline.ingest_file(
            test_file,
            doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
            extra_metadata={"category": "poultry"},
        )
        
        results = vector_store.query("chicken", n_results=1)
        
        assert results[0]["metadata"]["category"] == "poultry"
    
    def test_ingest_missing_file(self, pipeline):
        """Should handle missing file gracefully."""
        result = pipeline.ingest_file(
            Path("nonexistent.txt"),
            doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
        )
        
        assert result["success"] is False
        assert "not found" in result["error"].lower()
    
    def test_ingest_unsupported_format(self, pipeline, temp_dir):
        """Should reject unsupported file types."""
        test_file = temp_dir / "test.xyz"
        test_file.write_text("content")
        
        result = pipeline.ingest_file(
            test_file,
            doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
        )
        
        assert result["success"] is False
        assert "unsupported" in result["error"].lower()
    
    def test_ingest_directory(self, pipeline, vector_store, temp_dir):
        """Should ingest all files in directory."""
        # Create test files
        (temp_dir / "file1.txt").write_text("Content one.")
        (temp_dir / "file2.txt").write_text("Content two.")
        (temp_dir / "file3.md").write_text("# Markdown content")
        
        result = pipeline.ingest_directory(
            temp_dir,
            doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
        )
        
        assert result["total_files"] == 3
        assert result["successful_files"] == 3
        assert result["total_chunks"] >= 3
    
    def test_ingest_directory_recursive(self, pipeline, vector_store, temp_dir):
        """Should find files in subdirectories."""
        # Create nested structure
        subdir = temp_dir / "subdir"
        subdir.mkdir()
        (temp_dir / "root.txt").write_text("Root content.")
        (subdir / "nested.txt").write_text("Nested content.")
        
        result = pipeline.ingest_directory(
            temp_dir,
            doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
            recursive=True,
        )
        
        assert result["total_files"] == 2
    
    def test_ingest_directory_non_recursive(self, pipeline, vector_store, temp_dir):
        """Should not find files in subdirectories when recursive=False."""
        # Create nested structure
        subdir = temp_dir / "subdir"
        subdir.mkdir()
        (temp_dir / "root.txt").write_text("Root content.")
        (subdir / "nested.txt").write_text("Nested content.")
        
        result = pipeline.ingest_directory(
            temp_dir,
            doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
            recursive=False,
        )
        
        assert result["total_files"] == 1
    
    def test_ingest_text_directly(self, pipeline, vector_store):
        """Should ingest raw text."""
        result = pipeline.ingest_text(
            text="Raw chicken has pH 6.0 and water activity 0.99.",
            doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
            metadata={"food": "chicken"},
        )
        
        assert result["success"] is True
        assert result["chunks"] >= 1
        
        # Verify searchable
        results = vector_store.query("chicken pH")
        assert len(results) >= 1
    
    def test_ingest_empty_text(self, pipeline):
        """Should reject empty text."""
        result = pipeline.ingest_text(
            text="   ",
            doc_type=VectorStore.TYPE_FOOD_PROPERTIES,
        )
        
        assert result["success"] is False
        assert "empty" in result["error"].lower()