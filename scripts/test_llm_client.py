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

class TimeTemperatureStep(BaseModel):
    description: str = Field(description="Description of this step")
    temperature_c: float = Field(description="Temperature in Celsius")
    duration_minutes: float = Field(description="Duration in minutes")

class MultiStepExtraction(BaseModel):
    food_item: str = Field(description="The food item")
    steps: list[TimeTemperatureStep] = Field(description="Time-temperature steps in order")
    total_duration_minutes: float = Field(description="Total time from purchase to cooking")

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


    # Test 4: Complex structured extraction
    print("--- Test 4: Complex Structured Extraction ---")
    test_input = """
    After purchasing salmon fillets from the supermarket, I drove home which took about 
    45 minutes in summer traffic. The car was warm, maybe 28°C. Once home, I put the 
    salmon in the fridge at 4°C where it stayed overnight (about 10 hours) before I 
    cooked it for dinner.
    """
    print(f"Input: {test_input.strip()}")
    print()
    
    try:
        result = await client.extract(
            response_model=MultiStepExtraction,
            messages=[
                {
                    "role": "system",
                    "content": "Extract the time-temperature history of the food item. Identify each step with its temperature and duration."
                },
                {"role": "user", "content": test_input}
            ],
        )
        
        print(f"Food: {result.food_item}")
        print(f"Total duration: {result.total_duration_minutes} minutes")
        print(f"Steps:")
        for i, step in enumerate(result.steps, 1):
            print(f"  {i}. {step.description}")
            print(f"     Temp: {step.temperature_c}°C, Duration: {step.duration_minutes} min")
        
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")

if __name__ == "__main__":
    asyncio.run(main())