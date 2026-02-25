"""
Ingestion Pipeline

Loads documents from files and adds them to the vector store.
"""

from pathlib import Path

from app.rag.vector_store import VectorStore, get_vector_store
from app.rag.loaders import (
    Document,
    TextLoader,
    MarkdownLoader,
    CSVLoader,
    DocxLoader,
    PDFLoader,
)


# File extension to loader mapping
LOADER_MAP = {
    ".txt": TextLoader,
    ".md": MarkdownLoader,
    ".csv": CSVLoader,
    ".docx": DocxLoader,
    ".pdf": PDFLoader,
}


class IngestionPipeline:
    """
    Pipeline for ingesting documents into the vector store.
    
    Usage:
        pipeline = IngestionPipeline()
        stats = pipeline.ingest_file(Path("data/food_properties.csv"), doc_type="food_properties")
        stats = pipeline.ingest_directory(Path("data/sources"), doc_type="food_properties")
    """
    
    def __init__(self, vector_store: VectorStore | None = None):
        """
        Initialize pipeline.
        
        Args:
            vector_store: VectorStore instance (uses global if not provided)
        """
        self._store = vector_store or get_vector_store()
    
    def _get_loader(self, file_path: Path):
        """Get appropriate loader for file type."""
        suffix = file_path.suffix.lower()
        
        loader_class = LOADER_MAP.get(suffix)
        if loader_class is None:
            raise ValueError(f"Unsupported file type: {suffix}")
        
        return loader_class()
    
    def ingest_file(
        self,
        file_path: Path,
        doc_type: str,
        extra_metadata: dict | None = None,
    ) -> dict:
        """
        Ingest a single file.
        
        Args:
            file_path: Path to file
            doc_type: Document type for filtering
            extra_metadata: Additional metadata to add to all chunks
            
        Returns:
            Stats dict with 'file', 'chunks', 'success'
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            return {
                "file": str(file_path),
                "chunks": 0,
                "success": False,
                "error": "File not found",
            }
        
        try:
            loader = self._get_loader(file_path)
            documents = loader.load(file_path)
            
            if not documents:
                return {
                    "file": str(file_path),
                    "chunks": 0,
                    "success": True,
                    "warning": "No content extracted",
                }
            
            # Prepare for vector store
            texts = [doc.content for doc in documents]
            metadatas = []
            
            for doc in documents:
                meta = doc.metadata.copy()
                meta["source"] = doc.source
                meta["chunk_index"] = doc.chunk_index
                if extra_metadata:
                    meta.update(extra_metadata)
                metadatas.append(meta)
            
            # Add to vector store
            self._store.add_documents(
                documents=texts,
                doc_type=doc_type,
                metadatas=metadatas,
            )
            
            return {
                "file": str(file_path),
                "chunks": len(documents),
                "success": True,
            }
            
        except Exception as e:
            return {
                "file": str(file_path),
                "chunks": 0,
                "success": False,
                "error": str(e),
            }
    
    def ingest_directory(
        self,
        directory: Path,
        doc_type: str,
        recursive: bool = True,
        extra_metadata: dict | None = None,
    ) -> dict:
        """
        Ingest all supported files from a directory.
        
        Args:
            directory: Directory path
            doc_type: Document type for filtering
            recursive: Whether to search subdirectories
            extra_metadata: Additional metadata to add to all chunks
            
        Returns:
            Stats dict with 'total_files', 'total_chunks', 'results'
        """
        directory = Path(directory)
        
        if not directory.exists():
            raise FileNotFoundError(f"Directory not found: {directory}")
        
        if not directory.is_dir():
            raise ValueError(f"Not a directory: {directory}")
        
        # Find all supported files
        files = []
        for ext in LOADER_MAP.keys():
            if recursive:
                files.extend(directory.rglob(f"*{ext}"))
            else:
                files.extend(directory.glob(f"*{ext}"))
        
        # Ingest each file
        results = []
        total_chunks = 0
        
        for file_path in sorted(files):
            result = self.ingest_file(file_path, doc_type, extra_metadata)
            results.append(result)
            if result["success"]:
                total_chunks += result["chunks"]
        
        return {
            "total_files": len(files),
            "successful_files": sum(1 for r in results if r["success"]),
            "total_chunks": total_chunks,
            "results": results,
        }
    
    def ingest_text(
        self,
        text: str,
        doc_type: str,
        metadata: dict | None = None,
        source: str = "direct_input",
    ) -> dict:
        """
        Ingest raw text directly.
        
        Args:
            text: Text content
            doc_type: Document type for filtering
            metadata: Optional metadata
            source: Source identifier
            
        Returns:
            Stats dict
        """
        if not text.strip():
            return {
                "source": source,
                "chunks": 0,
                "success": False,
                "error": "Empty text",
            }
        
        # Use text loader for chunking
        loader = TextLoader()
        chunks = loader.chunk_text(text, loader.chunk_size, loader.chunk_overlap)
        
        metadatas = []
        for i, _ in enumerate(chunks):
            meta = {"source": source, "chunk_index": i}
            if metadata:
                meta.update(metadata)
            metadatas.append(meta)
        
        self._store.add_documents(
            documents=chunks,
            doc_type=doc_type,
            metadatas=metadatas,
        )
        
        return {
            "source": source,
            "chunks": len(chunks),
            "success": True,
        }


# =============================================================================
# SINGLETON
# =============================================================================

_pipeline: IngestionPipeline | None = None


def get_ingestion_pipeline() -> IngestionPipeline:
    """Get or create the global IngestionPipeline instance."""
    global _pipeline
    if _pipeline is None:
        _pipeline = IngestionPipeline()
    return _pipeline


def reset_ingestion_pipeline() -> None:
    """Reset the global pipeline (for testing)."""
    global _pipeline
    _pipeline = None