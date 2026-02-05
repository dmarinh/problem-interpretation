"""
Pytest configuration and shared fixtures.

This file is automatically loaded by pytest and provides:
- Test client for FastAPI
- Mock LLM client
- Common test data
"""

import pytest
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.config import settings


# =============================================================================
# PYTEST-ASYNCIO CONFIGURATION
# =============================================================================

pytest_plugins = ('pytest_asyncio',)


# =============================================================================
# FIXTURES: FastAPI Test Clients
# =============================================================================

@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """
    Synchronous test client for FastAPI.
    
    Use for simple endpoint tests that don't require async.
    
    Usage:
        def test_health(client):
            response = client.get("/health/live")
            assert response.status_code == 200
    """
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """
    Asynchronous test client for FastAPI.
    
    Use for tests that need async/await.
    
    Usage:
        async def test_health(async_client):
            response = await async_client.get("/health/live")
            assert response.status_code == 200
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# =============================================================================
# FIXTURES: LLM Client Mocking
# =============================================================================

@pytest.fixture
def mock_llm_response() -> dict:
    """Standard mock LLM response data."""
    return {
        "content": "This is a mock LLM response",
        "model": "mock-model",
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }


@pytest.fixture
def mock_llm_client(mock_llm_response: dict) -> MagicMock:
    """
    Mock LLM client for testing without API calls.
    
    Usage:
        def test_something(mock_llm_client, monkeypatch):
            monkeypatch.setattr(
                "app.services.llm.client._client", 
                mock_llm_client
            )
    """
    from app.services.llm.client import LLMResponse
    
    mock_client = MagicMock()
    
    # Mock complete method
    mock_client.complete = AsyncMock(
        return_value=LLMResponse(**mock_llm_response)
    )
    
    # Mock health_check method
    mock_client.health_check = AsyncMock(
        return_value={
            "healthy": True,
            "message": "Mock LLM client",
            "model": "mock-model",
        }
    )
    
    # Mock extract method (returns a MagicMock that can be configured per test)
    mock_client.extract = AsyncMock()
    
    return mock_client


@pytest.fixture
def patch_llm_client(mock_llm_client: MagicMock, monkeypatch: pytest.MonkeyPatch):
    """
    Patch the global LLM client with the mock.
    
    Usage:
        def test_something(patch_llm_client):
            # LLM client is now mocked
            pass
    """
    import app.services.llm.client as llm_module
    monkeypatch.setattr(llm_module, "_client", mock_llm_client)
    return mock_llm_client


# =============================================================================
# FIXTURES: Test Data
# =============================================================================

@pytest.fixture
def sample_food_scenario() -> str:
    """Sample food safety scenario for testing."""
    return "Raw chicken left at room temperature for 3 hours"


@pytest.fixture
def sample_extraction_result() -> dict:
    """Expected extraction result for sample scenario."""
    return {
        "food_description": "raw chicken",
        "pathogen_mentioned": None,
        "temperature_c": 25.0,
        "duration_minutes": 180.0,
    }


# =============================================================================
# FIXTURES: Settings Override
# =============================================================================

@pytest.fixture
def debug_settings(monkeypatch: pytest.MonkeyPatch):
    """Enable debug mode for tests."""
    monkeypatch.setattr(settings, "debug", True)
    return settings


@pytest.fixture
def production_settings(monkeypatch: pytest.MonkeyPatch):
    """Disable debug mode for tests."""
    monkeypatch.setattr(settings, "debug", False)
    return settings