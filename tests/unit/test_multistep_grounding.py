"""
Unit tests for multi-step time-temperature grounding and standardization.

Covers:
- GroundedValues.add_step / has_steps
- GroundingService._resolve_temperature_value / _resolve_duration_value
- GroundingService._ground_multi_step_profile
- GroundingService.ground_scenario routing (single vs multi-step)
- StandardizationService._build_multi_step_profile
- StandardizationService.standardize multi-step path (bias, defaults, missing duration)
"""

import pytest
from unittest.mock import MagicMock, AsyncMock

from app.models.enums import ModelType, ComBaseOrganism, BiasType
from app.models.extraction import (
    ExtractedScenario,
    ExtractedTemperature,
    ExtractedDuration,
    ExtractedTimeTemperatureStep,
    ExtractedEnvironmentalConditions,
)
from app.models.metadata import ValueSource
from app.services.grounding.grounding_service import (
    GroundedValues,
    GroundedStep,
    GroundingService,
)
from app.services.standardization.standardization_service import StandardizationService


# =============================================================================
# HELPERS
# =============================================================================

def make_grounding_service() -> GroundingService:
    mock_retrieval = MagicMock()
    mock_retrieval.query_food_properties.return_value = MagicMock(
        has_confident_result=False, results=[]
    )
    mock_retrieval.query_pathogen_hazards.return_value = MagicMock(
        has_confident_result=False, results=[]
    )
    return GroundingService(retrieval_service=mock_retrieval, use_llm_extraction=False)


def make_step(
    order: int,
    temp_celsius: float | None = None,
    temp_desc: str | None = None,
    dur_minutes: float | None = None,
    dur_desc: str | None = None,
) -> ExtractedTimeTemperatureStep:
    return ExtractedTimeTemperatureStep(
        sequence_order=order,
        temperature=ExtractedTemperature(
            value_celsius=temp_celsius,
            description=temp_desc,
        ),
        duration=ExtractedDuration(
            value_minutes=dur_minutes,
            description=dur_desc,
        ),
    )


def make_multistep_scenario(*steps: ExtractedTimeTemperatureStep) -> ExtractedScenario:
    return ExtractedScenario(
        food_description="chicken",
        is_multi_step=True,
        time_temperature_steps=list(steps),
        environmental_conditions=ExtractedEnvironmentalConditions(),
        implied_model_type=ModelType.GROWTH,
    )


# =============================================================================
# GroundedValues
# =============================================================================

class TestGroundedValuesSteps:

    def test_has_steps_false_initially(self):
        g = GroundedValues()
        assert g.has_steps is False

    def test_add_step_sets_has_steps(self):
        g = GroundedValues()
        g.add_step(step_order=1, temperature_celsius=25.0, duration_minutes=60.0)
        assert g.has_steps is True

    def test_add_step_stores_values(self):
        g = GroundedValues()
        g.add_step(step_order=1, temperature_celsius=28.0, duration_minutes=45.0)
        g.add_step(step_order=2, temperature_celsius=22.0, duration_minutes=60.0)

        assert len(g.steps) == 2
        assert g.steps[0].step_order == 1
        assert g.steps[0].temperature_celsius == 28.0
        assert g.steps[0].duration_minutes == 45.0
        assert g.steps[1].step_order == 2

    def test_add_step_stores_provenance(self):
        from app.models.metadata import ValueProvenance
        g = GroundedValues()
        prov = ValueProvenance(source=ValueSource.USER_EXPLICIT, confidence=0.9)
        g.add_step(step_order=1, temperature_celsius=25.0, duration_minutes=60.0,
                   temp_provenance=prov)
        assert g.steps[0].temp_provenance is prov

    def test_add_step_allows_none_values(self):
        g = GroundedValues()
        g.add_step(step_order=1, temperature_celsius=None, duration_minutes=None)
        assert g.steps[0].temperature_celsius is None
        assert g.steps[0].duration_minutes is None


# =============================================================================
# GroundingService — resolution helpers
# =============================================================================

class TestResolveTemperatureValue:

    def setup_method(self):
        self.svc = make_grounding_service()

    def test_explicit_value(self):
        temp = ExtractedTemperature(value_celsius=28.0)
        val, prov = self.svc._resolve_temperature_value(temp, ModelType.GROWTH)
        assert val == 28.0
        assert prov.source == ValueSource.USER_EXPLICIT
        assert prov.confidence == 0.90

    def test_range_growth_uses_upper_bound(self):
        temp = ExtractedTemperature(is_range=True, range_min_celsius=20.0, range_max_celsius=28.0)
        val, prov = self.svc._resolve_temperature_value(temp, ModelType.GROWTH)
        assert val == 28.0
        assert prov.source == ValueSource.USER_INFERRED

    def test_range_inactivation_uses_lower_bound(self):
        temp = ExtractedTemperature(is_range=True, range_min_celsius=65.0, range_max_celsius=75.0)
        val, prov = self.svc._resolve_temperature_value(temp, ModelType.THERMAL_INACTIVATION)
        assert val == 65.0

    def test_description_room_temperature(self):
        temp = ExtractedTemperature(description="room temperature")
        val, prov = self.svc._resolve_temperature_value(temp, ModelType.GROWTH)
        assert val == 25.0
        assert prov.source == ValueSource.USER_INFERRED

    def test_unresolvable_returns_none(self):
        temp = ExtractedTemperature()
        val, prov = self.svc._resolve_temperature_value(temp, ModelType.GROWTH)
        assert val is None
        assert prov is None


class TestResolveDurationValue:

    def setup_method(self):
        self.svc = make_grounding_service()

    def test_explicit_value(self):
        dur = ExtractedDuration(value_minutes=45.0)
        val, prov = self.svc._resolve_duration_value(dur, ModelType.GROWTH)
        assert val == 45.0
        assert prov.source == ValueSource.USER_EXPLICIT

    def test_range_growth_uses_upper_bound(self):
        dur = ExtractedDuration(range_min_minutes=30.0, range_max_minutes=60.0)
        val, prov = self.svc._resolve_duration_value(dur, ModelType.GROWTH)
        assert val == 60.0

    def test_range_inactivation_uses_lower_bound(self):
        dur = ExtractedDuration(range_min_minutes=5.0, range_max_minutes=10.0)
        val, prov = self.svc._resolve_duration_value(dur, ModelType.THERMAL_INACTIVATION)
        assert val == 5.0

    def test_description_overnight(self):
        dur = ExtractedDuration(description="overnight")
        val, prov = self.svc._resolve_duration_value(dur, ModelType.GROWTH)
        assert val is not None
        assert val > 0
        assert prov.source == ValueSource.USER_INFERRED

    def test_unresolvable_returns_none(self):
        dur = ExtractedDuration()
        val, prov = self.svc._resolve_duration_value(dur, ModelType.GROWTH)
        assert val is None
        assert prov is None


# =============================================================================
# GroundingService — multi-step profile grounding
# =============================================================================

class TestGroundMultiStepProfile:

    def setup_method(self):
        self.svc = make_grounding_service()

    def test_three_steps_all_explicit(self):
        scenario = make_multistep_scenario(
            make_step(1, temp_celsius=28.0, dur_minutes=45.0),
            make_step(2, temp_celsius=22.0, dur_minutes=60.0),
            make_step(3, temp_celsius=4.0,  dur_minutes=120.0),
        )
        grounded = GroundedValues()
        self.svc._ground_multi_step_profile(scenario, grounded, ModelType.GROWTH)

        assert grounded.has_steps
        assert len(grounded.steps) == 3
        assert grounded.steps[0].temperature_celsius == 28.0
        assert grounded.steps[0].duration_minutes == 45.0
        assert grounded.steps[1].temperature_celsius == 22.0
        assert grounded.steps[2].temperature_celsius == 4.0
        assert grounded.steps[2].duration_minutes == 120.0

    def test_steps_sorted_by_sequence_order(self):
        # Deliver steps out of order
        scenario = make_multistep_scenario(
            make_step(3, temp_celsius=4.0,  dur_minutes=120.0),
            make_step(1, temp_celsius=28.0, dur_minutes=45.0),
            make_step(2, temp_celsius=22.0, dur_minutes=60.0),
        )
        grounded = GroundedValues()
        self.svc._ground_multi_step_profile(scenario, grounded, ModelType.GROWTH)

        orders = [s.step_order for s in grounded.steps]
        assert orders == [1, 2, 3]
        assert grounded.steps[0].temperature_celsius == 28.0

    def test_provenance_explicit_temp_is_user_explicit(self):
        scenario = make_multistep_scenario(
            make_step(1, temp_celsius=28.0, dur_minutes=45.0),
        )
        grounded = GroundedValues()
        self.svc._ground_multi_step_profile(scenario, grounded, ModelType.GROWTH)

        assert grounded.steps[0].temp_provenance.source == ValueSource.USER_EXPLICIT
        assert grounded.steps[0].dur_provenance.source == ValueSource.USER_EXPLICIT

    def test_description_temperature_resolved(self):
        scenario = make_multistep_scenario(
            make_step(1, temp_desc="room temperature", dur_minutes=60.0),
        )
        grounded = GroundedValues()
        self.svc._ground_multi_step_profile(scenario, grounded, ModelType.GROWTH)

        assert grounded.steps[0].temperature_celsius == 25.0
        assert grounded.steps[0].temp_provenance.source == ValueSource.USER_INFERRED

    def test_unresolvable_temp_stores_none_with_warning(self):
        scenario = make_multistep_scenario(
            make_step(1, dur_minutes=60.0),  # no temperature at all
        )
        grounded = GroundedValues()
        self.svc._ground_multi_step_profile(scenario, grounded, ModelType.GROWTH)

        assert grounded.steps[0].temperature_celsius is None
        assert any("Step 1 temperature" in w for w in grounded.warnings)

    def test_unresolvable_duration_stores_none_with_warning(self):
        scenario = make_multistep_scenario(
            make_step(1, temp_celsius=25.0),  # no duration at all
        )
        grounded = GroundedValues()
        self.svc._ground_multi_step_profile(scenario, grounded, ModelType.GROWTH)

        assert grounded.steps[0].duration_minutes is None
        assert any("Step 1 duration" in w for w in grounded.warnings)

    def test_does_not_set_flat_temperature_or_duration(self):
        """Multi-step grounding must not clobber single-step keys."""
        scenario = make_multistep_scenario(
            make_step(1, temp_celsius=25.0, dur_minutes=60.0),
        )
        grounded = GroundedValues()
        self.svc._ground_multi_step_profile(scenario, grounded, ModelType.GROWTH)

        assert not grounded.has("temperature_celsius")
        assert not grounded.has("duration_minutes")


# =============================================================================
# GroundingService — ground_scenario routing
# =============================================================================

class TestGroundScenarioRouting:

    def setup_method(self):
        self.svc = make_grounding_service()

    async def test_single_step_uses_flat_keys(self):
        scenario = ExtractedScenario(
            food_description="chicken",
            is_multi_step=False,
            single_step_temperature=ExtractedTemperature(value_celsius=25.0),
            single_step_duration=ExtractedDuration(value_minutes=180.0),
            environmental_conditions=ExtractedEnvironmentalConditions(),
        )
        grounded = await self.svc.ground_scenario(scenario)

        assert grounded.get("temperature_celsius") == 25.0
        assert grounded.get("duration_minutes") == 180.0
        assert not grounded.has_steps

    async def test_multi_step_populates_steps_not_flat_keys(self):
        scenario = make_multistep_scenario(
            make_step(1, temp_celsius=28.0, dur_minutes=45.0),
            make_step(2, temp_celsius=4.0,  dur_minutes=120.0),
        )
        grounded = await self.svc.ground_scenario(scenario)

        assert grounded.has_steps
        assert len(grounded.steps) == 2
        assert not grounded.has("temperature_celsius")
        assert not grounded.has("duration_minutes")

    async def test_multi_step_flag_false_with_steps_falls_back_to_single(self):
        """is_multi_step=False even when time_temperature_steps is populated
        should use the single-step path."""
        scenario = ExtractedScenario(
            food_description="chicken",
            is_multi_step=False,
            single_step_temperature=ExtractedTemperature(value_celsius=25.0),
            single_step_duration=ExtractedDuration(value_minutes=180.0),
            time_temperature_steps=[make_step(1, temp_celsius=30.0, dur_minutes=90.0)],
            environmental_conditions=ExtractedEnvironmentalConditions(),
        )
        grounded = await self.svc.ground_scenario(scenario)

        assert grounded.get("temperature_celsius") == 25.0
        assert not grounded.has_steps


# =============================================================================
# StandardizationService — multi-step standardization
# =============================================================================

class TestStandardizeMultiStep:

    def setup_method(self):
        self.svc = StandardizationService(model_registry=None)

    def _make_grounded(self, *steps: tuple) -> GroundedValues:
        """Build a GroundedValues with organism + given (temp, dur) step pairs."""
        g = GroundedValues()
        g.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT, 0.90)
        for i, (temp, dur) in enumerate(steps, start=1):
            g.add_step(
                step_order=i,
                temperature_celsius=temp,
                duration_minutes=dur,
            )
        return g

    def test_three_step_payload_built_successfully(self):
        g = self._make_grounded((28.0, 45.0), (22.0, 60.0), (4.0, 120.0))
        result = self.svc.standardize(g, ModelType.GROWTH)

        assert result.missing_required == []
        assert result.payload is not None
        profile = result.payload.time_temperature_profile
        assert profile.is_multi_step is True
        assert len(profile.steps) == 3

    def test_step_temperatures_preserved(self):
        g = self._make_grounded((28.0, 45.0), (22.0, 60.0), (4.0, 120.0))
        result = self.svc.standardize(g, ModelType.GROWTH)

        temps = [s.temperature_celsius for s in result.payload.time_temperature_profile.steps]
        assert temps == [28.0, 22.0, 4.0]

    def test_step_durations_preserved_for_explicit_provenance(self):
        """Explicit provenance durations must not receive the inferred margin."""
        from app.models.metadata import ValueProvenance
        g = GroundedValues()
        g.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT, 0.90)
        prov_explicit = ValueProvenance(source=ValueSource.USER_EXPLICIT, confidence=0.90)
        g.add_step(1, 25.0, 60.0, dur_provenance=prov_explicit)
        g.add_step(2, 4.0, 120.0, dur_provenance=prov_explicit)

        result = self.svc.standardize(g, ModelType.GROWTH)

        durs = [s.duration_minutes for s in result.payload.time_temperature_profile.steps]
        assert durs == [60.0, 120.0]

    def test_inferred_duration_gets_growth_margin(self):
        """USER_INFERRED durations get +20% for growth models."""
        from app.models.metadata import ValueProvenance
        g = GroundedValues()
        g.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT, 0.90)
        prov_inferred = ValueProvenance(source=ValueSource.USER_INFERRED, confidence=0.75)
        g.add_step(1, 25.0, 60.0, dur_provenance=prov_inferred)

        result = self.svc.standardize(g, ModelType.GROWTH)

        step = result.payload.time_temperature_profile.steps[0]
        assert step.duration_minutes == pytest.approx(72.0)  # 60 * 1.2

    def test_inferred_duration_gets_inactivation_margin(self):
        """USER_INFERRED durations get -20% for thermal inactivation models."""
        from app.models.metadata import ValueProvenance
        g = GroundedValues()
        g.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT, 0.90)
        prov_inferred = ValueProvenance(source=ValueSource.USER_INFERRED, confidence=0.75)
        g.add_step(1, 72.0, 10.0, dur_provenance=prov_inferred)

        result = self.svc.standardize(g, ModelType.THERMAL_INACTIVATION)

        step = result.payload.time_temperature_profile.steps[0]
        assert step.duration_minutes == pytest.approx(8.0)  # 10 * 0.8

    def test_missing_temperature_gets_conservative_default(self):
        """A step with None temperature receives the abuse default (25°C for growth)."""
        g = self._make_grounded((None, 60.0))
        result = self.svc.standardize(g, ModelType.GROWTH)

        assert result.missing_required == []
        step = result.payload.time_temperature_profile.steps[0]
        assert step.temperature_celsius == 25.0  # default_temperature_abuse_c
        assert any(BiasType.MISSING_VALUE_IMPUTED == bc.bias_type for bc in result.bias_corrections)

    def test_missing_duration_fails_with_missing_required(self):
        """A step with None duration must populate missing_required and return no payload."""
        g = self._make_grounded((25.0, None))
        result = self.svc.standardize(g, ModelType.GROWTH)

        assert any("duration" in m for m in result.missing_required)
        assert result.payload is None

    def test_missing_duration_mid_sequence_fails(self):
        """Missing duration on the second of three steps must still fail."""
        g = self._make_grounded((28.0, 45.0), (22.0, None), (4.0, 120.0))
        result = self.svc.standardize(g, ModelType.GROWTH)

        assert any("step 2" in m.lower() for m in result.missing_required)
        assert result.payload is None

    def test_total_duration_is_sum_of_steps(self):
        g = self._make_grounded((28.0, 45.0), (22.0, 60.0), (4.0, 120.0))
        result = self.svc.standardize(g, ModelType.GROWTH)

        assert result.payload.time_temperature_profile.total_duration_minutes == pytest.approx(225.0)

    def test_representative_temp_is_first_step(self):
        """ComBaseParameters.temperature_celsius should equal the first step's temperature."""
        g = self._make_grounded((28.0, 45.0), (4.0, 120.0))
        result = self.svc.standardize(g, ModelType.GROWTH)

        assert result.payload.parameters.temperature_celsius == pytest.approx(28.0)

    def test_ph_and_aw_shared_across_all_steps(self):
        """pH and water activity in parameters come from grounded flat values."""
        g = self._make_grounded((28.0, 45.0), (4.0, 120.0))
        g.set("ph", 5.9, ValueSource.RAG_RETRIEVAL, 0.85)
        g.set("water_activity", 0.99, ValueSource.RAG_RETRIEVAL, 0.85)
        result = self.svc.standardize(g, ModelType.GROWTH)

        assert result.payload.parameters.ph == pytest.approx(5.9)
        assert result.payload.parameters.water_activity == pytest.approx(0.99)

    def test_low_confidence_temp_gets_bump_growth(self):
        """Low-confidence step temperature gets +5°C bump for growth models."""
        from app.models.metadata import ValueProvenance
        g = GroundedValues()
        g.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT, 0.90)
        low_conf = ValueProvenance(source=ValueSource.USER_INFERRED, confidence=0.40)
        g.add_step(1, 20.0, 60.0, temp_provenance=low_conf)

        result = self.svc.standardize(g, ModelType.GROWTH)

        step = result.payload.time_temperature_profile.steps[0]
        assert step.temperature_celsius == pytest.approx(25.0)  # 20 + 5

    def test_low_confidence_temp_gets_bump_inactivation(self):
        """Low-confidence step temperature gets -5°C bump for inactivation models."""
        from app.models.metadata import ValueProvenance
        g = GroundedValues()
        g.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT, 0.90)
        low_conf = ValueProvenance(source=ValueSource.USER_INFERRED, confidence=0.40)
        g.add_step(1, 72.0, 10.0, temp_provenance=low_conf)

        result = self.svc.standardize(g, ModelType.THERMAL_INACTIVATION)

        step = result.payload.time_temperature_profile.steps[0]
        assert step.temperature_celsius == pytest.approx(67.0)  # 72 - 5

    def test_gapped_step_orders_renumbered_sequentially(self):
        """LLM may return sequence_orders like [1, 2, 4]; validator requires [1, 2, 3].
        _build_multi_step_profile must renumber to sequential starting from 1."""
        g = GroundedValues()
        g.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT, 0.90)
        # Simulate gapped LLM output: step_orders 1, 2, 4 instead of 1, 2, 3
        g.add_step(1, 28.0, 45.0)
        g.add_step(2, 22.0, 60.0)
        g.add_step(4, 4.0, 120.0)  # gap — would fail TimeTemperatureProfile validator if not renumbered

        result = self.svc.standardize(g, ModelType.GROWTH)

        assert result.missing_required == [], result.missing_required
        profile = result.payload.time_temperature_profile
        assert profile.is_multi_step is True
        assert [s.step_order for s in profile.steps] == [1, 2, 3]
        # Physical order (temperature sequence) is preserved after renumbering
        assert [s.temperature_celsius for s in profile.steps] == pytest.approx([28.0, 22.0, 4.0])

    def test_single_step_scenario_unaffected(self):
        """Existing single-step path must still work when has_steps is False."""
        g = GroundedValues()
        g.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT, 0.90)
        g.set("temperature_celsius", 25.0, ValueSource.USER_EXPLICIT, 0.90)
        g.set("duration_minutes", 180.0, ValueSource.USER_EXPLICIT, 0.90)

        result = self.svc.standardize(g, ModelType.GROWTH)

        assert result.missing_required == []
        profile = result.payload.time_temperature_profile
        assert profile.is_multi_step is False
        assert len(profile.steps) == 1
