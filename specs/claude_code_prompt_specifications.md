# Claude Code Prompt — Reverse-engineer `specifications.md` for PTM

The PTM backend has accumulated several documentation files over the course of development. Three are now formally out of date (`problem_translation_module_complete_techincal_documentation.md`, `grounding_service_documentation.md`, `grounding_service_architecture_expanded.md`) — they describe a pre-cleanup architecture that no longer matches the codebase. The current authoritative source for project context is `ptm_context.md`, but that is a session-context document, not a technical specification.

The goal of this work is to produce a single, faithful, codebase-derived `specifications.md` that:

1. Describes what the system actually does today, derived from the code, not from prior documentation (which is stale).
2. Becomes the long-term technical specification, kept in sync with the codebase as it evolves.
3. Replaces (not supplements) the three legacy documentation files for new readers' purposes — those legacy files will be retained as historical references only.

This is a **read-only-then-write** task: read the codebase comprehensively, then produce one document. No code changes. The accompanying `specifications_context.md` file (provided alongside this prompt) contains the project context you need to frame the document correctly.

## What to do

### Phase 1 — Read the codebase

Read, in this order:

1. **The four service-layer files** (the system's core):
   - `app/services/extraction/semantic_parser.py`
   - `app/services/grounding/grounding_service.py`
   - `app/services/standardization/standardization_service.py`
   - `app/core/orchestrator.py`

2. **The data models and enumerations** (the system's vocabulary):
   - `app/models/metadata.py`
   - `app/models/scenario.py` (and any sibling files like `payload.py`, `extraction.py` if they exist — list the contents of `app/models/` first)
   - `app/core/enums.py` (and any sibling enum files)
   - `app/config/rules.py`
   - `app/config/settings.py`

3. **The engine layer**:
   - `app/engines/combase/engine.py`
   - `app/engines/combase/calculator.py`
   - `app/engines/combase/models.py`

4. **The RAG layer**:
   - `app/rag/vector_store.py`
   - `app/rag/data_sources/` (list and read each file, especially `food_safety.py` for the multi-source attribution logic)
   - `app/rag/embeddings/` if separate

5. **The API layer**:
   - `app/api/routes/translation.py`
   - `app/api/schemas/translation.py`
   - `app/main.py` if relevant

6. **Data tables** (read enough to characterise, not exhaustively):
   - `data/combase_models.csv` (first 5 rows + header)
   - `data/sources/source_references.csv`
   - List files under `data/rag/` and `data/vector_store/`

7. **One end-to-end test** to confirm runtime behaviour:
   - `tests/integration/test_full_pipeline.py`

If a file you expect doesn't exist, note it in the deliverable. If you find files I haven't listed that materially affect behaviour, read them too.

### Phase 2 — Write `specifications.md`

Produce a single file at the repo root named `specifications.md`. Suggested structure (adjust if the codebase suggests a better organisation, but cover all the topics):

```
1. Purpose and scope
   - What PTM does (one paragraph)
   - What it explicitly does not do (Result Interpretation, interactive
     clarification — see project context document)
   - Audience: regulators, industry QA, researchers, developers

2. Architecture overview
   - The five-stage pipeline with a diagram
   - Singleton patterns and lifecycle
   - Stateless-per-request guarantee

3. Pipeline stages (one section per stage)
   For each: SemanticParser, GroundingService, StandardizationService,
   ComBase engine, Orchestrator —
   - Responsibilities (what this stage decides)
   - Inputs and outputs (Pydantic types)
   - Algorithms used (regex, embedding similarity, polynomial
     evaluation, etc.)
   - Constants and thresholds (named, with their values from the code)
   - Side effects on metadata (what events this stage records)
   - Edge cases and how they're handled

4. Data model
   - ExtractedScenario and the extraction shape
   - GroundedValues
   - ComBaseExecutionPayload
   - InterpretationMetadata and its component types (ValueProvenance,
     RangeBoundSelection, RangeClamp, DefaultImputed, RetrievalResult,
     CombaseModelAudit, SystemAudit)
   - The `field_audit` map and its relationship to top-level lists

5. ComBase model registry
   - The CSV schema (columns)
   - Model selection logic
   - Coefficient interpretation
   - Valid range enforcement

6. RAG knowledge base
   - The data CSVs and their schemas
   - The ingestion pipeline (CSV → natural-language documents → ChromaDB)
   - Multi-source citation attribution at ingestion (the notes-field
     parsing logic in food_properties)
   - Source references CSV
   - The manifest file written at ingestion time
   - Retrieval, embedding, reranking
   - Confidence-related fields exposed (embedding_score is the only
     numeric reliability signal — explain why)

7. Audit trail
   - The full per-field structure
   - The four event types (range_bound_selection, range_clamp,
     default_imputed, plus warnings as a separate string list)
   - Which stage emits each event type
   - How events are recorded both per-field and at the top level
   - Full citations and source attribution
   - System provenance (manifest, hashes, timestamps)
   - Empty-list policy (truly empty `[]`, not sentinel strings)

8. Out-of-range behaviour
   - When clamping fires
   - The three audit signals
   - Why clamping rather than refusal

9. Conservative direction
   - Default values and where they live
   - Range-bound selection direction by model_type
   - The "two places" rule (defaults + range-bound selection;
     no other conservative layer)

10. Interpretation rules (rules.py)
    - The temperature and duration tables
    - The conservative bool flag
    - The embedding-fallback path
    - What the rules are NOT (not scientific facts; linguistic
      conventions only)

11. API contract
    - /api/v1/translate endpoint
    - The verbose=true response shape (full JSON example)
    - Error responses
    - Backward-compatibility considerations (legacy provenance array)

12. Testing strategy
    - Unit, integration, end-to-end coverage
    - The curated regression queries (T1–T8 plus clamp scenarios) —
      reference where they live in the test suite

13. Configuration
    - Environment variables and their purposes
    - Settings.py defaults
    - LLM provider configuration

14. Glossary
    - Pull from ptm_context.md §13; verify against the codebase

15. Appendix: file-to-responsibility map
    - For each file under app/, one line on what it does
    - Useful for newcomers navigating the codebase
```

### Phase 3 — Cross-check against `ptm_context.md`

Compare your draft against `ptm_context.md` (v1.2 or later). Flag any discrepancies you find — places where the context document and the codebase disagree. Bring those to the user's attention rather than silently picking one. The codebase wins by default (it's executable truth), but the user may want to update the context document instead, or there may be a third interpretation.

## Working principles

**Faithful, not aspirational.** Describe what the code does, not what the docstrings say it does. If a docstring describes a behaviour that the code doesn't implement, document the code's behaviour and flag the docstring as a follow-up. (This was a recurring problem in the legacy docs — the bias-correction layer was extensively documented but never executed.)

**Cite line numbers for non-obvious claims.** When asserting a constant or a threshold, cite the file and line. E.g., "The embedding similarity threshold for the rule-fallback path is `0.50` (`app/config/rules.py:EMBEDDING_SIMILARITY_THRESHOLD`)." This makes the spec verifiable and keeps it self-correcting as the code evolves.

**Diagrams where they help, prose where they don't.** A pipeline diagram is worth a paragraph. A data-flow diagram for the RAG ingestion is worth two paragraphs. Don't add diagrams for things that are clearer in text (e.g., a list of constants).

**Be explicit about what's structured vs. stringly-typed.** The audit response has both — structured `RangeClampInfo` objects and plain-string warnings. Document which is which and why.

**Identify deferred work.** When the codebase clearly anticipates a future change (e.g., the `range_pending` flag is internal plumbing for the standardization-block-as-a-list refactor that hasn't landed), note it.

**Don't speculate about future behaviour.** If a field exists on the model but isn't populated yet, say so. Don't describe what it will do "when fully implemented."

**Length is not the goal.** A precise 30-page document is better than a vague 60-page one. Cut anything that doesn't add information beyond what an attentive reader of the code would already understand.

## What NOT to do

- Don't reformat or rewrite any code. Read-only.
- Don't reproduce the legacy docs (`problem_translation_module_complete_techincal_documentation.md`, etc.) into the new spec. They're out of date. Read the codebase directly.
- Don't include scientific philosophy or strategic vision (those live in `ptm_context.md` §2). The spec is a technical document; cross-reference the context doc where the philosophy informs design.
- Don't include benchmarks or experiment specs (those live in `benchmarks/` and have their own specs). The spec is the production system.
- Don't include the frontend. The spec is backend-only.

## Deliverable

A single file: `specifications.md` at the repo root.

Plus a short summary in the chat:
- Which files you read
- Any discrepancies between codebase and `ptm_context.md`
- Any sections of the spec where you had to make a judgement call (e.g., a file's responsibility was unclear, or two files seemed to overlap)
- Total length of the resulting spec

## Process

This is a substantial read-and-write task. Plan first if it helps; otherwise proceed directly to reading. I expect the resulting spec to be ~30–60 pages of plain markdown.
