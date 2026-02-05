"""
Simple manual LLM test.

Usage:
    python scripts/test_llm_manual.py
"""

import asyncio
from pydantic import BaseModel, Field


class FoodExtraction(BaseModel):
    """Test extraction model."""
    food: str | None = Field(default=None, description="Food item mentioned")
    temperature_c: float | None = Field(default=None, description="Temperature in Celsius")
    duration_minutes: float | None = Field(default=None, description="Duration in minutes")


async def main():
    # Load settings from .env
    from app.config import settings
    from litellm import acompletion
    import instructor
    
    print(f"Model: {settings.llm_model}")
    print(f"API Key Set: {settings.llm_api_key is not None}")
    print()
    
    # Test 1: Simple completion
    print("--- Test 1: Simple Completion ---")
    response = await acompletion(
        model=settings.llm_model,
        messages=[{"role": "user", "content": "Say hello in 5 words or less"}],
        api_key=settings.llm_api_key,
        max_tokens=50,
    )
    print(f"Response: {response.choices[0].message.content}")
    print()
    
    # Test 2: Structured extraction
    print("--- Test 2: Structured Extraction ---")
    client = instructor.from_litellm(acompletion)
    
    test_input = "Raw chicken left at 25°C for 3 hours"
    print(f"Input: {test_input}")
    
    result = await client.chat.completions.create(
        model=settings.llm_model,
        response_model=FoodExtraction,
        messages=[{"role": "user", "content": test_input}],
        api_key=settings.llm_api_key,
    )
    
    print(f"Extracted: food={result.food}, temp={result.temperature_c}°C, duration={result.duration_minutes}min")


if __name__ == "__main__":
    asyncio.run(main())
