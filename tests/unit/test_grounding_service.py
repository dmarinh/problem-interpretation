"""
Unit tests for grounding service.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.enums import ComBaseOrganism
from app.models.extraction import (
    ExtractedDuration,
    ExtractedEnvironmentalConditions,
    ExtractedFoodProperties,
    ExtractedScenario,
    ExtractedTemperature,
)
from app.models.metadata import ValueSource
from app.services.grounding.grounding_service import (
    GroundedValues,
    GroundingService,
    _composite_keyword_match,
    get_grounding_service,
    reset_grounding_service,
)


@pytest.fixture
def grounding_service():
    """Create grounding service with mocked dependencies."""
    mock_retrieval = MagicMock()
    mock_llm = AsyncMock()

    service = GroundingService(
        retrieval_service=mock_retrieval,
        llm_client=mock_llm,
        use_llm_extraction=False,  # Disable LLM for unit tests
    )
    return service, mock_retrieval, mock_llm


class TestGroundedValues:
    """Tests for GroundedValues container."""

    def test_set_and_get(self):
        """Should set and get values."""
        grounded = GroundedValues()
        grounded.set("ph", 6.0, ValueSource.USER_EXPLICIT)

        assert grounded.get("ph") == 6.0
        assert grounded.has("ph")

    def test_get_default(self):
        """Should return default for missing values."""
        grounded = GroundedValues()

        assert grounded.get("ph") is None
        assert grounded.get("ph", 7.0) == 7.0

    def test_has_false_for_missing(self):
        """Should return False for missing fields."""
        grounded = GroundedValues()

        assert grounded.has("ph") is False

    def test_provenance_tracked(self):
        """Should track provenance."""
        grounded = GroundedValues()
        grounded.set(
            "ph",
            6.0,
            source=ValueSource.RAG_RETRIEVAL,
            retrieval_source="doc_123",
        )

        assert "ph" in grounded.provenance
        assert grounded.provenance["ph"].source == ValueSource.RAG_RETRIEVAL

    def test_mark_ungrounded(self):
        """Should mark fields as ungrounded with reason."""
        grounded = GroundedValues()
        grounded.mark_ungrounded("organism", "No pathogen found")

        assert "organism" in grounded.ungrounded_fields
        assert any("organism" in w for w in grounded.warnings)


class TestExtractNumericValue:
    """Tests for regex-based numeric extraction."""

    @pytest.fixture
    def service(self):
        return GroundingService(
            retrieval_service=MagicMock(),
            use_llm_extraction=False,
        )

    def test_extract_single_value(self, service):
        """Should extract single pH value."""
        result = service._extract_numeric_value("pH 6.0", ["ph"])

        assert result.value == 6.0
        assert result.is_range is False

    def test_extract_value_with_colon(self, service):
        """Should extract value after colon."""
        result = service._extract_numeric_value("pH: 6.5", ["ph"])

        assert result.value == 6.5

    def test_extract_range_with_hyphen(self, service):
        """Should extract range with hyphen."""
        result = service._extract_numeric_value("pH 5.9-6.2", ["ph"])

        assert result.is_range is True
        assert result.range_min == 5.9
        assert result.range_max == 6.2

    def test_extract_range_with_and(self, service):
        """Should extract range with 'and'."""
        result = service._extract_numeric_value("pH between 5.5 and 6.0", ["ph"])

        assert result.is_range is True
        assert result.range_min == 5.5
        assert result.range_max == 6.0

    def test_extract_range_with_to(self, service):
        """Should extract range with 'to'."""
        result = service._extract_numeric_value("pH 5.5 to 6.0", ["ph"])

        assert result.is_range is True
        assert result.range_min == 5.5
        assert result.range_max == 6.0

    def test_extract_water_activity(self, service):
        """Should extract water activity."""
        result = service._extract_numeric_value(
            "water activity 0.99", ["water activity", "aw"]
        )

        assert result.value == 0.99

    def test_extract_aw_shorthand(self, service):
        """Should extract aw shorthand."""
        result = service._extract_numeric_value("aw 0.98", ["water activity", "aw"])

        assert result.value == 0.98

    def test_no_match_returns_empty(self, service):
        """Should return empty result for no match."""
        result = service._extract_numeric_value("no values here", ["ph"])

        assert result.value is None
        assert result.is_range is False

    def test_keyword_not_found(self, service):
        """Should return empty when keyword not in text."""
        result = service._extract_numeric_value("temperature is 25", ["ph"])

        assert result.value is None

    # ------------------------------------------------------------------
    # Word-boundary and plausibility regression tests (bug: "raw" → aw=200)
    # ------------------------------------------------------------------

    def test_aw_not_matched_inside_raw(self, service):
        """'aw' inside 'raw' must not be matched (word-boundary fix)."""
        result = service._extract_numeric_value(
            "raw chicken stored at 25", ["water activity", "aw"]
        )
        assert result.value is None
        assert result.is_range is False

    def test_aw_not_matched_inside_raw_with_citation(self, service):
        """Actual bug case: citation year must not leak into aw extraction."""
        rag_content = (
            "chicken (poultry): pH range 6.5 to 6.7. Raw chicken [FDA-PH-2007]"
        )
        result = service._extract_numeric_value(rag_content, ["water activity", "aw"])
        assert result.value is None

    def test_aw_matched_as_standalone_word(self, service):
        """'aw' as a standalone word must still be matched after the fix."""
        result = service._extract_numeric_value("aw 0.97", ["water activity", "aw"])
        assert result.value == 0.97

    def test_aw_matched_with_colon(self, service):
        """'aw: 0.97' format must still be matched."""
        result = service._extract_numeric_value("aw: 0.95", ["water activity", "aw"])
        assert result.value == 0.95

    def test_aw_not_matched_inside_thaw(self, service):
        """'aw' inside 'thaw' must not be matched."""
        result = service._extract_numeric_value(
            "thaw the meat at room temperature", ["water activity", "aw"]
        )
        assert result.value is None

    def test_ph_with_is_connector(self, service):
        """'pH is 6.5' single-value format must still be extracted."""
        result = service._extract_numeric_value("pH is 6.5", ["ph"])
        assert result.value == 6.5

    def test_single_value_not_extracted_from_distant_text(self, service):
        """Number buried in non-adjacent text must not be captured."""
        # "aw" matches but the next content is unrelated text before any number
        result = service._extract_numeric_value(
            "aw category is high, but nothing quantified here: ref 200",
            ["water activity", "aw"],
        )
        # "is" connector allows "is high" — "high" is not a digit, so no match
        assert result.value is None


class TestExtractFoodPropertiesPlausibility:
    """Plausibility filter: out-of-range regex values fall through to LLM."""

    @pytest.fixture
    def service_no_llm(self):
        return GroundingService(
            retrieval_service=MagicMock(),
            use_llm_extraction=False,
        )

    @pytest.mark.asyncio
    async def test_aw_200_treated_as_not_found(self, service_no_llm):
        """Regex-extracted aw=200 (from citation) must be discarded as implausible."""
        rag_content = (
            "chicken (poultry): pH range 6.5 to 6.7. Raw chicken [FDA-PH-2007]"
        )
        props, _, _ = await service_no_llm._extract_food_properties(rag_content)
        # pH should be extracted correctly
        assert props.has_ph
        assert props.ph_min == 6.5
        assert props.ph_max == 6.7
        # aw should NOT be set (200 is not a valid water activity)
        assert not props.has_aw
        assert props.aw_value is None

    @pytest.mark.asyncio
    async def test_valid_aw_passes_through(self, service_no_llm):
        """Valid aw value from regex must pass the plausibility filter."""
        props, _, _ = await service_no_llm._extract_food_properties(
            "fresh poultry: water activity 0.99 to 1.0"
        )
        assert props.has_aw
        assert props.aw_min == 0.99
        assert props.aw_max == 1.0

    @pytest.mark.asyncio
    async def test_invalid_aw_triggers_llm_fallback(self):
        """Implausible regex aw triggers LLM fallback when LLM is enabled."""
        mock_llm = AsyncMock()
        mock_llm.extract = AsyncMock(
            return_value=ExtractedFoodProperties(
                aw_value=0.97,
                extraction_method="llm",
            )
        )
        service = GroundingService(
            retrieval_service=MagicMock(),
            llm_client=mock_llm,
            use_llm_extraction=True,
        )
        # Content where regex would extract aw=200 (pre-fix it crashed; now
        # the plausibility filter discards it, triggering the LLM fallback)
        props, _, _ = await service._extract_food_properties(
            "chicken (poultry): pH range 6.5 to 6.7. Raw chicken [FDA-PH-2007]"
        )
        mock_llm.extract.assert_called_once()
        assert props.has_aw
        assert props.aw_value == 0.97

    @pytest.mark.asyncio
    async def test_ph_out_of_range_discarded(self, service_no_llm):
        """pH > 14 from regex must be discarded as implausible."""
        props, _, _ = await service_no_llm._extract_food_properties(
            "product: aw 0.95, reference code 200"
        )
        # The "200" near "code" should not be captured as pH (word-boundary fix)
        assert props.ph_value is None or (0.0 <= (props.ph_value or 0.0) <= 14.0)


class TestGroundEnvironmentalConditions:
    """Tests for grounding user explicit environmental conditions."""

    def test_ground_explicit_ph(self, grounding_service):
        """Should ground explicit pH value."""
        service, _, _ = grounding_service
        grounded = GroundedValues()

        conditions = ExtractedEnvironmentalConditions(ph_value=6.5)
        service._ground_environmental_conditions(conditions, grounded)

        assert grounded.get("ph") == 6.5
        assert grounded.provenance["ph"].source == ValueSource.USER_EXPLICIT

    def test_ground_explicit_water_activity(self, grounding_service):
        """Should ground explicit water activity."""
        service, _, _ = grounding_service
        grounded = GroundedValues()

        conditions = ExtractedEnvironmentalConditions(water_activity=0.95)
        service._ground_environmental_conditions(conditions, grounded)

        assert grounded.get("water_activity") == 0.95
        assert grounded.provenance["water_activity"].source == ValueSource.USER_EXPLICIT

    def test_ground_multiple_conditions(self, grounding_service):
        """Should ground multiple conditions."""
        service, _, _ = grounding_service
        grounded = GroundedValues()

        conditions = ExtractedEnvironmentalConditions(
            ph_value=6.0,
            water_activity=0.98,
            co2_percent=5.0,
            nitrite_ppm=150.0,
        )
        service._ground_environmental_conditions(conditions, grounded)

        assert grounded.get("ph") == 6.0
        assert grounded.get("water_activity") == 0.98
        assert grounded.get("co2_percent") == 5.0
        assert grounded.get("nitrite_ppm") == 150.0

    def test_none_values_not_grounded(self, grounding_service):
        """Should not ground None values."""
        service, _, _ = grounding_service
        grounded = GroundedValues()

        conditions = ExtractedEnvironmentalConditions()
        service._ground_environmental_conditions(conditions, grounded)

        assert not grounded.has("ph")
        assert not grounded.has("water_activity")

    def test_ground_ph_range_stores_pending(self, grounding_service):
        """pH range: lower bound stored with range_pending=True, parsed_range=[min, max]."""
        service, _, _ = grounding_service
        grounded = GroundedValues()

        conditions = ExtractedEnvironmentalConditions(ph_min=5.5, ph_max=6.0)
        service._ground_environmental_conditions(conditions, grounded)

        assert grounded.get("ph") == 5.5
        prov = grounded.provenance["ph"]
        assert prov.source == ValueSource.USER_EXPLICIT
        assert prov.range_pending is True
        assert prov.parsed_range == [5.5, 6.0]

    def test_ground_aw_range_stores_pending(self, grounding_service):
        """aw range: lower bound stored with range_pending=True, parsed_range=[min, max]."""
        service, _, _ = grounding_service
        grounded = GroundedValues()

        conditions = ExtractedEnvironmentalConditions(
            water_activity_min=0.93, water_activity_max=0.96
        )
        service._ground_environmental_conditions(conditions, grounded)

        assert grounded.get("water_activity") == 0.93
        prov = grounded.provenance["water_activity"]
        assert prov.source == ValueSource.USER_EXPLICIT
        assert prov.range_pending is True
        assert prov.parsed_range == [0.93, 0.96]

    def test_single_ph_value_no_range_pending(self, grounding_service):
        """Single ph_value: range_pending must be False, parsed_range null. Regression guard."""
        service, _, _ = grounding_service
        grounded = GroundedValues()

        conditions = ExtractedEnvironmentalConditions(ph_value=6.0)
        service._ground_environmental_conditions(conditions, grounded)

        assert grounded.get("ph") == 6.0
        prov = grounded.provenance["ph"]
        assert prov.range_pending is False
        assert prov.parsed_range is None

    def test_ph_range_takes_priority_over_single_value(self, grounding_service):
        """When both ph_range and ph_value are present, range takes priority."""
        service, _, _ = grounding_service
        grounded = GroundedValues()

        conditions = ExtractedEnvironmentalConditions(
            ph_value=5.5, ph_min=5.5, ph_max=6.0
        )
        service._ground_environmental_conditions(conditions, grounded)

        prov = grounded.provenance["ph"]
        assert prov.range_pending is True
        assert prov.parsed_range == [5.5, 6.0]

    def test_ground_both_ph_and_aw_ranges(self, grounding_service):
        """Combined pH + aw ranges: both fields get independent range_pending entries."""
        service, _, _ = grounding_service
        grounded = GroundedValues()

        conditions = ExtractedEnvironmentalConditions(
            ph_min=5.5,
            ph_max=6.0,
            water_activity_min=0.93,
            water_activity_max=0.96,
        )
        service._ground_environmental_conditions(conditions, grounded)

        ph_prov = grounded.provenance["ph"]
        assert ph_prov.range_pending is True
        assert ph_prov.parsed_range == [5.5, 6.0]

        aw_prov = grounded.provenance["water_activity"]
        assert aw_prov.range_pending is True
        assert aw_prov.parsed_range == [0.93, 0.96]

    def test_ph_range_invalid_bounds_warns(self, grounding_service):
        """pH range with an out-of-range bound produces a warning, not a grounded value."""
        service, _, _ = grounding_service
        grounded = GroundedValues()

        conditions = ExtractedEnvironmentalConditions(ph_min=5.0, ph_max=20.0)
        service._ground_environmental_conditions(conditions, grounded)

        assert not grounded.has("ph")
        assert any("ph" in w.lower() for w in grounded.warnings)


class TestGroundTemperature:
    """Tests for temperature grounding."""

    def test_ground_explicit_temperature(self, grounding_service):
        """Should ground explicit temperature value."""
        service, _, _ = grounding_service
        grounded = GroundedValues()

        scenario = ExtractedScenario(
            single_step_temperature=ExtractedTemperature(value_celsius=25.0),
            single_step_duration=ExtractedDuration(value_minutes=60.0),
        )
        service._ground_temperature(scenario, grounded)

        assert grounded.get("temperature_celsius") == 25.0
        assert (
            grounded.provenance["temperature_celsius"].source
            == ValueSource.USER_EXPLICIT
        )

    def test_ground_temperature_range_stores_pending(self, grounding_service):
        """Range temperature stores lower bound with range_pending=True; bound selection
        happens in StandardizationService, not here."""
        service, _, _ = grounding_service
        grounded = GroundedValues()

        scenario = ExtractedScenario(
            single_step_temperature=ExtractedTemperature(
                is_range=True,
                range_min_celsius=20.0,
                range_max_celsius=25.0,
            ),
            single_step_duration=ExtractedDuration(value_minutes=60.0),
        )
        service._ground_temperature(scenario, grounded)

        assert grounded.get("temperature_celsius") == 20.0  # lower bound placeholder
        prov = grounded.provenance["temperature_celsius"]
        assert prov.source == ValueSource.USER_EXPLICIT
        assert prov.range_pending is True
        assert prov.parsed_range == [20.0, 25.0]

    def test_ground_temperature_description(self, grounding_service):
        """Should interpret temperature description."""
        service, _, _ = grounding_service
        grounded = GroundedValues()

        scenario = ExtractedScenario(
            single_step_temperature=ExtractedTemperature(
                description="room temperature"
            ),
            single_step_duration=ExtractedDuration(value_minutes=60.0),
        )
        service._ground_temperature(scenario, grounded)

        assert grounded.get("temperature_celsius") == 25.0
        assert (
            grounded.provenance["temperature_celsius"].source
            == ValueSource.USER_INFERRED
        )

    def test_unknown_description_marks_ungrounded(self, grounding_service):
        """Should mark ungrounded for unknown description."""
        service, _, _ = grounding_service
        grounded = GroundedValues()

        scenario = ExtractedScenario(
            single_step_temperature=ExtractedTemperature(description="xyz123"),
            single_step_duration=ExtractedDuration(value_minutes=60.0),
        )
        service._ground_temperature(scenario, grounded)

        assert not grounded.has("temperature_celsius")
        assert "temperature_celsius" in grounded.ungrounded_fields


class TestNewTemperatureRules:
    """
    Set B: verify each rule added in the vague-temperature workstream.

    Tests cover two levels:
    1. find_temperature_interpretation — confirms the substring rule fires (not embedding fallback)
       and returns the correct value.
    2. Grounding service — confirms the full provenance shape (USER_INFERRED / rule_match).
    """

    @pytest.mark.parametrize(
        "phrase,expected_value",
        [
            ("typical retail refrigeration", 4.0),
            ("retail refrigeration", 4.0),
            ("household refrigerator", 4.0),
            ("domestic refrigerator", 4.0),
            ("home refrigerator", 4.0),
            ("retail display", 4.0),
            ("home fridge", 4.0),
            ("household freezer", -18.0),
            ("home freezer", -18.0),
            ("stored cold", 4.0),
            ("kept cold", 4.0),
        ],
    )
    def test_substring_rule_fires(self, phrase, expected_value):
        from app.config.rules import find_temperature_interpretation

        rule = find_temperature_interpretation(phrase)
        assert rule is not None, f"No rule matched '{phrase}'"
        assert rule.value == expected_value
        assert (
            rule.similarity is None
        ), f"'{phrase}' should match via substring, not embedding"

    def test_stored_cold_wins_over_cold(self):
        """'stored cold' must resolve to 4°C, not 10°C from the 'cold' substring rule."""
        from app.config.rules import find_temperature_interpretation

        rule = find_temperature_interpretation("stored cold")
        assert rule is not None
        assert rule.value == 4.0
        assert rule.pattern == "stored cold"

    def test_kept_cold_wins_over_cold(self):
        """'kept cold' must resolve to 4°C, not 10°C."""
        from app.config.rules import find_temperature_interpretation

        rule = find_temperature_interpretation("kept cold")
        assert rule is not None
        assert rule.value == 4.0
        assert rule.pattern == "kept cold"

    @pytest.mark.parametrize(
        "phrase,expected_value",
        [
            ("home refrigerator", 4.0),
            ("typical retail refrigeration", 4.0),
            ("stored cold", 4.0),
            ("household freezer", -18.0),
            # home fridge / home freezer are closest substring-collision neighbours in the sort;
            # included to catch any future collision with the shorter "fridge" / "freezer" rules.
            ("home fridge", 4.0),
            ("home freezer", -18.0),
        ],
    )
    def test_grounding_provenance_is_user_inferred_rule_match(
        self, grounding_service, phrase, expected_value
    ):
        """Grounding service produces USER_INFERRED / rule_match for new rules."""
        service, _, _ = grounding_service
        grounded = GroundedValues()
        scenario = ExtractedScenario(
            single_step_temperature=ExtractedTemperature(description=phrase),
            single_step_duration=ExtractedDuration(value_minutes=60.0),
        )
        service._ground_temperature(scenario, grounded)

        assert grounded.get("temperature_celsius") == expected_value
        prov = grounded.provenance["temperature_celsius"]
        assert prov.source == ValueSource.USER_INFERRED
        assert prov.extraction_method == "rule_match"
        assert prov.matched_pattern is not None


class TestGroundDuration:
    """Tests for duration grounding."""

    def test_ground_explicit_duration(self, grounding_service):
        """Should ground explicit duration value."""
        service, _, _ = grounding_service
        grounded = GroundedValues()

        scenario = ExtractedScenario(
            single_step_temperature=ExtractedTemperature(value_celsius=25.0),
            single_step_duration=ExtractedDuration(value_minutes=180.0),
        )
        service._ground_duration(scenario, grounded)

        assert grounded.get("duration_minutes") == 180.0
        assert (
            grounded.provenance["duration_minutes"].source == ValueSource.USER_EXPLICIT
        )

    def test_ground_duration_range_stores_pending(self, grounding_service):
        """Range duration stores lower bound with range_pending=True; bound selection
        happens in StandardizationService, not here."""
        service, _, _ = grounding_service
        grounded = GroundedValues()

        scenario = ExtractedScenario(
            single_step_temperature=ExtractedTemperature(value_celsius=25.0),
            single_step_duration=ExtractedDuration(
                range_min_minutes=60.0,
                range_max_minutes=120.0,
            ),
        )
        service._ground_duration(scenario, grounded)

        assert grounded.get("duration_minutes") == 60.0  # lower bound placeholder
        prov = grounded.provenance["duration_minutes"]
        assert prov.source == ValueSource.USER_EXPLICIT
        assert prov.range_pending is True
        assert prov.parsed_range == [60.0, 120.0]

    def test_ground_duration_description(self, grounding_service):
        """Should interpret duration description."""
        service, _, _ = grounding_service
        grounded = GroundedValues()

        scenario = ExtractedScenario(
            single_step_temperature=ExtractedTemperature(value_celsius=25.0),
            single_step_duration=ExtractedDuration(description="overnight"),
        )
        service._ground_duration(scenario, grounded)

        assert grounded.get("duration_minutes") == 480.0  # 8 hours


class TestGroundScenario:
    """Tests for full scenario grounding."""

    @pytest.mark.asyncio
    async def test_user_explicit_takes_priority(self, grounding_service):
        """User explicit values should not be overwritten by RAG."""
        service, mock_retrieval, _ = grounding_service

        # Setup RAG to return different values for food properties
        mock_food_response = MagicMock()
        mock_food_response.has_confident_result = True
        mock_food_response.results = [
            MagicMock(
                confidence=0.9,
                content="pH 5.5, water activity 0.95",
                source="doc_1",
                doc_id="doc_1",
            )
        ]
        mock_food_response.top_result = mock_food_response.results[0]
        mock_retrieval.query_food_properties.return_value = mock_food_response

        # Tier 2 fallback for water_activity (not user-explicit) returns no result
        mock_retrieval.query_food_ph.return_value = MagicMock(
            has_confident_result=False, results=[]
        )
        mock_retrieval.query_food_water_activity.return_value = MagicMock(
            has_confident_result=False, results=[]
        )

        # Setup RAG for pathogen (won't be used since pathogen not needed)
        mock_pathogen_response = MagicMock()
        mock_pathogen_response.has_confident_result = False
        mock_pathogen_response.results = []
        mock_retrieval.query_pathogen_hazards.return_value = mock_pathogen_response

        scenario = ExtractedScenario(
            food_description="chicken",
            single_step_temperature=ExtractedTemperature(value_celsius=25.0),
            single_step_duration=ExtractedDuration(value_minutes=180.0),
            environmental_conditions=ExtractedEnvironmentalConditions(
                ph_value=6.5,  # User explicit
            ),
        )

        grounded = await service.ground_scenario(scenario)

        # User explicit pH should remain
        assert grounded.get("ph") == 6.5
        assert grounded.provenance["ph"].source == ValueSource.USER_EXPLICIT

    @pytest.mark.asyncio
    async def test_rag_not_called_when_not_needed(self, grounding_service):
        """RAG should not be called when user provides all values."""
        service, mock_retrieval, _ = grounding_service

        scenario = ExtractedScenario(
            food_description="chicken",
            pathogen_mentioned="Salmonella",
            single_step_temperature=ExtractedTemperature(value_celsius=25.0),
            single_step_duration=ExtractedDuration(value_minutes=180.0),
            environmental_conditions=ExtractedEnvironmentalConditions(
                ph_value=6.0,
                water_activity=0.99,
            ),
        )

        await service.ground_scenario(scenario)

        # RAG for food properties should not be called
        mock_retrieval.query_food_properties.assert_not_called()

        # RAG for pathogen should not be called (user provided it)
        mock_retrieval.query_pathogen_hazards.assert_not_called()

    @pytest.mark.asyncio
    async def test_explicit_pathogen_grounded(self, grounding_service):
        """Explicit pathogen mention should be grounded."""
        service, mock_retrieval, _ = grounding_service

        # Primary food-properties query: not confident
        mock_food_response = MagicMock()
        mock_food_response.has_confident_result = False
        mock_food_response.results = []
        mock_food_response.query = "chicken pH water activity properties"
        mock_retrieval.query_food_properties.return_value = mock_food_response

        # Tier 2 fallback queries: also not confident (food description doesn't match KB)
        mock_fallback_ph = MagicMock()
        mock_fallback_ph.has_confident_result = False
        mock_fallback_ph.results = []
        mock_fallback_ph.query = "chicken pH acidity"
        mock_retrieval.query_food_ph.return_value = mock_fallback_ph

        mock_fallback_aw = MagicMock()
        mock_fallback_aw.has_confident_result = False
        mock_fallback_aw.results = []
        mock_fallback_aw.query = "chicken water activity aw moisture"
        mock_retrieval.query_food_water_activity.return_value = mock_fallback_aw

        # Pathogen also not in hazards KB (not needed — user provided it)
        mock_retrieval.query_pathogen_hazards.return_value = MagicMock(
            has_confident_result=False, results=[]
        )

        scenario = ExtractedScenario(
            food_description="chicken",
            pathogen_mentioned="Salmonella",
            single_step_temperature=ExtractedTemperature(value_celsius=25.0),
            single_step_duration=ExtractedDuration(value_minutes=180.0),
        )

        grounded = await service.ground_scenario(scenario)

        assert grounded.get("organism") == ComBaseOrganism.SALMONELLA
        assert grounded.provenance["organism"].source == ValueSource.USER_EXPLICIT


class TestGroundFoodPropertiesTwoTier:
    """Tests for two-tier food property retrieval (Tier 1 primary + Tier 2 per-field fallback)."""

    def _make_confident_response(
        self, content: str, query: str, doc_id: str = "doc_1"
    ) -> MagicMock:
        """Build a mock RetrievalResponse with a confident top result."""
        top = MagicMock()
        top.doc_id = doc_id
        top.content = content
        top.source = "food_properties"
        top.distance = None  # suppresses isinstance(dist, (int, float)) branch
        top.rerank_score = None
        top.metadata = {}

        r = MagicMock()
        r.has_confident_result = True
        r.top_result = top
        r.results = [top]
        r.query = query
        return r

    def _make_no_result_response(self, query: str) -> MagicMock:
        """Build a mock RetrievalResponse with no confident result."""
        r = MagicMock()
        r.has_confident_result = False
        r.results = []
        r.top_result = None
        r.query = query
        return r

    @pytest.mark.asyncio
    async def test_capture_a_aw_fallback_when_primary_doc_lacks_aw(
        self, grounding_service
    ):
        """Capture A: primary returns chicken pH doc (no aw) → Tier 2 aw query fires and grounds aw."""
        service, mock_retrieval, _ = grounding_service

        primary_query = "chicken pH water activity properties"
        mock_retrieval.query_food_properties.return_value = self._make_confident_response(
            content="chicken (poultry): pH range 6.2 to 6.4. Raw chicken [IFT-2003-T33]",
            query=primary_query,
        )
        # No fallback pH query should fire — pH is already grounded
        aw_fallback_query = "chicken water activity aw moisture"
        mock_retrieval.query_food_water_activity.return_value = self._make_confident_response(
            content="fresh poultry (poultry): water activity 0.99 to 1.0. All fresh poultry [IFT-2003-T31]",
            query=aw_fallback_query,
            doc_id="doc_26",
        )

        grounded = GroundedValues()
        await service._ground_food_properties("chicken", grounded)

        # pH: grounded from primary, RAG_RETRIEVAL
        assert grounded.has("ph")
        assert grounded.provenance["ph"].source == ValueSource.RAG_RETRIEVAL
        assert grounded.get("ph") == 6.2  # lower bound of range stored pending
        assert grounded.provenance["ph"].parsed_range == [6.2, 6.4]

        # aw: grounded from fallback, RAG_RETRIEVAL_FALLBACK
        assert grounded.has("water_activity")
        assert (
            grounded.provenance["water_activity"].source
            == ValueSource.RAG_RETRIEVAL_FALLBACK
        )
        assert grounded.get("water_activity") == 0.99

        # Tier 2 pH query must NOT have fired (pH already grounded after Tier 1)
        mock_retrieval.query_food_ph.assert_not_called()

        # Tier 2 aw retrieval must be tagged with attributed_field
        aw_retrieval = next(
            (r for r in grounded.retrievals if r.attributed_field == "water_activity"),
            None,
        )
        assert aw_retrieval is not None
        assert aw_retrieval.query == aw_fallback_query

    @pytest.mark.asyncio
    async def test_capture_b_both_fields_from_fallback_when_primary_misses(
        self, grounding_service
    ):
        """Capture B: primary not confident → both Tier 2 fallback queries fire and ground both fields."""
        service, mock_retrieval, _ = grounding_service

        mock_retrieval.query_food_properties.return_value = (
            self._make_no_result_response("poultry pH water activity properties")
        )
        ph_fallback_query = "poultry pH acidity"
        mock_retrieval.query_food_ph.return_value = self._make_confident_response(
            content="chicken (poultry): pH range 6.2 to 6.4. Raw chicken [IFT-2003-T33]",
            query=ph_fallback_query,
        )
        aw_fallback_query = "poultry water activity aw moisture"
        mock_retrieval.query_food_water_activity.return_value = self._make_confident_response(
            content="fresh poultry (poultry): water activity 0.99 to 1.0. All fresh poultry [IFT-2003-T31]",
            query=aw_fallback_query,
        )

        grounded = GroundedValues()
        await service._ground_food_properties("poultry", grounded)

        assert grounded.has("ph")
        assert grounded.provenance["ph"].source == ValueSource.RAG_RETRIEVAL_FALLBACK
        assert grounded.has("water_activity")
        assert (
            grounded.provenance["water_activity"].source
            == ValueSource.RAG_RETRIEVAL_FALLBACK
        )

        # Both fallback retrievals tagged with their respective fields
        ph_retrieval = next(
            (r for r in grounded.retrievals if r.attributed_field == "ph"), None
        )
        aw_retrieval = next(
            (r for r in grounded.retrievals if r.attributed_field == "water_activity"),
            None,
        )
        assert ph_retrieval is not None and ph_retrieval.query == ph_fallback_query
        assert aw_retrieval is not None and aw_retrieval.query == aw_fallback_query

    @pytest.mark.asyncio
    async def test_unknown_food_defaults_when_both_tiers_miss(self, grounding_service):
        """Unmatchable food: both tiers below threshold → neither field grounded → defaults later."""
        service, mock_retrieval, _ = grounding_service

        mock_retrieval.query_food_properties.return_value = (
            self._make_no_result_response("zarflonite pH water activity properties")
        )
        mock_retrieval.query_food_ph.return_value = self._make_no_result_response(
            "zarflonite pH acidity"
        )
        mock_retrieval.query_food_water_activity.return_value = (
            self._make_no_result_response("zarflonite water activity aw moisture")
        )

        grounded = GroundedValues()
        await service._ground_food_properties("zarflonite", grounded)

        assert not grounded.has("ph")
        assert not grounded.has("water_activity")
        # Both fallback-miss warnings emitted
        assert any("ph" in w.lower() for w in grounded.warnings)
        assert any("water" in w.lower() for w in grounded.warnings)

    @pytest.mark.asyncio
    async def test_known_rich_row_no_fallback_fired(self, grounding_service):
        """Regression guard: primary returns both pH and aw → no Tier 2 queries fired."""
        service, mock_retrieval, _ = grounding_service

        mock_retrieval.query_food_properties.return_value = self._make_confident_response(
            content="bread white (grain): pH range 5.0 to 6.2. water activity 0.94 to 0.97.",
            query="bread white pH water activity properties",
        )

        grounded = GroundedValues()
        await service._ground_food_properties("bread white", grounded)

        assert grounded.has("ph")
        assert grounded.provenance["ph"].source == ValueSource.RAG_RETRIEVAL
        assert grounded.has("water_activity")
        assert grounded.provenance["water_activity"].source == ValueSource.RAG_RETRIEVAL

        mock_retrieval.query_food_ph.assert_not_called()
        mock_retrieval.query_food_water_activity.assert_not_called()

    @pytest.mark.asyncio
    async def test_asymmetric_primary_supplies_aw_fallback_supplies_ph(
        self, grounding_service
    ):
        """Asymmetric: primary doc has aw only → aw=RAG_RETRIEVAL, pH fires Tier 2 fallback.

        Tightened assertion: attributed_field tags verify which retrieval the audit routing
        would assign to each field — pH must reference the Tier 2 query, aw Tier 1.
        """
        service, mock_retrieval, _ = grounding_service

        primary_query = "soy sauce pH water activity properties"
        mock_retrieval.query_food_properties.return_value = self._make_confident_response(
            content="soy sauce (condiment): water activity 0.80. Fermented [FDA-PH-2007]",
            query=primary_query,
        )
        ph_fallback_query = "soy sauce pH acidity"
        mock_retrieval.query_food_ph.return_value = self._make_confident_response(
            content="soy sauce (condiment): pH range 4.4 to 5.4. Fermented soy sauce [FDA-PH-2007]",
            query=ph_fallback_query,
        )

        grounded = GroundedValues()
        await service._ground_food_properties("soy sauce", grounded)

        # aw from primary (Tier 1)
        assert grounded.has("water_activity")
        assert grounded.provenance["water_activity"].source == ValueSource.RAG_RETRIEVAL

        # pH from fallback (Tier 2)
        assert grounded.has("ph")
        assert grounded.provenance["ph"].source == ValueSource.RAG_RETRIEVAL_FALLBACK

        # Tier 2 aw query must NOT have fired (aw already grounded from primary)
        mock_retrieval.query_food_water_activity.assert_not_called()

        # Audit routing: untagged primary covers aw, tagged fallback covers pH
        ph_retrieval = next(
            (r for r in grounded.retrievals if r.attributed_field == "ph"), None
        )
        untagged = next(
            (r for r in grounded.retrievals if r.attributed_field is None), None
        )
        assert (
            ph_retrieval is not None
        ), "Tier 2 pH retrieval must be tagged attributed_field='ph'"
        assert ph_retrieval.query == ph_fallback_query
        assert (
            untagged is not None
        ), "Primary retrieval must be untagged (attributed_field=None)"
        assert untagged.query == primary_query


class TestExtractFoodProperties:
    """Tests for food properties extraction."""

    @pytest.mark.asyncio
    async def test_regex_extraction(self, grounding_service):
        """Should extract properties using regex."""
        service, _, _ = grounding_service

        props, _, _ = await service._extract_food_properties(
            "Raw chicken has pH 6.0 and water activity 0.99"
        )

        assert props.has_ph
        assert props.has_aw
        assert props.extraction_method == "regex"

    @pytest.mark.asyncio
    async def test_regex_extraction_range(self, grounding_service):
        """Should extract range values."""
        service, _, _ = grounding_service

        props, _, _ = await service._extract_food_properties(
            "Chicken has pH between 5.9 and 6.2"
        )

        assert props.has_ph
        assert props.ph_min == 5.9
        assert props.ph_max == 6.2


class TestExtractedFoodProperties:
    """Tests for ExtractedFoodProperties model."""

    def test_has_ph_with_value(self):
        """Should detect pH presence with single value."""
        props = ExtractedFoodProperties(ph_value=6.0)
        assert props.has_ph is True

    def test_has_ph_with_range(self):
        """Should detect pH presence with range."""
        props = ExtractedFoodProperties(ph_min=5.5, ph_max=6.0)
        assert props.has_ph is True

    def test_has_ph_false_when_missing(self):
        """Should return False when pH not set."""
        props = ExtractedFoodProperties()
        assert props.has_ph is False

    def test_has_aw_with_value(self):
        """Should detect aw presence with single value."""
        props = ExtractedFoodProperties(aw_value=0.99)
        assert props.has_aw is True

    def test_has_aw_false_when_missing(self):
        """Should return False when aw not set."""
        props = ExtractedFoodProperties()
        assert props.has_aw is False


class TestGroundPathogenFromRag:
    """Tests for two-stage pathogen grounding via RAG."""

    def _make_stage1_response(
        self, food_name: str, doc_id: str = "doc_1", content: str = ""
    ):
        """Build a mock Stage 1 RetrievalResponse with a confident top result."""
        top = MagicMock()
        top.doc_id = doc_id
        top.content = (
            content
            or f"Hazard for {food_name}: Salmonella spp. (238 annual US deaths)."
        )
        top.metadata = {"food_name": food_name, "pathogen": "Salmonella spp."}
        top.source = None
        top.distance = None
        top.rerank_score = None

        response = MagicMock()
        response.has_confident_result = True
        response.top_result = top
        response.results = [top]
        response.query = food_name
        return response

    def _make_hazard_dict(
        self, pathogen: str, deaths: int, food_name: str = "chicken raw"
    ) -> dict:
        return {
            "id": f"{food_name}_{pathogen}",
            "document": f"Hazard for {food_name}: {pathogen} ({deaths} annual US deaths).",
            "metadata": {
                "food_name": food_name,
                "pathogen": pathogen,
                "annual_deaths_us": str(deaths),
            },
        }

    @pytest.mark.asyncio
    async def test_selects_pathogen_with_highest_annual_deaths(self, grounding_service):
        """Stage 2 sort must select Salmonella (238) over Listeria (172) and Staph (6)."""
        service, mock_retrieval, _ = grounding_service

        mock_retrieval.query_pathogen_hazards.return_value = self._make_stage1_response(
            "chicken raw"
        )
        mock_retrieval.get_hazards_for_food.return_value = [
            self._make_hazard_dict("Salmonella spp.", 238),
            self._make_hazard_dict("Listeria monocytogenes", 172),
            self._make_hazard_dict("Staphylococcus aureus", 6),
        ]

        grounded = GroundedValues()
        await service._ground_pathogen_from_rag("raw chicken", grounded)

        assert grounded.has("organism")
        assert grounded.get("organism") == ComBaseOrganism.SALMONELLA
        assert (
            grounded.provenance["organism"].extraction_method
            == "ranked_by_annual_deaths"
        )

    @pytest.mark.asyncio
    async def test_staphylococcus_does_not_outrank_salmonella(self, grounding_service):
        """Staphylococcus (6 deaths) must never be selected when Salmonella (238) is present."""
        service, mock_retrieval, _ = grounding_service

        mock_retrieval.query_pathogen_hazards.return_value = self._make_stage1_response(
            "chicken raw"
        )
        # Return in "wrong" order as embedding would
        # Mock returns already sorted (as the real get_hazards_for_food would)
        mock_retrieval.get_hazards_for_food.return_value = [
            self._make_hazard_dict("Salmonella spp.", 238),
            self._make_hazard_dict("Campylobacter jejuni", 197),
            self._make_hazard_dict("Listeria monocytogenes", 172),
            self._make_hazard_dict("Staphylococcus aureus", 6),
        ]

        grounded = GroundedValues()
        await service._ground_pathogen_from_rag("raw chicken", grounded)

        assert grounded.get("organism") == ComBaseOrganism.SALMONELLA

    @pytest.mark.asyncio
    async def test_category_fallback_when_stage2_empty(self, grounding_service):
        """If get_hazards_for_food returns empty, the category-level fallback fires.

        For 'raw chicken': bridge → poultry → meats and poultry → Salmonella (238 deaths).
        Source is RAG_PATHOGEN_CATEGORY_FALLBACK, not the former Stage 1 fuzzy_match.
        """
        service, mock_retrieval, _ = grounding_service

        stage1_response = self._make_stage1_response(
            food_name="chicken raw",
            content="Hazard for chicken raw: Salmonella spp. (238 annual US deaths). [CDC-2019-T1T2]",
        )
        mock_retrieval.query_pathogen_hazards.return_value = stage1_response
        mock_retrieval.get_hazards_for_food.return_value = []

        grounded = GroundedValues()
        await service._ground_pathogen_from_rag("raw chicken", grounded)

        assert grounded.has("organism")
        assert grounded.get("organism") == ComBaseOrganism.SALMONELLA
        assert (
            grounded.provenance["organism"].source
            == ValueSource.RAG_PATHOGEN_CATEGORY_FALLBACK
        )
        assert (
            grounded.provenance["organism"].extraction_method
            == "category_fallback_ranked_by_annual_deaths"
        )

    @pytest.mark.asyncio
    async def test_nothing_grounded_when_stage1_not_confident(self, grounding_service):
        """If Stage 1 has no confident result, nothing is grounded."""
        service, mock_retrieval, _ = grounding_service

        response = MagicMock()
        response.has_confident_result = False
        response.results = []
        mock_retrieval.query_pathogen_hazards.return_value = response

        grounded = GroundedValues()
        await service._ground_pathogen_from_rag("unknown food xyz", grounded)

        assert not grounded.has("organism")

    @pytest.mark.asyncio
    async def test_stage2_called_with_canonical_food_name(self, grounding_service):
        """Stage 2 must be called with the food_name from Stage 1 metadata, not the raw description."""
        service, mock_retrieval, _ = grounding_service

        mock_retrieval.query_pathogen_hazards.return_value = self._make_stage1_response(
            "beef raw"
        )
        mock_retrieval.get_hazards_for_food.return_value = [
            self._make_hazard_dict("Salmonella spp.", 238, food_name="beef raw"),
        ]

        grounded = GroundedValues()
        await service._ground_pathogen_from_rag("raw beef steak", grounded)

        mock_retrieval.get_hazards_for_food.assert_called_once_with("beef raw")


class TestSingleton:
    """Tests for singleton pattern."""

    def test_get_grounding_service_returns_same_instance(self):
        """Should return same instance."""
        reset_grounding_service()

        service1 = get_grounding_service()
        service2 = get_grounding_service()

        assert service1 is service2

    def test_reset_creates_new_instance(self):
        """Reset should create new instance."""
        reset_grounding_service()
        service1 = get_grounding_service()

        reset_grounding_service()
        service2 = get_grounding_service()

        assert service1 is not service2


# =============================================================================
# _build_retrieval_metadata
# =============================================================================


class TestBuildRetrievalMetadata:
    """
    Unit tests for _build_retrieval_metadata in grounding_service.py.

    The function maps a rag-layer RetrievalResponse to a metadata RetrievalResult.
    Key behaviour under test: which doc becomes top_match, when reranker_top /
    attempted_top are emitted, and how runners_up are deduplicated.
    """

    def _rag_result(
        self, doc_id, distance, rerank_score=None, content="text", metadata=None
    ):
        from app.models.enums import RetrievalConfidenceLevel
        from app.rag.retrieval import RetrievalResult as RagResult

        conf = max(0.0, 1.0 - distance)
        level = (
            RetrievalConfidenceLevel.HIGH
            if conf >= 0.85
            else (
                RetrievalConfidenceLevel.MEDIUM
                if conf >= 0.70
                else RetrievalConfidenceLevel.LOW
            )
        )
        return RagResult(
            content=content,
            confidence=conf,
            confidence_level=level,
            source=f"src_{doc_id}",
            metadata=metadata or {},
            doc_id=doc_id,
            distance=distance,
            rerank_score=rerank_score,
        )

    def _response(self, results, threshold=0.70):
        from app.rag.retrieval import RetrievalResponse

        top_result = next((r for r in results if r.confidence >= threshold), None)
        return RetrievalResponse(
            query="test query",
            results=results,
            top_result=top_result,
            has_confident_result=top_result is not None,
            threshold=threshold,
        )

    def test_common_case_no_reranker_top(self):
        """When results[0] clears the threshold, reranker_top and attempted_top are absent."""
        from app.services.grounding.grounding_service import _build_retrieval_metadata

        r1 = self._rag_result(
            "doc_24", distance=0.25, rerank_score=0.90
        )  # conf=0.75 passes
        r2 = self._rag_result(
            "doc_26", distance=0.45, rerank_score=0.60
        )  # conf=0.55 fails
        result = _build_retrieval_metadata(self._response([r1, r2]))

        assert result.chunk_id == "doc_24"
        assert result.reranker_top is None
        assert result.attempted_top is None
        assert len(result.runners_up) == 1
        assert result.runners_up[0].doc_id == "doc_26"

    def test_reranker_divergence_reranker_top_populated(self):
        """
        When results[0] is the reranker's top pick but fails threshold while
        results[1] passes, reranker_top is emitted and top_match shows results[1].
        This is the Q04 scenario.
        """
        from app.services.grounding.grounding_service import _build_retrieval_metadata

        r1 = self._rag_result(
            "doc_26", distance=0.45, rerank_score=0.95
        )  # conf=0.55 fails
        r2 = self._rag_result(
            "doc_24", distance=0.25, rerank_score=0.80
        )  # conf=0.75 passes
        result = _build_retrieval_metadata(self._response([r1, r2]))

        assert result.chunk_id == "doc_24"
        assert result.reranker_top is not None
        assert result.reranker_top.doc_id == "doc_26"
        assert result.reranker_top.skip_reason == "failed_embedding_threshold:0.70"
        assert result.reranker_top.embedding_score == round(1.0 - 0.45, 4)
        assert result.reranker_top.rerank_score == 0.95
        assert result.attempted_top is None
        # Both doc_26 and doc_24 are already surfaced — runners_up is empty.
        assert result.runners_up == []

    def test_all_failed_attempted_top_populated(self):
        """When no result passes threshold, top_match is None and attempted_top is set."""
        from app.services.grounding.grounding_service import _build_retrieval_metadata

        r1 = self._rag_result(
            "doc_26", distance=0.45, rerank_score=0.90
        )  # conf=0.55 fails
        r2 = self._rag_result(
            "doc_24", distance=0.50, rerank_score=0.70
        )  # conf=0.50 fails
        result = _build_retrieval_metadata(self._response([r1, r2]))

        assert result.chunk_id is None
        assert result.reranker_top is None
        assert result.attempted_top is not None
        assert result.attempted_top.doc_id == "doc_26"
        assert result.attempted_top.skip_reason == "failed_embedding_threshold:0.70"

    def test_empty_results_all_null(self):
        """Empty result list: all doc fields null, no skipped docs, no runners_up."""
        from app.rag.retrieval import RetrievalResponse
        from app.services.grounding.grounding_service import _build_retrieval_metadata

        response = RetrievalResponse(
            query="empty",
            results=[],
            top_result=None,
            has_confident_result=False,
            threshold=0.70,
        )
        result = _build_retrieval_metadata(response)

        assert result.chunk_id is None
        assert result.reranker_top is None
        assert result.attempted_top is None
        assert result.runners_up == []

    def test_three_results_with_divergence_runners_up_deduplicated(self):
        """With 3 results and divergence, runners_up excludes top_match and reranker_top."""
        from app.services.grounding.grounding_service import _build_retrieval_metadata

        r1 = self._rag_result(
            "doc_26", distance=0.45, rerank_score=0.95
        )  # reranker top, fails
        r2 = self._rag_result("doc_24", distance=0.25, rerank_score=0.80)  # top_match
        r3 = self._rag_result(
            "doc_22", distance=0.28, rerank_score=0.60
        )  # pure runner-up
        result = _build_retrieval_metadata(self._response([r1, r2, r3]))

        assert result.chunk_id == "doc_24"
        assert result.reranker_top.doc_id == "doc_26"
        assert len(result.runners_up) == 1
        assert result.runners_up[0].doc_id == "doc_22"

    def test_threshold_value_in_skip_reason(self):
        """skip_reason embeds the exact threshold used by the query."""
        from app.services.grounding.grounding_service import _build_retrieval_metadata

        r1 = self._rag_result(
            "doc_26", distance=0.45, rerank_score=0.9
        )  # conf=0.55 fails 0.62
        r2 = self._rag_result(
            "doc_24", distance=0.30, rerank_score=0.7
        )  # conf=0.70 passes 0.62
        result = _build_retrieval_metadata(self._response([r1, r2], threshold=0.62))

        assert result.reranker_top is not None
        assert result.reranker_top.skip_reason == "failed_embedding_threshold:0.62"


# =============================================================================
# extraction_method label contract
# =============================================================================


class TestExtractionMethodLabels:
    """Verify that extraction_method labels honestly describe the mechanism used."""

    def test_llm_extracted_temperature_reports_llm_extraction_method(
        self, grounding_service
    ):
        service, _, _ = grounding_service
        temp = ExtractedTemperature(value_celsius=4.0)
        value, prov = service._resolve_temperature_value(temp)
        assert prov.extraction_method == "llm_extraction"
        assert prov.source == ValueSource.USER_EXPLICIT

    def test_llm_extracted_duration_reports_llm_extraction_method(
        self, grounding_service
    ):
        service, _, _ = grounding_service
        dur = ExtractedDuration(value_minutes=50400.0)
        value, prov = service._resolve_duration_value(dur)
        assert prov.extraction_method == "llm_extraction"
        assert prov.source == ValueSource.USER_EXPLICIT


# =============================================================================
# Composite-food guard — orchestrator-level (lifted from TaxonomyBridge)
# =============================================================================


class TestCompositeFoodGuardHelper:
    """Unit tests for the _composite_keyword_match helper function."""

    def test_returns_none_for_single_ingredient(self) -> None:
        assert _composite_keyword_match("chicken") is None

    def test_returns_none_for_plain_beef(self) -> None:
        assert _composite_keyword_match("beef") is None

    def test_returns_keyword_for_chicken_soup(self) -> None:
        assert _composite_keyword_match("chicken soup") == "soup"

    def test_returns_keyword_for_beef_stew(self) -> None:
        assert _composite_keyword_match("beef stew") == "stew"

    def test_returns_keyword_for_tuna_salad(self) -> None:
        assert _composite_keyword_match("tuna salad") == "salad"

    # New keywords added 2026-05-08
    def test_chili_is_composite(self) -> None:
        assert _composite_keyword_match("chili") == "chili"

    def test_custard_is_composite(self) -> None:
        assert _composite_keyword_match("custard") == "custard"

    def test_chowder_is_composite(self) -> None:
        assert _composite_keyword_match("chowder") == "chowder"

    def test_gumbo_is_composite(self) -> None:
        assert _composite_keyword_match("gumbo") == "gumbo"

    def test_bisque_is_composite(self) -> None:
        assert _composite_keyword_match("bisque") == "bisque"

    def test_lasagna_is_composite(self) -> None:
        assert _composite_keyword_match("lasagna") == "lasagna"

    def test_lasagne_is_composite(self) -> None:
        assert _composite_keyword_match("lasagne") == "lasagne"

    def test_case_insensitive(self) -> None:
        assert _composite_keyword_match("Chicken Soup") == "soup"

    def test_stir_fry_multiword(self) -> None:
        assert _composite_keyword_match("beef stir fry") == "stir fry"

    def test_stir_fry_hyphenated(self) -> None:
        assert _composite_keyword_match("tofu stir-fry") == "stir-fry"


def _make_no_hit_mock() -> MagicMock:
    """RetrievalResponse returning no confident result."""
    r = MagicMock()
    r.has_confident_result = False
    r.results = []
    r.top_result = None
    r.query = ""
    r.reranker_used = None
    r.threshold = 0.62
    return r


class TestCompositeFoodGuard:
    """Orchestrator-level composite-food guard in _ground_food_properties.

    Migrated from TestCompositeBlocklist (test_taxonomy_bridge.py) and expanded
    to test the new layer: the guard now fires before any retrieval call, not
    only before fuzzy matching inside the bridge.
    """

    @pytest.fixture
    def service_with_mock_retrieval(self) -> tuple[GroundingService, MagicMock]:
        mock_retrieval = MagicMock()
        mock_retrieval.query_food_properties.return_value = _make_no_hit_mock()
        mock_retrieval.query_food_ph.return_value = _make_no_hit_mock()
        mock_retrieval.query_food_water_activity.return_value = _make_no_hit_mock()
        mock_retrieval.query_pathogen_hazards.return_value = _make_no_hit_mock()
        mock_retrieval.get_hazards_for_food.return_value = []
        svc = GroundingService(
            retrieval_service=mock_retrieval,
            llm_client=AsyncMock(),
            use_llm_extraction=False,
            taxonomy_bridge=None,  # bridge not needed for guard tests
        )
        return svc, mock_retrieval

    @pytest.mark.asyncio
    async def test_chicken_soup_ph_not_grounded(
        self, service_with_mock_retrieval: tuple[GroundingService, MagicMock]
    ) -> None:
        svc, _ = service_with_mock_retrieval
        grounded = GroundedValues()
        await svc._ground_food_properties("chicken soup", grounded)
        assert not grounded.has("ph")

    @pytest.mark.asyncio
    async def test_chicken_soup_aw_not_grounded(
        self, service_with_mock_retrieval: tuple[GroundingService, MagicMock]
    ) -> None:
        svc, _ = service_with_mock_retrieval
        grounded = GroundedValues()
        await svc._ground_food_properties("chicken soup", grounded)
        assert not grounded.has("water_activity")

    @pytest.mark.asyncio
    async def test_beef_stew_ph_not_grounded(
        self, service_with_mock_retrieval: tuple[GroundingService, MagicMock]
    ) -> None:
        svc, _ = service_with_mock_retrieval
        grounded = GroundedValues()
        await svc._ground_food_properties("beef stew", grounded)
        assert not grounded.has("ph")

    @pytest.mark.asyncio
    async def test_tuna_salad_ph_not_grounded(
        self, service_with_mock_retrieval: tuple[GroundingService, MagicMock]
    ) -> None:
        svc, _ = service_with_mock_retrieval
        grounded = GroundedValues()
        await svc._ground_food_properties("tuna salad", grounded)
        assert not grounded.has("ph")

    @pytest.mark.asyncio
    async def test_guard_fires_before_any_retrieval_call(
        self, service_with_mock_retrieval: tuple[GroundingService, MagicMock]
    ) -> None:
        """No retrieval method must be called when the composite-food guard fires.

        This verifies ordering (guard before retrieval), not just outcome.
        Equivalent to the old test_composite_blocklist_short_circuits_before_fuzzy
        but at the grounding-service layer.
        """
        svc, mock_retrieval = service_with_mock_retrieval
        grounded = GroundedValues()
        await svc._ground_food_properties("chicken soup", grounded)

        mock_retrieval.query_food_properties.assert_not_called()
        mock_retrieval.query_food_ph.assert_not_called()
        mock_retrieval.query_food_water_activity.assert_not_called()

    @pytest.mark.asyncio
    async def test_plain_chicken_not_blocked(
        self, service_with_mock_retrieval: tuple[GroundingService, MagicMock]
    ) -> None:
        """Plain 'chicken' (no composite keyword) must attempt retrieval normally."""
        svc, mock_retrieval = service_with_mock_retrieval
        grounded = GroundedValues()
        await svc._ground_food_properties("chicken", grounded)

        # Guard did not fire → at least the primary query was attempted
        mock_retrieval.query_food_properties.assert_called_once()

    @pytest.mark.asyncio
    async def test_composite_skip_recorded_for_both_fields(
        self, service_with_mock_retrieval: tuple[GroundingService, MagicMock]
    ) -> None:
        """grounded.composite_skip must name both ph and water_activity after guard fires."""
        svc, _ = service_with_mock_retrieval
        grounded = GroundedValues()
        await svc._ground_food_properties("chicken soup", grounded)

        assert "ph" in grounded.composite_skip
        assert "water_activity" in grounded.composite_skip
        assert grounded.composite_skip["ph"] == "soup"
        assert grounded.composite_skip["water_activity"] == "soup"

    @pytest.mark.asyncio
    async def test_composite_skip_not_set_for_already_grounded_field(
        self, service_with_mock_retrieval: tuple[GroundingService, MagicMock]
    ) -> None:
        """If the user already provided pH explicitly, composite_skip must not record ph."""
        svc, _ = service_with_mock_retrieval
        grounded = GroundedValues()
        grounded.set("ph", 4.5, ValueSource.USER_EXPLICIT)
        await svc._ground_food_properties("chicken soup", grounded)

        assert "ph" not in grounded.composite_skip
        assert "water_activity" in grounded.composite_skip

    # New keyword tests (one per keyword added 2026-05-08)
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "food", ["chili", "custard", "chowder", "gumbo", "bisque", "lasagna", "lasagne"]
    )
    async def test_new_keywords_block_retrieval(
        self, service_with_mock_retrieval: tuple[GroundingService, MagicMock], food: str
    ) -> None:
        """Each newly added composite keyword must block all retrieval calls."""
        svc, mock_retrieval = service_with_mock_retrieval
        grounded = GroundedValues()
        await svc._ground_food_properties(food, grounded)

        assert not grounded.has("ph")
        assert not grounded.has("water_activity")
        assert food in grounded.composite_skip.values()
        mock_retrieval.query_food_properties.assert_not_called()


class TestCompositeFoodDefaultVariant:
    """Smoke tests for the COMPOSITE_FOOD_DEFAULT ValueSource variant."""

    def test_variant_value_string(self) -> None:
        assert ValueSource.COMPOSITE_FOOD_DEFAULT.value == "composite_food_default"

    def test_variant_is_reachable_from_module(self) -> None:
        assert hasattr(ValueSource, "COMPOSITE_FOOD_DEFAULT")

    def test_variant_is_str_comparable(self) -> None:
        assert ValueSource.COMPOSITE_FOOD_DEFAULT == "composite_food_default"


class TestRankExecutableOrganisms:
    """
    A1a: GroundingService.rank_executable_organisms() — the derived option
    set for the organism clarification gate. Ranks a caller-supplied
    executable-organism set by CDC annual death toll, using the same
    pathogen_characteristics.csv table and ComBaseOrganism.from_text()
    mapping _category_pathogen_fallback() uses.
    """

    @staticmethod
    def _service(pathogen_characteristics: dict) -> GroundingService:
        return GroundingService(
            retrieval_service=MagicMock(),
            llm_client=AsyncMock(),
            use_llm_extraction=False,
            pathogen_characteristics=pathogen_characteristics,
        )

    def test_ranks_by_annual_deaths_descending(self) -> None:
        svc = self._service(
            {
                "listeria monocytogenes": (172, "CDC-2019-T1T2"),
                "salmonella nontyphoidal": (238, "CDC-2019-T1T2"),
                "staphylococcus aureus": (6, "CDC-2011-T3"),
            }
        )
        executable = [
            ComBaseOrganism.LISTERIA_MONOCYTOGENES,
            ComBaseOrganism.SALMONELLA,
            ComBaseOrganism.STAPHYLOCOCCUS_AUREUS,
        ]

        ranked = svc.rank_executable_organisms(executable)

        assert ranked == [
            ComBaseOrganism.SALMONELLA,
            ComBaseOrganism.LISTERIA_MONOCYTOGENES,
            ComBaseOrganism.STAPHYLOCOCCUS_AUREUS,
        ]

    def test_excludes_organisms_not_in_executable_set(self) -> None:
        """Present in characteristics but not passed as executable -> excluded."""
        svc = self._service(
            {
                "salmonella nontyphoidal": (238, "CDC-2019-T1T2"),
                "listeria monocytogenes": (172, "CDC-2019-T1T2"),
            }
        )

        ranked = svc.rank_executable_organisms([ComBaseOrganism.SALMONELLA])

        assert ranked == [ComBaseOrganism.SALMONELLA]

    def test_excludes_organisms_absent_from_characteristics(self) -> None:
        """Executable but with no CDC death-toll entry -> excluded, not zero-ranked."""
        svc = self._service({"salmonella nontyphoidal": (238, "CDC-2019-T1T2")})

        ranked = svc.rank_executable_organisms(
            [ComBaseOrganism.SALMONELLA, ComBaseOrganism.PSEUDOMONAS]
        )

        assert ranked == [ComBaseOrganism.SALMONELLA]

    def test_unmappable_characteristics_entries_are_skipped(self) -> None:
        """A characteristics-CSV name with no ComBaseOrganism.from_text() match
        (e.g. Vibrio, not in the organism enum) must not raise or appear."""
        svc = self._service(
            {
                "salmonella nontyphoidal": (238, "CDC-2019-T1T2"),
                "vibrio vulnificus": (36, "CDC-2011-T3"),
            }
        )

        ranked = svc.rank_executable_organisms(
            [ComBaseOrganism.SALMONELLA, ComBaseOrganism.LISTERIA_MONOCYTOGENES]
        )

        assert ranked == [ComBaseOrganism.SALMONELLA]

    def test_empty_executable_set_yields_empty_list(self) -> None:
        svc = self._service({"salmonella nontyphoidal": (238, "CDC-2019-T1T2")})

        assert svc.rank_executable_organisms([]) == []

    def test_derived_against_real_csv_and_registry(self) -> None:
        """
        Deliberately does not hardcode names — recomputes the expected top-N
        independently from the real registry + real pathogen_characteristics.csv
        so this fails if the CSV or registry data changes, per A1a's "derived,
        never hardcoded" requirement.
        """
        from pathlib import Path

        from app.engines.combase.engine import ComBaseEngine
        from app.models.enums import ModelType

        engine = ComBaseEngine()
        csv_path = Path("data/combase_models.csv")
        if not csv_path.exists():
            pytest.skip("ComBase models CSV not available")
        engine.load_models(csv_path)

        svc = GroundingService(
            retrieval_service=MagicMock(),
            llm_client=AsyncMock(),
            use_llm_extraction=False,
        )

        executable = engine.registry.get_executable_organisms(ModelType.GROWTH)
        ranked = svc.rank_executable_organisms(executable)

        # Independently recompute via the same rule the method itself
        # documents: executable ∩ mappable pathogen_characteristics.csv
        # entries, sorted by annual_deaths_us descending.
        executable_set = set(executable)
        expected_scored = []
        for name, (deaths, _source_id) in svc._pathogen_characteristics.items():
            organism = ComBaseOrganism.from_text(name)
            if organism is not None and organism in executable_set:
                expected_scored.append((organism, deaths))
        # Dedup keeping first occurrence, mirroring the method's `seen` set.
        seen = set()
        deduped = []
        for organism, deaths in expected_scored:
            if organism not in seen:
                seen.add(organism)
                deduped.append((organism, deaths))
        deduped.sort(key=lambda pair: pair[1], reverse=True)
        expected = [organism for organism, _ in deduped]

        assert ranked == expected
        assert len(ranked) >= 5, "sanity check: real data should yield >=5 candidates"
