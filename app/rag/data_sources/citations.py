"""
Citation utilities for RAG knowledge base.

Handles loading source references and formatting citations.
"""

import csv
from pathlib import Path
from typing import Optional


def load_source_references(sources_dir: Path) -> dict[str, dict]:
    """Load source reference table for citation expansion.
    
    Args:
        sources_dir: Path to directory containing source_references.csv
    
    Returns:
        Dict mapping source_id to full citation info.
        
    Example:
        >>> sources = load_source_references(Path("data/sources"))
        >>> sources["CDC-2011-T3"]["short_name"]
        'CDC Scallan Table 3'
    """
    file_path = sources_dir / "source_references.csv"
    
    if not file_path.exists():
        return {}
    
    sources = {}
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("source_id"):
                continue
            sources[row["source_id"]] = {
                "short_name": row.get("short_name", ""),
                "document_title": row.get("document_title", ""),
                "authors": row.get("authors", ""),
                "year": row.get("year", ""),
                "publisher": row.get("publisher", ""),
                "table_or_section": row.get("table_or_section", ""),
                "url": row.get("url", ""),
                "doi": row.get("doi", ""),
            }
    
    return sources


def format_citation(
    source_id: str, 
    sources: dict[str, dict], 
    style: str = "short"
) -> str:
    """Format a citation for a given source_id.
    
    Args:
        source_id: The source identifier (e.g., "CDC-2011-T3")
        sources: Dict from load_source_references()
        style: "short" for inline, "full" for bibliography
    
    Returns:
        Formatted citation string
        
    Example:
        >>> format_citation("CDC-2011-T3", sources, style="short")
        'Scallan et al. (2011), Table 3'
        >>> format_citation("CDC-2011-T3", sources, style="full")
        'Scallan, Hoekstra, Angulo... (2011). Foodborne Illness... doi:10.3201/eid1701.P11101'
    """
    if source_id not in sources:
        return source_id  # Return raw ID if not found
    
    src = sources[source_id]
    
    if style == "short":
        # e.g., "Scallan et al. (2011), Table 3"
        authors = src["authors"].split(",")[0].strip() if src["authors"] else ""
        if "," in src.get("authors", ""):
            authors += " et al."
        
        parts = []
        if authors:
            parts.append(authors)
        if src["year"]:
            parts.append(f"({src['year']})")
        if src["table_or_section"]:
            parts.append(src["table_or_section"])
        
        return ", ".join(parts) if parts else source_id
    
    else:  # full
        # e.g., "Scallan, E. et al. (2011). Foodborne Illness... EID 17(1). Table 3. doi:..."
        parts = []
        if src["authors"]:
            parts.append(src["authors"])
        if src["year"]:
            parts.append(f"({src['year']})")
        if src["document_title"]:
            parts.append(src["document_title"])
        if src["publisher"]:
            parts.append(src["publisher"])
        if src["table_or_section"]:
            parts.append(src["table_or_section"])
        if src["doi"]:
            parts.append(f"doi:{src['doi']}")
        elif src["url"]:
            parts.append(src["url"])
        
        return ". ".join(parts) if parts else source_id


def expand_citation_tags(text: str, sources: dict[str, dict]) -> str:
    """Expand [SOURCE-ID] tags in text to full citations.
    
    Args:
        text: Text containing [SOURCE-ID] tags
        sources: Dict from load_source_references()
    
    Returns:
        Text with tags expanded to short citations
        
    Example:
        >>> expand_citation_tags("CFR is 34.8% [CDC-2011-T3]", sources)
        'CFR is 34.8% [Scallan et al. (2011), Table 3]'
    """
    import re
    
    def replace_tag(match):
        source_id = match.group(1)
        return f"[{format_citation(source_id, sources, style='short')}]"
    
    return re.sub(r'\[([A-Z0-9-]+)\]', replace_tag, text)
