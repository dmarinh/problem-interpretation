"""
Test our LLM client.

Usage:
    python scripts/test_llm_client.py
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent)) # So it can be run from any directory (from app.services.llm.client import get_llm_client will fail otherwise)

from pydantic import BaseModel, Field


class FoodExtraction(BaseModel):
    """Test extraction model."""
    food: str | None = Field(default=None, description="Food item mentioned")
    temperature_c: float | None = Field(default=None, description="Temperature in Celsius")
    duration_minutes: float | None = Field(default=None, description="Duration in minutes")


async def main():
    from app.services.llm.client import get_llm_client
    
    client = get_llm_client()
    
    print(f"Model: {client.model}")
    print(f"API Key Set: {client.api_key is not None}")
    print()
    
    # Test 1: Health check
    print("--- Test 1: Health Check ---")
    health = await client.health_check()
    print(f"Healthy: {health['healthy']}")
    print(f"Message: {health['message']}")
    print()
    
    # Test 2: Simple completion
    print("--- Test 2: Simple Completion ---")
    response = await client.complete("Say hello in 5 words or less")
    print(f"Response: {response.content}")
    print()
    
    # Test 3: Structured extraction
    print("--- Test 3: Structured Extraction ---")
    test_input = "Raw chicken left at 25°C for 3 hours"
    print(f"Input: {test_input}")
    
    result = await client.extract(
        response_model=FoodExtraction,
        messages=[{"role": "user", "content": test_input}],
    )
    
    print(f"Extracted: food={result.food}, temp={result.temperature_c}°C, duration={result.duration_minutes}min")


if __name__ == "__main__":
    asyncio.run(main())