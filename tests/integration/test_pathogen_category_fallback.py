"""
Integration tests — category-level pathogen fallback.

These tests exercise the full grounding flow for organism resolution using a real
TaxonomyBridge (loading production CSVs) and a mock retrieval service that
controls Stage 1 (food-name hazard embedding) outcomes precisely.

Test taxonomy
-------------
T — True positive: fallback fires and selects the correct organism.
    T1 "barley"       → grain → cereal grains (4 candidates)
    T2 "mascarpone"   → dairy → 3 IFT categories (Campylobacter skipped)
    T3 "boiled egg"   → eggs → eggs and egg products (Stage 1 margin: 0.13 below threshold)

N — Negative: fallback correctly does NOT ground organism.
    N1 "frobnitz"     → bridge returns None (no matching food)
    N2 "mustard"      → bridge → condiment → no IFT mapping

U — Unchanged behaviour: existing sources must not be replaced by fallback.
    U1 "raw chicken"  → Stage 1 confident → source=rag_retrieval (fallback never fires)
    U2 "Salmonella on bread" → pathogen_mentioned → source=user_explicit
    U3 "chicken soup" → composite guard blocks ph/aw; pathogen fallback fires for organism

All tests run against production data CSVs loaded through the real GroundingService
constructor (GroundingService injects real production lookup tables from disk unless
the tests override them for isolation).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.enums import ComBaseOrganism, OrganismGroundingFailureStage
from app.models.extraction import (
    ExtractedDuration,
    ExtractedEnvironmentalConditions,
    ExtractedScenario,
    ExtractedTemperature,
)
from app.models.metadata import ValueSource
from app.services.grounding.grounding_service import GroundingService
from app.services.grounding.taxonomy_bridge import TaxonomyBridge

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_scenario(
    food_description: str, pathogen_mentioned: str | None = None
) -> ExtractedScenario:
    """Minimal ExtractedScenario focused on food_description / pathogen_mentioned."""
    return ExtractedScenario(
        food_description=food_description,
        food_state=None,
        pathogen_mentioned=pathogen_mentioned,
        is_multi_step=False,
        single_step_temperature=ExtractedTemperature(value_celsius=25.0),
        single_step_duration=ExtractedDuration(value_minutes=180.0),
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
    """RetrievalResponse with no confident result — Stage 1 below threshold."""
    r = MagicMock()
    r.has_confident_result = False
    r.results = []
    r.top_result = None
    r.query = query
    r.reranker_used = None
    r.threshold = 0.75
    return r


def make_confident_pathogen_response(
    food_name: str, doc_id: str = "test-doc"
) -> MagicMock:
    """Stage 1 response with a confident food_name result for get_hazards_for_food."""
    top = MagicMock()
    top.doc_id = doc_id
    top.content = f"Pathogen hazard for {food_name}"
    top.source = "food_pathogen_hazard"
    top.distance = None
    top.rerank_score = None
    top.metadata = {"food_name": food_name, "source_id": "IFT-2003-T1"}

    r = MagicMock()
    r.has_confident_result = True
    r.top_result = top
    r.results = [top]
    r.query = food_name
    r.reranker_used = None
    r.threshold = 0.75
    return r


@pytest.fixture
def real_bridge() -> TaxonomyBridge:
    return TaxonomyBridge()


@pytest.fixture
def mock_retrieval_no_hit() -> MagicMock:
    """All retrieval calls return no confident result — forces fallback path for pathogen."""
    m = MagicMock()
    m.query_food_properties.return_value = make_no_hit_response()
    m.query_food_ph.return_value = make_no_hit_response()
    m.query_food_water_activity.return_value = make_no_hit_response()
    m.query_pathogen_hazards.return_value = make_no_hit_response()
    m.get_hazards_for_food.return_value = []
    return m


@pytest.fixture
def grounding_service(
    mock_retrieval_no_hit: MagicMock, real_bridge: TaxonomyBridge
) -> GroundingService:
    """GroundingService with mock retrieval (all misses) and real TaxonomyBridge + real production CSVs."""
    return GroundingService(
        retrieval_service=mock_retrieval_no_hit,
        llm_client=AsyncMock(),
        use_llm_extraction=False,
        taxonomy_bridge=real_bridge,
    )


# ---------------------------------------------------------------------------
# T1 — barley → grain → cereal grains
# ---------------------------------------------------------------------------


class TestT1Barley:
    """T1: 'barley' triggers category fallback → grain → cereal grains → Salmonella selected.

    Cereal grains has 4 pathogens (IFT-2003-T1):
      Salmonella spp.       (238 deaths) → selected
      Clostridium botulinum (9 deaths)
      Staphylococcus aureus (6 deaths)
      Bacillus cereus       (0 deaths)
    """

    @pytest.mark.asyncio
    async def test_organism_grounded_via_fallback(
        self, grounding_service: GroundingService
    ) -> None:
        """Organism must be grounded with source=rag_pathogen_category_fallback."""
        grounded = await grounding_service.ground_scenario(make_scenario("barley"))

        assert grounded.has("organism")
        assert (
            grounded.provenance["organism"].source
            == ValueSource.RAG_PATHOGEN_CATEGORY_FALLBACK
        )

    @pytest.mark.asyncio
    async def test_salmonella_selected(
        self, grounding_service: GroundingService
    ) -> None:
        """Salmonella (238 deaths) must win the ranking for cereal grains."""
        grounded = await grounding_service.ground_scenario(make_scenario("barley"))

        assert grounded.get("organism") == ComBaseOrganism.SALMONELLA

    @pytest.mark.asyncio
    async def test_ift_category_and_ptm_category(
        self, grounding_service: GroundingService
    ) -> None:
        """Fallback audit must record ptm_category=grain, ift_categories=[cereal grains]."""
        grounded = await grounding_service.ground_scenario(make_scenario("barley"))

        fb = grounded.provenance["organism"].pathogen_category_fallback
        assert fb is not None
        assert fb.ptm_category == "grain"
        assert fb.ift_categories == ["cereal grains"]
        assert fb.ift_source_id == "IFT-2003-T1"

    @pytest.mark.asyncio
    async def test_all_four_candidates_present(
        self, grounding_service: GroundingService
    ) -> None:
        """All four cereal-grains pathogens must appear in candidate_pathogens, ranked by deaths."""
        grounded = await grounding_service.ground_scenario(make_scenario("barley"))

        fb = grounded.provenance["organism"].pathogen_category_fallback
        assert fb is not None

        candidate_names = [c.pathogen for c in fb.candidate_pathogens]
        assert "Salmonella spp." in candidate_names
        assert "Clostridium botulinum" in candidate_names
        assert "Staphylococcus aureus" in candidate_names
        assert "Bacillus cereus" in candidate_names

        # Ranked descending by deaths
        deaths = [c.annual_deaths_us for c in fb.candidate_pathogens]
        assert deaths == sorted(
            deaths, reverse=True
        ), "Candidates must be sorted descending by annual_deaths_us"

        # Spot-check expected death counts
        by_name = {c.pathogen: c.annual_deaths_us for c in fb.candidate_pathogens}
        assert by_name["Salmonella spp."] == 238
        assert by_name["Clostridium botulinum"] == 9
        assert by_name["Staphylococcus aureus"] == 6
        assert by_name["Bacillus cereus"] == 0

    @pytest.mark.asyncio
    async def test_skipped_pathogens_empty(
        self, grounding_service: GroundingService
    ) -> None:
        """All cereal-grains pathogens map to ComBaseOrganism — skipped_pathogens must be empty."""
        grounded = await grounding_service.ground_scenario(make_scenario("barley"))

        fb = grounded.provenance["organism"].pathogen_category_fallback
        assert fb.skipped_pathogens == []

    @pytest.mark.asyncio
    async def test_warning_contains_grain(
        self, grounding_service: GroundingService
    ) -> None:
        """A warning mentioning 'grain' and 'IFT-2003-T1' must be emitted."""
        grounded = await grounding_service.ground_scenario(make_scenario("barley"))

        assert any("grain" in w and "IFT-2003-T1" in w for w in grounded.warnings)

    @pytest.mark.asyncio
    async def test_extraction_method(self, grounding_service: GroundingService) -> None:
        prov = (
            await grounding_service.ground_scenario(make_scenario("barley"))
        ).provenance["organism"]
        assert prov.extraction_method == "category_fallback_ranked_by_annual_deaths"

    @pytest.mark.asyncio
    async def test_full_citations_populated(
        self, grounding_service: GroundingService
    ) -> None:
        """full_citations must contain both IFT and CDC source IDs with non-empty values."""
        grounded = await grounding_service.ground_scenario(make_scenario("barley"))

        fb = grounded.provenance["organism"].pathogen_category_fallback
        assert fb is not None
        cites = fb.full_citations
        assert "IFT-2003-T1" in cites, "IFT source ID must be present"
        assert cites["IFT-2003-T1"], "IFT citation must be non-empty"
        assert "CDC-2019-T1T2" in cites, "CDC source ID for Salmonella must be present"
        assert cites["CDC-2019-T1T2"], "CDC citation must be non-empty"


# ---------------------------------------------------------------------------
# T2 — mascarpone → dairy → 3 IFT categories; Campylobacter in skipped
# ---------------------------------------------------------------------------


class TestT2Mascarpone:
    """T2: 'mascarpone' → dairy → 3 IFT categories.

    dairy maps to: milk and milk products, cheese and cheese products, butter and margarine.
    The union has 9 ranked pathogens.  Salmonella spp. (238 deaths) is selected first —
    it maps to ComBaseOrganism.SALMONELLA, so the loop breaks at rank 1 and
    skipped_pathogens is empty.

    Note on Campylobacter: Campylobacter jejuni (197 deaths) has no ComBaseOrganism
    mapping and would be skipped if it ranked above Salmonella.  It doesn't (197 < 238),
    so the skip mechanism for dairy is exercised by the unit tests with synthetic tables
    (test_top_candidate_no_combase_mapping_selects_next), not by this integration test.
    """

    @pytest.mark.asyncio
    async def test_organism_grounded_as_salmonella(
        self, grounding_service: GroundingService
    ) -> None:
        grounded = await grounding_service.ground_scenario(make_scenario("mascarpone"))

        assert grounded.has("organism")
        assert grounded.get("organism") == ComBaseOrganism.SALMONELLA

    @pytest.mark.asyncio
    async def test_three_ift_categories(
        self, grounding_service: GroundingService
    ) -> None:
        grounded = await grounding_service.ground_scenario(make_scenario("mascarpone"))

        fb = grounded.provenance["organism"].pathogen_category_fallback
        assert fb is not None
        assert fb.ptm_category == "dairy"
        assert set(fb.ift_categories) == {
            "milk and milk products",
            "cheese and cheese products",
            "butter and margarine",
        }

    @pytest.mark.asyncio
    async def test_union_includes_all_three_categories(
        self, grounding_service: GroundingService
    ) -> None:
        """Candidate list must include pathogens from all three IFT categories (union logic)."""
        grounded = await grounding_service.ground_scenario(make_scenario("mascarpone"))

        fb = grounded.provenance["organism"].pathogen_category_fallback
        names = {c.pathogen for c in fb.candidate_pathogens}
        # milk-only
        assert "Campylobacter jejuni" in names
        # cheese-only addition
        assert "Shigella spp." in names
        # butter-only addition
        assert "Yersinia enterocolitica" in names

    @pytest.mark.asyncio
    async def test_skipped_pathogens_empty(
        self, grounding_service: GroundingService
    ) -> None:
        """Salmonella (rank 1) maps successfully → no candidates are ever skipped."""
        grounded = await grounding_service.ground_scenario(make_scenario("mascarpone"))

        fb = grounded.provenance["organism"].pathogen_category_fallback
        assert fb.skipped_pathogens == []

    @pytest.mark.asyncio
    async def test_source_is_category_fallback(
        self, grounding_service: GroundingService
    ) -> None:
        grounded = await grounding_service.ground_scenario(make_scenario("mascarpone"))

        assert (
            grounded.provenance["organism"].source
            == ValueSource.RAG_PATHOGEN_CATEGORY_FALLBACK
        )

    @pytest.mark.asyncio
    async def test_full_citations_populated(
        self, grounding_service: GroundingService
    ) -> None:
        """full_citations must contain both IFT and CDC source IDs with non-empty values."""
        grounded = await grounding_service.ground_scenario(make_scenario("mascarpone"))

        fb = grounded.provenance["organism"].pathogen_category_fallback
        assert fb is not None
        cites = fb.full_citations
        assert "IFT-2003-T1" in cites, "IFT source ID must be present"
        assert cites["IFT-2003-T1"], "IFT citation must be non-empty"
        assert "CDC-2019-T1T2" in cites, "CDC source ID for Salmonella must be present"
        assert cites["CDC-2019-T1T2"], "CDC citation must be non-empty"


# ---------------------------------------------------------------------------
# T3 — boiled egg → eggs → eggs and egg products
# ---------------------------------------------------------------------------


class TestT3BoiledEgg:
    """T3: 'boiled egg' → eggs → eggs and egg products → Salmonella selected.

    Note: Stage 1 embedding score for 'boiled egg' was empirically measured at ~0.62,
    which is 0.13 below the 0.75 threshold, so the fallback reliably fires.
    The margin is narrow enough that future embedding model changes could push it
    above threshold — revisit if this test becomes flaky.
    """

    @pytest.mark.asyncio
    async def test_organism_grounded_as_salmonella(
        self, grounding_service: GroundingService
    ) -> None:
        grounded = await grounding_service.ground_scenario(make_scenario("boiled egg"))

        assert grounded.has("organism")
        assert grounded.get("organism") == ComBaseOrganism.SALMONELLA

    @pytest.mark.asyncio
    async def test_ptm_category_is_eggs(
        self, grounding_service: GroundingService
    ) -> None:
        grounded = await grounding_service.ground_scenario(make_scenario("boiled egg"))

        fb = grounded.provenance["organism"].pathogen_category_fallback
        assert fb is not None
        assert fb.ptm_category == "eggs"
        assert fb.ift_categories == ["eggs and egg products"]

    @pytest.mark.asyncio
    async def test_salmonella_ranked_above_listeria(
        self, grounding_service: GroundingService
    ) -> None:
        """Salmonella (238 deaths) must rank above Listeria (172 deaths)."""
        grounded = await grounding_service.ground_scenario(make_scenario("boiled egg"))

        fb = grounded.provenance["organism"].pathogen_category_fallback
        candidate_names = [c.pathogen for c in fb.candidate_pathogens]
        assert candidate_names.index("Salmonella spp.") < candidate_names.index(
            "Listeria monocytogenes"
        )

    @pytest.mark.asyncio
    async def test_skipped_pathogens_empty(
        self, grounding_service: GroundingService
    ) -> None:
        """Both egg pathogens (Salmonella, Listeria) map to ComBaseOrganism — no skipped."""
        grounded = await grounding_service.ground_scenario(make_scenario("boiled egg"))

        fb = grounded.provenance["organism"].pathogen_category_fallback
        assert fb.skipped_pathogens == []

    @pytest.mark.asyncio
    async def test_full_citations_populated(
        self, grounding_service: GroundingService
    ) -> None:
        """full_citations must contain both IFT and CDC source IDs with non-empty values."""
        grounded = await grounding_service.ground_scenario(make_scenario("boiled egg"))

        fb = grounded.provenance["organism"].pathogen_category_fallback
        assert fb is not None
        cites = fb.full_citations
        assert "IFT-2003-T1" in cites, "IFT source ID must be present"
        assert cites["IFT-2003-T1"], "IFT citation must be non-empty"
        assert "CDC-2019-T1T2" in cites, "CDC source ID for Salmonella must be present"
        assert cites["CDC-2019-T1T2"], "CDC citation must be non-empty"


# ---------------------------------------------------------------------------
# N1 — frobnitz: bridge cannot resolve food → fallback does not fire
# ---------------------------------------------------------------------------


class TestN1Frobnitz:
    """N1: 'frobnitz' is an unrecognisable food → TaxonomyBridge returns None → organism ungrounded."""

    @pytest.mark.asyncio
    async def test_organism_not_grounded(
        self, grounding_service: GroundingService
    ) -> None:
        grounded = await grounding_service.ground_scenario(make_scenario("frobnitz"))

        assert not grounded.has(
            "organism"
        ), "No organism should be grounded for an unrecognisable food"

    @pytest.mark.asyncio
    async def test_no_fallback_warning(
        self, grounding_service: GroundingService
    ) -> None:
        """No IFT-2003-T1 warning should be emitted — the fallback must not have run."""
        grounded = await grounding_service.ground_scenario(make_scenario("frobnitz"))

        assert not any("IFT-2003-T1" in w for w in grounded.warnings)

    @pytest.mark.asyncio
    async def test_organism_failure_recorded(
        self, grounding_service: GroundingService
    ) -> None:
        """organism_failure records FOOD_UNRECOGNISED — the taxonomy bridge returned None."""
        grounded = await grounding_service.ground_scenario(make_scenario("frobnitz"))

        assert grounded.organism_failure is not None
        assert (
            grounded.organism_failure.stage
            == OrganismGroundingFailureStage.FOOD_UNRECOGNISED
        )


# ---------------------------------------------------------------------------
# N2 — mustard: bridge → condiment → no IFT category → fallback returns early
# ---------------------------------------------------------------------------


class TestN2Mustard:
    """N2: 'mustard' → condiment → no IFT mapping → organism ungrounded.

    condiment is a valid ptm_category (it exists in food_taxonomy.csv) but has
    no corresponding IFT-2003-T1 row in ift_category_alignment.csv.
    """

    @pytest.mark.asyncio
    async def test_organism_not_grounded(
        self, grounding_service: GroundingService
    ) -> None:
        grounded = await grounding_service.ground_scenario(make_scenario("mustard"))

        assert not grounded.has(
            "organism"
        ), "No organism for condiment category (no IFT mapping)"

    @pytest.mark.asyncio
    async def test_no_fallback_warning(
        self, grounding_service: GroundingService
    ) -> None:
        grounded = await grounding_service.ground_scenario(make_scenario("mustard"))

        assert not any("IFT-2003-T1" in w for w in grounded.warnings)

    @pytest.mark.asyncio
    async def test_organism_failure_recorded(
        self, grounding_service: GroundingService
    ) -> None:
        """organism_failure records CATEGORY_HAS_NO_HAZARD_DATA with the resolved category and a match score."""
        grounded = await grounding_service.ground_scenario(make_scenario("mustard"))

        assert grounded.organism_failure is not None
        assert (
            grounded.organism_failure.stage
            == OrganismGroundingFailureStage.CATEGORY_HAS_NO_HAZARD_DATA
        )
        assert grounded.organism_failure.resolved_category == "condiment"
        assert grounded.organism_failure.match_score is not None


# ---------------------------------------------------------------------------
# U1 — raw chicken: Stage 1 confident → RAG_RETRIEVAL (fallback must not fire)
# ---------------------------------------------------------------------------


class TestU1RawChicken:
    """U1: 'raw chicken' succeeds Stage 1 embedding (empirically ≥ 0.75).

    Stage 1 returns confident result → organism grounded with source=rag_retrieval.
    The category fallback must NOT fire.
    """

    @pytest.fixture
    def retrieval_with_chicken_hit(self) -> MagicMock:
        """Stage 1 returns a confident result for raw chicken; Stage 2 returns Salmonella."""
        m = MagicMock()
        m.query_food_properties.return_value = make_no_hit_response()
        m.query_food_ph.return_value = make_no_hit_response()
        m.query_food_water_activity.return_value = make_no_hit_response()
        m.query_pathogen_hazards.return_value = make_confident_pathogen_response(
            "chicken raw", "rag-doc-001"
        )
        # Stage 2: top hazard is Salmonella
        m.get_hazards_for_food.return_value = [
            {"document": "Salmonella spp. chicken raw", "id": "cdc-chicken-001"},
        ]
        return m

    @pytest.fixture
    def grounding_service_with_hit(
        self, retrieval_with_chicken_hit: MagicMock, real_bridge: TaxonomyBridge
    ) -> GroundingService:
        return GroundingService(
            retrieval_service=retrieval_with_chicken_hit,
            llm_client=AsyncMock(),
            use_llm_extraction=False,
            taxonomy_bridge=real_bridge,
        )

    @pytest.mark.asyncio
    async def test_source_is_rag_retrieval(
        self, grounding_service_with_hit: GroundingService
    ) -> None:
        """Source must be rag_retrieval — Stage 1 succeeded so fallback must not have run."""
        grounded = await grounding_service_with_hit.ground_scenario(
            make_scenario("raw chicken")
        )

        assert grounded.has("organism")
        assert grounded.provenance["organism"].source == ValueSource.RAG_RETRIEVAL

    @pytest.mark.asyncio
    async def test_no_fallback_provenance(
        self, grounding_service_with_hit: GroundingService
    ) -> None:
        """pathogen_category_fallback must be None when Stage 1 succeeded."""
        grounded = await grounding_service_with_hit.ground_scenario(
            make_scenario("raw chicken")
        )

        prov = grounded.provenance["organism"]
        assert prov.pathogen_category_fallback is None

    @pytest.mark.asyncio
    async def test_no_fallback_warning(
        self, grounding_service_with_hit: GroundingService
    ) -> None:
        grounded = await grounding_service_with_hit.ground_scenario(
            make_scenario("raw chicken")
        )

        assert not any("IFT-2003-T1" in w for w in grounded.warnings)


# ---------------------------------------------------------------------------
# U2 — Salmonella on bread: pathogen_mentioned → USER_EXPLICIT
# ---------------------------------------------------------------------------


class TestU2SalmonellaOnBread:
    """U2: 'Salmonella on bread' with pathogen_mentioned set → USER_EXPLICIT.

    The user explicitly named the pathogen.  The fallback must not override it.
    """

    @pytest.mark.asyncio
    async def test_source_is_user_explicit(
        self, grounding_service: GroundingService
    ) -> None:
        """Explicit pathogen_mentioned must yield source=user_explicit."""
        scenario = make_scenario("bread", pathogen_mentioned="Salmonella")
        grounded = await grounding_service.ground_scenario(scenario)

        assert grounded.has("organism")
        assert grounded.provenance["organism"].source == ValueSource.USER_EXPLICIT

    @pytest.mark.asyncio
    async def test_no_fallback_provenance(
        self, grounding_service: GroundingService
    ) -> None:
        scenario = make_scenario("bread", pathogen_mentioned="Salmonella")
        grounded = await grounding_service.ground_scenario(scenario)

        assert grounded.provenance["organism"].pathogen_category_fallback is None

    @pytest.mark.asyncio
    async def test_no_fallback_warning(
        self, grounding_service: GroundingService
    ) -> None:
        scenario = make_scenario("bread", pathogen_mentioned="Salmonella")
        grounded = await grounding_service.ground_scenario(scenario)

        assert not any("IFT-2003-T1" in w for w in grounded.warnings)


# ---------------------------------------------------------------------------
# U3 — chicken soup: composite guard + category fallback are orthogonal
# ---------------------------------------------------------------------------


class TestU3ChickenSoup:
    """U3: 'chicken soup' demonstrates that the composite guard (ph/aw) and the
    category pathogen fallback are orthogonal mechanisms that fire independently.

    The composite guard blocks ph and aw retrieval (soup is a composite keyword).
    The pathogen fallback fires for organism (Stage 1 score < 0.75 for 'chicken soup').
    The fallback resolves chicken soup → poultry → meats and poultry → Salmonella.
    """

    @pytest.mark.asyncio
    async def test_ph_blocked_by_composite_guard(
        self, grounding_service: GroundingService
    ) -> None:
        """ph must NOT be grounded — composite guard skipped retrieval."""
        grounded = await grounding_service.ground_scenario(
            make_scenario("chicken soup")
        )

        assert not grounded.has("ph")
        assert (
            "ph" in grounded.composite_skip
            or "water_activity" in grounded.composite_skip
        )

    @pytest.mark.asyncio
    async def test_aw_blocked_by_composite_guard(
        self, grounding_service: GroundingService
    ) -> None:
        """water_activity must NOT be grounded — composite guard skipped retrieval."""
        grounded = await grounding_service.ground_scenario(
            make_scenario("chicken soup")
        )

        assert not grounded.has("water_activity")

    @pytest.mark.asyncio
    async def test_organism_grounded_via_category_fallback(
        self, grounding_service: GroundingService
    ) -> None:
        """Organism must be grounded via RAG_PATHOGEN_CATEGORY_FALLBACK, not composite guard."""
        grounded = await grounding_service.ground_scenario(
            make_scenario("chicken soup")
        )

        assert grounded.has("organism")
        assert (
            grounded.provenance["organism"].source
            == ValueSource.RAG_PATHOGEN_CATEGORY_FALLBACK
        )

    @pytest.mark.asyncio
    async def test_ptm_category_is_poultry(
        self, grounding_service: GroundingService
    ) -> None:
        """Bridge must resolve 'chicken soup' to ptm_category=poultry."""
        grounded = await grounding_service.ground_scenario(
            make_scenario("chicken soup")
        )

        fb = grounded.provenance["organism"].pathogen_category_fallback
        assert fb is not None
        assert fb.ptm_category == "poultry"

    @pytest.mark.asyncio
    async def test_composite_skip_keyword_is_soup(
        self, grounding_service: GroundingService
    ) -> None:
        """The composite guard must record 'soup' as the matched keyword."""
        grounded = await grounding_service.ground_scenario(
            make_scenario("chicken soup")
        )

        # composite_skip["ph"] or ["water_activity"] should contain the matched keyword
        matched_keywords = set(grounded.composite_skip.values())
        assert "soup" in matched_keywords
