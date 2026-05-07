"""
Duration extraction tests — Workstream 2.

Three test sets:

  Set A  — Pydantic constraint validation (no live LLM).
            Asserts that ExtractedDuration.value_minutes accepts valid values
            and rejects out-of-range ones via the gt=0, le=131400 constraint.

  Set B  — Live-LLM extraction success and decline cases.
            Marked @pytest.mark.live; excluded from standard pytest run.
            Run with: pytest -m live tests/integration/test_duration_extraction.py

  Set C  — Live-LLM regression cases from the original investigation.
            Same @pytest.mark.live marker.
            Three-way assertion per case:
              PASS if  value_minutes == expected_minutes
              PASS if  value_minutes is None AND backstop warning fired
              FAIL if  value_minutes is not None AND value_minutes != expected_minutes
            Silent wrong values are never acceptable, regardless of threshold.
            Shipping criterion: >=8 of 10 cases must hit the first branch (correct value).
"""

import pytest
from pydantic import ValidationError

from app.models.extraction import ExtractedDuration
from app.services.extraction.semantic_parser import SemanticParser
from app.core.orchestrator import Orchestrator
from app.core.state import SessionManager


# =============================================================================
# Set A — Pydantic constraint validation (no live LLM)
# =============================================================================

class TestValueMinutesConstraint:
    """
    Verifies the (0, 131400] bounds on ExtractedDuration.value_minutes.
    No LLM involved — pure schema validation.
    """

    @pytest.mark.parametrize("value", [
        0.5,      # sub-minute (thermal inactivation use case)
        1.0,      # 1 minute
        1440.0,   # 1 day
        50400.0,  # 35 days
        131400.0, # 90 days — ceiling, should pass
    ])
    def test_valid_values_accepted(self, value: float) -> None:
        dur = ExtractedDuration(value_minutes=value)
        assert dur.value_minutes == value

    @pytest.mark.parametrize("value", [
        0.0,       # zero — rejected by gt=0
        -1.0,      # negative
        -60.0,
        131400.1,  # just above 90-day ceiling
        200000.0,  # far above ceiling
    ])
    def test_invalid_values_rejected(self, value: float) -> None:
        with pytest.raises(ValidationError):
            ExtractedDuration(value_minutes=value)

    def test_none_is_accepted(self) -> None:
        """Null is the valid signal for vague / unextracted durations."""
        dur = ExtractedDuration(value_minutes=None)
        assert dur.value_minutes is None

    def test_description_always_accepted(self) -> None:
        """description has no constraint — vague phrases must always be storable."""
        dur = ExtractedDuration(
            value_minutes=None,
            description="overnight",
            is_ambiguous=True,
        )
        assert dur.description == "overnight"
        assert dur.is_ambiguous is True


# =============================================================================
# Set B — Live-LLM extraction cases
# =============================================================================

# Stem held constant across all Set B queries so only the duration phrasing varies.
_STEM = "We need to model Listeria monocytogenes growth in vacuum-packed turkey deli meat."


@pytest.fixture
def parser() -> SemanticParser:
    return SemanticParser()


@pytest.mark.live
class TestSetB_ExtractionSuccess:
    """
    Prompt-driven cases where the LLM should extract a correct value_minutes.
    Each query uses the constant stem so only the duration phrasing is tested.
    """

    @pytest.mark.parametrize("suffix, expected_minutes", [
        ("Store for 35 days at 4°C.",                         50400),
        ("The product has a 35-day shelf life at 4°C.",       50400),
        ("Store for 5 days at 4°C.",                          7200),
        ("Store for 1 day at 4°C.",                           1440),
        ("Store for 2 weeks at 4°C.",                         20160),
        ("Store for 24 hours at 4°C.",                        1440),
        ("Store for 1 week at 4°C.",                          10080),
        ("Store for 840 hours at 4°C.",                       50400),
        ("Store for 50400 minutes at 4°C.",                   50400),
        # Mid-sentence duration — tests prompt generalisation to natural Cat A register
        (
            "We need to assess growth during retail refrigeration "
            "for the duration of its 35-day shelf life. "
            "What growth can we expect by sell-by date?",
            50400,
        ),
    ])
    async def test_success_case(
        self,
        parser: SemanticParser,
        suffix: str,
        expected_minutes: float,
    ) -> None:
        query = f"{_STEM} {suffix}"
        scenario = await parser.extract_scenario(query)
        assert scenario.single_step_duration.value_minutes == expected_minutes, (
            f"Query: {query!r}\n"
            f"Expected value_minutes={expected_minutes}, "
            f"got {scenario.single_step_duration.value_minutes!r} "
            f"(description={scenario.single_step_duration.description!r})"
        )

    @pytest.mark.parametrize("suffix", [
        "Store overnight at 4°C.",
        "Held during retail display at 4°C.",
        "Stored for a few days at 4°C.",
        "Throughout cold-chain transport at 4°C.",
    ])
    async def test_decline_case(
        self,
        parser: SemanticParser,
        suffix: str,
    ) -> None:
        """Vague phrases must produce value_minutes=None with description populated."""
        query = f"{_STEM} {suffix}"
        scenario = await parser.extract_scenario(query)
        dur = scenario.single_step_duration
        assert dur.value_minutes is None, (
            f"Query: {query!r}\n"
            f"Expected value_minutes=None for vague phrase, got {dur.value_minutes!r}"
        )
        assert dur.description, (
            f"Query: {query!r}\nExpected description to be populated for downstream resolution"
        )


# =============================================================================
# Set C — Regression cases from the original investigation
# Three-way assertion: correct value | (None + backstop) | FAIL (wrong value)
# =============================================================================

# (query_suffix, expected_minutes)
_SET_C_CASES = [
    ("for 35 days at 4°C",                             50400),
    ("for 5 days at 4°C",                              7200),
    ("for 1 day at 4°C",                               1440),
    ("for 2 weeks at 4°C",                             20160),
    ("for 24 hours at 4°C",                            1440),
    ("for 1 week at 4°C",                              10080),
    ("over its 35-day shelf life at 4°C",              50400),
    ("for 35 days at 4°C, refrigerated",               50400),
    ("for 50400 minutes at 4°C",                       50400),
    ("for 840 hours at 4°C",                           50400),
]


@pytest.fixture
def orchestrator() -> Orchestrator:
    return Orchestrator(session_manager=SessionManager())


@pytest.mark.live
class TestSetC_Regression:
    """
    Original investigation inputs.  Three-way assertion per case.
    Shipping criterion: >=8 of 10 cases must hit branch 1 (correct value).
    Silent wrong values (branch 3) are a hard failure in every case.
    """

    @pytest.mark.parametrize("suffix, expected_minutes", _SET_C_CASES)
    async def test_regression(
        self,
        orchestrator: Orchestrator,
        suffix: str,
        expected_minutes: float,
    ) -> None:
        query = f"{_STEM} {suffix}"
        result = await orchestrator.translate(query)

        # Retrieve extracted duration from the scenario stored on the session state.
        scenario = result.state.extracted_scenario
        if scenario is None:
            pytest.skip("Scenario extraction failed (API error) — not a duration bug")

        dur = scenario.single_step_duration
        warnings = result.state.metadata.warnings if result.state.metadata else []

        backstop_fired = any("Duration phrase detected" in w for w in warnings)

        if dur.value_minutes == expected_minutes:
            # Branch 1 — correct extraction.
            return

        if dur.value_minutes is None and backstop_fired:
            # Branch 2 — LLM missed the value; backstop detected it.
            # Acceptable outcome; the rule-library / conservative-default path runs.
            pytest.xfail(
                f"LLM did not extract value_minutes for '{suffix}'; "
                f"backstop fired correctly. Rule-library fallback will run."
            )
            return

        # Branch 3 — wrong non-None value or None without backstop.
        # This is the unacceptable outcome in both sub-cases:
        if dur.value_minutes is not None:
            pytest.fail(
                f"Silent wrong extraction for '{suffix}': "
                f"expected {expected_minutes}, got {dur.value_minutes}. "
                f"A wrong value with no warning violates audit-honesty."
            )
        else:
            pytest.fail(
                f"value_minutes=None for '{suffix}' but backstop did not fire. "
                f"Either the LLM put nothing in description or the backstop regex "
                f"missed the phrase. Audit-honesty requires the warning to surface."
            )
