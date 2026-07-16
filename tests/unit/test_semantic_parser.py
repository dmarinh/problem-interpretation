"""
Unit tests for semantic parser.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.extraction import (
    ExtractedClarificationResponse,
    ExtractedDuration,
    ExtractedIntent,
    ExtractedScenario,
    ExtractedTemperature,
)
from app.services.extraction.semantic_parser import (
    SemanticParser,
    get_semantic_parser,
    reset_semantic_parser,
)


class TestSemanticParser:
    """Tests for SemanticParser class."""

    @pytest.fixture
    def mock_llm_client(self):
        """Create a mock LLM client."""
        client = MagicMock()
        client.extract = AsyncMock()
        return client

    @pytest.fixture
    def parser(self, mock_llm_client):
        """Create parser with mock client."""
        return SemanticParser(llm_client=mock_llm_client)

    @pytest.mark.asyncio
    async def test_extract_scenario_calls_llm(self, parser, mock_llm_client):
        """extract_scenario should call LLM with correct model."""
        mock_llm_client.extract.return_value = ExtractedScenario(
            food_description="raw chicken"
        )

        result = await parser.extract_scenario("Raw chicken left out")

        mock_llm_client.extract.assert_called_once()
        call_kwargs = mock_llm_client.extract.call_args.kwargs
        assert call_kwargs["response_model"] == ExtractedScenario

    @pytest.mark.asyncio
    async def test_extract_scenario_returns_model(self, parser, mock_llm_client):
        """extract_scenario should return ExtractedScenario."""
        expected = ExtractedScenario(
            food_description="raw chicken",
            single_step_temperature=ExtractedTemperature(value_celsius=25.0),
            single_step_duration=ExtractedDuration(value_minutes=180.0),
        )
        mock_llm_client.extract.return_value = expected

        result = await parser.extract_scenario("Raw chicken at 25C for 3 hours")

        assert result.food_description == "raw chicken"
        assert result.single_step_temperature.value_celsius == 25.0
        assert result.single_step_duration.value_minutes == 180.0

    @pytest.mark.asyncio
    async def test_extract_scenario_with_context(self, parser, mock_llm_client):
        """extract_scenario should include conversation context."""
        mock_llm_client.extract.return_value = ExtractedScenario()

        await parser.extract_scenario(
            "It was about 25 degrees",
            conversation_context="User mentioned raw chicken earlier",
        )

        call_kwargs = mock_llm_client.extract.call_args.kwargs
        messages = call_kwargs["messages"]
        user_message = messages[-1]["content"]
        assert "Previous context" in user_message
        assert "raw chicken earlier" in user_message

    @pytest.mark.asyncio
    async def test_classify_intent_prediction_request(self, parser, mock_llm_client):
        """classify_intent should identify prediction requests."""
        mock_llm_client.extract.return_value = ExtractedIntent(
            is_prediction_request=True,
            is_information_query=False,
            confidence=0.95,
        )

        result = await parser.classify_intent("Is my chicken still safe to eat?")

        assert result.is_prediction_request is True
        assert result.is_information_query is False

    @pytest.mark.asyncio
    async def test_classify_intent_information_query(self, parser, mock_llm_client):
        """classify_intent should identify information queries."""
        mock_llm_client.extract.return_value = ExtractedIntent(
            is_prediction_request=False,
            is_information_query=True,
            confidence=0.90,
        )

        result = await parser.classify_intent("What temperature kills salmonella?")

        assert result.is_prediction_request is False
        assert result.is_information_query is True

    @pytest.mark.asyncio
    async def test_extract_clarification_response(self, parser, mock_llm_client):
        """extract_clarification_response should extract user's answer."""
        mock_llm_client.extract.return_value = ExtractedClarificationResponse(
            understood_value="3 hours",
            selected_option=None,
            wants_to_skip=False,
        )

        result = await parser.extract_clarification_response(
            user_response="It was about 3 hours",
            original_question="How long was the food left out?",
        )

        assert result.understood_value == "3 hours"
        assert result.wants_to_skip is False

    @pytest.mark.asyncio
    async def test_extract_clarification_with_options(self, parser, mock_llm_client):
        """extract_clarification_response should handle option selection."""
        mock_llm_client.extract.return_value = ExtractedClarificationResponse(
            selected_option="2-4 hours",
            wants_to_skip=False,
        )

        result = await parser.extract_clarification_response(
            user_response="The second one",
            original_question="How long was the food left out?",
            options=["Less than 2 hours", "2-4 hours", "More than 4 hours"],
        )

        assert result.selected_option == "2-4 hours"


class TestScenarioExtractionPromptRanges:
    """Verify SCENARIO_EXTRACTION_PROMPT instructs pH and aw range extraction."""

    def test_prompt_instructs_ph_range_extraction(self):
        """Prompt must direct the LLM to use ph_min/ph_max for pH range inputs."""
        from app.services.extraction.semantic_parser import SCENARIO_EXTRACTION_PROMPT

        assert "ph_min" in SCENARIO_EXTRACTION_PROMPT
        assert "ph_max" in SCENARIO_EXTRACTION_PROMPT

    def test_prompt_instructs_aw_range_extraction(self):
        """Prompt must direct the LLM to use water_activity_min/max for aw range inputs."""
        from app.services.extraction.semantic_parser import SCENARIO_EXTRACTION_PROMPT

        assert "water_activity_min" in SCENARIO_EXTRACTION_PROMPT
        assert "water_activity_max" in SCENARIO_EXTRACTION_PROMPT

    @pytest.mark.asyncio
    async def test_parser_passes_through_ph_range(self):
        """Parser passes an LLM-returned ph_min/ph_max through to ExtractedScenario."""
        from app.models.extraction import ExtractedEnvironmentalConditions
        from app.services.extraction.semantic_parser import SemanticParser

        mock_client = MagicMock()
        mock_client.extract = AsyncMock(
            return_value=ExtractedScenario(
                food_description="white bread",
                environmental_conditions=ExtractedEnvironmentalConditions(
                    ph_min=5.5,
                    ph_max=6.0,
                ),
            )
        )
        parser = SemanticParser(llm_client=mock_client)

        result = await parser.extract_scenario(
            "Predict B. cereus growth on white bread at pH 5.5-6.0, 25°C, for 4 hours."
        )

        assert result.environmental_conditions.ph_min == 5.5
        assert result.environmental_conditions.ph_max == 6.0
        assert result.environmental_conditions.ph_value is None


class TestFoodDescriptionQualifierStripping:
    """Verify SCENARIO_EXTRACTION_PROMPT instructs the LLM to strip quantity/container qualifiers."""

    # ------------------------------------------------------------------
    # Prompt-inspection tests
    # ------------------------------------------------------------------

    def test_prompt_contains_qualifier_stripping_rule(self):
        """Prompt must contain the core qualifier-stripping instruction."""
        from app.services.extraction.semantic_parser import SCENARIO_EXTRACTION_PROMPT

        assert "Strip leading quantity, container, and" in SCENARIO_EXTRACTION_PROMPT

    def test_prompt_contains_all_six_examples(self):
        """All six worked examples must be present in the prompt."""
        from app.services.extraction.semantic_parser import SCENARIO_EXTRACTION_PROMPT

        assert '"a large batch of ham"' in SCENARIO_EXTRACTION_PROMPT
        assert '"two pounds of ground beef"' in SCENARIO_EXTRACTION_PROMPT
        assert '"a jar of peanut butter"' in SCENARIO_EXTRACTION_PROMPT
        assert '"leftover chicken soup"' in SCENARIO_EXTRACTION_PROMPT
        assert '"raw chicken breast"' in SCENARIO_EXTRACTION_PROMPT
        assert '"smoked salmon fillet"' in SCENARIO_EXTRACTION_PROMPT

    # ------------------------------------------------------------------
    # Parser pass-through tests (mock LLM returns the cleaned value)
    # ------------------------------------------------------------------

    def _make_parser(self, food_description: str) -> "SemanticParser":
        mock_client = MagicMock()
        mock_client.extract = AsyncMock(
            return_value=ExtractedScenario(
                food_description=food_description,
            )
        )
        return SemanticParser(llm_client=mock_client)

    @pytest.mark.asyncio
    async def test_batch_qualifier_stripped_to_ham(self):
        """'a large batch of ham' → food_description='ham'."""
        parser = self._make_parser("ham")
        result = await parser.extract_scenario(
            "a large batch of ham left to cool overnight"
        )
        assert result.food_description == "ham"

    @pytest.mark.asyncio
    async def test_weight_qualifier_stripped_to_ground_beef(self):
        """'two pounds of ground beef' → food_description='ground beef'."""
        parser = self._make_parser("ground beef")
        result = await parser.extract_scenario(
            "two pounds of ground beef at 25°C for 3 hours"
        )
        assert result.food_description == "ground beef"

    @pytest.mark.asyncio
    async def test_container_qualifier_stripped_to_peanut_butter(self):
        """'a jar of peanut butter' → food_description='peanut butter'."""
        parser = self._make_parser("peanut butter")
        result = await parser.extract_scenario(
            "a jar of peanut butter left on the counter"
        )
        assert result.food_description == "peanut butter"

    @pytest.mark.asyncio
    async def test_leftover_qualifier_stripped_to_chicken_soup(self):
        """'leftover chicken soup' → food_description='chicken soup'."""
        parser = self._make_parser("chicken soup")
        result = await parser.extract_scenario("leftover chicken soup sitting at 20°C")
        assert result.food_description == "chicken soup"

    @pytest.mark.asyncio
    async def test_raw_adjective_preserved_in_chicken_breast(self):
        """'raw chicken breast' → food_description='raw chicken breast' (raw kept)."""
        parser = self._make_parser("raw chicken breast")
        result = await parser.extract_scenario("raw chicken breast at 25°C for 2 hours")
        assert result.food_description == "raw chicken breast"

    @pytest.mark.asyncio
    async def test_smoked_adjective_preserved_cut_stripped_in_salmon(self):
        """'smoked salmon fillet' → food_description='smoked salmon' (smoked kept, fillet dropped)."""
        parser = self._make_parser("smoked salmon")
        result = await parser.extract_scenario(
            "smoked salmon fillet left out for 1 hour"
        )
        assert result.food_description == "smoked salmon"

    # ------------------------------------------------------------------
    # Negative cases
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_bare_food_name_unchanged(self):
        """A food name without any qualifier passes through unchanged."""
        parser = self._make_parser("chicken")
        result = await parser.extract_scenario("chicken at 25°C for 3 hours")
        assert result.food_description == "chicken"

    @pytest.mark.asyncio
    async def test_food_state_adjective_preserved(self):
        """Adjectives describing food state (cooked, cured) must not be stripped."""
        parser = self._make_parser("cooked ham")
        result = await parser.extract_scenario(
            "cooked ham left at room temperature for 4 hours"
        )
        assert result.food_description == "cooked ham"


class TestSemanticParserSingleton:
    """Tests for singleton management."""

    def test_get_semantic_parser_returns_instance(self):
        """get_semantic_parser should return a parser."""
        reset_semantic_parser()
        parser = get_semantic_parser()

        assert isinstance(parser, SemanticParser)

    def test_get_semantic_parser_returns_same_instance(self):
        """get_semantic_parser should return singleton."""
        reset_semantic_parser()
        parser1 = get_semantic_parser()
        parser2 = get_semantic_parser()

        assert parser1 is parser2

    def test_reset_clears_singleton(self):
        """reset_semantic_parser should clear the singleton."""
        reset_semantic_parser()
        parser1 = get_semantic_parser()
        reset_semantic_parser()
        parser2 = get_semantic_parser()

        assert parser1 is not parser2
