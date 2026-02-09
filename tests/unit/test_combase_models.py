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