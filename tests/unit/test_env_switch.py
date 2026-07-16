"""
Unit tests for the PTM_TAXONOMY_BRIDGE_ENABLED env-var switch and the
_BRIDGE_SENTINEL pattern in GroundingService.

Covers:
- _parse_bridge_enabled_env() returns True/False for various env-var values.
- GroundingService.__init__ reads the env var when taxonomy_bridge is not
  explicitly provided (sentinel default).
- Explicit taxonomy_bridge=None disables the bridge regardless of env var.
- An injected TaxonomyBridge instance is used regardless of env var.
- When _taxonomy_bridge is None, _ground_via_taxonomy_bridge is a no-op
  (no fields set, no bridge_attempts populated).

Sentinel design:
  _BRIDGE_SENTINEL = object()  (module-level, distinct identity)

  GroundingService.__init__ signature uses _BRIDGE_SENTINEL as the default
  for the taxonomy_bridge parameter.  Inside __init__:
    if taxonomy_bridge is _BRIDGE_SENTINEL:
        # Caller did not pass anything → read env var
        self._taxonomy_bridge = TaxonomyBridge() if _parse_bridge_enabled_env() else None
    else:
        # Caller explicitly passed None or a bridge instance → honour it
        self._taxonomy_bridge = taxonomy_bridge

  This lets tests inject None to disable the bridge without touching the env var,
  and lets production code use a single env-var gate.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.grounding.grounding_service import (
    _BRIDGE_SENTINEL,
    GroundedValues,
    GroundingService,
    _parse_bridge_enabled_env,
)
from app.services.grounding.taxonomy_bridge import TaxonomyBridge

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_retrieval() -> MagicMock:
    """Minimal mock retrieval service — all queries return no confident result."""

    def _no_hit():
        r = MagicMock()
        r.has_confident_result = False
        r.results = []
        r.top_result = None
        r.query = ""
        r.reranker_used = None
        r.threshold = 0.62
        return r

    m = MagicMock()
    m.query_food_properties.return_value = _no_hit()
    m.query_food_ph.return_value = _no_hit()
    m.query_food_water_activity.return_value = _no_hit()
    m.query_pathogen_hazards.return_value = _no_hit()
    m.get_hazards_for_food.return_value = []
    return m


# ---------------------------------------------------------------------------
# _parse_bridge_enabled_env
# ---------------------------------------------------------------------------


class TestParseBridgeEnabledEnv:

    def test_no_env_var_defaults_to_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PTM_TAXONOMY_BRIDGE_ENABLED", raising=False)
        assert _parse_bridge_enabled_env() is True

    @pytest.mark.parametrize("value", ["true", "True", "TRUE", "1", "yes"])
    def test_truthy_values_return_true(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        monkeypatch.setenv("PTM_TAXONOMY_BRIDGE_ENABLED", value)
        assert _parse_bridge_enabled_env() is True

    @pytest.mark.parametrize("value", ["false", "False", "FALSE", "0", "no", ""])
    def test_falsey_values_return_false(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        monkeypatch.setenv("PTM_TAXONOMY_BRIDGE_ENABLED", value)
        assert _parse_bridge_enabled_env() is False


# ---------------------------------------------------------------------------
# Sentinel identity
# ---------------------------------------------------------------------------


class TestBridgeSentinelIdentity:

    def test_sentinel_is_not_none(self) -> None:
        """_BRIDGE_SENTINEL must be a distinct object — not None."""
        assert _BRIDGE_SENTINEL is not None

    def test_sentinel_is_not_a_taxonomy_bridge(self) -> None:
        assert not isinstance(_BRIDGE_SENTINEL, TaxonomyBridge)


# ---------------------------------------------------------------------------
# GroundingService.__init__ sentinel behaviour
# ---------------------------------------------------------------------------


class TestGroundingServiceInitBridgeSelection:

    def test_no_arg_reads_env_var_enabled(
        self, monkeypatch: pytest.MonkeyPatch, mock_retrieval: MagicMock
    ) -> None:
        """When taxonomy_bridge is not passed and env var is truthy, a real bridge is created."""
        monkeypatch.delenv("PTM_TAXONOMY_BRIDGE_ENABLED", raising=False)
        service = GroundingService(
            retrieval_service=mock_retrieval,
            llm_client=AsyncMock(),
        )
        assert service._taxonomy_bridge is not None
        assert isinstance(service._taxonomy_bridge, TaxonomyBridge)

    def test_no_arg_reads_env_var_disabled(
        self, monkeypatch: pytest.MonkeyPatch, mock_retrieval: MagicMock
    ) -> None:
        """When taxonomy_bridge is not passed and env var is falsey, bridge is None."""
        monkeypatch.setenv("PTM_TAXONOMY_BRIDGE_ENABLED", "false")
        service = GroundingService(
            retrieval_service=mock_retrieval,
            llm_client=AsyncMock(),
        )
        assert service._taxonomy_bridge is None

    def test_explicit_none_disables_bridge_regardless_of_env_var(
        self, monkeypatch: pytest.MonkeyPatch, mock_retrieval: MagicMock
    ) -> None:
        """taxonomy_bridge=None is an explicit override — env var is irrelevant."""
        monkeypatch.delenv("PTM_TAXONOMY_BRIDGE_ENABLED", raising=False)
        service = GroundingService(
            retrieval_service=mock_retrieval,
            llm_client=AsyncMock(),
            taxonomy_bridge=None,
        )
        assert service._taxonomy_bridge is None

    def test_explicit_bridge_instance_used_regardless_of_env_var(
        self, monkeypatch: pytest.MonkeyPatch, mock_retrieval: MagicMock
    ) -> None:
        """An injected bridge instance is used even when env var is 'false'."""
        monkeypatch.setenv("PTM_TAXONOMY_BRIDGE_ENABLED", "false")
        custom_bridge = TaxonomyBridge()
        service = GroundingService(
            retrieval_service=mock_retrieval,
            llm_client=AsyncMock(),
            taxonomy_bridge=custom_bridge,
        )
        assert service._taxonomy_bridge is custom_bridge


# ---------------------------------------------------------------------------
# Bridge disabled is a no-op on _ground_food_properties
# ---------------------------------------------------------------------------


class TestBridgeDisabledIsNoOp:
    """When _taxonomy_bridge is None, Tier 3 must not set any field or record attempts."""

    @pytest.mark.asyncio
    async def test_disabled_bridge_does_not_ground_ph(
        self, monkeypatch: pytest.MonkeyPatch, mock_retrieval: MagicMock
    ) -> None:
        monkeypatch.setenv("PTM_TAXONOMY_BRIDGE_ENABLED", "false")
        service = GroundingService(
            retrieval_service=mock_retrieval,
            llm_client=AsyncMock(),
        )
        grounded = GroundedValues()
        await service._ground_food_properties("turkey portions", grounded)
        assert not grounded.has("ph")

    @pytest.mark.asyncio
    async def test_disabled_bridge_does_not_ground_aw(
        self, monkeypatch: pytest.MonkeyPatch, mock_retrieval: MagicMock
    ) -> None:
        monkeypatch.setenv("PTM_TAXONOMY_BRIDGE_ENABLED", "false")
        service = GroundingService(
            retrieval_service=mock_retrieval,
            llm_client=AsyncMock(),
        )
        grounded = GroundedValues()
        await service._ground_food_properties("turkey portions", grounded)
        assert not grounded.has("water_activity")

    @pytest.mark.asyncio
    async def test_disabled_bridge_leaves_bridge_attempts_empty(
        self, monkeypatch: pytest.MonkeyPatch, mock_retrieval: MagicMock
    ) -> None:
        monkeypatch.setenv("PTM_TAXONOMY_BRIDGE_ENABLED", "false")
        service = GroundingService(
            retrieval_service=mock_retrieval,
            llm_client=AsyncMock(),
        )
        grounded = GroundedValues()
        await service._ground_food_properties("turkey portions", grounded)
        assert grounded.bridge_attempts == {}
