"""
Unit Tests for Model-Type-Aware Conservative Bias

Conservatism is committed in two places only:
  1. Default values — substituted when a field is absent.
  2. Range-bound selection — upper bound for growth/survival,
     lower bound for thermal inactivation.

Mapped values (USER_INFERRED) from rules.py are NOT multiplied or bumped on
top of the rule's chosen point.  The rule already picked the conservative end
of its stated range.

Test Naming Convention:
    test_<component>_<scenario>_<model_type>_<expected_behavior>
"""

import pytest
from unittest.mock import MagicMock

from app.models.enums import (
    ModelType,
    ComBaseOrganism,
)
from app.models.metadata import ValueSource
from app.models.extraction import (
    ExtractedScenario,
    ExtractedTemperature,
    ExtractedDuration,
)
from app.services.standardization.standardization_service import (
    StandardizationService,
)
from app.services.grounding.grounding_service import (
    GroundingService,
    GroundedValues,
)
from app.engines.combase.models import ComBaseModelConstraints


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
    """Grounded values with a USER_INFERRED duration (from a rules.py match)."""
    grounded = GroundedValues()
    grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT)
    grounded.set("temperature_celsius", 68.0, ValueSource.USER_EXPLICIT)
    grounded.set(
        "duration_minutes",
        60.0,  # "a while" → 60 min (rule's conservative point)
        ValueSource.USER_INFERRED,
        original_text="a while",
    )
    return grounded


# =============================================================================
# STANDARDIZATION SERVICE: USER_INFERRED DURATION PASSTHROUGH
# =============================================================================

class TestDurationPassthrough:
    """
    USER_INFERRED durations pass through standardization unchanged.

    The rule already chose the conservative point (e.g., "a while" → 60 min
    is the upper end of the 30–90 min range in the rule's notes).  Multiplying
    on top produces 72 min, which is past the stated worst case without
    justification.
    """

    def test_inferred_duration_growth_unchanged(
        self,
        standardization_service,
        grounded_with_inferred_duration,
    ):
        """Growth model: USER_INFERRED duration passes through at the rule's value."""
        result = standardization_service.standardize(
            grounded_with_inferred_duration,
            model_type=ModelType.GROWTH,
        )

        assert result.payload is not None
        assert result.payload.time_temperature_profile.total_duration_minutes == 60.0

    def test_inferred_duration_inactivation_unchanged(
        self,
        standardization_service,
        grounded_with_inferred_duration,
    ):
        """Inactivation model: USER_INFERRED duration passes through unchanged."""
        result = standardization_service.standardize(
            grounded_with_inferred_duration,
            model_type=ModelType.THERMAL_INACTIVATION,
        )

        assert result.payload is not None
        assert result.payload.time_temperature_profile.total_duration_minutes == 60.0

    def test_inferred_duration_survival_unchanged(
        self,
        standardization_service,
        grounded_with_inferred_duration,
    ):
        """Non-thermal survival model: USER_INFERRED duration passes through unchanged."""
        result = standardization_service.standardize(
            grounded_with_inferred_duration,
            model_type=ModelType.NON_THERMAL_SURVIVAL,
        )

        assert result.payload is not None
        assert result.payload.time_temperature_profile.total_duration_minutes == 60.0

    def test_explicit_duration_unchanged(self, standardization_service):
        """USER_EXPLICIT duration also passes through unchanged."""
        grounded = GroundedValues()
        grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT)
        grounded.set("temperature_celsius", 68.0, ValueSource.USER_EXPLICIT)
        grounded.set("duration_minutes", 8.0, ValueSource.USER_EXPLICIT)

        for model_type in [ModelType.GROWTH, ModelType.THERMAL_INACTIVATION]:
            result = standardization_service.standardize(grounded, model_type=model_type)
            assert result.payload.time_temperature_profile.total_duration_minutes == 8.0
            # No default should be imputed for duration — it was explicitly provided
            duration_defaults = [d for d in result.defaults_imputed if "duration" in d.field_name]
            assert duration_defaults == []


# =============================================================================
# GROUNDING SERVICE + STANDARDIZATION: RANGE BOUND SELECTION TESTS
# =============================================================================

class TestRangeBoundSelectionModelTypeAware:
    """
    Range-bound selection produces the correct conservative value.

    Grounding preserves both bounds (range_pending=True, value=lower bound).
    StandardizationService picks the correct bound based on model type.
    These are integration tests covering both phases together.
    """

    def _add_organism(self, grounded: GroundedValues) -> None:
        grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT)

    @pytest.mark.asyncio
    async def test_temperature_range_growth_uses_upper_bound(self, grounding_service):
        """For growth models, temperature range should resolve to upper bound."""
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

        grounded = await grounding_service.ground_scenario(scenario)
        assert grounded.get("temperature_celsius") == 20.0
        assert grounded.provenance["temperature_celsius"].range_pending is True

        self._add_organism(grounded)
        result = StandardizationService(model_registry=None).standardize(
            grounded, model_type=ModelType.GROWTH
        )

        assert result.payload.parameters.temperature_celsius == 30.0
        sel = grounded.provenance["temperature_celsius"].standardization
        assert sel is not None
        assert sel.direction == "upper"
        assert sel.before_value == [20.0, 30.0]
        assert sel.after_value == 30.0

    @pytest.mark.asyncio
    async def test_temperature_range_inactivation_uses_lower_bound(self, grounding_service):
        """For inactivation models, temperature range should resolve to lower bound."""
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

        grounded = await grounding_service.ground_scenario(scenario)
        self._add_organism(grounded)
        result = StandardizationService(model_registry=None).standardize(
            grounded, model_type=ModelType.THERMAL_INACTIVATION
        )

        assert result.payload.parameters.temperature_celsius == 65.0
        sel = grounded.provenance["temperature_celsius"].standardization
        assert sel.direction == "lower"
        assert sel.before_value == [65.0, 75.0]
        assert sel.after_value == 65.0

    @pytest.mark.asyncio
    async def test_duration_range_growth_uses_upper_bound(self, grounding_service):
        """For growth models, duration range should resolve to upper bound."""
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

        grounded = await grounding_service.ground_scenario(scenario)
        self._add_organism(grounded)
        result = StandardizationService(model_registry=None).standardize(
            grounded, model_type=ModelType.GROWTH
        )

        assert result.payload.time_temperature_profile.total_duration_minutes == 240.0
        sel = grounded.provenance["duration_minutes"].standardization
        assert sel.direction == "upper"

    @pytest.mark.asyncio
    async def test_duration_range_inactivation_uses_lower_bound(self, grounding_service):
        """For inactivation models, duration range should resolve to lower bound."""
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

        grounded = await grounding_service.ground_scenario(scenario)
        self._add_organism(grounded)
        result = StandardizationService(model_registry=None).standardize(
            grounded, model_type=ModelType.THERMAL_INACTIVATION
        )

        assert result.payload.time_temperature_profile.total_duration_minutes == 5.0
        sel = grounded.provenance["duration_minutes"].standardization
        assert sel.direction == "lower"


# =============================================================================
# CHICKEN NUGGETS SCENARIO (Query C2)
# =============================================================================

class TestChickenNuggetsScenario:
    """
    Query C2: chicken nuggets reached 68°C instead of target 74°C, held for 8 min.

    Conservative handling for THERMAL_INACTIVATION means range-bound selection
    picks the lower bound (less kill = worse).  Duration and temperature values
    provided by the user pass through unchanged — the conservatism is in
    choosing the lower bound when a range is present, not in adjusting
    point values after the fact.
    """

    def test_chicken_nuggets_inactivation_no_defaults_applied(
        self,
        standardization_service,
    ):
        """
        When temperature and duration are user-supplied, no DefaultImputed events
        should be emitted — the values pass through unchanged.
        """
        grounded = GroundedValues()
        grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT)
        grounded.set("temperature_celsius", 68.0, ValueSource.USER_INFERRED,
                     original_text="about 68°C")
        grounded.set("duration_minutes", 8.0, ValueSource.USER_INFERRED,
                     original_text="roughly 8 minutes")

        result = standardization_service.standardize(
            grounded,
            model_type=ModelType.THERMAL_INACTIVATION,
        )

        assert result.payload is not None
        assert result.payload.parameters.temperature_celsius == 68.0
        assert result.payload.time_temperature_profile.total_duration_minutes == 8.0
        # Temperature and duration were supplied — neither should have a default imputed
        supplied_defaults = [
            d for d in result.defaults_imputed
            if d.field_name in ("temperature_celsius", "duration_minutes")
        ]
        assert supplied_defaults == []

    def test_chicken_nuggets_growth_no_defaults_applied(
        self,
        standardization_service,
    ):
        """Same scenario under GROWTH: user-supplied values pass through unchanged."""
        grounded = GroundedValues()
        grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT)
        grounded.set("temperature_celsius", 68.0, ValueSource.USER_INFERRED)
        grounded.set("duration_minutes", 8.0, ValueSource.USER_INFERRED)

        result = standardization_service.standardize(
            grounded,
            model_type=ModelType.GROWTH,
        )

        assert result.payload is not None
        assert result.payload.parameters.temperature_celsius == 68.0
        assert result.payload.time_temperature_profile.total_duration_minutes == 8.0
        supplied_defaults = [
            d for d in result.defaults_imputed
            if d.field_name in ("temperature_celsius", "duration_minutes")
        ]
        assert supplied_defaults == []


# =============================================================================
# NON-THERMAL SURVIVAL MODEL TESTS
# =============================================================================

class TestNonThermalSurvivalModel:
    """
    NON_THERMAL_SURVIVAL uses the same bound direction as GROWTH.

    Conservative = predict MORE survival (worse outcome) → upper bounds.
    """

    def test_survival_inferred_duration_unchanged(
        self,
        standardization_service,
        grounded_with_inferred_duration,
    ):
        """Survival model: USER_INFERRED duration passes through at the rule's value."""
        result = standardization_service.standardize(
            grounded_with_inferred_duration,
            model_type=ModelType.NON_THERMAL_SURVIVAL,
        )

        assert result.payload.time_temperature_profile.total_duration_minutes == 60.0

    @pytest.mark.asyncio
    async def test_survival_range_uses_upper_bound(self, grounding_service):
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

        grounded = await grounding_service.ground_scenario(scenario)
        grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT)
        result = StandardizationService(model_registry=None).standardize(
            grounded, model_type=ModelType.NON_THERMAL_SURVIVAL
        )

        assert result.payload.time_temperature_profile.total_duration_minutes == 120.0
        sel = grounded.provenance["duration_minutes"].standardization
        assert sel.direction == "upper"


# =============================================================================
# DEFAULT VALUE TESTS
# =============================================================================

class TestDefaultValuesModelTypeAware:
    """Default values record DefaultImputed events with model-type-aware reasons."""

    def test_missing_temperature_growth_uses_abuse_temp(self, standardization_service):
        """Growth model should default to abuse temperature and record a DefaultImputed."""
        grounded = GroundedValues()
        grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT)
        grounded.set("duration_minutes", 60.0, ValueSource.USER_EXPLICIT)

        result = standardization_service.standardize(grounded, model_type=ModelType.GROWTH)

        assert result.payload is not None
        temp_defaults = [
            d for d in result.defaults_imputed if d.field_name == "temperature_celsius"
        ]
        assert len(temp_defaults) == 1
        assert "growth" in temp_defaults[0].reason.lower()

    def test_missing_temperature_inactivation_uses_conservative_cooking_temp(
        self, standardization_service
    ):
        """Inactivation model should default to conservative cooking temperature."""
        grounded = GroundedValues()
        grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT)
        grounded.set("duration_minutes", 10.0, ValueSource.USER_EXPLICIT)

        result = standardization_service.standardize(
            grounded, model_type=ModelType.THERMAL_INACTIVATION
        )

        assert result.payload is not None
        assert result.payload.parameters.temperature_celsius == 60.0

        temp_defaults = [
            d for d in result.defaults_imputed if d.field_name == "temperature_celsius"
        ]
        assert len(temp_defaults) == 1
        assert (
            "pasteurization" in temp_defaults[0].reason.lower()
            or "cooking" in temp_defaults[0].reason.lower()
        )


# =============================================================================
# HELPER METHOD TESTS
# =============================================================================

class TestHelperMethods:
    """Test the helper methods for determining conservative direction."""

    def test_is_inactivation_model(self, standardization_service):
        assert standardization_service._is_inactivation_model(ModelType.THERMAL_INACTIVATION) is True
        assert standardization_service._is_inactivation_model(ModelType.GROWTH) is False
        assert standardization_service._is_inactivation_model(ModelType.NON_THERMAL_SURVIVAL) is False

    def test_get_range_bound_to_use(self, standardization_service):
        assert standardization_service._get_range_bound_to_use(ModelType.GROWTH) == "upper"
        assert standardization_service._get_range_bound_to_use(ModelType.THERMAL_INACTIVATION) == "lower"
        assert standardization_service._get_range_bound_to_use(ModelType.NON_THERMAL_SURVIVAL) == "upper"


# =============================================================================
# INTEGRATION: COMBINED SCENARIO WITH DEFAULTS
# =============================================================================

class TestCombinedDefaults:
    """Test scenarios where multiple defaults are imputed."""

    def test_all_defaults_applied_growth(self, standardization_service):
        """Growth model with only organism set: temperature, pH, aw all defaulted."""
        grounded = GroundedValues()
        grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT)
        grounded.set("duration_minutes", 60.0, ValueSource.USER_EXPLICIT)
        # No temperature, pH, or aw

        result = standardization_service.standardize(grounded, model_type=ModelType.GROWTH)

        default_fields = {d.field_name for d in result.defaults_imputed}
        assert "temperature_celsius" in default_fields
        assert "ph" in default_fields
        assert "water_activity" in default_fields

    def test_all_defaults_applied_inactivation(self, standardization_service):
        """Inactivation model with only organism set: temperature, pH, aw all defaulted."""
        grounded = GroundedValues()
        grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT)
        grounded.set("duration_minutes", 10.0, ValueSource.USER_EXPLICIT)

        result = standardization_service.standardize(
            grounded, model_type=ModelType.THERMAL_INACTIVATION
        )

        default_fields = {d.field_name for d in result.defaults_imputed}
        assert "temperature_celsius" in default_fields


# =============================================================================
# EDGE CASES
# =============================================================================

class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_short_inferred_duration_unchanged(self, standardization_service):
        """Very short USER_INFERRED durations pass through unchanged."""
        grounded = GroundedValues()
        grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT)
        grounded.set("temperature_celsius", 70.0, ValueSource.USER_EXPLICIT)
        grounded.set("duration_minutes", 1.0, ValueSource.USER_INFERRED)

        result = standardization_service.standardize(
            grounded, model_type=ModelType.THERMAL_INACTIVATION
        )

        assert result.payload.time_temperature_profile.total_duration_minutes == 1.0


# =============================================================================
# STANDARDIZATION SERVICE: _select_range_bound UNIT TESTS
# =============================================================================

class TestSelectRangeBound:
    """Unit tests for StandardizationService._select_range_bound."""

    def test_growth_uses_upper_bound(self, standardization_service):
        value, sel = standardization_service._select_range_bound(5.0, 6.2, ModelType.GROWTH)
        assert value == 6.2
        assert sel.direction == "upper"
        assert sel.before_value == [5.0, 6.2]
        assert sel.after_value == 6.2
        assert sel.rule == "range_bound_selection"

    def test_thermal_inactivation_uses_lower_bound(self, standardization_service):
        value, sel = standardization_service._select_range_bound(5.0, 6.2, ModelType.THERMAL_INACTIVATION)
        assert value == 5.0
        assert sel.direction == "lower"
        assert sel.before_value == [5.0, 6.2]
        assert sel.after_value == 5.0

    def test_non_thermal_survival_uses_upper_bound(self, standardization_service):
        value, sel = standardization_service._select_range_bound(0.94, 0.97, ModelType.NON_THERMAL_SURVIVAL)
        assert value == 0.97
        assert sel.direction == "upper"


# =============================================================================
# END-TO-END: BREAD QUERY (GROWTH) — range-bound selection audit
# =============================================================================

class TestBreadQueryEndToEnd:
    """
    Bread query: pH 5.0–6.2, aw 0.94–0.97, growth model.

    Verifies that:
    - Range-bound selection is recorded in provenance.standardization
    - defaults_imputed and range_clamps are empty (range selection is
      NOT a default-imputed or range-clamp event)
    """

    def _make_grounded_bread(self) -> GroundedValues:
        g = GroundedValues()
        g.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT)
        g.set("temperature_celsius", 25.0, ValueSource.USER_EXPLICIT)
        g.set("duration_minutes", 180.0, ValueSource.USER_EXPLICIT)
        g.set(
            "ph",
            5.0,
            source=ValueSource.RAG_RETRIEVAL,
            parsed_range=[5.0, 6.2],
            range_pending=True,
            transformation_applied="range extracted, awaiting standardization",
        )
        g.set(
            "water_activity",
            0.94,
            source=ValueSource.RAG_RETRIEVAL,
            parsed_range=[0.94, 0.97],
            range_pending=True,
            transformation_applied="range extracted, awaiting standardization",
        )
        return g

    def test_bread_growth_upper_bounds_selected(self, standardization_service):
        g = self._make_grounded_bread()
        result = standardization_service.standardize(g, ModelType.GROWTH)

        assert result.payload is not None

        ph_sel = g.provenance["ph"].standardization
        assert ph_sel is not None
        assert ph_sel.rule == "range_bound_selection"
        assert ph_sel.direction == "upper"
        assert ph_sel.before_value == [5.0, 6.2]
        assert ph_sel.after_value == pytest.approx(6.2)
        assert result.payload.parameters.ph == pytest.approx(6.2)

        aw_sel = g.provenance["water_activity"].standardization
        assert aw_sel is not None
        assert aw_sel.direction == "upper"
        assert aw_sel.before_value == [0.94, 0.97]
        assert aw_sel.after_value == pytest.approx(0.97)
        assert result.payload.parameters.water_activity == pytest.approx(0.97)

        # Range-bound selection must NOT appear in audit event lists
        assert result.defaults_imputed == []
        assert result.range_clamps == []
        assert result.warnings == []

    def test_bread_inactivation_lower_bounds_selected(self, standardization_service):
        g = self._make_grounded_bread()
        result = standardization_service.standardize(g, ModelType.THERMAL_INACTIVATION)

        assert result.payload is not None

        ph_sel = g.provenance["ph"].standardization
        assert ph_sel.direction == "lower"
        assert ph_sel.after_value == pytest.approx(5.0)
        assert result.payload.parameters.ph == pytest.approx(5.0)

        aw_sel = g.provenance["water_activity"].standardization
        assert aw_sel.direction == "lower"
        assert aw_sel.after_value == pytest.approx(0.94)

        assert result.defaults_imputed == []
        assert result.range_clamps == []
        assert result.warnings == []


# =============================================================================
# RANGE CLAMPING TESTS (B.1)
# =============================================================================

def _make_registry_with_constraints(
    temp_min: float = 10.0, temp_max: float = 42.0,
    ph_min: float = 4.5, ph_max: float = 7.5,
    aw_min: float = 0.961, aw_max: float = 1.0,
) -> MagicMock:
    """Return a mock registry whose get_model() yields the given constraints."""
    constraints = ComBaseModelConstraints(
        temp_min=temp_min, temp_max=temp_max,
        ph_min=ph_min, ph_max=ph_max,
        aw_min=aw_min, aw_max=aw_max,
    )
    mock_model = MagicMock()
    mock_model.constraints = constraints
    registry = MagicMock()
    registry.get_model.return_value = mock_model
    return registry


class TestRangeClamping:
    """
    Range clamping fires when a value is outside the model's valid range.

    Three audit signals must fire for each clamp:
      1. RangeClamp record in result.range_clamps
      2. Warning string in result.warnings
      3. Clamped value reflected in the payload

    The per-field StandardizationAuditInfo is verified in the integration tests
    (field_audit requires a full pipeline run).
    """

    def test_temperature_above_max_clamped(self):
        """T8: 50°C > max 42°C → clamped to 42°C with RangeClamp + warning."""
        service = StandardizationService(
            model_registry=_make_registry_with_constraints(temp_min=10.0, temp_max=42.0)
        )
        grounded = GroundedValues()
        grounded.set("organism", ComBaseOrganism.ESCHERICHIA_COLI, ValueSource.USER_EXPLICIT)
        grounded.set("temperature_celsius", 50.0, ValueSource.USER_EXPLICIT)
        grounded.set("duration_minutes", 360.0, ValueSource.USER_EXPLICIT)

        result = service.standardize(grounded, model_type=ModelType.GROWTH)

        assert result.payload is not None
        assert result.payload.parameters.temperature_celsius == pytest.approx(42.0)

        temp_clamps = [c for c in result.range_clamps if c.field_name == "temperature_celsius"]
        assert len(temp_clamps) == 1
        c = temp_clamps[0]
        assert c.original_value == pytest.approx(50.0)
        assert c.clamped_value == pytest.approx(42.0)
        assert c.valid_min == pytest.approx(10.0)
        assert c.valid_max == pytest.approx(42.0)

        # Warning string references the original value and the clamped value
        assert any("50" in w and "42" in w for w in result.warnings), (
            f"Expected clamping notice mentioning 50 and 42; got: {result.warnings}"
        )

    def test_temperature_below_min_clamped(self):
        """2°C < min 10°C → clamped to 10°C."""
        service = StandardizationService(
            model_registry=_make_registry_with_constraints(temp_min=10.0, temp_max=42.0)
        )
        grounded = GroundedValues()
        grounded.set("organism", ComBaseOrganism.ESCHERICHIA_COLI, ValueSource.USER_EXPLICIT)
        grounded.set("temperature_celsius", 2.0, ValueSource.USER_EXPLICIT)
        grounded.set("duration_minutes", 60.0, ValueSource.USER_EXPLICIT)

        result = service.standardize(grounded, model_type=ModelType.GROWTH)

        assert result.payload.parameters.temperature_celsius == pytest.approx(10.0)
        c = result.range_clamps[0]
        assert c.original_value == pytest.approx(2.0)
        assert c.clamped_value == pytest.approx(10.0)

    def test_water_activity_below_min_clamped(self):
        """aw 0.97 < min 0.973 → clamped to 0.973 with RangeClamp + warning."""
        service = StandardizationService(
            model_registry=_make_registry_with_constraints(aw_min=0.973, aw_max=1.0)
        )
        grounded = GroundedValues()
        grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT)
        grounded.set("temperature_celsius", 25.0, ValueSource.USER_EXPLICIT)
        grounded.set("duration_minutes", 240.0, ValueSource.USER_EXPLICIT)
        grounded.set("water_activity", 0.97, ValueSource.USER_EXPLICIT)

        result = service.standardize(grounded, model_type=ModelType.GROWTH)

        assert result.payload is not None
        assert result.payload.parameters.water_activity == pytest.approx(0.973)

        aw_clamps = [c for c in result.range_clamps if c.field_name == "water_activity"]
        assert len(aw_clamps) == 1
        assert aw_clamps[0].original_value == pytest.approx(0.97)
        assert aw_clamps[0].clamped_value == pytest.approx(0.973)

        assert any("0.97" in w for w in result.warnings), (
            f"Expected aw clamping notice; got: {result.warnings}"
        )

    def test_in_range_value_no_clamp_no_warning(self):
        """Value inside valid range → no clamp, no range-related warning."""
        service = StandardizationService(
            model_registry=_make_registry_with_constraints(temp_min=10.0, temp_max=42.0)
        )
        grounded = GroundedValues()
        grounded.set("organism", ComBaseOrganism.ESCHERICHIA_COLI, ValueSource.USER_EXPLICIT)
        grounded.set("temperature_celsius", 25.0, ValueSource.USER_EXPLICIT)
        grounded.set("duration_minutes", 60.0, ValueSource.USER_EXPLICIT)

        result = service.standardize(grounded, model_type=ModelType.GROWTH)

        temp_clamps = [c for c in result.range_clamps if c.field_name == "temperature_celsius"]
        assert temp_clamps == []
        range_warnings = [w for w in result.warnings if "range" in w.lower() and "temperature" in w.lower()]
        assert range_warnings == []

    def test_no_registry_value_passes_through_unchanged(self):
        """Without a registry, out-of-range values pass through with no clamp."""
        service = StandardizationService(model_registry=None)
        grounded = GroundedValues()
        grounded.set("organism", ComBaseOrganism.ESCHERICHIA_COLI, ValueSource.USER_EXPLICIT)
        grounded.set("temperature_celsius", 50.0, ValueSource.USER_EXPLICIT)
        grounded.set("duration_minutes", 60.0, ValueSource.USER_EXPLICIT)

        result = service.standardize(grounded, model_type=ModelType.GROWTH)

        assert result.payload is not None
        assert result.payload.parameters.temperature_celsius == pytest.approx(50.0)
        assert result.range_clamps == []


# =============================================================================
# ORGANISM DEFAULT IMPUTATION TESTS (B.2)
# =============================================================================

class TestOrganismDefaultImputation:
    """
    When no organism is specified, Salmonella is imputed.
    The imputation must appear in both defaults_imputed (canonical audit record)
    and warnings (user-facing notice) — they serve different purposes.
    """

    def test_missing_organism_emits_default_imputed(self):
        """No organism → DefaultImputed entry for 'organism' field."""
        service = StandardizationService(model_registry=None)
        grounded = GroundedValues()
        grounded.set("temperature_celsius", 25.0, ValueSource.USER_EXPLICIT)
        grounded.set("duration_minutes", 60.0, ValueSource.USER_EXPLICIT)

        result = service.standardize(grounded, model_type=ModelType.GROWTH)

        assert result.payload is not None
        assert result.payload.model_selection.organism == ComBaseOrganism.SALMONELLA

        org_defaults = [d for d in result.defaults_imputed if d.field_name == "organism"]
        assert len(org_defaults) == 1
        assert "salmonella" in str(org_defaults[0].imputed_value).lower()
        assert "salmonella" in org_defaults[0].reason.lower()

    def test_missing_organism_also_emits_warning(self):
        """No organism → warning string emitted alongside DefaultImputed."""
        service = StandardizationService(model_registry=None)
        grounded = GroundedValues()
        grounded.set("temperature_celsius", 25.0, ValueSource.USER_EXPLICIT)
        grounded.set("duration_minutes", 60.0, ValueSource.USER_EXPLICIT)

        result = service.standardize(grounded, model_type=ModelType.GROWTH)

        org_warnings = [
            w for w in result.warnings
            if "salmonella" in w.lower() or "pathogen" in w.lower()
        ]
        assert len(org_warnings) >= 1

    def test_explicit_organism_no_default_emitted(self):
        """Explicit organism → no DefaultImputed for organism field."""
        service = StandardizationService(model_registry=None)
        grounded = GroundedValues()
        grounded.set("organism", ComBaseOrganism.LISTERIA_MONOCYTOGENES, ValueSource.USER_EXPLICIT)
        grounded.set("temperature_celsius", 4.0, ValueSource.USER_EXPLICIT)
        grounded.set("duration_minutes", 1440.0, ValueSource.USER_EXPLICIT)

        result = service.standardize(grounded, model_type=ModelType.GROWTH)

        org_defaults = [d for d in result.defaults_imputed if d.field_name == "organism"]
        assert org_defaults == []
