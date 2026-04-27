"""
Unit tests for grounding service.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.grounding.grounding_service import (
    GroundingService,
    GroundedValues,
    ExtractedNumericValue,
    get_grounding_service,
    reset_grounding_service,
)
from app.models.enums import ComBaseOrganism, RetrievalConfidenceLevel
from app.models.extraction import (
    ExtractedScenario,
    ExtractedTemperature,
    ExtractedDuration,
    ExtractedEnvironmentalConditions,
    ExtractedFoodProperties,
)
from app.models.metadata import ValueSource

from app.models.enums import ComBaseOrganism, RetrievalConfidenceLevel, ModelType


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
        grounded.set("ph", 6.0, ValueSource.USER_EXPLICIT, 0.95)
        
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
            confidence=0.85,
            retrieval_source="doc_123",
        )
        
        assert "ph" in grounded.provenance
        assert grounded.provenance["ph"].source == ValueSource.RAG_RETRIEVAL
        assert grounded.provenance["ph"].confidence == 0.85
    
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
            "water activity 0.99",
            ["water activity", "aw"]
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
        rag_content = "chicken (poultry): pH range 6.5 to 6.7. Raw chicken [FDA-PH-2007]"
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
            "aw category is high, but nothing quantified here: ref 200", ["water activity", "aw"]
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
        rag_content = "chicken (poultry): pH range 6.5 to 6.7. Raw chicken [FDA-PH-2007]"
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
        mock_llm.extract = AsyncMock(return_value=ExtractedFoodProperties(
            aw_value=0.97,
            extraction_method="llm",
        ))
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
        assert grounded.provenance["ph"].confidence == 0.90
    
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
        service._ground_temperature(scenario, grounded, ModelType.GROWTH)
        
        assert grounded.get("temperature_celsius") == 25.0
        assert grounded.provenance["temperature_celsius"].source == ValueSource.USER_EXPLICIT
    
    def test_ground_temperature_range_uses_upper(self, grounding_service):
        """Should use upper bound of temperature range."""
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
        service._ground_temperature(scenario, grounded, ModelType.GROWTH)
        
        assert grounded.get("temperature_celsius") == 25.0
        assert grounded.provenance["temperature_celsius"].source == ValueSource.USER_INFERRED
    
    def test_ground_temperature_description(self, grounding_service):
        """Should interpret temperature description."""
        service, _, _ = grounding_service
        grounded = GroundedValues()
        
        scenario = ExtractedScenario(
            single_step_temperature=ExtractedTemperature(description="room temperature"),
            single_step_duration=ExtractedDuration(value_minutes=60.0),
        )
        service._ground_temperature(scenario, grounded, ModelType.GROWTH)
        
        assert grounded.get("temperature_celsius") == 25.0
        assert grounded.provenance["temperature_celsius"].source == ValueSource.USER_INFERRED
    
    def test_unknown_description_marks_ungrounded(self, grounding_service):
        """Should mark ungrounded for unknown description."""
        service, _, _ = grounding_service
        grounded = GroundedValues()
        
        scenario = ExtractedScenario(
            single_step_temperature=ExtractedTemperature(description="xyz123"),
            single_step_duration=ExtractedDuration(value_minutes=60.0),
        )
        service._ground_temperature(scenario, grounded, ModelType.GROWTH)
        
        assert not grounded.has("temperature_celsius")
        assert "temperature_celsius" in grounded.ungrounded_fields


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
        service._ground_duration(scenario, grounded, ModelType.GROWTH)
        
        assert grounded.get("duration_minutes") == 180.0
        assert grounded.provenance["duration_minutes"].source == ValueSource.USER_EXPLICIT
    
    def test_ground_duration_range_uses_upper(self, grounding_service):
        """Should use upper bound of duration range."""
        service, _, _ = grounding_service
        grounded = GroundedValues()
        
        scenario = ExtractedScenario(
            single_step_temperature=ExtractedTemperature(value_celsius=25.0),
            single_step_duration=ExtractedDuration(
                range_min_minutes=60.0,
                range_max_minutes=120.0,
            ),
        )
        service._ground_duration(scenario, grounded, ModelType.GROWTH)
        
        assert grounded.get("duration_minutes") == 120.0
    
    def test_ground_duration_description(self, grounding_service):
        """Should interpret duration description."""
        service, _, _ = grounding_service
        grounded = GroundedValues()
        
        scenario = ExtractedScenario(
            single_step_temperature=ExtractedTemperature(value_celsius=25.0),
            single_step_duration=ExtractedDuration(description="overnight"),
        )
        service._ground_duration(scenario, grounded, ModelType.GROWTH)
        
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
        mock_food_response.results = [MagicMock(
            confidence=0.9,
            confidence_level=RetrievalConfidenceLevel.HIGH,
            content="pH 5.5, water activity 0.95",
            source="doc_1",
            doc_id="doc_1",
        )]
        mock_food_response.top_result = mock_food_response.results[0]
        mock_retrieval.query_food_properties.return_value = mock_food_response
        
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
        
        grounded = await service.ground_scenario(scenario)
        
        # RAG for food properties should not be called
        mock_retrieval.query_food_properties.assert_not_called()
        
        # RAG for pathogen should not be called (user provided it)
        mock_retrieval.query_pathogen_hazards.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_explicit_pathogen_grounded(self, grounding_service):
        """Explicit pathogen mention should be grounded."""
        service, mock_retrieval, _ = grounding_service
        
        # Mock food properties (will be called since pH/aw not provided)
        mock_food_response = MagicMock()
        mock_food_response.has_confident_result = False
        mock_food_response.results = []
        mock_retrieval.query_food_properties.return_value = mock_food_response
    
        scenario = ExtractedScenario(
            food_description="chicken",
            pathogen_mentioned="Salmonella",
            single_step_temperature=ExtractedTemperature(value_celsius=25.0),
            single_step_duration=ExtractedDuration(value_minutes=180.0),
        )
    
        grounded = await service.ground_scenario(scenario)
    
        assert grounded.get("organism") == ComBaseOrganism.SALMONELLA
        assert grounded.provenance["organism"].source == ValueSource.USER_EXPLICIT


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
