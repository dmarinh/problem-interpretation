# -*- coding: utf-8 -*-
"""
Unit tests for Experiment 2.1 (Embedder Comparison).

Tests cover pure functions that have no external dependencies:
  - load_corpus / corpus structure
  - _format_query (must mirror production RetrievalService exactly)
  - _get_threshold (tier → threshold lookup)
  - _score_query_result (per-query metric calculation, both polarities)
  - _compute_embedder_summary (aggregation math, including error-path)

Integration-level tests (no model load, no real ChromaDB):
  - TestAllQueriesErroredPipeline: monkey-patches collection.query to always
    raise; verifies pipeline completes, writes valid JSON, print_summary
    does not crash when top1_accuracy is None.

ChromaDB, SentenceTransformer, and MLflow are NOT exercised here.
"""

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DATASETS_DIR = PROJECT_ROOT / "benchmarks" / "datasets"


# ---------------------------------------------------------------------------
# Import targets — will fail until the module exists
# ---------------------------------------------------------------------------

from benchmarks.experiments.exp_2_1_embedder_comparison import (
    _format_query,
    _get_threshold,
    _score_query_result,
    _compute_embedder_summary,
    compute_recommendation,
    load_corpus,
    run_embedder_queries,
    save_results,
    print_summary,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def corpus() -> list[dict]:
    return load_corpus()


# ---------------------------------------------------------------------------
# Corpus structure
# ---------------------------------------------------------------------------

class TestLoadCorpus:
    def test_total_count(self, corpus):
        assert len(corpus) == 30

    def test_stratum_easy(self, corpus):
        assert sum(1 for q in corpus if q["tier"] == "easy") == 10

    def test_stratum_medium(self, corpus):
        assert sum(1 for q in corpus if q["tier"] == "medium") == 10

    def test_stratum_hard(self, corpus):
        assert sum(1 for q in corpus if q["tier"] == "hard") == 6

    def test_stratum_pathogen(self, corpus):
        assert sum(1 for q in corpus if q["tier"] == "pathogen") == 4

    def test_positive_entries_have_food_names(self, corpus):
        positives = [q for q in corpus if q["tier"] != "hard"]
        for q in positives:
            assert isinstance(q["acceptable_food_names"], list)
            assert len(q["acceptable_food_names"]) >= 1, f"{q['id']} has empty acceptable_food_names but tier={q['tier']}"

    def test_negative_controls_have_empty_acceptable_list(self, corpus):
        negatives = [q for q in corpus if q["tier"] == "hard"]
        for q in negatives:
            assert q["acceptable_food_names"] == [], f"{q['id']} hard-tier entry should have empty acceptable_food_names"

    def test_required_fields_present(self, corpus):
        required = {"id", "food_description", "field", "production_tier", "tier", "acceptable_food_names"}
        for q in corpus:
            missing = required - set(q.keys())
            assert not missing, f"{q['id']} missing fields: {missing}"

    def test_production_tier_values(self, corpus):
        valid_tiers = {"tier_1", "tier_2", "pathogen_stage_1"}
        for q in corpus:
            assert q["production_tier"] in valid_tiers, f"{q['id']} has unknown production_tier: {q['production_tier']}"

    def test_field_values(self, corpus):
        valid_fields = {"ph_aw_combined", "ph", "water_activity", "pathogen"}
        for q in corpus:
            assert q["field"] in valid_fields, f"{q['id']} has unknown field: {q['field']}"


# ---------------------------------------------------------------------------
# Query reformulation — must match production RetrievalService exactly
# ---------------------------------------------------------------------------

class TestFormatQuery:
    """_format_query must mirror app/rag/retrieval.py query strings verbatim."""

    def test_ph_aw_combined(self):
        entry = {"food_description": "chicken", "field": "ph_aw_combined"}
        assert _format_query(entry) == "chicken pH water activity properties"

    def test_ph_fallback(self):
        entry = {"food_description": "turkey", "field": "ph"}
        assert _format_query(entry) == "turkey pH acidity"

    def test_water_activity_fallback(self):
        entry = {"food_description": "duck", "field": "water_activity"}
        assert _format_query(entry) == "duck water activity aw moisture"

    def test_pathogen(self):
        entry = {"food_description": "raw chicken", "field": "pathogen"}
        assert _format_query(entry) == "raw chicken food hazard"

    def test_multi_word_food(self):
        entry = {"food_description": "cooked white rice", "field": "ph_aw_combined"}
        assert _format_query(entry) == "cooked white rice pH water activity properties"


# ---------------------------------------------------------------------------
# Threshold lookup
# ---------------------------------------------------------------------------

class TestGetThreshold:
    def test_tier_1(self):
        from app.config import settings
        assert _get_threshold("tier_1") == pytest.approx(settings.food_properties_confidence)

    def test_tier_2(self):
        from app.config import settings
        assert _get_threshold("tier_2") == pytest.approx(settings.food_properties_fallback_confidence)

    def test_pathogen_stage_1(self):
        from app.config import settings
        assert _get_threshold("pathogen_stage_1") == pytest.approx(settings.pathogen_hazards_confidence)

    def test_reads_from_settings(self):
        from app.config import settings
        assert _get_threshold("tier_1") == pytest.approx(settings.food_properties_confidence)
        assert _get_threshold("tier_2") == pytest.approx(settings.food_properties_fallback_confidence)
        assert _get_threshold("pathogen_stage_1") == pytest.approx(settings.pathogen_hazards_confidence)


# ---------------------------------------------------------------------------
# Per-query metric calculation
# ---------------------------------------------------------------------------

def _make_result(food_name: str, score: float, doc_id: str | None = None) -> dict:
    return {
        "food_name": food_name,
        "doc_id": doc_id or f"fp_{food_name.replace(' ', '_')}",
        "score": score,
    }


class TestScoreQueryResult:
    """_score_query_result(top_k_results, query_entry, threshold) -> per-query dict."""

    # --- Positive cases (non-empty acceptable_food_names) ---

    def test_correct_at_1_true_when_top1_matches_and_above_threshold(self):
        results = [
            _make_result("chicken", 0.85),
            _make_result("fresh poultry", 0.72),
        ]
        entry = {
            "id": "E01",
            "food_description": "chicken",
            "field": "ph_aw_combined",
            "production_tier": "tier_1",
            "tier": "easy",
            "acceptable_food_names": ["chicken"],
        }
        scored = _score_query_result(results, entry, threshold=0.70)
        assert scored["correct_at_1"] is True
        assert scored["gate_passed"] is True

    def test_correct_at_1_false_when_top1_wrong_food(self):
        results = [
            _make_result("chili sauce acidified", 0.75),
            _make_result("chicken", 0.65),
        ]
        entry = {
            "id": "E01",
            "food_description": "chicken",
            "field": "ph_aw_combined",
            "production_tier": "tier_1",
            "tier": "easy",
            "acceptable_food_names": ["chicken"],
        }
        scored = _score_query_result(results, entry, threshold=0.70)
        assert scored["correct_at_1"] is False

    def test_correct_at_1_false_when_top1_matches_but_below_threshold(self):
        results = [
            _make_result("chicken", 0.68),  # matches food but below 0.70
        ]
        entry = {
            "id": "E01",
            "food_description": "chicken",
            "field": "ph_aw_combined",
            "production_tier": "tier_1",
            "tier": "easy",
            "acceptable_food_names": ["chicken"],
        }
        scored = _score_query_result(results, entry, threshold=0.70)
        assert scored["correct_at_1"] is False

    def test_correct_at_3_true_when_canonical_in_top3_above_threshold(self):
        results = [
            _make_result("chili sauce acidified", 0.80),
            _make_result("beets canned", 0.75),
            _make_result("chicken", 0.72),  # rank 3
        ]
        entry = {
            "id": "E01",
            "food_description": "turkey",
            "field": "ph_aw_combined",
            "production_tier": "tier_1",
            "tier": "easy",
            "acceptable_food_names": ["chicken"],
        }
        scored = _score_query_result(results, entry, threshold=0.70)
        assert scored["correct_at_1"] is False
        assert scored["correct_at_3"] is True

    def test_acceptable_list_multi_option(self):
        """M10 (cod): either codfish boiled or fish fresh most is acceptable."""
        results = [_make_result("fish fresh most", 0.68)]
        entry = {
            "id": "M10",
            "food_description": "cod",
            "field": "ph",
            "production_tier": "tier_2",
            "tier": "medium",
            "acceptable_food_names": ["codfish boiled", "fish fresh most"],
        }
        scored = _score_query_result(results, entry, threshold=0.62)
        assert scored["correct_at_1"] is True

    def test_expected_rank_populated(self):
        results = [
            _make_result("chili sauce acidified", 0.80),
            _make_result("chicken", 0.72),
        ]
        entry = {
            "id": "E01",
            "food_description": "chicken",
            "field": "ph_aw_combined",
            "production_tier": "tier_1",
            "tier": "easy",
            "acceptable_food_names": ["chicken"],
        }
        scored = _score_query_result(results, entry, threshold=0.70)
        assert scored["expected_rank"] == 2
        assert scored["expected_score"] == pytest.approx(0.72)

    def test_expected_score_is_none_when_not_in_top_k(self):
        """expected_score must be None (not 0.0, not absent) when canonical not found."""
        results = [
            _make_result("chili sauce acidified", 0.80),
            _make_result("beets canned", 0.75),
        ]
        entry = {
            "id": "E01",
            "food_description": "chicken",
            "field": "ph_aw_combined",
            "production_tier": "tier_1",
            "tier": "easy",
            "acceptable_food_names": ["chicken"],
        }
        scored = _score_query_result(results, entry, threshold=0.70)
        assert "expected_score" in scored
        assert scored["expected_score"] is None
        assert "expected_rank" in scored
        assert scored["expected_rank"] is None

    def test_canonical_food_name_set(self):
        results = [_make_result("chicken", 0.85)]
        entry = {
            "id": "E01",
            "food_description": "chicken",
            "field": "ph_aw_combined",
            "production_tier": "tier_1",
            "tier": "easy",
            "acceptable_food_names": ["chicken"],
        }
        scored = _score_query_result(results, entry, threshold=0.70)
        assert scored["canonical_food_name"] == "chicken"

    # --- Negative controls (empty acceptable_food_names) ---

    def test_negative_control_correct_at_1_true_when_no_doc_clears_threshold(self):
        """H01–H06: correct behaviour is that nothing clears the gate."""
        results = [
            _make_result("chili sauce acidified", 0.55),
            _make_result("beets", 0.52),
        ]
        entry = {
            "id": "H01",
            "food_description": "turkey",
            "field": "ph",
            "production_tier": "tier_2",
            "tier": "hard",
            "acceptable_food_names": [],
        }
        scored = _score_query_result(results, entry, threshold=0.62)
        assert scored["correct_at_1"] is True
        assert scored["gate_passed"] is True

    def test_negative_control_correct_at_1_false_when_doc_clears_threshold(self):
        """Bad embedder matches nonsense food above threshold — should be flagged."""
        results = [_make_result("chili sauce acidified", 0.75)]
        entry = {
            "id": "H01",
            "food_description": "turkey",
            "field": "ph",
            "production_tier": "tier_2",
            "tier": "hard",
            "acceptable_food_names": [],
        }
        scored = _score_query_result(results, entry, threshold=0.62)
        assert scored["correct_at_1"] is False
        assert scored["gate_passed"] is False

    def test_negative_control_canonical_food_name_is_none(self):
        results = [_make_result("anything", 0.50)]
        entry = {
            "id": "H05",
            "food_description": "zarblax burger",
            "field": "ph",
            "production_tier": "tier_2",
            "tier": "hard",
            "acceptable_food_names": [],
        }
        scored = _score_query_result(results, entry, threshold=0.62)
        assert scored["canonical_food_name"] is None


# ---------------------------------------------------------------------------
# Per-embedder summary aggregation
# ---------------------------------------------------------------------------

class TestComputeEmbedderSummary:
    def _make_query_results(self) -> list[dict]:
        return [
            # easy - correct
            {"tier": "easy", "correct_at_1": True, "correct_at_3": True, "gate_passed": True, "expected_score": 0.80},
            {"tier": "easy", "correct_at_1": True, "correct_at_3": True, "gate_passed": True, "expected_score": 0.75},
            # medium - mixed
            {"tier": "medium", "correct_at_1": False, "correct_at_3": True, "gate_passed": False, "expected_score": 0.58},
            {"tier": "medium", "correct_at_1": True, "correct_at_3": True, "gate_passed": True, "expected_score": 0.65},
            # hard (negative control) - correct (no false positives)
            {"tier": "hard", "correct_at_1": True, "correct_at_3": True, "gate_passed": True, "expected_score": None},
            # pathogen - correct
            {"tier": "pathogen", "correct_at_1": True, "correct_at_3": True, "gate_passed": True, "expected_score": 0.78},
        ]

    def test_top1_accuracy(self):
        qr = self._make_query_results()
        summary = _compute_embedder_summary(qr)
        # 5 correct out of 6
        assert summary["top1_accuracy"] == pytest.approx(5 / 6)

    def test_gate_pass_rate(self):
        qr = self._make_query_results()
        summary = _compute_embedder_summary(qr)
        # 5 passed gate out of 6
        assert summary["gate_pass_rate"] == pytest.approx(5 / 6)

    def test_mean_expected_score_excludes_nulls(self):
        qr = self._make_query_results()
        summary = _compute_embedder_summary(qr)
        # Non-null expected_scores: 0.80, 0.75, 0.58, 0.65, 0.78 → mean = 3.56/5
        assert summary["mean_expected_score"] == pytest.approx((0.80 + 0.75 + 0.58 + 0.65 + 0.78) / 5)

    def test_tier_accuracy_easy(self):
        qr = self._make_query_results()
        summary = _compute_embedder_summary(qr)
        assert summary["tier_accuracy"]["easy"] == pytest.approx(1.0)

    def test_tier_accuracy_medium(self):
        qr = self._make_query_results()
        summary = _compute_embedder_summary(qr)
        assert summary["tier_accuracy"]["medium"] == pytest.approx(0.5)

    def test_tier_accuracy_hard(self):
        qr = self._make_query_results()
        summary = _compute_embedder_summary(qr)
        assert summary["tier_accuracy"]["hard"] == pytest.approx(1.0)

    def test_tier_accuracy_pathogen(self):
        qr = self._make_query_results()
        summary = _compute_embedder_summary(qr)
        assert summary["tier_accuracy"]["pathogen"] == pytest.approx(1.0)

    def test_n_positive_queries(self):
        qr = self._make_query_results()
        summary = _compute_embedder_summary(qr)
        # 5 have non-null expected_score
        assert summary["n_positive_queries"] == 5

    def test_n_errored_queries_zero_when_no_errors(self):
        qr = self._make_query_results()
        summary = _compute_embedder_summary(qr)
        assert summary["n_errored_queries"] == 0


# ---------------------------------------------------------------------------
# Error-path: BUG 2 regression tests
#
# When ChromaDB raises at query time, the per-query record must carry
# error=<str> and correct_at_1=None.  _compute_embedder_summary must:
#   - exclude errored records from accuracy denominators
#   - report n_errored_queries separately
# The original failure mode: empty top-K → negative controls trivially
# "passed" (no doc cleared threshold) → correct_at_1=True → 100% accuracy
# on an all-error run.  This class locks that out.
# ---------------------------------------------------------------------------

class TestComputeEmbedderSummaryErrors:
    _EMBED_ERROR = "'_STEmbeddingFunction' object has no attribute 'embed_query'"

    def _make_mixed_results(self) -> list[dict]:
        return [
            # valid easy  — correct
            {"tier": "easy",   "correct_at_1": True,  "correct_at_3": True,  "gate_passed": True,  "expected_score": 0.80, "error": None},
            # valid medium — wrong
            {"tier": "medium", "correct_at_1": False, "correct_at_3": False, "gate_passed": False, "expected_score": 0.55, "error": None},
            # errored hard (negative control) — must NOT count as correct
            {"tier": "hard",   "correct_at_1": None,  "correct_at_3": None,  "gate_passed": None,  "expected_score": None, "error": self._EMBED_ERROR},
            # errored easy — must NOT count as correct
            {"tier": "easy",   "correct_at_1": None,  "correct_at_3": None,  "gate_passed": None,  "expected_score": None, "error": "ChromaDB query error"},
        ]

    def test_errored_queries_excluded_from_denominator(self):
        summary = _compute_embedder_summary(self._make_mixed_results())
        # 2 valid queries: 1 correct_at_1 → 0.5
        assert summary["top1_accuracy"] == pytest.approx(1 / 2)

    def test_n_errored_queries_reported(self):
        summary = _compute_embedder_summary(self._make_mixed_results())
        assert summary["n_errored_queries"] == 2

    def test_all_errors_returns_none_accuracy(self):
        """The silent-success bug: all queries errored must yield None, not 1.0."""
        results = [
            {"tier": "hard", "correct_at_1": None, "correct_at_3": None,
             "gate_passed": None, "expected_score": None, "error": self._EMBED_ERROR}
            for _ in range(6)
        ]
        summary = _compute_embedder_summary(results)
        assert summary["top1_accuracy"] is None
        assert summary["top3_accuracy"] is None
        assert summary["gate_pass_rate"] is None
        assert summary["n_errored_queries"] == 6

    def test_tier_accuracy_excludes_errored_queries(self):
        summary = _compute_embedder_summary(self._make_mixed_results())
        # 1 valid easy query (correct) → 1.0
        assert summary["tier_accuracy"]["easy"] == pytest.approx(1.0)
        # 1 valid medium query (wrong) → 0.0
        assert summary["tier_accuracy"]["medium"] == pytest.approx(0.0)
        # no valid hard queries → absent from tier_accuracy
        assert "hard" not in summary["tier_accuracy"]

    def test_mean_expected_score_excludes_errored_queries(self):
        summary = _compute_embedder_summary(self._make_mixed_results())
        # Only 2 valid queries have scores: 0.80 (easy) and 0.55 (medium)
        assert summary["mean_expected_score"] == pytest.approx((0.80 + 0.55) / 2, abs=1e-4)

    def test_records_without_error_key_treated_as_valid(self):
        """Records from old code without an 'error' key default to valid (no regression)."""
        results = [
            {"tier": "easy", "correct_at_1": True, "correct_at_3": True,
             "gate_passed": True, "expected_score": 0.80},
        ]
        summary = _compute_embedder_summary(results)
        assert summary["top1_accuracy"] == pytest.approx(1.0)
        assert summary["n_errored_queries"] == 0


# ---------------------------------------------------------------------------
# Integration: all queries error → full pipeline must not crash
#
# Reproduces the compound failure from BUG 2 + BUG 3:
#   - collection.query() always raises (mock of ChromaDB interface error)
#   - run_embedder_queries must capture the error, not call _score_query_result
#   - _compute_embedder_summary must return None for accuracy, not 1.0
#   - save_results must write valid JSON (json.load must not raise)
#   - print_summary must not crash on None accuracy values
# ---------------------------------------------------------------------------

class TestAllQueriesErroredPipeline:
    class _AlwaysErrorCollection:
        def query(self, **kwargs):
            raise RuntimeError("mock: embed_query() called with keyword arg")

    def _make_embedder_result(self, query_results: list[dict]) -> dict:
        summary = _compute_embedder_summary(query_results)
        return {
            "id": "test-embedder", "name": "Test Embedder",
            "hf_model": "test/model", "dim": 384, "params_m": 22,
            "is_baseline": True, "training_objective": "general",
            "load_time_s": 0.01, "corpus_embed_time_s": 0.01,
            "queries": query_results, "summary": summary,
        }

    def test_run_embedder_queries_captures_errors(self):
        corpus = [q for q in load_corpus() if q["tier"] == "hard"]
        results = run_embedder_queries(self._AlwaysErrorCollection(), corpus, top_k=5)
        assert all(r["error"] is not None for r in results)
        assert all(r["correct_at_1"] is None for r in results)

    def test_all_errored_summary_top1_is_none_not_one(self):
        """The silent-success regression: must be None, not 1.0."""
        corpus = [q for q in load_corpus() if q["tier"] == "hard"]
        results = run_embedder_queries(self._AlwaysErrorCollection(), corpus, top_k=5)
        summary = _compute_embedder_summary(results)
        assert summary["top1_accuracy"] is None
        assert summary["n_errored_queries"] == len(corpus)

    def test_save_results_writes_valid_json(self, tmp_path, monkeypatch):
        import benchmarks.experiments.exp_2_1_embedder_comparison as exp_mod
        monkeypatch.setattr(exp_mod, "RESULTS_DIR", tmp_path)

        corpus = load_corpus()[:3]
        query_results = run_embedder_queries(self._AlwaysErrorCollection(), corpus, top_k=5)
        embedder_results = [self._make_embedder_result(query_results)]

        out_dir = save_results(embedder_results, corpus, "20260515_120000")

        latest = out_dir / "latest.json"
        assert latest.exists()
        with open(latest, encoding="utf-8") as f:
            data = json.load(f)  # must not raise

        s = data["embedders"][0]["summary"]
        assert s["top1_accuracy"] is None
        assert s["n_errored_queries"] == 3

    def test_print_summary_does_not_crash_on_none_accuracy(self):
        """print_summary must survive None accuracy (BUG 4 regression lock)."""
        embedder_results = [self._make_embedder_result(
            run_embedder_queries(self._AlwaysErrorCollection(), load_corpus()[:2], top_k=5)
        )]
        print_summary(embedder_results)  # must not raise


# ---------------------------------------------------------------------------
# TestComputeRecommendation
#
# Regression lock for BUG 1: terminal print_summary and Streamlit page must
# agree on the recommendation because both call compute_recommendation().
#
# The exact failing case: candidate has Δtop-1 = +7% BUT hard accuracy = 83%
# (one false positive out of 6 queries).  Must produce action="no_safe_candidates".
# ---------------------------------------------------------------------------

def _make_embedder(
    *,
    is_baseline: bool,
    top1: float | None,
    hard: float | None,
    gate: float | None = None,
    name: str = "embedder",
) -> dict:
    return {
        "id": name,
        "name": name,
        "is_baseline": is_baseline,
        "summary": {
            "top1_accuracy": top1,
            "gate_pass_rate": gate,
            "tier_accuracy": {"hard": hard} if hard is not None else {},
        },
    }


class TestComputeRecommendation:
    def test_baseline_only_returns_baseline_only_action(self):
        baseline = _make_embedder(is_baseline=True, top1=0.80, hard=1.0)
        rec = compute_recommendation([baseline])
        assert rec["action"] == "baseline_only"
        assert rec["best_candidate"] is None

    def test_no_baseline_returns_no_baseline_action(self):
        candidate = _make_embedder(is_baseline=False, top1=0.87, hard=1.0)
        rec = compute_recommendation([candidate])
        assert rec["action"] == "no_baseline"

    def test_empty_list_returns_no_baseline(self):
        rec = compute_recommendation([])
        assert rec["action"] == "no_baseline"

    def test_hard_regression_blocks_switch_bug1_regression(self):
        """BUG 1 exact case: Δ+7% AND hard=83% must NOT recommend a switch."""
        baseline  = _make_embedder(is_baseline=True,  top1=0.80, hard=1.0,    name="minilm")
        candidate = _make_embedder(is_baseline=False, top1=0.87, hard=5/6,    name="mpnet")
        rec = compute_recommendation([baseline, candidate])
        assert rec["action"] == "no_safe_candidates", (
            f"Expected no_safe_candidates but got {rec['action']!r} — "
            "hard-stratum false positive must block switch recommendation"
        )
        assert rec["best_candidate"] is None

    def test_all_candidates_hard_regression_no_safe(self):
        baseline  = _make_embedder(is_baseline=True,  top1=0.80, hard=1.0, name="base")
        cand_a    = _make_embedder(is_baseline=False, top1=0.90, hard=0.83, name="a")
        cand_b    = _make_embedder(is_baseline=False, top1=0.85, hard=0.67, name="b")
        rec = compute_recommendation([baseline, cand_a, cand_b])
        assert rec["action"] == "no_safe_candidates"

    def test_no_improvement_returns_keep_baseline(self):
        baseline  = _make_embedder(is_baseline=True,  top1=0.87, hard=1.0, name="base")
        candidate = _make_embedder(is_baseline=False, top1=0.80, hard=1.0, name="cand")
        rec = compute_recommendation([baseline, candidate])
        assert rec["action"] == "keep_baseline"
        assert rec["delta"] <= 0

    def test_safe_improvement_returns_switch(self):
        baseline  = _make_embedder(is_baseline=True,  top1=0.80, hard=1.0, name="base")
        candidate = _make_embedder(is_baseline=False, top1=0.90, hard=1.0, name="cand")
        rec = compute_recommendation([baseline, candidate])
        assert rec["action"] == "switch"
        assert rec["best_candidate"]["name"] == "cand"
        assert abs(rec["delta"] - 0.10) < 1e-9

    def test_picks_best_among_multiple_safe_candidates(self):
        baseline = _make_embedder(is_baseline=True,  top1=0.80, hard=1.0, name="base")
        cand_a   = _make_embedder(is_baseline=False, top1=0.85, hard=1.0, name="a")
        cand_b   = _make_embedder(is_baseline=False, top1=0.92, hard=1.0, name="b")
        rec = compute_recommendation([baseline, cand_a, cand_b])
        assert rec["action"] == "switch"
        assert rec["best_candidate"]["name"] == "b"

    def test_safe_candidate_with_none_top1_treated_as_zero(self):
        baseline  = _make_embedder(is_baseline=True,  top1=0.80, hard=1.0, name="base")
        candidate = _make_embedder(is_baseline=False, top1=None, hard=1.0, name="cand")
        rec = compute_recommendation([baseline, candidate])
        assert rec["action"] == "keep_baseline"

    def test_missing_hard_key_treated_as_zero(self):
        """An embedder whose tier_accuracy has no 'hard' key must not pass the guard."""
        baseline  = _make_embedder(is_baseline=True,  top1=0.80, hard=1.0, name="base")
        candidate = _make_embedder(is_baseline=False, top1=0.90, hard=None, name="cand")
        rec = compute_recommendation([baseline, candidate])
        assert rec["action"] == "no_safe_candidates"
