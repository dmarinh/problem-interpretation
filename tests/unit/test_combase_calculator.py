"""
Unit tests for ComBase calculator.
"""

import pytest
import math
from pathlib import Path

from app.engines.combase.calculator import ComBaseCalculator, CalculationResult
from app.engines.combase.models import ComBaseModelRegistry
from app.models.enums import ModelType, ComBaseOrganism, Factor4Type


@pytest.fixture
def registry() -> ComBaseModelRegistry:
    """Load model registry."""
    reg = ComBaseModelRegistry()
    csv_path = Path("data/combase_models.csv")
    if csv_path.exists():
        reg.load_from_csv(csv_path)
    return reg


@pytest.fixture
def listeria_growth_model(registry):
    """Get Listeria growth model."""
    if len(registry) == 0:
        pytest.skip("combase_models.csv not found")
    
    model = registry.get_model(
        organism=ComBaseOrganism.LISTERIA_MONOCYTOGENES,
        model_type=ModelType.GROWTH,
        factor4_type=Factor4Type.NONE,
    )
    
    if model is None:
        pytest.skip("Listeria growth model not found")
    
    return model


@pytest.fixture
def salmonella_thermal_model(registry):
    """Get Salmonella thermal inactivation model."""
    if len(registry) == 0:
        pytest.skip("combase_models.csv not found")
    
    model = registry.get_model(
        organism=ComBaseOrganism.SALMONELLA,
        model_type=ModelType.THERMAL_INACTIVATION,
        factor4_type=Factor4Type.NONE,
    )
    
    if model is None:
        pytest.skip("Salmonella thermal model not found")
    
    return model


class TestComBaseCalculator:
    """Tests for ComBaseCalculator."""
    
    def test_growth_calculation(self, listeria_growth_model):
        """Should calculate positive growth rate for growth model."""
        calc = ComBaseCalculator(listeria_growth_model)
        
        result = calc.calculate(
            temperature=25.0,
            ph=7.0,
            aw=0.99,
        )
        
        assert result.mu_max > 0
        assert result.doubling_time_hours is not None
        assert result.doubling_time_hours > 0
        assert result.model_type == ModelType.GROWTH
    
    def test_thermal_inactivation_calculation(self, salmonella_thermal_model):
        """Should calculate negative mu for inactivation model."""
        calc = ComBaseCalculator(salmonella_thermal_model)
        
        result = calc.calculate(
            temperature=60.0,
            ph=7.0,
            aw=0.99,
        )
        
        assert result.mu_max < 0  # Negative for inactivation
        assert result.doubling_time_hours is None  # Not applicable
        assert result.model_type == ModelType.THERMAL_INACTIVATION
    
    def test_clamping_out_of_range(self, listeria_growth_model):
        """Should clamp values outside valid range."""
        calc = ComBaseCalculator(listeria_growth_model)
        
        # Temperature way outside range
        result = calc.calculate(
            temperature=100.0,  # Way too high
            ph=7.0,
            aw=0.99,
            clamp_to_range=True,
        )
        
        assert result.within_range is False
        assert len(result.warnings) > 0
        assert result.temperature == listeria_growth_model.constraints.temp_max
    
    def test_no_clamping_when_disabled(self, listeria_growth_model):
        """Should not clamp when disabled."""
        calc = ComBaseCalculator(listeria_growth_model)
        
        result = calc.calculate(
            temperature=100.0,
            ph=7.0,
            aw=0.99,
            clamp_to_range=False,
        )
        
        assert result.temperature == 100.0  # Not clamped
        assert result.within_range is False
        assert len(result.warnings) != 0
    
    def test_bw_calculation_growth(self, listeria_growth_model):
        """Growth model should use bw = sqrt(1 - aw)."""
        calc = ComBaseCalculator(listeria_growth_model)
        
        result = calc.calculate(
            temperature=25.0,
            ph=7.0,
            aw=0.99,
        )
        
        expected_bw = math.sqrt(1 - 0.99)
        assert abs(result.bw - expected_bw) < 0.0001
    
    def test_bw_calculation_thermal(self, salmonella_thermal_model):
        """Thermal inactivation model should use bw = aw."""
        calc = ComBaseCalculator(salmonella_thermal_model)
        
        result = calc.calculate(
            temperature=60.0,
            ph=7.0,
            aw=0.99,
        )
        
        assert result.bw == 0.99  # bw = aw for thermal
    
    def test_log_increase_calculation(self, listeria_growth_model):
        """Should calculate log increase correctly."""
        calc = ComBaseCalculator(listeria_growth_model)
        
        result = calc.calculate(
            temperature=25.0,
            ph=7.0,
            aw=0.99,
        )
        
        # 4 hours of growth
        log_increase = calc.calculate_log_increase(
            mu_max=result.mu_max,
            duration_hours=4.0,
        )
        
        # log increase = mu * t / ln(10)
        expected = result.mu_max * 4.0 / math.log(10)
        assert abs(log_increase - expected) < 0.0001
    
    
    def test_doubling_time_relationship(self, listeria_growth_model):
        """Doubling time should be ln(2) / mu."""
        calc = ComBaseCalculator(listeria_growth_model)
        
        result = calc.calculate(
            temperature=25.0,
            ph=7.0,
            aw=0.99,
        )
        
        expected_dt = math.log(2) / result.mu_max
        assert abs(result.doubling_time_hours - expected_dt) < 0.0001


class TestCalculatorEdgeCases:
    """Edge case tests for calculator."""
    
    def test_low_temperature_growth(self, listeria_growth_model):
        """Should handle low temperature (slow growth)."""
        calc = ComBaseCalculator(listeria_growth_model)
        
        result = calc.calculate(
            temperature=4.0,  # Refrigeration
            ph=7.0,
            aw=0.99,
        )
        
        # Listeria can grow at refrigeration temps
        # mu should be positive but small
        assert result.mu_max > 0
        assert result.doubling_time_hours > 10  # Slow growth
    
    def test_extreme_aw(self, listeria_growth_model):
        """Should handle edge case water activity."""
        calc = ComBaseCalculator(listeria_growth_model)
        
        # Very high aw
        result = calc.calculate(
            temperature=25.0,
            ph=7.0,
            aw=1.0,
        )
        
        # bw = sqrt(1 - 1.0) = 0
        assert result.bw == 0.0
        assert result.mu_max > 0  # Should still calculate