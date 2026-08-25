"""
Baranyi-Roberts primary growth model: forward trajectory and its inverse.

Additive capability. Does not touch, call, or get called by anything in
predictive/engines/combase/ — PTM's existing log-linear forward path
(ComBaseCalculator.calculate_log_increase) is completely untouched by
this module's existence. The two are independent ways of turning a rate
into a population change; nothing here changes what the other computes.

Ported from the frontend's validated TypeScript implementation
(src/features/translation/utils/baranyi.ts, per specs/ptm_baranyi_spec_v1.2.md
§4), which is itself a documented-fix port of ComBase's legacy cbMath.js
`dmy` (lines 247-307). `_dmy_ln` below is a line-for-line port of that
file's `dmyLn` export, preserving its exact branches and constants
(including the two documented legacy-bug fixes: t<0 and h0<0 both return
y0Ln unchanged, not 0) so it can be audited against the TypeScript
source directly. `population_at` and `time_to_target` are the public,
explicitly-based wrappers described below.

===========================================================================
THE MIXED-BASIS UNITS CONTRACT -- read this before touching any of the math
===========================================================================

Every quantity below sits in log10, ln, or a raw unit, PER FIELD -- there
is no single "convert everything" rule, and treating two adjacent
population fields as if they shared a basis is the single highest-risk
mistake in this module (a factor of ln(10) ~= 2.3026 error, silent unless
checked against a known example).

| Field                       | Basis as received      | What this module does with it            |
|------------------------------|------------------------|-------------------------------------------|
| `initial_log_cfu`            | log10(CFU/g)            | x ln(10) -> ln, internally                |
| `target_log_increase`(inverse)| log10(CFU/g)           | x ln(10) -> ln, internally                |
| `y_max_ln`                   | ALREADY ln(CFU/g)       | passed through -- NEVER x ln(10)          |
| `mu_max_ln`                  | ALREADY ln, per hour    | passed through -- NEVER x ln(10)          |
| `h0`                         | dimensionless (mu.lambda)| passed through -- no conversion either way|
| `duration_minutes`           | minutes                 | / 60 -> hours, internally                 |
| curve output (internal)      | ln                      | / ln(10) -> log10 on the way out          |

`y_max_ln` and `mu_max_ln` are named with an explicit `_ln` suffix so the
basis is visible at every call site, not just in a docstring a caller can
skip. `initial_log_cfu` and `target_log_increase` are named to match the
log10 fields they mirror elsewhere in this codebase
(`ComBaseExecutionResult.initial_log_cfu`). There is no generic "pass a
list of log values" entry point anywhere in this module -- every function
takes these five named fields individually, so a uniform per-category
conversion is not a thing there is room to write by accident.

Where `mu_max_ln` comes from is the caller's decision, not this module's:
if it is derived from an already-capped `total_log_increase`
(`log_increase * ln(10) / duration_hours`) rather than read from the raw
polynomial `mu_max` field, the physical-plausibility cap from
`ComBaseEngine.execute()` is respected; if the raw field is used instead,
it is not. This module is agnostic to that choice -- it takes whatever
`mu_max_ln` value it is given as the rate to use, exactly as received.

===========================================================================
h0 IS A PARAMETER, NEVER READ FROM THE CSV
===========================================================================

`h0` defaults to 0.0 (no lag -- the conservative floor: assume the
organism is ready to grow/inactivate immediately). It must never be
populated from `ComBaseModel.h0` (the CSV-fitted value). That figure is
fitted from the training culture's own history in the ComBase experiment
that produced the row -- it reflects how long *that* culture took to
adapt, not the user's product, which may have a different (or zero)
adaptation history. Crediting the user's scenario with the training
culture's lag time would silently assume away real risk. Callers that
want a swept range of lag scenarios pass their own h0 values explicitly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

_BIGEXP = 30.0
_UP_BREAK = 20.0
_LN10 = math.log(10)

# Near-singularity guard for time_to_target()'s asymptote-corrected branch.
# As the target approaches y_max_ln, the reachable/unreachable boundary is
# t -> infinity (the curve approaches but never crosses the asymptote in
# finite time) -- a target within _NEAR_ASYMPTOTE_EPS of that boundary is
# treated as UNREACHABLE rather than solved for, because (a) the "true"
# t* there is astronomically large and not a useful answer, and (b) right
# at that boundary a single quantity (1 - w*f_const, computed once and
# reused -- see time_to_target) can be driven negative by ordinary float64
# rounding even when the target is nominally still inside y_max. 1e-9 is
# far above float64 rounding noise (~1e-15 relative) but still represents
# "at the boundary," not a normal separated case.
_NEAR_ASYMPTOTE_EPS = 1e-9


def _dmy_ln(
    mu_ln: float,
    h0: float,
    y0_ln: float,
    y_end_ln: float,
    n_curv: float,
    m_curv: float,
    t: float,
) -> float:
    """
    Baranyi-Roberts closed-form solution, ln-basis throughout.

    Line-for-line port of the TypeScript `dmyLn` (itself a documented-fix
    port of ComBase's legacy cbMath.js `dmy`). All arguments and the
    return value are in ln -- this is the internal engine; population_at()
    and time_to_target() are the log10-in/log10-out public surface.

    Not exported. Kept private so the only way to call into this math is
    through the explicitly-based public functions below.
    """
    if (y_end_ln - y0_ln) * mu_ln <= 0:
        return y0_ln
    if h0 < 0 or t < 0:
        return y0_ln

    if h0 == 0:
        a_t = t
    else:
        lag = h0 / (abs(mu_ln) * n_curv)
        tpl = t / lag
        exponent = -h0 * tpl + h0
        if exponent > _BIGEXP:
            a_t = 0.0
        else:
            a_t = (
                t
                - lag
                + (lag / h0) * math.log(1 - math.exp(-h0 * tpl) + math.exp(exponent))
            )

    y_no_end = y0_ln + mu_ln * a_t
    if m_curv == 0:
        return y_no_end
    if m_curv >= _UP_BREAK:
        return min(y_no_end, y_end_ln) if mu_ln > 0 else max(y_no_end, y_end_ln)

    cm = (y_end_ln - y0_ln) / m_curv
    mupcm = (m_curv * mu_ln) / (y_end_ln - y0_ln)
    overflow_arg = -m_curv + mupcm * a_t
    if overflow_arg > _BIGEXP:
        return y_end_ln

    m_t = math.exp(overflow_arg)
    e_t = 1 - math.exp(-m_curv) + m_t
    return y0_ln + mu_ln * a_t - cm * math.log(e_t)


@dataclass(frozen=True)
class BaranyiParams:
    """
    A Baranyi scenario. See the module docstring's units table -- every
    field's basis is fixed by its name/description, not by convention.

    Cheap to construct repeatedly (a plain frozen dataclass, no I/O, no
    validation beyond the one h0 guard below) -- sweeping many initial
    counts and h0 values means constructing many of these, which costs
    nothing beyond the dataclass allocation itself.
    """

    initial_log_cfu: float  # y0, log10(CFU/g)
    y_max_ln: float  # asymptote, ALREADY ln(CFU/g) -- do not x ln(10)
    mu_max_ln: float  # rate, ALREADY ln per hour -- do not x ln(10)
    is_growth: bool  # True -> asymptote correction applies; False -> none
    h0: float = 0.0  # dimensionless; NEVER the CSV-fitted value (see module docstring)

    def __post_init__(self) -> None:
        if self.h0 < 0:
            raise ValueError(f"h0 must be >= 0, got {self.h0}")


def population_at(params: BaranyiParams, duration_minutes: float) -> float:
    """
    Population at a given time, log10(CFU/g).

    Args:
        params: the scenario (see BaranyiParams).
        duration_minutes: time since t=0, in minutes (per the units table:
            converted to hours internally).

    Returns:
        log10(CFU/g) at that time.
    """
    y0_ln = params.initial_log_cfu * _LN10
    t_hours = duration_minutes / 60.0
    m_curv = 10.0 if params.is_growth else 0.0
    y_ln = _dmy_ln(
        params.mu_max_ln, params.h0, y0_ln, params.y_max_ln, 1.0, m_curv, t_hours
    )
    return y_ln / _LN10


class BaranyiOutcome(StrEnum):
    """
    Three honest outcomes for time_to_target() -- each a real, meaningful
    result, not an error. See time_to_target()'s docstring for what each
    one means and when it fires.
    """

    REACHED = "reached"
    UNREACHABLE = "unreachable"
    ALREADY_MET = "already_met"


@dataclass(frozen=True)
class BaranyiInverseResult:
    """
    Result of time_to_target().

    hours is populated for REACHED (the computed time) and ALREADY_MET
    (always 0.0); it is None for UNREACHABLE, since there is no time at
    which the target is reached under these conditions.
    """

    outcome: BaranyiOutcome
    hours: float | None


def time_to_target(
    params: BaranyiParams, target_log_increase: float
) -> BaranyiInverseResult:
    """
    Time to reach a target log10 change from the scenario's initial count.

    Analytic inverse -- no numerical root-finding anywhere in this
    function (see the derivation in specs/lessons.md and the module's
    accompanying recon report). Cheap to call repeatedly for the same
    reason population_at() is: closed-form arithmetic, no iteration.

    Args:
        params: the scenario (see BaranyiParams). target_log_increase's
            sign is relative to params.mu_max_ln's direction -- for a
            growth scenario (mu_max_ln > 0) this is normally positive
            ("+N log"); for an inactivation/survival scenario
            (mu_max_ln < 0) a negative value asks "when has it dropped by
            N log" -- the function is symmetric in direction, it does not
            assume growth.

    Returns:
        BaranyiInverseResult with exactly one of:
        - REACHED: hours is the (non-negative) time at which the curve
          first reaches the target.
        - ALREADY_MET: the target is at or past the starting population,
          in the direction the curve is already moving -- hours=0.0.
          E.g. asking for a non-positive increase while growing, or a
          non-negative increase while declining.
        - UNREACHABLE: the target lies on the far side of the model's
          asymptote (y_max) from the starting population, or the curve is
          flat (mu_max_ln == 0, or the model/asymptote configuration is
          internally inconsistent -- mirrors _dmy_ln's own degenerate
          guard). This is a fact about the model and the target, not a
          solver failure -- the food genuinely never reaches that level
          under these conditions.
    """
    y0_ln = params.initial_log_cfu * _LN10
    target_ln = target_log_increase * _LN10
    target_y_ln = y0_ln + target_ln
    mu_ln = params.mu_max_ln

    # Already met: the curve starts at y0 and moves monotonically in the
    # direction mu_ln points, so "target at or behind the starting point,
    # in that direction" is trivially satisfied at t=0.
    already_met = (mu_ln >= 0 and target_ln <= 0) or (mu_ln < 0 and target_ln >= 0)
    if already_met:
        return BaranyiInverseResult(BaranyiOutcome.ALREADY_MET, 0.0)

    # Degenerate: curve is flat for all t (mirrors _dmy_ln's own first
    # guard -- (y_end_ln - y0_ln) * mu_ln <= 0, e.g. mu_ln == 0, or an
    # asymptote/rate pairing that doesn't make sense together).
    if (params.y_max_ln - y0_ln) * mu_ln <= 0:
        return BaranyiInverseResult(BaranyiOutcome.UNREACHABLE, None)

    if not params.is_growth:
        # m_curv == 0: no asymptote correction, y = y0_ln + mu_ln * A(t).
        a_star = target_ln / mu_ln
        if a_star < 0:
            return BaranyiInverseResult(BaranyiOutcome.UNREACHABLE, None)
    else:
        # m_curv == 10: solve the asymptote-corrected form for A(t) given
        # the target population, in closed form.
        #
        # y = y0_ln + mu_ln*A - cm*ln(Et),  cm = (y_end_ln - y0_ln) / m_curv
        # Et = 1 - exp(-m_curv) + exp(-m_curv + (mu_ln/cm)*A)
        #
        # Substituting z = exp((mu_ln/cm)*A) turns this into a single
        # linear equation in z (derivation in specs/lessons.md):
        #   z = W*G / (1 - W*F),  W = exp((target_y_ln - y0_ln)/cm),
        #   F = exp(-m_curv), G = 1-F
        # then A = cm*ln(z)/mu_ln.
        m_curv = 10.0
        cm = (params.y_max_ln - y0_ln) / m_curv

        # cm can underflow to exactly 0.0 when y_max_ln is within about a
        # ULP of y0_ln at the subnormal-float extreme (an astronomically
        # tight, not physically meaningful, asymptote gap) -- the earlier
        # (y_max_ln-y0_ln)*mu_ln<=0 guard only checks a *sign*, so a
        # nonzero-but-about-to-underflow difference passes it and then
        # divides by zero one line below. A gap that tight means the
        # curve has, for float64's purposes, no room to grow at all --
        # the same "no measurable signal left" conclusion as the h0
        # precision floor discussed above, so UNREACHABLE is the honest
        # answer, not a crash. Found by code review -- see specs/lessons.md.
        if cm == 0.0:
            return BaranyiInverseResult(BaranyiOutcome.UNREACHABLE, None)

        exponent = (target_y_ln - y0_ln) / cm  # = ln(w); always >= 0 here,
        # since the already_met and (y_max-y0)*mu<=0 guards above force
        # target_y_ln and cm to share sign relative to y0_ln.
        shifted = exponent - m_curv  # = ln(w * f_const)

        # w*f_const (equivalently exp(shifted)) can be astronomically large
        # for a target far beyond reach relative to how tight the asymptote
        # correction is (small cm, e.g. y_max close to y0) -- direct
        # math.exp(exponent) can raise OverflowError before the denom<=0
        # "past the asymptote" check below ever runs. shifted>=0 is exactly
        # that condition (w*f_const>=1 <=> denom<=0), decided from the
        # exponent's arithmetic without exponentiating it -- and once
        # shifted<0, exponent=shifted+m_curv is bounded above by m_curv
        # (10), so the exp() calls below cannot overflow. Found by fuzzing
        # beyond the code review's own cases -- see specs/lessons.md.
        if shifted >= 0:
            return BaranyiInverseResult(BaranyiOutcome.UNREACHABLE, None)

        f_const = math.exp(-m_curv)
        g_const = 1 - f_const
        w = math.exp(exponent)
        denom = 1 - w * f_const

        # Reachability, derived from the SAME quantity (denom) the z
        # computation below uses -- not a separately-rounded expression.
        # denom -> 0+ is the t -> infinity boundary (the curve approaches
        # y_max_ln but never crosses it in finite time); denom <= 0 means
        # past it. Checking a single shared quantity against an epsilon,
        # rather than recomputing "distance from y_max_ln" a second way,
        # avoids two independently-rounded views of the same near-
        # singularity disagreeing at the boundary (this was a real bug,
        # caught by code review -- see specs/lessons.md).
        if denom <= _NEAR_ASYMPTOTE_EPS:
            return BaranyiInverseResult(BaranyiOutcome.UNREACHABLE, None)

        z = w * g_const / denom
        a_star = cm * math.log(z) / mu_ln
        if a_star < 0:
            return BaranyiInverseResult(BaranyiOutcome.UNREACHABLE, None)

    # Invert A(t) -> t. Closed form (derivation in specs/lessons.md):
    # A(t) = t - lag + (1/|mu|)*ln(1 + exp(-|mu|*t)*(exp(h0)-1)), lag=h0/|mu|
    # =>  t = (1/|mu|) * ln( exp(h0)*(exp(|mu|*A) - 1) + 1 )     [h0 != 0]
    #
    # Computed via the log-sum-exp form rather than directly, mirroring how
    # _dmy_ln itself avoids exp() of a large positive argument: let
    # x = h0 + |mu|*A (the dominant term). Then
    #   exp(h0)*(exp(|mu|*A)-1) + 1 = exp(x) - exp(h0) + 1
    #                                = exp(x) * (1 - exp(h0-x) + exp(-x))
    #   ln(...) = x + log1p(exp(-x) - exp(h0-x))
    #           = x + log1p(exp(-|mu|*A) * expm1(-h0))     [factored below]
    # exp(-x) and exp(h0-x) are both exp() of a NEGATIVE argument for any
    # A >= 0 -- they safely underflow to 0.0 for large x rather than
    # overflowing, so this form has no failure mode direct exponentiation
    # of |mu|*A has for realistic-but-large (A, mu) combinations (a fast
    # rate over a long-but-real duration -- not a contrived input; this is
    # exactly what a thermal-inactivation scenario with a large log
    # reduction target produces). A HIGH-severity gap in the first version
    # of this function: it returned a silent `inf`/crashed for exactly
    # this shape of input, caught by code review (specs/lessons.md).
    if params.h0 == 0:
        t_star = a_star
    else:
        mu_abs = abs(mu_ln)
        x = params.h0 + mu_abs * a_star
        # term_a - term_b = exp(-x) - exp(h0-x) = exp(-mu_abs*a_star) *
        # expm1(-h0) -- computed as one expm1() call rather than the
        # subtraction of two independently-rounded exp() results, since
        # expm1() is the numerically stable primitive for exactly this
        # "exp(y)-1" pattern. For a_star very close to 0 combined with a
        # large h0 (a long lag phase observed only briefly), this
        # subtraction is still fundamentally ill-conditioned -- and not
        # only inside this function: population_at() itself returns
        # exactly y0 (no measurable growth at all) for the same
        # (a_star-implying) durations once the lag genuinely dwarfs the
        # observation window, confirmed directly against the forward path.
        # That is a real float64 precision floor shared with the
        # (separately verified) forward computation, not a defect unique
        # to the inverse -- not claimed fixed here, only guarded so it
        # reports UNREACHABLE rather than crashing when representability
        # is genuinely exhausted (see specs/lessons.md, 2026-08-22).
        term_diff = math.exp(-mu_abs * a_star) * math.expm1(-params.h0)
        if term_diff <= -1.0:
            return BaranyiInverseResult(BaranyiOutcome.UNREACHABLE, None)
        ln_inner = x + math.log1p(term_diff)
        t_star = ln_inner / mu_abs

    if not math.isfinite(t_star) or t_star < 0:
        # Only reachable for a target so extreme (astronomically large
        # target_log_increase) that even this stabilised form can't
        # represent the answer -- honestly reported as unreachable rather
        # than as a crash or a silently wrong number.
        return BaranyiInverseResult(BaranyiOutcome.UNREACHABLE, None)

    return BaranyiInverseResult(BaranyiOutcome.REACHED, t_star)
