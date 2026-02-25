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

    # Test 3: Complex tructured extraction
    print("--- Test 3: Complex tructured extraction ---")
    client = instructor.from_litellm(acompletion)
    
    test_input = """
    After purchasing salmon fillets from the supermarket, I drove home which took about 
    45 minutes in summer traffic. The car was warm, maybe 28°C. Once home, I put the 
    salmon in the fridge at 4°C where it stayed overnight (about 10 hours) before I 
    cooked it for dinner.
    """
    
    class TimeTemperatureStep(BaseModel):
        description: str = Field(description="Description of this step")
        temperature_c: float = Field(description="Temperature in Celsius")
        duration_minutes: float = Field(description="Duration in minutes")
    
    class MultiStepExtraction(BaseModel):
        food_item: str = Field(description="The food item")
        steps: list[TimeTemperatureStep] = Field(description="Time-temperature steps in order")
        total_duration_minutes: float = Field(description="Total time from purchase to cooking")
    
    print(f"Input: {test_input.strip()}")
    print()
    
    try:
        result = await client.chat.completions.create(
            model=settings.llm_model,
            response_model=MultiStepExtraction,
            messages=[
                {
                    "role": "system",
                    "content": "Extract the time-temperature history of the food item. Identify each step with its temperature and duration."
                },
                {"role": "user", "content": test_input}
            ],
            api_key=settings.llm_api_key,
            api_base=settings.llm_api_base,
            max_tokens=500,
            temperature=0.1,
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
