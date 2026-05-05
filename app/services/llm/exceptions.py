"""
LLM provider error hierarchy.

LiteLLM exceptions are caught at the client boundary and re-raised as these
typed exceptions so callers can map them to appropriate HTTP status codes
without importing LiteLLM types outside the client module.
"""


class LLMProviderError(Exception):
    """Base class for errors that originate from the upstream LLM provider."""

    http_status: int = 500
    user_message: str = "LLM provider error"

    def __init__(self, user_message: str, original: Exception | None = None):
        self.user_message = user_message
        self.original = original
        super().__init__(user_message)


class LLMRateLimitError(LLMProviderError):
    """Provider is throttling requests (HTTP 429, rate limit)."""

    http_status = 429


class LLMCreditExhaustedError(LLMProviderError):
    """Account quota or billing limit reached (HTTP 402)."""

    http_status = 402


class LLMAuthenticationError(LLMProviderError):
    """Invalid or missing API key (HTTP 401)."""

    http_status = 401


class LLMServiceUnavailableError(LLMProviderError):
    """Provider is unreachable or returned a server error (HTTP 503)."""

    http_status = 503
