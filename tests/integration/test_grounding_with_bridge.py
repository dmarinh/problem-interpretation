"""
Integration tests — GroundingService with Tier 3 TaxonomyBridge enabled.

These tests exercise the full grounding flow (Tier 1 → Tier 2 → Tier 3 bridge)
using a real TaxonomyBridge (loading production CSV data) and a mock retrieval
service.  The mock lets us precisely control which tier "hits" for each
food description without requiring a live ChromaDB instance.

Test scenarios
--------------
C1-like  Turkey portions: Tiers 1/2 both miss → bridge fires.
         pH resolves via 'chicken' food_properties row (IFT-2003-T33).
         aw resolves via 'fresh poultry' food_properties row (IFT-2003-T31).
         Verified per-field and independently (they come from different rows).

B1-like  Fresh chicken portions: Tier 1 misses, Tier 2 hits for both pH and aw.
         Bridge must NOT fire for either field.
         Regression-coupling check: if Tier 2 silently regresses for chicken, the
         assertion field_audit.ph.source == rag_retrieval_fallback will fail loudly
         before the bridge can silently compensate.

B2-like  Chicken soup: composite blocklist returns None before any matching runs.
         Both ph and aw remain ungrounded after all three tiers.
         (Conservative defaults are applied downstream in StandardizationService,
         not here; this test only checks the grounding layer.)

Beef     'beef' resolves via alias (beef → bovine) → meat category.
         pH found in meat food_properties rows (beef ground, etc.).
         aw found in meat food_properties rows (fresh meat row).

Audit-honesty — bridge attempted, field data absent
     When the bridge resolves a category that has no rows for a given field,
     the GroundedValues object must record a bridge_attempt on that field so
     StandardizationService can mention it in the DefaultImputed reason.
     Verified with a synthetic scenario (shellfish category has pH rows but no aw).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.enums import ComBaseOrganism, ModelType
from app.models.extraction import (
    ExtractedDuration,
    ExtractedEnvironmentalConditions,
    ExtractedScenario,
    ExtractedTemperature,
)
from app.models.metadata import ValueSource
from app.services.grounding.grounding_service import GroundedValues, GroundingService
from app.services.grounding.taxonomy_bridge import TaxonomyBridge
from app.services.standardization.standardization_service import StandardizationService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_scenario(food_description: str) -> ExtractedScenario:
    """Minimal ExtractedScenario with only food_description set.

    Temperature and duration are left unspecified so the tests can focus
    exclusively on the food-property grounding path.
    """
    return ExtractedScenario(
        food_description=food_description,
        food_state=None,
        pathogen_mentioned=None,
        is_multi_step=False,
        single_step_temperature=ExtractedTemperature(value_celsius=13.0),
        single_step_duration=ExtractedDuration(value_minutes=600.0),
        time_temperature_steps=[],
        environmental_conditions=ExtractedEnvironmentalConditions(),
        concern_type="safety",
        additional_context=None,
        is_cooking_scenario=False,
        is_storage_scenario=True,
        is_non_thermal_treatment=False,
        implied_model_type=None,
    )


def make_no_hit_response(query: str = "") -> MagicMock:
    """RetrievalResponse with no confident result — simulates both Tier 1 and Tier 2 missing."""
    r = MagicMock()
    r.has_confident_result = False
    r.results = []
    r.top_result = None
    r.query = query
    r.reranker_used = None
    r.threshold = 0.62
    return r


def make_confident_response(
    content: str, query: str, doc_id: str, source_id: str = ""
) -> MagicMock:
    """RetrievalResponse with one confident result — simulates a Tier 2 hit."""
    top = MagicMock()
    top.doc_id = doc_id
    top.content = content
    top.source = "food_properties"
    top.distance = None  # suppresses isinstance checks in _build_retrieval_metadata
    top.rerank_score = None
    top.metadata = {"source_id": source_id}

    r = MagicMock()
    r.has_confident_result = True
    r.top_result = top
    r.results = [top]
    r.query = query
    r.reranker_used = None
    r.threshold = 0.62
    return r


@pytest.fixture
def real_bridge() -> TaxonomyBridge:
    """Production TaxonomyBridge loading the real food_taxonomy.csv and food_properties.csv."""
    return TaxonomyBridge()


@pytest.fixture
def mock_retrieval() -> MagicMock:
    """Retrieval service mock with all queries returning no confident result by default."""
    m = MagicMock()
    m.query_food_properties.return_value = make_no_hit_response()
    m.query_food_ph.return_value = make_no_hit_response()
    m.query_food_water_activity.return_value = make_no_hit_response()
    m.query_pathogen_hazards.return_value = make_no_hit_response()
    m.get_hazards_for_food.return_value = []
    return m


@pytest.fixture
def grounding_service(
    mock_retrieval: MagicMock, real_bridge: TaxonomyBridge
) -> GroundingService:
    """GroundingService wired with mock retrieval and real TaxonomyBridge."""
    return GroundingService(
        retrieval_service=mock_retrieval,
        llm_client=AsyncMock(),
        use_llm_extraction=False,
        taxonomy_bridge=real_bridge,
    )


# ---------------------------------------------------------------------------
# C1-like: turkey → bridge fires → split property rows
# ---------------------------------------------------------------------------


class TestTurkeyBridgeResolution:
    """C1-like scenario: 'turkey portions' with both Tier 1 and Tier 2 missing.

    With the state-aware curated lookup, the bridge supplies aw (poultry+fresh+aw
    row exists) but NOT pH (no curated pH row for poultry — pH tests moved to
    TestTurkeyPhNoCuratedRow).
    """

    @pytest.mark.asyncio
    async def test_aw_resolved_via_bridge(
        self, grounding_service: GroundingService
    ) -> None:
        """aw should be set with source RAG_RETRIEVAL_CATEGORY_BRIDGE after bridge fires."""
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("turkey portions", grounded)

        assert grounded.has("water_activity")
        assert (
            grounded.provenance["water_activity"].source
            == ValueSource.RAG_RETRIEVAL_CATEGORY_BRIDGE
        )

    @pytest.mark.asyncio
    async def test_aw_category_bridge_points_to_fresh_poultry_row(
        self, grounding_service: GroundingService
    ) -> None:
        """aw audit block: bridge resolved turkey → poultry+fresh → fresh poultry row (IFT-2003-T31).

        query_state records the state used for the curated lookup.
        assumed_state is empty because turkey was explicitly 'fresh' in the taxonomy
        (A01SQ) — no state-default assumption was applied.
        """
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("turkey portions", grounded)

        aw_bridge = grounded.provenance["water_activity"].category_bridge
        assert aw_bridge is not None
        assert aw_bridge.species == "turkey portions"
        assert aw_bridge.resolved_category == "poultry"
        assert aw_bridge.taxonomy_code == "A01SQ"
        assert aw_bridge.matched_food_name == "turkey"
        # Curated row supplying aw for poultry+fresh
        assert aw_bridge.property_row_food_name == "fresh poultry"
        assert "IFT-2003-T31" in aw_bridge.property_row_source_ids
        # State audit: taxonomy said "fresh"; no assumption needed
        assert aw_bridge.query_state == "fresh"
        assert aw_bridge.assumed_state == ""  # no conversion applied

    @pytest.mark.asyncio
    async def test_aw_value_is_in_fresh_poultry_aw_range(
        self, grounding_service: GroundingService
    ) -> None:
        """aw stored is the lower bound of the fresh-poultry range [0.99, 1.0]."""
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("turkey portions", grounded)

        aw_prov = grounded.provenance["water_activity"]
        assert aw_prov.parsed_range == pytest.approx([0.99, 1.0])
        assert aw_prov.range_pending is True


# ---------------------------------------------------------------------------
# B1-like: fresh chicken portions → Tier 2 hits → bridge does NOT fire
# ---------------------------------------------------------------------------


class TestChickenTier2NoBridge:
    """B1 regression-coupling check.

    Tier 2 succeeds for both pH and aw when given confident mock responses.
    The bridge must not fire or overwrite these fields.

    If Tier 2 silently regresses (stops returning confident results for chicken),
    the assertions on source == RAG_RETRIEVAL_FALLBACK will fail loudly rather
    than silently falling through to bridge-supplied values.
    """

    @pytest.fixture
    def chicken_retrieval(self, mock_retrieval: MagicMock) -> MagicMock:
        """Configure mock so Tier 2 hits for chicken pH and aw."""
        mock_retrieval.query_food_ph.return_value = make_confident_response(
            content="chicken (poultry): pH range 6.2 to 6.4. Raw chicken [IFT-2003-T33]",
            query="fresh chicken portions pH acidity",
            doc_id="food_properties_12",
            source_id="IFT-2003-T33",
        )
        mock_retrieval.query_food_water_activity.return_value = make_confident_response(
            content="fresh poultry (poultry): water activity 0.99 to 1.0. All fresh poultry [IFT-2003-T31]",
            query="fresh chicken portions water activity aw moisture",
            doc_id="food_properties_24",
            source_id="IFT-2003-T31",
        )
        return mock_retrieval

    @pytest.mark.asyncio
    async def test_ph_source_is_rag_retrieval_fallback_not_bridge(
        self, grounding_service: GroundingService, chicken_retrieval: MagicMock
    ) -> None:
        """pH must come from Tier 2 (RAG_RETRIEVAL_FALLBACK), not from the bridge."""
        grounded = GroundedValues()
        await grounding_service._ground_food_properties(
            "fresh chicken portions", grounded
        )

        assert grounded.has("ph")
        assert grounded.provenance["ph"].source == ValueSource.RAG_RETRIEVAL_FALLBACK

    @pytest.mark.asyncio
    async def test_ph_category_bridge_is_none(
        self, grounding_service: GroundingService, chicken_retrieval: MagicMock
    ) -> None:
        """category_bridge must be None when Tier 2 succeeded — bridge never ran for ph."""
        grounded = GroundedValues()
        await grounding_service._ground_food_properties(
            "fresh chicken portions", grounded
        )

        assert grounded.provenance["ph"].category_bridge is None

    @pytest.mark.asyncio
    async def test_aw_source_is_rag_retrieval_fallback_not_bridge(
        self, grounding_service: GroundingService, chicken_retrieval: MagicMock
    ) -> None:
        """aw must come from Tier 2 (RAG_RETRIEVAL_FALLBACK), not from the bridge."""
        grounded = GroundedValues()
        await grounding_service._ground_food_properties(
            "fresh chicken portions", grounded
        )

        assert grounded.has("water_activity")
        assert (
            grounded.provenance["water_activity"].source
            == ValueSource.RAG_RETRIEVAL_FALLBACK
        )

    @pytest.mark.asyncio
    async def test_aw_category_bridge_is_none(
        self, grounding_service: GroundingService, chicken_retrieval: MagicMock
    ) -> None:
        """category_bridge must be None when Tier 2 succeeded — bridge never ran for aw."""
        grounded = GroundedValues()
        await grounding_service._ground_food_properties(
            "fresh chicken portions", grounded
        )

        assert grounded.provenance["water_activity"].category_bridge is None


# ---------------------------------------------------------------------------
# B2-like: chicken soup → composite blocklist → fields remain ungrounded
# ---------------------------------------------------------------------------


class TestChickenSoupCompositeMiss:
    """B2-like scenario: 'chicken soup' is blocked before bridge matching runs.

    After all three tiers the fields should be ungrounded; the bridge must not
    resolve 'chicken soup' to the poultry category even though 'chicken' alone
    would score 100 in fuzzy matching.
    """

    @pytest.mark.asyncio
    async def test_ph_not_grounded_for_chicken_soup(
        self, grounding_service: GroundingService
    ) -> None:
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("chicken soup", grounded)
        assert not grounded.has("ph")

    @pytest.mark.asyncio
    async def test_aw_not_grounded_for_chicken_soup(
        self, grounding_service: GroundingService
    ) -> None:
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("chicken soup", grounded)
        assert not grounded.has("water_activity")


# ---------------------------------------------------------------------------
# Beef → alias resolution through the full grounding path
# ---------------------------------------------------------------------------


class TestBeefAliasResolution:
    """'beef' resolves via alias (beef → bovine) → meat category, state='fresh'.

    With state-aware curated lookup:
    - aw: meat+fresh+aw curated row exists → bridge supplies aw
    - pH: no curated pH row for meat → bridge records an attempt, pH falls
      through to conservative default (see TestBeefPhNoCuratedRow in this class)
    """

    @pytest.mark.asyncio
    async def test_aw_resolved_via_bridge_for_beef(
        self, grounding_service: GroundingService
    ) -> None:
        """Meat+fresh+aw curated row (fresh meat, IFT-2003-T31) supplies aw for beef."""
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("beef", grounded)

        assert grounded.has("water_activity")
        assert (
            grounded.provenance["water_activity"].source
            == ValueSource.RAG_RETRIEVAL_CATEGORY_BRIDGE
        )

    @pytest.mark.asyncio
    async def test_aw_category_bridge_records_category_meat(
        self, grounding_service: GroundingService
    ) -> None:
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("beef", grounded)

        aw_bridge = grounded.provenance["water_activity"].category_bridge
        assert aw_bridge is not None
        assert aw_bridge.resolved_category == "meat"
        assert aw_bridge.species == "beef"

    @pytest.mark.asyncio
    async def test_ph_not_grounded_via_bridge_for_beef(
        self, grounding_service: GroundingService
    ) -> None:
        """No curated pH row exists for meat+fresh; bridge must NOT set pH."""
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("beef", grounded)

        assert not grounded.has("ph")

    @pytest.mark.asyncio
    async def test_ph_bridge_attempt_recorded_for_beef(
        self, grounding_service: GroundingService
    ) -> None:
        """Bridge resolved beef → meat but found no curated pH row; attempt recorded."""
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("beef", grounded)

        assert "ph" in grounded.bridge_attempts
        assert grounded.bridge_attempts["ph"].resolved_category == "meat"
        assert grounded.bridge_attempts["ph"].species == "beef"


# ---------------------------------------------------------------------------
# Audit-honesty: bridge attempted but category has no data for that field
# ---------------------------------------------------------------------------


class TestBridgeAttemptedNoData:
    """When the bridge resolves a category that has no rows supplying a particular
    field, the GroundedValues must record the bridge attempt for that field.

    This lets StandardizationService mention the attempt in the DefaultImputed
    reason rather than emitting the silent 'no value found, default applied'.

    Test vehicle: 'lobster' — taxonomy resolves to shellfish.  shellfish has
    no curated rows in category_level_rows.csv (only 5 curated rows exist,
    none for shellfish), so neither pH nor aw is resolved and both fields
    must appear in bridge_attempts.
    """

    @pytest.mark.asyncio
    async def test_shellfish_ph_not_grounded(
        self, grounding_service: GroundingService
    ) -> None:
        """No curated pH row for shellfish; pH must remain ungrounded."""
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("lobster", grounded)

        assert not grounded.has("ph")

    @pytest.mark.asyncio
    async def test_shellfish_ph_bridge_attempt_recorded(
        self, grounding_service: GroundingService
    ) -> None:
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("lobster", grounded)

        assert "ph" in grounded.bridge_attempts
        assert grounded.bridge_attempts["ph"].resolved_category == "shellfish"
        assert grounded.bridge_attempts["ph"].species == "lobster"

    @pytest.mark.asyncio
    async def test_shellfish_aw_not_grounded_but_bridge_attempt_recorded(
        self, grounding_service: GroundingService
    ) -> None:
        """No curated aw row for shellfish; grounded.has('water_activity') must be False,
        and bridge_attempts['water_activity'] must record the attempted resolution."""
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("lobster", grounded)

        assert not grounded.has("water_activity")
        assert "water_activity" in grounded.bridge_attempts
        attempt = grounded.bridge_attempts["water_activity"]
        assert attempt.resolved_category == "shellfish"
        assert attempt.species == "lobster"


# ---------------------------------------------------------------------------
# Turkey pH — bridge fires but no curated pH row for poultry
# ---------------------------------------------------------------------------


class TestTurkeyPhNoCuratedRow:
    """The curated rows include fresh-poultry aw but no poultry pH row.

    When the bridge resolves turkey → poultry and finds no curated pH row,
    it must:
    - NOT set grounded.ph (pH stays ungrounded, falls to conservative default)
    - Record a bridge_attempt on 'ph' so the downstream DefaultImputed reason
      can say "bridge resolved to poultry, no pH data available" rather than
      a silent "no value found".
    """

    @pytest.mark.asyncio
    async def test_turkey_ph_not_grounded_via_bridge(
        self, grounding_service: GroundingService
    ) -> None:
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("turkey portions", grounded)

        assert not grounded.has(
            "ph"
        ), "pH must NOT be grounded via bridge: no curated pH row exists for poultry"

    @pytest.mark.asyncio
    async def test_turkey_ph_bridge_attempt_recorded(
        self, grounding_service: GroundingService
    ) -> None:
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("turkey portions", grounded)

        assert "ph" in grounded.bridge_attempts, (
            "bridge_attempts['ph'] must be set when bridge resolved poultry "
            "but found no curated pH row"
        )

    @pytest.mark.asyncio
    async def test_turkey_ph_bridge_attempt_names_poultry_category(
        self, grounding_service: GroundingService
    ) -> None:
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("turkey portions", grounded)

        attempt = grounded.bridge_attempts["ph"]
        assert attempt.resolved_category == "poultry"
        assert attempt.species == "turkey portions"
        assert attempt.taxonomy_code == "A01SQ"


# ---------------------------------------------------------------------------
# Broccoli — vegetable category has no curated rows at all
# ---------------------------------------------------------------------------


class TestBroccoliNoCuratedRows:
    """'broccoli' resolves to vegetable (state=unspecified → assumed fresh).

    The curated rows do not include any vegetable entries (held at 5 rows).
    Both pH and aw must remain ungrounded, with a bridge_attempt recorded for
    each field so the downstream reason text is specific rather than silent.
    """

    @pytest.mark.asyncio
    async def test_broccoli_ph_not_grounded(
        self, grounding_service: GroundingService
    ) -> None:
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("broccoli", grounded)

        assert not grounded.has("ph")

    @pytest.mark.asyncio
    async def test_broccoli_aw_not_grounded(
        self, grounding_service: GroundingService
    ) -> None:
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("broccoli", grounded)

        assert not grounded.has("water_activity")

    @pytest.mark.asyncio
    async def test_broccoli_ph_bridge_attempt_recorded(
        self, grounding_service: GroundingService
    ) -> None:
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("broccoli", grounded)

        assert "ph" in grounded.bridge_attempts
        assert grounded.bridge_attempts["ph"].resolved_category == "vegetable"

    @pytest.mark.asyncio
    async def test_broccoli_aw_bridge_attempt_recorded(
        self, grounding_service: GroundingService
    ) -> None:
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("broccoli", grounded)

        assert "water_activity" in grounded.bridge_attempts
        assert (
            grounded.bridge_attempts["water_activity"].resolved_category == "vegetable"
        )


# ---------------------------------------------------------------------------
# Env-var disabled bridge — Tier 3 does not fire at all
# ---------------------------------------------------------------------------


class TestEnvVarDisabledBridge:
    """When PTM_TAXONOMY_BRIDGE_ENABLED=false the bridge is None; Tier 3 is skipped.

    Uses a service constructed with taxonomy_bridge=None (explicit override)
    rather than env-var patching so the test does not depend on monkeypatch
    propagating through the asyncio event loop.
    """

    @pytest.fixture
    def disabled_service(self, mock_retrieval: MagicMock) -> GroundingService:
        """GroundingService with bridge explicitly disabled."""
        return GroundingService(
            retrieval_service=mock_retrieval,
            llm_client=AsyncMock(),
            use_llm_extraction=False,
            taxonomy_bridge=None,
        )

    @pytest.mark.asyncio
    async def test_turkey_aw_not_grounded_when_bridge_disabled(
        self, disabled_service: GroundingService
    ) -> None:
        """aw must NOT be resolved when the bridge is disabled."""
        grounded = GroundedValues()
        await disabled_service._ground_food_properties("turkey portions", grounded)

        assert not grounded.has("water_activity")

    @pytest.mark.asyncio
    async def test_no_bridge_attempts_when_bridge_disabled(
        self, disabled_service: GroundingService
    ) -> None:
        """bridge_attempts must stay empty when the bridge is disabled."""
        grounded = GroundedValues()
        await disabled_service._ground_food_properties("turkey portions", grounded)

        assert grounded.bridge_attempts == {}


# ---------------------------------------------------------------------------
# B3: "chili" composite-food rejection — full grounding + standardization path
# ---------------------------------------------------------------------------


class TestChiliCompositeRejection:
    """B3 scenario: 'chili' triggers the orchestrator-level composite-food guard.

    Without the guard, 'chili' matched 'chili sauce acidified' at embedding
    0.7115 / reranker +5.90, silently grounding pH to 2.77.

    The guard fires before any retrieval call, populates composite_skip, and
    downstream consumers produce COMPOSITE_FOOD_DEFAULT source with a reason
    string that names the matched keyword.

    Assertions mirror the spec:
    1. Neither pH nor aw is grounded from retrieval.
    2. grounded.retrievals contains no entry attributed to ph or water_activity.
    3. After standardization, field_audit.ph.source == composite_food_default.
    4. provenance[] matches field_audit on source for the same field (cross-array).
    5. The DefaultImputed reason string mentions the matched keyword 'chili'.
    6. The DefaultImputed rule is 'default_imputed' (no new rule introduced).
    7. Standardization does not emit missing_required for ph or aw (prediction not blocked).
    """

    @pytest.fixture
    def chili_grounded(self, grounding_service: GroundingService) -> GroundedValues:
        """GroundedValues after grounding 'chili' (synchronous helper via pytest-asyncio)."""
        import asyncio

        grounded = GroundedValues()
        asyncio.get_event_loop().run_until_complete(
            grounding_service._ground_food_properties("chili", grounded)
        )
        return grounded

    @pytest.mark.asyncio
    async def test_ph_not_grounded_from_retrieval(
        self, grounding_service: GroundingService
    ) -> None:
        """1. pH must not be set after grounding — composite guard skipped retrieval."""
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("chili", grounded)
        assert not grounded.has("ph")

    @pytest.mark.asyncio
    async def test_aw_not_grounded_from_retrieval(
        self, grounding_service: GroundingService
    ) -> None:
        """1. aw must not be set after grounding — composite guard skipped retrieval."""
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("chili", grounded)
        assert not grounded.has("water_activity")

    @pytest.mark.asyncio
    async def test_no_retrieval_attributed_to_ph_or_aw(
        self, grounding_service: GroundingService
    ) -> None:
        """2. grounded.retrievals must contain no entry attributed to ph or water_activity."""
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("chili", grounded)

        ph_attributed = [r for r in grounded.retrievals if r.attributed_field == "ph"]
        aw_attributed = [
            r for r in grounded.retrievals if r.attributed_field == "water_activity"
        ]
        assert (
            ph_attributed == []
        ), "No retrieval should be attributed to ph for a composite food"
        assert (
            aw_attributed == []
        ), "No retrieval should be attributed to water_activity for a composite food"

    @pytest.mark.asyncio
    async def test_field_audit_ph_source_is_composite_food_default(
        self, grounding_service: GroundingService
    ) -> None:
        """3. field_audit.ph.source must be composite_food_default after the full grounding+std path."""
        from app.api.routes.translation import _build_field_audit
        from app.core.orchestrator import TranslationResult
        from app.core.state import SessionState
        from app.models.enums import SessionStatus

        grounded = GroundedValues()
        await grounding_service._ground_food_properties("chili", grounded)

        # Set organism + temperature + duration so standardization can proceed
        grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT)
        grounded.set("temperature_celsius", 25.0, ValueSource.USER_EXPLICIT)
        grounded.set("duration_minutes", 180.0, ValueSource.USER_EXPLICIT)

        std_svc = StandardizationService(model_registry=None)
        std_result = std_svc.standardize(grounded, ModelType.GROWTH)

        # Build a minimal SessionState/TranslationResult that mirrors what the orchestrator produces
        state = SessionState(user_input="chili at room temperature for 3 hours")
        state.initialize_metadata()
        state.status = SessionStatus.COMPLETED
        state.grounded_values = grounded.values
        for field, prov in grounded.provenance.items():
            state.metadata.add_provenance(field, prov)
        for retrieval in grounded.retrievals:
            state.metadata.add_retrieval(retrieval)
        if grounded.composite_skip:
            state.metadata.composite_skip.update(grounded.composite_skip)
        state.metadata.defaults_imputed.extend(std_result.defaults_imputed)

        result = TranslationResult(state)
        field_audit = _build_field_audit(result)

        assert "ph" in field_audit
        assert (
            field_audit["ph"].source == ValueSource.COMPOSITE_FOOD_DEFAULT.value
        ), f"Expected composite_food_default, got {field_audit['ph'].source}"

    @pytest.mark.asyncio
    async def test_provenance_list_agrees_with_field_audit_on_ph_source(
        self, grounding_service: GroundingService
    ) -> None:
        """4. provenance[] must show composite_food_default for ph — consistent with field_audit."""
        from app.api.routes.translation import (
            _build_field_audit,
            _build_provenance_list,
        )
        from app.core.orchestrator import TranslationResult
        from app.core.state import SessionState
        from app.models.enums import SessionStatus

        grounded = GroundedValues()
        await grounding_service._ground_food_properties("chili", grounded)
        grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT)
        grounded.set("temperature_celsius", 25.0, ValueSource.USER_EXPLICIT)
        grounded.set("duration_minutes", 180.0, ValueSource.USER_EXPLICIT)

        std_svc = StandardizationService(model_registry=None)
        std_result = std_svc.standardize(grounded, ModelType.GROWTH)

        state = SessionState(user_input="chili")
        state.initialize_metadata()
        state.status = SessionStatus.COMPLETED
        state.grounded_values = grounded.values
        for field, prov in grounded.provenance.items():
            state.metadata.add_provenance(field, prov)
        for retrieval in grounded.retrievals:
            state.metadata.add_retrieval(retrieval)
        if grounded.composite_skip:
            state.metadata.composite_skip.update(grounded.composite_skip)
        state.metadata.defaults_imputed.extend(std_result.defaults_imputed)

        result = TranslationResult(state)
        field_audit = _build_field_audit(result)
        provenance_list = _build_provenance_list(result, field_audit)

        # Cross-array agreement: provenance[] source for ph must match field_audit
        ph_fa = field_audit.get("ph")
        ph_prov = next((p for p in provenance_list if p.field == "ph"), None)

        assert ph_fa is not None, "ph must appear in field_audit"
        assert ph_prov is not None, "ph must appear in provenance[]"
        assert ph_prov.source == ph_fa.source, (
            f"Cross-array mismatch: field_audit.ph.source={ph_fa.source!r}, "
            f"provenance[ph].source={ph_prov.source!r}"
        )
        assert ph_prov.source == ValueSource.COMPOSITE_FOOD_DEFAULT.value

    @pytest.mark.asyncio
    async def test_default_imputed_reason_mentions_chili_keyword(
        self, grounding_service: GroundingService
    ) -> None:
        """5. The DefaultImputed reason for pH must name the matched keyword 'chili'."""
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("chili", grounded)
        grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT)
        grounded.set("temperature_celsius", 25.0, ValueSource.USER_EXPLICIT)
        grounded.set("duration_minutes", 180.0, ValueSource.USER_EXPLICIT)

        std_svc = StandardizationService(model_registry=None)
        std_result = std_svc.standardize(grounded, ModelType.GROWTH)

        ph_default = next(
            (d for d in std_result.defaults_imputed if d.field_name == "ph"), None
        )
        assert (
            ph_default is not None
        ), "pH must be in defaults_imputed for a composite food"
        assert (
            "chili" in ph_default.reason
        ), f"Reason must name matched keyword 'chili'; got: {ph_default.reason!r}"

    @pytest.mark.asyncio
    async def test_default_imputed_rule_is_default_imputed(
        self, grounding_service: GroundingService
    ) -> None:
        """6. The standardization rule must remain 'default_imputed' — no new rule introduced."""
        from app.api.routes.translation import _build_field_audit
        from app.core.orchestrator import TranslationResult
        from app.core.state import SessionState
        from app.models.enums import SessionStatus

        grounded = GroundedValues()
        await grounding_service._ground_food_properties("chili", grounded)
        grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT)
        grounded.set("temperature_celsius", 25.0, ValueSource.USER_EXPLICIT)
        grounded.set("duration_minutes", 180.0, ValueSource.USER_EXPLICIT)

        std_svc = StandardizationService(model_registry=None)
        std_result = std_svc.standardize(grounded, ModelType.GROWTH)

        state = SessionState(user_input="chili")
        state.initialize_metadata()
        state.status = SessionStatus.COMPLETED
        state.grounded_values = grounded.values
        for field, prov in grounded.provenance.items():
            state.metadata.add_provenance(field, prov)
        state.metadata.defaults_imputed.extend(std_result.defaults_imputed)
        if grounded.composite_skip:
            state.metadata.composite_skip.update(grounded.composite_skip)

        result = TranslationResult(state)
        field_audit = _build_field_audit(result)

        ph_entry = field_audit.get("ph")
        assert ph_entry is not None
        assert ph_entry.standardization is not None
        assert ph_entry.standardization.rule == "default_imputed"

    @pytest.mark.asyncio
    async def test_standardization_does_not_block_prediction(
        self, grounding_service: GroundingService
    ) -> None:
        """7. Composite-food guard must not block the prediction (success=True).

        Verified by confirming std_result.missing_required is empty when the
        required fields (organism, temperature, duration) are set.  ph and aw
        get conservative defaults — not missing_required — so the pipeline proceeds.
        """
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("chili", grounded)
        grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.USER_EXPLICIT)
        grounded.set("temperature_celsius", 25.0, ValueSource.USER_EXPLICIT)
        grounded.set("duration_minutes", 180.0, ValueSource.USER_EXPLICIT)

        std_svc = StandardizationService(model_registry=None)
        std_result = std_svc.standardize(grounded, ModelType.GROWTH)

        assert (
            std_result.missing_required == []
        ), f"Composite food must not block prediction; missing_required={std_result.missing_required}"
