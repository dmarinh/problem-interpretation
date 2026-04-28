"""
Standardization Service

Transforms grounded values into execution-ready payloads.

Responsibilities
----------------
1. Conservative defaults — when a required field is absent, substitute the
   worst-case value for the active model type and record a DefaultImputed event.

2. Range clamping — when a value falls outside the ComBase model's valid range,
   clamp it and record a RangeClamp event.

3. Range-bound selection — when GroundingService left a range with
   range_pending=True, pick the conservative bound (upper for growth/survival,
   lower for thermal inactivation) and record a RangeBoundSelection block on
   the field's ValueProvenance.

That is the complete list.  There is no "bias correction" phase.
Conservatism is committed exactly twice in the system: once in the default
value (committed here at standardization) and once in range-bound selection
(committed here per range).  Mapped values from rules.py carry their own
conservatism via the rule's chosen point — the rule author already picked the
upper end of the plausible range.  Multiplying or bumping on top of that
produces a value that is no longer a defensible interpretation of the user's
words; it is an arbitrary point past the stated worst case.

Conservative direction by model type
-------------------------------------
The meaning of "conservative" depends on the model type:

- GROWTH / NON_THERMAL_SURVIVAL: conservative = predict MORE growth/survival
  → upper bounds, higher defaults (more pathogen multiplication/survival)

- THERMAL_INACTIVATION: conservative = predict LESS kill
  → lower bounds, lower defaults (fewer pathogens destroyed)

Range-bound selection
---------------------
When GroundingService retrieves or extracts a range (e.g., pH 5.0–6.2), it
stores the lower bound as a placeholder with ValueProvenance.range_pending=True.
This service resolves the pending range at the start of each _get_* method:

- GROWTH / NON_THERMAL_SURVIVAL → upper bound (more growth = worse)
- THERMAL_INACTIVATION → lower bound (less kill = worse)

The selection is recorded in ValueProvenance.standardization as a
RangeBoundSelection block.  It does not appear in defaults_imputed or
range_clamps — it is a deterministic, mechanical step that fires on every
range-typed value.
"""

from app.config import settings
from app.models.enums import (
    ModelType,
    ComBaseOrganism,
    Factor4Type,
)
from app.models.execution.base import TimeTemperatureStep, TimeTemperatureProfile
from app.models.execution.combase import (
    ComBaseParameters,
    ComBaseModelSelection,
    ComBaseExecutionPayload,
)
from app.models.metadata import (
    DefaultImputed,
    RangeBoundSelection,
    RangeClamp,
)
from app.services.grounding.grounding_service import GroundedValues
from app.engines.combase.models import ComBaseModelConstraints, ComBaseModelRegistry
from pydantic import ValidationError

# Imported at the bottom of this module to break the circular-import chain:
#   standardization_service → engine (ok) → models (ok)
# get_combase_engine is used only inside get_standardization_service(), not at
# module load time, so the deferred import is safe.
def _get_engine_registry() -> "ComBaseModelRegistry":
    from app.engines.combase.engine import get_combase_engine  # noqa: PLC0415
    return get_combase_engine().registry


class StandardizationResult:
    """Result of standardization."""

    def __init__(self):
        self.payload: ComBaseExecutionPayload | None = None
        self.defaults_imputed: list[DefaultImputed] = []
        self.range_clamps: list[RangeClamp] = []
        self.warnings: list[str] = []
        self.missing_required: list[str] = []


class StandardizationService:
    """
    Standardizes grounded values into execution payloads.

    See module docstring for the full responsibility contract.

    Usage:
        service = StandardizationService(registry)
        result = service.standardize(grounded_values, model_type=ModelType.GROWTH)
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
            model_type: Type of model to run (affects default direction and
                        range-bound selection)

        Returns:
            StandardizationResult with payload, defaults_imputed, and
            range_clamps.
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

        # Get and standardize pH and water activity (shared across all steps)
        ph = self._get_ph(grounded, result, constraints, model_type)
        aw = self._get_water_activity(grounded, result, constraints, model_type)

        if grounded.has_steps:
            # Multi-step path: build profile from per-step grounded data
            profile = self._build_multi_step_profile(grounded, result, constraints, model_type)
            if profile is None:
                return result  # missing_required already populated
            # Use first step's temperature for ComBaseParameters scalar summary.
            representative_temp = profile.steps[0].temperature_celsius
        else:
            # Single-step path
            temperature = self._get_temperature(grounded, result, constraints, model_type)
            if temperature is None:
                result.missing_required.append("temperature")
                return result

            duration = self._get_duration(grounded, result, model_type)
            if duration is None:
                result.missing_required.append("duration")
                return result

            representative_temp = temperature
            profile = TimeTemperatureProfile(
                is_multi_step=False,
                steps=[
                    TimeTemperatureStep(
                        temperature_celsius=temperature,
                        duration_minutes=duration,
                        step_order=1,
                    )
                ],
                total_duration_minutes=duration,
            )

        try:
            result.payload = ComBaseExecutionPayload(
                model_selection=ComBaseModelSelection(
                    organism=organism,
                    model_type=model_type,
                    factor4_type=factor4_type,
                ),
                parameters=ComBaseParameters(
                    temperature_celsius=representative_temp,
                    ph=ph,
                    water_activity=aw,
                    factor4_type=factor4_type,
                    factor4_value=factor4_value,
                ),
                time_temperature_profile=profile,
            )
        except ValidationError as e:
            result.warnings.append(f"Failed to build payload: {e}")

        return result

    # =========================================================================
    # HELPER: CONSERVATIVE DIRECTION
    # =========================================================================

    def _is_inactivation_model(self, model_type: ModelType) -> bool:
        """
        True for thermal inactivation models, which require reversed bound
        selection: conservative = less pathogen kill = lower temperature,
        shorter duration, lower bound on ranges.
        """
        return model_type == ModelType.THERMAL_INACTIVATION

    def _get_range_bound_to_use(self, model_type: ModelType) -> str:
        """
        "upper" for growth/survival (more growth = worse),
        "lower" for thermal inactivation (less kill = worse).
        """
        if self._is_inactivation_model(model_type):
            return "lower"
        return "upper"

    def _select_range_bound(
        self,
        range_min: float,
        range_max: float,
        model_type: ModelType,
    ) -> tuple[float, RangeBoundSelection]:
        """
        Pick the conservative bound from a range based on model type.

        Returns:
            (selected_value, RangeBoundSelection audit block)
        """
        if self._is_inactivation_model(model_type):
            value = range_min
            direction = "lower"
            reason = (
                f"Range narrowed to lower bound for {model_type.value} model "
                "(less pathogen kill = more conservative)"
            )
        else:
            value = range_max
            direction = "upper"
            reason = (
                f"Range narrowed to upper bound for {model_type.value} model "
                "(more pathogen growth/survival = more conservative)"
            )
        return value, RangeBoundSelection(
            direction=direction,
            reason=reason,
            before_value=[range_min, range_max],
            after_value=value,
        )

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

        Salmonella is the default because it is a common worst-case pathogen
        for both growth and cooking scenarios.
        """
        organism = grounded.get("organism")

        if organism is None:
            default_reason = (
                "No pathogen specified. Using Salmonella as conservative default. "
                "Salmonella is a leading cause of foodborne illness and is broadly "
                "applicable across food categories."
            )
            result.defaults_imputed.append(DefaultImputed(
                field_name="organism",
                imputed_value="Salmonella",
                reason=default_reason,
            ))
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
        Get temperature, applying model-type-aware default if absent.

        GROWTH / NON_THERMAL_SURVIVAL default: 25°C (abuse temperature —
        warm enough for rapid growth, conservative for storage scenarios).

        THERMAL_INACTIVATION default: settings.default_temperature_inactivation_conservative_c
        (a cooking temperature that may not achieve full pasteurization —
        conservative because it predicts less kill).
        """
        temp = grounded.get("temperature_celsius")
        prov = grounded.provenance.get("temperature_celsius")

        # Resolve pending range: grounding stored the lower bound; pick the
        # conservative bound now that we know the model type.
        if prov is not None and prov.range_pending and prov.parsed_range is not None:
            temp, selection = self._select_range_bound(
                prov.parsed_range[0], prov.parsed_range[1], model_type
            )
            prov.standardization = selection
            prov.range_pending = False

        if temp is None:
            if self._is_inactivation_model(model_type):
                temp = settings.default_temperature_inactivation_conservative_c
                result.defaults_imputed.append(DefaultImputed(
                    field_name="temperature_celsius",
                    imputed_value=temp,
                    reason=(
                        "No cooking temperature specified. Using conservative "
                        f"{temp}°C (may not achieve full pasteurization)."
                    ),
                ))
            else:
                temp = settings.default_temperature_abuse_c
                result.defaults_imputed.append(DefaultImputed(
                    field_name="temperature_celsius",
                    imputed_value=temp,
                    reason=(
                        "No temperature specified. Using conservative abuse "
                        f"temperature ({temp}°C) for growth prediction."
                    ),
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
            result.warnings.append(
                f"Temperature {original}°C is outside the model's valid range "
                f"[{constraints.temp_min}, {constraints.temp_max}]°C; "
                f"clamped to {temp}°C. Prediction is at the model boundary."
            )

        return temp

    def _get_duration(
        self,
        grounded: GroundedValues,
        result: StandardizationResult,
        model_type: ModelType,
    ) -> float | None:
        """
        Get duration, passing it through unchanged.

        Mapped values (USER_INFERRED) already carry conservatism through the
        rule's chosen point — e.g., "a while" → 60 min is the upper end of
        the 30–90 min range described in the rule's notes.  No multiplier is
        applied on top of that.
        """
        duration = grounded.get("duration_minutes")
        prov = grounded.provenance.get("duration_minutes")

        # Resolve pending range before default logic.
        if prov is not None and prov.range_pending and prov.parsed_range is not None:
            duration, selection = self._select_range_bound(
                prov.parsed_range[0], prov.parsed_range[1], model_type
            )
            prov.standardization = selection
            prov.range_pending = False

        if duration is None:
            result.warnings.append("Duration is required but not specified")
            return None

        return duration

    def _get_ph(
        self,
        grounded: GroundedValues,
        result: StandardizationResult,
        constraints: ComBaseModelConstraints | None,
        model_type: ModelType,
    ) -> float:
        """
        Get pH, applying neutral default (7.0) if absent.

        Neutral pH is near-optimal for pathogen growth and provides no
        protective effect from acidity, making it conservative for all model
        types.
        """
        ph = grounded.get("ph")
        prov = grounded.provenance.get("ph")

        # Resolve pending range before validation/default logic.
        if prov is not None and prov.range_pending and prov.parsed_range is not None:
            ph, selection = self._select_range_bound(
                prov.parsed_range[0], prov.parsed_range[1], model_type
            )
            prov.standardization = selection
            prov.range_pending = False

        # Reject physically impossible values (LLM field confusion / regex mismatch)
        if ph is not None and not (0.0 <= ph <= 14.0):
            result.warnings.append(
                f"Extracted ph={ph} is outside valid range [0, 14]; "
                f"discarding and using neutral default."
            )
            ph = None

        if ph is None:
            ph = settings.default_ph_neutral
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
            result.defaults_imputed.append(DefaultImputed(
                field_name="ph",
                imputed_value=ph,
                reason=reason,
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
            result.warnings.append(
                f"pH {original} is outside the model's valid range "
                f"[{constraints.ph_min}, {constraints.ph_max}]; "
                f"clamped to {ph}. Prediction is at the model boundary."
            )

        return ph

    def _get_water_activity(
        self,
        grounded: GroundedValues,
        result: StandardizationResult,
        constraints: ComBaseModelConstraints | None,
        model_type: ModelType,
    ) -> float:
        """
        Get water activity, applying high default (0.99) if absent.

        High aw is conservative for all model types: it maximises predicted
        growth/survival, and for inactivation it does not assume any
        protective drying effect.
        """
        aw = grounded.get("water_activity")
        prov = grounded.provenance.get("water_activity")

        # Resolve pending range before validation/default logic.
        if prov is not None and prov.range_pending and prov.parsed_range is not None:
            aw, selection = self._select_range_bound(
                prov.parsed_range[0], prov.parsed_range[1], model_type
            )
            prov.standardization = selection
            prov.range_pending = False

        # Reject physically impossible values (LLM field confusion / regex mismatch)
        if aw is not None and not (0.0 <= aw <= 1.0):
            result.warnings.append(
                f"Extracted water_activity={aw} is outside valid range [0, 1]; "
                f"discarding and using conservative default."
            )
            aw = None

        if aw is None:
            aw = settings.default_water_activity
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
            result.defaults_imputed.append(DefaultImputed(
                field_name="water_activity",
                imputed_value=aw,
                reason=reason,
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
            result.warnings.append(
                f"Water activity {original} is outside the model's valid range "
                f"[{constraints.aw_min}, {constraints.aw_max}]; "
                f"clamped to {aw}. Prediction is at the model boundary."
            )

        return aw

    def _build_multi_step_profile(
        self,
        grounded: "GroundedValues",
        result: StandardizationResult,
        constraints: "ComBaseModelConstraints | None",
        model_type: ModelType,
    ) -> TimeTemperatureProfile | None:
        """
        Build a multi-step TimeTemperatureProfile from grounded.steps.

        Applies the same per-value defaults and range clamping as the
        single-step path.  Duration values pass through unchanged — mapped
        values carry their own conservatism via the rule's chosen point.

        Returns None and populates result.missing_required if any step is
        missing a duration (temperature falls back to the conservative default).
        """
        built_steps: list[TimeTemperatureStep] = []
        total_duration = 0.0

        # Sort by original step_order so physical sequence is preserved,
        # then re-number 1, 2, 3 … to satisfy TimeTemperatureProfile's
        # sequential-order validator (LLM may return gaps like [1, 2, 4]).
        ordered_steps = sorted(grounded.steps, key=lambda s: s.step_order)

        for new_order, gs in enumerate(ordered_steps, start=1):
            # --- Temperature ---
            temp = gs.temperature_celsius
            temp_prov = gs.temp_provenance

            # Resolve pending range for this step's temperature.
            if (
                temp_prov is not None
                and temp_prov.range_pending
                and temp_prov.parsed_range is not None
            ):
                temp, selection = self._select_range_bound(
                    temp_prov.parsed_range[0], temp_prov.parsed_range[1], model_type
                )
                temp_prov.standardization = selection
                temp_prov.range_pending = False

            if temp is None:
                if self._is_inactivation_model(model_type):
                    temp = settings.default_temperature_inactivation_conservative_c
                else:
                    temp = settings.default_temperature_abuse_c
                result.defaults_imputed.append(DefaultImputed(
                    field_name=f"temperature_celsius (step {gs.step_order})",
                    imputed_value=temp,
                    reason=(
                        f"Step {gs.step_order}: no temperature specified. "
                        f"Using conservative default {temp}°C."
                    ),
                ))

            if constraints and not constraints.is_temperature_valid(temp):
                original = temp
                temp = constraints.clamp_temperature(temp)
                result.range_clamps.append(RangeClamp(
                    field_name=f"temperature_celsius (step {gs.step_order})",
                    original_value=original,
                    clamped_value=temp,
                    valid_min=constraints.temp_min,
                    valid_max=constraints.temp_max,
                    reason=f"Model constraint for {model_type.value}",
                ))
                result.warnings.append(
                    f"Step {gs.step_order}: temperature {original}°C is outside the "
                    f"model's valid range [{constraints.temp_min}, {constraints.temp_max}]°C; "
                    f"clamped to {temp}°C. Prediction is at the model boundary."
                )

            # --- Duration ---
            dur = gs.duration_minutes
            dur_prov = gs.dur_provenance

            # Resolve pending range for this step's duration.
            if (
                dur_prov is not None
                and dur_prov.range_pending
                and dur_prov.parsed_range is not None
            ):
                dur, selection = self._select_range_bound(
                    dur_prov.parsed_range[0], dur_prov.parsed_range[1], model_type
                )
                dur_prov.standardization = selection
                dur_prov.range_pending = False

            if dur is None:
                result.missing_required.append(f"duration (step {gs.step_order})")
                return None

            total_duration += dur
            built_steps.append(TimeTemperatureStep(
                temperature_celsius=temp,
                duration_minutes=dur,
                step_order=new_order,
            ))

        return TimeTemperatureProfile(
            is_multi_step=True,
            steps=built_steps,
            total_duration_minutes=total_duration,
        )


# =============================================================================
# SINGLETON
# =============================================================================

_service: StandardizationService | None = None


def get_standardization_service() -> StandardizationService:
    """Get or create the global StandardizationService instance."""
    global _service
    if _service is None:
        _service = StandardizationService(model_registry=_get_engine_registry())
    return _service


def reset_standardization_service() -> None:
    """Reset the global service (for testing)."""
    global _service
    _service = None
