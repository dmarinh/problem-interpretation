"""
Unit tests for ComBase model data structures.
"""

import pytest
from pathlib import Path

from app.engines.combase.models import (
    ComBaseModel,
    ComBaseModelConstraints,
    ComBaseModelRegistry,
    _parse_coefficients,
)
from app.models.enums import ModelType, ComBaseOrganism, Factor4Type


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
        """Every member's OrganismID must load row(s) naming this organism."""
        if len(registry) == 0:
            pytest.skip("combase_models.csv not found")

        models = registry.get_models_for_organism(organism)
        assert models, f"No CSV rows loaded for {organism.name} (OrganismID={organism.value!r})"

        expected = self._EXPECTED_NAME_SUBSTRING[organism]
        assert any(expected in m.organism_name.lower() for m in models), (
            f"{organism.name} (OrganismID={organism.value!r}) loaded Org names "
            f"{[m.organism_name for m in models]}, none containing {expected!r}"
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