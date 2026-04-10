"""
Model-Agnostic LLM Client

Uses LiteLLM for provider abstraction and Instructor for structured extraction.

Supported providers (via LiteLLM):
- OpenAI: gpt-4o, gpt-4-turbo, gpt-3.5-turbo
- Anthropic: claude-3-opus, claude-3-sonnet, claude-3-haiku
- Ollama (local): ollama/llama2, ollama/mistral
- Azure, Bedrock, Vertex AI, etc.

Usage:
    from app.services.llm.client import get_llm_client
    from pydantic import BaseModel
    
    class MyOutput(BaseModel):
        name: str
        value: int
    
    client = get_llm_client()
    
    # Simple completion
    response = await client.complete("Hello, world!")
    print(response.content)
    
    # Structured extraction
    result = await client.extract(
        response_model=MyOutput,
        messages=[{"role": "user", "content": "Extract: name=test, value=42"}]
    )
    print(result.name, result.value)
"""

from typing import TypeVar, Type, Any

from pydantic import BaseModel

from app.config import settings


# Type variable for generic structured extraction
T = TypeVar("T", bound=BaseModel)


class LLMResponse(BaseModel):
    """Standardized LLM response wrapper."""
    content: str
    model: str
    usage: dict[str, int] | None = None


class LLMClient:
    """
    LLM client using LiteLLM + Instructor.
    
    Supports multiple providers through LiteLLM's unified interface.
    Uses Instructor for structured extraction with Pydantic models.
    """
    
    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        instructor_mode: str | None = None,
    ):
        """
        Initialize the LLM client.
        
        Args:
            model: Model identifier (default: from settings)
            api_key: API key (default: from settings)
            api_base: Base URL override (default: from settings)
            temperature: Generation temperature (default: from settings)
            max_tokens: Max tokens in response (default: from settings)
            instructor_mode: How Instructor extracts structured data.
                None or "TOOLS" — uses the LLM's native function/tool-calling
                    API. Most reliable for frontier models (OpenAI, Anthropic)
                    that were specifically trained for tool use.
                "JSON" — puts the Pydantic schema in the prompt and asks
                    the LLM to respond with matching JSON. Works with local
                    models (Ollama) that don't support tool calls.
                See: https://python.useinstructor.com/concepts/modes/
        """
        self.model = model or settings.llm_model
        self.api_key = api_key or settings.llm_api_key
        self.api_base = api_base or settings.llm_api_base
        self.temperature = temperature if temperature is not None else settings.llm_temperature
        self.max_tokens = max_tokens or settings.llm_max_tokens
        self.instructor_mode = instructor_mode
    
    async def complete(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """
        Generate a completion for the given prompt.
        
        Args:
            prompt: User message
            system_prompt: Optional system message
            temperature: Override default temperature
            max_tokens: Override default max tokens
            
        Returns:
            LLMResponse with generated content
        """
        from litellm import acompletion
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        response = await acompletion(
            model=self.model,
            messages=messages,
            temperature=temperature if temperature is not None else self.temperature,
            max_tokens=max_tokens or self.max_tokens,
            api_key=self.api_key,
            api_base=self.api_base,
        )
        
        return LLMResponse(
            content=response.choices[0].message.content,
            model=response.model,
            usage={
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
            } if response.usage else None,
        )
    
    async def extract(
        self,
        response_model: Type[T],
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> T:
        """
        Extract structured data from messages using Instructor.
        
        The extraction mode is determined by self.instructor_mode (set in __init__):
        
        - TOOLS mode (default): The LLM uses its native function-calling API.
          Instructor sends the Pydantic schema as a tool definition and the
          LLM responds with a tool call whose arguments match the schema.
          This is the most reliable mode for frontier models (OpenAI, Anthropic)
          because they were specifically fine-tuned for tool use.
        
        - JSON mode: Instructor embeds the Pydantic schema in the system prompt
          and instructs the LLM to respond with JSON matching that schema.
          No tool calls involved — just constrained text generation.
          This works with local models (e.g., Ollama) that don't support
          tool calls, at the cost of slightly lower extraction reliability.
        
        Both modes validate the output against the Pydantic schema and retry
        on validation errors (up to Instructor's default max_retries).
        
        Args:
            response_model: Pydantic model class to extract
            messages: List of message dicts with 'role' and 'content'
            system_prompt: Optional system message
            temperature: Override default temperature
            max_tokens: Override default max tokens
            
        Returns:
            Instance of response_model populated with extracted data
        """
        import instructor
        from litellm import acompletion
        
        # Select Instructor mode based on client configuration.
        # - None or "TOOLS": use function/tool calling (default, best for API providers)
        # - "JSON": use JSON-in-prompt (required for most local/Ollama models)
        if self.instructor_mode and self.instructor_mode.upper() == "JSON":
            mode = instructor.Mode.JSON
        else:
            mode = instructor.Mode.TOOLS
        
        client = instructor.from_litellm(acompletion, mode=mode)
        
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)
        
        return await client.chat.completions.create(
            model=self.model,
            response_model=response_model,
            messages=full_messages,
            temperature=temperature if temperature is not None else self.temperature,
            max_tokens=max_tokens or self.max_tokens,
            api_key=self.api_key,
            api_base=self.api_base,
        )
    
    async def health_check(self) -> dict[str, Any]:
        """
        Check if the LLM API is reachable.
        
        Returns:
            Dict with 'healthy' bool and 'message'
        """
        if not self.api_key:
            return {
                "healthy": False,
                "message": "No API key configured",
                "model": self.model,
            }
        
        try:
            response = await self.complete(
                prompt="Respond with only: ok",
                max_tokens=10,
            )
            return {
                "healthy": True,
                "message": "API connection successful",
                "model": self.model,
            }
        except Exception as e:
            return {
                "healthy": False,
                "message": f"API error: {str(e)}",
                "model": self.model,
            }


# =============================================================================
# SINGLETON
# =============================================================================

_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """
    Get the LLM client singleton instance.
    
    Returns:
        LLMClient instance configured from settings
    """
    global _client
    if _client is None:
        _client = LLMClient()
    return _client


def reset_llm_client() -> None:
    """Reset the singleton (useful for testing)."""
    global _client
    _client = None