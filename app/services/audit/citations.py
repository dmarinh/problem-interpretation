"""
Citation loader for audit trail.

Loads source_references.csv once per process and returns formatted
bibliographic citation strings keyed by source_id.
"""

import csv
from pathlib import Path

_cache: dict[str, str] | None = None

_CSV_PATH = (
    Path(__file__).parent.parent.parent.parent
    / "data" / "sources" / "source_references.csv"
)


def _format_citation(row: dict) -> str:
    """
    Build a single-line citation string from a CSV row.

    Format: Authors (year). Title. Publisher. Section. DOI/URL
    """
    parts: list[str] = []

    authors = row.get("authors", "").strip()
    if authors:
        parts.append(authors)

    year = row.get("year", "").strip()
    title = row.get("document_title", "").strip()
    if title:
        parts.append(f"({year}). {title}." if year else f"{title}.")

    publisher = row.get("publisher", "").strip()
    if publisher:
        parts.append(f"{publisher}.")

    section = row.get("table_or_section", "").strip()
    if section:
        parts.append(f"{section}.")

    doi = row.get("doi", "").strip()
    url = row.get("url", "").strip()
    if doi:
        parts.append(f"DOI: {doi}")
    elif url:
        parts.append(url)

    return " ".join(parts)


def _load() -> dict[str, str]:
    result: dict[str, str] = {}
    if not _CSV_PATH.exists():
        return result
    with _CSV_PATH.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            sid = row.get("source_id", "").strip()
            if sid:
                result[sid] = _format_citation(row)
    return result


def get_full_citations(source_ids: list[str]) -> dict[str, str]:
    """Return {source_id: formatted_citation} for each recognised source_id."""
    global _cache
    if _cache is None:
        _cache = _load()
    return {sid: _cache[sid] for sid in source_ids if sid in _cache}
