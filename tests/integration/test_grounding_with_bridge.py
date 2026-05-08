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

import pytest
from unittest.mock import MagicMock, AsyncMock

from app.services.grounding.grounding_service import GroundingService, GroundedValues
from app.services.grounding.taxonomy_bridge import TaxonomyBridge
from app.models.metadata import ValueSource
from app.models.extraction import (
    ExtractedScenario,
    ExtractedTemperature,
    ExtractedDuration,
    ExtractedEnvironmentalConditions,
)


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


def make_confident_response(content: str, query: str, doc_id: str, source_id: str = "") -> MagicMock:
    """RetrievalResponse with one confident result — simulates a Tier 2 hit."""
    top = MagicMock()
    top.doc_id = doc_id
    top.content = content
    top.source = "food_properties"
    top.distance = None       # suppresses isinstance checks in _build_retrieval_metadata
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
def grounding_service(mock_retrieval: MagicMock, real_bridge: TaxonomyBridge) -> GroundingService:
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
    """C1-like scenario: 'turkey portions' with both Tier 1 and Tier 2 missing."""

    @pytest.mark.asyncio
    async def test_ph_resolved_via_bridge(
        self, grounding_service: GroundingService
    ) -> None:
        """pH should be set with source RAG_RETRIEVAL_CATEGORY_BRIDGE after bridge fires."""
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("turkey portions", grounded)

        assert grounded.has("ph")
        assert grounded.provenance["ph"].source == ValueSource.RAG_RETRIEVAL_CATEGORY_BRIDGE

    @pytest.mark.asyncio
    async def test_aw_resolved_via_bridge(
        self, grounding_service: GroundingService
    ) -> None:
        """aw should be set with source RAG_RETRIEVAL_CATEGORY_BRIDGE after bridge fires."""
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("turkey portions", grounded)

        assert grounded.has("water_activity")
        assert grounded.provenance["water_activity"].source == ValueSource.RAG_RETRIEVAL_CATEGORY_BRIDGE

    @pytest.mark.asyncio
    async def test_ph_category_bridge_points_to_chicken_row(
        self, grounding_service: GroundingService
    ) -> None:
        """pH audit block: bridge resolved turkey → poultry → chicken row (IFT-2003-T33)."""
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("turkey portions", grounded)

        ph_bridge = grounded.provenance["ph"].category_bridge
        assert ph_bridge is not None
        # Species recorded as the original food description
        assert ph_bridge.species == "turkey portions"
        # Taxonomy resolution: turkey → poultry via A01SQ
        assert ph_bridge.resolved_category == "poultry"
        assert ph_bridge.taxonomy_code == "A01SQ"
        assert ph_bridge.taxonomy_source_id == "EFSA-FoodEx2-MTX-12.0"
        assert ph_bridge.matched_food_name == "turkey"
        assert ph_bridge.match_score == pytest.approx(100.0)
        # Property row: chicken supplies pH for the poultry category
        assert ph_bridge.property_row_food_name == "chicken"
        assert "IFT-2003-T33" in ph_bridge.property_row_source_ids

    @pytest.mark.asyncio
    async def test_aw_category_bridge_points_to_fresh_poultry_row(
        self, grounding_service: GroundingService
    ) -> None:
        """aw audit block: bridge resolved turkey → poultry → fresh poultry row (IFT-2003-T31).

        pH and aw come from DIFFERENT property rows; each field's category_bridge
        must record the row that actually supplied the value — not the same row.
        """
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("turkey portions", grounded)

        aw_bridge = grounded.provenance["water_activity"].category_bridge
        assert aw_bridge is not None
        assert aw_bridge.species == "turkey portions"
        assert aw_bridge.resolved_category == "poultry"
        assert aw_bridge.taxonomy_code == "A01SQ"
        assert aw_bridge.matched_food_name == "turkey"
        # Property row: fresh poultry supplies aw for the poultry category
        assert aw_bridge.property_row_food_name == "fresh poultry"
        assert "IFT-2003-T31" in aw_bridge.property_row_source_ids

    @pytest.mark.asyncio
    async def test_ph_and_aw_have_different_property_row_names(
        self, grounding_service: GroundingService
    ) -> None:
        """pH and aw must reference different property rows — not the same row.

        This is the split-row poultry invariant: chicken supplies pH, fresh
        poultry supplies aw.  Both are attributed back through the same taxonomy
        entry (turkey, A01SQ) but name distinct property rows.
        """
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("turkey portions", grounded)

        ph_row = grounded.provenance["ph"].category_bridge.property_row_food_name  # type: ignore[union-attr]
        aw_row = grounded.provenance["water_activity"].category_bridge.property_row_food_name  # type: ignore[union-attr]
        assert ph_row != aw_row

    @pytest.mark.asyncio
    async def test_ph_value_is_in_chicken_ph_range(
        self, grounding_service: GroundingService
    ) -> None:
        """pH value stored must be the lower bound of chicken's pH range [6.2, 6.4]
        (range_pending=True; StandardizationService picks the conservative bound)."""
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("turkey portions", grounded)

        ph_prov = grounded.provenance["ph"]
        assert ph_prov.parsed_range == pytest.approx([6.2, 6.4])
        assert ph_prov.range_pending is True

    @pytest.mark.asyncio
    async def test_aw_value_is_in_fresh_poultry_aw_range(
        self, grounding_service: GroundingService
    ) -> None:
        """aw value stored must be the lower bound of fresh poultry's aw range [0.99, 1.0]."""
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
        await grounding_service._ground_food_properties("fresh chicken portions", grounded)

        assert grounded.has("ph")
        assert grounded.provenance["ph"].source == ValueSource.RAG_RETRIEVAL_FALLBACK

    @pytest.mark.asyncio
    async def test_ph_category_bridge_is_none(
        self, grounding_service: GroundingService, chicken_retrieval: MagicMock
    ) -> None:
        """category_bridge must be None when Tier 2 succeeded — bridge never ran for ph."""
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("fresh chicken portions", grounded)

        assert grounded.provenance["ph"].category_bridge is None

    @pytest.mark.asyncio
    async def test_aw_source_is_rag_retrieval_fallback_not_bridge(
        self, grounding_service: GroundingService, chicken_retrieval: MagicMock
    ) -> None:
        """aw must come from Tier 2 (RAG_RETRIEVAL_FALLBACK), not from the bridge."""
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("fresh chicken portions", grounded)

        assert grounded.has("water_activity")
        assert grounded.provenance["water_activity"].source == ValueSource.RAG_RETRIEVAL_FALLBACK

    @pytest.mark.asyncio
    async def test_aw_category_bridge_is_none(
        self, grounding_service: GroundingService, chicken_retrieval: MagicMock
    ) -> None:
        """category_bridge must be None when Tier 2 succeeded — bridge never ran for aw."""
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("fresh chicken portions", grounded)

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
    """'beef' resolves via alias (beef → bovine) → meat category.

    Meat has both pH rows (beef ground, ham, etc.) and aw rows (fresh meat).
    The bridge must supply at least pH for beef queries.
    """

    @pytest.mark.asyncio
    async def test_ph_resolved_via_bridge_for_beef(
        self, grounding_service: GroundingService
    ) -> None:
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("beef", grounded)

        assert grounded.has("ph")
        assert grounded.provenance["ph"].source == ValueSource.RAG_RETRIEVAL_CATEGORY_BRIDGE

    @pytest.mark.asyncio
    async def test_ph_category_bridge_records_category_meat(
        self, grounding_service: GroundingService
    ) -> None:
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("beef", grounded)

        ph_bridge = grounded.provenance["ph"].category_bridge
        assert ph_bridge is not None
        assert ph_bridge.resolved_category == "meat"
        assert ph_bridge.species == "beef"

    @pytest.mark.asyncio
    async def test_aw_resolved_via_bridge_for_beef(
        self, grounding_service: GroundingService
    ) -> None:
        """Meat category has aw rows (fresh meat 0.99–1.0, cured meat 0.87–0.95);
        bridge should supply aw for beef."""
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("beef", grounded)

        assert grounded.has("water_activity")
        assert grounded.provenance["water_activity"].source == ValueSource.RAG_RETRIEVAL_CATEGORY_BRIDGE


# ---------------------------------------------------------------------------
# Audit-honesty: bridge attempted but category has no data for that field
# ---------------------------------------------------------------------------

class TestBridgeAttemptedNoData:
    """When the bridge resolves a category that has no rows supplying a particular
    field, the GroundedValues must record the bridge attempt for that field.

    This lets StandardizationService mention the attempt in the DefaultImputed
    reason rather than emitting the silent 'no value found, default applied'.

    Test vehicle: 'lobster' — taxonomy has shellfish entries, food_properties
    has shellfish rows with pH only (no aw rows for shellfish).
    Bridge should:
    - successfully ground pH from the shellfish rows
    - record a bridge_attempt on 'water_activity' so the downstream default
      reason can say "bridge resolved to 'shellfish', no aw data available"
    """

    @pytest.mark.asyncio
    async def test_shellfish_ph_resolved_via_bridge(
        self, grounding_service: GroundingService
    ) -> None:
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("lobster", grounded)

        assert grounded.has("ph")
        assert grounded.provenance["ph"].source == ValueSource.RAG_RETRIEVAL_CATEGORY_BRIDGE

    @pytest.mark.asyncio
    async def test_shellfish_aw_not_grounded_but_bridge_attempt_recorded(
        self, grounding_service: GroundingService
    ) -> None:
        """aw is absent from food_properties for the shellfish category.

        grounded.has('water_activity') must be False (no value set), but
        grounded.bridge_attempts['water_activity'] must be set to a
        CategoryBridgeInfo recording the resolved category, so the downstream
        default's reason string can reference the failed bridge attempt.
        """
        grounded = GroundedValues()
        await grounding_service._ground_food_properties("lobster", grounded)

        assert not grounded.has("water_activity")
        assert "water_activity" in grounded.bridge_attempts
        attempt = grounded.bridge_attempts["water_activity"]
        assert attempt.resolved_category == "shellfish"
        assert attempt.species == "lobster"
