"""
Manual test for ComBase engine.

Usage:
    python scripts/test_combase_engine.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.engines.combase.engine import ComBaseEngine
from app.models.enums import ModelType, ComBaseOrganism, Factor4Type
from app.models.execution.base import TimeTemperatureStep, TimeTemperatureProfile
from app.models.execution.combase import (
    ComBaseParameters,
    ComBaseModelSelection,
    ComBaseExecutionPayload,
)


async def main():
    # Initialize engine
    engine = ComBaseEngine()
    csv_path = Path("data/combase_models.csv")
    
    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found")
        return
    
    count = engine.load_models(csv_path)
    print(f"Loaded {count} models")
    print()
    
    # Test 1: Simple growth prediction
    print("=" * 60)
    print("TEST 1: Listeria growth at 25°C for 3 hours")
    print("=" * 60)
    
    payload = ComBaseExecutionPayload(
        model_selection=ComBaseModelSelection(
            organism=ComBaseOrganism.LISTERIA_MONOCYTOGENES,
            model_type=ModelType.GROWTH,
        ),
        parameters=ComBaseParameters(
            temperature_celsius=25.0,
            ph=7.0,
            water_activity=0.99,
        ),
        time_temperature_profile=TimeTemperatureProfile(
            is_multi_step=False,
            steps=[
                TimeTemperatureStep(
                    temperature_celsius=25.0,
                    duration_minutes=180.0,
                    step_order=1,
                )
            ],
            total_duration_minutes=180.0,
        ),
    )
    
    result = await engine.execute(payload)
    
    print(f"Organism: {result.model_result.organism.value}")
    print(f"mu_max: {result.model_result.mu_max:.4f} 1/h")
    print(f"Doubling time: {result.model_result.doubling_time_hours:.2f} h")
    print(f"Total log increase: {result.total_log_increase:.2f} log10 CFU")
    if result.warnings:
        print(f"Warnings: {result.warnings}")
    print()
    
    # Test 2: Multi-step scenario
    print("=" * 60)
    print("TEST 2: Salmonella - 1h at 25°C then 4h at 4°C")
    print("=" * 60)
    
    payload = ComBaseExecutionPayload(
        model_selection=ComBaseModelSelection(
            organism=ComBaseOrganism.SALMONELLA,
            model_type=ModelType.GROWTH,
        ),
        parameters=ComBaseParameters(
            temperature_celsius=25.0,
            ph=7.0,
            water_activity=0.99,
        ),
        time_temperature_profile=TimeTemperatureProfile(
            is_multi_step=True,
            steps=[
                TimeTemperatureStep(
                    temperature_celsius=25.0,
                    duration_minutes=60.0,
                    step_order=1,
                ),
                TimeTemperatureStep(
                    temperature_celsius=4.0,
                    duration_minutes=240.0,
                    step_order=2,
                ),
            ],
            total_duration_minutes=300.0,
        ),
    )
    
    result = await engine.execute(payload)
    
    print(f"Organism: {result.model_result.organism.value}")
    print(f"Steps:")
    for pred in result.step_predictions:
        print(f"  Step {pred.step_order}: {pred.temperature_celsius}°C for {pred.duration_minutes} min")
        print(f"    mu_max: {pred.mu_max:.4f} 1/h")
        print(f"    Log increase: {pred.log_increase:.3f}")
    print(f"Total log increase: {result.total_log_increase:.3f} log10 CFU")
    print()
    
    # Test 3: Thermal inactivation
    print("=" * 60)
    print("TEST 3: Salmonella thermal inactivation at 60°C for 10 min")
    print("=" * 60)
    
    payload = ComBaseExecutionPayload(
        model_selection=ComBaseModelSelection(
            organism=ComBaseOrganism.SALMONELLA,
            model_type=ModelType.THERMAL_INACTIVATION,
        ),
        parameters=ComBaseParameters(
            temperature_celsius=60.0,
            ph=7.0,
            water_activity=0.99,
        ),
        time_temperature_profile=TimeTemperatureProfile(
            is_multi_step=False,
            steps=[
                TimeTemperatureStep(
                    temperature_celsius=60.0,
                    duration_minutes=10.0,
                    step_order=1,
                )
            ],
            total_duration_minutes=10.0,
        ),
    )
    
    result = await engine.execute(payload)
    
    print(f"Organism: {result.model_result.organism.value}")
    print(f"mu_max: {result.model_result.mu_max:.4f} 1/h (negative = inactivation)")
    print(f"Total log reduction: {abs(result.total_log_increase):.2f} log10 CFU")
    print()
    
    # Test 4: With fourth factor
    print("=" * 60)
    print("TEST 4: Listeria growth with 10% CO2")
    print("=" * 60)
    
    payload = ComBaseExecutionPayload(
        model_selection=ComBaseModelSelection(
            organism=ComBaseOrganism.LISTERIA_MONOCYTOGENES,
            model_type=ModelType.GROWTH,
            factor4_type=Factor4Type.CO2,
        ),
        parameters=ComBaseParameters(
            temperature_celsius=10.0,
            ph=6.5,
            water_activity=0.98,
            factor4_type=Factor4Type.CO2,
            factor4_value=10.0,
        ),
        time_temperature_profile=TimeTemperatureProfile(
            is_multi_step=False,
            steps=[
                TimeTemperatureStep(
                    temperature_celsius=10.0,
                    duration_minutes=1440.0,  # 24 hours
                    step_order=1,
                )
            ],
            total_duration_minutes=1440.0,
        ),
    )
    
    result = await engine.execute(payload)
    
    print(f"Organism: {result.model_result.organism.value}")
    print(f"Conditions: {result.model_result.temperature_used}°C, pH {result.model_result.ph_used}, aw {result.model_result.aw_used}")
    print(f"CO2: {result.model_result.factor4_value_used}%")
    print(f"mu_max: {result.model_result.mu_max:.4f} 1/h")
    print(f"Doubling time: {result.model_result.doubling_time_hours:.2f} h")
    print(f"Log increase in 24h: {result.total_log_increase:.2f} log10 CFU")


if __name__ == "__main__":
    asyncio.run(main())