# CLAUDE.md

# Behavioral guidelines for coding

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Predictive Microbiology Translation Module information

Semantic middleware translating natural language food safety scenarios into
predictive microbiology predictions via ComBase polynomial models.
Food safety is the domain — conservative defaults are intentional and safety-critical.

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
`scripts/` contains manual integration tests that call live LLM APIs and require `.env` keys. Run with `python scripts/<name>.py`. These are not pytest tests — do not add them to the test suite.

**Windows note:** scripts that print Unicode (✓, →, °, μ) must add `sys.stdout.reconfigure(encoding="utf-8")` immediately after `sys.path.insert(...)`.

## Architecture (non-obvious parts only)

### Pipeline
```
User Query → Intent → Extraction → Model Type → Grounding (RAG) → Standardization → ComBase → Result
```

### Key service responsibilities
- **SemanticParser** (`app/services/extraction/semantic_parser.py`): LLM + Instructor → `ExtractedScenario`. Free text is allowed here. Populates `time_temperature_steps[]` for multi-step scenarios.
- **GroundingService** (`app/services/grounding/grounding_service.py`): Resolves `ExtractedScenario` → `GroundedValues`. Uses RAG for food pH/aw; uses `config/rules.py` for linguistic terms ("room temperature" → 25°C). Applies model-type-aware range bound selection. Dispatches to `_ground_multi_step_profile` when `scenario.is_multi_step and scenario.time_temperature_steps` is truthy; falls back to single-step otherwise. Multi-step results land in `grounded.steps` (`GroundedStep` objects), not in the flat key-value store.
- **StandardizationService** (`app/services/standardization/standardization_service.py`): `GroundedValues` → `ComBaseExecutionPayload`. Applies conservative bias corrections and safety defaults. Dispatches to `_build_multi_step_profile` when `grounded.has_steps`; applies identical per-step temperature defaults, confidence bumps, range clamps, and duration margins as the single-step path. pH/aw/pathogen remain global (per-step environmental conditions are not supported by the ComBase polynomial models).
- **ComBaseEngine** (`app/engines/combase/engine.py`): Iterates over `TimeTemperatureProfile.steps`, accumulating log growth per step via `GrowthPrediction` objects into `step_predictions[]`.

### API response schema
`GET /api/v1/translate` returns `TranslationResponse` → `PredictionResult`. The prediction includes:
- Scalar summary: `temperature_celsius`, `mu_max`, `doubling_time_hours` (first-step values for multi-step scenarios — kept for back-compat)
- Multi-step breakdown: `is_multi_step: bool`, `steps: list[StepInput]`, `step_predictions: list[StepPrediction]` — always populated (length 1 for single-step). Schemas in `app/api/schemas/translation.py`.

### Model type determination priority (orchestrator.py)
explicit param → LLM inference (`implied_model_type`) → temperature heuristic (>50°C → thermal) → scenario flags → environmental conditions → default GROWTH

### Range selection is model-type-aware
UPPER bound for GROWTH/NON_THERMAL (more growth = worse), LOWER bound for THERMAL_INACTIVATION (less kill = worse).

### Three model types map to ComBase ModelIDs
GROWTH (1), THERMAL_INACTIVATION (2), NON_THERMAL_SURVIVAL (3).

### GroundedValues is a flat key-value store
`grounded.set("temperature_celsius", 25.0, ...)` / `grounded.get("temperature_celsius")`. There is no concept of indexed steps — adding multi-step support requires either extending this class or passing `time_temperature_steps` alongside it.

### LLM configuration
LiteLLM + Instructor. Model via `LLM_MODEL` env var (default `gpt-4o`). See `.env.example`. Temperature defaults to 0.1 for determinism.

### RAG data sources
CSV files in `data/rag/` (food properties, pathogen hazards, aw limits, TCS classification) are the authoritative knowledge base. Ingested into ChromaDB at `data/vector_store/`. CDC 2019 is primary; CDC 2011 is fallback with explicit notation. All changes to these CSVs must be logged in `data/rag/rag_audit_changelog.md` with source citation — values are cross-checked against FDA-PH-2007 and IFT-2003 source PDFs in `data/sources/`.

### Benchmarks
Each experiment in `benchmarks/experiments/` produces timestamped JSON/CSV under `benchmarks/results/` and optionally logs to MLflow (`mlruns.db`). Results are read by the Streamlit dashboard.

## Critical Conventions

### Safety-critical conservative defaults
Missing values default to worst-case for growth:
- Temperature → 25°C (abuse), pH → 7.0 (neutral), water activity → 0.99

These are intentional. Do not make them more optimistic. For safety-critical metrics (model type classification, conservative defaults, safety gates), missing data must default to the worst-case interpretation — never borrow a semantically-different field as a fallback (use `.get(key, False)`, not `.get(key, some_other_field)`).

### Enums only — no free text to the engine
All engine inputs use controlled enums (`app/models/enums.py`). Free text resolved via rapidfuzz before reaching the engine.

### Provenance tracking
Every value tracks its source (`USER_EXPLICIT`, `USER_INFERRED`, `RAG_RETRIEVAL`, `CONSERVATIVE_DEFAULT`, `FUZZY_MATCH`), confidence score 0–1, and bias corrections applied. See `app/models/metadata.py`. Add a `ValueProvenance` when setting any grounded value.

### Async-first
All I/O is async. Tests use pytest-asyncio with `asyncio_mode = "auto"` (set in `pyproject.toml`).

### Data dependency
`data/combase_models.csv` must exist at startup — the ComBase engine loads it eagerly.

## Workflow

- Enter plan mode for any task with 3+ steps
- After completing any implementation phase, invoke the code-reviewer agent before moving on
- Use subagents for investigations that require reading more than 5 files
- After any correction, update `tasks/lessons.md` with a prevention rule
- If any test fails, stop and present the failure — do not auto-fix without approval

## Testing

- Always run tests after any code change
- Use pytest fixtures for client setup (`client`, `async_client` in `tests/conftest.py`)
- Use `httpx.AsyncClient` for endpoint tests
- Parametrize across pathogen types where applicable
- Integration tests in `tests/integration/` use `mock_semantic_parser` to avoid live LLM calls

## Lessons

Read `tasks/lessons.md` at the start of every session for project-specific rules learned from past mistakes.
