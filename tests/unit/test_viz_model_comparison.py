"""Unit tests for pages/2_model_comparison.py safety-critical banner logic.

The page executes Streamlit UI calls on import, so it cannot be imported
directly. Following the pattern established in test_viz_overview.py, the
pure ``any_failure`` expression is mirrored here as a helper function.
The page's copy is authoritative; this test ensures the LOGIC is correct.
If the expression is ever factored into lib/, update accordingly.

Safety context
--------------
``any_failure`` gates a visible red alert whenever any query × model cell
shows GROWTH vs THERMAL_INACTIVATION misclassification. The severity is
highest among all benchmark failure modes because bias correction signs
reverse on misclassification, silently producing optimistic values for
thermal-inactivation scenarios — a direct food safety risk.

The expression from pages/2_model_comparison.py (authoritative):

    any_failure = any(
        not q.get("model_type_ok", False)
        for r in results
        for q in r.get("queries", [])
        if "model_type" in q.get("field_scores", {})
    )
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Mirror of the pure expression from pages/2_model_comparison.py
# ---------------------------------------------------------------------------


def any_model_type_failure(results: list[dict]) -> bool:
    """Return True when any query that has model_type in ground truth failed.

    Mirrors the ``any_failure`` expression in pages/2_model_comparison.py.
    """
    return any(
        not q.get("model_type_ok", False)
        for r in results
        for q in r.get("queries", [])
        if "model_type" in q.get("field_scores", {})
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _query(query_id: str, model_type_in_truth: bool, model_type_ok: bool | None = None) -> dict:
    """Build a minimal query dict for test fixtures."""
    field_scores = {}
    if model_type_in_truth:
        field_scores["model_type"] = True
    q: dict = {"query_id": query_id, "field_scores": field_scores}
    if model_type_ok is not None:
        q["model_type_ok"] = model_type_ok
    return q


def _result(model: str, queries: list[dict]) -> dict:
    return {"model": model, "queries": queries, "summary": {"field_accuracy": {}}}


# ---------------------------------------------------------------------------
# Tests: any_model_type_failure
# ---------------------------------------------------------------------------


class TestAnyModelTypeFailure:
    # --- baseline cases ---

    def test_empty_results_is_not_a_failure(self):
        """No results → no failure; banner must not appear."""
        assert any_model_type_failure([]) is False

    def test_result_with_no_queries_is_not_a_failure(self):
        assert any_model_type_failure([_result("M1", [])]) is False

    # --- gating on model_type in ground truth ---

    def test_query_without_model_type_in_truth_is_ignored(self):
        """model_type_ok=False is irrelevant when model_type is not in field_scores.

        The banner reflects misclassification only for queries where model_type
        was part of the ground truth benchmark.
        """
        q = {"query_id": "Q1", "field_scores": {"pathogen": True}, "model_type_ok": False}
        results = [_result("M1", [q])]
        assert any_model_type_failure(results) is False

    def test_query_with_model_type_in_truth_and_ok_true_is_not_a_failure(self):
        q = _query("Q1", model_type_in_truth=True, model_type_ok=True)
        assert any_model_type_failure([_result("M1", [q])]) is False

    def test_query_with_model_type_in_truth_and_ok_false_is_a_failure(self):
        q = _query("Q1", model_type_in_truth=True, model_type_ok=False)
        assert any_model_type_failure([_result("M1", [q])]) is True

    # --- safety-critical: missing model_type_ok fails closed ---

    def test_missing_model_type_ok_field_is_treated_as_failure(self):
        """Safety-critical: absent model_type_ok must never be treated as a pass.

        The default in q.get('model_type_ok', False) is False, which means a
        malformed or partial result still triggers the banner — the correct
        conservative behaviour for a food safety system.
        """
        q = _query("Q1", model_type_in_truth=True)  # no model_type_ok key
        assert any_model_type_failure([_result("M1", [q])]) is True

    # --- mixed scenarios ---

    def test_one_failure_among_passing_models_triggers_banner(self):
        """Even a single failure in one model flags the banner."""
        results = [
            _result("Good", [
                _query("Q1", True, True),
                _query("Q2", True, True),
            ]),
            _result("Bad", [
                _query("Q1", True, True),
                _query("Q2", True, False),  # one failure
            ]),
        ]
        assert any_model_type_failure(results) is True

    def test_all_models_all_queries_pass_is_not_a_failure(self):
        results = [
            _result("M1", [_query("Q1", True, True), _query("Q2", True, True)]),
            _result("M2", [_query("Q1", True, True), _query("Q2", True, True)]),
        ]
        assert any_model_type_failure(results) is False

    def test_all_models_all_queries_fail_is_a_failure(self):
        results = [
            _result("M1", [_query("Q1", True, False), _query("Q2", True, False)]),
            _result("M2", [_query("Q1", True, False), _query("Q2", True, False)]),
        ]
        assert any_model_type_failure(results) is True

    def test_mixed_truth_presence_only_scored_queries_count(self):
        """Queries without model_type in ground truth are excluded from the gate,
        regardless of model_type_ok value.
        """
        results = [
            _result("M1", [
                _query("Q_scored", model_type_in_truth=True, model_type_ok=True),
                # Q_unscored has model_type_ok=False but no ground truth for model_type
                _query("Q_unscored", model_type_in_truth=False, model_type_ok=False),
            ])
        ]
        assert any_model_type_failure(results) is False

    # --- short-circuits at first failure (efficiency, not correctness) ---

    def test_failure_in_first_query_of_first_model_triggers(self):
        """The first query is enough to trigger — does not need to scan all."""
        results = [
            _result("M1", [_query("Q1", True, False)]),
            _result("M2", [_query("Q1", True, True)]),
        ]
        assert any_model_type_failure(results) is True

    # --- edge: empty queries list with other fields present ---

    def test_result_missing_queries_key_does_not_crash(self):
        """r.get('queries', []) must gracefully handle a missing 'queries' key."""
        results = [{"model": "M1", "summary": {}}]  # no 'queries' key
        assert any_model_type_failure(results) is False
