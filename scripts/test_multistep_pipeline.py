"""
Manual test script for multi-step (multiple temperatures) pipeline translation.

Tests a scenario where food passes through several temperature stages, verifying
that the orchestrator correctly extracts a multi-step time-temperature profile
and accumulates log growth across each step.

Usage:
    python scripts/test_multistep_pipeline.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()


async def main():
    from app.core.log_config import setup_logging, get_logger
    setup_logging()

    from app.core.orchestrator import get_orchestrator, reset_orchestrator
    from app.engines.combase.engine import get_combase_engine
    from app.rag.vector_store import get_vector_store

    print("=" * 70)
    print("MULTI-STEP TEMPERATURE PIPELINE TEST")
    print("=" * 70)
    print()

    # Initialize ComBase engine
    engine = get_combase_engine()
    csv_path = Path("data/combase_models.csv")
    if not csv_path.exists():
        print(f"✗ ComBase models not found at {csv_path}")
        return
    count = engine.load_models(csv_path)
    print(f"✓ Loaded {count} ComBase models")

    # Initialize vector store
    store = get_vector_store()
    store.initialize()
    print(f"✓ Vector store initialized ({store.get_count()} documents)")
    print()

    reset_orchestrator()
    orchestrator = get_orchestrator()

    # Multi-step scenarios: food that travels through distinct temperature stages
    test_cases = [
        {
            "query": (
                "After buying raw chicken at the grocery store I drove home for 45 minutes "
                "in a warm car (about 28°C). Then I left it on the kitchen counter for "
                "1 hour at room temperature (22°C) while I prepared dinner. "
                "Finally I put it in the fridge at 4°C for 2 hours before cooking."
            ),
            "description": "Chicken: warm car → counter → fridge (3 steps, growth scenario)",
            "expected_steps": 3,
        },
        # {
        #     "query": (
        #         "Cooked rice was stored on the counter at 30°C for 2 hours, "
        #         "then moved to a cool pantry shelf at 18°C for another 3 hours "
        #         "before serving."
        #     ),
        #     "description": "Rice: counter → pantry (2 steps, growth scenario)",
        #     "expected_steps": 2,
        # },
        # {
        #     "query": (
        #         "Ground beef was thawed at room temperature (20°C) for 2 hours, "
        #         "then kept at 10°C in the fridge for 4 hours, "
        #         "and finally left out again at 25°C for 1 hour."
        #     ),
        #     "description": "Ground beef: room temp → fridge → room temp (3 steps, growth scenario)",
        #     "expected_steps": 3,
        # },
    ]

    for i, test in enumerate(test_cases, 1):
        print(f"TEST {i}: {test['description']}")
        print(f"Query: \"{test['query'][:80]}...\"")
        print(f"Expected steps: {test['expected_steps']}")
        print("-" * 70)

        try:
            result = await orchestrator.translate(user_input=test["query"])

            if result.success:
                print(f"✓ Status: SUCCESS")

                er = result.execution_result
                mr = er.model_result if er else None
                profile = result.state.execution_payload.time_temperature_profile

                # Multi-step profile details
                print(f"  is_multi_step: {profile.is_multi_step}")
                print(f"  Steps extracted: {len(profile.steps)}  (expected {test['expected_steps']})")
                print(f"  Total duration: {profile.total_duration_minutes:.0f} min ({profile.total_duration_minutes/60:.1f} h)")

                for step in profile.steps:
                    print(
                        f"    Step {step.step_order}: {step.temperature_celsius}°C "
                        f"for {step.duration_minutes:.0f} min"
                    )

                if er:
                    print(f"  Total log change: {er.total_log_increase:.2f} log CFU")
                    if er.step_predictions:
                        print(f"  Per-step log contributions:")
                        for sp in er.step_predictions:
                            print(
                                f"    Step {sp.step_order} ({sp.temperature_celsius}°C): "
                                f"μ_max={sp.mu_max:.4f} 1/h, Δlog={sp.log_increase:.2f}"
                            )
                    if er.total_log_increase > 0:
                        fold = 10 ** er.total_log_increase
                        print(f"  → ~{fold:.1f}x bacterial increase across all steps")

                if result.metadata:
                    print(f"  Overall confidence: {result.metadata.overall_confidence:.2f}")
                    if result.metadata.warnings:
                        for w in result.metadata.warnings[:3]:
                            print(f"  Warning: {w[:80]}")

                # Sanity checks
                step_count_ok = len(profile.steps) == test["expected_steps"]
                multi_step_flag_ok = profile.is_multi_step == (len(profile.steps) > 1)
                print(f"  [check] step count matches: {'✓' if step_count_ok else '✗'}")
                print(f"  [check] is_multi_step flag correct: {'✓' if multi_step_flag_ok else '✗'}")

            else:
                print(f"✗ Status: FAILED")
                print(f"  Error: {result.error}")

        except Exception as e:
            import traceback
            print(f"✗ Exception: {e}")
            traceback.print_exc()

        print()

    print("=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
