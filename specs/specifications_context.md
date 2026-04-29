# PTM Specifications — Context for the Reverse-Engineering Pass

This file is a companion to the `claude_code_prompt_specifications.md` prompt. It gives Claude Code the project context it needs to frame `specifications.md` correctly.

If you (Claude Code) are running the spec generation prompt, read this file first, then proceed to read the codebase. This file does NOT describe the codebase; it describes the project around the codebase. The code is the source of truth for technical content; this file is the source of truth for context.

---

## What PTM is

The Problem Translation Module (PTM) translates natural-language food safety queries into precise, scientifically-grounded parameters for predictive microbiology models (the ComBase family). It takes a user question like *"Is raw chicken safe after sitting on the counter for 3 hours?"* and produces:

1. A structured execution payload — food, pathogen, temperature, duration, pH, water activity, model type — that a ComBase calculator can run.
2. The mathematical result of that calculation (μ_max, doubling time, log increase or reduction).
3. A full audit trail explaining how every input value was determined, what events fired during standardization, and which sources the values are cited from.

PTM is the **input side** of a planned two-stage system. A future Result Interpretation Module will translate the mathematical output into natural-language guidance. PTM is not that module.

## Who uses it

Three audiences:

- **Risk assessors and regulators** evaluating food safety scenarios.
- **Industry QA personnel** validating HACCP plans without challenge studies.
- **Researchers** in predictive microbiology who need a standardised parameter-extraction protocol.

The scientific framing is **methodological, not software-engineering**: PTM exists to reduce inter-operator variability in food safety assessment, by making the human-input layer reproducible and bibliographically grounded. This framing shapes design choices — the audit trail is regulatory-grade because regulators will read it, not because completeness is intrinsically virtuous.

## What it explicitly does NOT do

- It does not interpret or communicate results in natural language. That's the planned Result Interpretation Module.
- It does not ask the user clarifying questions interactively. Currently it makes assumptions with documented provenance when information is missing. An interactive clarification loop is planned for Phase 12.
- It does not modify user-supplied values silently. User priority is strict; when the user says "pH 5.5", the system uses 5.5 even if RAG would suggest 6.2. (A bias-detection flag layer that *highlights* divergent user values is planned but not built.)

## Architecture in one paragraph

PTM is a five-stage pipeline: SemanticParser (LLM-based extraction with Instructor) → GroundingService (resolves vague terms via interpretation rules and food properties via RAG) → StandardizationService (selects bounds from ranges, applies defaults, clamps to model valid ranges, builds the execution payload) → ComBase engine (selects the correct ComBase model, evaluates the polynomial, returns growth/inactivation predictions) → Orchestrator (coordinates the above, builds the audit metadata, returns a TranslationResult). The audit metadata is captured post-standardization and exposed via `/api/v1/translate?verbose=true` as a structured per-field map plus three top-level lists (range_clamps, defaults_imputed, warnings) plus three context blocks (combase_model, system, provenance).

## What's settled (closed design decisions)

The following design decisions are settled. The spec should describe them as the system's current behaviour, not relitigate them:

1. **Conservative direction is committed in two places only**: (a) in default values themselves, and (b) in range-bound selection (model-type-aware: upper for growth and non-thermal-survival, lower for thermal-inactivation). There is NO bias-correction layer.

2. **No confidence numbers anywhere** except the RAG retrieval's embedding cosine similarity. The categorical `source` tier is the reliability signal. Per-rule confidence numbers, per-field confidence numbers, "overall confidence", and LLM intent confidence have all been removed. If you find a confidence number in the codebase, it should not be propagated to the audit response — verify this against the actual response shape in `app/api/schemas/translation.py`.

3. **Range-bound selection happens in the StandardizationService**, not in the GroundingService. The GroundingService stores both bounds with a `range_pending=True` flag; the StandardizationService picks the model-type-appropriate bound. This was a deliberate refactor; the architectural reasoning is that range-bound selection is a standardization concern (transforming a value to be safe to feed the model), not a grounding concern (resolving where a value came from).

4. **Audit metadata is captured post-standardization**, not pre-standardization. The orchestrator's `field_audit[X].final_value` reflects the value that reached the model, not a pre-standardization placeholder.

5. **Out-of-range values are clamped**, not extrapolated, not refused. Three audit signals fire when clamping happens: a structured `RangeClampInfo` in the top-level `range_clamps` list, a structured `range_clamp` event on the per-field `standardization` block, and a warning string in the top-level `warnings` list.

6. **Empty audit categories emit truly empty arrays `[]`**, not sentinel strings like `["(none applied)"]`. The "(none applied)" rendering is a UI concern. If you find sentinel-emission anywhere in the backend, it's a regression and should be flagged in the deliverable summary.

7. **Multi-source citation attribution at ingestion**: when a `food_properties.csv` row's `notes` field references additional source IDs (in `[SOURCE-ID]` or "from SOURCE-ID" form), those are parsed at ingestion and added to the document's source list. Validate against `data/sources/source_references.csv`. This is a workaround for the row-level single-source-id schema constraint.

8. **RAG provenance manifest** is written at ingestion alongside the ChromaDB persistence directory: `rag_store_hash`, `rag_ingested_at`, `source_csv_audit_date`. The orchestrator reads it at request time to populate the `system` block. When the manifest is missing, the system fields are emitted as null and a warning ("RAG manifest missing — store provenance unknown") is added.

9. **Default organism imputation as structured event**: when a query specifies no pathogen, Salmonella is imputed. The imputation is recorded as a structured `DefaultImputed` event in `defaults_imputed`, with the same structured event written to `field_audit["organism"].standardization`. A warning string is also retained in `warnings` to give the missing-critical-field event extra prominence.

10. **The `field_audit` map is canonical**; the legacy top-level `provenance` array is auto-derived from it for backward compatibility. New consumers should use `field_audit`.

## What's deferred (filed but not implemented)

These items are deliberately out of scope for the current spec and should be noted in the spec as deferred:

- **Standardization-block-as-a-list refactor.** Currently when both range_bound_selection and range_clamp fire on the same field, only the clamp is recorded on the per-field `standardization` block (last-event-wins). The pre-clamp range is recoverable from `extraction.parsed_range`. A future refactor will make the block a list.
- **Sourcing of `rules.py` interpretation values.** The current values are plausible defaults. Some are sourceable (refrigerator temperature, freezer temperature, room temperature). Some are convention-backed. Some are linguistic-only and not sourceable in any standard. A planned tier split will add `source_id` per rule.
- **Per-field source attribution within multi-source food rows.** Currently the multi-source attribution is row-level (this row cites FDA-PH-2007 and IFT-2003-T31). Per-field attribution (pH cites FDA, aw cites IFT) requires a CSV schema migration.
- **CDC-2019 pathogen rows merged into `pathogen_characteristics.csv`.** The source is registered but rows are not yet populated.
- **Result Interpretation Module** (Phase 10).
- **Multi-step scenarios with per-step model-type inference** (Phase 11).
- **Interactive clarification loop** (Phase 12).
- **Production deployment hardening** (Phase 13).

## Working preferences

- **Faithful, not aspirational.** The spec describes what the code does, not what the docstrings say. If a docstring describes a behaviour the code doesn't implement, document the code's behaviour and flag the docstring as a follow-up. This was a recurring problem in the legacy docs.
- **Cite line numbers for non-obvious claims.** When asserting a constant or a threshold, cite the file and line.
- **Length is not the goal.** A precise 30-page spec is better than a vague 60-page one.
- **Cross-reference, don't duplicate.** Where `ptm_context.md` already covers something well (e.g., the scientific philosophy in §2, the strategic vision in §2.7), cross-reference it rather than reproduce it.
- **Empty arrays vs. sentinel strings, structured vs. stringly-typed, post-standardization vs. pre-standardization** — these are the kinds of distinctions the spec must be precise about. They're load-bearing for audit honesty.

## What success looks like

A reader of `specifications.md` who has not seen the codebase should be able to:

- Understand what each pipeline stage does and which Pydantic types flow through it.
- Predict the JSON shape of an `/api/v1/translate?verbose=true` response without running the system.
- Find any constant, threshold, or default by following a citation to a file and line.
- Distinguish settled architectural decisions from deferred future work.
- Know what the system explicitly does NOT do.

If a domain expert (microbiologist, regulator) reads the spec, they should be able to:

- Verify that the conservative direction logic is what their field would expect.
- Verify that the audit trail meets their cross-checking needs (cited sources, retrieved text verbatim, full bibliographic citations).
- Identify where the system's behaviour diverges from a "best estimate" interpretation toward a "regulatory upper bound" interpretation, and why.

If a developer joining the project reads the spec, they should be able to:

- Run the system locally and predict what each component does.
- Add a new pipeline component (e.g., a clarification step) by extending the existing patterns rather than working against them.
- Identify the test fixtures and curated queries that exercise each behaviour.

## Companion files

- `ptm_context.md` (v1.2 or later) — the session-context document. Authoritative for project context, scientific philosophy, and roadmap. Cross-reference it from the spec.
- `lessons.md` — meta-learning from development sessions. Not relevant to the spec content, but useful background.
- The three legacy docs (`problem_translation_module_complete_techincal_documentation.md`, `grounding_service_documentation.md`, `grounding_service_architecture_expanded.md`) — out of date; do NOT read or use as reference. Each carries a "HISTORICAL DOCUMENT" notice at the top.

---

*End of context document. Now read the codebase, then write the spec.*
