# FREEZE_MANIFEST.md

## Purpose

`v1.0-rag` is a frozen snapshot of the Predictive Microbiology Translation
Module's RAG/retrieval stack — the ChromaDB vector store, the embedding and
reranker models, and the exact Python environment they were validated
against. It exists so the retrieval behaviour reported for this version
(scores, thresholds, gate outcomes) can be reproduced or audited later,
even after the environment or the vector store contents change.

## Vector store fingerprint

`data/vector_store/ingest_manifest.json`, verbatim:

```json
{
  "ingested_at": "2026-05-08T07:59:05.965827+00:00",
  "rag_store_hash": "0ce41a51b0f6ff1a",
  "source_csv_audit_date": "2026-05-06T09:53:36.217081+00:00",
  "total_chunks": 452
}
```

- SHA-256 of `chroma.sqlite3`:
  `c87b044e395603489866fd107130d04263451d3082c131341367b33be2dc1dea`
- Total `data/vector_store/` size: 8,198,216 bytes

## Environment

- Python 3.12.10
- chromadb 1.5.9
- sentence-transformers 5.2.2
- torch 2.10.0
- transformers 5.0.0

Full pinned environment: `requirements.lock.txt` (repo root).

## Note on the vector store location

`data/vector_store/` is gitignored in **this** repo (see `.gitignore`) and
is not committed here. The store contents fingerprinted above live in the
backup repo instead.
