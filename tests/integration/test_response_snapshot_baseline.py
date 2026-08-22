"""
Full-response snapshot baseline for the engine-relocation refactor.

These are CHARACTERIZATION tests, not correctness tests: they pin the
complete /api/v1/translate?verbose=true response body (prediction + full
audit) for a fixed set of queries, as produced by today's code. They make
no claim that the pinned numbers are scientifically correct -- only that
the refactor (relocating app/engines/, splitting enums.py, and separating
StandardizationService's use of ComBaseModelConstraints) must not change
them. If the refactor is behaviour-preserving, every one of these tests
passes unmodified; any diff is either a real regression or a deliberate,
reviewed re-baseline.

Runs through the real FastAPI route (not the orchestrator directly), so
the response-building logic in app/api/routes/translation.py (field_audit,
provenance, combase_model/system/provenance context blocks) is pinned too,
not just the orchestrator's internal state. Only the semantic parser is
mocked (LLM calls are out of scope and costly); grounding, standardization,
and the ComBase engine run for real. The vector store is real but empty,
so every direct ChromaDB retrieval misses -- grounding then falls through
to whatever deterministic path GroundingService takes next (a conservative
default, or the category-bridge fallback, which is itself CSV-derived, not
vector-store-derived). Either way the result is deterministic and
independent of ChromaDB/embedding internals (confirmed empirically: two
independent capture runs produced byte-identical bodies), which is what
matters for this refactor -- RAG retrieval itself is out of scope for it.

Expected bodies live in tests/fixtures/expected_outputs.json, keyed by
scenario name. Only genuinely nondeterministic fields (session_id,
created_at, completed_at) are masked before comparison; everything else
is pinned exactly.
"""

import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

import app.api.routes.translation as route_module
from app.core.orchestrator import Orchestrator
from app.core.state import SessionManager
from app.main import app
from app.models.extraction import (
    ExtractedDuration,
    ExtractedEnvironmentalConditions,
    ExtractedIntent,
    ExtractedScenario,
    ExtractedTemperature,
    ExtractedTimeTemperatureStep,
)
from app.rag.retrieval import RetrievalService
from app.rag.vector_store import VectorStore
from app.services.grounding.grounding_service import GroundingService
from app.services.standardization.standardization_service import StandardizationService
from predictive.engines.combase.engine import ComBaseEngine
from predictive.models.enums import ModelType

FIXTURE_PATH = Path("tests/fixtures/expected_outputs.json")

# Fields whose value is nondeterministic per-run (wall-clock time, random
# session id) and must be masked before comparing against the pinned body.
# ptm_version is `git rev-parse --short HEAD` (app/services/audit/system.py
# ::_git_sha()), computed live at request time -- it changes on every commit
# by design, unrelated to prediction/audit behaviour, so it belongs here
# alongside the timestamps and session id. Originally missed: the fixture
# baked in whatever commit was HEAD at capture time, which broke the moment
# the very next commit landed. Confirmed via a masked re-diff against the
# committed fixture that this was the *only* divergence across all 4
# scenarios, before and after the engine-relocation move.
_MASKED_FIELDS = {"session_id", "created_at", "completed_at", "ptm_version"}


def _mask(obj):
    """Recursively replace nondeterministic field values with a sentinel."""
    if isinstance(obj, dict):
        return {
            k: ("<MASKED>" if k in _MASKED_FIELDS else _mask(v)) for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_mask(v) for v in obj]
    return obj


def _make_step(order: int, temp_celsius: float, dur_minutes: float):
    return ExtractedTimeTemperatureStep(
        sequence_order=order,
        temperature=ExtractedTemperature(value_celsius=temp_celsius),
        duration=ExtractedDuration(value_minutes=dur_minutes),
    )


# Scenario name -> (user_input, ExtractedScenario, request model_type)
_SCENARIOS = {
    "clean_growth": (
        "Raw chicken at 25C for 3 hours",
        ExtractedScenario(
            food_description="chicken",
            food_state="raw",
            pathogen_mentioned="Salmonella",
            single_step_temperature=ExtractedTemperature(value_celsius=25.0),
            single_step_duration=ExtractedDuration(value_minutes=180.0),
            environmental_conditions=ExtractedEnvironmentalConditions(),
            is_storage_scenario=True,
            implied_model_type=ModelType.GROWTH,
        ),
        ModelType.GROWTH,
    ),
    "clamped_temperature": (
        "Raw chicken at 50C for 2 hours",
        ExtractedScenario(
            food_description="chicken",
            food_state="raw",
            pathogen_mentioned="Salmonella",
            # Salmonella GROWTH model TempMax=40 (data/combase_models.csv) --
            # 50C must clamp to 40C.
            single_step_temperature=ExtractedTemperature(value_celsius=50.0),
            single_step_duration=ExtractedDuration(value_minutes=120.0),
            environmental_conditions=ExtractedEnvironmentalConditions(),
            is_storage_scenario=True,
            implied_model_type=ModelType.GROWTH,
        ),
        ModelType.GROWTH,
    ),
    "multi_step": (
        "Chicken at 25C for 1 hour then 4C for 4 hours",
        ExtractedScenario(
            food_description="chicken",
            food_state="raw",
            pathogen_mentioned="Salmonella",
            is_multi_step=True,
            time_temperature_steps=[
                _make_step(1, 25.0, 60.0),
                _make_step(2, 4.0, 240.0),
            ],
            environmental_conditions=ExtractedEnvironmentalConditions(),
            implied_model_type=ModelType.GROWTH,
        ),
        ModelType.GROWTH,
    ),
    "thermal_inactivation": (
        "Cooking chicken at 60C for 10 minutes",
        ExtractedScenario(
            food_description="chicken",
            food_state="raw",
            pathogen_mentioned="Salmonella",
            single_step_temperature=ExtractedTemperature(value_celsius=60.0),
            single_step_duration=ExtractedDuration(value_minutes=10.0),
            environmental_conditions=ExtractedEnvironmentalConditions(),
            is_cooking_scenario=True,
            implied_model_type=ModelType.THERMAL_INACTIVATION,
        ),
        ModelType.THERMAL_INACTIVATION,
    ),
}


@pytest.fixture
def empty_vector_store():
    """Real, initialized, but empty vector store -- every direct ChromaDB
    query misses by construction (no documents to match), so pH/aw resolve
    via whichever deterministic fallback GroundingService takes next
    (conservative default or category-bridge). No ChromaDB embedding
    nondeterminism, no dependency on committed RAG data."""
    d = Path(tempfile.mkdtemp())
    store = VectorStore(persist_directory=d / "vectors")
    store.initialize()
    yield store
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def combase_engine():
    engine = ComBaseEngine()
    csv_path = Path("data/combase_models.csv")
    if csv_path.exists():
        engine.load_models(csv_path)
    return engine


def _build_orchestrator(
    scenario: ExtractedScenario, combase_engine, empty_vector_store
) -> Orchestrator:
    parser = AsyncMock()
    parser.classify_intent = AsyncMock(
        return_value=ExtractedIntent(
            is_prediction_request=True,
            is_information_query=False,
            confidence=0.95,
        )
    )
    parser.extract_scenario = AsyncMock(return_value=scenario)

    retrieval_service = RetrievalService(vector_store=empty_vector_store)
    grounding_service = GroundingService(retrieval_service=retrieval_service)
    standardization_service = StandardizationService(
        model_registry=combase_engine.registry
    )

    return Orchestrator(
        session_manager=SessionManager(),
        semantic_parser=parser,
        grounding_service=grounding_service,
        standardization_service=standardization_service,
        combase_engine=combase_engine,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario_name", sorted(_SCENARIOS.keys()))
async def test_full_response_matches_pinned_baseline(
    scenario_name, combase_engine, empty_vector_store, monkeypatch
):
    if not combase_engine.is_available:
        pytest.skip("combase_models.csv not found")

    user_input, scenario, model_type = _SCENARIOS[scenario_name]
    orchestrator = _build_orchestrator(scenario, combase_engine, empty_vector_store)
    monkeypatch.setattr(route_module, "get_orchestrator", lambda: orchestrator)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/translate",
            params={"verbose": "true"},
            json={"query": user_input, "model_type": model_type.value},
        )

    assert response.status_code == 200, response.text
    actual = _mask(response.json())

    expected_all = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert scenario_name in expected_all, (
        f"No pinned baseline for {scenario_name!r} in {FIXTURE_PATH}. "
        f"If this is a new scenario, capture its output and add it to the fixture."
    )
    expected = _mask(expected_all[scenario_name])

    assert actual == expected, (
        f"Response for scenario {scenario_name!r} diverged from the pinned "
        f"baseline in {FIXTURE_PATH}. If this divergence is an intentional, "
        f"reviewed behaviour change, re-capture and update the fixture. If "
        f"it happened during the engine-relocation refactor, it is a "
        f"regression."
    )
