"""
Unit Tests for Model-Type-Aware Conservative Bias

These tests verify that the conservative bias corrections reverse direction
based on the model type:

- GROWTH models: bias toward MORE growth (upper bounds, +duration, +temperature)
- THERMAL_INACTIVATION models: bias toward LESS kill (lower bounds, -duration, -temperature)
- NON_THERMAL_SURVIVAL models: same as growth (more survival = worse)

The key insight: "conservative" always means assuming the WORSE food safety
outcome. For growth, that's more growth. For inactivation, that's less kill.

Test Naming Convention:
    test_<component>_<scenario>_<model_type>_<expected_behavior>
    
Example:
    test_duration_margin_inferred_inactivation_reduces_duration
    → Tests that inferred durations are reduced for inactivation models
"""

import pytest
from unittest.mock import MagicMock, AsyncMock

from app.models.enums import (
    ModelType,
    ComBaseOrganism,
    BiasType,
    Factor4Type,
)
from app.models.metadata import ValueSource, ValueProvenance
from app.models.extraction import (
    ExtractedScenario,
    ExtractedTemperature,
    ExtractedDuration,
    ExtractedEnvironmentalConditions,
)
from app.services.standardization.standardization_service import (
    StandardizationService,
    StandardizationResult,
)
from app.services.grounding.grounding_service import (
    GroundingService,
    GroundedValues,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def standardization_service():
    """Create a StandardizationService without registry for testing."""
    return StandardizationService(model_registry=None)


@pytest.fixture
def grounding_service():
    """Create a GroundingService without RAG for testing."""
    mock_retrieval = MagicMock()
    mock_retrieval.query_food_properties.return_value = MagicMock(
        has_confident_result=False,
        results=[],
    )
    mock_retrieval.query_pathogen_hazards.return_value = MagicMock(
        has_confident_result=False,
        results=[],
    )
    return GroundingService(
        retrieval_service=mock_retrieval,
        use_llm_extraction=False,
    )


@pytest.fixture
def grounded_with_inferred_duration():
    """Create grounded values with an inferred duration."""
    grounded = GroundedValues()
    grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT, 0.90)
    grounded.set("temperature_celsius", 68.0, ValueSource.USER_EXPLICIT, 0.90)
    grounded.set(
        "duration_minutes",
        8.0,
        ValueSource.USER_INFERRED,  # This triggers duration margin
        0.75,
        original_text="roughly 8 minutes",
    )
    return grounded


@pytest.fixture
def grounded_with_low_confidence_temp():
    """Create grounded values with low-confidence temperature."""
    grounded = GroundedValues()
    grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT, 0.90)
    grounded.set(
        "temperature_celsius",
        68.0,
        ValueSource.USER_INFERRED,
        0.40,  # Below LOW_CONFIDENCE_THRESHOLD (0.5)
        original_text="about 68°C",
    )
    grounded.set("duration_minutes", 10.0, ValueSource.USER_EXPLICIT, 0.90)
    return grounded


# =============================================================================
# STANDARDIZATION SERVICE: DURATION MARGIN TESTS
# =============================================================================

class TestDurationMarginModelTypeAware:
    """Test that duration margin reverses direction based on model type."""
    
    def test_duration_margin_growth_adds_20_percent(
        self,
        standardization_service,
        grounded_with_inferred_duration,
    ):
        """For growth models, inferred duration should increase by 20%."""
        result = standardization_service.standardize(
            grounded_with_inferred_duration,
            model_type=ModelType.GROWTH,
        )
        
        assert result.payload is not None
        # 8.0 * 1.2 = 9.6
        assert result.payload.time_temperature_profile.total_duration_minutes == pytest.approx(9.6)
        
        # Verify bias correction was applied
        duration_corrections = [
            bc for bc in result.bias_corrections
            if bc.field_name == "duration_minutes" and bc.bias_type == BiasType.OPTIMISTIC_DURATION
        ]
        assert len(duration_corrections) == 1
        assert duration_corrections[0].original_value == 8.0
        assert duration_corrections[0].corrected_value == pytest.approx(9.6)
        assert "+20%" in duration_corrections[0].correction_reason
    
    def test_duration_margin_inactivation_reduces_20_percent(
        self,
        standardization_service,
        grounded_with_inferred_duration,
    ):
        """For inactivation models, inferred duration should decrease by 20%."""
        result = standardization_service.standardize(
            grounded_with_inferred_duration,
            model_type=ModelType.THERMAL_INACTIVATION,
        )
        
        assert result.payload is not None
        # 8.0 * 0.8 = 6.4
        assert result.payload.time_temperature_profile.total_duration_minutes == pytest.approx(6.4)
        
        # Verify bias correction was applied
        duration_corrections = [
            bc for bc in result.bias_corrections
            if bc.field_name == "duration_minutes" and bc.bias_type == BiasType.OPTIMISTIC_DURATION
        ]
        assert len(duration_corrections) == 1
        assert duration_corrections[0].original_value == 8.0
        assert duration_corrections[0].corrected_value == pytest.approx(6.4)
        assert "-20%" in duration_corrections[0].correction_reason
    
    def test_duration_margin_survival_same_as_growth(
        self,
        standardization_service,
        grounded_with_inferred_duration,
    ):
        """For survival models, duration margin should be same as growth (+20%)."""
        result = standardization_service.standardize(
            grounded_with_inferred_duration,
            model_type=ModelType.NON_THERMAL_SURVIVAL,
        )
        
        assert result.payload is not None
        # 8.0 * 1.2 = 9.6 (same as growth)
        assert result.payload.time_temperature_profile.total_duration_minutes == pytest.approx(9.6)
    
    def test_explicit_duration_not_adjusted(
        self,
        standardization_service,
    ):
        """Explicit durations should not have margin applied."""
        grounded = GroundedValues()
        grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT, 0.90)
        grounded.set("temperature_celsius", 68.0, ValueSource.USER_EXPLICIT, 0.90)
        grounded.set(
            "duration_minutes",
            8.0,
            ValueSource.USER_EXPLICIT,  # Not USER_INFERRED
            0.90,
        )
        
        # Test for both model types
        for model_type in [ModelType.GROWTH, ModelType.THERMAL_INACTIVATION]:
            result = standardization_service.standardize(grounded, model_type=model_type)
            assert result.payload.time_temperature_profile.total_duration_minutes == 8.0
            
            # No duration bias correction should be applied
            duration_corrections = [
                bc for bc in result.bias_corrections
                if bc.field_name == "duration_minutes" and bc.bias_type == BiasType.OPTIMISTIC_DURATION
            ]
            assert len(duration_corrections) == 0


# =============================================================================
# STANDARDIZATION SERVICE: TEMPERATURE BUMP TESTS
# =============================================================================

class TestTemperatureBumpModelTypeAware:
    """Test that low-confidence temperature bumps reverse based on model type."""
    
    def test_temperature_bump_growth_adds_5_degrees(
        self,
        standardization_service,
        grounded_with_low_confidence_temp,
    ):
        """For growth models, low-confidence temperature should increase by 5°C."""
        result = standardization_service.standardize(
            grounded_with_low_confidence_temp,
            model_type=ModelType.GROWTH,
        )
        
        assert result.payload is not None
        # 68.0 + 5.0 = 73.0
        assert result.payload.parameters.temperature_celsius == pytest.approx(73.0)
        
        # Verify bias correction
        temp_corrections = [
            bc for bc in result.bias_corrections
            if bc.field_name == "temperature_celsius" and bc.bias_type == BiasType.OPTIMISTIC_TEMPERATURE
        ]
        assert len(temp_corrections) == 1
        assert temp_corrections[0].original_value == 68.0
        assert temp_corrections[0].corrected_value == pytest.approx(73.0)
        assert "warmer" in temp_corrections[0].correction_reason
        assert "more growth" in temp_corrections[0].correction_reason
    
    def test_temperature_bump_inactivation_subtracts_5_degrees(
        self,
        standardization_service,
        grounded_with_low_confidence_temp,
    ):
        """For inactivation models, low-confidence temperature should decrease by 5°C."""
        result = standardization_service.standardize(
            grounded_with_low_confidence_temp,
            model_type=ModelType.THERMAL_INACTIVATION,
        )
        
        assert result.payload is not None
        # 68.0 - 5.0 = 63.0
        assert result.payload.parameters.temperature_celsius == pytest.approx(63.0)
        
        # Verify bias correction
        temp_corrections = [
            bc for bc in result.bias_corrections
            if bc.field_name == "temperature_celsius" and bc.bias_type == BiasType.OPTIMISTIC_TEMPERATURE
        ]
        assert len(temp_corrections) == 1
        assert temp_corrections[0].original_value == 68.0
        assert temp_corrections[0].corrected_value == pytest.approx(63.0)
        assert "cooler" in temp_corrections[0].correction_reason
        assert "less pathogen kill" in temp_corrections[0].correction_reason
    
    def test_high_confidence_temp_not_bumped(
        self,
        standardization_service,
    ):
        """Temperature with confidence above threshold should not be bumped."""
        grounded = GroundedValues()
        grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT, 0.90)
        grounded.set(
            "temperature_celsius",
            68.0,
            ValueSource.USER_INFERRED,
            0.80,  # Above LOW_CONFIDENCE_THRESHOLD (0.5)
        )
        grounded.set("duration_minutes", 10.0, ValueSource.USER_EXPLICIT, 0.90)
        
        for model_type in [ModelType.GROWTH, ModelType.THERMAL_INACTIVATION]:
            result = standardization_service.standardize(grounded, model_type=model_type)
            assert result.payload.parameters.temperature_celsius == 68.0
            
            temp_corrections = [
                bc for bc in result.bias_corrections
                if bc.field_name == "temperature_celsius" and bc.bias_type == BiasType.OPTIMISTIC_TEMPERATURE
            ]
            assert len(temp_corrections) == 0


# =============================================================================
# GROUNDING SERVICE: RANGE BOUND SELECTION TESTS
# =============================================================================

class TestRangeBoundSelectionModelTypeAware:
    """Test that range bound selection reverses based on model type."""
    
    @pytest.mark.asyncio
    async def test_temperature_range_growth_uses_upper_bound(
        self,
        grounding_service,
    ):
        """For growth models, temperature range should use upper bound."""
        scenario = ExtractedScenario(
            original_text="chicken left out between 20 and 30°C",
            food_description="chicken",
            single_step_temperature=ExtractedTemperature(
                is_range=True,
                range_min_celsius=20.0,
                range_max_celsius=30.0,
            ),
            single_step_duration=ExtractedDuration(value_minutes=60),
        )
        
        grounded = await grounding_service.ground_scenario(
            scenario,
            model_type=ModelType.GROWTH,
        )
        
        assert grounded.get("temperature_celsius") == 30.0  # Upper bound
        assert "UPPER" in grounded.provenance["temperature_celsius"].transformation_applied
        assert "more pathogen growth" in grounded.provenance["temperature_celsius"].transformation_applied
    
    @pytest.mark.asyncio
    async def test_temperature_range_inactivation_uses_lower_bound(
        self,
        grounding_service,
    ):
        """For inactivation models, temperature range should use lower bound."""
        scenario = ExtractedScenario(
            original_text="chicken cooked between 65 and 75°C",
            food_description="chicken",
            single_step_temperature=ExtractedTemperature(
                is_range=True,
                range_min_celsius=65.0,
                range_max_celsius=75.0,
            ),
            single_step_duration=ExtractedDuration(value_minutes=10),
        )
        
        grounded = await grounding_service.ground_scenario(
            scenario,
            model_type=ModelType.THERMAL_INACTIVATION,
        )
        
        assert grounded.get("temperature_celsius") == 65.0  # Lower bound
        assert "LOWER" in grounded.provenance["temperature_celsius"].transformation_applied
        assert "less pathogen kill" in grounded.provenance["temperature_celsius"].transformation_applied
    
    @pytest.mark.asyncio
    async def test_duration_range_growth_uses_upper_bound(
        self,
        grounding_service,
    ):
        """For growth models, duration range should use upper bound."""
        scenario = ExtractedScenario(
            original_text="chicken left out for 2 to 4 hours",
            food_description="chicken",
            single_step_temperature=ExtractedTemperature(value_celsius=25.0),
            single_step_duration=ExtractedDuration(
                is_range=True,
                range_min_minutes=120.0,
                range_max_minutes=240.0,
            ),
        )
        
        grounded = await grounding_service.ground_scenario(
            scenario,
            model_type=ModelType.GROWTH,
        )
        
        assert grounded.get("duration_minutes") == 240.0  # Upper bound
    
    @pytest.mark.asyncio
    async def test_duration_range_inactivation_uses_lower_bound(
        self,
        grounding_service,
    ):
        """For inactivation models, duration range should use lower bound."""
        scenario = ExtractedScenario(
            original_text="chicken cooked for 5 to 10 minutes",
            food_description="chicken",
            single_step_temperature=ExtractedTemperature(value_celsius=70.0),
            single_step_duration=ExtractedDuration(
                is_range=True,
                range_min_minutes=5.0,
                range_max_minutes=10.0,
            ),
        )
        
        grounded = await grounding_service.ground_scenario(
            scenario,
            model_type=ModelType.THERMAL_INACTIVATION,
        )
        
        assert grounded.get("duration_minutes") == 5.0  # Lower bound


# =============================================================================
# CHICKEN NUGGETS SCENARIO (Query C2)
# =============================================================================

class TestChickenNuggetsScenario:
    """
    Test the specific scenario from the critique:
    
    Query C2: chicken nuggets reached 68°C instead of target 74°C, held for 8 min.
    
    Old (buggy) behavior:
        - Duration: 8 min × 1.2 = 9.6 min (MORE kill predicted)
        - Temperature bump: 68°C + 5°C = 73°C (MORE kill predicted)
        → System would say "probably safe" - WRONG!
    
    New (correct) behavior:
        - Duration: 8 min × 0.8 = 6.4 min (LESS kill predicted)
        - Temperature bump: 68°C - 5°C = 63°C (LESS kill predicted)
        → System says "may not be safe" - CORRECT!
    """
    
    def test_chicken_nuggets_inactivation_conservative_bias(
        self,
        standardization_service,
    ):
        """
        Verify that chicken nuggets at 68°C for ~8 min gets conservative treatment.
        
        This is the critical bug fix test. The old behavior would make this
        scenario look SAFER than it actually is, potentially approving
        undercooked chicken.
        """
        grounded = GroundedValues()
        grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT, 0.90)
        grounded.set(
            "temperature_celsius",
            68.0,
            ValueSource.USER_INFERRED,
            0.40,  # Low confidence ("about 68°C")
            original_text="about 68°C",
        )
        grounded.set(
            "duration_minutes",
            8.0,
            ValueSource.USER_INFERRED,  # Inferred ("roughly 8 minutes")
            0.75,
            original_text="roughly 8 minutes",
        )
        
        result = standardization_service.standardize(
            grounded,
            model_type=ModelType.THERMAL_INACTIVATION,
        )
        
        assert result.payload is not None
        
        # Temperature should be LOWER (68 - 5 = 63°C)
        assert result.payload.parameters.temperature_celsius == pytest.approx(63.0)
        
        # Duration should be SHORTER (8 × 0.8 = 6.4 min)
        assert result.payload.time_temperature_profile.total_duration_minutes == pytest.approx(6.4)
        
        # Verify both corrections were applied
        assert len(result.bias_corrections) >= 2
        
        # This combination (lower temp + shorter time) predicts LESS Salmonella kill
        # which is the correct conservative behavior for thermal inactivation
    
    def test_chicken_nuggets_growth_would_be_opposite(
        self,
        standardization_service,
    ):
        """
        Contrast: same scenario treated as growth would get opposite bias.
        
        This test verifies the model type actually changes the behavior.
        """
        grounded = GroundedValues()
        grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT, 0.90)
        grounded.set(
            "temperature_celsius",
            68.0,
            ValueSource.USER_INFERRED,
            0.40,
        )
        grounded.set(
            "duration_minutes",
            8.0,
            ValueSource.USER_INFERRED,
            0.75,
        )
        
        result = standardization_service.standardize(
            grounded,
            model_type=ModelType.GROWTH,
        )
        
        assert result.payload is not None
        
        # Temperature should be HIGHER (68 + 5 = 73°C)
        assert result.payload.parameters.temperature_celsius == pytest.approx(73.0)
        
        # Duration should be LONGER (8 × 1.2 = 9.6 min)
        assert result.payload.time_temperature_profile.total_duration_minutes == pytest.approx(9.6)


# =============================================================================
# NON-THERMAL SURVIVAL MODEL TESTS
# =============================================================================

class TestNonThermalSurvivalModel:
    """
    Test that NON_THERMAL_SURVIVAL uses the same bias direction as GROWTH.
    
    Rationale:
    - Non-thermal survival models predict how pathogens survive treatments
      like acid exposure, drying, or preservatives
    - Conservative = predict MORE survival (worse outcome)
    - This is similar to growth: more survival = more risk
    
    Examples:
    - Acid treatment: higher pH = more survival (worse)
    - Drying: higher water activity = more survival (worse)
    - Preservative exposure: shorter time = more survival (worse)
    """
    
    def test_survival_duration_margin_same_as_growth(
        self,
        standardization_service,
        grounded_with_inferred_duration,
    ):
        """Survival model should increase duration like growth (+20%)."""
        result = standardization_service.standardize(
            grounded_with_inferred_duration,
            model_type=ModelType.NON_THERMAL_SURVIVAL,
        )
        
        # 8.0 * 1.2 = 9.6 (same as growth)
        assert result.payload.time_temperature_profile.total_duration_minutes == pytest.approx(9.6)
    
    def test_survival_temp_bump_same_as_growth(
        self,
        standardization_service,
        grounded_with_low_confidence_temp,
    ):
        """Survival model should increase temperature like growth (+5°C)."""
        result = standardization_service.standardize(
            grounded_with_low_confidence_temp,
            model_type=ModelType.NON_THERMAL_SURVIVAL,
        )
        
        # 68.0 + 5.0 = 73.0 (same as growth)
        assert result.payload.parameters.temperature_celsius == pytest.approx(73.0)
    
    @pytest.mark.asyncio
    async def test_survival_range_uses_upper_bound(
        self,
        grounding_service,
    ):
        """Survival model should use upper bound of ranges like growth."""
        scenario = ExtractedScenario(
            original_text="dried fruit with aw between 0.65 and 0.75",
            food_description="dried fruit",
            single_step_temperature=ExtractedTemperature(value_celsius=25.0),
            single_step_duration=ExtractedDuration(
                is_range=True,
                range_min_minutes=60.0,
                range_max_minutes=120.0,
            ),
        )
        
        grounded = await grounding_service.ground_scenario(
            scenario,
            model_type=ModelType.NON_THERMAL_SURVIVAL,
        )
        
        # Should use upper bound (more survival time = worse)
        assert grounded.get("duration_minutes") == 120.0


# =============================================================================
# DEFAULT VALUE TESTS
# =============================================================================

class TestDefaultValuesModelTypeAware:
    """Test that default values are documented with model-type-aware reasons."""
    
    def test_missing_temperature_growth_uses_abuse_temp(
        self,
        standardization_service,
    ):
        """Growth model should default to abuse temperature (e.g., 25°C)."""
        grounded = GroundedValues()
        grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT, 0.90)
        # No temperature
        grounded.set("duration_minutes", 60.0, ValueSource.USER_EXPLICIT, 0.90)
        
        result = standardization_service.standardize(
            grounded,
            model_type=ModelType.GROWTH,
        )
        
        assert result.payload is not None
        assert "temperature" in str(result.defaults_applied)
        
        # Check reason mentions growth
        temp_imputed = [
            bc for bc in result.bias_corrections
            if bc.field_name == "temperature_celsius" and bc.bias_type == BiasType.MISSING_VALUE_IMPUTED
        ]
        assert len(temp_imputed) == 1
        assert "growth" in temp_imputed[0].correction_reason.lower()
    
    def test_missing_temperature_inactivation_uses_conservative_cooking_temp(
        self,
        standardization_service,
    ):
        """Inactivation model should default to conservative cooking temperature."""
        grounded = GroundedValues()
        grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT, 0.90)
        # No temperature
        grounded.set("duration_minutes", 10.0, ValueSource.USER_EXPLICIT, 0.90)
        
        result = standardization_service.standardize(
            grounded,
            model_type=ModelType.THERMAL_INACTIVATION,
        )
        
        assert result.payload is not None
        
        # Default should be a conservative cooking temp (e.g., 60°C)
        # that may not achieve full pasteurization
        assert result.payload.parameters.temperature_celsius == 60.0
        
        # Check reason mentions cooking/pasteurization
        temp_imputed = [
            bc for bc in result.bias_corrections
            if bc.field_name == "temperature_celsius" and bc.bias_type == BiasType.MISSING_VALUE_IMPUTED
        ]
        assert len(temp_imputed) == 1
        assert "pasteurization" in temp_imputed[0].correction_reason.lower() or \
               "cooking" in temp_imputed[0].correction_reason.lower()


# =============================================================================
# HELPER METHOD TESTS
# =============================================================================

class TestHelperMethods:
    """Test the helper methods for determining bias direction."""
    
    def test_is_inactivation_model(self, standardization_service):
        """Test _is_inactivation_model helper."""
        assert standardization_service._is_inactivation_model(ModelType.THERMAL_INACTIVATION) is True
        assert standardization_service._is_inactivation_model(ModelType.GROWTH) is False
        assert standardization_service._is_inactivation_model(ModelType.NON_THERMAL_SURVIVAL) is False
    
    def test_get_range_bound_to_use(self, standardization_service):
        """Test _get_range_bound_to_use helper."""
        assert standardization_service._get_range_bound_to_use(ModelType.GROWTH) == "upper"
        assert standardization_service._get_range_bound_to_use(ModelType.THERMAL_INACTIVATION) == "lower"
        assert standardization_service._get_range_bound_to_use(ModelType.NON_THERMAL_SURVIVAL) == "upper"
    
    def test_get_duration_margin(self, standardization_service):
        """Test _get_duration_margin helper."""
        assert standardization_service._get_duration_margin(ModelType.GROWTH) == 1.2
        assert standardization_service._get_duration_margin(ModelType.THERMAL_INACTIVATION) == 0.8
        assert standardization_service._get_duration_margin(ModelType.NON_THERMAL_SURVIVAL) == 1.2
    
    def test_get_temperature_bump(self, standardization_service):
        """Test _get_temperature_bump helper."""
        assert standardization_service._get_temperature_bump(ModelType.GROWTH) == 5.0
        assert standardization_service._get_temperature_bump(ModelType.THERMAL_INACTIVATION) == -5.0
        assert standardization_service._get_temperature_bump(ModelType.NON_THERMAL_SURVIVAL) == 5.0


# =============================================================================
# INTEGRATION: COMBINED BIAS CORRECTIONS
# =============================================================================

class TestCombinedBiasCorrections:
    """Test scenarios with multiple bias corrections applied together."""
    
    def test_all_corrections_applied_growth(
        self,
        standardization_service,
    ):
        """Growth model with inferred temp and duration gets all +bias."""
        grounded = GroundedValues()
        grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT, 0.90)
        grounded.set(
            "temperature_celsius",
            25.0,
            ValueSource.USER_INFERRED,
            0.40,  # Low confidence → bump
        )
        grounded.set(
            "duration_minutes",
            60.0,
            ValueSource.USER_INFERRED,  # Inferred → margin
            0.75,
        )
        
        result = standardization_service.standardize(
            grounded,
            model_type=ModelType.GROWTH,
        )
        
        # Both corrections should push values UP
        assert result.payload.parameters.temperature_celsius == pytest.approx(30.0)  # 25 + 5
        assert result.payload.time_temperature_profile.total_duration_minutes == pytest.approx(72.0)  # 60 × 1.2
    
    def test_all_corrections_applied_inactivation(
        self,
        standardization_service,
    ):
        """Inactivation model with inferred temp and duration gets all -bias."""
        grounded = GroundedValues()
        grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT, 0.90)
        grounded.set(
            "temperature_celsius",
            70.0,
            ValueSource.USER_INFERRED,
            0.40,  # Low confidence → bump (down)
        )
        grounded.set(
            "duration_minutes",
            10.0,
            ValueSource.USER_INFERRED,  # Inferred → margin (down)
            0.75,
        )
        
        result = standardization_service.standardize(
            grounded,
            model_type=ModelType.THERMAL_INACTIVATION,
        )
        
        # Both corrections should push values DOWN
        assert result.payload.parameters.temperature_celsius == pytest.approx(65.0)  # 70 - 5
        assert result.payload.time_temperature_profile.total_duration_minutes == pytest.approx(8.0)  # 10 × 0.8


# =============================================================================
# EDGE CASES
# =============================================================================

class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_confidence_exactly_at_threshold(
        self,
        standardization_service,
    ):
        """Temperature at exactly LOW_CONFIDENCE_THRESHOLD should not be bumped."""
        grounded = GroundedValues()
        grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT, 0.90)
        grounded.set(
            "temperature_celsius",
            68.0,
            ValueSource.USER_INFERRED,
            0.50,  # Exactly at threshold (not below)
        )
        grounded.set("duration_minutes", 10.0, ValueSource.USER_EXPLICIT, 0.90)
        
        result = standardization_service.standardize(
            grounded,
            model_type=ModelType.THERMAL_INACTIVATION,
        )
        
        # Should NOT apply bump (threshold is < 0.5, not <=)
        assert result.payload.parameters.temperature_celsius == 68.0
    
    def test_zero_duration_not_negative_after_margin(
        self,
        standardization_service,
    ):
        """Very short durations should not become negative after -20% margin."""
        grounded = GroundedValues()
        grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT, 0.90)
        grounded.set("temperature_celsius", 70.0, ValueSource.USER_EXPLICIT, 0.90)
        grounded.set(
            "duration_minutes",
            1.0,  # Very short
            ValueSource.USER_INFERRED,
            0.75,
        )
        
        result = standardization_service.standardize(
            grounded,
            model_type=ModelType.THERMAL_INACTIVATION,
        )
        
        # 1.0 × 0.8 = 0.8 (still positive)
        assert result.payload.time_temperature_profile.total_duration_minutes == pytest.approx(0.8)
        assert result.payload.time_temperature_profile.total_duration_minutes > 0
