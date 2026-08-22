"""
Unit tests for factor4 (fourth-factor) clamping, auditing, and fail-closed
behavior in StandardizationService.

Factor4 had zero test coverage before this file — no test, fixture, or query
anywhere in the repo exercised it. These are the first.
"""

from pathlib import Path

import pytest

from app.models.metadata import ValueSource
from app.services.grounding.grounding_service import GroundedValues
from app.services.standardization.standardization_service import (
    StandardizationService,
)
from predictive.engines.combase.models import (
    ComBaseModel,
    ComBaseModelConstraints,
    ComBaseModelDefaults,
    ComBaseModelRegistry,
)
from predictive.models.enums import ComBaseOrganism, Factor4Type, ModelType

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def real_registry() -> ComBaseModelRegistry:
    """Real registry loaded from data/combase_models.csv."""
    reg = ComBaseModelRegistry()
    csv_path = Path("data/combase_models.csv")
    if csv_path.exists():
        reg.load_from_csv(csv_path)
    return reg


def make_synthetic_registry(
    factor4_min: float | None, factor4_max: float | None
) -> ComBaseModelRegistry:
    """
    A registry with exactly one synthetic model: Salmonella growth with a
    NITRITE factor4, whose bounds are controlled by the caller.

    Built by hand (no CSV read) so the "no declared bounds" case can be
    exercised without editing data/combase_models.csv — that combination
    does not exist in the current CSV (all 11 factor4 rows carry both
    bounds) but must still be handled, since a future engine's CSV is not
    this one.
    """
    registry = ComBaseModelRegistry()
    constraints = ComBaseModelConstraints(
        temp_min=5.0,
        temp_max=45.0,
        ph_min=4.0,
        ph_max=9.0,
        aw_min=0.90,
        aw_max=1.0,
        factor4_min=factor4_min,
        factor4_max=factor4_max,
    )
    defaults = ComBaseModelDefaults(
        temp=20.0, ph=7.0, aw=0.99, nacl=0.5, factor4=None, inoculum=3.0
    )
    model = ComBaseModel(
        model_id=1,
        organism_id="ss",
        organism_name="Salmonellae with nitrite(ppm)",
        model_type=ModelType.GROWTH,
        factor4_type=Factor4Type.NITRITE,
        y_max=10.0,
        h0=1.0,
        coefficients=[0.0] * 15,
        constraints=constraints,
        defaults=defaults,
        std_err=0.3,
        h0_std_err=0.5,
    )
    registry._register_model(model)
    return registry


def make_grounded(
    *, organism: ComBaseOrganism = ComBaseOrganism.SALMONELLA, **factor4_fields
) -> GroundedValues:
    """GroundedValues with organism + temperature/pH/aw/duration filled in so
    standardize() reaches the factor4 logic, plus whichever factor4_fields
    (co2_percent=, nitrite_ppm=, ...) the caller supplies."""
    grounded = GroundedValues()
    grounded.set("organism", organism, ValueSource.USER_EXPLICIT)
    grounded.set("temperature_celsius", 25.0, ValueSource.USER_EXPLICIT)
    grounded.set("duration_minutes", 180.0, ValueSource.USER_EXPLICIT)
    grounded.set("ph", 7.0, ValueSource.USER_EXPLICIT)
    grounded.set("water_activity", 0.99, ValueSource.USER_EXPLICIT)
    for field, value in factor4_fields.items():
        grounded.set(field, value, ValueSource.USER_EXPLICIT)
    return grounded


# =============================================================================
# Clamping — nitrite above the model's max
# =============================================================================


class TestFactor4Clamping:
    def test_nitrite_above_max_is_clamped(self, real_registry: ComBaseModelRegistry):
        """Salmonella + nitrite: real CSV bounds are [0, 200]. 500ppm must be
        clamped to 200, recorded as a RangeClamp, and the payload must still
        build (polynomial evaluated at the boundary, not refused)."""
        if len(real_registry) == 0:
            pytest.skip("combase_models.csv not found")

        service = StandardizationService(model_registry=real_registry)
        grounded = make_grounded(nitrite_ppm=500.0)

        result = service.standardize(grounded, model_type=ModelType.GROWTH)

        assert result.missing_required == [], result.missing_required
        assert result.payload is not None, result.warnings
        assert result.payload.parameters.factor4_value == 200.0
        assert result.payload.parameters.factor4_type == Factor4Type.NITRITE

        clamps = [c for c in result.range_clamps if c.field_name == "nitrite_ppm"]
        assert len(clamps) == 1
        clamp = clamps[0]
        assert clamp.original_value == 500.0
        assert clamp.clamped_value == 200.0
        assert clamp.valid_min == 0.0
        assert clamp.valid_max == 200.0

        assert any(
            "nitrite" in w.lower() and "clamped to 200" in w for w in result.warnings
        ), result.warnings

    def test_nitrite_within_range_not_clamped(
        self, real_registry: ComBaseModelRegistry
    ):
        """A value already inside [0, 200] must pass through unchanged, with
        no RangeClamp and no clamp warning."""
        if len(real_registry) == 0:
            pytest.skip("combase_models.csv not found")

        service = StandardizationService(model_registry=real_registry)
        grounded = make_grounded(nitrite_ppm=50.0)

        result = service.standardize(grounded, model_type=ModelType.GROWTH)

        assert result.missing_required == []
        assert result.payload is not None
        assert result.payload.parameters.factor4_value == 50.0
        assert all(c.field_name != "nitrite_ppm" for c in result.range_clamps)
        assert not any(
            "nitrite" in w.lower() and "clamped" in w for w in result.warnings
        )


# =============================================================================
# Multiple grounded candidates — excluded ones must not read as used
# =============================================================================


class TestFactor4Exclusion:
    def test_co2_and_nitrite_grounded_co2_wins(
        self, real_registry: ComBaseModelRegistry
    ):
        """CO2 > nitrite priority: when both are grounded, only CO2 reaches
        the model. The excluded field's provenance must carry excluded_reason
        so field_audit does not present it as used; the warning must name
        both the selected and excluded field."""
        if len(real_registry) == 0:
            pytest.skip("combase_models.csv not found")

        service = StandardizationService(model_registry=real_registry)
        grounded = make_grounded(co2_percent=10.0, nitrite_ppm=50.0)

        result = service.standardize(grounded, model_type=ModelType.GROWTH)

        assert result.missing_required == [], result.missing_required
        assert result.payload is not None, result.warnings
        assert result.payload.parameters.factor4_type == Factor4Type.CO2
        assert result.payload.parameters.factor4_value == 10.0

        # Selected field's provenance is untouched.
        assert grounded.provenance["co2_percent"].excluded_reason is None
        # Excluded field is marked, naming why.
        excluded_reason = grounded.provenance["nitrite_ppm"].excluded_reason
        assert excluded_reason is not None
        assert "co2" in excluded_reason.lower()

        assert any(
            "co2_percent" in w and "nitrite_ppm" in w for w in result.warnings
        ), result.warnings

    def test_single_factor4_grounded_no_exclusion_marker(
        self, real_registry: ComBaseModelRegistry
    ):
        """When only one factor4 candidate is grounded, nothing is excluded --
        no warning, no excluded_reason anywhere."""
        if len(real_registry) == 0:
            pytest.skip("combase_models.csv not found")

        service = StandardizationService(model_registry=real_registry)
        grounded = make_grounded(nitrite_ppm=50.0)

        result = service.standardize(grounded, model_type=ModelType.GROWTH)

        assert result.missing_required == []
        assert grounded.provenance["nitrite_ppm"].excluded_reason is None
        assert not any("Multiple fourth-factor" in w for w in result.warnings)


# =============================================================================
# Fail closed — model declares a factor4 type but no bounds (synthetic only)
# =============================================================================


class TestFactor4MissingBoundsFailsClosed:
    def test_no_declared_bounds_fails_closed(self):
        """A model row that declares NITRITE but has no Factor4Min/Factor4Max
        cannot be bounded, so it must not be modelled -- same fail-closed
        principle as organism executability. Unreachable with the real CSV
        (all 11 factor4 rows carry both bounds); exercised here with a
        synthetic registry, per instruction not to edit the CSV."""
        registry = make_synthetic_registry(factor4_min=None, factor4_max=None)
        service = StandardizationService(model_registry=registry)
        grounded = make_grounded(nitrite_ppm=50.0)

        result = service.standardize(grounded, model_type=ModelType.GROWTH)

        assert result.payload is None
        assert result.missing_required, "must fail closed, not silently proceed"
        assert any(
            "nitrite_ppm" in m and "no declared valid range" in m
            for m in result.missing_required
        ), result.missing_required
        # Plain language, not a short code.
        assert not any("nitrite / growth" in m for m in result.missing_required)

    def test_partial_bounds_also_fails_closed(self):
        """Only one of Factor4Min/Factor4Max present is just as unbounded as
        neither -- must still fail closed."""
        registry = make_synthetic_registry(factor4_min=0.0, factor4_max=None)
        service = StandardizationService(model_registry=registry)
        grounded = make_grounded(nitrite_ppm=50.0)

        result = service.standardize(grounded, model_type=ModelType.GROWTH)

        assert result.payload is None
        assert result.missing_required

    def test_declared_bounds_execute_normally(self):
        """Sanity check on the synthetic registry itself: when bounds ARE
        declared, standardize() succeeds normally (isolates the fail-closed
        assertions above from a broken fixture)."""
        registry = make_synthetic_registry(factor4_min=0.0, factor4_max=200.0)
        service = StandardizationService(model_registry=registry)
        grounded = make_grounded(nitrite_ppm=50.0)

        result = service.standardize(grounded, model_type=ModelType.GROWTH)

        assert result.missing_required == []
        assert result.payload is not None
        assert result.payload.parameters.factor4_value == 50.0


# =============================================================================
# field_audit surfaces excluded_reason end to end
# =============================================================================


class TestFactor4FieldAuditParity:
    def test_excluded_reason_reaches_field_audit(
        self, real_registry: ComBaseModelRegistry
    ):
        """The excluded_reason set on ValueProvenance during standardization
        must actually reach FieldAuditEntry via _build_field_audit() -- not
        just sit on the internal provenance object."""
        if len(real_registry) == 0:
            pytest.skip("combase_models.csv not found")

        from unittest.mock import MagicMock

        from app.api.routes.translation import _build_field_audit

        service = StandardizationService(model_registry=real_registry)
        grounded = make_grounded(co2_percent=10.0, nitrite_ppm=50.0)
        std_result = service.standardize(grounded, model_type=ModelType.GROWTH)
        assert std_result.payload is not None

        # Minimal TranslationResult-shaped stand-in: _build_field_audit only
        # reads .metadata and .state.grounded_values.
        fake_metadata = MagicMock()
        fake_metadata.provenance = grounded.provenance
        fake_metadata.range_clamps = std_result.range_clamps
        fake_metadata.retrievals = []
        fake_metadata.combase_model = None

        fake_result = MagicMock()
        fake_result.metadata = fake_metadata
        fake_result.state.grounded_values = grounded.values

        field_audit = _build_field_audit(fake_result)

        assert field_audit["co2_percent"].excluded_reason is None
        assert field_audit["nitrite_ppm"].excluded_reason is not None
        assert "co2" in field_audit["nitrite_ppm"].excluded_reason.lower()
