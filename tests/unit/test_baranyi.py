"""
Unit tests for the Baranyi-Roberts primary growth model
(predictive/primary/baranyi.py).

Three kinds of proof, matching the task that added this module:
1. Frontend-oracle reproduction (TestFrontendExamples) -- the three
   worked examples from the validated TypeScript port, reproduced to the
   stated tolerances. A mismatch here means the port is wrong.
2. Units-contract regression (TestUnitsContract) -- a deliberately
   constructed check that would fail if y_max_ln/mu_max_ln were ever
   multiplied by ln(10) by mistake (the single highest-risk bug in a
   mixed-basis port).
3. Round-trip correctness for the inverse (TestRoundTrip) -- no external
   oracle for time_to_target(), so forward->inverse->recovered-time is
   the proof, across h0=0 and h0>0, growth and inactivation.
"""

import math

import pytest

from predictive.primary.baranyi import (
    BaranyiInverseResult,
    BaranyiOutcome,
    BaranyiParams,
    population_at,
    time_to_target,
)

_LN10 = math.log(10)


class TestFrontendExamples:
    """Reproduce the three worked examples from baranyi.test.ts exactly."""

    def test_example_a_static_growth(self):
        """Static growth, renderLag=false (h0Eff=0). muEffLn back-derived
        from the (possibly-capped) log_increase, per the reference --
        not the raw polynomial mu_max."""
        y0 = 4.0
        duration_minutes = 240.0
        log_increase = 0.8377860811922253
        mu_eff_ln = (log_increase * _LN10) / (duration_minutes / 60.0)
        # ~0.48228, matching the reference to the precision it was quoted at.
        assert mu_eff_ln == pytest.approx(0.4822792764, abs=1e-4)

        params = BaranyiParams(
            initial_log_cfu=y0,
            y_max_ln=19.6,
            mu_max_ln=mu_eff_ln,
            is_growth=True,
            h0=0.0,  # renderLag=false in the reference -> h0Eff=0
        )
        endpoint = population_at(params, duration_minutes)

        expected = 4.837786081192226
        # Reference's own documented tolerance: ~1e-4 systematic gap is
        # expected (Baranyi's stationary-phase correction vs. PTM's linear
        # total_log_increase), not a bug -- see specs/lessons.md.
        assert endpoint == pytest.approx(expected, abs=1e-3)

    def test_example_b_thermal_inactivation_capped(self):
        """Thermal inactivation, mCurv=0 (no asymptote correction) -> exact
        match, no correction-term gap. log_increase is the CLAMPED value
        (-15, the physical-plausibility cap); raw mu_max was -1797.7 and
        must not be used."""
        y0 = 0.0
        duration_minutes = 10.0
        log_increase = -15.0
        mu_eff_ln = (log_increase * _LN10) / (duration_minutes / 60.0)
        assert mu_eff_ln == pytest.approx(-207.2326, abs=1e-3)

        params = BaranyiParams(
            initial_log_cfu=y0,
            y_max_ln=-27.0,
            mu_max_ln=mu_eff_ln,
            is_growth=False,
            h0=0.0,
        )
        endpoint = population_at(params, duration_minutes)

        assert endpoint == pytest.approx(-15.0, abs=1e-6)

    def test_example_c_dynamic_three_step_growth(self):
        """Dynamic 3-step growth: each step's endpoint population becomes
        the next step's y0, exactly as generateBaranyiCurveDynamic does
        (yCurrentLn carried across steps, re-evaluated at the step's exact
        end). h0Eff=0 throughout (renderLag=false)."""
        y0 = 3.0
        y_max_ln = 19.6
        steps = [
            (180.0, 1.2066952725481046),
            (240.0, 0.3469576737544402),
            (300.0, 1.0472326014902817),
        ]

        y_current = y0
        for duration_minutes, log_increase in steps:
            mu_ln = (log_increase * _LN10) / (duration_minutes / 60.0)
            params = BaranyiParams(
                initial_log_cfu=y_current,
                y_max_ln=y_max_ln,
                mu_max_ln=mu_ln,
                is_growth=True,
                h0=0.0,
            )
            y_current = population_at(params, duration_minutes)

        expected = 5.600885547792826
        # Reference's own documented tolerance: gap accumulates across
        # steps from the same correction-term effect as Example A.
        assert y_current == pytest.approx(expected, abs=1e-2)


class TestUnitsContract:
    """
    Regression tests for the mixed-basis units contract. Each of these
    would fail loudly (not subtly) if a uniform conversion were applied
    by mistake -- the whole point of naming fields _ln/_log_cfu.
    """

    def test_y_max_ln_is_not_multiplied_by_ln10(self):
        """y_max=19.6 is already ln(CFU/g) (~3.27e8 CFU/g via exp(19.6) --
        biologically plausible). If a bug multiplied it by ln(10), the
        effective ceiling would be ~45.1 ln (~4e19 CFU/g -- physically
        absurd) and a short-duration growth curve would never come close
        to clamping against it either way, but a longer one would show a
        wildly wrong asymptote. This test uses a duration long enough to
        approach the real asymptote and asserts the endpoint lands near
        19.6, not near the y_max*ln(10) figure a bug would produce."""
        params = BaranyiParams(
            initial_log_cfu=3.0,
            y_max_ln=19.6,
            mu_max_ln=0.5,
            is_growth=True,
            h0=0.0,
        )
        # 100 hours at mu=0.5 is far past saturation for y_max=19.6.
        endpoint = population_at(params, duration_minutes=100 * 60)
        assert endpoint == pytest.approx(19.6 / _LN10, abs=0.05)
        # If y_max_ln had been wrongly multiplied by ln(10) (~45.13
        # instead of 19.6), the endpoint would land near 45.13/ln(10)
        # =~19.6*ln(10) =~ 45.1 log10 CFU -- nowhere near the correct value.
        assert endpoint < 25.0

    def test_initial_log_cfu_is_converted_to_ln(self):
        """At t=0, population_at() must return exactly initial_log_cfu
        back out (log10 in, log10 out) -- this fails if the internal ln
        conversion is missing or doubled."""
        params = BaranyiParams(
            initial_log_cfu=4.5, y_max_ln=19.6, mu_max_ln=0.5, is_growth=True
        )
        assert population_at(params, duration_minutes=0.0) == pytest.approx(
            4.5, abs=1e-9
        )

    def test_duration_minutes_converted_to_hours(self):
        """60 minutes must produce the same result as duration expressed
        directly as 1 hour internally -- i.e. the /60 conversion actually
        happens. Cross-checked against a hand-computed no-lag, no-asymptote
        value: y = y0 + mu*t/ln(10)."""
        params = BaranyiParams(
            initial_log_cfu=3.0, y_max_ln=19.6, mu_max_ln=0.5, is_growth=False, h0=0.0
        )
        endpoint = population_at(params, duration_minutes=60.0)
        expected = 3.0 + (0.5 * 1.0) / _LN10  # mCurv=0: y0 + mu*t, t in hours
        assert endpoint == pytest.approx(expected, abs=1e-9)


class TestH0Parameterization:
    """Part 2: h0 is a parameter, defaults to 0, is never read from a CSV
    fitted value (there is no CSV/model argument anywhere in this module's
    signatures -- structurally impossible to read one in by accident)."""

    def test_h0_defaults_to_zero(self):
        params = BaranyiParams(
            initial_log_cfu=3.0, y_max_ln=19.6, mu_max_ln=0.5, is_growth=True
        )
        assert params.h0 == 0.0

    def test_h0_zero_is_numerically_clean(self):
        """No blow-up (division by the h0 that appears in the denominator
        of the lag-adjustment term) when h0=0 -- the dedicated h0==0
        branch must be taken, not a division-by-zero path."""
        params = BaranyiParams(
            initial_log_cfu=3.0, y_max_ln=19.6, mu_max_ln=0.792, is_growth=True, h0=0.0
        )
        result = population_at(params, duration_minutes=240.0)
        assert math.isfinite(result)
        # h0=0 means no lag: the curve should already show meaningful
        # growth from t=0 (no flat lag-phase plateau).
        assert result > 3.0

    def test_h0_negative_rejected(self):
        """h0<0 is not a valid parameter (unlike the legacy dmy(), which
        silently no-ops on it) -- this module raises rather than silently
        returning y0, since a negative h0 can only arise from caller error."""
        with pytest.raises(ValueError, match="h0"):
            BaranyiParams(
                initial_log_cfu=3.0,
                y_max_ln=19.6,
                mu_max_ln=0.5,
                is_growth=True,
                h0=-1.0,
            )


class TestForwardPathIndependence:
    """Part 3 (of the recon): confirm PTM's existing log-linear forward
    path is untouched and independent -- calculate_log_increase() and
    Baranyi's population_at() are two different consumers of the same
    mu_max, computing different (and each internally consistent) things."""

    def test_baranyi_and_log_linear_agree_at_the_no_lag_no_asymptote_limit(self):
        """When h0=0 and the population is far from y_max (asymptote
        correction negligible), Baranyi's forward output should closely
        match PTM's existing linear calculate_log_increase() formula
        (mu*t/ln(10)) -- both are approximating the same unbounded
        exponential growth in that regime, from two independent code
        paths that never call each other."""
        mu_max = 0.792
        duration_hours = 1.0  # short enough that y_max correction is negligible
        y0 = 3.0
        y_max_ln = (
            19.6 * 5
        )  # push the asymptote far away to isolate the no-correction regime

        params = BaranyiParams(
            initial_log_cfu=y0,
            y_max_ln=y_max_ln,
            mu_max_ln=mu_max,
            is_growth=True,
            h0=0.0,
        )
        baranyi_endpoint = population_at(params, duration_minutes=duration_hours * 60)

        # PTM's own existing formula (calculator.calculate_log_increase, for
        # mu_max > 0): log_increase = mu_max * duration_hours / ln(10)
        log_linear_log_increase = mu_max * duration_hours / _LN10
        log_linear_endpoint = y0 + log_linear_log_increase

        # "Closely match," not identical -- the mCurv=10 correction term is
        # never exactly zero, only negligible far from y_max. 1e-4 is loose
        # enough to accommodate that residual while still being three
        # orders of magnitude tighter than the ~ln(10)=2.3 gap a units bug
        # (e.g. a stray *ln(10) on y_max_ln) would actually produce.
        assert baranyi_endpoint == pytest.approx(log_linear_endpoint, abs=1e-4)


class TestInverseOutcomes:
    """Part 3: the three honest outcomes."""

    def test_reached(self):
        params = BaranyiParams(
            initial_log_cfu=3.0, y_max_ln=19.6, mu_max_ln=0.792, is_growth=True, h0=0.0
        )
        result = time_to_target(params, target_log_increase=2.0)
        assert result.outcome == BaranyiOutcome.REACHED
        assert result.hours is not None
        assert result.hours > 0

    def test_already_met_zero_target(self):
        params = BaranyiParams(
            initial_log_cfu=3.0, y_max_ln=19.6, mu_max_ln=0.792, is_growth=True
        )
        result = time_to_target(params, target_log_increase=0.0)
        assert result == BaranyiInverseResult(BaranyiOutcome.ALREADY_MET, 0.0)

    def test_already_met_negative_target_while_growing(self):
        params = BaranyiParams(
            initial_log_cfu=3.0, y_max_ln=19.6, mu_max_ln=0.792, is_growth=True
        )
        result = time_to_target(params, target_log_increase=-5.0)
        assert result.outcome == BaranyiOutcome.ALREADY_MET
        assert result.hours == 0.0

    def test_already_met_positive_target_while_inactivating(self):
        """Symmetric case: asking for an 'increase' while the model
        predicts decline -- already at/above that trivially, at t=0."""
        params = BaranyiParams(
            initial_log_cfu=3.0, y_max_ln=-27.0, mu_max_ln=-100.0, is_growth=False
        )
        result = time_to_target(params, target_log_increase=5.0)
        assert result.outcome == BaranyiOutcome.ALREADY_MET
        assert result.hours == 0.0

    def test_unreachable_target_beyond_asymptote(self):
        """Target above y_max (in log10) is never reached in finite time
        -- this is a fact about the model, not a solver failure."""
        params = BaranyiParams(
            initial_log_cfu=3.0, y_max_ln=19.6, mu_max_ln=0.792, is_growth=True
        )
        y_max_log10 = 19.6 / _LN10
        result = time_to_target(params, target_log_increase=(y_max_log10 - 3.0) + 1.0)
        assert result == BaranyiInverseResult(BaranyiOutcome.UNREACHABLE, None)

    def test_no_wrong_direction_unreachable_case_without_an_asymptote(self):
        """mCurv=0 (no y_max bound) has no "wrong direction, eventually
        gives up" case distinct from ALREADY_MET: outcomes are threshold
        crossings on a monotonic, unbounded curve, so "asking for a target
        on the side already passed" is always trivially already met at
        t=0, never a genuine failure-to-reach. (Contrast with mCurv=10,
        where the y_max asymptote creates a real UNREACHABLE case --
        test_unreachable_target_beyond_asymptote above.) This is the same
        input as test_already_met_positive_target_while_inactivating,
        named here to make the "no unreachable case" property explicit."""
        params = BaranyiParams(
            initial_log_cfu=3.0, y_max_ln=-27.0, mu_max_ln=-50.0, is_growth=False
        )
        result = time_to_target(params, target_log_increase=2.0)
        assert result == BaranyiInverseResult(BaranyiOutcome.ALREADY_MET, 0.0)

    def test_unreachable_flat_curve(self):
        """mu_max_ln == 0: population never changes; any nonzero-direction
        target is unreachable."""
        params = BaranyiParams(
            initial_log_cfu=3.0, y_max_ln=19.6, mu_max_ln=0.0, is_growth=True
        )
        result = time_to_target(params, target_log_increase=1.0)
        assert result == BaranyiInverseResult(BaranyiOutcome.UNREACHABLE, None)

    def test_declining_target_is_reached_not_already_met(self):
        """Standalone regression for the direction-fix (code review caught
        this in a first draft that unconditionally treated any
        target_log_increase<=0 as ALREADY_MET, which is only correct while
        growing -- for a declining/inactivation scenario a negative target
        is the NORMAL reachable case, not a trivial pre-condition. Isolated
        from the round-trip mechanism so a regression here fails on its own
        terms, not indirectly via a tolerance in TestRoundTrip."""
        params = BaranyiParams(
            initial_log_cfu=3.0, y_max_ln=-27.0, mu_max_ln=-50.0, is_growth=False
        )
        result = time_to_target(params, target_log_increase=-2.0)
        assert result.outcome == BaranyiOutcome.REACHED
        assert result.hours is not None
        assert result.hours > 0


class TestRoundTrip:
    """
    Correctness proof for the analytic inverse, with no external oracle:
    population_at(T) -> target; time_to_target(target) must recover T.
    Covers h0=0 and h0>0, growth (mCurv=10) and inactivation (mCurv=0).
    """

    @pytest.mark.parametrize("h0", [0.0, 1.5, 3.29, 8.0])
    @pytest.mark.parametrize("t_true_hours", [0.1, 0.5, 1.0, 2.0, 5.0, 10.0])
    def test_round_trip_growth(self, h0, t_true_hours):
        params = BaranyiParams(
            initial_log_cfu=3.0, y_max_ln=19.6, mu_max_ln=0.792, is_growth=True, h0=h0
        )
        y_end = population_at(params, duration_minutes=t_true_hours * 60)
        target = y_end - params.initial_log_cfu

        result = time_to_target(params, target_log_increase=target)

        assert result.outcome == BaranyiOutcome.REACHED
        assert result.hours == pytest.approx(t_true_hours, abs=1e-6)

    @pytest.mark.parametrize("h0", [0.0, 1.8])
    @pytest.mark.parametrize("t_true_hours", [0.05, 0.1, 0.2, 0.5])
    def test_round_trip_inactivation(self, h0, t_true_hours):
        params = BaranyiParams(
            initial_log_cfu=3.0,
            y_max_ln=-27.0,
            mu_max_ln=-100.0,
            is_growth=False,
            h0=h0,
        )
        y_end = population_at(params, duration_minutes=t_true_hours * 60)
        target = y_end - params.initial_log_cfu

        result = time_to_target(params, target_log_increase=target)

        assert result.outcome == BaranyiOutcome.REACHED
        assert result.hours == pytest.approx(t_true_hours, abs=1e-6)

    @pytest.mark.parametrize("h0", [0.0, 2.0, 6.0])
    @pytest.mark.parametrize("t_true_hours", [12.0, 18.0, 24.0, 30.0])
    def test_round_trip_growth_long_duration(self, h0, t_true_hours):
        """Extends the round-trip envelope well past this class's original
        0.1-10h range, into durations that saturate the curve close to
        y_max at a moderate mu_max_ln -- the region a code review fuzz
        pass found crashing/wrong in the first version of this function
        (see specs/lessons.md, 2026-08-22). A moderate-rate, moderate-
        duration, non-degenerate scenario -- exactly the shape a real
        caller would use, not a contrived edge case."""
        params = BaranyiParams(
            initial_log_cfu=2.0, y_max_ln=19.6, mu_max_ln=1.1, is_growth=True, h0=h0
        )
        y_end = population_at(params, duration_minutes=t_true_hours * 60)
        target = y_end - params.initial_log_cfu

        result = time_to_target(params, target_log_increase=target)

        # Either a correctly-recovered REACHED, or an honest UNREACHABLE if
        # the curve has saturated to y_max within float precision by
        # t_true_hours -- never a crash, never a silently wrong REACHED.
        if result.outcome == BaranyiOutcome.REACHED:
            assert result.hours is not None and math.isfinite(result.hours)
            assert result.hours == pytest.approx(t_true_hours, rel=1e-3, abs=1e-2)
        else:
            assert result.outcome == BaranyiOutcome.UNREACHABLE
            assert result.hours is None
            y_max_log10 = params.y_max_ln / _LN10
            assert y_end == pytest.approx(y_max_log10, abs=1e-6)


class TestNumericalStability:
    """
    Regression tests for two HIGH-severity numerical bugs code review found
    by fuzzing (specs/lessons.md, 2026-08-22): the first version of
    time_to_target() could raise ValueError/OverflowError, or silently
    return a non-finite "REACHED" result, for realistic (not adversarial)
    inputs -- a moderate-duration growth query near saturation, and an
    inactivation query asking for a large-but-real log reduction with
    h0>0. Both are ordinary food-safety questions, not contrived stress
    inputs. Fixed by (1) deriving the asymptote-reachability check from the
    same quantity the z computation uses, instead of two independently-
    rounded expressions that could disagree at the near-singular boundary,
    and (2) computing the h0>0 time inversion via a log-sum-exp form that
    never exponentiates a large positive argument, mirroring how _dmy_ln
    itself avoids the same failure mode in the forward direction.
    """

    def test_near_saturation_growth_does_not_crash(self):
        """Exact reproduction of the code-review finding: a moderate rate
        over ~21 hours saturates this scenario's curve to y_max within
        float64 precision. Must return a clean outcome, never raise."""
        params = BaranyiParams(
            initial_log_cfu=-1.6814866040566878,
            y_max_ln=16.277512957010906,
            mu_max_ln=4.412431379609677,
            is_growth=True,
            h0=0.0,
        )
        y_end = population_at(params, duration_minutes=21.243092426704795 * 60)
        target = y_end - params.initial_log_cfu

        result = time_to_target(params, target_log_increase=target)

        assert result.outcome in (BaranyiOutcome.REACHED, BaranyiOutcome.UNREACHABLE)
        if result.outcome == BaranyiOutcome.REACHED:
            assert result.hours is not None and math.isfinite(result.hours)
        else:
            assert result.hours is None

    def test_large_log_reduction_with_lag_is_reached_not_unreachable(self):
        """A large-but-physically-real inactivation target (a log
        reduction far beyond typical validated process values, but still
        finite and, per population_at() itself, reached at a normal time)
        combined with h0>0. The unstable first-draft formula computed
        exp(|mu|*A) directly for this shape of input, which either
        overflowed to a silent `inf` (no exception -- math.log(inf) is
        also silent) or, for slightly smaller magnitudes, stayed just
        under Python's float overflow threshold and produced a materially
        wrong (but finite-looking) answer. The fix must recover the
        correct, finite time -- not report UNREACHABLE for a target that
        genuinely is reached."""
        params = BaranyiParams(
            initial_log_cfu=-2.487148349097328,
            y_max_ln=-999.0,  # far below y0 -- not the limiting factor here
            mu_max_ln=-150.07746958030003,
            is_growth=False,
            h0=6.573615217650514,
        )
        t_true_hours = 4.9159486752995845
        y_end = population_at(params, duration_minutes=t_true_hours * 60)
        target = y_end - params.initial_log_cfu

        result = time_to_target(params, target_log_increase=target)

        assert result.outcome == BaranyiOutcome.REACHED
        assert result.hours is not None and math.isfinite(result.hours)
        assert result.hours == pytest.approx(t_true_hours, rel=1e-6)

    def test_absurd_but_finite_target_is_reached_not_a_crash(self):
        """A target far beyond any realistic food-safety scenario (a
        1300-year inactivation time) is still a legitimate, finite answer
        under the stabilised formula -- the fix is more robust than merely
        "doesn't crash for realistic inputs," it computes correctly across
        many orders of magnitude before hitting float64's actual limits
        (see the next test)."""
        params = BaranyiParams(
            initial_log_cfu=0.0,
            y_max_ln=-9999.0,
            mu_max_ln=-0.001,
            is_growth=False,
            h0=5.0,
        )
        result = time_to_target(params, target_log_increase=-5000.0)
        assert result.outcome == BaranyiOutcome.REACHED
        assert result.hours is not None and math.isfinite(result.hours)
        assert result.hours == pytest.approx(11517925.46497023, rel=1e-6)

    def test_target_at_float64_limits_is_unreachable_not_a_crash(self):
        """At the actual edge of float64 representability (target_ln
        approaching ~1.8e308), the closed form itself can no longer
        represent a finite intermediate value -- must report UNREACHABLE
        cleanly, never raise, even here."""
        params = BaranyiParams(
            initial_log_cfu=0.0,
            y_max_ln=-1e10,
            mu_max_ln=-1e-8,
            is_growth=False,
            h0=5.0,
        )
        result = time_to_target(params, target_log_increase=-1e300)
        assert result.outcome == BaranyiOutcome.UNREACHABLE
        assert result.hours is None


class TestLargeH0CrashGuard:
    """
    Regression tests for numerical-stability findings from a second code-
    review pass and two independent rounds of follow-up fuzzing (mine,
    then a third review pass's own), each finding cases the previous
    round's fuzzing missed (specs/lessons.md, 2026-08-22). Three distinct
    crash walls, all in inputs no longer contrived once h0 (an observed
    lag duration) or the asymptote gap is allowed to sit at a float64
    extreme:

    1. h0 >= ~37.5h: the h0>0 time-inversion step's `expm1(-h0)` term
       combined with catastrophic cancellation against `exp(-mu*A)` could
       raise ValueError ("math domain error") for a-star near zero.
    2. A target far beyond reach relative to a tight asymptote-correction
       band (small `cm`, i.e. y_max close to y0) could overflow
       `math.exp()` directly in the growth branch's `w` computation --
       found by fuzzing wider than the reviewer's reported case, entirely
       independent of h0.
    3. y_max_ln within about a ULP of y0_ln at the subnormal-float extreme
       makes `cm` underflow to exactly 0.0, raising ZeroDivisionError one
       arithmetic step before guard #2 above -- found by a third code-
       review pass's own fuzzing, not caught by any sweep in this file.

    All three are now guarded to report UNREACHABLE (a true fact: none of
    these inputs describe a target reachable within float64's
    representable range) rather than crashing. The softer h0 approximately
    15-37 "reduced precision" band mentioned in the second review is NOT
    claimed fixed here -- investigation showed it is a pre-existing
    float64 precision floor shared identically with population_at() (the
    already frontend-verified forward path), not a defect unique to or
    newly introduced by the inverse, and this was independently
    reconfirmed by the third review pass. See specs/lessons.md for the
    full derivation of why no reformulation of the inverse's algebra can
    recover precision the forward computation itself cannot represent.
    """

    def test_large_h0_lag_crash_is_now_a_clean_unreachable(self):
        """Exact reproduction of the code-review finding: h0=40h (over a
        37.5h threshold where expm1(-h0) underflows to -1.0 exactly)
        combined with a near-zero target used to previously raise
        ValueError from math.log(). Must return a clean UNREACHABLE."""
        params = BaranyiParams(
            initial_log_cfu=0.0,
            y_max_ln=5000.0,
            mu_max_ln=1.0,
            is_growth=True,
            h0=40.0,
        )
        result = time_to_target(params, target_log_increase=1e-16)
        assert result.outcome == BaranyiOutcome.UNREACHABLE
        assert result.hours is None

    @pytest.mark.parametrize("h0", [37.5, 37.6, 50.0, 100.0, 300.0])
    def test_h0_at_and_beyond_threshold_never_crashes(self, h0):
        """Sweep past the exact expm1 underflow boundary (37.5) -- every
        value must return a clean outcome, never raise."""
        params = BaranyiParams(
            initial_log_cfu=0.0,
            y_max_ln=5000.0,
            mu_max_ln=1.0,
            is_growth=True,
            h0=h0,
        )
        result = time_to_target(params, target_log_increase=0.5)
        assert result.outcome in (BaranyiOutcome.REACHED, BaranyiOutcome.UNREACHABLE)

    def test_tight_asymptote_band_overflow_is_now_a_clean_unreachable(self):
        """Exact reproduction of the w-overflow crash found by fuzzing
        beyond the reviewer's own cases: a target far beyond reach
        relative to a narrow y_max-close-to-y0 asymptote-correction band
        used to raise OverflowError directly from math.exp() before the
        denom<=0 'past the asymptote' check ever ran. Must return a clean
        UNREACHABLE (this target genuinely is unreachable -- it is far
        past y_max)."""
        params = BaranyiParams(
            initial_log_cfu=-2.2487562456428956,
            y_max_ln=-3.858675823327378,
            mu_max_ln=1.6902573859262562,
            is_growth=True,
            h0=35.25683301580705,
        )
        result = time_to_target(params, target_log_increase=47.928458961371945)
        assert result.outcome == BaranyiOutcome.UNREACHABLE
        assert result.hours is None

    def test_subnormal_asymptote_gap_is_now_a_clean_unreachable(self):
        """Exact reproduction of a fifth crash found by an independent
        code-review pass's own fuzzing (not caught by any fuzz sweep in
        this file, including the wide one below): y_max_ln within about a
        ULP of y0_ln at the subnormal-float extreme makes `cm` underflow
        to exactly 0.0, and the following division by cm raised
        ZeroDivisionError. An asymptote gap this tight (~1e-323) has no
        physical meaning and, for float64's purposes, leaves the curve no
        room to grow -- must return a clean UNREACHABLE, never crash."""
        params = BaranyiParams(
            initial_log_cfu=0.0,
            y_max_ln=1e-323,
            mu_max_ln=1.0,
            is_growth=True,
            h0=0.0,
        )
        result = time_to_target(params, target_log_increase=0.001)
        assert result.outcome == BaranyiOutcome.UNREACHABLE
        assert result.hours is None

    def test_fuzz_wide_parameter_sweep_never_crashes(self):
        """Broad randomized sweep (h0 up to 300h, |mu| up to 8, targets up
        to +-80 log10, asymptote bands from near-zero to wide) as a
        standing regression net for both crash walls above and any
        similar-shaped failure mode -- every combination must return a
        clean outcome, and every REACHED result must be a finite,
        non-negative time. Fixed seed for reproducibility."""
        import random

        rng = random.Random(20260822)
        for _ in range(5000):
            h0 = rng.uniform(0, 300)
            mu = rng.uniform(-8, 8) or 0.001
            is_growth = rng.random() < 0.5
            target = rng.uniform(-80, 80)
            y0 = rng.uniform(-20, 20)
            y_max_ln = y0 * _LN10 + rng.uniform(0.001, 80)
            params = BaranyiParams(
                initial_log_cfu=y0,
                y_max_ln=y_max_ln,
                mu_max_ln=mu,
                is_growth=is_growth,
                h0=h0,
            )
            result = time_to_target(params, target_log_increase=target)
            assert result.outcome in (
                BaranyiOutcome.REACHED,
                BaranyiOutcome.UNREACHABLE,
                BaranyiOutcome.ALREADY_MET,
            )
            if result.outcome == BaranyiOutcome.REACHED:
                assert result.hours is not None
                assert math.isfinite(result.hours)
                assert result.hours >= 0
