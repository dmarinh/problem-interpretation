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

from typing import Any, TypeVar

from pydantic import BaseModel

from app.config import settings
from app.services.llm.exceptions import (
    LLMAuthenticationError,
    LLMCreditExhaustedError,
    LLMRateLimitError,
    LLMServiceUnavailableError,
)


def _raise_as_provider_error(exc: Exception) -> None:
    """Map a LiteLLM exception to the appropriate LLMProviderError subclass.

    Instructor wraps the original LiteLLM exception inside its own retry
    exception after exhausting retries (InstructorRetryException).  We walk
    the exception chain so the LiteLLM cause is found even when wrapped.
    """
    import litellm

    _LITELLM_TYPES = (
        litellm.AuthenticationError,
        litellm.BudgetExceededError,
        litellm.RateLimitError,
        litellm.NotFoundError,
        litellm.ServiceUnavailableError,
        litellm.APIConnectionError,
        litellm.InternalServerError,
    )

    # Walk __cause__ / __context__ chain to find the deepest LiteLLM exception.
    candidate: Exception | None = exc
    litellm_exc: Exception | None = None
    seen: set[int] = set()
    while candidate is not None and id(candidate) not in seen:
        seen.add(id(candidate))
        if isinstance(candidate, _LITELLM_TYPES):
            litellm_exc = candidate
            break
        candidate = candidate.__cause__ or candidate.__context__  # type: ignore[assignment]

    if litellm_exc is None:
        return  # Not a recognised provider error; let it propagate as-is.

    # LiteLLM's __str__ prepends "litellm.ClassName: " — strip it so the detail
    # field that reaches the client isn't redundantly prefixed.
    raw = str(litellm_exc)
    provider_msg = raw.split(": ", 1)[1] if raw.startswith("litellm.") else raw

    if isinstance(litellm_exc, litellm.AuthenticationError):
        raise LLMAuthenticationError(
            f"LLM authentication failed: {provider_msg}", litellm_exc
        )
    if isinstance(litellm_exc, litellm.BudgetExceededError):
        raise LLMCreditExhaustedError(
            f"LLM account budget exceeded: {provider_msg}", litellm_exc
        )
    if isinstance(litellm_exc, litellm.RateLimitError):
        # OpenAI returns HTTP 429 for both rate limiting and credit exhaustion;
        # distinguish by message content.
        lowered = provider_msg.lower()
        if any(
            k in lowered
            for k in ("insufficient_quota", "quota", "billing", "exceeded your current")
        ):
            raise LLMCreditExhaustedError(
                f"LLM account credit exhausted: {provider_msg}", litellm_exc
            )
        raise LLMRateLimitError(f"LLM rate limit reached: {provider_msg}", litellm_exc)
    if isinstance(litellm_exc, litellm.NotFoundError):
        raise LLMServiceUnavailableError(
            f"LLM API returned 404 — check LLM_API_BASE and LLM_MODEL in your configuration. "
            f"Provider detail: {provider_msg}",
            litellm_exc,
        )
    if isinstance(
        litellm_exc,
        (
            litellm.ServiceUnavailableError,
            litellm.APIConnectionError,
            litellm.InternalServerError,
        ),
    ):
        raise LLMServiceUnavailableError(
            f"LLM service unavailable: {provider_msg}", litellm_exc
        )


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
        extra_params: dict | None = None,
        drop_params: bool = False,
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
            extra_params: Provider-specific parameters forwarded verbatim to
                every LiteLLM call. Examples: {"thinking": {"type": "disabled"}}
                for Anthropic, {"reasoning_effort": "none"} for OpenAI o-series,
                {"thinking_config": {"thinking_budget": 0}} for Gemini.
            drop_params: When True, omit ``temperature`` from every API call.
                Use for models that have deprecated or disallowed temperature
                (e.g. claude-opus-4-7, GPT-5.5, o-series). LiteLLM's global
                drop_params flag handles provider-level unknowns; this flag
                handles model-level deprecations that LiteLLM doesn't track.
        """
        self.model = model or settings.llm_model
        self.api_key = api_key or settings.llm_api_key
        self.api_base = api_base or settings.llm_api_base
        self.temperature = (
            temperature if temperature is not None else settings.llm_temperature
        )
        self.max_tokens = max_tokens or settings.llm_max_tokens
        self.instructor_mode = instructor_mode or settings.llm_instructor_mode
        self.extra_params: dict = extra_params or {}
        self.drop_params: bool = drop_params

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

        call_kwargs: dict = dict(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens or self.max_tokens,
            api_key=self.api_key,
            api_base=self.api_base,
            **self.extra_params,
        )
        if not self.drop_params:
            call_kwargs["temperature"] = (
                temperature if temperature is not None else self.temperature
            )
        try:
            response = await acompletion(**call_kwargs)
        except Exception as exc:
            _raise_as_provider_error(exc)
            raise

        return LLMResponse(
            content=response.choices[0].message.content,
            model=response.model,
            usage=(
                {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                }
                if response.usage
                else None
            ),
        )

    async def extract(
        self,
        response_model: type[T],
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

        call_kwargs: dict = dict(
            model=self.model,
            response_model=response_model,
            messages=full_messages,
            max_tokens=max_tokens or self.max_tokens,
            api_key=self.api_key,
            api_base=self.api_base,
            **self.extra_params,
        )
        if not self.drop_params:
            call_kwargs["temperature"] = (
                temperature if temperature is not None else self.temperature
            )
        try:
            return await client.chat.completions.create(**call_kwargs)
        except Exception as exc:
            _raise_as_provider_error(exc)
            raise

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
            await self.complete(
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
