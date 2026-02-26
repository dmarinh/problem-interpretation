"""
Standardization Service

Applies conservative defaults, range clamping, and bias correction.
Transforms grounded values into execution-ready payloads.
"""

from app.config import settings
from app.models.enums import (
    ModelType,
    ComBaseOrganism,
    Factor4Type,
    BiasType,
)
from app.models.execution.base import TimeTemperatureStep, TimeTemperatureProfile
from app.models.execution.combase import (
    ComBaseParameters,
    ComBaseModelSelection,
    ComBaseExecutionPayload,
)
from app.models.metadata import (
    BiasCorrection,
    RangeClamp,
    ValueProvenance,
    ValueSource,
)
from app.services.grounding.grounding_service import GroundedValues
from app.engines.combase.models import ComBaseModelRegistry


class StandardizationResult:
    """Result of standardization with corrections applied."""
    
    def __init__(self):
        self.payload: ComBaseExecutionPayload | None = None
        self.bias_corrections: list[BiasCorrection] = []
        self.range_clamps: list[RangeClamp] = []
        self.defaults_applied: list[str] = []
        self.warnings: list[str] = []
        self.missing_required: list[str] = []


class StandardizationService:
    """
    Service for standardizing grounded values into execution payloads.
    
    Responsibilities:
    - Apply conservative defaults for missing values
    - Clamp values to model-valid ranges
    - Apply bias corrections for optimistic estimates
    - Build execution payload
    
    Usage:
        service = StandardizationService(registry)
        result = service.standardize(grounded_values)
    """
    
    def __init__(
        self,
        model_registry: ComBaseModelRegistry | None = None,
    ):
        self._registry = model_registry
    
    def standardize(
        self,
        grounded: GroundedValues,
        model_type: ModelType = ModelType.GROWTH,
    ) -> StandardizationResult:
        """
        Standardize grounded values into an execution payload.
        
        Args:
            grounded: Grounded values from GroundingService
            model_type: Type of model to run
            
        Returns:
            StandardizationResult with payload and corrections
        """
        result = StandardizationResult()
        
        # Determine organism
        organism = self._get_organism(grounded, result)
        if organism is None:
            result.missing_required.append("organism")
            return result
        
        # Determine factor4
        factor4_type, factor4_value = self._get_factor4(grounded)
        
        # Get model constraints if registry available
        constraints = None
        if self._registry:
            model = self._registry.get_model(organism, model_type, factor4_type)
            if model:
                constraints = model.constraints
        
        # Get and standardize temperature
        temperature = self._get_temperature(grounded, result, constraints)
        if temperature is None:
            result.missing_required.append("temperature")
            return result
        
        # Get and standardize duration
        duration = self._get_duration(grounded, result)
        if duration is None:
            result.missing_required.append("duration")
            return result
        
        # Get and standardize pH
        ph = self._get_ph(grounded, result, constraints)
        
        # Get and standardize water activity
        aw = self._get_water_activity(grounded, result, constraints)
        
        # Build payload
        try:
            result.payload = ComBaseExecutionPayload(
                model_selection=ComBaseModelSelection(
                    organism=organism,
                    model_type=model_type,
                    factor4_type=factor4_type,
                ),
                parameters=ComBaseParameters(
                    temperature_celsius=temperature,
                    ph=ph,
                    water_activity=aw,
                    factor4_type=factor4_type,
                    factor4_value=factor4_value,
                ),
                time_temperature_profile=TimeTemperatureProfile(
                    is_multi_step=False,
                    steps=[
                        TimeTemperatureStep(
                            temperature_celsius=temperature,
                            duration_minutes=duration,
                            step_order=1,
                        )
                    ],
                    total_duration_minutes=duration,
                ),
            )
        except Exception as e:
            result.warnings.append(f"Failed to build payload: {e}")
        
        return result
    
    def _get_organism(
        self,
        grounded: GroundedValues,
        result: StandardizationResult,
    ) -> ComBaseOrganism | None:
        """Get organism, applying default if needed."""
        organism = grounded.get("organism")
        
        if organism is None:
            # Default to Salmonella (common worst-case)
            result.defaults_applied.append("organism (defaulted to Salmonella)")
            result.warnings.append(
                "No pathogen specified. Using Salmonella as conservative default."
            )
            return ComBaseOrganism.SALMONELLA
        
        return organism
    
    def _get_factor4(
        self,
        grounded: GroundedValues,
    ) -> tuple[Factor4Type, float | None]:
        """Determine factor4 type and value."""
        if grounded.has("co2_percent"):
            return Factor4Type.CO2, grounded.get("co2_percent")
        if grounded.has("nitrite_ppm"):
            return Factor4Type.NITRITE, grounded.get("nitrite_ppm")
        if grounded.has("lactic_acid_ppm"):
            return Factor4Type.LACTIC_ACID, grounded.get("lactic_acid_ppm")
        if grounded.has("acetic_acid_ppm"):
            return Factor4Type.ACETIC_ACID, grounded.get("acetic_acid_ppm")
        
        return Factor4Type.NONE, None
    
    def _get_temperature(
        self,
        grounded: GroundedValues,
        result: StandardizationResult,
        constraints=None,
    ) -> float | None:
        """Get temperature, applying defaults and clamping."""
        temp = grounded.get("temperature_celsius")
        
        if temp is None:
            # Apply conservative default
            temp = settings.default_temperature_abuse_c
            result.defaults_applied.append(f"temperature (defaulted to {temp}°C)")
            result.bias_corrections.append(BiasCorrection(
                bias_type=BiasType.MISSING_VALUE_IMPUTED,
                field_name="temperature_celsius",
                original_value=None,
                corrected_value=temp,
                correction_reason="No temperature specified, using conservative abuse temperature",
            ))
        
        # Clamp to valid range if constraints available
        if constraints and not constraints.is_temperature_valid(temp):
            original = temp
            temp = constraints.clamp_temperature(temp)
            result.range_clamps.append(RangeClamp(
                field_name="temperature_celsius",
                original_value=original,
                clamped_value=temp,
                valid_min=constraints.temp_min,
                valid_max=constraints.temp_max,
                reason="Model constraint",
            ))
        
        return temp
    
    def _get_duration(
        self,
        grounded: GroundedValues,
        result: StandardizationResult,
    ) -> float | None:
        """Get duration, applying conservative estimates."""
        duration = grounded.get("duration_minutes")
        
        if duration is None:
            # Cannot default duration - it's critical
            result.warnings.append("Duration is required but not specified")
            return None
        
        # Apply conservative bias for short durations
        provenance = grounded.provenance.get("duration_minutes")
        if provenance and provenance.source == ValueSource.USER_INFERRED:
            # Add 20% for uncertainty
            original = duration
            duration = duration * 1.2
            result.bias_corrections.append(BiasCorrection(
                bias_type=BiasType.OPTIMISTIC_DURATION,
                field_name="duration_minutes",
                original_value=original,
                corrected_value=duration,
                correction_reason="Added 20% margin for inferred duration",
                correction_magnitude=duration - original,
            ))
        
        return duration
    
    def _get_ph(
        self,
        grounded: GroundedValues,
        result: StandardizationResult,
        constraints=None,
    ) -> float:
        """Get pH, applying defaults and clamping."""
        ph = grounded.get("ph")
        
        if ph is None:
            # Apply neutral default
            ph = settings.default_ph_neutral
            result.defaults_applied.append(f"pH (defaulted to {ph})")
            result.bias_corrections.append(BiasCorrection(
                bias_type=BiasType.MISSING_VALUE_IMPUTED,
                field_name="ph",
                original_value=None,
                corrected_value=ph,
                correction_reason="No pH specified, using neutral default",
            ))
        
        # Clamp to valid range
        if constraints and not constraints.is_ph_valid(ph):
            original = ph
            ph = constraints.clamp_ph(ph)
            result.range_clamps.append(RangeClamp(
                field_name="ph",
                original_value=original,
                clamped_value=ph,
                valid_min=constraints.ph_min,
                valid_max=constraints.ph_max,
                reason="Model constraint",
            ))
        
        return ph
    
    def _get_water_activity(
        self,
        grounded: GroundedValues,
        result: StandardizationResult,
        constraints=None,
    ) -> float:
        """Get water activity, applying conservative default."""
        aw = grounded.get("water_activity")
        
        if aw is None:
            # Apply conservative (high) default
            aw = settings.default_water_activity
            result.defaults_applied.append(f"water_activity (defaulted to {aw})")
            result.bias_corrections.append(BiasCorrection(
                bias_type=BiasType.MISSING_VALUE_IMPUTED,
                field_name="water_activity",
                original_value=None,
                corrected_value=aw,
                correction_reason="No water activity specified, using conservative high default",
            ))
        
        # Clamp to valid range
        if constraints and not constraints.is_aw_valid(aw):
            original = aw
            aw = constraints.clamp_aw(aw)
            result.range_clamps.append(RangeClamp(
                field_name="water_activity",
                original_value=original,
                clamped_value=aw,
                valid_min=constraints.aw_min,
                valid_max=constraints.aw_max,
                reason="Model constraint",
            ))
        
        return aw


# =============================================================================
# SINGLETON
# =============================================================================

_service: StandardizationService | None = None


def get_standardization_service() -> StandardizationService:
    """Get or create the global StandardizationService instance."""
    global _service
    if _service is None:
        _service = StandardizationService()
    return _service


def reset_standardization_service() -> None:
    """Reset the global service (for testing)."""
    global _service
    _service = None