"""
Manual test for ComBase calculator.

Usage:
    python scripts/test_combase_calculator.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.engines.combase.models import ComBaseModelRegistry
from app.engines.combase.calculator import ComBaseCalculator
from app.models.enums import ModelType, ComBaseOrganism, Factor4Type


def main():
    # Load models
    registry = ComBaseModelRegistry()
    csv_path = Path("data/combase_models.csv")
    
    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found")
        return
    
    count = registry.load_from_csv(csv_path)
    print(f"Loaded {count} models")
    print()
    
    # Test Listeria growth at different temperatures
    print("=" * 60)
    print("LISTERIA GROWTH AT DIFFERENT TEMPERATURES")
    print("=" * 60)
    
    model = registry.get_model(
        organism=ComBaseOrganism.LISTERIA_MONOCYTOGENES,
        model_type=ModelType.GROWTH,
        factor4_type=Factor4Type.NONE,
    )
    
    if model is None:
        print("Listeria growth model not found")
        return
    
    print(f"Model: {model.organism_name}")
    print(f"Valid temp range: {model.constraints.temp_min} - {model.constraints.temp_max}°C")
    print()
    
    calc = ComBaseCalculator(model)
    
    temperatures = [4, 10, 15, 20, 25, 30, 37]
    
    print(f"{'Temp (°C)':<12} {'mu (1/h)':<12} {'Doubling Time (h)':<18} {'Log inc/4h':<12}")
    print("-" * 54)
    
    for temp in temperatures:
        result = calc.calculate(temperature=temp, ph=7.0, aw=0.99)
        log_inc = calc.calculate_log_increase(result.mu_max, 4.0)
        
        dt_str = f"{result.doubling_time_hours:.2f}" if result.doubling_time_hours else "N/A"
        print(f"{temp:<12} {result.mu_max:<12.4f} {dt_str:<18} {log_inc:<12.2f}")
    
    print()
    
    # Test Salmonella thermal inactivation
    print("=" * 60)
    print("SALMONELLA THERMAL INACTIVATION")
    print("=" * 60)
    
    model = registry.get_model(
        organism=ComBaseOrganism.SALMONELLA,
        model_type=ModelType.THERMAL_INACTIVATION,
        factor4_type=Factor4Type.NONE,
    )
    
    if model is None:
        print("Salmonella thermal model not found")
        return
    
    print(f"Model: {model.organism_name}")
    print(f"Valid temp range: {model.constraints.temp_min} - {model.constraints.temp_max}°C")
    print()
    
    calc = ComBaseCalculator(model)
    
    temperatures = [55, 57.5, 60, 62.5, 65]
    
    print(f"{'Temp (°C)':<12} {'mu (1/h)':<12} {'Log reduction/min':<18}")
    print("-" * 42)
    
    for temp in temperatures:
        result = calc.calculate(temperature=temp, ph=7.0, aw=0.99)
        # Log reduction per minute
        log_red_per_min = abs(result.mu_max) / 60 / 2.303
        
        print(f"{temp:<12} {result.mu_max:<12.4f} {log_red_per_min:<18.4f}")
    
    print()
    
    # List all available models
    print("=" * 60)
    print("ALL AVAILABLE MODELS")
    print("=" * 60)
    
    for model in registry.list_all_models():
        f4 = f" + {model.factor4_type.value}" if model.factor4_type != Factor4Type.NONE else ""
        print(f"{model.model_type.value:<25} {model.organism_name:<40}{f4}")


if __name__ == "__main__":
    main()