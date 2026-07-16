"""
Unit tests for Experiment 2.2 (Embedder x Doc Text Format).

Tests cover pure functions only — no ChromaDB, no SentenceTransformer:
  - _score_query_result  — reciprocal_rank computation (new in 2.2), negative-
                           control polarity, per-stratum field independence
  - _compute_cell_summary — per-stratum MRR, negative exclusion from denominator,
                            hard_fpr Type-1/Type-2 taxonomy
  - compute_recommendation — all five action values

Key invariant under test:
  Negative controls (is_negative=True) are excluded from the MRR denominator.
  reciprocal_rank=None for all negative controls.
  Per-stratum MRR uses the `tier` key, not `field`, so a stratum containing
  queries from multiple fields (ph, water_activity, ph_aw_combined) is still
  aggregated correctly.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.experiments.exp_2_2_embedder_doc_format import (
    _CATEGORY_LEVEL_FOOD_NAMES,
    FPR_CEILING,
    MRR_EASY_FLOOR,
    _compute_cell_summary,
    _recompute_query_at_threshold,
    _score_query_result,
    _threshold_sweep,
    compute_recommendation,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _hit(food_name: str, score: float, doc_id: str | None = None) -> dict:
    return {
        "food_name": food_name,
        "doc_id": doc_id or f"fp_{food_name.replace(' ', '_')}",
        "score": score,
    }


def _pos_entry(
    acceptable: list[str],
    tier: str = "easy",
    field: str = "ph_aw_combined",
    production_tier: str = "tier_1",
) -> dict:
    return {
        "id": f"{tier}_test",
        "food_description": acceptable[0] if acceptable else "unknown",
        "field": field,
        "production_tier": production_tier,
        "tier": tier,
        "acceptable_food_names": acceptable,
    }


def _neg_entry(
    tier: str = "hard",
    field: str = "ph",
    production_tier: str = "tier_2",
) -> dict:
    return {
        "id": f"{tier}_negative",
        "food_description": "generic food",
        "field": field,
        "production_tier": production_tier,
        "tier": tier,
        "acceptable_food_names": [],
    }


def _make_query_record(
    tier: str,
    production_tier: str,
    is_negative: bool,
    reciprocal_rank,  # float or None (gate-filtered)
    correct_at_1: bool,
    top1_food_name: str | None = None,
    expected_score: float | None = None,
    gate_passed: bool | None = None,
    field: str = "ph_aw_combined",
    expected_rank: (
        int | None
    ) = None,  # None → use default (1 for positive, None for negative)
) -> dict:
    exp_rank = (
        expected_rank if expected_rank is not None else (1 if not is_negative else None)
    )
    pure_rr = (
        (round(1.0 / exp_rank, 6) if exp_rank else 0.0) if not is_negative else None
    )
    return {
        "query_id": f"Q_{tier}",
        "field": field,
        "production_tier": production_tier,
        "tier": tier,
        "threshold_used": 0.70,
        "latency_ms": 10.0,
        "error": None,
        "top1_doc_id": "some_doc",
        "top1_food_name": top1_food_name,
        "top1_score": 0.75 if not is_negative else 0.50,
        "top3_food_names": [],
        "canonical_food_name": None,
        "acceptable_food_names": [],
        "is_negative": is_negative,
        "expected_rank": exp_rank,
        "expected_score": expected_score,
        "pure_reciprocal_rank": pure_rr,
        "reciprocal_rank": reciprocal_rank,
        "correct_at_1": correct_at_1,
        "gate_passed": gate_passed if gate_passed is not None else correct_at_1,
    }


# ---------------------------------------------------------------------------
# _score_query_result — reciprocal_rank (new in 2.2)
# ---------------------------------------------------------------------------


class TestScoreQueryResultReciprocalRank:

    def test_rank_1_gives_rr_1(self):
        top_k = [_hit("chicken", 0.85), _hit("other", 0.70)]
        entry = _pos_entry(["chicken"])
        r = _score_query_result(top_k, entry, threshold=0.70)
        assert r["reciprocal_rank"] == pytest.approx(1.0)

    def test_rank_2_gives_rr_half(self):
        top_k = [_hit("wrong", 0.90), _hit("chicken", 0.80)]
        entry = _pos_entry(["chicken"])
        r = _score_query_result(top_k, entry, threshold=0.70)
        assert r["reciprocal_rank"] == pytest.approx(0.5)

    def test_rank_3_gives_rr_third(self):
        top_k = [_hit("wrong1", 0.90), _hit("wrong2", 0.85), _hit("chicken", 0.80)]
        entry = _pos_entry(["chicken"])
        r = _score_query_result(top_k, entry, threshold=0.70)
        assert r["reciprocal_rank"] == pytest.approx(round(1.0 / 3, 6))

    def test_no_acceptable_above_threshold_gives_rr_zero(self):
        top_k = [_hit("chicken", 0.65), _hit("other", 0.60)]  # all below threshold
        entry = _pos_entry(["chicken"])
        r = _score_query_result(top_k, entry, threshold=0.70)
        assert r["reciprocal_rank"] == pytest.approx(0.0)

    def test_acceptable_below_threshold_does_not_count(self):
        # chicken appears at rank 1 but below threshold; should not count toward RR
        top_k = [_hit("chicken", 0.68), _hit("other", 0.85)]
        entry = _pos_entry(["chicken"])
        r = _score_query_result(top_k, entry, threshold=0.70)
        assert r["reciprocal_rank"] == pytest.approx(0.0)

    def test_multiple_acceptable_names(self):
        # Any of the acceptable names at rank 2 should give rr=0.5
        top_k = [
            _hit("turkey breast", 0.92),
            _hit("fresh poultry", 0.80),
            _hit("chicken", 0.75),
        ]
        entry = _pos_entry(["fresh poultry", "chicken"])
        r = _score_query_result(top_k, entry, threshold=0.70)
        assert r["reciprocal_rank"] == pytest.approx(0.5)

    def test_empty_top_k_gives_rr_zero(self):
        entry = _pos_entry(["chicken"])
        r = _score_query_result([], entry, threshold=0.70)
        assert r["reciprocal_rank"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _score_query_result — negative controls
# ---------------------------------------------------------------------------


class TestScoreQueryResultNegativeControl:

    def test_negative_control_reciprocal_rank_is_none(self):
        top_k = [_hit("beef ground", 0.80)]
        entry = _neg_entry()
        r = _score_query_result(top_k, entry, threshold=0.62)
        assert r["reciprocal_rank"] is None

    def test_negative_control_correct_when_no_doc_above_threshold(self):
        top_k = [_hit("beef ground", 0.55)]
        entry = _neg_entry()
        r = _score_query_result(top_k, entry, threshold=0.62)
        assert r["correct_at_1"] is True
        assert r["is_negative"] is True

    def test_negative_control_incorrect_when_doc_above_threshold(self):
        top_k = [_hit("beef ground", 0.70)]
        entry = _neg_entry()
        r = _score_query_result(top_k, entry, threshold=0.62)
        assert r["correct_at_1"] is False
        assert r["is_negative"] is True

    def test_negative_control_reciprocal_rank_none_even_on_false_positive(self):
        # Even when a doc wrongly clears the threshold, rr must be None for negative controls
        top_k = [_hit("fresh poultry", 0.75)]
        entry = _neg_entry()
        r = _score_query_result(top_k, entry, threshold=0.62)
        assert r["reciprocal_rank"] is None
        assert r["correct_at_1"] is False


# ---------------------------------------------------------------------------
# _compute_cell_summary — MRR, per-stratum, negative exclusion
# ---------------------------------------------------------------------------


class TestComputeCellSummaryMRR:

    def _build_results(self) -> list[dict]:
        """
        3 easy positive (RR 1.0, 0.5, 0.0), 2 medium positive (RR 1.0, 0.5),
        1 pathogen positive (RR 1.0), 2 hard negative (both pass = no FP).
        """
        return [
            _make_query_record("easy", "tier_1", False, 1.0, True, "chicken", 0.85),
            _make_query_record("easy", "tier_1", False, 0.5, False, "wrong", 0.85),
            _make_query_record("easy", "tier_1", False, 0.0, False, "wrong", 0.65),
            _make_query_record("medium", "tier_2", False, 1.0, True, "chicken", 0.80),
            _make_query_record("medium", "tier_2", False, 0.5, False, "wrong", 0.80),
            _make_query_record(
                "pathogen", "pathogen_stage_1", False, 1.0, True, "chicken", 0.90
            ),
            _make_query_record("hard", "tier_2", True, None, True, None, None),
            _make_query_record("hard", "tier_2", True, None, True, None, None),
        ]

    def test_pure_mrr_uses_expected_rank_not_threshold(self):
        # All 6 positive records have expected_rank=1 (default in _make_query_record),
        # so pure_reciprocal_rank=1.0 for all — mrr must be 1.0 regardless of reciprocal_rank.
        results = self._build_results()
        s = _compute_cell_summary(results)
        assert s["mrr"] == pytest.approx(1.0)

    def test_gate_filtered_mrr_excludes_negative_controls(self):
        results = self._build_results()
        s = _compute_cell_summary(results)
        # Gate-filtered RR values: 1.0, 0.5, 0.0, 1.0, 0.5, 1.0 → mean = 4.0/6 ≈ 0.6667
        assert s["mrr_gate_filtered"] == pytest.approx(round(4.0 / 6, 4))

    def test_positive_query_count_excludes_hard(self):
        results = self._build_results()
        s = _compute_cell_summary(results)
        assert s["n_positive_queries"] == 6
        assert s["n_hard_queries"] == 2

    def test_gate_filtered_mrr_easy_stratum(self):
        results = self._build_results()
        s = _compute_cell_summary(results)
        # easy gate-filtered RRs: 1.0, 0.5, 0.0 → mean = 0.5
        assert s["mrr_gate_filtered_by_stratum"]["easy"] == pytest.approx(0.5)

    def test_gate_filtered_mrr_medium_stratum(self):
        results = self._build_results()
        s = _compute_cell_summary(results)
        # medium gate-filtered RRs: 1.0, 0.5 → mean = 0.75
        assert s["mrr_gate_filtered_by_stratum"]["medium"] == pytest.approx(0.75)

    def test_gate_filtered_mrr_pathogen_stratum(self):
        results = self._build_results()
        s = _compute_cell_summary(results)
        assert s["mrr_gate_filtered_by_stratum"]["pathogen"] == pytest.approx(1.0)

    def test_hard_stratum_not_in_mrr_by_stratum(self):
        results = self._build_results()
        s = _compute_cell_summary(results)
        assert "hard" not in s["mrr_by_stratum"]
        assert "hard" not in s["mrr_gate_filtered_by_stratum"]

    def test_pure_mrr_invariant_to_threshold(self):
        # When canonical doc is at rank 1 but below threshold, pure mrr=1.0 but gate_filtered=0.0.
        # This is the key invariant: a threshold change must not move mrr.
        results = [
            _make_query_record("easy", "tier_1", False, 0.0, False, "wrong", 0.60),
            _make_query_record("easy", "tier_1", False, 0.0, False, "wrong", 0.60),
        ]
        # expected_rank=1 (default), so pure_reciprocal_rank=1.0 for both
        # reciprocal_rank=0.0 (canonical below threshold at rank 1)
        s = _compute_cell_summary(results)
        assert s["mrr"] == pytest.approx(1.0)
        assert s["mrr_gate_filtered"] == pytest.approx(0.0)

    def test_hard_fpr_zero_when_all_pass(self):
        results = self._build_results()
        s = _compute_cell_summary(results)
        assert s["hard_fpr"] == pytest.approx(0.0)


class TestComputeCellSummaryMixedFieldStrata:
    """
    Per-stratum MRR uses the `tier` key, NOT `field`.
    A medium stratum with ph + water_activity + ph_aw_combined queries
    must aggregate all three into one mrr_medium figure.
    """

    def test_medium_stratum_mixes_ph_and_aw_queries(self):
        results = [
            _make_query_record(
                "medium", "tier_2", False, 1.0, True, "chicken", 0.80, field="ph"
            ),
            _make_query_record(
                "medium",
                "tier_2",
                False,
                0.5,
                False,
                "wrong",
                0.80,
                field="water_activity",
            ),
            _make_query_record(
                "medium",
                "tier_2",
                False,
                0.0,
                False,
                "wrong",
                0.65,
                field="ph_aw_combined",
            ),
        ]
        s = _compute_cell_summary(results)
        # Gate-filtered RRs: 1.0, 0.5, 0.0 → mean = 0.5
        assert s["mrr_gate_filtered_by_stratum"]["medium"] == pytest.approx(
            round((1.0 + 0.5 + 0.0) / 3, 4)
        )

    def test_easy_stratum_mixes_fields(self):
        results = [
            _make_query_record(
                "easy", "tier_1", False, 1.0, True, "chicken", 0.85, field="ph"
            ),
            _make_query_record(
                "easy", "tier_1", False, 1.0, True, "beef", 0.85, field="water_activity"
            ),
        ]
        s = _compute_cell_summary(results)
        assert s["mrr_gate_filtered_by_stratum"]["easy"] == pytest.approx(1.0)

    def test_stratum_with_only_rr_zero_gives_gate_filtered_mrr_zero(self):
        results = [
            _make_query_record(
                "medium", "tier_2", False, 0.0, False, "wrong", 0.65, field="ph"
            ),
            _make_query_record(
                "medium", "tier_2", False, 0.0, False, "wrong", 0.60, field="ph"
            ),
        ]
        s = _compute_cell_summary(results)
        assert s["mrr_gate_filtered_by_stratum"]["medium"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _compute_cell_summary — hard FPR Type-1 / Type-2 taxonomy
# ---------------------------------------------------------------------------


class TestHardFPRTaxonomy:
    """
    Type-1: FP whose top1_food_name is NOT in _CATEGORY_LEVEL_FOOD_NAMES
            (class-noun grounding a specific-row value — unambiguously wrong).
    Type-2: FP whose top1_food_name IS in _CATEGORY_LEVEL_FOOD_NAMES
            (class-noun grounding a category-level row — contestable).
    """

    def _build_hard_results(
        self,
        n_pass: int = 0,
        type1_fp_food_names: list[str] | None = None,
        type2_fp_food_names: list[str] | None = None,
    ) -> list[dict]:
        records = []
        for _ in range(n_pass):
            records.append(
                _make_query_record("hard", "tier_2", True, None, True, None, None)
            )
        for food in type1_fp_food_names or []:
            # FP: correct_at_1=False, top1_food_name is a specific-row value
            records.append(
                _make_query_record("hard", "tier_2", True, None, False, food, None)
            )
        for food in type2_fp_food_names or []:
            # FP: correct_at_1=False, top1_food_name is a category-level value
            records.append(
                _make_query_record("hard", "tier_2", True, None, False, food, None)
            )
        return records

    def test_type1_fp_counted_correctly(self):
        results = self._build_hard_results(
            n_pass=2,
            type1_fp_food_names=["beef ground"],
        )
        s = _compute_cell_summary(results)
        # round(1/3, 4) = 0.3333; use abs tolerance to stay within 4dp rounding
        assert s["hard_fpr"] == pytest.approx(1 / 3, abs=1e-3)
        assert s["hard_fpr_type1"] == pytest.approx(1 / 3, abs=1e-3)
        assert s["hard_fpr_type2"] == pytest.approx(0.0)

    def test_type2_fp_counted_correctly(self):
        results = self._build_hard_results(
            n_pass=2,
            type2_fp_food_names=["fresh poultry"],
        )
        s = _compute_cell_summary(results)
        assert s["hard_fpr"] == pytest.approx(1 / 3, abs=1e-3)
        assert s["hard_fpr_type1"] == pytest.approx(0.0)
        assert s["hard_fpr_type2"] == pytest.approx(1 / 3, abs=1e-3)

    def test_mixed_type1_and_type2(self):
        # 4 hard queries: 2 pass, 1 Type-1 FP (beef ground), 1 Type-2 FP (fresh meat)
        results = self._build_hard_results(
            n_pass=2,
            type1_fp_food_names=["beef ground"],
            type2_fp_food_names=["fresh meat"],
        )
        s = _compute_cell_summary(results)
        assert s["hard_fpr"] == pytest.approx(0.5)
        assert s["hard_fpr_type1"] == pytest.approx(0.25)
        assert s["hard_fpr_type2"] == pytest.approx(0.25)

    def test_all_pass_gives_zero_fpr(self):
        results = self._build_hard_results(n_pass=6)
        s = _compute_cell_summary(results)
        assert s["hard_fpr"] == pytest.approx(0.0)
        assert s["hard_fpr_type1"] == pytest.approx(0.0)
        assert s["hard_fpr_type2"] == pytest.approx(0.0)

    def test_category_level_food_names_set_contains_expected_entries(self):
        assert "fresh poultry" in _CATEGORY_LEVEL_FOOD_NAMES
        assert "fresh meat" in _CATEGORY_LEVEL_FOOD_NAMES
        assert "cured meat" in _CATEGORY_LEVEL_FOOD_NAMES
        assert "fish fresh most" in _CATEGORY_LEVEL_FOOD_NAMES
        assert "eggs" in _CATEGORY_LEVEL_FOOD_NAMES
        assert "beef ground" not in _CATEGORY_LEVEL_FOOD_NAMES
        assert "chicken" not in _CATEGORY_LEVEL_FOOD_NAMES


# ---------------------------------------------------------------------------
# _compute_cell_summary — edge cases
# ---------------------------------------------------------------------------


class TestComputeCellSummaryEdgeCases:

    def test_empty_query_results_returns_empty_dict(self):
        assert _compute_cell_summary([]) == {}

    def test_all_errored_returns_empty_dict(self):
        records = [
            {
                **_make_query_record("easy", "tier_1", False, None, None),
                "error": "ChromaDB timeout",
            },
        ]
        assert _compute_cell_summary(records) == {}

    def test_no_hard_queries_gives_zero_hard_fpr(self):
        results = [
            _make_query_record("easy", "tier_1", False, 1.0, True, "chicken", 0.85),
        ]
        s = _compute_cell_summary(results)
        assert s["hard_fpr"] == pytest.approx(0.0)
        assert s["n_hard_queries"] == 0

    def test_only_negative_controls_gives_none_mrr(self):
        results = [
            _make_query_record("hard", "tier_2", True, None, True, None, None),
            _make_query_record("hard", "tier_2", True, None, True, None, None),
        ]
        s = _compute_cell_summary(results)
        assert s["mrr"] is None
        assert s["mrr_gate_filtered"] is None


# ---------------------------------------------------------------------------
# compute_recommendation — viability-based decision rule
# ---------------------------------------------------------------------------


def _make_cell(
    embedder_id: str,
    format_id: str,
    mrr: float | None,
    viable: bool = False,
    mrr_easy: float = 0.0,
    n_errored: int = 0,
    params_m: int = 22,
    latency_ms: float = 20.0,
    is_baseline: bool = False,
) -> dict:
    # Convert bool to tri-state string so tests don't need to know the internal representation.
    vat = "true" if viable else "false"
    return {
        "cell_id": f"{embedder_id}_{format_id}",
        "embedder_id": embedder_id,
        "embedder_name": embedder_id,
        "embedder_hf_model": f"sentence-transformers/{embedder_id}",
        "embedder_dim": 384,
        "embedder_params_m": params_m,
        "embedder_is_baseline": is_baseline,
        "embedder_training_objective": "general",
        "format_id": format_id,
        "load_time_s": 1.0,
        "embed_time_s": 0.5,
        "queries": [],
        "summary": {
            "mrr": mrr,
            "mrr_by_stratum": {"easy": mrr_easy},
            "viable_at_calibrated_threshold": vat,
            "n_errored_queries": n_errored,
            "mean_query_latency_ms": latency_ms,
            "hard_fpr": 0.0 if viable else 0.083,
        },
    }


class TestComputeRecommendation:

    BASELINE_EMBEDDER = "minilm-l6-v2"
    BASELINE_FORMAT = "current"

    def _baseline(
        self, mrr: float, viable: bool = True, mrr_easy: float = 0.95
    ) -> dict:
        return _make_cell(
            self.BASELINE_EMBEDDER,
            self.BASELINE_FORMAT,
            mrr,
            viable=viable,
            mrr_easy=mrr_easy,
            is_baseline=True,
        )

    def _viable(
        self,
        embedder_id: str,
        format_id: str,
        mrr: float,
        mrr_easy: float = 0.95,
        params_m: int = 22,
        latency_ms: float = 20.0,
    ) -> dict:
        return _make_cell(
            embedder_id,
            format_id,
            mrr,
            viable=True,
            mrr_easy=mrr_easy,
            params_m=params_m,
            latency_ms=latency_ms,
        )

    def _not_viable(
        self, embedder_id: str, format_id: str, mrr: float, mrr_easy: float = 0.0
    ) -> dict:
        return _make_cell(embedder_id, format_id, mrr, viable=False, mrr_easy=mrr_easy)

    # Action: "no_baseline"
    def test_no_baseline_when_missing(self):
        cells = [self._viable("mpnet", "terse", 0.8)]
        r = compute_recommendation(cells)
        assert r["action"] == "no_baseline"
        assert r["baseline"] is None
        assert r["best_cell"] is None

    # Action: "baseline_only"
    def test_baseline_only_when_only_cell(self):
        cells = [self._baseline(0.75)]
        r = compute_recommendation(cells)
        assert r["action"] == "baseline_only"
        assert r["best_cell"] is None

    # Action: "no_viable_cells" — FPR ceiling unmet
    def test_no_viable_cells_when_all_candidates_fail_fpr(self):
        cells = [
            self._baseline(0.75),
            self._not_viable("mpnet", "terse", 0.90, mrr_easy=0.0),
            self._not_viable("mpnet", "verbose", 0.85, mrr_easy=0.0),
        ]
        r = compute_recommendation(cells)
        assert r["action"] == "no_viable_cells"
        assert r["best_cell"] is None
        assert r["closest_cell"]["failure_reason"] == "fpr_ceiling_unmet"
        assert r["closest_cell"]["is_fundamental"] is True

    # Action: "no_viable_cells" — FPR met but MRR below floor
    def test_no_viable_cells_when_mrr_below_floor(self):
        # viable_at_calibrated_threshold=True but mrr_easy too low
        cells = [
            self._baseline(0.75),
            _make_cell("mpnet", "verbose", 0.85, viable=True, mrr_easy=0.70),
        ]
        r = compute_recommendation(cells)
        assert r["action"] == "no_viable_cells"
        assert r["closest_cell"]["failure_reason"] == "mrr_below_floor"
        assert r["closest_cell"]["is_fundamental"] is False

    # Action: "switch"
    def test_switch_when_viable_cell_beats_baseline(self):
        cells = [
            self._baseline(0.70),
            self._viable("mpnet", "verbose", 0.85),
            self._viable("mpnet", "terse", 0.80),
        ]
        r = compute_recommendation(cells)
        assert r["action"] == "switch"
        assert r["best_cell"]["cell_id"] == "mpnet_verbose"
        assert r["delta_mrr"] == pytest.approx(0.15)

    # Action: "keep_baseline"
    def test_keep_baseline_when_no_viable_candidate_beats_it(self):
        cells = [
            self._baseline(0.85),
            self._viable("mpnet", "verbose", 0.80),
            self._viable("mpnet", "terse", 0.70),
        ]
        r = compute_recommendation(cells)
        assert r["action"] == "keep_baseline"
        assert r["delta_mrr"] == pytest.approx(-0.05)

    def test_switch_picks_highest_mrr_viable_cell(self):
        cells = [
            self._baseline(0.60),
            self._viable("mpnet", "verbose", 0.90),
            self._viable("mpnet", "terse", 0.85),
            self._not_viable("mpnet", "current", 0.95),  # highest MRR but not viable
        ]
        r = compute_recommendation(cells)
        assert r["action"] == "switch"
        assert r["best_cell"]["cell_id"] == "mpnet_verbose"

    def test_not_viable_excluded_even_if_higher_mrr(self):
        cells = [
            self._baseline(0.70),
            self._not_viable("mpnet", "terse", 0.95),  # not viable
            self._viable("mpnet", "verbose", 0.75),  # viable but lower MRR
        ]
        r = compute_recommendation(cells)
        assert r["action"] == "switch"
        assert r["best_cell"]["cell_id"] == "mpnet_verbose"

    def test_baseline_mrr_used_as_reference_regardless_of_viability(self):
        cells = [
            self._baseline(0.70, viable=False),  # baseline itself not viable
            self._viable("mpnet", "verbose", 0.80),
        ]
        r = compute_recommendation(cells)
        assert r["action"] == "switch"
        assert r["delta_mrr"] == pytest.approx(0.10)

    def test_recommendation_returns_baseline_mrr(self):
        cells = [
            self._baseline(0.72),
            self._not_viable("mpnet", "terse", 0.68),
        ]
        r = compute_recommendation(cells)
        assert r["baseline"]["mrr"] == pytest.approx(0.72)

    def test_tiebreak_prefers_lower_latency(self):
        # Two viable cells within ΔMRR=0.02 — lower latency wins
        cells = [
            self._baseline(0.60),
            self._viable("mpnet", "verbose", 0.85, latency_ms=50.0),
            self._viable("mpnet", "terse", 0.84, latency_ms=15.0),  # lower latency
        ]
        r = compute_recommendation(cells)
        assert r["action"] == "switch"
        assert r["best_cell"]["cell_id"] == "mpnet_terse"

    def test_tiebreak_prefers_format_proximity_to_current(self):
        # Same latency and params — "current" > "verbose" > "terse"
        cells = [
            self._baseline(0.60),
            self._viable("mpnet", "terse", 0.85),
            self._viable("mpnet", "verbose", 0.85),
            self._viable("mpnet", "current", 0.85),
        ]
        r = compute_recommendation(cells)
        assert r["action"] == "switch"
        assert r["best_cell"]["cell_id"] == "mpnet_current"


# ---------------------------------------------------------------------------
# _threshold_sweep — FPR-constrained objective
# ---------------------------------------------------------------------------


def _make_tier_query(
    top1_score: float,
    is_negative: bool,
    top1_food_name: str | None = None,
    acceptable: list[str] | None = None,
    production_tier: str = "tier_2",
) -> dict:
    return {
        "production_tier": production_tier,
        "top1_score": top1_score,
        "top1_food_name": top1_food_name or ("wrong" if not is_negative else None),
        "acceptable_food_names": acceptable or ([] if is_negative else ["chicken"]),
        "is_negative": is_negative,
        "error": None,
    }


class TestThresholdSweepFPRConstrained:

    def test_sweep_has_61_entries(self):
        queries = [_make_tier_query(0.80, False, "chicken", ["chicken"])]
        result = _threshold_sweep(queries, "tier_2")
        assert len(result["sweep"]) == 61

    def test_sweep_entries_have_required_keys(self):
        queries = [_make_tier_query(0.80, False, "chicken", ["chicken"])]
        result = _threshold_sweep(queries, "tier_2")
        for entry in result["sweep"]:
            assert set(entry.keys()) == {
                "threshold",
                "tp",
                "fp",
                "fn",
                "tn",
                "f1",
                "fpr",
            }

    def test_all_hard_scores_above_90_gives_not_viable(self):
        # All negative controls score very high — no threshold can achieve FPR ≤ 5%
        # without also eliminating all positives (which are at the same score level).
        # With 1 positive and 12 hard queries all scoring ≥ 0.90:
        # at any threshold ≤ 0.90, fp=12, tn=0 → FPR = 1.0 > FPR_CEILING.
        # at threshold = 0.91 (above sweep ceiling), no results → out of range.
        queries = [
            _make_tier_query(0.92, False, "chicken", ["chicken"])
        ] + [  # positive
            _make_tier_query(0.91, True) for _ in range(12)
        ]  # 12 negatives
        result = _threshold_sweep(queries, "tier_2")
        assert result["viable"] is False
        assert result["optimal_threshold"] is None
        assert result["f1_at_optimal"] is None
        assert result["fpr_at_optimal"] is None

    def test_clean_separation_gives_viable_result(self):
        # Positives all score > 0.70, hard controls all score < 0.50.
        # The FPR=0 for all thresholds in [0.50, 0.70), so viable=True.
        queries = [
            _make_tier_query(0.80, False, "chicken", ["chicken"]) for _ in range(5)
        ] + [_make_tier_query(0.40, True) for _ in range(5)]
        result = _threshold_sweep(queries, "tier_2")
        assert result["viable"] is True
        assert result["optimal_threshold"] is not None
        # Threshold must be in the gap: above all hard scores (0.40) and
        # at or below the lowest positive score (0.80).
        assert 0.40 < result["optimal_threshold"] <= 0.80
        assert result["fpr_at_optimal"] <= FPR_CEILING

    def test_empty_queries_returns_null_viable_false(self):
        result = _threshold_sweep([], "tier_2")
        assert result["viable"] is False
        assert result["optimal_threshold"] is None
        assert result["sweep"] == []

    def test_no_negatives_gives_null_viable(self):
        # No negative-control queries in this tier: FPR is undefined (0/0), not 0.0.
        # viable=None signals a corpus coverage gap — the tier simply has no negatives.
        queries = [_make_tier_query(0.75, False, "chicken", ["chicken"])]
        result = _threshold_sweep(queries, "tier_2")
        assert result["viable"] is None
        assert result["optimal_threshold"] is None
        assert result["fpr_at_production"] is None
        assert result["reason"] == "FPR_undefined_no_negatives_in_tier"
        assert result["n_negatives_in_tier"] == 0

    def test_production_threshold_metrics_populated(self):
        from app.config import settings

        queries = [_make_tier_query(0.80, False, "chicken", ["chicken"])] + [
            _make_tier_query(0.40, True)
        ]
        result = _threshold_sweep(queries, "tier_2")
        assert result["production_threshold"] == pytest.approx(
            settings.food_properties_fallback_confidence
        )
        assert result["f1_at_production"] is not None
        assert result["fpr_at_production"] is not None

    def test_fpr_ceiling_boundary(self):
        # 1 FP out of 12 hard queries = 8.3% > 5% ceiling → not viable at that threshold
        # 0 FP → FPR = 0% → viable.
        # Build scenario: 12 hard queries score 0.65; 1 positive scores 0.75.
        # At threshold 0.66: fp=0, tn=12, tp=1 → FPR=0 → viable.
        # At threshold 0.64: fp=12, tn=0 → FPR=1.0 → not viable.
        queries = [_make_tier_query(0.75, False, "chicken", ["chicken"])] + [
            _make_tier_query(0.65, True) for _ in range(12)
        ]
        result = _threshold_sweep(queries, "tier_2")
        assert result["viable"] is True
        # The optimal threshold must be in the region where all 12 hard queries are below
        assert result["optimal_threshold"] > 0.65


# ---------------------------------------------------------------------------
# _recompute_query_at_threshold
# ---------------------------------------------------------------------------


class TestRecomputeQueryAtThreshold:

    def _pos_record(
        self,
        top1_score: float,
        top1_food: str,
        acceptable: list[str],
        exp_score: float | None = None,
        exp_rank: int | None = None,
    ) -> dict:
        pure_rr = round(1.0 / exp_rank, 6) if exp_rank else 0.0
        return {
            "is_negative": False,
            "top1_score": top1_score,
            "top1_food_name": top1_food,
            "acceptable_food_names": acceptable,
            "expected_score": exp_score,
            "expected_rank": exp_rank,
            "pure_reciprocal_rank": pure_rr,
            "error": None,
            "threshold_used": 0.62,
            "correct_at_1": True,
            "gate_passed": True,
            "reciprocal_rank": 1.0,
        }

    def _neg_record(self, top1_score: float) -> dict:
        return {
            "is_negative": True,
            "top1_score": top1_score,
            "top1_food_name": "beef ground",
            "acceptable_food_names": [],
            "expected_score": None,
            "expected_rank": None,
            "pure_reciprocal_rank": None,
            "error": None,
            "threshold_used": 0.62,
            "correct_at_1": top1_score < 0.62,
            "gate_passed": top1_score < 0.62,
            "reciprocal_rank": None,
        }

    def test_positive_top1_match_above_new_threshold(self):
        r = _recompute_query_at_threshold(
            self._pos_record(0.80, "chicken", ["chicken"]),
            threshold=0.75,
        )
        assert r["correct_at_1"] is True
        assert r["reciprocal_rank"] == pytest.approx(1.0)
        assert r["gate_passed"] is False  # expected_score not set → False

    def test_positive_top1_match_below_new_threshold_uses_expected(self):
        r = _recompute_query_at_threshold(
            self._pos_record(0.68, "chicken", ["chicken"], exp_score=0.68, exp_rank=1),
            threshold=0.70,
        )
        # top1 below threshold → correct_at_1=False; expected also below → rr=0
        assert r["correct_at_1"] is False
        assert r["reciprocal_rank"] == pytest.approx(0.0)

    def test_positive_expected_at_rank_3_above_threshold(self):
        r = _recompute_query_at_threshold(
            self._pos_record(0.90, "wrong", ["chicken"], exp_score=0.80, exp_rank=3),
            threshold=0.75,
        )
        # top1 is "wrong" (not in acceptable) → correct_at_1=False
        # expected is "chicken" at rank 3 with score 0.80 ≥ 0.75 → rr = 1/3
        assert r["correct_at_1"] is False
        assert r["reciprocal_rank"] == pytest.approx(round(1.0 / 3, 6))

    def test_negative_below_threshold_is_correct(self):
        r = _recompute_query_at_threshold(self._neg_record(0.55), threshold=0.70)
        assert r["correct_at_1"] is True
        assert r["reciprocal_rank"] is None

    def test_negative_above_threshold_is_incorrect(self):
        r = _recompute_query_at_threshold(self._neg_record(0.80), threshold=0.70)
        assert r["correct_at_1"] is False
        assert r["reciprocal_rank"] is None

    def test_errored_record_returned_unchanged(self):
        record = {**self._pos_record(0.80, "chicken", ["chicken"]), "error": "timeout"}
        r = _recompute_query_at_threshold(record, threshold=0.90)
        assert r is record  # same object returned unmodified

    def test_threshold_used_field_updated(self):
        r = _recompute_query_at_threshold(
            self._pos_record(0.80, "chicken", ["chicken"]),
            threshold=0.75,
        )
        assert r["threshold_used"] == pytest.approx(0.75)

    def test_pure_reciprocal_rank_preserved_unchanged(self):
        # pure_reciprocal_rank is rank-based and must not be overwritten at any threshold.
        record = self._pos_record(
            0.80, "chicken", ["chicken"], exp_score=0.80, exp_rank=2
        )
        assert record["pure_reciprocal_rank"] == pytest.approx(0.5)
        r = _recompute_query_at_threshold(record, threshold=0.90)
        assert r["pure_reciprocal_rank"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# hard_negative_control_pass_rate (Problem 4)
# ---------------------------------------------------------------------------


class TestHardNegativeControlPassRate:

    def test_hard_ncpr_reported_separately_from_top1_by_stratum(self):
        results = [
            _make_query_record("hard", "tier_2", True, None, True, None, None),
            _make_query_record(
                "hard", "tier_2", True, None, False, "beef ground", None
            ),
        ]
        s = _compute_cell_summary(results)
        assert "hard" not in s["top1_by_stratum"]
        assert s["hard_negative_control_pass_rate"] == pytest.approx(0.5)

    def test_hard_ncpr_all_pass(self):
        results = [
            _make_query_record("hard", "tier_2", True, None, True, None, None)
            for _ in range(4)
        ]
        s = _compute_cell_summary(results)
        assert s["hard_negative_control_pass_rate"] == pytest.approx(1.0)

    def test_hard_ncpr_none_when_no_hard_queries(self):
        results = [
            _make_query_record("easy", "tier_1", False, 1.0, True, "chicken", 0.85)
        ]
        s = _compute_cell_summary(results)
        assert s["hard_negative_control_pass_rate"] is None

    def test_top1_by_stratum_contains_only_positive_strata(self):
        results = [
            _make_query_record("easy", "tier_1", False, 1.0, True, "chicken", 0.85),
            _make_query_record("medium", "tier_2", False, 1.0, True, "chicken", 0.80),
            _make_query_record(
                "pathogen", "pathogen_stage_1", False, 1.0, True, "chicken", 0.90
            ),
            _make_query_record("hard", "tier_2", True, None, True, None, None),
        ]
        s = _compute_cell_summary(results)
        assert set(s["top1_by_stratum"].keys()) == {"easy", "medium", "pathogen"}
        assert "hard" not in s["top1_by_stratum"]


# ---------------------------------------------------------------------------
# Tri-state viable_at_calibrated_threshold (Problem 2)
# ---------------------------------------------------------------------------


class TestTriStateViability:

    def _make_cell_with_vat(self, vat: str, mrr_easy: float = 0.99) -> dict:
        """Build a minimal candidate cell with the given viable_at_calibrated_threshold."""
        return {
            "cell_id": f"test_{vat}",
            "embedder_id": "mpnet",
            "embedder_name": "mpnet",
            "embedder_hf_model": "sentence-transformers/mpnet",
            "embedder_dim": 768,
            "embedder_params_m": 109,
            "embedder_is_baseline": False,
            "embedder_training_objective": "general",
            "format_id": "verbose",
            "load_time_s": 1.0,
            "embed_time_s": 0.5,
            "queries": [],
            "summary": {
                "mrr": 0.85,
                "mrr_by_stratum": {"easy": mrr_easy},
                "viable_at_calibrated_threshold": vat,
                "n_errored_queries": 0,
                "mean_query_latency_ms": 20.0,
                "hard_fpr": 0.0,
            },
        }

    def _baseline(self) -> dict:
        return {
            "cell_id": "minilm-l6-v2_current",
            "embedder_id": "minilm-l6-v2",
            "embedder_name": "minilm-l6-v2",
            "embedder_hf_model": "sentence-transformers/all-MiniLM-L6-v2",
            "embedder_dim": 384,
            "embedder_params_m": 22,
            "embedder_is_baseline": True,
            "embedder_training_objective": "general",
            "format_id": "current",
            "load_time_s": 1.0,
            "embed_time_s": 0.5,
            "queries": [],
            "summary": {
                "mrr": 0.70,
                "mrr_by_stratum": {"easy": MRR_EASY_FLOOR},
                "viable_at_calibrated_threshold": "true",
                "n_errored_queries": 0,
                "mean_query_latency_ms": 20.0,
                "hard_fpr": 0.0,
            },
        }

    def test_partial_viability_is_treated_as_viable(self):
        # "partial" = some tiers have undefined FPR (corpus coverage gap). Still viable.
        cells = [self._baseline(), self._make_cell_with_vat("partial")]
        r = compute_recommendation(cells)
        assert r["action"] == "switch"

    def test_false_viability_is_not_viable(self):
        cells = [self._baseline(), self._make_cell_with_vat("false")]
        r = compute_recommendation(cells)
        assert r["action"] == "no_viable_cells"
        assert r["closest_cell"]["failure_reason"] == "fpr_ceiling_unmet"

    def test_true_viability_is_viable(self):
        cells = [self._baseline(), self._make_cell_with_vat("true")]
        r = compute_recommendation(cells)
        assert r["action"] == "switch"
