"""
Standardization Service

Applies conservative defaults, range clamping, and bias correction.
Transforms grounded values into execution-ready payloads.

IMPORTANT: Conservative Bias Direction
=======================================
The meaning of "conservative" depends on the model type:

- GROWTH models: Conservative = predict MORE growth (worse outcome)
  → Use upper bounds for temperature and duration
  → Add duration margin (+20%)
  → Higher temp + longer time = more bacterial multiplication
  
- THERMAL INACTIVATION models: Conservative = predict LESS kill (worse outcome)
  → Use lower bounds for temperature and duration  
  → Subtract duration margin (-20%)
  → Lower temp + shorter time = fewer pathogens killed
  → This prevents approving undercooked food as safe

- NON_THERMAL SURVIVAL models: Conservative = predict MORE survival (worse outcome)
  → Similar to growth models in most cases
  → Treatment-specific: lower acid concentration, shorter exposure, etc.
  → Weaker treatment = more surviving pathogens

The key insight: "conservative" always means assuming the WORSE food safety
outcome given the uncertainty in the inputs. For growth, that's more growth.
For inactivation, that's less kill.

Example of the anti-conservative bug this fixes:
------------------------------------------------
User: "chicken nuggets at about 68°C for roughly 8 minutes"
Old behavior: 68°C + temp bump = 70°C, 8 min × 1.2 = 9.6 min
             → Predicts MORE Salmonella kill → "probably safe"
             
This is WRONG because it makes undercooked food look safer than it is.

New behavior: 68°C - temp bump = 66°C, 8 min × 0.8 = 6.4 min  
             → Predicts LESS Salmonella kill → "may not be safe"
             
This correctly errs on the side of caution for cooking scenarios.
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
from app.engines.combase.models import ComBaseModelConstraints, ComBaseModelRegistry
from pydantic import ValidationError


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
    - Apply bias corrections with MODEL-TYPE-AWARE direction
    - Build execution payload
    
    The direction of bias corrections REVERSES for thermal inactivation models
    to ensure we always err toward the worse food safety outcome.
    
    Usage:
        service = StandardizationService(registry)
        result = service.standardize(grounded_values, model_type=ModelType.GROWTH)
    """
    
    # =========================================================================
    # BIAS CORRECTION CONFIGURATION
    # =========================================================================
    
    # Duration margin: how much to adjust inferred durations
    # For growth: multiply by 1.2 (add 20% → more growth)
    # For inactivation: multiply by 0.8 (subtract 20% → less kill)
    DURATION_MARGIN_GROWTH = 1.2
    DURATION_MARGIN_INACTIVATION = 0.8
    
    # Temperature bump for low-confidence values
    # For growth: add 5°C (warmer → more growth)
    # For inactivation: subtract 5°C (cooler → less kill)
    TEMPERATURE_BUMP_GROWTH = 5.0
    TEMPERATURE_BUMP_INACTIVATION = -5.0
    
    # Confidence threshold below which temperature bump is applied
    LOW_CONFIDENCE_THRESHOLD = 0.5
    
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
            model_type: Type of model to run (affects bias direction)
            
        Returns:
            StandardizationResult with payload and corrections
            
        Note:
            The model_type parameter is CRITICAL for correct bias direction.
            - ModelType.GROWTH: bias toward more growth (upper bounds, +duration)
            - ModelType.THERMAL_INACTIVATION: bias toward less kill (lower bounds, -duration)
            - ModelType.NON_THERMAL_SURVIVAL: same as growth (bias toward more survival)
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
        
        # Get and standardize temperature (model-type aware)
        temperature = self._get_temperature(grounded, result, constraints, model_type)
        if temperature is None:
            result.missing_required.append("temperature")
            return result
        
        # Get and standardize duration (model-type aware)
        duration = self._get_duration(grounded, result, model_type)
        if duration is None:
            result.missing_required.append("duration")
            return result
        
        # Get and standardize pH (model-type aware for defaults)
        ph = self._get_ph(grounded, result, constraints, model_type)
        
        # Get and standardize water activity (model-type aware for defaults)
        aw = self._get_water_activity(grounded, result, constraints, model_type)
        
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
        except ValidationError as e:
            result.warnings.append(f"Failed to build payload: {e}")
        
        return result
    
    # =========================================================================
    # HELPER: CONSERVATIVE DIRECTION
    # =========================================================================
    
    def _is_inactivation_model(self, model_type: ModelType) -> bool:
        """
        Determine if this is an inactivation model (requires reversed bias).
        
        For inactivation models, "conservative" means predicting LESS pathogen
        death, so we use lower temperatures and shorter durations.
        
        For growth and survival models, "conservative" means predicting MORE
        pathogen growth/survival, so we use higher temperatures and longer durations.
        """
        return model_type == ModelType.THERMAL_INACTIVATION
    
    def _get_range_bound_to_use(self, model_type: ModelType) -> str:
        """
        Determine which bound of a range to use for conservative bias.
        
        Returns:
            "upper" for growth/survival models (more growth = worse)
            "lower" for inactivation models (less kill = worse)
        """
        if self._is_inactivation_model(model_type):
            return "lower"
        return "upper"
    
    def _get_duration_margin(self, model_type: ModelType) -> float:
        """
        Get the duration margin multiplier for conservative bias.
        
        Returns:
            1.2 (add 20%) for growth/survival models
            0.8 (subtract 20%) for inactivation models
        """
        if self._is_inactivation_model(model_type):
            return self.DURATION_MARGIN_INACTIVATION
        return self.DURATION_MARGIN_GROWTH
    
    def _get_temperature_bump(self, model_type: ModelType) -> float:
        """
        Get the temperature adjustment for low-confidence values.
        
        Returns:
            +5.0°C for growth/survival models (warmer = more growth)
            -5.0°C for inactivation models (cooler = less kill)
        """
        if self._is_inactivation_model(model_type):
            return self.TEMPERATURE_BUMP_INACTIVATION
        return self.TEMPERATURE_BUMP_GROWTH
    
    # =========================================================================
    # VALUE STANDARDIZATION
    # =========================================================================
    
    def _get_organism(
        self,
        grounded: GroundedValues,
        result: StandardizationResult,
    ) -> ComBaseOrganism | None:
        """
        Get organism, applying default if needed.
        
        Note: Organism selection is NOT affected by model type.
        Salmonella is used as the default because it's a common
        worst-case pathogen for both growth and cooking scenarios.
        """
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
        constraints: ComBaseModelConstraints | None,
        model_type: ModelType,
    ) -> float | None:
        """
        Get temperature, applying model-type-aware defaults and bias corrections.
        
        For GROWTH models:
            - Default to abuse temperature (25°C) - warm = more growth
            - Low confidence: add 5°C (warmer = worse)
            
        For THERMAL INACTIVATION models:
            - Default to a conservative cooking temperature
            - Low confidence: subtract 5°C (cooler = worse, less kill)
            
        For NON_THERMAL SURVIVAL models:
            - Same as growth (higher temp = more survival under stress)
        """
        temp = grounded.get("temperature_celsius")
        
        if temp is None:
            # Apply model-type-aware default
            if self._is_inactivation_model(model_type):
                # For cooking: default to a moderate temperature that might
                # not achieve full pasteurization (conservative = less kill)
                temp = settings.default_temperature_inactivation_conservative_c
                result.defaults_applied.append(f"temperature (defaulted to {temp}°C for cooking)")
                result.bias_corrections.append(BiasCorrection(
                    bias_type=BiasType.MISSING_VALUE_IMPUTED,
                    field_name="temperature_celsius",
                    original_value=None,
                    corrected_value=temp,
                    correction_reason=(
                        "No cooking temperature specified. Using conservative 60°C "
                        "(may not achieve full pasteurization)."
                    ),
                ))
            else:
                # For growth/survival: default to abuse temperature
                temp = settings.default_temperature_abuse_c
                result.defaults_applied.append(f"temperature (defaulted to {temp}°C)")
                result.bias_corrections.append(BiasCorrection(
                    bias_type=BiasType.MISSING_VALUE_IMPUTED,
                    field_name="temperature_celsius",
                    original_value=None,
                    corrected_value=temp,
                    correction_reason=(
                        "No temperature specified. Using conservative abuse "
                        f"temperature ({temp}°C) for growth prediction."
                    ),
                ))
        else:
            # Apply low-confidence temperature bump if applicable
            provenance = grounded.provenance.get("temperature_celsius")
            if provenance and provenance.confidence < self.LOW_CONFIDENCE_THRESHOLD:
                original = temp
                bump = self._get_temperature_bump(model_type)
                temp = temp + bump
                
                direction_desc = "warmer" if bump > 0 else "cooler"
                safety_desc = "more growth" if bump > 0 else "less pathogen kill"
                
                result.bias_corrections.append(BiasCorrection(
                    bias_type=BiasType.OPTIMISTIC_TEMPERATURE,
                    field_name="temperature_celsius",
                    original_value=original,
                    corrected_value=temp,
                    correction_reason=(
                        f"Low confidence ({provenance.confidence:.2f}) temperature. "
                        f"Adjusted {abs(bump):.1f}°C {direction_desc} for conservative "
                        f"estimate ({safety_desc})."
                    ),
                    correction_magnitude=bump,
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
                reason=f"Model constraint for {model_type.value}",
            ))
        
        return temp
    
    def _get_duration(
        self,
        grounded: GroundedValues,
        result: StandardizationResult,
        model_type: ModelType,
    ) -> float | None:
        """
        Get duration, applying model-type-aware conservative bias.
        
        For GROWTH models:
            - Inferred durations: multiply by 1.2 (+20%)
            - Longer time = more growth = worse outcome
            
        For THERMAL INACTIVATION models:
            - Inferred durations: multiply by 0.8 (-20%)
            - Shorter time = less kill = worse outcome
            - This prevents approving undercooked food!
            
        For NON_THERMAL SURVIVAL models:
            - Same as growth (+20%)
            - Longer survival time = more risk
        """
        duration = grounded.get("duration_minutes")
        
        if duration is None:
            # Cannot default duration - it's critical information
            result.warnings.append("Duration is required but not specified")
            return None
        
        # Apply conservative bias for inferred durations
        provenance = grounded.provenance.get("duration_minutes")
        if provenance and provenance.source == ValueSource.USER_INFERRED:
            original = duration
            margin = self._get_duration_margin(model_type)
            duration = duration * margin
            
            # Describe the direction and rationale
            if margin > 1.0:
                direction_desc = f"+{(margin - 1.0) * 100:.0f}%"
                safety_desc = "assuming longer exposure (more growth)"
            else:
                direction_desc = f"-{(1.0 - margin) * 100:.0f}%"
                safety_desc = "assuming shorter cooking (less pathogen kill)"
            
            result.bias_corrections.append(BiasCorrection(
                bias_type=BiasType.OPTIMISTIC_DURATION,
                field_name="duration_minutes",
                original_value=original,
                corrected_value=duration,
                correction_reason=(
                    f"Inferred duration adjusted {direction_desc} for "
                    f"{model_type.value} model: {safety_desc}."
                ),
                correction_magnitude=duration - original,
            ))
        
        return duration
    
    def _get_ph(
        self,
        grounded: GroundedValues,
        result: StandardizationResult,
        constraints: ComBaseModelConstraints | None,
        model_type: ModelType,
    ) -> float:
        """
        Get pH, applying model-type-aware defaults and clamping.
        
        For GROWTH models:
            - Default to neutral pH (7.0) - optimal for most pathogens
            - This maximizes predicted growth (conservative)
            
        For THERMAL INACTIVATION models:
            - Default to neutral pH (7.0)
            - Neutral pH generally means pathogens are more heat-resistant
            - Lower pH (acidic) can increase heat sensitivity
            
        For NON_THERMAL SURVIVAL models:
            - Default depends on treatment type
            - For acid treatments: higher pH = more survival (conservative)
            - Generally: neutral pH allows more survival
        """
        ph = grounded.get("ph")
        
        if ph is None:
            # Apply neutral default (conservative for most scenarios)
            # Neutral pH is near-optimal for pathogen growth and doesn't
            # provide the protective effect that acidic conditions would
            ph = settings.default_ph_neutral
            result.defaults_applied.append(f"pH (defaulted to {ph})")
            
            if self._is_inactivation_model(model_type):
                reason = (
                    "No pH specified. Using neutral pH (7.0) which provides "
                    "no additional thermal protection (conservative for cooking)."
                )
            else:
                reason = (
                    "No pH specified. Using neutral default which is near-optimal "
                    "for pathogen growth (conservative)."
                )
            
            result.bias_corrections.append(BiasCorrection(
                bias_type=BiasType.MISSING_VALUE_IMPUTED,
                field_name="ph",
                original_value=None,
                corrected_value=ph,
                correction_reason=reason,
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
        constraints: ComBaseModelConstraints | None,
        model_type: ModelType,
    ) -> float:
        """
        Get water activity, applying model-type-aware defaults.
        
        For GROWTH models:
            - Default to high water activity (0.99)
            - High aw = more available water = more growth (conservative)
            
        For THERMAL INACTIVATION models:
            - Default to high water activity (0.99)
            - High aw generally means pathogens are MORE heat-sensitive
            - However, we keep it high to not assume protective effects
            
        For NON_THERMAL SURVIVAL models:
            - For drying treatments: high aw = more survival
            - Default to high (0.99) which is conservative
            
        Note: Unlike temperature and duration, the conservative default for
        water activity is the same (high) for all model types because:
        - Growth: high aw = more growth
        - Inactivation: high aw = no protective effect assumed
        - Survival: high aw = more survival
        """
        aw = grounded.get("water_activity")
        
        if aw is None:
            # Apply conservative (high) default
            aw = settings.default_water_activity
            result.defaults_applied.append(f"water_activity (defaulted to {aw})")
            
            if self._is_inactivation_model(model_type):
                reason = (
                    "No water activity specified. Using high default (0.99) "
                    "which doesn't assume any protective effect from low aw."
                )
            else:
                reason = (
                    "No water activity specified. Using conservative high "
                    "default (0.99) which maximizes predicted growth."
                )
            
            result.bias_corrections.append(BiasCorrection(
                bias_type=BiasType.MISSING_VALUE_IMPUTED,
                field_name="water_activity",
                original_value=None,
                corrected_value=aw,
                correction_reason=reason,
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
