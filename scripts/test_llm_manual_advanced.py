"""
Manual LLM Testing Script

Use this to test different LLM providers interactively.

Usage:
    # From project root, with venv activated
    python scripts/test_llm_manual.py


    # Or test specific provider
    powershell
    # OpenAI
    $env:OPENAI_API_KEY="sk-your-key-here"

    # Anthropic
    $env:ANTHROPIC_API_KEY="sk-ant-your-key-here"
   
    python scripts/test_llm_manual.py --provider openai
    python scripts/test_llm_manual.py --provider anthropic
    python scripts/test_llm_manual.py --provider ollama
"""

import asyncio
import argparse
import os
from typing import Optional
from pydantic import BaseModel, Field


# =============================================================================
# TEST MODELS (for structured extraction)
# =============================================================================

class FoodSafetyExtraction(BaseModel):
    """Test model for food safety scenario extraction."""
    food_description: Optional[str] = Field(
        default=None,
        description="The food item or matrix mentioned"
    )
    pathogen_mentioned: Optional[str] = Field(
        default=None,
        description="Any pathogen explicitly mentioned"
    )
    temperature_c: Optional[float] = Field(
        default=None,
        description="Temperature in Celsius if mentioned"
    )
    duration_minutes: Optional[float] = Field(
        default=None,
        description="Duration in minutes if mentioned"
    )


class SimpleExtraction(BaseModel):
    """Simple test model."""
    main_topic: str = Field(description="The main topic of the text")
    sentiment: str = Field(description="Sentiment: positive, negative, or neutral")
    key_points: list[str] = Field(description="Key points mentioned")


# =============================================================================
# PROVIDER CONFIGURATIONS
# =============================================================================

PROVIDERS = {
    "openai": {
        "model": "gpt-4-turbo-preview",
        "env_key": "OPENAI_API_KEY",
        "api_base": None,
    },
    "openai-gpt4o": {
        "model": "gpt-4o",
        "env_key": "OPENAI_API_KEY",
        "api_base": None,
    },
    "openai-gpt35": {
        "model": "gpt-3.5-turbo",
        "env_key": "OPENAI_API_KEY",
        "api_base": None,
    },
    "anthropic": {
        "model": "claude-3-sonnet-20240229",
        "env_key": "ANTHROPIC_API_KEY",
        "api_base": None,
    },
    "anthropic-haiku": {
        "model": "claude-3-haiku-20240307",
        "env_key": "ANTHROPIC_API_KEY",
        "api_base": None,
    },
    "ollama": {
        "model": "ollama/llama2",
        "env_key": None,  # No API key needed
        "api_base": "http://localhost:11434",
    },
    "ollama-mistral": {
        "model": "ollama/mistral",
        "env_key": None,
        "api_base": "http://localhost:11434",
    },
}


# =============================================================================
# TEST FUNCTIONS
# =============================================================================

async def test_simple_completion(model: str, api_key: Optional[str], api_base: Optional[str]):
    """Test basic completion."""
    from litellm import acompletion
    
    print(f"\n{'='*60}")
    print("TEST: Simple Completion")
    print(f"{'='*60}")
    
    messages = [
        {"role": "system", "content": "You are a helpful assistant. Be concise."},
        {"role": "user", "content": "What is predictive microbiology in one sentence?"}
    ]
    
    try:
        response = await acompletion(
            model=model,
            messages=messages,
            api_key=api_key,
            api_base=api_base,
            max_tokens=100,
            temperature=0.1,
        )
        
        print(f"Model: {response.model}")
        print(f"Response: {response.choices[0].message.content}")
        print(f"Tokens: {response.usage.prompt_tokens} in, {response.usage.completion_tokens} out")
        return True
        
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        return False


async def test_structured_extraction(model: str, api_key: Optional[str], api_base: Optional[str]):
    """Test structured extraction with Instructor."""
    import instructor
    from litellm import acompletion
    
    print(f"\n{'='*60}")
    print("TEST: Structured Extraction (Food Safety)")
    print(f"{'='*60}")
    
    client = instructor.from_litellm(acompletion)
    
    test_input = "Raw chicken breast was left on the kitchen counter at room temperature (about 22°C) for approximately 4 hours before being discovered."
    
    print(f"Input: {test_input}")
    print()
    
    try:
        result = await client.chat.completions.create(
            model=model,
            response_model=FoodSafetyExtraction,
            messages=[
                {
                    "role": "system",
                    "content": "Extract food safety information from the user's description. Be precise with numbers."
                },
                {"role": "user", "content": test_input}
            ],
            api_key=api_key,
            api_base=api_base,
            max_tokens=500,
            temperature=0.1,
        )
        
        print("Extracted:")
        print(f"  Food: {result.food_description}")
        print(f"  Pathogen: {result.pathogen_mentioned}")
        print(f"  Temperature: {result.temperature_c}°C")
        print(f"  Duration: {result.duration_minutes} minutes")
        return True
        
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        return False


async def test_complex_extraction(model: str, api_key: Optional[str], api_base: Optional[str]):
    """Test more complex extraction."""
    import instructor
    from litellm import acompletion
    
    print(f"\n{'='*60}")
    print("TEST: Complex Extraction (Multi-step scenario)")
    print(f"{'='*60}")
    
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
            model=model,
            response_model=MultiStepExtraction,
            messages=[
                {
                    "role": "system",
                    "content": "Extract the time-temperature history of the food item. Identify each step with its temperature and duration."
                },
                {"role": "user", "content": test_input}
            ],
            api_key=api_key,
            api_base=api_base,
            max_tokens=500,
            temperature=0.1,
        )
        
        print(f"Food: {result.food_item}")
        print(f"Total duration: {result.total_duration_minutes} minutes")
        print(f"Steps:")
        for i, step in enumerate(result.steps, 1):
            print(f"  {i}. {step.description}")
            print(f"     Temp: {step.temperature_c}°C, Duration: {step.duration_minutes} min")
        return True
        
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        return False


async def run_all_tests(provider: str):
    """Run all tests for a provider."""
    if provider not in PROVIDERS:
        print(f"Unknown provider: {provider}")
        print(f"Available: {', '.join(PROVIDERS.keys())}")
        return
    
    config = PROVIDERS[provider]
    model = config["model"]
    api_base = config["api_base"]
    
    # Get API key
    api_key = None
    if config["env_key"]:
        api_key = os.getenv(config["env_key"])
        if not api_key:
            print(f"ERROR: {config['env_key']} environment variable not set")
            print(f"Set it with: $env:{config['env_key']}='your-key-here'")
            return
    
    print(f"\n{'#'*60}")
    print(f"TESTING PROVIDER: {provider}")
    print(f"Model: {model}")
    print(f"API Base: {api_base or 'default'}")
    print(f"{'#'*60}")
    
    results = []
    
    # Run tests
    results.append(("Simple Completion", await test_simple_completion(model, api_key, api_base)))
    results.append(("Structured Extraction", await test_structured_extraction(model, api_key, api_base)))
    results.append(("Complex Extraction", await test_complex_extraction(model, api_key, api_base)))
    
    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}: {name}")


def interactive_mode():
    """Interactive testing mode."""
    import instructor
    from litellm import completion
    
    print("\n" + "="*60)
    print("INTERACTIVE MODE")
    print("="*60)
    print("Type your prompts and see responses.")
    print("Commands: /quit, /model <name>, /extract")
    print()
    
    current_model = "gpt-3.5-turbo"
    api_key = os.getenv("OPENAI_API_KEY")
    
    while True:
        try:
            user_input = input(f"\n[{current_model}] You: ").strip()
            
            if not user_input:
                continue
            
            if user_input == "/quit":
                break
            
            if user_input.startswith("/model "):
                current_model = user_input[7:].strip()
                print(f"Switched to: {current_model}")
                continue
            
            if user_input == "/extract":
                print("Enter text for extraction:")
                text = input("> ")
                client = instructor.from_litellm(completion)
                result = client.chat.completions.create(
                    model=current_model,
                    response_model=SimpleExtraction,
                    messages=[{"role": "user", "content": text}],
                    api_key=api_key,
                )
                print(f"Topic: {result.main_topic}")
                print(f"Sentiment: {result.sentiment}")
                print(f"Key points: {result.key_points}")
                continue
            
            # Regular completion
            response = completion(
                model=current_model,
                messages=[{"role": "user", "content": user_input}],
                api_key=api_key,
            )
            print(f"\nAssistant: {response.choices[0].message.content}")
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Manual LLM Testing")
    parser.add_argument(
        "--provider", "-p",
        choices=list(PROVIDERS.keys()) + ["all"],
        default="openai",
        help="LLM provider to test"
    )
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Run in interactive mode"
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List available providers"
    )
    
    args = parser.parse_args()
    
    if args.list:
        print("Available providers:")
        for name, config in PROVIDERS.items():
            key_info = f"(needs {config['env_key']})" if config['env_key'] else "(no key needed)"
            print(f"  {name}: {config['model']} {key_info}")
        return
    
    if args.interactive:
        interactive_mode()
        return
    
    if args.provider == "all":
        for provider in PROVIDERS:
            asyncio.run(run_all_tests(provider))
    else:
        asyncio.run(run_all_tests(args.provider))


if __name__ == "__main__":
    main()