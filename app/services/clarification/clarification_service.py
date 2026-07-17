"""
Organism clarification gate — question construction (ask-only, A1a).

Builds a user-facing clarification question when organism grounding fails
closed for a reason a question can actually resolve: the food description
matched nothing (FOOD_UNRECOGNISED), or it resolved to a food category the
hazard source doesn't cover (CATEGORY_HAS_NO_HAZARD_DATA). Every other
organism-grounding failure stage (BRIDGE_DISABLED,
INTERNAL_NO_MAPPABLE_CANDIDATE) and every other missing_required reason
(non-executable organism, missing factor4 bounds, missing duration, ...)
keeps the existing fail-closed path unchanged — see
Orchestrator._build_organism_clarification for the trigger condition.

Pure and deterministic: given the same stage, food description, resolved
category, and ranked organism list, this always produces the same question.
No I/O, no LLM call, no registry access — the orchestrator resolves the
option set (registry executability ∩ pathogen_characteristics.csv, ranked by
CDC annual deaths — see GroundingService.rank_executable_organisms) and
display names (StandardizationService.organism_display_name) before
calling in, so this module never derives or reorders anything itself.

Non-goals (A1a is ask-only): no re-entry, no answer parsing, no
clarification_context — that is A1b.
"""

from app.models.enums import (
    ClarificationReason,
    ComBaseOrganism,
    OrganismGroundingFailureStage,
)
from app.models.metadata import ClarificationOption, ClarificationQuestion

# Not consumed by anything yet — A1a does not wire answer handling.
FREE_TEXT_ESCAPE_CODE = "other"
FREE_TEXT_ESCAPE_LABEL = "Something else / I'm not sure"

# The only two OrganismGroundingFailureStage members a question can resolve.
# Every other stage (BRIDGE_DISABLED, INTERNAL_NO_MAPPABLE_CANDIDATE) means
# no amount of pathogen-naming would help, so the existing fail-closed path
# is left untouched — this service is never called for those stages.
_STAGE_TO_REASON: dict[OrganismGroundingFailureStage, ClarificationReason] = {
    OrganismGroundingFailureStage.FOOD_UNRECOGNISED: (
        ClarificationReason.ORGANISM_FOOD_UNRECOGNIZED
    ),
    OrganismGroundingFailureStage.CATEGORY_HAS_NO_HAZARD_DATA: (
        ClarificationReason.ORGANISM_CATEGORY_UNCOVERED
    ),
}


class ClarificationService:
    """Builds ask-only organism clarification questions. See module docstring."""

    def build_organism_question(
        self,
        stage: OrganismGroundingFailureStage,
        food_description: str,
        ranked_organisms: list[tuple[ComBaseOrganism, str]],
        resolved_category: str | None = None,
    ) -> ClarificationQuestion:
        """
        Args:
            stage: FOOD_UNRECOGNISED or CATEGORY_HAS_NO_HAZARD_DATA. Any
                other value raises — this method does not decide whether a
                question is appropriate, it trusts the caller's gate and
                validates only that it was called for a handled stage.
            food_description: the user's original food description, echoed
                back in the FOOD_UNRECOGNISED preamble so the user can see
                what wasn't recognised.
            ranked_organisms: (organism, display_name) pairs, already
                filtered to organisms executable for this request's
                model_type/factor4_type and ranked by severity by the
                caller (see GroundingService.rank_executable_organisms and
                StandardizationService.organism_display_name). This method
                does not re-derive, re-filter, or re-order them — ordering
                here is presentation order only, not a recommendation.
            resolved_category: the ptm_category the taxonomy bridge
                resolved to. Required (non-None) for
                CATEGORY_HAS_NO_HAZARD_DATA so the preamble can name the
                actual coverage gap instead of speaking generically; unused
                for FOOD_UNRECOGNISED.

        Returns:
            A ClarificationQuestion with a stage-appropriate preamble and
            the given options plus a fixed free-text escape.
        """
        if stage not in _STAGE_TO_REASON:
            raise ValueError(
                f"ClarificationService.build_organism_question does not handle "
                f"stage {stage!r} — only FOOD_UNRECOGNISED and "
                f"CATEGORY_HAS_NO_HAZARD_DATA produce a question; every other "
                f"stage must keep the existing fail-closed path."
            )

        if stage == OrganismGroundingFailureStage.FOOD_UNRECOGNISED:
            question_text = (
                f'I don\'t recognise "{food_description}" as a food I have '
                "safety data for. You could try rephrasing the food, or — if "
                "you already know it — tell me which pathogen you're "
                "concerned about:"
            )
        else:
            if not resolved_category:
                raise ValueError(
                    "resolved_category is required for CATEGORY_HAS_NO_HAZARD_DATA "
                    "— OrganismGroundingFailure.resolved_category should always be "
                    "populated for this stage; the caller passed None/empty."
                )
            question_text = (
                f'I resolved "{food_description}" to the category '
                f"'{resolved_category}', but my hazard data source "
                "(IFT-2003-T1) doesn't cover that category — that's a "
                "coverage limit of the source, not a failure to understand "
                "your query, so rephrasing won't help. If you know which "
                "pathogen you're concerned about, tell me and I can "
                "proceed:"
            )

        options = [
            ClarificationOption(code=organism.value, label=label)
            for organism, label in ranked_organisms
        ]
        options.append(
            ClarificationOption(
                code=FREE_TEXT_ESCAPE_CODE, label=FREE_TEXT_ESCAPE_LABEL
            )
        )

        return ClarificationQuestion(
            reason=_STAGE_TO_REASON[stage],
            stage=stage,
            question=question_text,
            options=options,
        )


_clarification_service: ClarificationService | None = None


def get_clarification_service() -> ClarificationService:
    """Get or create the global ClarificationService instance."""
    global _clarification_service
    if _clarification_service is None:
        _clarification_service = ClarificationService()
    return _clarification_service


def reset_clarification_service() -> None:
    """Reset the global instance (for testing)."""
    global _clarification_service
    _clarification_service = None
