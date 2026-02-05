"""
LLM client services.

Provides a model-agnostic interface for LLM interactions using LiteLLM + Instructor.
"""

from app.services.llm.client import (
    LLMClient,
    get_llm_client,
)

__all__ = [
    "LLMClient",
    "get_llm_client",
]