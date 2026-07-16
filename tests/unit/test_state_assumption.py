"""
Unit tests for _apply_state_default in grounding_service.

_apply_state_default(state: str) -> str

  Converts the raw FoodEx2 state value from TaxonomyResolution.matched_state
  into the state used for lookup_category_level_row.

  Conversion rule:
    "unspecified" → "fresh"   (FoodEx2 often marks entries as unspecified
    ""            → "fresh"    when the state is irrelevant or unknown; we
                               assume fresh because it is the most common
                               food safety scenario and we have curated rows
                               for fresh state only)
    anything else → unchanged (fresh, cured, dried, cooked, etc.)

  The assumption is logged by the caller (GroundingService._ground_via_taxonomy_bridge)
  and surfaced in CategoryBridgeInfo.assumed_state so auditors can see it.
"""

import pytest

from app.services.grounding.grounding_service import _apply_state_default


class TestApplyStateDefault:

    def test_unspecified_becomes_fresh(self) -> None:
        assert _apply_state_default("unspecified") == "fresh"

    def test_empty_string_becomes_fresh(self) -> None:
        assert _apply_state_default("") == "fresh"

    def test_fresh_is_unchanged(self) -> None:
        assert _apply_state_default("fresh") == "fresh"

    def test_cured_is_unchanged(self) -> None:
        assert _apply_state_default("cured") == "cured"

    def test_dried_is_unchanged(self) -> None:
        assert _apply_state_default("dried") == "dried"

    def test_cooked_is_unchanged(self) -> None:
        assert _apply_state_default("cooked") == "cooked"

    @pytest.mark.parametrize(
        "state", ["unspecified", "", "fresh", "cured", "dried", "cooked"]
    )
    def test_return_type_is_always_str(self, state: str) -> None:
        result = _apply_state_default(state)
        assert isinstance(
            result, str
        ), f"_apply_state_default({state!r}) returned {type(result).__name__}, expected str"
