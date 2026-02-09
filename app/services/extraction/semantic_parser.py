"""
Semantic Parser

Uses Instructor to extract structured information from user input.
This is the bridge between free-text user input and typed extraction models.

Design Principles:
- Single responsibility: only extracts, does not validate or standardize
- Returns extraction models, not engine payloads
- Handles extraction failures gracefully
- Supports both single-step and multi-step scenarios
"""

from typing import TypeVar

from pydantic import BaseModel

from app.config import settings
from app.services.llm.client import LLMClient, get_llm_client
from app.models.extraction import (
    ExtractedScenario,
    ExtractedIntent,
    ExtractedClarificationResponse,
)


T = TypeVar("T", bound=BaseModel)


# =============================================================================
# SYSTEM PROMPTS
# =============================================================================

SCENARIO_EXTRACTION_PROMPT = """You are a food safety expert assistant. Your task is to extract structured information from a user's description of a food safety scenario.

Extract the following information if present:
- Food item description (what food is involved)
- Food state (raw, cooked, frozen, thawed, etc.)
- Pathogen if explicitly mentioned
- Temperature information (explicit values or descriptions like "room temperature")
- Duration information (explicit values or descriptions like "a few hours")
- Environmental conditions (pH, salt content, atmosphere, etc.)
- Whether this is a multi-step scenario (e.g., transport then storage)
- What the user is concerned about (safety, spoilage, shelf life)

Important guidelines:
- Only extract what is explicitly stated or clearly implied
- Do not invent or assume values not mentioned
- If a range is given (e.g., "20-25C"), capture it as a range
- If time/temperature is ambiguous (e.g., "a while"), mark it as ambiguous
- Convert all temperatures to Celsius
- Convert all durations to minutes
- For multi-step scenarios, capture each step in sequence order
"""

INTENT_CLASSIFICATION_PROMPT = """You are a food safety expert assistant. Classify the user's intent.

A PREDICTION REQUEST is when the user:
- Wants to know if food is safe to eat
- Asks about microbial growth or contamination risk
- Describes a scenario and wants a safety assessment
- Asks about shelf life or how long food can be kept

An INFORMATION QUERY is when the user:
- Asks general questions about food safety
- Wants to know about pathogens or foodborne illness
- Asks about food safety guidelines or regulations
- Wants educational information, not a specific prediction

If the intent is unclear or could be either, mark requires_clarification as true.
"""

CLARIFICATION_RESPONSE_PROMPT = """You are a food safety expert assistant. The user is responding to a clarification question.

Extract:
- The specific value or information they provided
- If they selected from given options, which option
- If they want to skip the question and use defaults
- Any additional context they provided
"""


# =============================================================================
# SEMANTIC PARSER
# =============================================================================

class SemanticParser:
    """
    Extracts structured information from user input using LLM + Instructor.
    
    Usage:
        parser = SemanticParser()
        scenario = await parser.extract_scenario("Raw chicken left out for 3 hours")
        intent = await parser.classify_intent("Is my chicken still safe to eat?")
    """
    
    def __init__(self, llm_client: LLMClient | None = None):
        """
        Initialize the semantic parser.
        
        Args:
            llm_client: Optional LLM client. If not provided, uses the global client.
        """
        self._client = llm_client or get_llm_client()
    
    async def extract_scenario(
        self,
        user_input: str,
        conversation_context: str | None = None,
    ) -> ExtractedScenario:
        """
        Extract a food safety scenario from user input.
        
        Args:
            user_input: The user's description of their food safety scenario
            conversation_context: Optional previous conversation for context
        
        Returns:
            ExtractedScenario with all extracted information
        """
        messages = [
            {"role": "system", "content": SCENARIO_EXTRACTION_PROMPT},
        ]
        
        if conversation_context:
            messages.append({
                "role": "user",
                "content": f"Previous context:\n{conversation_context}\n\nCurrent input:\n{user_input}"
            })
        else:
            messages.append({"role": "user", "content": user_input})
        
        result = await self._client.extract(
            response_model=ExtractedScenario,
            messages=messages,
        )
        
        return result
    
    async def classify_intent(
        self,
        user_input: str,
    ) -> ExtractedIntent:
        """
        Classify the user's intent.
        
        Args:
            user_input: The user's message
        
        Returns:
            ExtractedIntent with classification
        """
        messages = [
            {"role": "system", "content": INTENT_CLASSIFICATION_PROMPT},
            {"role": "user", "content": user_input},
        ]
        
        result = await self._client.extract(
            response_model=ExtractedIntent,
            messages=messages,
        )
        
        return result
    
    async def extract_clarification_response(
        self,
        user_response: str,
        original_question: str,
        options: list[str] | None = None,
    ) -> ExtractedClarificationResponse:
        """
        Extract information from user's response to a clarification question.
        
        Args:
            user_response: The user's response
            original_question: The clarification question that was asked
            options: The options that were provided (if any)
        
        Returns:
            ExtractedClarificationResponse with extracted information
        """
        context = f"Original question: {original_question}"
        if options:
            context += f"\nOptions provided: {', '.join(options)}"
        
        messages = [
            {"role": "system", "content": CLARIFICATION_RESPONSE_PROMPT},
            {"role": "user", "content": f"{context}\n\nUser response: {user_response}"},
        ]
        
        result = await self._client.extract(
            response_model=ExtractedClarificationResponse,
            messages=messages,
        )
        
        return result
    
    async def extract_generic(
        self,
        response_model: type[T],
        user_input: str,
        system_prompt: str,
    ) -> T:
        """
        Generic extraction for custom models.
        
        Args:
            response_model: The Pydantic model to extract into
            user_input: The user's input
            system_prompt: The system prompt for extraction
        
        Returns:
            Instance of response_model with extracted data
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ]
        
        result = await self._client.extract(
            response_model=response_model,
            messages=messages,
        )
        
        return result


# =============================================================================
# SINGLETON
# =============================================================================

_parser: SemanticParser | None = None


def get_semantic_parser() -> SemanticParser:
    """Get or create the global SemanticParser instance."""
    global _parser
    if _parser is None:
        _parser = SemanticParser()
    return _parser


def reset_semantic_parser() -> None:
    """Reset the global parser (for testing)."""
    global _parser
    _parser = None