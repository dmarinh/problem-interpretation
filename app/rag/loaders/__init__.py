"""
Document loaders for different file formats.
"""

from app.rag.loaders.base import BaseLoader, Document
from app.rag.loaders.csv_loader import CSVLoader
from app.rag.loaders.docx_loader import DocxLoader
from app.rag.loaders.pdf_loader import PDFLoader
from app.rag.loaders.text import MarkdownLoader, TextLoader

__all__ = [
    "Document",
    "BaseLoader",
    "TextLoader",
    "MarkdownLoader",
    "CSVLoader",
    "DocxLoader",
    "PDFLoader",
]
