"""
System audit stamp builder.

Gathers immutable facts about the running PTM instance — git sha, RAG store
fingerprint, ingestion timestamp — so every audit record can be tied to a
specific software and data state.
"""

import hashlib
import json
import subprocess
from pathlib import Path

_MANIFEST_PATH = Path("data/vector_store/ingest_manifest.json")
_COMBASE_CSV_PATH = Path("data/combase_models.csv")


def _read_manifest() -> dict:
    try:
        return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _git_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        sha = result.stdout.strip()
        return sha if sha else None
    except Exception:
        return None


def _file_sha256(path: Path) -> str | None:
    try:
        h = hashlib.sha256(path.read_bytes())
        return h.hexdigest()[:16]
    except (FileNotFoundError, OSError):
        return None


def build_system_audit() -> dict:
    """
    Return a dict of system-level facts for inclusion in InterpretationMetadata.

    Called once per request; file reads are fast (one JSON, one git invocation,
    one CSV hash).  The caller converts this dict to a SystemAudit instance.

    If the manifest file is absent or unreadable, the three manifest-sourced
    fields are None and "manifest_missing": True is included so the caller can
    append a warning to metadata.warnings.
    """
    manifest = _read_manifest()
    result = {
        "rag_store_hash": manifest.get("rag_store_hash"),
        "rag_ingested_at": manifest.get("ingested_at"),
        "source_csv_audit_date": manifest.get("source_csv_audit_date"),
        "ptm_version": _git_sha(),
        "combase_model_table_hash": _file_sha256(_COMBASE_CSV_PATH),
    }
    if not manifest:
        result["manifest_missing"] = True
    return result
