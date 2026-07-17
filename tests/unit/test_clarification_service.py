"""
Unit tests for ClarificationService (A1a organism clarification gate,
question construction only — no re-entry/answer handling).
"""

import pytest

from app.models.enums import (
    ClarificationReason,
    ComBaseOrganism,
    OrganismGroundingFailureStage,
)
from app.services.clarification.clarification_service import (
    FREE_TEXT_ESCAPE_CODE,
    ClarificationService,
    get_clarification_service,
    reset_clarification_service,
)


@pytest.fixture
def service() -> ClarificationService:
    return ClarificationService()


class TestFoodUnrecognisedQuestion:
    def test_preamble_names_food_and_offers_rephrase_or_pathogen(
        self, service: ClarificationService
    ) -> None:
        question = service.build_organism_question(
            stage=OrganismGroundingFailureStage.FOOD_UNRECOGNISED,
            food_description="frobnitz",
            ranked_organisms=[(ComBaseOrganism.SALMONELLA, "Salmonella")],
        )

        assert "frobnitz" in question.question
        assert "rephrasing" in question.question or "rephrase" in question.question
        assert question.reason == ClarificationReason.ORGANISM_FOOD_UNRECOGNIZED
        assert question.stage == OrganismGroundingFailureStage.FOOD_UNRECOGNISED

    def test_does_not_reference_resolved_category(
        self, service: ClarificationService
    ) -> None:
        """FOOD_UNRECOGNISED means the bridge never resolved a category at all —
        the preamble must not claim otherwise even if resolved_category is
        (incorrectly) passed."""
        question = service.build_organism_question(
            stage=OrganismGroundingFailureStage.FOOD_UNRECOGNISED,
            food_description="frobnitz",
            ranked_organisms=[(ComBaseOrganism.SALMONELLA, "Salmonella")],
            resolved_category="should be ignored",
        )
        assert "should be ignored" not in question.question


class TestCategoryUncoveredQuestion:
    def test_preamble_names_category_and_coverage_limit(
        self, service: ClarificationService
    ) -> None:
        question = service.build_organism_question(
            stage=OrganismGroundingFailureStage.CATEGORY_HAS_NO_HAZARD_DATA,
            food_description="mustard",
            ranked_organisms=[(ComBaseOrganism.SALMONELLA, "Salmonella")],
            resolved_category="condiment",
        )

        assert "mustard" in question.question
        assert "condiment" in question.question
        assert "IFT-2003-T1" in question.question
        assert (
            "rephrasing won't help" in question.question
            or "rephrasing won" in question.question
        )
        assert question.reason == ClarificationReason.ORGANISM_CATEGORY_UNCOVERED
        assert (
            question.stage == OrganismGroundingFailureStage.CATEGORY_HAS_NO_HAZARD_DATA
        )

    def test_requires_resolved_category(self, service: ClarificationService) -> None:
        with pytest.raises(ValueError, match="resolved_category"):
            service.build_organism_question(
                stage=OrganismGroundingFailureStage.CATEGORY_HAS_NO_HAZARD_DATA,
                food_description="mustard",
                ranked_organisms=[(ComBaseOrganism.SALMONELLA, "Salmonella")],
                resolved_category=None,
            )


class TestUnhandledStagesRejected:
    @pytest.mark.parametrize(
        "stage",
        [
            OrganismGroundingFailureStage.BRIDGE_DISABLED,
            OrganismGroundingFailureStage.INTERNAL_NO_MAPPABLE_CANDIDATE,
        ],
    )
    def test_raises_for_non_clarifiable_stage(
        self, service: ClarificationService, stage: OrganismGroundingFailureStage
    ) -> None:
        with pytest.raises(ValueError, match="does not handle"):
            service.build_organism_question(
                stage=stage,
                food_description="anything",
                ranked_organisms=[(ComBaseOrganism.SALMONELLA, "Salmonella")],
            )


class TestReasonForStage:
    """A1b: reason_for_stage() — the standalone stage->reason lookup used on
    re-entry, when the full question doesn't need to be rebuilt."""

    def test_food_unrecognised(self, service: ClarificationService) -> None:
        assert (
            service.reason_for_stage(OrganismGroundingFailureStage.FOOD_UNRECOGNISED)
            == ClarificationReason.ORGANISM_FOOD_UNRECOGNIZED
        )

    def test_category_has_no_hazard_data(self, service: ClarificationService) -> None:
        assert (
            service.reason_for_stage(
                OrganismGroundingFailureStage.CATEGORY_HAS_NO_HAZARD_DATA
            )
            == ClarificationReason.ORGANISM_CATEGORY_UNCOVERED
        )

    @pytest.mark.parametrize(
        "stage",
        [
            OrganismGroundingFailureStage.BRIDGE_DISABLED,
            OrganismGroundingFailureStage.INTERNAL_NO_MAPPABLE_CANDIDATE,
        ],
    )
    def test_raises_for_non_clarifiable_stage(
        self, service: ClarificationService, stage: OrganismGroundingFailureStage
    ) -> None:
        with pytest.raises(ValueError, match="does not handle"):
            service.reason_for_stage(stage)

    def test_matches_build_organism_question_reason(
        self, service: ClarificationService
    ) -> None:
        """Same mapping both ways — one source of truth, not two."""
        for stage in (
            OrganismGroundingFailureStage.FOOD_UNRECOGNISED,
            OrganismGroundingFailureStage.CATEGORY_HAS_NO_HAZARD_DATA,
        ):
            question = service.build_organism_question(
                stage=stage,
                food_description="frobnitz",
                ranked_organisms=[(ComBaseOrganism.SALMONELLA, "Salmonella")],
                resolved_category="condiment",
            )
            assert question.reason == service.reason_for_stage(stage)


class TestOptionAssembly:
    def test_options_preserve_caller_order_and_append_free_text_escape(
        self, service: ClarificationService
    ) -> None:
        question = service.build_organism_question(
            stage=OrganismGroundingFailureStage.FOOD_UNRECOGNISED,
            food_description="frobnitz",
            ranked_organisms=[
                (ComBaseOrganism.SALMONELLA, "Salmonella"),
                (ComBaseOrganism.LISTERIA_MONOCYTOGENES, "Listeria monocytogenes"),
            ],
        )

        codes = [o.code for o in question.options]
        labels = [o.label for o in question.options]

        assert codes == [
            ComBaseOrganism.SALMONELLA.value,
            ComBaseOrganism.LISTERIA_MONOCYTOGENES.value,
            FREE_TEXT_ESCAPE_CODE,
        ]
        assert labels[:2] == ["Salmonella", "Listeria monocytogenes"]
        assert (
            "something else" in labels[-1].lower() or "not sure" in labels[-1].lower()
        )

    def test_empty_ranked_organisms_still_offers_free_text_escape(
        self, service: ClarificationService
    ) -> None:
        question = service.build_organism_question(
            stage=OrganismGroundingFailureStage.FOOD_UNRECOGNISED,
            food_description="frobnitz",
            ranked_organisms=[],
        )
        assert len(question.options) == 1
        assert question.options[0].code == FREE_TEXT_ESCAPE_CODE

    def test_deterministic_given_same_inputs(
        self, service: ClarificationService
    ) -> None:
        args = {
            "stage": OrganismGroundingFailureStage.FOOD_UNRECOGNISED,
            "food_description": "frobnitz",
            "ranked_organisms": [(ComBaseOrganism.SALMONELLA, "Salmonella")],
        }
        q1 = service.build_organism_question(**args)
        q2 = service.build_organism_question(**args)
        assert q1 == q2


class TestSingleton:
    def test_get_returns_same_instance(self) -> None:
        reset_clarification_service()
        a = get_clarification_service()
        b = get_clarification_service()
        assert a is b
        reset_clarification_service()
