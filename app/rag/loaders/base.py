"""
Base loader interface and Document model.
"""

from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel, Field


class Document(BaseModel):
    """
    A document chunk for the vector store.
    """
    content: str = Field(description="Document text content")
    metadata: dict = Field(default_factory=dict, description="Document metadata")
    source: str | None = Field(default=None, description="Source file path")
    chunk_index: int | None = Field(default=None, description="Chunk index if split")


class BaseLoader(ABC):
    """
    Abstract base class for document loaders.
    """
    
    @abstractmethod
    def load(self, file_path: Path) -> list[Document]:
        """
        Load documents from a file.
        
        Args:
            file_path: Path to the file
            
        Returns:
            List of Document objects
        """
        pass
    
    def chunk_text(
        self,
        text: str,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
    ) -> list[str]:
        """
        Split text into chunks.
        
        Args:
            text: Text to split
            chunk_size: Maximum characters per chunk
            chunk_overlap: Overlap between chunks
            
        Returns:
            List of text chunks
        """
        if len(text) <= chunk_size:
            return [text]
        
        chunks = []
        start = 0
        
        while start < len(text):
            end = start + chunk_size
            
            # Try to break at sentence or word boundary
            if end < len(text):
                # Look for sentence boundary
                for sep in ['. ', '.\n', '\n\n', '\n', ' ']:
                    last_sep = text[start:end].rfind(sep)
                    if last_sep > chunk_size // 2:
                        end = start + last_sep + len(sep)
                        break
            
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            
            start = end - chunk_overlap
        
        return chunks