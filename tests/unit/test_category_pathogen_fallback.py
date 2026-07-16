"""
Unit tests for the category-level pathogen fallback.

Tests _PATHOGEN_NAME_NORMALIZATION dict integrity and _category_pathogen_fallback
edge cases using synthetic injected dicts (no filesystem reads).
"""

from unittest.mock import AsyncMock, MagicMock

from app.models.enums import ComBaseOrganism, OrganismGroundingFailureStage
from app.models.metadata import ValueSource
from app.services.audit.citations import get_full_citations
from app.services.grounding.grounding_service import (
    _PATHOGEN_NAME_NORMALIZATION,
    GroundedValues,
    GroundingService,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_service(
    *,
    ift_alignment: dict,
    pathogen_associations: dict,
    pathogen_characteristics: dict,
    taxonomy_bridge=None,
) -> GroundingService:
    """Build a GroundingService with injected lookup tables (no CSV reads)."""
    mock_retrieval = MagicMock()
    mock_retrieval.query_food_properties.return_value = MagicMock(
        has_confident_result=False,
        results=[],
        top_result=None,
        query="",
        reranker_used=None,
        threshold=0.62,
    )
    mock_retrieval.query_food_ph.return_value = MagicMock(
        has_confident_result=False,
        results=[],
        top_result=None,
        query="",
        reranker_used=None,
        threshold=0.62,
    )
    mock_retrieval.query_food_water_activity.return_value = MagicMock(
        has_confident_result=False,
        results=[],
        top_result=None,
        query="",
        reranker_used=None,
        threshold=0.62,
    )
    mock_retrieval.query_pathogen_hazards.return_value = MagicMock(
        has_confident_result=False,
        results=[],
        top_result=None,
        query="",
        reranker_used=None,
        threshold=0.62,
    )
    mock_retrieval.get_hazards_for_food.return_value = []

    if taxonomy_bridge is None:
        from app.services.grounding.taxonomy_bridge import TaxonomyBridge

        taxonomy_bridge = TaxonomyBridge()

    return GroundingService(
        retrieval_service=mock_retrieval,
        llm_client=AsyncMock(),
        use_llm_extraction=False,
        taxonomy_bridge=taxonomy_bridge,
        ift_alignment=ift_alignment,
        pathogen_associations=pathogen_associations,
        pathogen_characteristics=pathogen_characteristics,
    )


def call_fallback(service: GroundingService, food_description: str) -> GroundedValues:
    """Call _category_pathogen_fallback directly and return the GroundedValues."""
    grounded = GroundedValues()
    service._category_pathogen_fallback(food_description, grounded)
    return grounded


# ---------------------------------------------------------------------------
# TestGetFullCitationsUnknownId
# ---------------------------------------------------------------------------


class TestGetFullCitationsUnknownId:
    """Unknown source IDs must be silently omitted — not raised, not given placeholder text."""

    def test_unknown_id_returns_empty_dict(self):
        assert get_full_citations(["NONEXISTENT-SOURCE-ID-XYZ"]) == {}

    def test_mixed_ids_only_known_returned(self):
        result = get_full_citations(["NONEXISTENT-SOURCE-ID-XYZ", "IFT-2003-T1"])
        assert "NONEXISTENT-SOURCE-ID-XYZ" not in result
        assert "IFT-2003-T1" in result
        assert result["IFT-2003-T1"]  # non-empty


# ---------------------------------------------------------------------------
# TestPathogenNameNormalization
# ---------------------------------------------------------------------------


class TestPathogenNameNormalization:
    """Assert every row in _PATHOGEN_NAME_NORMALIZATION maps to the correct characteristics-CSV name."""

    def test_salmonella_spp_to_nontyphoidal(self):
        assert (
            _PATHOGEN_NAME_NORMALIZATION["salmonella spp."] == "salmonella nontyphoidal"
        )

    def test_campylobacter_jejuni_to_spp(self):
        assert (
            _PATHOGEN_NAME_NORMALIZATION["campylobacter jejuni"] == "campylobacter spp."
        )

    def test_ecoli_o157_to_stec_o157(self):
        assert _PATHOGEN_NAME_NORMALIZATION["escherichia coli o157:h7"] == "stec o157"

    def test_vibrio_cholerae_to_toxigenic(self):
        assert (
            _PATHOGEN_NAME_NORMALIZATION["vibrio cholerae"]
            == "vibrio cholerae toxigenic"
        )

    def test_clostridium_botulinum_identity(self):
        assert (
            _PATHOGEN_NAME_NORMALIZATION["clostridium botulinum"]
            == "clostridium botulinum"
        )

    def test_clostridium_perfringens_identity(self):
        assert (
            _PATHOGEN_NAME_NORMALIZATION["clostridium perfringens"]
            == "clostridium perfringens"
        )

    def test_listeria_monocytogenes_identity(self):
        assert (
            _PATHOGEN_NAME_NORMALIZATION["listeria monocytogenes"]
            == "listeria monocytogenes"
        )

    def test_yersinia_enterocolitica_identity(self):
        assert (
            _PATHOGEN_NAME_NORMALIZATION["yersinia enterocolitica"]
            == "yersinia enterocolitica"
        )

    def test_staphylococcus_aureus_identity(self):
        assert (
            _PATHOGEN_NAME_NORMALIZATION["staphylococcus aureus"]
            == "staphylococcus aureus"
        )

    def test_bacillus_cereus_identity(self):
        assert _PATHOGEN_NAME_NORMALIZATION["bacillus cereus"] == "bacillus cereus"

    def test_shigella_spp_identity(self):
        assert _PATHOGEN_NAME_NORMALIZATION["shigella spp."] == "shigella spp."

    def test_vibrio_vulnificus_identity(self):
        assert _PATHOGEN_NAME_NORMALIZATION["vibrio vulnificus"] == "vibrio vulnificus"

    def test_vibrio_parahaemolyticus_identity(self):
        assert (
            _PATHOGEN_NAME_NORMALIZATION["vibrio parahaemolyticus"]
            == "vibrio parahaemolyticus"
        )

    def test_all_values_are_lowercase(self):
        """All map values should be lowercase (characteristics CSV names)."""
        for k, v in _PATHOGEN_NAME_NORMALIZATION.items():
            assert k == k.lower(), f"Key not lowercase: {k!r}"
            assert v == v.lower(), f"Value not lowercase: {v!r}"


# ---------------------------------------------------------------------------
# TestCategoryFallbackEdgeCases
# ---------------------------------------------------------------------------


class TestCategoryFallbackEdgeCases:
    """_category_pathogen_fallback with synthetic injected tables — no filesystem reads."""

    def test_top_candidate_no_combase_mapping_selects_next(self):
        """When ranked top candidate has no ComBaseOrganism mapping, fall through to the next one."""
        # Campylobacter jejuni (→ None from from_text) beats Salmonella in this synthetic table.
        # Salmonella spp. must be selected after Campylobacter is skipped.
        service = make_service(
            ift_alignment={"grain": ["cereal grains"]},
            pathogen_associations={
                "cereal grains": ["Campylobacter jejuni", "Salmonella spp."]
            },
            pathogen_characteristics={
                "campylobacter spp.": (
                    9999,
                    "CDC-TEST",
                ),  # synthetic high deaths — ranks first
                "salmonella nontyphoidal": (238, "CDC-2019-T1T2"),
            },
        )
        grounded = call_fallback(service, "barley")

        assert grounded.has(
            "organism"
        ), "Organism should be grounded via second candidate"
        assert grounded.get("organism") == ComBaseOrganism.SALMONELLA
        prov = grounded.provenance["organism"]
        assert prov.source == ValueSource.RAG_PATHOGEN_CATEGORY_FALLBACK

        fb = prov.pathogen_category_fallback
        assert fb is not None
        skipped = [s["pathogen"] for s in fb.skipped_pathogens]
        assert "Campylobacter jejuni" in skipped
        assert fb.selected_pathogen.pathogen == "Salmonella spp."

    def test_all_candidates_fail_mapping_organism_ungrounded(self):
        """When every ranked candidate has no ComBaseOrganism mapping, organism stays ungrounded."""
        # "Campylobacter jejuni" has no from_text mapping (confirmed empirically).
        # Using two unmapped names ensures all paths are exhausted.
        service = make_service(
            ift_alignment={"grain": ["cereal grains"]},
            pathogen_associations={"cereal grains": ["Campylobacter jejuni"]},
            pathogen_characteristics={
                "campylobacter spp.": (197, "CDC-2019-T1T2"),
            },
        )
        grounded = call_fallback(service, "barley")

        assert not grounded.has(
            "organism"
        ), "No organism should be grounded when all candidates are unmappable"
        assert grounded.organism_failure is not None
        assert (
            grounded.organism_failure.stage
            == OrganismGroundingFailureStage.INTERNAL_NO_MAPPABLE_CANDIDATE
        )

    def test_pathogen_absent_from_characteristics_excluded_from_ranking(self):
        """A pathogen present in associations but absent from characteristics is not ranked."""
        # "Unknown pathogen" is in associations but not in characteristics.
        # Salmonella spp. is in both — it should still be selected.
        service = make_service(
            ift_alignment={"grain": ["cereal grains"]},
            pathogen_associations={
                "cereal grains": ["Unknown pathogen", "Salmonella spp."]
            },
            pathogen_characteristics={
                "salmonella nontyphoidal": (238, "CDC-2019-T1T2"),
                # "Unknown pathogen" is intentionally absent
            },
        )
        grounded = call_fallback(service, "barley")

        assert grounded.has("organism")
        assert grounded.get("organism") == ComBaseOrganism.SALMONELLA

        fb = grounded.provenance["organism"].pathogen_category_fallback
        assert fb is not None
        ranked_names = [c.pathogen for c in fb.candidate_pathogens]
        assert (
            "Unknown pathogen" not in ranked_names
        ), "Absent-from-characteristics pathogen must not appear in ranked list"

    def test_normalization_applied_before_characteristics_lookup(self):
        """'Salmonella spp.' in associations must look up 'salmonella nontyphoidal' in characteristics."""
        # The characteristics dict has 'salmonella nontyphoidal' (normalized), NOT 'salmonella spp.'
        service = make_service(
            ift_alignment={"eggs": ["eggs and egg products"]},
            pathogen_associations={"eggs and egg products": ["Salmonella spp."]},
            pathogen_characteristics={
                "salmonella nontyphoidal": (238, "CDC-2019-T1T2"),
                # "salmonella spp." is NOT in characteristics — normalization is required
            },
        )
        grounded = call_fallback(service, "boiled egg")

        assert grounded.has(
            "organism"
        ), "Normalization must succeed so Salmonella is found in characteristics"
        fb = grounded.provenance["organism"].pathogen_category_fallback
        assert fb is not None
        assert fb.candidate_pathogens[0].normalized_name == "salmonella nontyphoidal"
        assert fb.candidate_pathogens[0].annual_deaths_us == 238

    def test_bridge_none_returns_without_grounding(self):
        """When taxonomy_bridge is None, fallback must not ground anything."""
        mock_retrieval = MagicMock()
        mock_retrieval.query_pathogen_hazards.return_value = MagicMock(
            has_confident_result=False,
            results=[],
            top_result=None,
            query="",
            reranker_used=None,
            threshold=0.62,
        )
        service = GroundingService(
            retrieval_service=mock_retrieval,
            llm_client=AsyncMock(),
            use_llm_extraction=False,
            taxonomy_bridge=None,  # explicitly disabled
            ift_alignment={"grain": ["cereal grains"]},
            pathogen_associations={"cereal grains": ["Salmonella spp."]},
            pathogen_characteristics={
                "salmonella nontyphoidal": (238, "CDC-2019-T1T2")
            },
        )
        grounded = call_fallback(service, "barley")

        assert not grounded.has("organism")
        assert grounded.organism_failure is not None
        assert (
            grounded.organism_failure.stage
            == OrganismGroundingFailureStage.BRIDGE_DISABLED
        )

    def test_no_ift_mapping_returns_without_grounding(self):
        """When ptm_category has no IFT row (e.g. condiment), fallback must not ground anything.

        In production the loader drops empty-ift_category rows, so 'condiment' is absent
        from the dict entirely. Using {} here mirrors that shape; the same `not ift_categories`
        branch handles both the absent-key and empty-list cases.
        """
        service = make_service(
            ift_alignment={},  # condiment absent, matching what the loader produces
            pathogen_associations={},
            pathogen_characteristics={},
        )
        grounded = call_fallback(service, "mustard")

        assert not grounded.has("organism")
        assert grounded.organism_failure is not None
        assert (
            grounded.organism_failure.stage
            == OrganismGroundingFailureStage.CATEGORY_HAS_NO_HAZARD_DATA
        )
        assert grounded.organism_failure.resolved_category is not None
        assert grounded.organism_failure.match_score is not None

    def test_zero_deaths_ranked_last_not_excluded(self):
        """Pathogens with annual_deaths_us=0 rank last but are still candidates."""
        service = make_service(
            ift_alignment={"grain": ["cereal grains"]},
            # Salmonella absent from characteristics, Bacillus cereus has 0 deaths.
            pathogen_associations={"cereal grains": ["Bacillus cereus"]},
            pathogen_characteristics={
                "bacillus cereus": (0, "CDC-2011-T3"),
            },
        )
        grounded = call_fallback(service, "barley")

        assert grounded.has(
            "organism"
        ), "Zero-death pathogen must still be selected if it maps to ComBaseOrganism"
        assert grounded.get("organism") == ComBaseOrganism.BACILLUS_CEREUS
        fb = grounded.provenance["organism"].pathogen_category_fallback
        assert fb.selected_pathogen.annual_deaths_us == 0

    def test_warning_emitted_on_success(self):
        """A transparency warning must be appended to grounded.warnings when fallback succeeds."""
        service = make_service(
            ift_alignment={"grain": ["cereal grains"]},
            pathogen_associations={"cereal grains": ["Salmonella spp."]},
            pathogen_characteristics={
                "salmonella nontyphoidal": (238, "CDC-2019-T1T2")
            },
        )
        grounded = call_fallback(service, "barley")

        assert grounded.has("organism")
        assert len(grounded.warnings) == 1
        warning = grounded.warnings[0]
        assert "grain" in warning
        assert "IFT-2003-T1" in warning
        assert "barley" in warning
