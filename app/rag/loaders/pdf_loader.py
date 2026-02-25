"""
PDF loader using PyMuPDF (fitz).
"""

from pathlib import Path

import fitz  # pymupdf

from app.config import settings
from app.rag.loaders.base import BaseLoader, Document


class PDFLoader(BaseLoader):
    """
    Loader for PDF documents.
    
    Extracts text from all pages.
    """
    
    def __init__(
        self,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        page_separator: str = "\n\n",
    ):
        """
        Initialize PDF loader.
        
        Args:
            chunk_size: Maximum characters per chunk
            chunk_overlap: Overlap between chunks
            page_separator: Separator between pages
        """
        self.chunk_size = chunk_size or settings.chunk_size
        self.chunk_overlap = chunk_overlap or settings.chunk_overlap
        self.page_separator = page_separator
    
    def load(self, file_path: Path) -> list[Document]:
        """Load and chunk a PDF file."""
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        doc = fitz.open(file_path)
        
        pages_text = []
        for page_num, page in enumerate(doc):
            text = page.get_text().strip()
            if text:
                pages_text.append(text)
        
        doc.close()
        
        full_text = self.page_separator.join(pages_text)
        
        if not full_text.strip():
            return []
        
        chunks = self.chunk_text(full_text, self.chunk_size, self.chunk_overlap)
        
        documents = []
        for i, chunk in enumerate(chunks):
            documents.append(Document(
                content=chunk,
                metadata={"filename": file_path.name, "format": "pdf"},
                source=str(file_path),
                chunk_index=i,
            ))
        
        return documents
    
    def load_by_page(self, file_path: Path) -> list[Document]:
        """
        Load PDF with one document per page.
        
        Useful when page boundaries are meaningful.
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        doc = fitz.open(file_path)
        
        documents = []
        for page_num, page in enumerate(doc):
            text = page.get_text().strip()
            if text:
                # Chunk if page is too large
                if len(text) > self.chunk_size:
                    chunks = self.chunk_text(text, self.chunk_size, self.chunk_overlap)
                    for i, chunk in enumerate(chunks):
                        documents.append(Document(
                            content=chunk,
                            metadata={
                                "filename": file_path.name,
                                "format": "pdf",
                                "page": page_num + 1,
                            },
                            source=str(file_path),
                            chunk_index=len(documents),
                        ))
                else:
                    documents.append(Document(
                        content=text,
                        metadata={
                            "filename": file_path.name,
                            "format": "pdf",
                            "page": page_num + 1,
                        },
                        source=str(file_path),
                        chunk_index=page_num,
                    ))
        
        doc.close()
        return documents