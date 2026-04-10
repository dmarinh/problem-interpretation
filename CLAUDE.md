# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A semantic middleware that translates natural language food safety scenarios into predictive microbiology parameters and predictions using ComBase polynomial models. Food safety is the domain — conservative defaults are intentional and safety-critical.

## Commands

### Run the application
```bash
uvicorn app.main:app --reload        # Development
uvicorn app.main:app --host 0.0.0.0 --port 8000  # Production
```

### Tests
```bash
pytest                               # All tests
pytest tests/unit/ -v               # Unit tests only
pytest tests/integration/ -v        # Integration tests only
pytest tests/unit/test_enums.py -v  # Single file
pytest tests/unit/test_enums.py::TestComBaseOrganism::test_fuzzy_matching -v  # Single test
pytest -k "test_growth" -v          # Pattern match
pytest --cov=app --cov-report=html  # With coverage
```

### Linting & formatting
```bash
black app tests                     # Format
ruff check app tests                # Lint
ruff check --fix app tests          # Auto-fix
mypy app                            # Type check
```

### RAG vector store admin
```bash
python -m cli.rag_admin             # Bootstrap database from sources
python -m cli.rag_admin status      # Show DB statistics
python -m cli.rag_admin verify      # Run verification queries
python -m cli.rag_admin --clear     # Clear before loading
```

## Architecture

The system implements a multi-stage pipeline:

```
User Query → Intent Classification → Scenario Extraction → Model Type Determination
→ RAG Grounding → Standardization → ComBase Engine → Result with Provenance
```

### Key modules

- **`app/core/orchestrator.py`** — Coordinates the full pipeline; determines model type via priority: explicit param → LLM inference → temperature heuristic (>50°C → thermal) → scenario flags → environmental conditions → default GROWTH
- **`app/services/extraction/semantic_parser.py`** — LLM-powered extraction of intent and scenario details (food, pathogen, time, temperature) into `ExtractedScenario`
- **`app/services/grounding/grounding_service.py`** — Resolves extracted values via RAG retrieval from ChromaDB; applies fuzzy matching for organism identification; model-type-aware range selection (UPPER bound for GROWTH/NON_THERMAL, LOWER bound for THERMAL_INACTIVATION)
- **`app/services/standardization/standardization_service.py`** — Applies conservative defaults for missing values; clamps out-of-range values; model-type-aware bias corrections
- **`app/engines/combase/engine.py`** — Loads polynomial models from `data/combase_models.csv` at startup; executes growth/inactivation calculations for 15 organisms across 3 model types
- **`app/rag/vector_store.py`** — ChromaDB wrapper; single "knowledge_base" collection with doc_type metadata filtering; cosine distance metric
- **`app/core/state.py`** — In-memory session tracking (PENDING → EXTRACTING → STANDARDIZING → EXECUTING → COMPLETED); `SessionManager` singleton

### Model types
- **GROWTH** (ModelID=1) — Bacterial multiplication during storage/holding
- **THERMAL_INACTIVATION** (ModelID=2) — Pathogen death from heat treatment
- **NON_THERMAL_SURVIVAL** (ModelID=3) — Pathogen survival under acid/aw/preservatives

### LLM integration
Uses LiteLLM for provider-agnostic abstraction (`app/services/llm/client.py`). Configure via `LLM_MODEL` env var (e.g., `gpt-4-turbo-preview`, Anthropic, Ollama). Uses `instructor` for structured output parsing.

## Critical Conventions

### Safety-critical conservative defaults
Missing values default to worst-case assumptions for growth:
- Temperature → 25°C (abuse temperature)
- pH → 7.0 (neutral, supports most growth)
- Water activity → 0.99 (high, supports most growth)

These are intentional. Do not "fix" them to be more optimistic.

### Enums only — no free text to the engine
All inputs use controlled enums (`app/models/enums.py`). Free text is resolved via fuzzy matching (rapidfuzz) before reaching the engine. Key enums: `ModelType`, `ComBaseOrganism` (15 organisms), `Factor4Type`, `SessionStatus`, `RetrievalConfidenceLevel`.

### Provenance tracking
Every value is tracked: `ValueSource` (USER_INPUT, RAG_RETRIEVAL, CONSERVATIVE_DEFAULT, FUZZY_MATCH), confidence score 0–1, bias corrections applied (optimistic_temperature, out_of_range_clamped, etc.). The `app/models/metadata.py` holds these structures.

### Singleton services
Global singletons with lazy initialization: `get_orchestrator()`, `get_session_manager()`, `get_llm_client()`, `get_vector_store()`, `get_combase_engine()`. Initialized during FastAPI lifespan in `app/main.py`.

### Async-first
All I/O (LLM calls, RAG retrieval, engine execution) is async. Tests use `pytest-asyncio` with `asyncio_mode = "auto"`.

## Configuration

All settings via `.env` (see `.env.example`). Key variables:

| Variable | Default | Purpose |
|---|---|---|
| `LLM_MODEL` | `gpt-4-turbo-preview` | LiteLLM model string |
| `LLM_API_KEY` | — | Provider API key |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence-transformers model |
| `VECTOR_STORE_PATH` | `./data/vector_store` | ChromaDB persistent storage |
| `GLOBAL_MIN_CONFIDENCE` | `0.65` | Minimum RAG retrieval confidence |
| `DEFAULT_TEMPERATURE_ABUSE_C` | `25.0` | Conservative temperature default |
| `MAX_CLARIFICATION_TURNS` | `3` | Before applying defaults |

## Test Fixtures (conftest.py)

- `client` — Synchronous FastAPI test client
- `async_client` — Async test client
- `mock_llm_client` — Mock LLM with preset responses
- `patch_llm_client` — Monkeypatches global LLM singleton
- `sample_food_scenario` — Standard test query string
- `debug_settings` / `production_settings` — Config overrides

## Data Files

- `data/combase_models.csv` — ComBase polynomial model coefficients (loaded at startup; required)
- `data/sources/` — RAG source documents (CSV, PDF, DOCX, Markdown)
- `data/vector_store/` — ChromaDB persistent storage (generated by `cli/rag_admin.py`)
- `data/cache/` — Constraint cache (TTL controlled by `CONSTRAINT_CACHE_TTL_SECONDS`)
