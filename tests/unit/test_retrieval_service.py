"""
Unit tests for RetrievalService.
"""

from unittest.mock import MagicMock

import pytest

from app.rag.reranker import BaseReranker, RerankResult
from app.rag.retrieval import RetrievalService
from app.rag.vector_store import VectorStore


def _make_hazard(food_name: str, pathogen: str, annual_deaths: int) -> dict:
    return {
        "id": f"{food_name}_{pathogen}",
        "document": f"Hazard for {food_name}: {pathogen} ({annual_deaths} annual US deaths).",
        "metadata": {
            "food_name": food_name,
            "pathogen": pathogen,
            "annual_deaths_us": str(annual_deaths),
            "type": VectorStore.TYPE_PATHOGEN_HAZARDS,
        },
    }


@pytest.fixture
def retrieval_service():
    mock_store = MagicMock()
    return RetrievalService(vector_store=mock_store), mock_store


class TestGetHazardsForFood:

    def test_returns_sorted_by_annual_deaths_descending(self, retrieval_service):
        service, mock_store = retrieval_service
        mock_store.get_documents.return_value = [
            _make_hazard("chicken raw", "Staphylococcus aureus", 6),
            _make_hazard("chicken raw", "Salmonella spp.", 238),
            _make_hazard("chicken raw", "Listeria monocytogenes", 172),
        ]

        results = service.get_hazards_for_food("chicken raw")

        assert [r["metadata"]["pathogen"] for r in results] == [
            "Salmonella spp.",
            "Listeria monocytogenes",
            "Staphylococcus aureus",
        ]

    def test_passes_correct_filter_to_store(self, retrieval_service):
        service, mock_store = retrieval_service
        mock_store.get_documents.return_value = []

        service.get_hazards_for_food("beef raw")

        mock_store.get_documents.assert_called_once_with(
            where={"food_name": "beef raw", "type": VectorStore.TYPE_PATHOGEN_HAZARDS}
        )

    def test_returns_empty_list_when_food_not_found(self, retrieval_service):
        service, mock_store = retrieval_service
        mock_store.get_documents.return_value = []

        results = service.get_hazards_for_food("unknown food xyz")

        assert results == []

    def test_handles_string_death_values_from_csv(self, retrieval_service):
        """annual_deaths_us is stored as a string from the CSV."""
        service, mock_store = retrieval_service
        mock_store.get_documents.return_value = [
            _make_hazard("oysters raw", "Vibrio vulnificus", 36),
            _make_hazard("oysters raw", "Norovirus", 174),
        ]

        results = service.get_hazards_for_food("oysters raw")

        assert results[0]["metadata"]["pathogen"] == "Norovirus"

    def test_handles_missing_annual_deaths_gracefully(self, retrieval_service):
        """Rows missing annual_deaths_us metadata should sort to the bottom."""
        service, mock_store = retrieval_service
        mock_store.get_documents.return_value = [
            {
                "id": "a",
                "document": "Hazard for fish: Unknown pathogen.",
                "metadata": {
                    "food_name": "fish",
                    "pathogen": "Unknown",
                    "type": VectorStore.TYPE_PATHOGEN_HAZARDS,
                },
            },
            _make_hazard("fish", "Salmonella spp.", 238),
        ]

        results = service.get_hazards_for_food("fish")

        assert results[0]["metadata"]["pathogen"] == "Salmonella spp."


class TestPerFieldFallbackMethods:
    """Tests for query_food_ph() and query_food_water_activity() (Tier 2 fallback methods)."""

    def _make_raw_result(self, document: str, distance: float) -> dict:
        return {
            "document": document,
            "distance": distance,
            "id": "doc_1",
            "metadata": {},
        }

    @pytest.fixture
    def service_with_store(self):
        mock_store = MagicMock()
        return RetrievalService(vector_store=mock_store), mock_store

    def test_query_food_ph_uses_ph_focused_query_text(self, service_with_store):
        """query_food_ph must embed a pH-specific query, not the combined properties query."""
        service, mock_store = service_with_store
        mock_store.query.return_value = []

        service.query_food_ph("raw chicken")

        call_args = mock_store.query.call_args
        query_text = call_args.kwargs.get("query_text") or call_args.args[0]
        assert "raw chicken" in query_text
        assert "pH" in query_text or "ph" in query_text.lower()
        # Must NOT be the combined primary query
        assert "water activity" not in query_text.lower()

    def test_query_food_water_activity_uses_aw_focused_query_text(
        self, service_with_store
    ):
        """query_food_water_activity must embed a water-activity-specific query."""
        service, mock_store = service_with_store
        mock_store.query.return_value = []

        service.query_food_water_activity("raw chicken")

        call_args = mock_store.query.call_args
        query_text = call_args.kwargs.get("query_text") or call_args.args[0]
        assert "raw chicken" in query_text
        assert "water activity" in query_text.lower() or "aw" in query_text.lower()
        # Must NOT be the pH-specific query (which uses "acidity") or the combined primary
        assert "acidity" not in query_text.lower()

    def test_query_food_ph_filters_to_food_properties_doc_type(
        self, service_with_store
    ):
        """Fallback pH query must stay scoped to TYPE_FOOD_PROPERTIES."""
        service, mock_store = service_with_store
        mock_store.query.return_value = []

        service.query_food_ph("chicken")

        call_args = mock_store.query.call_args
        doc_type = call_args.kwargs.get("doc_type") or call_args.args[2]
        assert doc_type == VectorStore.TYPE_FOOD_PROPERTIES

    def test_query_food_water_activity_filters_to_food_properties_doc_type(
        self, service_with_store
    ):
        """Fallback aw query must stay scoped to TYPE_FOOD_PROPERTIES."""
        service, mock_store = service_with_store
        mock_store.query.return_value = []

        service.query_food_water_activity("chicken")

        call_args = mock_store.query.call_args
        doc_type = call_args.kwargs.get("doc_type") or call_args.args[2]
        assert doc_type == VectorStore.TYPE_FOOD_PROPERTIES

    # TODO: flaky against real .env — depends on the live settings singleton,
    # so a local FOOD_PROPERTIES_CONFIDENCE override can collide with the
    # fallback confidence default. Will fix in the future (make it
    # env-independent, e.g. Settings(_env_file=None)).
    # def test_query_food_ph_uses_fallback_threshold_below_primary(self, service_with_store):
    #     """Fallback threshold must be strictly below the primary food_properties_confidence."""
    #     from app.config import settings
    #     service, mock_store = service_with_store
    #     mock_store.query.return_value = []
    #
    #     service.query_food_ph("chicken")
    #
    #     assert settings.food_properties_fallback_confidence < settings.food_properties_confidence

    def test_query_food_ph_has_confident_result_when_above_threshold(
        self, service_with_store
    ):
        """has_confident_result=True when top doc scores above fallback threshold."""
        service, mock_store = service_with_store
        # Distance 0.35 → confidence 0.65 > fallback threshold 0.62
        mock_store.query.return_value = [
            self._make_raw_result("chicken pH 6.2", distance=0.35)
        ]

        response = service.query_food_ph("chicken")

        assert response.has_confident_result is True
        assert response.top_result is not None

    def test_query_food_water_activity_no_confident_result_when_below_threshold(
        self, service_with_store
    ):
        """has_confident_result=False when top doc scores below fallback threshold."""
        service, mock_store = service_with_store
        # Distance 0.45 → confidence 0.55 < fallback threshold 0.62
        mock_store.query.return_value = [
            self._make_raw_result("watercress pH 6.0", distance=0.45)
        ]

        response = service.query_food_water_activity("zarflonite")

        assert response.has_confident_result is False
        assert response.top_result is None


class _MockReranker(BaseReranker):
    """Reranker that inverts embedding order: later documents get higher rerank scores.

    index 0 → score 1.0, index 1 → score 2.0, etc.
    So the last document by embedding order always wins the rerank.
    """

    @property
    def model_name(self) -> str:
        return "mock-reranker"

    def rerank(
        self, _query: str, documents: list[str], top_k: int | None = None
    ) -> list[RerankResult]:
        results = [
            RerankResult(index=i, score=float(i + 1), text=doc)
            for i, doc in enumerate(documents)
        ]
        results.sort(key=lambda r: r.score, reverse=True)
        if top_k is not None:
            results = results[:top_k]
        return results


class TestReranking:
    """Verify reranker wiring: scores surface in results and ordering is authoritative."""

    def _make_raw(self, document: str, distance: float) -> dict:
        return {
            "document": document,
            "distance": distance,
            "id": f"doc_{document[:8]}",
            "metadata": {},
        }

    @pytest.fixture
    def service_with_reranker(self):
        mock_store = MagicMock()
        return (
            RetrievalService(vector_store=mock_store, reranker=_MockReranker()),
            mock_store,
        )

    @pytest.fixture
    def service_no_reranker(self):
        mock_store = MagicMock()
        return RetrievalService(vector_store=mock_store), mock_store

    def test_rerank_score_populated_when_reranker_injected(self, service_with_reranker):
        """rerank_score must be non-null on top_result when a reranker is active."""
        service, mock_store = service_with_reranker
        mock_store.query.return_value = [
            self._make_raw("chicken pH 6.2", distance=0.30),
            self._make_raw("beef pH 5.8", distance=0.35),
        ]

        response = service.query("chicken pH", n_results=2)

        assert response.top_result is not None
        assert response.top_result.rerank_score is not None

    def test_rerank_score_null_when_no_reranker(self, service_no_reranker):
        """rerank_score must be null when no reranker is injected."""
        service, mock_store = service_no_reranker
        mock_store.query.return_value = [
            self._make_raw("chicken pH 6.2", distance=0.30)
        ]

        response = service.query("chicken pH", n_results=1)

        assert response.top_result is not None
        assert response.top_result.rerank_score is None

    def test_reranker_used_populated_when_reranker_active(self, service_with_reranker):
        """reranker_used must report the model name when reranking fires."""
        service, mock_store = service_with_reranker
        mock_store.query.return_value = [
            self._make_raw("chicken pH 6.2", distance=0.30)
        ]

        response = service.query("chicken pH", n_results=1)

        assert response.reranker_used == "mock-reranker"

    def test_reranker_used_null_when_no_reranker(self, service_no_reranker):
        """reranker_used must be null when no reranker is injected."""
        service, mock_store = service_no_reranker
        mock_store.query.return_value = [
            self._make_raw("chicken pH 6.2", distance=0.30)
        ]

        response = service.query("chicken pH", n_results=1)

        assert response.reranker_used is None

    def test_reranker_ordering_overrides_embedding_order(self, service_with_reranker):
        """top_result must reflect reranker ordering, not embedding score order.

        Doc A has better embedding score (distance 0.20) but _MockReranker gives
        higher score to later-indexed docs, so doc B (index 1, score 2.0) beats
        doc A (index 0, score 1.0) despite doc A's better embedding.
        """
        service, mock_store = service_with_reranker
        mock_store.query.return_value = [
            self._make_raw(
                "doc_A content", distance=0.20
            ),  # better embedding, loses rerank
            self._make_raw(
                "doc_B content", distance=0.35
            ),  # worse embedding, wins rerank
        ]

        response = service.query("query", n_results=2)

        assert response.top_result is not None
        assert "doc_B" in response.top_result.content

    def test_runners_up_have_rerank_scores(self, service_with_reranker):
        """All runners-up must carry non-null rerank_scores when reranking fires."""
        service, mock_store = service_with_reranker
        mock_store.query.return_value = [
            self._make_raw("chicken pH 6.2", distance=0.30),
            self._make_raw("poultry pH 6.0", distance=0.33),
            self._make_raw("turkey pH 6.1", distance=0.36),
        ]

        response = service.query("poultry pH", n_results=3)

        assert len(response.results) == 3
        for result in response.results:
            assert result.rerank_score is not None

    def test_reranker_disabled_path_produces_null_scores(self):
        """RERANKER_ENABLED=False path: rerank_score and reranker_used must both be null.

        The production singleton passes reranker=None when disabled, so the NoOpReranker
        branch never fires and the audit does not misleadingly report reranker activity.
        """
        mock_store = MagicMock()
        mock_store.query.return_value = [
            self._make_raw("chicken pH 6.2", distance=0.30)
        ]
        service = RetrievalService(vector_store=mock_store, reranker=None)

        response = service.query("chicken pH", n_results=1)

        assert response.reranker_used is None
        assert response.top_result is not None
        assert response.top_result.rerank_score is None

    def test_threshold_gate_skips_reranker_top_pick_when_below_threshold(
        self, service_with_reranker
    ):
        """Threshold gate walks the reranked list for the first result above threshold.

        _MockReranker gives doc_B (index 1, distance 0.42, confidence 0.58) the higher
        rerank score, making it results[0]. But 0.58 is below the explicit threshold of
        0.65, so the gate skips it and selects doc_A (confidence 0.75) as top_result.
        """
        service, mock_store = service_with_reranker
        mock_store.query.return_value = [
            self._make_raw(
                "doc_A content", distance=0.25
            ),  # confidence 0.75 — above threshold
            self._make_raw(
                "doc_B content", distance=0.42
            ),  # confidence 0.58 — below threshold, wins rerank
        ]

        response = service.query("query", n_results=2, threshold=0.65)

        # doc_B wins rerank (higher rerank score) but fails embedding threshold → skipped
        assert response.top_result is not None
        assert "doc_A" in response.top_result.content
