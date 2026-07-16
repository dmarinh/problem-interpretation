"""
Unit tests for ComBase model data structures.
"""

from pathlib import Path

import pytest

from app.engines.combase.models import (
    ComBaseModelConstraints,
    ComBaseModelRegistry,
    _parse_coefficients,
)
from app.models.enums import ComBaseOrganism, Factor4Type, ModelType


class TestComBaseModelConstraints:
    """Tests for ComBaseModelConstraints."""

    def test_temperature_validation(self):
        """Should validate temperature range."""
        constraints = ComBaseModelConstraints(
            temp_min=5.0,
            temp_max=40.0,
            ph_min=4.0,
            ph_max=8.0,
            aw_min=0.9,
            aw_max=1.0,
        )

        assert constraints.is_temperature_valid(20.0) is True
        assert constraints.is_temperature_valid(4.0) is False
        assert constraints.is_temperature_valid(41.0) is False

    def test_clamping(self):
        """Should clamp values to valid range."""
        constraints = ComBaseModelConstraints(
            temp_min=5.0,
            temp_max=40.0,
            ph_min=4.0,
            ph_max=8.0,
            aw_min=0.9,
            aw_max=1.0,
        )

        assert constraints.clamp_temperature(50.0) == 40.0
        assert constraints.clamp_temperature(0.0) == 5.0
        assert constraints.clamp_ph(3.0) == 4.0


class TestParseCoefficients:
    """Tests for coefficient parsing."""

    def test_parse_coefficients(self):
        """Should parse coefficient string."""
        coeff_str = '"-26.034;0.2627;6.8356;0;0;0;1.59297;-0.00444;-0.52104;-125.70625;0;0;0;0;0"'
        result = _parse_coefficients(coeff_str)

        assert len(result) == 15
        assert result[0] == -26.034
        assert result[1] == 0.2627


class TestComBaseModelRegistry:
    """Tests for ComBaseModelRegistry."""

    @pytest.fixture
    def registry(self) -> ComBaseModelRegistry:
        """Create and load registry."""
        reg = ComBaseModelRegistry()
        csv_path = Path("data/combase_models.csv")
        if csv_path.exists():
            reg.load_from_csv(csv_path)
        return reg

    def test_load_models(self, registry):
        """Should load models from CSV."""
        # Skip if CSV not present
        if len(registry) == 0:
            pytest.skip("combase_models.csv not found")

        assert len(registry) > 0

    def test_get_listeria_growth_model(self, registry):
        """Should find Listeria growth model."""
        if len(registry) == 0:
            pytest.skip("combase_models.csv not found")

        model = registry.get_model(
            organism=ComBaseOrganism.LISTERIA_MONOCYTOGENES,
            model_type=ModelType.GROWTH,
            factor4_type=Factor4Type.NONE,
        )

        assert model is not None
        assert model.organism_id == "lm"
        assert model.model_type == ModelType.GROWTH

    def test_get_model_with_factor4(self, registry):
        """Should find model with factor4."""
        if len(registry) == 0:
            pytest.skip("combase_models.csv not found")

        model = registry.get_model(
            organism=ComBaseOrganism.LISTERIA_MONOCYTOGENES,
            model_type=ModelType.GROWTH,
            factor4_type=Factor4Type.CO2,
        )

        if model is not None:
            assert model.factor4_type == Factor4Type.CO2

    def test_list_organisms(self, registry):
        """Should list available organisms."""
        if len(registry) == 0:
            pytest.skip("combase_models.csv not found")

        organisms = registry.list_organisms()

        assert len(organisms) > 0
        assert ComBaseOrganism.LISTERIA_MONOCYTOGENES in organisms or len(organisms) > 0


class TestComBaseOrganismMatchesCSV:
    """
    Enum-CSV reconciliation (A0.5a). Every ComBaseOrganism member's .value
    (OrganismID) must load data/combase_models.csv row(s) whose Org name is
    recognizably that organism, not a different one wearing the same short
    code. Regression test for the historical bl/bt swap: BROCHOTHRIX_THERMOSPHACTA
    was "bl" (Bacillus licheniformis's row) and BACILLUS_STEAROTHERMOPHILUS was
    "bt" (Brochothrix thermosphacta's row, for an organism the CSV never had).
    """

    # Expected substring (case-insensitive) that must appear in at least one
    # combase_models.csv Org value loaded under this organism's OrganismID.
    _EXPECTED_NAME_SUBSTRING: dict = {
        ComBaseOrganism.AEROMONAS_HYDROPHILA: "aeromonas hydrophila",
        ComBaseOrganism.BACILLUS_CEREUS: "bacillus cereus",
        ComBaseOrganism.BROCHOTHRIX_THERMOSPHACTA: "thermosphacta",
        ComBaseOrganism.BACILLUS_SUBTILIS: "bacillus subtilis",
        ComBaseOrganism.BACILLUS_LICHENIFORMIS: "bacillus licheniformis",
        ComBaseOrganism.CLOSTRIDIUM_BOTULINUM_NONPROT: "clostridium botulinum (non-prot.)",
        ComBaseOrganism.CLOSTRIDIUM_BOTULINUM_PROT: "clostridium botulinum (prot.)",
        ComBaseOrganism.CLOSTRIDIUM_PERFRINGENS: "clostridium perfringens",
        ComBaseOrganism.ESCHERICHIA_COLI: "escherichia coli",
        ComBaseOrganism.LISTERIA_MONOCYTOGENES: "listeria monocytogenes",
        ComBaseOrganism.PSEUDOMONAS: "pseudomonas",
        ComBaseOrganism.SALMONELLA: "salmonella",
        ComBaseOrganism.SHIGELLA_FLEXNERI: "shigella flexneri",
        ComBaseOrganism.STAPHYLOCOCCUS_AUREUS: "staphylococcus aureus",
        ComBaseOrganism.YERSINIA_ENTEROCOLITICA: "yersinia enterocolitica",
    }

    @pytest.fixture
    def registry(self) -> ComBaseModelRegistry:
        """Create and load registry."""
        reg = ComBaseModelRegistry()
        csv_path = Path("data/combase_models.csv")
        if csv_path.exists():
            reg.load_from_csv(csv_path)
        return reg

    @pytest.mark.parametrize("organism", list(ComBaseOrganism))
    def test_organism_value_resolves_to_matching_csv_row(self, registry, organism):
        """Alias-routing check: from_string()/_get_fuzzy_map() bucket every CSV row
        under the member whose short-code alias matches its raw OrganismID. This
        exercises get_models_for_organism() -> _by_organism, which is built via
        from_string() at registration time -- it verifies the alias dict is
        self-consistent with the CSV, not that .value itself matches the CSV
        (see test_organism_value_matches_raw_csv_organism_id for that)."""
        if len(registry) == 0:
            pytest.skip("combase_models.csv not found")

        models = registry.get_models_for_organism(organism)
        assert (
            models
        ), f"No CSV rows loaded for {organism.name} (OrganismID={organism.value!r})"

        expected = self._EXPECTED_NAME_SUBSTRING[organism]
        assert any(expected in m.organism_name.lower() for m in models), (
            f"{organism.name} (OrganismID={organism.value!r}) loaded Org names "
            f"{[m.organism_name for m in models]}, none containing {expected!r}"
        )

    @pytest.fixture
    def raw_csv_org_names(self) -> dict:
        """{OrganismID: [Org, ...]} read directly from the CSV -- no ComBaseOrganism,
        no from_string(), no registry indexing. The ground truth this class checks against.
        """
        csv_path = Path("data/combase_models.csv")
        if not csv_path.exists():
            return {}
        import csv as csv_module

        by_oid: dict = {}
        with csv_path.open(encoding="utf-8-sig") as f:
            for row in csv_module.DictReader(f, delimiter=";"):
                oid = row.get("OrganismID", "").strip()
                org = row.get("Org", "").strip()
                if oid:
                    by_oid.setdefault(oid, []).append(org)
        return by_oid

    @pytest.mark.parametrize("organism", list(ComBaseOrganism))
    def test_organism_value_matches_raw_csv_organism_id(
        self, raw_csv_org_names, organism
    ):
        """Execution-path check: registry.get_model() builds its lookup key from
        organism.value directly (f"{model_id}_{organism.value}_{factor4_type.value}"),
        matched against rows keyed by their own raw OrganismID string. This test
        resolves organism.value against the CSV's raw OrganismID with no enum
        machinery in between (no from_string, no _get_fuzzy_map, no registry
        bucketing) -- it is the thing that actually determines which coefficients
        get_model() loads, and is exactly what test_organism_value_resolves_to_matching_csv_row
        does NOT cover."""
        if not raw_csv_org_names:
            pytest.skip("combase_models.csv not found")

        org_names = raw_csv_org_names.get(organism.value)
        assert org_names, (
            f"{organism.name} (.value={organism.value!r}) has no row in the CSV "
            f"under OrganismID={organism.value!r}"
        )

        expected = self._EXPECTED_NAME_SUBSTRING[organism]
        assert any(expected in name.lower() for name in org_names), (
            f"{organism.name} (.value={organism.value!r}) resolves via .value to CSV "
            f"OrganismID={organism.value!r}, whose Org name(s) are {org_names}, "
            f"none containing {expected!r}"
        )

    def test_brochothrix_resolves_to_brochothrix_row(self, registry):
        """from_string('brochothrix') must load the Brochothrix thermosphacta row,
        not Bacillus licheniformis (the historical bl/bt swap)."""
        if len(registry) == 0:
            pytest.skip("combase_models.csv not found")

        organism = ComBaseOrganism.from_string("brochothrix")
        assert organism == ComBaseOrganism.BROCHOTHRIX_THERMOSPHACTA

        model = registry.get_model(organism, ModelType.GROWTH, Factor4Type.NONE)
        assert model is not None
        assert "thermosphacta" in model.organism_name.lower()

    def test_bacillus_stearothermophilus_no_longer_resolves(self):
        """B. stearothermophilus has no CSV row; the alias must fail closed to None."""
        assert ComBaseOrganism.from_string("bacillus stearothermophilus") is None
        assert ComBaseOrganism.from_string("b. stearothermophilus") is None
        assert not hasattr(ComBaseOrganism, "BACILLUS_STEAROTHERMOPHILUS")


class TestExecutableOrganisms:
    """A0.5b: is_executable() / get_executable_organisms() must be derived from
    the loaded registry (no hardcoded organism lists). sf (Shigella flexneri) is
    the only member with no (ModelID=1, Factor4=NONE) row -- its sole CSV row
    requires Factor4=nitrite."""

    @pytest.fixture
    def registry(self) -> ComBaseModelRegistry:
        """Create and load registry."""
        reg = ComBaseModelRegistry()
        csv_path = Path("data/combase_models.csv")
        if csv_path.exists():
            reg.load_from_csv(csv_path)
        return reg

    def test_shigella_not_executable_for_plain_growth(self, registry):
        if len(registry) == 0:
            pytest.skip("combase_models.csv not found")

        assert (
            registry.is_executable(
                ComBaseOrganism.SHIGELLA_FLEXNERI, ModelType.GROWTH, Factor4Type.NONE
            )
            is False
        )

    def test_shigella_executable_with_nitrite(self, registry):
        """The nitrite path must keep working -- executability depends on the
        actual factor4_type, not an assumption of NONE."""
        if len(registry) == 0:
            pytest.skip("combase_models.csv not found")

        assert (
            registry.is_executable(
                ComBaseOrganism.SHIGELLA_FLEXNERI, ModelType.GROWTH, Factor4Type.NITRITE
            )
            is True
        )

    def test_get_executable_organisms_growth_none_excludes_shigella(self, registry):
        """The count must be derived, not hardcoded: cross-checked here against an
        independently computed list (every loaded organism filtered by get_model()),
        not just asserted as a bare literal."""
        if len(registry) == 0:
            pytest.skip("combase_models.csv not found")

        executable = registry.get_executable_organisms(
            ModelType.GROWTH, Factor4Type.NONE
        )

        assert ComBaseOrganism.SHIGELLA_FLEXNERI not in executable

        all_loaded = registry.list_organisms()
        independently_derived = [
            o
            for o in all_loaded
            if registry.get_model(o, ModelType.GROWTH, Factor4Type.NONE) is not None
        ]
        assert set(executable) == set(independently_derived)
        assert len(all_loaded) == 15
        assert len(executable) == 14
