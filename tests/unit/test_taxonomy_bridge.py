"""
Unit tests for TaxonomyBridge — the Tier 3 deterministic lookup component.

The bridge resolves a food description to a FoodEx2 ptm_category via fuzzy
matching against food_taxonomy.csv, then supplies food_properties rows for
that category.  These tests cover the bridge in isolation; pipeline integration
is in tests/integration/test_grounding_with_bridge.py.

Key invariants under test
-------------------------
- Exact and near-exact food names resolve above the default threshold (80).
- A composite-food blocklist guard short-circuits BEFORE fuzzy matching runs.
  (Verified structurally with monkeypatch, not just by outcome.)
- Alias map (beef → bovine, pork → pig, etc.) is applied before matching.
- Unknown foods return None; no false positives in the test vocabulary.
- Threshold calibration: all positive cases pass at 70/75/80/85; tornado stays
  below all four thresholds.  Chosen default: 80.
"""

import pytest
from unittest.mock import MagicMock

from app.services.grounding.taxonomy_bridge import TaxonomyBridge, TaxonomyResolution


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def bridge() -> TaxonomyBridge:
    """Real TaxonomyBridge loading production CSV data."""
    return TaxonomyBridge()


# ---------------------------------------------------------------------------
# Exact and near-exact matching
# ---------------------------------------------------------------------------

class TestExactAndNearMatches:

    def test_exact_match_turkey(self, bridge: TaxonomyBridge) -> None:
        """'turkey' matches the taxonomy food_name 'turkey' at score 100."""
        result = bridge.resolve("turkey")
        assert result is not None
        assert result.ptm_category == "poultry"
        assert result.match_score == pytest.approx(100.0)
        assert result.matched_food_name == "turkey"

    def test_exact_match_includes_taxonomy_metadata(self, bridge: TaxonomyBridge) -> None:
        """Resolution records the FoodEx2 code, label, and source for the winning row."""
        result = bridge.resolve("turkey")
        assert result is not None
        # Turkey fresh meat is A01SQ in FoodEx2 MTX 12.0 (first 'turkey' row in CSV)
        assert result.taxonomy_code == "A01SQ"
        assert result.taxonomy_label == "Turkey fresh meat"
        assert result.taxonomy_source_id == "EFSA-FoodEx2-MTX-12.0"

    def test_word_order_turkey_portions(self, bridge: TaxonomyBridge) -> None:
        """'turkey portions' resolves to the 'turkey' taxonomy entry above threshold."""
        result = bridge.resolve("turkey portions")
        assert result is not None
        assert result.ptm_category == "poultry"
        assert result.matched_food_name == "turkey"
        assert result.match_score >= bridge.threshold

    def test_word_order_independence(self, bridge: TaxonomyBridge) -> None:
        """token_set_ratio is order-invariant: 'raw chicken' and 'chicken raw' produce
        identical scores and resolve to the same matched food name."""
        r1 = bridge.resolve("raw chicken")
        r2 = bridge.resolve("chicken raw")
        assert r1 is not None
        assert r2 is not None
        assert r1.match_score == pytest.approx(r2.match_score)
        assert r1.matched_food_name == r2.matched_food_name

    def test_plural_tolerance_lettuce(self, bridge: TaxonomyBridge) -> None:
        """'lettuce' (singular) should score above threshold against 'lettuces' in taxonomy."""
        result = bridge.resolve("lettuce")
        assert result is not None
        assert result.ptm_category == "vegetable"
        assert result.match_score >= bridge.threshold

    def test_typo_tolerance_turkey(self, bridge: TaxonomyBridge) -> None:
        """'tukey' (missing r) should still resolve to the turkey entry above threshold."""
        result = bridge.resolve("tukey")
        assert result is not None
        assert result.ptm_category == "poultry"
        assert result.match_score >= bridge.threshold


# ---------------------------------------------------------------------------
# Below-threshold: no false positives
# ---------------------------------------------------------------------------

class TestBelowThreshold:

    def test_unknown_food_returns_none(self, bridge: TaxonomyBridge) -> None:
        """'tornado' shares no meaningful token overlap with any food_name; returns None."""
        result = bridge.resolve("tornado")
        assert result is None

    def test_gibberish_returns_none(self, bridge: TaxonomyBridge) -> None:
        """Completely unrelated string should return None at any threshold in 70–85."""
        result = bridge.resolve("xyzqwerty")
        assert result is None

    def test_empty_string_returns_none(self, bridge: TaxonomyBridge) -> None:
        """Empty input: token_set_ratio against any string is 0 → below threshold."""
        result = bridge.resolve("")
        assert result is None


# ---------------------------------------------------------------------------
# Composite-food blocklist
# ---------------------------------------------------------------------------

class TestCompositeBlocklist:

    def test_chicken_soup_returns_none(self, bridge: TaxonomyBridge) -> None:
        """'chicken soup' is a composite food; must return None even though 'chicken'
        alone would score 100 in fuzzy matching."""
        result = bridge.resolve("chicken soup")
        assert result is None

    def test_beef_stew_returns_none(self, bridge: TaxonomyBridge) -> None:
        result = bridge.resolve("beef stew")
        assert result is None

    def test_tuna_salad_returns_none(self, bridge: TaxonomyBridge) -> None:
        result = bridge.resolve("tuna salad")
        assert result is None

    def test_composite_blocklist_short_circuits_before_fuzzy(
        self, bridge: TaxonomyBridge, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The blocklist guard must run BEFORE fuzzy matching.

        This test verifies ordering, not merely outcome.  We replace
        _fuzzy_match_food_name with a function that raises AssertionError if
        called.  If the blocklist fires first, resolve() returns None without
        ever reaching the fuzzy step.
        """
        def exploding_fuzzy(*args: object, **kwargs: object) -> object:
            raise AssertionError(
                "_fuzzy_match_food_name must not be called for composite foods; "
                "blocklist guard should have returned None first"
            )

        monkeypatch.setattr(bridge, "_fuzzy_match_food_name", exploding_fuzzy)
        result = bridge.resolve("chicken soup")
        assert result is None

    def test_blocklist_does_not_block_plain_chicken(self, bridge: TaxonomyBridge) -> None:
        """Plain 'chicken' (no composite keyword) should still resolve via fuzzy match."""
        result = bridge.resolve("chicken")
        assert result is not None
        assert result.ptm_category == "poultry"


# ---------------------------------------------------------------------------
# Alias resolution
# ---------------------------------------------------------------------------

class TestAliasResolution:

    def test_beef_resolves_via_bovine_alias_to_meat(self, bridge: TaxonomyBridge) -> None:
        """'beef' is rewritten to 'bovine' before matching; resolves to meat category."""
        result = bridge.resolve("beef")
        assert result is not None
        assert result.ptm_category == "meat"
        # 'bovine' is the taxonomy food_name that wins the match after alias rewrite
        assert result.matched_food_name in ("bovine", "bovine and pig")

    def test_pork_resolves_via_pig_alias_to_meat(self, bridge: TaxonomyBridge) -> None:
        """'pork' is rewritten to 'pig' before matching."""
        result = bridge.resolve("pork")
        assert result is not None
        assert result.ptm_category == "meat"

    def test_lamb_resolves_via_sheep_alias(self, bridge: TaxonomyBridge) -> None:
        """'lamb' is rewritten to 'sheep'; 'sheep' is in taxonomy under meat category."""
        result = bridge.resolve("lamb")
        assert result is not None
        assert result.ptm_category == "meat"
        assert result.matched_food_name == "sheep"

    def test_mutton_resolves_via_sheep_alias(self, bridge: TaxonomyBridge) -> None:
        """'mutton' is also rewritten to 'sheep'."""
        result = bridge.resolve("mutton")
        assert result is not None
        assert result.ptm_category == "meat"

    def test_veal_resolves_via_calf_alias(self, bridge: TaxonomyBridge) -> None:
        """'veal' is rewritten to 'calf'; 'calf' appears in taxonomy under meat."""
        result = bridge.resolve("veal")
        assert result is not None
        assert result.ptm_category == "meat"
        assert result.matched_food_name == "calf"

    def test_alias_applied_before_fuzzy_not_after(
        self, bridge: TaxonomyBridge, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The alias rewrite must produce the post-alias string when _fuzzy_match_food_name
        is called.  We capture the argument to verify the alias was applied."""
        captured: list[str] = []
        original_fuzzy = bridge._fuzzy_match_food_name  # type: ignore[attr-defined]

        def capturing_fuzzy(text: str) -> TaxonomyResolution | None:
            captured.append(text)
            return original_fuzzy(text)

        monkeypatch.setattr(bridge, "_fuzzy_match_food_name", capturing_fuzzy)
        bridge.resolve("beef")
        assert len(captured) == 1
        # After alias substitution, "beef" becomes "bovine"
        assert captured[0] == "bovine"


# ---------------------------------------------------------------------------
# TaxonomyResolution property rows
# ---------------------------------------------------------------------------

class TestPropertyRows:

    def test_resolved_category_has_property_rows(self, bridge: TaxonomyBridge) -> None:
        """A successful resolution for turkey should supply non-empty property_rows
        from food_properties.csv for the poultry category."""
        result = bridge.resolve("turkey")
        assert result is not None
        assert len(result.property_rows) > 0

    def test_poultry_has_ph_row_and_aw_row(self, bridge: TaxonomyBridge) -> None:
        """Poultry category has exactly two food_properties rows: chicken (pH) and
        fresh poultry (aw).  Bridge integration for C1 depends on both being present."""
        result = bridge.resolve("turkey")
        assert result is not None
        assert result.ptm_category == "poultry"
        food_names_in_rows = {r["food_name"] for r in result.property_rows}
        assert "chicken" in food_names_in_rows
        assert "fresh poultry" in food_names_in_rows

    def test_meat_has_ph_and_aw_rows(self, bridge: TaxonomyBridge) -> None:
        """Meat category should provide both pH rows (beef ground, etc.) and
        aw rows (fresh meat, cured meat)."""
        result = bridge.resolve("beef")
        assert result is not None
        assert result.ptm_category == "meat"
        has_ph = any(r["ph_min"] for r in result.property_rows)
        has_aw = any(r["aw_min"] for r in result.property_rows)
        assert has_ph
        assert has_aw


# ---------------------------------------------------------------------------
# Threshold calibration (parametrized over 70 / 75 / 80 / 85)
#
# Purpose: verify that the chosen default threshold of 80 is the lowest value
# at which no false positives appear in this test vocabulary.  If all four
# thresholds behave identically (no case flips), we pick 80 for margin.
#
# True positives: turkey, turkey portions, turkeys, tukey, raw chicken, lettuce
# True negatives: tornado (max score ~57 across all taxonomy food_names)
# ---------------------------------------------------------------------------

THRESHOLD_POSITIVE_CASES = [
    "turkey",
    "turkey portions",
    "turkeys",
    "tukey",          # typo
    "raw chicken",
    "lettuce",        # singular vs. 'lettuces' in taxonomy
]

THRESHOLD_NEGATIVE_CASES = [
    "tornado",        # max score ~57, safely below 70
    "xyzqwerty",
]


@pytest.mark.parametrize("threshold", [70, 75, 80, 85])
@pytest.mark.parametrize("query", THRESHOLD_POSITIVE_CASES)
def test_threshold_calibration_positive(threshold: int, query: str) -> None:
    """Positive cases must resolve at all four candidate thresholds.

    If any case fails at a threshold, that threshold is too tight and the
    chosen default (80) must be re-evaluated.
    """
    b = TaxonomyBridge(threshold=threshold)
    result = b.resolve(query)
    assert result is not None, (
        f"query={query!r} expected to resolve at threshold={threshold}; "
        f"got None — threshold too tight or matching logic broken"
    )
    assert result.match_score >= threshold


@pytest.mark.parametrize("threshold", [70, 75, 80, 85])
@pytest.mark.parametrize("query", THRESHOLD_NEGATIVE_CASES)
def test_threshold_calibration_negative(threshold: int, query: str) -> None:
    """Negative cases must NOT resolve at any of the four candidate thresholds.

    If 'tornado' (max score ~57) resolves at 70, the threshold is dangerously
    low and the default of 80 would be the wrong choice.
    """
    b = TaxonomyBridge(threshold=threshold)
    result = b.resolve(query)
    assert result is None, (
        f"query={query!r} expected None at threshold={threshold}; "
        f"got resolution to {result.ptm_category!r} (matched {result.matched_food_name!r} "
        f"at score {result.match_score:.1f}) — false positive at this threshold"
    )
