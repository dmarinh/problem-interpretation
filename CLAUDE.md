# Predictive Microbiology Translation Module

Semantic middleware translating natural language food safety scenarios into 
predictive microbiology predictions via ComBase polynomial models. 
Food safety is the domain — conservative defaults are intentional and safety-critical.

## Commands
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

## Architecture (non-obvious parts only)
Pipeline: User Query → Intent → Extraction → Model Type → RAG → Standardization → ComBase → Result

Model type determination priority (in orchestrator.py): 
explicit param → LLM inference → temperature heuristic (>50°C → thermal) → scenario flags → environmental conditions → default GROWTH

Range selection is model-type-aware: UPPER bound for GROWTH/NON_THERMAL, LOWER bound for THERMAL_INACTIVATION.

Three model types: GROWTH (ModelID=1), THERMAL_INACTIVATION (ModelID=2), NON_THERMAL_SURVIVAL (ModelID=3).

LLM via LiteLLM + Instructor. Configure model via LLM_MODEL env var. See .env.example.

## Critical Conventions

### Safety-critical conservative defaults
Missing values default to worst-case for growth:
- Temperature → 25°C (abuse), pH → 7.0 (neutral), Water activity → 0.99
These are intentional. Do not make them more optimistic.

### Enums only — no free text to the engine
All engine inputs use controlled enums (app/models/enums.py). Free text resolved 
via rapidfuzz before reaching the engine.

### Provenance tracking
Every value tracks its source (USER_INPUT, RAG_RETRIEVAL, CONSERVATIVE_DEFAULT, 
FUZZY_MATCH), confidence score 0–1, and bias corrections applied. 
See app/models/metadata.py.

### Async-first
All I/O is async. Tests use pytest-asyncio with asyncio_mode = "auto".

### Data dependency
data/combase_models.csv must exist at startup — the ComBase engine loads it eagerly.

## Conventions
- All data sources must track provenance (data_year, source, notes)
- CDC 2019 is primary data; CDC 2011 is fallback with explicit notation

## Workflow
- Enter plan mode for any task with 3+ steps
- After completing any implementation phase, suggest using test-writer and 
  code-reviewer agents before moving on
- Use subagents for investigations that require reading more than 5 files
- After any correction, update tasks/lessons.md with a prevention rule

## Testing
- Always run tests after any code change
- Use pytest fixtures for database and client setup
- Use httpx.AsyncClient for endpoint tests
- Parametrize across pathogen types where applicable

## Lessons
Read tasks/lessons.md at the start of every session for project-specific 
rules learned from past mistakes.