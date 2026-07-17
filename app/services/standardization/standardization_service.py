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

from collections.abc import Callable

from pydantic import ValidationError

from app.config import settings
from app.engines.combase.models import (
    ComBaseModel,
    ComBaseModelConstraints,
    ComBaseModelRegistry,
)
from app.models.enums import (
    ComBaseOrganism,
    Factor4Type,
    ModelType,
)
from app.models.execution.base import TimeTemperatureProfile, TimeTemperatureStep
from app.models.execution.combase import (
    ComBaseExecutionPayload,
    ComBaseModelSelection,
    ComBaseParameters,
)
from app.models.metadata import (
    CategoryBridgeInfo,
    DefaultImputed,
    RangeBoundSelection,
    RangeClamp,
    ValueSource,
)
from app.services.grounding.grounding_service import GroundedValues


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
        # Set unconditionally near the top of standardize(), before the
        # organism check, so it is populated even when organism grounding
        # fails and standardize() returns early — callers that need the
        # factor4_type used for executability (e.g. the orchestrator's
        # organism clarification gate, which needs it to derive the
        # executable-organism option set) don't have to re-derive it.
        self.factor4_type: Factor4Type = Factor4Type.NONE


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

        # Peek at which factor4 candidate would win. Pure — reads only
        # grounded data, no organism/registry dependency — so it can run
        # before the organism check and be recorded unconditionally,
        # including on the organism-missing early return below. The full
        # pick — with clamping and audit — happens once constraints are
        # known, via _get_factor4() further down; constraints depend on
        # factor4_type, so this cheap lookup runs first and is repeated
        # there (same grounded data, same winner — safe to call twice).
        factor4_type, _, _, _ = self._pick_factor4_candidate(grounded)
        result.factor4_type = factor4_type

        # Determine organism
        organism = self._get_organism(grounded)
        if organism is None:
            result.missing_required.append("organism")
            return result

        # Get model constraints if registry available
        model = None
        constraints = None
        if self._registry:
            if not self._registry.is_executable(organism, model_type, factor4_type):
                organism_name = self.organism_display_name(organism)
                result.missing_required.append(
                    f"organism ({organism_name} is not supported for "
                    f"{model_type.value.replace('_', ' ')} predictions)"
                )
                return result
            model = self._registry.get_model(organism, model_type, factor4_type)
            if model:
                constraints = model.constraints

        # Determine, clamp, and audit factor4 now that constraints (if any)
        # are known. Picks the same winner as the peek above — grounded data
        # hasn't changed — then applies the model's declared valid range.
        factor4_type, factor4_value = self._get_factor4(grounded, result, constraints)
        if result.missing_required:
            return result

        # Get and standardize pH and water activity (shared across all steps)
        ph = self._get_ph(grounded, result, constraints, model_type)
        aw = self._get_water_activity(grounded, result, constraints, model_type)
        initial_inoculum = self._get_initial_inoculum(grounded, result, model)

        if grounded.has_steps:
            # Multi-step path: build profile from per-step grounded data
            profile = self._build_multi_step_profile(
                grounded, result, constraints, model_type
            )
            if profile is None:
                return result  # missing_required already populated
            # Use first step's temperature for ComBaseParameters scalar summary.
            representative_temp = profile.steps[0].temperature_celsius
        else:
            # Single-step path
            temperature = self._get_temperature(
                grounded, result, constraints, model_type
            )
            if temperature is None:
                result.missing_required.append("temperature")
                return result

            duration = self._get_duration(grounded, result, model_type)

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
                    initial_inoculum_log_cfu=initial_inoculum,
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

    def _clamp_to_constraints(
        self,
        result: StandardizationResult,
        field_name: str,
        label: str,
        value: float,
        is_valid: Callable[[float], bool],
        clamp: Callable[[float], float],
        valid_min: float,
        valid_max: float,
        reason: str,
        unit_suffix: str = "",
    ) -> float:
        """
        Shared clamp-and-audit block for a scalar model input.

        Checks is_valid(value); if invalid, clamps via clamp(value), records a
        RangeClamp (field_name, original_value, clamped_value, valid_min,
        valid_max, reason) and a warning string on result, and returns the
        clamped value. Returns value unchanged when already valid.

        Field-specific behavior (which ComBaseModelConstraints method to call,
        the reason text, the warning's units) is entirely supplied by the
        caller, so wording is parameterised per field, not normalised across
        them — e.g. temperature's "°C" survives via unit_suffix, pH/aw's
        static "Model constraint" reason survives as a plain string.
        """
        if is_valid(value):
            return value

        original = value
        clamped_value = clamp(value)
        result.range_clamps.append(
            RangeClamp(
                field_name=field_name,
                original_value=original,
                clamped_value=clamped_value,
                valid_min=valid_min,
                valid_max=valid_max,
                reason=reason,
            )
        )
        result.warnings.append(
            f"{label} {original}{unit_suffix} is outside the model's valid range "
            f"[{valid_min}, {valid_max}]{unit_suffix}; "
            f"clamped to {clamped_value}{unit_suffix}. Prediction is at the model boundary."
        )
        return clamped_value

    # =========================================================================
    # VALUE STANDARDIZATION
    # =========================================================================

    def _get_organism(self, grounded: GroundedValues) -> ComBaseOrganism | None:
        """Get organism; returns None when not grounded (caller adds to missing_required)."""
        return grounded.get("organism")

    def organism_display_name(self, organism: ComBaseOrganism) -> str:
        """Human-readable organism name for error messages — never a short code.

        Prefers the CSV's own Org name (correct casing, e.g. "Shigella flexneri"),
        stripping a trailing factor4 qualifier ("... with nitrite(ppm)") so the
        name reads cleanly regardless of which row supplied it. Falls back to a
        title-cased enum name only if the registry has no row at all for this
        organism (should not occur for a grounded organism, but no registry
        lookup is guaranteed non-empty).
        """
        if self._registry:
            models = self._registry.get_models_for_organism(organism)
            if models:
                base = models[0].organism_name.split(" with ")[0].strip()
                if base:
                    return base
        return organism.name.replace("_", " ").title()

    def _pick_factor4_candidate(
        self, grounded: GroundedValues
    ) -> tuple[Factor4Type, str | None, float | None, list[str]]:
        """
        Pick the winning factor4 candidate from grounded environmental conditions.

        First-match-wins priority: CO2 > nitrite > lactic acid > acetic acid.
        GroundingService grounds all four independently whenever the user
        states a number for each, so more than one may be present; this picks
        exactly one to reach the model and reports the field names of the
        others, so the caller can mark them excluded rather than letting them
        sit in field_audit looking used.

        Pure lookup — no registry access, no side effects, safe to call more
        than once for the same GroundedValues.

        Returns (factor4_type, grounded_field_name, value, excluded_field_names).
        factor4_type is NONE and the rest are (None, None, []) when nothing
        was grounded.
        """
        candidates: list[tuple[Factor4Type, str]] = [
            (Factor4Type.CO2, "co2_percent"),
            (Factor4Type.NITRITE, "nitrite_ppm"),
            (Factor4Type.LACTIC_ACID, "lactic_acid_ppm"),
            (Factor4Type.ACETIC_ACID, "acetic_acid_ppm"),
        ]
        present = [(t, f) for t, f in candidates if grounded.has(f)]
        if not present:
            return Factor4Type.NONE, None, None, []

        winner_type, winner_field = present[0]
        excluded_fields = [f for _, f in present[1:]]
        return winner_type, winner_field, grounded.get(winner_field), excluded_fields

    def _get_factor4(
        self,
        grounded: GroundedValues,
        result: StandardizationResult,
        constraints: ComBaseModelConstraints | None,
    ) -> tuple[Factor4Type, float | None]:
        """
        Determine, clamp, and audit the fourth factor.

        Picks the winning grounded candidate (see _pick_factor4_candidate).
        When more than one factor4 field was grounded, records a warning
        naming the selected and excluded field(s) and marks each excluded
        field's ValueProvenance.excluded_reason, so field_audit does not
        present it as having reached the model.

        When a model constraint is available for the winning factor4_type,
        clamps the value via the shared _clamp_to_constraints helper — full
        parity with temperature/pH/aw (RangeClamp, range_clamps entry,
        warning). Bounds are read from the registry (Factor4Min/Factor4Max),
        never hardcoded.

        Fails closed via result.missing_required when the model declares a
        factor4 type but the registry has no bounds for it (Factor4Min
        and/or Factor4Max absent) — an unbounded input cannot be modelled,
        same principle as the organism-executability check above.
        Unreachable with the current CSV (all 11 factor4 rows carry both
        bounds) but not assumed impossible — bounds come from whatever
        registry is loaded, so a future engine's CSV is handled the same way.
        """
        factor4_type, field_name, factor4_value, excluded_fields = (
            self._pick_factor4_candidate(grounded)
        )

        if excluded_fields:
            excluded_desc = ", ".join(f"{f}={grounded.get(f)}" for f in excluded_fields)
            result.warnings.append(
                f"Multiple fourth-factor values grounded ({field_name}={factor4_value} "
                f"and {excluded_desc}); only {field_name} reaches the model "
                f"(priority: CO2 > nitrite > lactic acid > acetic acid)."
            )
            for excluded_field in excluded_fields:
                excluded_prov = grounded.provenance.get(excluded_field)
                if excluded_prov is not None:
                    excluded_prov.excluded_reason = (
                        f"Grounded but not used — {field_name} took priority "
                        f"(CO2 > nitrite > lactic acid > acetic acid)."
                    )

        if factor4_type == Factor4Type.NONE or constraints is None:
            return factor4_type, factor4_value

        # Invariant: _pick_factor4_candidate() only returns a non-NONE
        # factor4_type alongside a real field_name/value pair — never one
        # without the other. Asserted (not just commented) so the type
        # narrowing below is checked, not assumed.
        assert field_name is not None and factor4_value is not None

        if constraints.factor4_min is None or constraints.factor4_max is None:
            result.missing_required.append(
                f"{field_name} (no declared valid range for {factor4_type.value} "
                f"— cannot bound the input, not modelled)"
            )
            return factor4_type, factor4_value

        factor4_value = self._clamp_to_constraints(
            result,
            field_name=field_name,
            label=field_name.replace("_", " "),
            value=factor4_value,
            is_valid=constraints.is_factor4_valid,
            clamp=constraints.clamp_factor4,
            valid_min=constraints.factor4_min,
            valid_max=constraints.factor4_max,
            reason="Model constraint",
        )
        return factor4_type, factor4_value

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
                result.defaults_imputed.append(
                    DefaultImputed(
                        field_name="temperature_celsius",
                        imputed_value=temp,
                        reason=(
                            "No cooking temperature specified. Using conservative "
                            f"{temp}°C (may not achieve full pasteurization)."
                        ),
                    )
                )
            else:
                temp = settings.default_temperature_abuse_c
                result.defaults_imputed.append(
                    DefaultImputed(
                        field_name="temperature_celsius",
                        imputed_value=temp,
                        reason=(
                            "No temperature specified. Using conservative abuse "
                            f"temperature ({temp}°C) for growth prediction."
                        ),
                    )
                )

        # Clamp to valid range if constraints available
        if constraints:
            temp = self._clamp_to_constraints(
                result,
                field_name="temperature_celsius",
                label="Temperature",
                value=temp,
                is_valid=constraints.is_temperature_valid,
                clamp=constraints.clamp_temperature,
                valid_min=constraints.temp_min,
                valid_max=constraints.temp_max,
                reason=f"Model constraint for {model_type.value}",
                unit_suffix="°C",
            )

        return temp

    def _get_duration(
        self,
        grounded: GroundedValues,
        result: StandardizationResult,
        model_type: ModelType,
    ) -> float:
        """
        Get duration, passing it through unchanged.

        Mapped values (USER_INFERRED) already carry conservatism through the
        rule's chosen point — e.g., "a while" → 60 min is the upper end of
        the 30–90 min range described in the rule's notes.  No multiplier is
        applied on top of that.

        When no duration is specified for a single-step scenario, applies a
        long-window default (settings.default_long_window_minutes, 7 days by
        default) so the prediction trajectory reaches the physical growth cap.
        The Result Interpretation Module will slice meaningful sub-windows.
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
            duration = float(settings.default_long_window_minutes)
            result.defaults_imputed.append(
                DefaultImputed(
                    field_name="duration_minutes",
                    imputed_value=duration,
                    reason=(
                        f"No duration specified. Using long-window default "
                        f"({int(duration / 60)} hours / {int(duration / 1440)} days) to ensure "
                        "the prediction trajectory reaches the physical growth cap. "
                        "The Result Interpretation Module will identify actionable sub-windows."
                    ),
                    source=ValueSource.LONG_WINDOW_DEFAULT,
                )
            )
            result.warnings.append(
                f"Duration not specified — long-window default applied "
                f"({int(duration / 60)} hours / {int(duration / 1440)} days). "
                "Prediction shows full growth trajectory to physical cap; "
                "sub-window analysis required for actionable interpretation."
            )

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
            bridge_attempt: CategoryBridgeInfo | None = grounded.bridge_attempts.get(
                "ph"
            )
            composite_keyword = grounded.composite_skip.get("ph")
            if composite_keyword is not None:
                reason = (
                    f"Composite-food guard fired (matched: '{composite_keyword}'). "
                    f"pH retrieval skipped — composite dishes cannot be reliably grounded "
                    f"against single-ingredient documents. Using neutral default (conservative)."
                )
            elif bridge_attempt:
                state_clause = (
                    f" (state: '{bridge_attempt.query_state}')"
                    if bridge_attempt.query_state
                    else ""
                )
                reason = (
                    f"No pH specified. Bridge resolved food to category "
                    f"'{bridge_attempt.resolved_category}'{state_clause} but no curated "
                    f"pH data is available for that category/state. Using neutral default "
                    f"pH (7.0) — near-optimal for pathogen growth (conservative)."
                )
            elif self._is_inactivation_model(model_type):
                reason = (
                    "No pH specified. Using neutral pH (7.0) which provides "
                    "no additional thermal protection (conservative for cooking)."
                )
            else:
                reason = (
                    "No pH specified. Using neutral default which is near-optimal "
                    "for pathogen growth (conservative)."
                )
            result.defaults_imputed.append(
                DefaultImputed(
                    field_name="ph",
                    imputed_value=ph,
                    reason=reason,
                )
            )

        # Clamp to valid range
        if constraints:
            ph = self._clamp_to_constraints(
                result,
                field_name="ph",
                label="pH",
                value=ph,
                is_valid=constraints.is_ph_valid,
                clamp=constraints.clamp_ph,
                valid_min=constraints.ph_min,
                valid_max=constraints.ph_max,
                reason="Model constraint",
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
            bridge_attempt = grounded.bridge_attempts.get("water_activity")
            composite_keyword = grounded.composite_skip.get("water_activity")
            if composite_keyword is not None:
                reason = (
                    f"Composite-food guard fired (matched: '{composite_keyword}'). "
                    f"Water activity retrieval skipped — composite dishes cannot be reliably "
                    f"grounded against single-ingredient documents. Using conservative "
                    f"high default (0.99) — maximizes predicted growth."
                )
            elif bridge_attempt:
                state_clause = (
                    f" (state: '{bridge_attempt.query_state}')"
                    if bridge_attempt.query_state
                    else ""
                )
                reason = (
                    f"No water activity specified. Bridge resolved food to category "
                    f"'{bridge_attempt.resolved_category}'{state_clause} but no curated "
                    f"aw data is available for that category/state. Using conservative "
                    f"high default (0.99) — maximizes predicted growth."
                )
            elif self._is_inactivation_model(model_type):
                reason = (
                    "No water activity specified. Using high default (0.99) "
                    "which doesn't assume any protective effect from low aw."
                )
            else:
                reason = (
                    "No water activity specified. Using conservative high "
                    "default (0.99) which maximizes predicted growth."
                )
            result.defaults_imputed.append(
                DefaultImputed(
                    field_name="water_activity",
                    imputed_value=aw,
                    reason=reason,
                )
            )

        # Clamp to valid range
        if constraints:
            aw = self._clamp_to_constraints(
                result,
                field_name="water_activity",
                label="Water activity",
                value=aw,
                is_valid=constraints.is_aw_valid,
                clamp=constraints.clamp_aw,
                valid_min=constraints.aw_min,
                valid_max=constraints.aw_max,
                reason="Model constraint",
            )

        return aw

    def _get_initial_inoculum(
        self,
        grounded: GroundedValues,
        result: StandardizationResult,
        model: "ComBaseModel | None",
    ) -> float:
        """
        Get initial inoculum (log10 CFU/g), applying model-specific default if absent.

        If the user supplied a value, use it directly (USER_EXPLICIT provenance
        is already recorded in grounded).  If absent, default to the model's
        DefaultInoc value, which reflects the experimental conditions under which
        the ComBase model was fitted.  Fallback is 3.0 when no model is available.
        """
        value = grounded.get("initial_inoculum_log_cfu")

        # Guard: discard physically implausible values (LLM field confusion)
        if value is not None and not (-2.0 <= value <= 16.0):
            result.warnings.append(
                f"Extracted initial_inoculum_log_cfu={value} is outside plausible "
                f"log CFU range [-2, 16]; discarding and using model default."
            )
            value = None

        if value is not None:
            return value

        inoculum = model.defaults.inoculum if model is not None else 3.0
        result.defaults_imputed.append(
            DefaultImputed(
                field_name="initial_inoculum_log_cfu",
                imputed_value=inoculum,
                reason=(
                    f"No initial inoculum specified. Using model default "
                    f"({inoculum} log CFU/g) from ComBase DefaultInoc."
                    if model is not None
                    else "No initial inoculum specified. Using fallback default (3.0 log CFU/g)."
                ),
            )
        )
        return inoculum

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
                result.defaults_imputed.append(
                    DefaultImputed(
                        field_name=f"temperature_celsius (step {gs.step_order})",
                        imputed_value=temp,
                        reason=(
                            f"Step {gs.step_order}: no temperature specified. "
                            f"Using conservative default {temp}°C."
                        ),
                    )
                )

            if constraints and not constraints.is_temperature_valid(temp):
                original = temp
                temp = constraints.clamp_temperature(temp)
                result.range_clamps.append(
                    RangeClamp(
                        field_name=f"temperature_celsius (step {gs.step_order})",
                        original_value=original,
                        clamped_value=temp,
                        valid_min=constraints.temp_min,
                        valid_max=constraints.temp_max,
                        reason=f"Model constraint for {model_type.value}",
                    )
                )
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
            built_steps.append(
                TimeTemperatureStep(
                    temperature_celsius=temp,
                    duration_minutes=dur,
                    step_order=new_order,
                )
            )

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
