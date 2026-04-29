# CLAUDE.md

Guidance for Claude Code working on the **Predictive Microbiology Translation Module (PTM)** — semantic middleware translating natural language food safety scenarios into predictive microbiology predictions via ComBase polynomial models. Food safety is the domain — conservative defaults are intentional and safety-critical.

**Read `coding_guidelines.md` at the start of every interaction.** It contains the generic LLM coding discipline (think before coding, simplicity first, surgical changes, goal-driven execution) that applies across all work. This file (`CLAUDE.md`) covers PTM-specific information only.

---

## Commands

### Core
- Dev server: `uvicorn app.main:app --reload`
- All tests: `pytest`
- Unit only: `pytest tests/unit/ -v`
- Integration only: `pytest tests/integration/ -v`
- Single test: `pytest tests/unit/test_enums.py::TestComBaseOrganism::test_fuzzy_matching -v`
- Coverage: `pytest --cov=app --cov-report=html`
- Format: `black app tests`
- Lint: `ruff check app tests` (auto-fix with `--fix`)
- Type check: `mypy app`
- RAG admin: `python -m cli.rag_admin` (subcommands: status, verify, --clear)

### Benchmarks (require API keys in `.env`)
- Run model comparison: `python -m benchmarks.experiments.exp_3_3_model_comparison --runs 1`
- Run pH stochasticity: `python -m benchmarks.experiments.exp_1_1_ph_stochasticity --runs 1`
- View dashboard: `streamlit run benchmarks/visualizations/app.py`
- MLflow UI: `mlflow ui --backend-store-uri sqlite:///mlruns.db`

### Manual scripts
`scripts/` contains manual integration tests that call live LLM APIs and require `.env` keys. Run with `python scripts/<name>.py`. These are not pytest tests — do not add them to the test suite. On Windows, scripts that print Unicode (✓, →, °, μ) must add `sys.stdout.reconfigure(encoding="utf-8")` immediately after `sys.path.insert(...)`.

---

## Architecture (non-obvious parts only)

### Pipeline
```
User Query → SemanticParser → GroundingService → StandardizationService → ComBase Engine → Orchestrator → Result
```

Model type is determined inside the orchestrator (priority chain below), not as a separate stage.

### Key service responsibilities
- **SemanticParser** (`app/services/extraction/semantic_parser.py`): LLM + Instructor → `ExtractedScenario`. Free text is allowed here. Populates `time_temperature_steps[]` for multi-step scenarios.
- **GroundingService** (`app/services/grounding/grounding_service.py`): Resolves `ExtractedScenario` → `GroundedValues`. Uses RAG for food pH/aw; uses `config/rules.py` for linguistic terms ("room temperature" → 25°C). When a value is a range (RAG-retrieved or user-supplied), stores BOTH bounds with `range_pending=True` and lets the value pass through; bound selection happens downstream in standardization. Dispatches to `_ground_multi_step_profile` when `scenario.is_multi_step and scenario.time_temperature_steps` is truthy. Multi-step results land in `grounded.steps` (`GroundedStep` objects), not in the flat key-value store.
- **StandardizationService** (`app/services/standardization/standardization_service.py`): `GroundedValues` → `ComBaseExecutionPayload`. Performs four operations, each recorded as a structured event: (1) range-bound selection from pending ranges (model-type-aware: upper for growth/non-thermal-survival, lower for thermal-inactivation); (2) default imputation for missing values; (3) range clamping to ComBase model valid ranges; (4) payload construction. **No bias-correction layer** — conservatism is committed only in defaults and range-bound selection.
- **ComBaseEngine** (`app/engines/combase/engine.py`): Iterates over `TimeTemperatureProfile.steps`, accumulating log growth per step via `GrowthPrediction` objects into `step_predictions[]`.
- **Orchestrator** (`app/core/orchestrator.py`): Coordinates the pipeline. Captures audit metadata POST-standardization (so `field_audit[X].final_value` reflects what reached the model, not a pre-standardization placeholder).

### API response schema
`POST /api/v1/translate` returns `TranslationResponse` → `PredictionResult`. With `verbose=true`, the response includes the full structured audit (per-field map plus three top-level lists: `range_clamps`, `defaults_imputed`, `warnings`; plus three context blocks: `combase_model`, `system`, `provenance` (auto-derived legacy)). Schemas in `app/api/schemas/translation.py`.

The prediction includes:
- Scalar summary: `temperature_celsius`, `mu_max`, `doubling_time_hours` (first-step values for multi-step scenarios — kept for back-compat)
- Multi-step breakdown: `is_multi_step: bool`, `steps: list[StepInput]`, `step_predictions: list[StepPrediction]` — always populated (length 1 for single-step).

### Model type determination priority (orchestrator.py)
explicit param → LLM inference (`implied_model_type`) → temperature heuristic (>50°C → thermal) → scenario flags → environmental conditions → default GROWTH

### Range selection is model-type-aware
UPPER bound for GROWTH/NON_THERMAL (more growth = worse), LOWER bound for THERMAL_INACTIVATION (less kill = worse). Selection happens in StandardizationService and is recorded as a structured `range_bound_selection` event on the per-field `standardization` block.

### Three model types map to ComBase ModelIDs
GROWTH (1), THERMAL_INACTIVATION (2), NON_THERMAL_SURVIVAL (3).

### GroundedValues is a flat key-value store
`grounded.set("temperature_celsius", 25.0, ...)` / `grounded.get("temperature_celsius")`. There is no concept of indexed steps — multi-step scenarios use the `grounded.steps` list separately.

### LLM configuration
LiteLLM + Instructor. Model via `LLM_MODEL` env var (default `gpt-4o`). See `.env.example`. Temperature defaults to 0.1 for determinism.

### RAG data sources
CSV files in `data/rag/` (food properties, pathogen hazards, aw limits, TCS classification) are the authoritative knowledge base. Ingested into ChromaDB at `data/vector_store/`. CDC 2019 is primary; CDC 2011 is fallback with explicit notation. All changes to these CSVs must be logged in `data/rag/rag_audit_changelog.md` with source citation — values are cross-checked against FDA-PH-2007 and IFT-2003 source PDFs in `data/sources/`. A manifest file is written alongside the ChromaDB persistence directory at ingestion time, recording `rag_store_hash`, `rag_ingested_at`, and `source_csv_audit_date`.

### Benchmarks
Each experiment in `benchmarks/experiments/` produces timestamped JSON/CSV under `benchmarks/results/` and optionally logs to MLflow (`mlruns.db`). Results are read by the Streamlit dashboard.

---

## Critical Conventions

### Safety-critical conservative defaults
Missing values default to worst-case for growth:
- Organism → Salmonella, Temperature → 25°C (abuse), pH → 7.0 (neutral), water activity → 0.99

These are intentional. Do not make them more optimistic. For safety-critical metrics (model type classification, conservative defaults, safety gates), missing data must default to the worst-case interpretation — never borrow a semantically-different field as a fallback (use `.get(key, False)`, not `.get(key, some_other_field)`).

### Enums only — no free text to the engine
All engine inputs use controlled enums (`app/models/enums.py`). Free text resolved via rapidfuzz before reaching the engine.

### Provenance tracking
Every value tracks its `source` (categorical: `USER_EXPLICIT`, `USER_INFERRED`, `RAG_RETRIEVAL`, `CONSERVATIVE_DEFAULT`) and any standardization events that fired. See `app/models/metadata.py`. **No confidence numbers** are emitted anywhere in the audit response except the RAG retrieval's embedding cosine similarity (`embedding_score`) — the categorical `source` tier is the reliability signal. Add a `ValueProvenance` when setting any grounded value.

### Out-of-range values are clamped
When an input parameter falls outside the selected ComBase model's valid range, the StandardizationService clamps to the nearest boundary. Three audit signals fire: a structured `RangeClampInfo` in the top-level `range_clamps` list, a structured `range_clamp` event on the per-field `standardization` block, and a warning string. The model is then evaluated at the clamped value (no extrapolation).

### Empty audit categories emit truly empty arrays
`range_clamps`, `defaults_imputed`, and `warnings` emit `[]` when no events fired — never sentinel strings like `["(none applied)"]`. The "(none applied)" rendering is a UI concern.

### Async-first
All I/O is async. Tests use pytest-asyncio with `asyncio_mode = "auto"` (set in `pyproject.toml`).

### Data dependency
`data/combase_models.csv` must exist at startup — the ComBase engine loads it eagerly.

---

## Living documents

Two files at the repo root must stay in sync with the codebase. Update them in the same change that motivates the update, not at session end.

### `specs/specifications.md` — what the system does

Update when:
- Pipeline stages, services, or components change responsibilities
- Pydantic models exposed by the API gain, lose, or change fields
- Constants, thresholds, or defaults change (spec cites file:line)
- Structured event types or API response shapes change
- An architectural decision is made or reversed

Don't update for: internal refactors with no behaviour change, test-only changes, comment-only changes.

Style: faithful not aspirational (describe code, not docstrings). Cite file:line for non-obvious claims. Be precise about structured-vs-stringly-typed and empty-array-vs-sentinel-string distinctions — they're load-bearing for audit honesty.

### `specs/lessons.md` — meta-learning log

Append (don't rewrite) at session close if any were true:
- A bug surfaced an architectural issue
- A working approach is worth keeping (prompt structure, verification technique, sequencing pattern)
- A failure mode recurred — name the pattern
- An assumption turned out to be wrong — record the heuristic that would have prevented it

One section per session, dated. Subsections: what went well, what surfaced repeatedly, what to do differently. Don't log routine successful work — only the lessons.

### Both files

Don't update from the deliverable summary alone. Verify against the codebase or a live response. Deliverables describe intent; reality sometimes diverges.

---

## Workflow

- After completing any implementation phase, invoke the code-reviewer agent before moving on.
- Use subagents for investigations that require reading more than 5 files.
- After any correction, append a prevention rule to `specs/lessons.md`.
- If any test fails, stop and present the failure — do not auto-fix without approval.

## Testing

- Always run tests after any code change.
- Use pytest fixtures for client setup (`client`, `async_client` in `tests/conftest.py`).
- Use `httpx.AsyncClient` for endpoint tests.
- Parametrize across pathogen types where applicable.
- Integration tests in `tests/integration/` use `mock_semantic_parser` to avoid live LLM calls.

## Lessons

Read `specs/lessons.md` at the start of every session for project-specific rules learned from past mistakes.
