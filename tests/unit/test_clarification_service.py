"""
Unit tests for ClarificationService (organism clarification gate,
question construction only — no re-entry/answer handling).

Free-text only (2026-08-19): no options menu, so build_organism_question()
no longer takes ranked_organisms. Its question names a few example
pathogens in prose instead.
"""

import pytest

from app.models.enums import ClarificationReason, OrganismGroundingFailureStage
from app.models.metadata import DurationClarificationStep
from app.services.clarification.clarification_service import (
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
            resolved_category="should be ignored",
        )
        assert "should be ignored" not in question.question

    def test_question_names_example_pathogens_in_prose(
        self, service: ClarificationService
    ) -> None:
        """Discoverability without a menu: the question itself names a few
        common, executable pathogens as examples."""
        question = service.build_organism_question(
            stage=OrganismGroundingFailureStage.FOOD_UNRECOGNISED,
            food_description="frobnitz",
        )
        assert "Salmonella" in question.question
        assert "Listeria" in question.question

    def test_has_no_options_field(self, service: ClarificationService) -> None:
        question = service.build_organism_question(
            stage=OrganismGroundingFailureStage.FOOD_UNRECOGNISED,
            food_description="frobnitz",
        )
        assert not hasattr(question, "options")


class TestCategoryUncoveredQuestion:
    def test_preamble_names_category_and_coverage_limit(
        self, service: ClarificationService
    ) -> None:
        question = service.build_organism_question(
            stage=OrganismGroundingFailureStage.CATEGORY_HAS_NO_HAZARD_DATA,
            food_description="mustard",
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
                resolved_category=None,
            )

    def test_question_names_example_pathogens_in_prose(
        self, service: ClarificationService
    ) -> None:
        question = service.build_organism_question(
            stage=OrganismGroundingFailureStage.CATEGORY_HAS_NO_HAZARD_DATA,
            food_description="mustard",
            resolved_category="condiment",
        )
        assert "Salmonella" in question.question
        assert "Listeria" in question.question


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
                resolved_category="condiment",
            )
            assert question.reason == service.reason_for_stage(stage)


class TestOrganismQuestionDeterminism:
    def test_deterministic_given_same_inputs(
        self, service: ClarificationService
    ) -> None:
        args = {
            "stage": OrganismGroundingFailureStage.FOOD_UNRECOGNISED,
            "food_description": "frobnitz",
        }
        q1 = service.build_organism_question(**args)
        q2 = service.build_organism_question(**args)
        assert q1 == q2


class TestBuildDurationQuestion:
    """2026-08-17: multi-step duration clarification gate — question
    construction only. No LLM, no I/O, deterministic given the same steps —
    same discipline as build_organism_question(), but no `options` field:
    duration is an open numeric quantity, not a closed menu."""

    def test_single_step_with_phrase_is_quoted(
        self, service: ClarificationService
    ) -> None:
        question = service.build_duration_question(
            [DurationClarificationStep(step_order=2, duration_phrase="a while")]
        )
        assert "step 2" in question.question
        assert '"a while"' in question.question
        assert question.reason == ClarificationReason.AMBIGUOUS_DURATION
        assert question.steps == [
            DurationClarificationStep(step_order=2, duration_phrase="a while")
        ]

    def test_single_step_without_phrase_names_step_only(
        self, service: ClarificationService
    ) -> None:
        question = service.build_duration_question(
            [DurationClarificationStep(step_order=1, duration_phrase=None)]
        )
        assert "step 1" in question.question
        assert '"' not in question.question

    def test_multiple_steps_all_named_in_one_question(
        self, service: ClarificationService
    ) -> None:
        question = service.build_duration_question(
            [
                DurationClarificationStep(step_order=1, duration_phrase="a while"),
                DurationClarificationStep(step_order=2, duration_phrase=None),
                DurationClarificationStep(step_order=3, duration_phrase="ages"),
            ]
        )
        assert "step 1" in question.question
        assert "step 2" in question.question
        assert "step 3" in question.question
        assert [s.step_order for s in question.steps] == [1, 2, 3]

    def test_empty_steps_raises(self, service: ClarificationService) -> None:
        with pytest.raises(ValueError):
            service.build_duration_question([])

    def test_deterministic_given_same_inputs(
        self, service: ClarificationService
    ) -> None:
        steps = [DurationClarificationStep(step_order=1, duration_phrase="a while")]
        q1 = service.build_duration_question(steps)
        q2 = service.build_duration_question(steps)
        assert q1 == q2

    def test_no_options_field(self, service: ClarificationService) -> None:
        """Unlike ClarificationQuestion, there is nothing to select from."""
        question = service.build_duration_question(
            [DurationClarificationStep(step_order=1, duration_phrase=None)]
        )
        assert not hasattr(question, "options")


class TestSingleton:
    def test_get_returns_same_instance(self) -> None:
        reset_clarification_service()
        a = get_clarification_service()
        b = get_clarification_service()
        assert a is b
        reset_clarification_service()
