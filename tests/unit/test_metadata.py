"""
Unit tests for metadata models.
"""

import pytest
from datetime import datetime

from app.models.metadata import (
    ValueSource,
    ValueProvenance,
    BiasCorrection,
    RangeClamp,
    RetrievalResult,
    ClarificationRecord,
    InterpretationMetadata,
)
from app.models.enums import (
    BiasType,
    ClarificationReason,
    RetrievalConfidenceLevel,
    SessionStatus,
)


class TestValueProvenance:
    """Tests for ValueProvenance model."""
    
    def test_user_explicit_source(self):
        """Should track user-provided values."""
        prov = ValueProvenance(
            source=ValueSource.USER_EXPLICIT,
            confidence=0.95,
            original_text="about 25 degrees",
        )
        
        assert prov.source == ValueSource.USER_EXPLICIT
        assert prov.confidence == 0.95
    
    def test_rag_retrieval_source(self):
        """Should track RAG-retrieved values."""
        prov = ValueProvenance(
            source=ValueSource.RAG_RETRIEVAL,
            confidence=0.80,
            retrieval_source="food_properties_chunk_42",
        )
        
        assert prov.source == ValueSource.RAG_RETRIEVAL
        assert prov.retrieval_source == "food_properties_chunk_42"
    
    def test_conservative_default(self):
        """Should track conservative defaults."""
        prov = ValueProvenance(
            source=ValueSource.CONSERVATIVE_DEFAULT,
            confidence=0.5,
            transformation_applied="Used default pH=7.0 (neutral)",
        )
        
        assert prov.source == ValueSource.CONSERVATIVE_DEFAULT


class TestBiasCorrection:
    """Tests for BiasCorrection model."""
    
    def test_temperature_correction(self):
        """Should record temperature bias correction."""
        correction = BiasCorrection(
            bias_type=BiasType.OPTIMISTIC_TEMPERATURE,
            field_name="temperature_celsius",
            original_value=20.0,
            corrected_value=25.0,
            correction_reason="User said 'room temperature' - using conservative estimate",
            correction_magnitude=5.0,
        )
        
        assert correction.bias_type == BiasType.OPTIMISTIC_TEMPERATURE
        assert correction.correction_magnitude == 5.0


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
    
    def test_high_confidence_retrieval(self):
        """Should record successful retrieval."""
        result = RetrievalResult(
            query="raw chicken pH water activity",
            confidence_level=RetrievalConfidenceLevel.HIGH,
            confidence_score=0.92,
            source_document="food_properties.json",
            retrieved_text="Raw chicken: pH 5.9-6.2, aw 0.99",
        )
        
        assert result.confidence_level == RetrievalConfidenceLevel.HIGH
        assert result.fallback_used is False
    
    def test_low_confidence_with_fallback(self):
        """Should record fallback usage."""
        result = RetrievalResult(
            query="exotic food pH",
            confidence_level=RetrievalConfidenceLevel.LOW,
            confidence_score=0.45,
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
                confidence=0.9,
            )
        )
        
        assert "temperature_celsius" in meta.provenance
        assert meta.provenance["temperature_celsius"].confidence == 0.9
    
    def test_add_corrections(self):
        """Should track corrections."""
        meta = InterpretationMetadata(
            session_id="test-123",
            original_input="test",
        )
        
        meta.add_bias_correction(BiasCorrection(
            bias_type=BiasType.OPTIMISTIC_TEMPERATURE,
            field_name="temperature_celsius",
            original_value=20.0,
            corrected_value=25.0,
            correction_reason="Conservative estimate",
        ))
        
        meta.add_range_clamp(RangeClamp(
            field_name="ph",
            original_value=3.5,
            clamped_value=4.0,
            valid_min=4.0,
            valid_max=7.5,
            reason="Model constraint",
        ))
        
        assert len(meta.bias_corrections) == 1
        assert len(meta.range_clamps) == 1
    
    def test_compute_overall_confidence(self):
        """Should compute aggregate confidence."""
        meta = InterpretationMetadata(
            session_id="test-123",
            original_input="test",
        )
        
        # Add high confidence provenance
        meta.add_provenance("temp", ValueProvenance(
            source=ValueSource.USER_EXPLICIT,
            confidence=0.95,
        ))
        meta.add_provenance("ph", ValueProvenance(
            source=ValueSource.RAG_RETRIEVAL,
            confidence=0.80,
        ))
        
        # Add a bias correction (5% penalty)
        meta.add_bias_correction(BiasCorrection(
            bias_type=BiasType.OPTIMISTIC_TEMPERATURE,
            field_name="temp",
            original_value=20.0,
            corrected_value=25.0,
            correction_reason="test",
        ))
        
        confidence = meta.compute_overall_confidence()
        
        # min(0.95, 0.80) - 0.05 = 0.75
        assert confidence == 0.75
    
    def test_confidence_with_low_retrieval(self):
        """Should penalize low-confidence retrievals."""
        meta = InterpretationMetadata(
            session_id="test-123",
            original_input="test",
        )
        
        meta.add_provenance("temp", ValueProvenance(
            source=ValueSource.USER_EXPLICIT,
            confidence=0.90,
        ))
        
        meta.add_retrieval(RetrievalResult(
            query="test",
            confidence_level=RetrievalConfidenceLevel.LOW,
            confidence_score=0.4,
            fallback_used=True,
        ))
        
        confidence = meta.compute_overall_confidence()
        
        # 0.90 - 0.10 (low retrieval penalty) = 0.80
        assert confidence == 0.80
    
    def test_confidence_never_negative(self):
        """Confidence should never go below 0."""
        meta = InterpretationMetadata(
            session_id="test-123",
            original_input="test",
        )
        
        meta.add_provenance("temp", ValueProvenance(
            source=ValueSource.CONSERVATIVE_DEFAULT,
            confidence=0.3,
        ))
        
        # Add many corrections
        for i in range(10):
            meta.add_bias_correction(BiasCorrection(
                bias_type=BiasType.MISSING_VALUE_IMPUTED,
                field_name=f"field_{i}",
                original_value=None,
                corrected_value=0.0,
                correction_reason="test",
            ))
        
        confidence = meta.compute_overall_confidence()
        
        assert confidence == 0.0  # Clamped to 0