"""
Text and Markdown loaders.
"""

from pathlib import Path

from app.config import settings
from app.rag.loaders.base import BaseLoader, Document


class TextLoader(BaseLoader):
    """
    Loader for plain text files.
    """
    
    def __init__(
        self,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ):
        self.chunk_size = chunk_size or settings.chunk_size
        self.chunk_overlap = chunk_overlap or settings.chunk_overlap
    
    def load(self, file_path: Path) -> list[Document]:
        """Load and chunk a text file."""
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        text = file_path.read_text(encoding="utf-8")
        chunks = self.chunk_text(text, self.chunk_size, self.chunk_overlap)
        
        documents = []
        for i, chunk in enumerate(chunks):
            documents.append(Document(
                content=chunk,
                metadata={"filename": file_path.name},
                source=str(file_path),
                chunk_index=i,
            ))
        
        return documents


class MarkdownLoader(TextLoader):
    """
    Loader for Markdown files.
    
    Extracts sections based on headers and preserves structure.
    """
    
    def load(self, file_path: Path) -> list[Document]:
        """Load a Markdown file, splitting by sections."""
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        text = file_path.read_text(encoding="utf-8")
        sections = self._split_by_headers(text)
        
        documents = []
        for i, (header, content) in enumerate(sections):
            # Combine header and content
            full_content = f"{header}\n{content}".strip() if header else content.strip()
            
            # Chunk if too large
            if len(full_content) > self.chunk_size:
                chunks = self.chunk_text(full_content, self.chunk_size, self.chunk_overlap)
                for j, chunk in enumerate(chunks):
                    documents.append(Document(
                        content=chunk,
                        metadata={
                            "filename": file_path.name,
                            "section": header or "intro",
                        },
                        source=str(file_path),
                        chunk_index=len(documents),
                    ))
            else:
                documents.append(Document(
                    content=full_content,
                    metadata={
                        "filename": file_path.name,
                        "section": header or "intro",
                    },
                    source=str(file_path),
                    chunk_index=i,
                ))
        
        return documents
    
    def _split_by_headers(self, text: str) -> list[tuple[str, str]]:
        """
        Split markdown by headers.
        
        Returns list of (header, content) tuples.
        """
        lines = text.split('\n')
        sections = []
        current_header = ""
        current_content = []
        
        for line in lines:
            if line.startswith('#'):
                # Save previous section
                if current_content or current_header:
                    sections.append((current_header, '\n'.join(current_content)))
                current_header = line
                current_content = []
            else:
                current_content.append(line)
        
        # Save last section
        if current_content or current_header:
            sections.append((current_header, '\n'.join(current_content)))
        
        return sections