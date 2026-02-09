"""
Manual test for semantic parser.

Usage:
    python scripts/test_semantic_parser.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")


async def main():
    from app.services.extraction.semantic_parser import SemanticParser
    
    parser = SemanticParser()
    
    # Test scenarios
    test_inputs = [
        "I left raw chicken on the counter for about 3 hours, it was pretty warm, maybe 25C",
        "Cooked rice was in the fridge at 4C for 5 days",
        "Salmon was transported for 45 minutes in a warm car (28C) then refrigerated overnight",
        "Is it safe to eat? The meat was left out but I'm not sure how long",
    ]
    
    print("=" * 60)
    print("SCENARIO EXTRACTION TESTS")
    print("=" * 60)
    
    for user_input in test_inputs:
        print(f"\nInput: {user_input}")
        print("-" * 40)
        
        result = await parser.extract_scenario(user_input)
        
        print(f"Food: {result.food_description}")
        print(f"State: {result.food_state}")
        print(f"Pathogen: {result.pathogen_mentioned}")
        print(f"Multi-step: {result.is_multi_step}")
        
        if not result.is_multi_step:
            temp = result.single_step_temperature
            dur = result.single_step_duration
            print(f"Temperature: {temp.value_celsius}C ({temp.description})")
            print(f"Duration: {dur.value_minutes} min ({dur.description})")
            print(f"Duration ambiguous: {dur.is_ambiguous}")
        else:
            print(f"Steps: {len(result.time_temperature_steps)}")
            for i, step in enumerate(result.time_temperature_steps, 1):
                print(f"  Step {i}: {step.description}")
                print(f"    Temp: {step.temperature.value_celsius}C")
                print(f"    Duration: {step.duration.value_minutes} min")
        
        print()
    
    print("=" * 60)
    print("INTENT CLASSIFICATION TESTS")
    print("=" * 60)
    
    intent_inputs = [
        "Is my chicken still safe to eat?",
        "What temperature kills salmonella?",
        "I left food out, should I throw it away?",
        "How does listeria grow?",
    ]
    
    for user_input in intent_inputs:
        print(f"\nInput: {user_input}")
        print("-" * 40)
        
        result = await parser.classify_intent(user_input)
        
        print(f"Prediction request: {result.is_prediction_request}")
        print(f"Information query: {result.is_information_query}")
        print(f"Needs clarification: {result.requires_clarification}")
        print(f"Confidence: {result.confidence}")
        print(f"Reasoning: {result.reasoning}")


if __name__ == "__main__":
    asyncio.run(main())