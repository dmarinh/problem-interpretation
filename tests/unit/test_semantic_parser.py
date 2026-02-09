"""
Unit tests for semantic parser.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.extraction.semantic_parser import (
    SemanticParser,
    get_semantic_parser,
    reset_semantic_parser,
)
from app.models.extraction import (
    ExtractedScenario,
    ExtractedTemperature,
    ExtractedDuration,
    ExtractedIntent,
    ExtractedClarificationResponse,
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
            conversation_context="User mentioned raw chicken earlier"
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