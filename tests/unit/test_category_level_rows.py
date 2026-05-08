"""
Unit tests for data/rag/category_level_rows.csv and TaxonomyBridge.lookup_category_level_row.

Validates two things:
1. The CSV file has the correct schema and the 5 curated rows are present and well-formed.
2. TaxonomyBridge.lookup_category_level_row(category, state, field) -> dict | None
   returns the correct row for each curated entry and None for everything else.

The 5 curated rows:
  poultry + fresh + aw  → fresh poultry (IFT-2003-T31)
  meat    + fresh + aw  → fresh meat   (IFT-2003-T31)
  meat    + cured + aw  → cured meat   (IFT-2003-T31)
  fish    + fresh + ph  → fish fresh most (IFT-2003-T33)
  eggs    + fresh + aw  → eggs         (IFT-2003-T31)

Design rationale: the bridge inherits ONLY from rows that a source authority
published as category-wide claims.  No envelope-across-all-rows, no cross-species
pH borrowing (e.g. chicken → poultry pH is gone).
"""

import csv
from pathlib import Path

import pytest

from app.services.grounding.taxonomy_bridge import TaxonomyBridge

_REPO_ROOT = Path(__file__).parent.parent.parent
_CATEGORY_LEVEL_ROWS_CSV = _REPO_ROOT / "data" / "rag" / "category_level_rows.csv"

REQUIRED_COLUMNS = {
    "food_name", "ptm_category", "state",
    "ph_min", "ph_max", "ph_source_id",
    "aw_min", "aw_max", "aw_source_id",
}


# ---------------------------------------------------------------------------
# CSV schema
# ---------------------------------------------------------------------------

class TestCategoryLevelRowsCsvSchema:

    def test_csv_file_exists(self) -> None:
        assert _CATEGORY_LEVEL_ROWS_CSV.exists(), (
            f"category_level_rows.csv not found at {_CATEGORY_LEVEL_ROWS_CSV}"
        )

    def test_csv_has_required_columns(self) -> None:
        with _CATEGORY_LEVEL_ROWS_CSV.open(encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            columns = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - columns
        assert not missing, f"Missing columns in category_level_rows.csv: {missing}"

    def test_csv_has_exactly_five_rows(self) -> None:
        with _CATEGORY_LEVEL_ROWS_CSV.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 5, (
            f"Expected 5 curated rows, got {len(rows)}.  "
            "Add rows only after updating the design spec."
        )

    @pytest.mark.parametrize("category, state, field_col, expected_food_name, expected_source", [
        ("poultry", "fresh", "aw_min",  "fresh poultry",   "IFT-2003-T31"),
        ("meat",    "fresh", "aw_min",  "fresh meat",      "IFT-2003-T31"),
        ("meat",    "cured", "aw_min",  "cured meat",      "IFT-2003-T31"),
        ("fish",    "fresh", "ph_min",  "fish fresh most", "IFT-2003-T33"),
        ("eggs",    "fresh", "aw_min",  "eggs",            "IFT-2003-T31"),
    ])
    def test_curated_row_present_and_named(
        self,
        category: str,
        state: str,
        field_col: str,
        expected_food_name: str,
        expected_source: str,
    ) -> None:
        with _CATEGORY_LEVEL_ROWS_CSV.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        matches = [
            r for r in rows
            if r["ptm_category"] == category
            and r["state"] == state
            and r.get(field_col, "").strip()
        ]
        assert matches, f"No row for ({category!r}, {state!r}, {field_col!r})"
        assert any(r["food_name"] == expected_food_name for r in matches), (
            f"Expected food_name {expected_food_name!r} in ({category}, {state}) rows; "
            f"found: {[r['food_name'] for r in matches]}"
        )
        source_col = "ph_source_id" if "ph" in field_col else "aw_source_id"
        assert any(expected_source in r.get(source_col, "") for r in matches), (
            f"Expected source {expected_source!r} in ({category}, {state}) {source_col}"
        )


# ---------------------------------------------------------------------------
# TaxonomyBridge.lookup_category_level_row
# ---------------------------------------------------------------------------

@pytest.fixture
def bridge() -> TaxonomyBridge:
    """Real TaxonomyBridge loading production CSV data."""
    return TaxonomyBridge()


class TestLookupCategoryLevelRowHits:

    @pytest.mark.parametrize("category, state, field", [
        ("poultry", "fresh", "aw"),
        ("meat",    "fresh", "aw"),
        ("meat",    "cured", "aw"),
        ("fish",    "fresh", "ph"),
        ("eggs",    "fresh", "aw"),
    ])
    def test_curated_row_found(
        self, bridge: TaxonomyBridge, category: str, state: str, field: str
    ) -> None:
        result = bridge.lookup_category_level_row(category, state, field)
        assert result is not None, (
            f"lookup_category_level_row({category!r}, {state!r}, {field!r}) "
            f"returned None — expected a curated row"
        )

    def test_poultry_fresh_aw_values(self, bridge: TaxonomyBridge) -> None:
        result = bridge.lookup_category_level_row("poultry", "fresh", "aw")
        assert result is not None
        assert float(result["aw_min"]) == pytest.approx(0.99)
        assert float(result["aw_max"]) == pytest.approx(1.0)
        assert result["aw_source_id"] == "IFT-2003-T31"

    def test_meat_fresh_aw_values(self, bridge: TaxonomyBridge) -> None:
        result = bridge.lookup_category_level_row("meat", "fresh", "aw")
        assert result is not None
        assert float(result["aw_min"]) == pytest.approx(0.99)
        assert float(result["aw_max"]) == pytest.approx(1.0)

    def test_meat_cured_aw_values(self, bridge: TaxonomyBridge) -> None:
        result = bridge.lookup_category_level_row("meat", "cured", "aw")
        assert result is not None
        assert float(result["aw_min"]) == pytest.approx(0.87)
        assert float(result["aw_max"]) == pytest.approx(0.95)
        assert result["aw_source_id"] == "IFT-2003-T31"

    def test_fish_fresh_ph_values(self, bridge: TaxonomyBridge) -> None:
        result = bridge.lookup_category_level_row("fish", "fresh", "ph")
        assert result is not None
        assert float(result["ph_min"]) == pytest.approx(6.6)
        assert float(result["ph_max"]) == pytest.approx(6.8)
        assert result["ph_source_id"] == "IFT-2003-T33"

    def test_eggs_fresh_aw_values(self, bridge: TaxonomyBridge) -> None:
        result = bridge.lookup_category_level_row("eggs", "fresh", "aw")
        assert result is not None
        assert float(result["aw_min"]) == pytest.approx(0.97)
        assert float(result["aw_max"]) == pytest.approx(0.97)

    def test_returned_dict_has_all_required_keys(self, bridge: TaxonomyBridge) -> None:
        result = bridge.lookup_category_level_row("poultry", "fresh", "aw")
        assert result is not None
        for key in ("food_name", "ptm_category", "state", "aw_min", "aw_max", "aw_source_id"):
            assert key in result, f"Key {key!r} missing from returned dict"


class TestLookupCategoryLevelRowMisses:

    @pytest.mark.parametrize("category, state, field, reason", [
        ("poultry", "fresh",  "ph",  "no curated pH row for poultry"),
        ("vegetable","fresh", "ph",  "vegetable not in curated rows"),
        ("vegetable","fresh", "aw",  "vegetable not in curated rows"),
        ("poultry", "cured",  "aw",  "no curated cured-poultry aw row"),
        ("meat",    "dried",  "aw",  "no curated dried-meat aw row"),
        ("fish",    "fresh",  "aw",  "no curated fish aw row"),
        ("eggs",    "fresh",  "ph",  "no curated eggs pH row"),
        ("unknown", "fresh",  "aw",  "category does not exist in curated rows"),
    ])
    def test_no_row_returns_none(
        self, bridge: TaxonomyBridge, category: str, state: str, field: str, reason: str
    ) -> None:
        result = bridge.lookup_category_level_row(category, state, field)
        assert result is None, (
            f"lookup_category_level_row({category!r}, {state!r}, {field!r}) "
            f"returned {result!r} but expected None — {reason}"
        )
