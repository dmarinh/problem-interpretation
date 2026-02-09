"""
Unit tests for core enums.
"""

import pytest
from app.models.enums import (
    ModelType,
    ComBaseOrganism,
    Factor4Type,
)


class TestModelType:
    """Tests for ModelType enum."""
    
    def test_from_model_id_growth(self):
        """ModelID 1 should map to GROWTH."""
        assert ModelType.from_model_id(1) == ModelType.GROWTH
    
    def test_from_model_id_thermal_inactivation(self):
        """ModelID 2 should map to THERMAL_INACTIVATION."""
        assert ModelType.from_model_id(2) == ModelType.THERMAL_INACTIVATION
    
    def test_from_model_id_non_thermal_survival(self):
        """ModelID 3 should map to NON_THERMAL_SURVIVAL."""
        assert ModelType.from_model_id(3) == ModelType.NON_THERMAL_SURVIVAL


class TestComBaseOrganism:
    """Tests for ComBaseOrganism enum."""
    
    def test_all_values_are_lowercase(self):
        """All enum values should be lowercase."""
        for member in ComBaseOrganism:
            assert member.value == member.value.lower()
    
    def test_from_string_exact_match(self):
        """Should match exact organism IDs."""
        assert ComBaseOrganism.from_string("lm") == ComBaseOrganism.LISTERIA_MONOCYTOGENES
        assert ComBaseOrganism.from_string("ss") == ComBaseOrganism.SALMONELLA
        assert ComBaseOrganism.from_string("ec") == ComBaseOrganism.ESCHERICHIA_COLI
    
    def test_from_string_common_names(self):
        """Should match common pathogen names."""
        assert ComBaseOrganism.from_string("listeria") == ComBaseOrganism.LISTERIA_MONOCYTOGENES
        assert ComBaseOrganism.from_string("salmonella") == ComBaseOrganism.SALMONELLA
        assert ComBaseOrganism.from_string("e. coli") == ComBaseOrganism.ESCHERICHIA_COLI
        assert ComBaseOrganism.from_string("E.coli") == ComBaseOrganism.ESCHERICHIA_COLI
        assert ComBaseOrganism.from_string("staph") == ComBaseOrganism.STAPHYLOCOCCUS_AUREUS
    
    def test_from_string_no_match(self):
        """Should return None for unknown organisms."""
        assert ComBaseOrganism.from_string("unknown_bug") is None
    
    def test_from_string_case_insensitive(self):
        """Should be case insensitive."""
        assert ComBaseOrganism.from_string("LISTERIA") == ComBaseOrganism.LISTERIA_MONOCYTOGENES
        assert ComBaseOrganism.from_string("Salmonella") == ComBaseOrganism.SALMONELLA


class TestFactor4Type:
    """Tests for Factor4Type enum."""
    
    def test_from_string_none(self):
        """NULL and None should map to NONE."""
        assert Factor4Type.from_string(None) == Factor4Type.NONE
        assert Factor4Type.from_string("NULL") == Factor4Type.NONE
        assert Factor4Type.from_string("") == Factor4Type.NONE
    
    def test_from_string_co2(self):
        """Should match CO2."""
        assert Factor4Type.from_string("co2") == Factor4Type.CO2
        assert Factor4Type.from_string("CO2") == Factor4Type.CO2
    
    def test_from_string_acids(self):
        """Should match acid types."""
        assert Factor4Type.from_string("lactic_acid") == Factor4Type.LACTIC_ACID
        assert Factor4Type.from_string("lactic") == Factor4Type.LACTIC_ACID
        assert Factor4Type.from_string("acetic_acid") == Factor4Type.ACETIC_ACID
        assert Factor4Type.from_string("nitrite") == Factor4Type.NITRITE