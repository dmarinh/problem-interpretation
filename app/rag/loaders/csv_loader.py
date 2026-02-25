"""
CSV loader for structured data.
"""

import csv
from pathlib import Path

from app.rag.loaders.base import BaseLoader, Document


class CSVLoader(BaseLoader):
    """
    Loader for CSV files.
    
    Each row becomes a document, with columns as metadata.
    Can specify which column(s) to use as content.
    """
    
    def __init__(
        self,
        content_columns: list[str] | None = None,
        metadata_columns: list[str] | None = None,
        delimiter: str = ",",
    ):
        """
        Initialize CSV loader.
        
        Args:
            content_columns: Columns to combine as document content.
                             If None, all columns are combined.
            metadata_columns: Columns to include as metadata.
                              If None, all non-content columns are used.
            delimiter: CSV delimiter
        """
        self.content_columns = content_columns
        self.metadata_columns = metadata_columns
        self.delimiter = delimiter
    
    def load(self, file_path: Path) -> list[Document]:
        """Load a CSV file, one document per row."""
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        documents = []
        
        with open(file_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=self.delimiter)
            
            for i, row in enumerate(reader):
                # Determine content columns
                if self.content_columns:
                    content_cols = self.content_columns
                else:
                    content_cols = list(row.keys())
                
                # Build content
                content_parts = []
                for col in content_cols:
                    if col in row and row[col]:
                        content_parts.append(f"{col}: {row[col]}")
                
                content = "\n".join(content_parts)
                
                if not content.strip():
                    continue
                
                # Build metadata
                if self.metadata_columns:
                    metadata = {k: row.get(k, "") for k in self.metadata_columns}
                else:
                    metadata = {k: v for k, v in row.items() if k not in content_cols}
                
                metadata["filename"] = file_path.name
                metadata["row_index"] = i
                
                documents.append(Document(
                    content=content,
                    metadata=metadata,
                    source=str(file_path),
                    chunk_index=i,
                ))
        
        return documents