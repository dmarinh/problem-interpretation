"""
Unit tests for ComBase calculator.
"""

import math
from pathlib import Path

import pytest

from app.engines.combase.calculator import ComBaseCalculator
from app.engines.combase.models import ComBaseModelRegistry
from app.models.enums import ComBaseOrganism, Factor4Type, ModelType


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


class TestPolynomialCharacterization:
    """
    Characterization pins for the core polynomial math (_calculate_ln_mu /
    _calculate_mu / _calculate_bw / calculate_log_increase), added ahead of
    the engine-relocation refactor (see specs/lessons.md).

    These are CHARACTERIZATION tests, not correctness tests: they assert
    what the current code outputs today, not that the output is
    scientifically right. Their job is to fail if the refactor changes
    behaviour (a transposed coefficient, a swapped term, a sign flip),
    not to validate the ComBase model itself.

    Every expected number below is computed independently of
    ComBaseCalculator -- by hand-expanding the documented polynomial
    (see calculator.py's module docstring) against the coefficients as
    they appear in data/combase_models.csv, not by calling the code under
    test. All three rows have at least one nonzero coefficient on a T*pH,
    T*bw, or pH*bw cross term or a squared term, so transposing/swapping
    any two coefficients changes the expected number -- these pins have
    teeth, verified by deliberately perturbing a coefficient and
    confirming the test fails (see PR/commit description).

    Uses the module-level `registry` fixture defined above.
    """

    def test_listeria_growth_pinned(self, registry):
        """
        Listeria monocytogenes GROWTH (lm, ModelID=1). CSV coefficients
        (b0..b14): -18.851; 0.2409; 4.2628; 6.36771; 0; 0; 0; -0.00332;
        -0.31377; -43.12409; 0;0;0;0;0

        Inputs: T=25.0, pH=7.0, aw=0.99 -> bw = sqrt(1-0.99) = 0.1

        Independent derivation (growth/non-thermal bw branch, F4=0):
            ln_mu = b0 + b1*T + b2*pH + b3*bw + b7*T^2 + b8*pH^2 + b9*bw^2
                  = -18.851 + 0.2409*25 + 4.2628*7.0 + 6.36771*0.1
                    + (-0.00332)*25^2 + (-0.31377)*7.0^2 + (-43.12409)*0.1^2
                  = -18.851 + 6.0225 + 29.8396 + 0.636771
                    - 2.075 - 15.37473 - 0.4312409
                  = -0.2330999
            mu_max = exp(ln_mu) = 0.7920744413350427   (GROWTH -> exp, not -exp)
            doubling_time = ln(2) / mu_max = 0.8751035816679612
            log_increase(4h) = mu_max * 4 / ln(10) = 1.3759742365136398
        """
        if len(registry) == 0:
            pytest.skip("combase_models.csv not found")

        model = registry.get_model(
            organism=ComBaseOrganism.LISTERIA_MONOCYTOGENES,
            model_type=ModelType.GROWTH,
            factor4_type=Factor4Type.NONE,
        )
        if model is None:
            pytest.skip("Listeria growth model not found")

        calc = ComBaseCalculator(model)
        result = calc.calculate(temperature=25.0, ph=7.0, aw=0.99)

        assert result.mu_max == pytest.approx(0.7920744413350427, rel=1e-9)
        assert result.doubling_time_hours == pytest.approx(0.8751035816679612, rel=1e-9)

        log_increase = calc.calculate_log_increase(
            mu_max=result.mu_max, duration_hours=4.0
        )
        assert log_increase == pytest.approx(1.3759742365136398, rel=1e-9)

    def test_salmonella_thermal_inactivation_pinned(self, registry):
        """
        Salmonella THERMAL_INACTIVATION (ss, ModelID=2). CSV coefficients
        (b0..b14): 8.1218; 0; -5.94372; 0; 0.0900627; 0;0;0;0;0;0;0;0;0;0

        Inputs: T=60.0, pH=7.0, aw=0.997 (the model's own DefaultTemp/
        DefaultPH/DefaultAw) -> bw = aw = 0.997 (thermal-inactivation
        branch of _calculate_bw uses aw directly, not sqrt(1-aw)).

        Independent derivation (F4=0):
            ln_mu = b0 + b2*pH + b4*T*pH
                  = 8.1218 + (-5.94372)*7.0 + 0.0900627*60*7.0
                  = 8.1218 - 41.60604 + 37.826334
                  = 4.342094
            mu_max = -exp(ln_mu) = -76.86833321810728   (inactivation -> -exp)
            doubling_time = None (not applicable to non-growth models)
            log_increase(10min = 1/6 h) = mu_max * duration   (mu<=0: no /ln(10))
                                         = -76.86833321810728 / 6
                                         = -12.811388869684546
        """
        if len(registry) == 0:
            pytest.skip("combase_models.csv not found")

        model = registry.get_model(
            organism=ComBaseOrganism.SALMONELLA,
            model_type=ModelType.THERMAL_INACTIVATION,
            factor4_type=Factor4Type.NONE,
        )
        if model is None:
            pytest.skip("Salmonella thermal model not found")

        calc = ComBaseCalculator(model)
        result = calc.calculate(temperature=60.0, ph=7.0, aw=0.997)

        assert result.mu_max == pytest.approx(-76.86833321810728, rel=1e-9)
        assert result.doubling_time_hours is None

        log_increase = calc.calculate_log_increase(
            mu_max=result.mu_max, duration_hours=10.0 / 60.0
        )
        assert log_increase == pytest.approx(-12.811388869684546, rel=1e-9)

    def test_salmonella_non_thermal_survival_pinned(self, registry):
        """
        Salmonella NON_THERMAL_SURVIVAL (ss, ModelID=3). CSV coefficients
        (b0..b14): 16.67318; 0; -7.46417; 0; 0; 0.296892; 3.03002; 0;
        0.5249836; -22.921838; 0;0;0;0;0

        Inputs: T=8.0, pH=4.5, aw=0.894 (the model's own DefaultTemp/
        DefaultPH/DefaultAw) -> bw = sqrt(1-0.894) = 0.3255764119219941
        (non-thermal-survival branch of _calculate_bw uses sqrt(1-aw),
        same as GROWTH -- only THERMAL_INACTIVATION differs).

        Independent derivation (F4=0):
            ln_mu = b0 + b2*pH + b5*T*bw + b6*pH*bw + b8*pH^2 + b9*bw^2
                  = 16.67318 + (-7.46417)*4.5 + 0.296892*8*0.3255764119...
                    + 3.03002*4.5*0.3255764119... + 0.5249836*4.5^2
                    + (-22.921838)*0.3255764119...^2
                  = 16.67318 - 33.588765 + 0.773198 + 4.438978
                    + 10.6309929 - 2.429712
                  = -3.5018299928597845
            mu_max = -exp(ln_mu) = -0.030142172959056   (survival -> -exp)
            doubling_time = None
            log_increase(24h) = mu_max * 24   (mu<=0: no /ln(10))
                               = -0.723412151017344
        """
        if len(registry) == 0:
            pytest.skip("combase_models.csv not found")

        model = registry.get_model(
            organism=ComBaseOrganism.SALMONELLA,
            model_type=ModelType.NON_THERMAL_SURVIVAL,
            factor4_type=Factor4Type.NONE,
        )
        if model is None:
            pytest.skip("Salmonella non-thermal survival model not found")

        calc = ComBaseCalculator(model)
        result = calc.calculate(temperature=8.0, ph=4.5, aw=0.894)

        assert result.mu_max == pytest.approx(-0.030142172959056, rel=1e-9)
        assert result.doubling_time_hours is None

        log_increase = calc.calculate_log_increase(
            mu_max=result.mu_max, duration_hours=24.0
        )
        assert log_increase == pytest.approx(-0.723412151017344, rel=1e-9)
