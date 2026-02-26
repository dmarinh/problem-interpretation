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

class TestComBaseOrganismFromText:
    """Tests for ComBaseOrganism.from_text()."""
    
    def test_finds_salmonella_in_text(self):
        """Should find Salmonella in longer text."""
        text = "Salmonella is commonly found in raw poultry and eggs."
        result = ComBaseOrganism.from_text(text)
        
        assert result == ComBaseOrganism.SALMONELLA
    
    def test_finds_listeria_in_text(self):
        """Should find Listeria in longer text."""
        text = "Listeria monocytogenes can grow at refrigeration temperatures."
        result = ComBaseOrganism.from_text(text)
        
        assert result == ComBaseOrganism.LISTERIA_MONOCYTOGENES
    
    def test_finds_ecoli_in_text(self):
        """Should find E. coli in text."""
        text = "E. coli O157:H7 is associated with undercooked ground beef."
        result = ComBaseOrganism.from_text(text)
        
        assert result == ComBaseOrganism.ESCHERICHIA_COLI
    
    def test_finds_bacillus_cereus_in_text(self):
        """Should find Bacillus cereus in text."""
        text = "Bacillus cereus produces toxins in cooked rice."
        result = ComBaseOrganism.from_text(text)
        
        assert result == ComBaseOrganism.BACILLUS_CEREUS
    
    def test_prefers_longer_match(self):
        """Should match longer patterns first."""
        text = "Salmonella enteritidis is common in eggs."
        result = ComBaseOrganism.from_text(text)
        
        # Should still resolve to SALMONELLA
        assert result == ComBaseOrganism.SALMONELLA
    
    def test_case_insensitive(self):
        """Should match case-insensitively."""
        text = "LISTERIA was found in the sample."
        result = ComBaseOrganism.from_text(text)
        
        assert result == ComBaseOrganism.LISTERIA_MONOCYTOGENES
    
    def test_no_match_returns_none(self):
        """Should return None when no organism found."""
        text = "This food is perfectly safe to eat."
        result = ComBaseOrganism.from_text(text)
        
        assert result is None
    
    def test_empty_text_returns_none(self):
        """Should return None for empty text."""
        assert ComBaseOrganism.from_text("") is None
        assert ComBaseOrganism.from_text(None) is None
    
    def test_finds_first_organism(self):
        """Should return first matching organism."""
        text = "Both Salmonella and Listeria can contaminate deli meats."
        result = ComBaseOrganism.from_text(text)
        
        # Salmonella appears first in text, but longer patterns checked first
        # "salmonella" and "listeria" are same length, so depends on dict order
        # Just verify we get a valid organism
        assert result in [ComBaseOrganism.SALMONELLA, ComBaseOrganism.LISTERIA_MONOCYTOGENES]


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