"""
ComBase Engine Implementation

Local implementation of ComBase broth models.
Executes predictions using loaded model coefficients.
"""

from pathlib import Path

from app.engines.base import BaseEngine
from app.engines.combase.models import ComBaseModelRegistry, ComBaseModel
from app.engines.combase.calculator import ComBaseCalculator, CalculationResult
from app.models.enums import EngineType, ModelType
from app.models.execution.base import GrowthPrediction, TimeTemperatureProfile
from app.models.execution.combase import (
    ComBaseExecutionPayload,
    ComBaseExecutionResult,
    ComBaseModelResult,
)


class ComBaseEngine(BaseEngine):
    """
    Local ComBase engine implementation.
    
    Loads models from CSV and executes predictions locally
    using the polynomial equations.
    
    Usage:
        engine = ComBaseEngine()
        engine.load_models(Path("data/combase_models.csv"))
        result = await engine.execute(payload)
    """
    
    def __init__(self):
        self._registry = ComBaseModelRegistry()
        self._loaded = False
        self._model_path: Path | None = None
    
    @property
    def engine_name(self) -> str:
        return "ComBase Local"
    
    @property
    def is_available(self) -> bool:
        return self._loaded and len(self._registry) > 0
    
    def load_models(self, csv_path: Path) -> int:
        """
        Load models from CSV file.
        
        Args:
            csv_path: Path to combase_models.csv
            
        Returns:
            Number of models loaded
        """
        count = self._registry.load_from_csv(csv_path)
        self._loaded = count > 0
        self._model_path = csv_path
        return count
    
    @property
    def registry(self) -> ComBaseModelRegistry:
        """Access to the model registry."""
        return self._registry
    
    async def execute(self, payload: ComBaseExecutionPayload) -> ComBaseExecutionResult:
        """
        Execute a ComBase prediction.
        
        Args:
            payload: ComBase execution payload
            
        Returns:
            ComBaseExecutionResult with predictions
        """
        if not self.is_available:
            raise RuntimeError("ComBase engine not loaded. Call load_models() first.")
        
        warnings = []
        
        # Get the model
        model = self._registry.get_model(
            organism=payload.model_selection.organism,
            model_type=payload.model_selection.model_type,
            factor4_type=payload.model_selection.factor4_type,
        )
        
        if model is None:
            raise ValueError(
                f"Model not found: {payload.model_selection.organism.value} / "
                f"{payload.model_selection.model_type.value} / "
                f"{payload.model_selection.factor4_type.value}"
            )
        
        # Create calculator
        calculator = ComBaseCalculator(model)
        
        # Calculate for each time-temperature step
        step_predictions = []
        total_log_increase = 0.0
        total_generations = 0.0
        
        # Use first step's calculation for model result
        first_calc_result: CalculationResult | None = None
        
        for step in payload.time_temperature_profile.steps:
            # Calculate mu at this step's temperature
            calc_result = calculator.calculate(
                temperature=step.temperature_celsius,
                ph=payload.parameters.ph,
                aw=payload.parameters.water_activity,
                factor4_value=payload.parameters.factor4_value or 0.0,
                clamp_to_range=False,
            )
            
            if first_calc_result is None:
                first_calc_result = calc_result
            
            # Add any warnings
            warnings.extend(calc_result.warnings)
            
            # Calculate growth/inactivation during this step
            duration_hours = step.duration_minutes / 60.0
            
            log_increase = calculator.calculate_log_increase(
                mu_max=calc_result.mu_max,
                duration_hours=duration_hours,
            )
                      
            step_predictions.append(GrowthPrediction(
                step_order=step.step_order,
                duration_minutes=step.duration_minutes,
                temperature_celsius=step.temperature_celsius,
                mu_max=calc_result.mu_max,
                log_increase=log_increase,
            ))
            
            total_log_increase += log_increase
        
        # Build model result from first calculation
        model_result = ComBaseModelResult(
            mu_max=first_calc_result.mu_max,
            doubling_time_hours=first_calc_result.doubling_time_hours,
            model_type=model.model_type,
            organism=payload.model_selection.organism,
            temperature_used=first_calc_result.temperature,
            ph_used=first_calc_result.ph,
            aw_used=first_calc_result.aw,
            factor4_type_used=payload.parameters.factor4_type,
            factor4_value_used=payload.parameters.factor4_value,
            engine_type=EngineType.COMBASE_LOCAL,
        )
        
        return ComBaseExecutionResult(
            model_result=model_result,
            step_predictions=step_predictions,
            total_log_increase=total_log_increase,
            engine_type=EngineType.COMBASE_LOCAL,
            warnings=warnings,
        )
    
    async def health_check(self) -> dict:
        """Check engine health."""
        if not self._loaded:
            return {
                "healthy": False,
                "message": "Models not loaded",
                "engine": self.engine_name,
            }
        
        return {
            "healthy": True,
            "message": f"Loaded {len(self._registry)} models",
            "engine": self.engine_name,
            "model_path": str(self._model_path) if self._model_path else None,
        }


# =============================================================================
# SINGLETON
# =============================================================================

_engine: ComBaseEngine | None = None


def get_combase_engine() -> ComBaseEngine:
    """Get or create the global ComBase engine instance."""
    global _engine
    if _engine is None:
        _engine = ComBaseEngine()
    return _engine


def reset_combase_engine() -> None:
    """Reset the global engine (for testing)."""
    global _engine
    _engine = None