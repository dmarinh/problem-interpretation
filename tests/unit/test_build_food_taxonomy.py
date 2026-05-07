"""
Tests for build_food_taxonomy.

Run: pytest tests/test_build_food_taxonomy.py -v
"""

from __future__ import annotations

import csv
import textwrap
from pathlib import Path

import pytest

from build_food_taxonomy import (
    AnchorSpec,
    Term,
    apply_species_override,
    build_row,
    build_taxonomy,
    descendants_of,
    load_alignment,
    normalize_label,
    parse_mtx,
)


# ---------------------------------------------------------------------------
# normalize_label — the most user-visible single function
# ---------------------------------------------------------------------------

class TestNormalizeLabel:
    @pytest.mark.parametrize("label, food_name, state", [
        # Canonical species + 'fresh meat' suffix
        ("Turkey fresh meat",        "turkey",            "fresh"),
        ("Chicken fresh meat",       "chicken",           "fresh"),
        ("Bovine fresh meat",        "bovine",            "fresh"),
        # State word elsewhere in the label
        ("Smoked salmon",            "salmon",            "smoked"),
        ("Cooked pork ham",          "pork ham",          "cooked"),
        ("Dried bovine meat",        "bovine",            "dried"),
        # No state keyword present
        ("White bread",              "white bread",       "unspecified"),
        ("Cheese, camembert",        "cheese camembert",  "unspecified"),
        ("Lettuces (generic)",       "lettuces",          "unspecified"),
        # Stop-phrase strip with no state keyword. Note: category-level nodes
        # often have verbose food_names — they are hierarchy roots, not realistic
        # lookup keys, so this is acceptable.
        ("Eggs and egg products",    "eggs and egg products",  "unspecified"),
        # Composite phrases: don't over-strip
        ("Peanut butter",            "peanut butter",     "unspecified"),
    ])
    def test_examples(self, label, food_name, state):
        got_name, got_state = normalize_label(label)
        assert got_name == food_name
        assert got_state == state

    def test_only_first_state_keyword_extracted(self):
        # 'fresh' comes before 'cooked' in STATE_KEYWORDS list order
        name, state = normalize_label("Fresh and cooked stuff")
        assert state == "fresh"
        # 'cooked' should remain in the food_name because we extract one only
        assert "cooked" in name

    def test_lowercase_invariant(self):
        a = normalize_label("TURKEY FRESH MEAT")
        b = normalize_label("turkey fresh meat")
        assert a == b


# ---------------------------------------------------------------------------
# apply_species_override
# ---------------------------------------------------------------------------

class TestSpeciesOverride:
    @pytest.mark.parametrize("label, expected", [
        ("Cooked turkey ham",              "poultry"),
        ("Chicken sausage smoked",         "poultry"),
        ("Duck rillette",                  "poultry"),
        ("Goose liver paté",               "poultry"),
        # Mammal products keep the default 'meat'
        ("Cooked pork ham",                "meat"),
        ("Beef bologna sausage",           "meat"),
        ("Bacon",                          "meat"),
        # Edge: 'chamois' contains 'cham' but not 'chicken' — must not match
        ("Chamois fresh meat",             "meat"),
    ])
    def test_override(self, label, expected):
        assert apply_species_override(label, default_category="meat") == expected


# ---------------------------------------------------------------------------
# load_alignment
# ---------------------------------------------------------------------------

ALIGNMENT_HEADER = "foodex2_code,foodex2_name,treatment,ptm_category,sub_anchors,notes\n"

def _write_csv(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "alignment.csv"
    p.write_text(ALIGNMENT_HEADER + textwrap.dedent(body).lstrip(), encoding="utf-8")
    return p


class TestLoadAlignment:
    def test_direct_only(self, tmp_path):
        p = _write_csv(tmp_path, """
            A000J,Grains,DIRECT,grain,,Direct
            A031E,Eggs,DIRECT,eggs,,Direct
        """)
        anchors = load_alignment(p)
        assert [(a.code, a.ptm_category) for a in anchors] == \
               [("A000J", "grain"), ("A031E", "eggs")]
        assert all(not a.apply_species_override for a in anchors)

    def test_descend_expands_sub_anchors(self, tmp_path):
        p = _write_csv(tmp_path, """
            A0EZS,Mammals and birds,DESCEND,,A0EYF→meat;A0EYG→poultry,Split
        """)
        anchors = load_alignment(p)
        codes = {a.code for a in anchors}
        assert codes == {"A0EYF", "A0EYG"}

    def test_descend_with_a0bxt_marks_species_override(self, tmp_path):
        p = _write_csv(tmp_path, """
            A0EZS,Mammals,DESCEND,,A0EYF→meat;A0EYG→poultry;A0BXT→meat,Split
        """)
        anchors = load_alignment(p)
        a0bxt = next(a for a in anchors if a.code == "A0BXT")
        a0eyf = next(a for a in anchors if a.code == "A0EYF")
        assert a0bxt.apply_species_override is True
        assert a0eyf.apply_species_override is False

    def test_out_of_scope_and_defer_skipped(self, tmp_path):
        p = _write_csv(tmp_path, """
            A03PV,Infant,OUT_OF_SCOPE,,,Skip
            A03VA,Composite dishes,DEFER,,,Skip
            A000J,Grains,DIRECT,grain,,Keep
        """)
        anchors = load_alignment(p)
        assert [a.code for a in anchors] == ["A000J"]

    def test_direct_without_category_raises(self, tmp_path):
        p = _write_csv(tmp_path, """
            A000J,Grains,DIRECT,,,Missing category
        """)
        with pytest.raises(ValueError, match="no ptm_category"):
            load_alignment(p)

    def test_duplicate_anchor_raises(self, tmp_path):
        p = _write_csv(tmp_path, """
            A000J,Grains,DIRECT,grain,,One
            A0EZS,Foo,DESCEND,,A000J→grain,Conflict
        """)
        with pytest.raises(ValueError, match="listed twice"):
            load_alignment(p)


# ---------------------------------------------------------------------------
# descendants_of (uses a small synthetic terms dict)
# ---------------------------------------------------------------------------

def _t(code, name, parent=None, hierarchy="report"):
    parents = {hierarchy: parent} if parent else {}
    return Term(code=code, name=name, scope_note="", parents=parents)


class TestDescendants:
    def _tree(self):
        # root → a → a1, a2; b → b1
        # tree separate (no parent for root, b)
        return {
            "ROOT": _t("ROOT", "root"),
            "A":    _t("A", "a", parent="ROOT"),
            "A1":   _t("A1", "a1", parent="A"),
            "A2":   _t("A2", "a2", parent="A"),
            "B":    _t("B", "b", parent="ROOT"),
            "B1":   _t("B1", "b1", parent="B"),
        }

    def test_includes_anchor_itself(self):
        terms = self._tree()
        result = descendants_of("A", terms)
        assert "A" in result

    def test_includes_all_descendants(self):
        terms = self._tree()
        result = set(descendants_of("ROOT", terms))
        assert result == {"ROOT", "A", "A1", "A2", "B", "B1"}

    def test_subtree_only(self):
        terms = self._tree()
        assert set(descendants_of("A", terms)) == {"A", "A1", "A2"}

    def test_unknown_anchor_returns_empty(self):
        terms = self._tree()
        assert descendants_of("ZZZ", terms) == []

    def test_other_hierarchies_ignored(self):
        terms = {
            "ROOT": _t("ROOT", "root"),
            "X":    Term(code="X", name="x", scope_note="",
                         parents={"report": "ROOT", "expo": "OTHER"}),
            "Y":    Term(code="Y", name="y", scope_note="",
                         parents={"expo": "OTHER"}),  # not in report
        }
        result = descendants_of("ROOT", terms)
        assert "X" in result
        assert "Y" not in result  # Y is in expo only


# ---------------------------------------------------------------------------
# build_row — integrates normalization, parent lookup, and override
# ---------------------------------------------------------------------------

class TestBuildRow:
    def test_simple_direct_anchor(self):
        terms = {
            "A031E": _t("A031E", "Eggs and egg products"),
            "A0F6E": _t("A0F6E", "Egg mixed whole", parent="A031E"),
        }
        anchor = AnchorSpec(code="A031E", ptm_category="eggs",
                            apply_species_override=False)
        row = build_row(terms["A0F6E"], anchor, terms)
        assert row["food_name"] == "egg mixed whole"
        assert row["foodex2_code"] == "A0F6E"
        assert row["foodex2_label"] == "Egg mixed whole"
        assert row["foodex2_parent_code"] == "A031E"
        assert row["foodex2_parent_label"] == "Eggs and egg products"
        assert row["ptm_category"] == "eggs"
        assert row["state"] == "unspecified"

    def test_a0bxt_anchor_applies_poultry_override(self):
        terms = {
            "A0BXT":  _t("A0BXT", "Processed or preserved meat"),
            "TURKEY": _t("TURKEY", "Cooked turkey ham", parent="A0BXT"),
            "PORK":   _t("PORK", "Cooked pork ham", parent="A0BXT"),
        }
        anchor = AnchorSpec(code="A0BXT", ptm_category="meat",
                            apply_species_override=True)
        turkey_row = build_row(terms["TURKEY"], anchor, terms)
        pork_row = build_row(terms["PORK"], anchor, terms)
        assert turkey_row["ptm_category"] == "poultry"
        assert pork_row["ptm_category"] == "meat"

    def test_orphan_parent_handled(self):
        # parent code present but not in terms dict
        terms = {
            "X": Term(code="X", name="X label", scope_note="",
                      parents={"report": "MISSING_PARENT"}),
        }
        anchor = AnchorSpec(code="X", ptm_category="grain",
                            apply_species_override=False)
        row = build_row(terms["X"], anchor, terms)
        assert row["foodex2_parent_code"] == "MISSING_PARENT"
        assert row["foodex2_parent_label"] == ""


# ---------------------------------------------------------------------------
# build_taxonomy — small end-to-end on a synthetic MTX-like XML
# ---------------------------------------------------------------------------

SYNTH_MTX = """<?xml version='1.0' encoding='UTF-8'?>
<message>
  <catalogue>
    <catalogueDesc><code>MTX</code></catalogueDesc>
    <term>
      <termDesc><termCode>R</termCode><termExtendedName>Food</termExtendedName>
                <termScopeNote>root</termScopeNote></termDesc>
    </term>
    <term>
      <termDesc><termCode>BIRDS</termCode><termExtendedName>Birds meat</termExtendedName>
                <termScopeNote>birds</termScopeNote></termDesc>
      <hierarchyAssignments><hierarchyAssignment>
        <hierarchyCode>report</hierarchyCode><parentCode>R</parentCode>
      </hierarchyAssignment></hierarchyAssignments>
    </term>
    <term>
      <termDesc><termCode>TURK</termCode><termExtendedName>Turkey fresh meat</termExtendedName>
                <termScopeNote>raw turkey</termScopeNote></termDesc>
      <hierarchyAssignments><hierarchyAssignment>
        <hierarchyCode>report</hierarchyCode><parentCode>BIRDS</parentCode>
      </hierarchyAssignment></hierarchyAssignments>
    </term>
    <term>
      <termDesc><termCode>OTHER</termCode><termExtendedName>Out of scope</termExtendedName>
                <termScopeNote>x</termScopeNote></termDesc>
    </term>
  </catalogue>
</message>
"""

class TestEndToEnd:
    def test_synthetic_mtx_to_taxonomy(self, tmp_path):
        mtx = tmp_path / "mtx.xml"
        mtx.write_text(SYNTH_MTX, encoding="utf-8")
        align = _write_csv(tmp_path, """
            BIRDS,Birds meat,DIRECT,poultry,,test
        """)
        rows = build_taxonomy(mtx, align)
        codes = sorted(r["foodex2_code"] for r in rows)
        assert codes == ["BIRDS", "TURK"]  # OTHER not under any anchor
        turk = next(r for r in rows if r["foodex2_code"] == "TURK")
        assert turk["food_name"] == "turkey"
        assert turk["state"] == "fresh"
        assert turk["ptm_category"] == "poultry"
        assert turk["source_id"] == "EFSA-FoodEx2-MTX-12.0"
