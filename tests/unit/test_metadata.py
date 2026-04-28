"""
Unit tests for metadata models.
"""

import pytest
from datetime import datetime

from app.models.metadata import (
    ValueSource,
    ValueProvenance,
    DefaultImputed,
    RangeClamp,
    RetrievalResult,
    ClarificationRecord,
    InterpretationMetadata,
)
from app.models.enums import (
    ClarificationReason,
    SessionStatus,
)


class TestValueProvenance:
    """Tests for ValueProvenance model."""

    def test_user_explicit_source(self):
        """Should track user-provided values."""
        prov = ValueProvenance(
            source=ValueSource.USER_EXPLICIT,
            original_text="about 25 degrees",
        )

        assert prov.source == ValueSource.USER_EXPLICIT

    def test_rag_retrieval_source(self):
        """Should track RAG-retrieved values."""
        prov = ValueProvenance(
            source=ValueSource.RAG_RETRIEVAL,
            retrieval_source="food_properties_chunk_42",
        )

        assert prov.source == ValueSource.RAG_RETRIEVAL
        assert prov.retrieval_source == "food_properties_chunk_42"

    def test_conservative_default(self):
        """Should track conservative defaults."""
        prov = ValueProvenance(
            source=ValueSource.CONSERVATIVE_DEFAULT,
            transformation_applied="Used default pH=7.0 (neutral)",
        )

        assert prov.source == ValueSource.CONSERVATIVE_DEFAULT


class TestDefaultImputed:
    """Tests for DefaultImputed model."""

    def test_default_imputed_record(self):
        """Should record a conservative default substitution."""
        default = DefaultImputed(
            field_name="temperature_celsius",
            imputed_value=25.0,
            reason="No temperature specified. Using conservative abuse temperature (25°C).",
        )

        assert default.field_name == "temperature_celsius"
        assert default.imputed_value == 25.0
        assert default.original_value is None

    def test_default_imputed_ph(self):
        """Should record pH default."""
        default = DefaultImputed(
            field_name="ph",
            imputed_value=7.0,
            reason="No pH specified. Using neutral default.",
        )

        assert default.imputed_value == 7.0


class TestRangeClamp:
    """Tests for RangeClamp model."""

    def test_clamp_record(self):
        """Should record range clamping."""
        clamp = RangeClamp(
            field_name="ph",
            original_value=3.5,
            clamped_value=4.0,
            valid_min=4.0,
            valid_max=7.5,
            reason="Listeria model valid range",
        )

        assert clamp.original_value == 3.5
        assert clamp.clamped_value == 4.0


class TestRetrievalResult:
    """Tests for RetrievalResult model."""

    def test_retrieval_with_embedding_score(self):
        """Should record retrieval with embedding score."""
        result = RetrievalResult(
            query="raw chicken pH water activity",
            source_document="food_properties.json",
            retrieved_text="Raw chicken: pH 5.9-6.2, aw 0.99",
            embedding_score=0.92,
        )

        assert result.embedding_score == 0.92
        assert result.fallback_used is False

    def test_retrieval_fallback(self):
        """Should record fallback usage."""
        result = RetrievalResult(
            query="exotic food pH",
            fallback_used=True,
        )

        assert result.fallback_used is True


class TestInterpretationMetadata:
    """Tests for InterpretationMetadata model."""

    def test_create_session(self):
        """Should create metadata session."""
        meta = InterpretationMetadata(
            session_id="test-123",
            original_input="Raw chicken left out for 3 hours",
        )

        assert meta.session_id == "test-123"
        assert meta.status == SessionStatus.PENDING
        assert isinstance(meta.created_at, datetime)

    def test_add_provenance(self):
        """Should add field provenance."""
        meta = InterpretationMetadata(
            session_id="test-123",
            original_input="test",
        )

        meta.add_provenance(
            "temperature_celsius",
            ValueProvenance(
                source=ValueSource.USER_EXPLICIT,
            )
        )

        assert "temperature_celsius" in meta.provenance
        assert meta.provenance["temperature_celsius"].source == ValueSource.USER_EXPLICIT

    def test_add_default_imputed(self):
        """Should track defaults imputed and range clamps."""
        meta = InterpretationMetadata(
            session_id="test-123",
            original_input="test",
        )

        meta.add_default_imputed(DefaultImputed(
            field_name="temperature_celsius",
            imputed_value=25.0,
            reason="No temperature specified. Using conservative abuse temperature (25°C).",
        ))

        meta.add_range_clamp(RangeClamp(
            field_name="ph",
            original_value=3.5,
            clamped_value=4.0,
            valid_min=4.0,
            valid_max=7.5,
            reason="Model constraint",
        ))

        assert len(meta.defaults_imputed) == 1
        assert len(meta.range_clamps) == 1
