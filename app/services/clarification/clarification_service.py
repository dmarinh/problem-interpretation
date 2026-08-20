"""
Clarification gate question construction: organism (A1a asks, A1b answers)
and multi-step duration (build_duration_question, see below).

Builds a user-facing clarification question when organism grounding fails
closed for a reason a question can actually resolve: the food description
matched nothing (FOOD_UNRECOGNISED), or it resolved to a food category the
hazard source doesn't cover (CATEGORY_HAS_NO_HAZARD_DATA). Every other
organism-grounding failure stage (BRIDGE_DISABLED,
INTERNAL_NO_MAPPABLE_CANDIDATE) and every other missing_required reason
(non-executable organism, missing factor4 bounds) keeps the existing
fail-closed path unchanged — see Orchestrator._build_organism_clarification
(round 1, asking) and Orchestrator._resolve_organism_from_transcript (round
2, re-entry) for the trigger conditions.

Free-text only (2026-08-19, see specs/lessons.md): the question names a few
common, executable pathogens in prose rather than offering a selectable
options menu. The prose is discoverability only — words in the question the
frontend already renders verbatim — not a structured options list. The
reply is resolved deterministically downstream (Orchestrator, via
ComBaseOrganism.all_matches_in_text()), never through an LLM extraction
step: routing a free-text reply through an LLM was the confirmed source of
nondeterministic clarification failures (a clean one-word answer failed
extraction ~50% of the time on identical runs).

Pure and deterministic: given the same stage, food description, and resolved
category, this always produces the same question. No I/O, no LLM call, no
registry access.

Non-goals (A1b is still one round only): no multi-round, no
clarification_context, no server-side session — the caller carries the
round-1 exchange back on the request (ClarificationTranscript).

build_duration_question() (2026-08-17) is a second, independent gate for
multi-step scenarios missing one or more step durations. It shares this
module for the same "pure wording construction, no I/O" discipline, but is
not a variant of the organism flow: duration has no closed option set to
select from (it's an open numeric quantity), so its question has no
`options` field, and its acceptance check (Orchestrator._resolve_duration_reply)
is a structural number-and-range check, not an LLM-extract-then-set-membership
check. See specs/lessons.md for why the two gates are safe for different
reasons.
"""

from app.models.enums import (
    ClarificationReason,
    OrganismGroundingFailureStage,
)
from app.models.metadata import (
    ClarificationQuestion,
    DurationClarificationQuestion,
    DurationClarificationStep,
)

# Common, executable pathogens named in prose in the organism clarification
# question — discoverability only (the frontend renders the question text
# verbatim), not a structured options list. Any executable organism may be
# named in the reply, not just these.
_EXAMPLE_PATHOGENS = "Salmonella, Listeria, E. coli, or Staphylococcus aureus"

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
        resolved_category: str | None = None,
    ) -> ClarificationQuestion:
        """
        Args:
            stage: FOOD_UNRECOGNISED or CATEGORY_HAS_NO_HAZARD_DATA. Any
                other value raises — this method does not decide whether a
                question is appropriate, it trusts the caller's gate and
                validates only that it was called for a handled stage.
            food_description: the user's original food description, echoed
                back in the preamble so the user can see what wasn't
                recognised (or what it resolved to).
            resolved_category: the ptm_category the taxonomy bridge
                resolved to. Required (non-None) for
                CATEGORY_HAS_NO_HAZARD_DATA so the preamble can name the
                actual coverage gap instead of speaking generically; unused
                for FOOD_UNRECOGNISED.

        Returns:
            A ClarificationQuestion with a stage-appropriate preamble asking
            the user to name a pathogen directly, in free text — no options
            menu. The reply is resolved deterministically by the caller
            (ComBaseOrganism.all_matches_in_text()), not by this method.
        """
        if stage not in _STAGE_TO_REASON:
            raise ValueError(
                f"ClarificationService.build_organism_question does not handle "
                f"stage {stage!r} — only FOOD_UNRECOGNISED and "
                f"CATEGORY_HAS_NO_HAZARD_DATA produce a question; every other "
                f"stage must keep the existing fail-closed path."
            )

        if stage == OrganismGroundingFailureStage.FOOD_UNRECOGNISED:
            # The food couldn't be used to infer a pathogen at all. Rephrasing
            # the food *might* help (it's a recognition miss, not a proven
            # coverage gap), but asking for the pathogen directly is the more
            # reliable path, so it's offered first.
            question_text = (
                f'I don\'t recognise "{food_description}" as a food I have '
                "safety data for, so I can't infer which pathogen to model. "
                "Please tell me directly which pathogen you're concerned "
                f"about (for example {_EXAMPLE_PATHOGENS}) — rephrasing the "
                "food description might also help."
            )
        else:
            if not resolved_category:
                raise ValueError(
                    "resolved_category is required for CATEGORY_HAS_NO_HAZARD_DATA "
                    "— OrganismGroundingFailure.resolved_category should always be "
                    "populated for this stage; the caller passed None/empty."
                )
            # The food WAS recognised, and its pH/water activity resolved
            # fine — ComBase models are broth, so the food's only other job
            # was pathogen inference. This stage is purely a hazard-source
            # coverage gap for that inference, so rephrasing won't help;
            # that's the whole reason this wording stays distinct from
            # FOOD_UNRECOGNISED's.
            question_text = (
                f"I recognised \"{food_description}\" as '{resolved_category}' "
                "and resolved its pH and water activity fine, but my hazard "
                "data source (IFT-2003-T1) doesn't cover which pathogens are "
                "typically associated with that category — that's a data "
                "coverage limit, not a misunderstanding, so rephrasing won't "
                "help. Please tell me directly which pathogen you're "
                f"concerned about (for example {_EXAMPLE_PATHOGENS})."
            )

        return ClarificationQuestion(
            reason=_STAGE_TO_REASON[stage],
            stage=stage,
            question=question_text,
        )

    def reason_for_stage(
        self, stage: OrganismGroundingFailureStage
    ) -> ClarificationReason:
        """
        Public accessor for the stage -> reason mapping build_organism_question()
        uses internally.

        A1b needs this on re-entry: it already has the round-1 question text
        verbatim from the transcript (ClarificationTranscript), so rebuilding
        a full ClarificationQuestion via build_organism_question() just to
        read its .reason would be wasteful. Raises the same ValueError as
        build_organism_question() for an unhandled stage — one validation
        rule, not two.
        """
        if stage not in _STAGE_TO_REASON:
            raise ValueError(
                f"ClarificationService.reason_for_stage does not handle "
                f"stage {stage!r} — only FOOD_UNRECOGNISED and "
                f"CATEGORY_HAS_NO_HAZARD_DATA have a reason mapping."
            )
        return _STAGE_TO_REASON[stage]

    def build_duration_question(
        self, steps: list[DurationClarificationStep]
    ) -> DurationClarificationQuestion:
        """
        Build a multi-step duration clarification question — pure and
        deterministic, same discipline as build_organism_question(): given
        the same step list, always produces the same question. No I/O, no
        LLM call. The caller (Orchestrator) derives `steps` from
        grounded.steps (GroundedStep.step_order / duration_phrase) before
        calling in; this method never touches grounding internals.

        Args:
            steps: every step still missing a duration, already resolved by
                the caller — not re-derived or re-filtered here. Must be
                non-empty (the caller only calls this when at least one step
                is missing).

        Returns:
            A DurationClarificationQuestion naming every missing step, quoting
            its duration_phrase where the user said something we couldn't
            resolve, or just naming the step number where they said nothing.
        """
        if not steps:
            raise ValueError(
                "build_duration_question requires at least one missing step "
                "— the caller should only call this when the duration gate "
                "has actually fired."
            )

        def _describe(step: DurationClarificationStep) -> str:
            if step.duration_phrase:
                return f'step {step.step_order} (you said "{step.duration_phrase}")'
            return f"step {step.step_order}"

        described = [_describe(s) for s in steps]
        if len(described) == 1:
            steps_clause = described[0]
        else:
            steps_clause = ", ".join(described[:-1]) + f", and {described[-1]}"

        question_text = (
            f"I need an exact duration to run this prediction, but {steps_clause} "
            "didn't resolve to a specific length. Please provide the duration "
            "in hours for each listed step."
        )

        return DurationClarificationQuestion(
            reason=ClarificationReason.AMBIGUOUS_DURATION,
            question=question_text,
            steps=steps,
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
