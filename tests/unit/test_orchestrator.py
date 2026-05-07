"""
Unit tests for workflow orchestrator.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from app.core.orchestrator import Orchestrator, TranslationResult, _missing_key_to_audit_key
from app.core.state import SessionState, SessionManager
from app.models.enums import SessionStatus, IntentType, ModelType, ComBaseOrganism
from app.models.extraction import (
    ExtractedScenario,
    ExtractedIntent,
    ExtractedTemperature,
    ExtractedDuration,
)
from app.services.grounding.grounding_service import GroundedValues
from app.models.metadata import ValueSource, ValueProvenance


@pytest.fixture
def mock_parser():
    """Create mock semantic parser."""
    parser = MagicMock()
    parser.classify_intent = AsyncMock(return_value=ExtractedIntent(
        is_prediction_request=True,
        is_information_query=False,
        confidence=0.95,
    ))
    parser.extract_scenario = AsyncMock(return_value=ExtractedScenario(
        food_description="raw chicken",
        single_step_temperature=ExtractedTemperature(value_celsius=25.0),
        single_step_duration=ExtractedDuration(value_minutes=180.0),
    ))
    return parser


@pytest.fixture
def mock_grounder():
    """Create mock grounding service."""
    grounder = MagicMock()
    
    async def mock_ground(scenario):
        grounded = GroundedValues()
        grounded.set("temperature_celsius", 25.0, ValueSource.USER_EXPLICIT)
        grounded.set("duration_minutes", 180.0, ValueSource.USER_EXPLICIT)
        grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.RAG_RETRIEVAL)
        grounded.set("ph", 6.0, ValueSource.RAG_RETRIEVAL)
        grounded.set("water_activity", 0.99, ValueSource.RAG_RETRIEVAL)
        return grounded
    
    grounder.ground_scenario = mock_ground
    return grounder


@pytest.fixture
def mock_engine():
    """Create mock ComBase engine."""
    from app.models.execution.combase import ComBaseExecutionResult, ComBaseModelResult
    from app.models.enums import EngineType
    
    engine = MagicMock()
    engine.is_available = True
    engine.execute = AsyncMock(return_value=ComBaseExecutionResult(
        model_result=ComBaseModelResult(
            mu_max=0.5,
            doubling_time_hours=1.4,
            model_type=ModelType.GROWTH,
            organism=ComBaseOrganism.SALMONELLA,
            temperature_used=25.0,
            ph_used=6.0,
            aw_used=0.99,
        ),
        step_predictions=[],
        total_log_increase=0.65,
        engine_type=EngineType.COMBASE_LOCAL,
        warnings=[],
    ))
    return engine


@pytest.fixture
def orchestrator(mock_parser, mock_grounder, mock_engine):
    """Create orchestrator with mocks."""
    return Orchestrator(
        session_manager=SessionManager(),
        semantic_parser=mock_parser,
        grounding_service=mock_grounder,
        standardization_service=None,  # Use real standardizer
        combase_engine=mock_engine,
    )


class TestOrchestrator:
    """Tests for Orchestrator."""
    
    @pytest.mark.asyncio
    async def test_successful_interpretation(self, orchestrator):
        """Should complete full pipeline successfully."""
        result = await orchestrator.translate(
            "Raw chicken left out for 3 hours at 25C"
        )
        
        assert result.success is True
        assert result.state.status == SessionStatus.COMPLETED
        assert result.execution_result is not None
        assert result.execution_result.model_result.mu_max > 0
    
    @pytest.mark.asyncio
    async def test_creates_session(self, orchestrator):
        """Should create a session."""
        result = await orchestrator.translate("Test input")
        
        assert result.state.session_id is not None
        assert result.state.user_input == "Test input"
    
    @pytest.mark.asyncio
    async def test_extracts_scenario(self, orchestrator, mock_parser):
        """Should extract scenario from input."""
        result = await orchestrator.translate("Raw chicken at 25C for 3 hours")
        
        mock_parser.extract_scenario.assert_called_once()
        assert result.state.extracted_scenario is not None
    
    @pytest.mark.asyncio
    async def test_grounds_values(self, orchestrator, mock_grounder):
        """Should ground values via RAG."""
        result = await orchestrator.translate("Raw chicken at 25C for 3 hours")
        
        assert result.state.grounded_values is not None
        assert "temperature_celsius" in result.state.grounded_values
    
    @pytest.mark.asyncio
    async def test_builds_execution_payload(self, orchestrator):
        """Should build execution payload."""
        result = await orchestrator.translate("Raw chicken at 25C for 3 hours")
        
        assert result.state.execution_payload is not None
        assert result.state.execution_payload.parameters.temperature_celsius == 25.0
    
    @pytest.mark.asyncio
    async def test_tracks_metadata(self, orchestrator):
        """Should track provenance metadata."""
        result = await orchestrator.translate("Raw chicken at 25C for 3 hours")
        
        assert result.metadata is not None
        assert len(result.metadata.provenance) > 0
    
    @pytest.mark.asyncio
    async def test_out_of_scope_fails(self, orchestrator, mock_parser):
        """Should fail for out-of-scope queries."""
        mock_parser.classify_intent = AsyncMock(return_value=ExtractedIntent(
            is_prediction_request=False,
            is_information_query=False,
            confidence=0.9,
        ))
        
        result = await orchestrator.translate("What is the meaning of life?")
        
        assert result.success is False
        assert "out of scope" in result.error.lower()
    
    @pytest.mark.asyncio
    async def test_engine_not_available(self, orchestrator, mock_engine):
        """Should fail if engine not available."""
        mock_engine.is_available = False
        
        result = await orchestrator.translate("Raw chicken at 25C for 3 hours")
        
        assert result.success is False
        assert "not available" in result.error.lower()


class TestMissingKeyToAuditKey:
    """Unit tests for the _missing_key_to_audit_key helper."""

    def test_single_step_duration(self):
        assert _missing_key_to_audit_key("duration") == "duration_minutes"

    def test_multi_step_duration(self):
        assert _missing_key_to_audit_key("duration (step 1)") == "duration_minutes (step 1)"
        assert _missing_key_to_audit_key("duration (step 3)") == "duration_minutes (step 3)"

    def test_single_step_temperature(self):
        assert _missing_key_to_audit_key("temperature") == "temperature_celsius"

    def test_organism_explicit_branch(self):
        assert _missing_key_to_audit_key("organism") == "organism"

    def test_unknown_field_passthrough(self, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger="app.core.orchestrator"):
            result = _missing_key_to_audit_key("some_other_field")
        assert result == "some_other_field"
        assert "unrecognised field spec" in caplog.text


class TestValidationFailureAuditCompleteness:
    """
    Verify that when standardization fails with missing_required, the
    orchestrator still populates metadata completely so _build_field_audit
    can produce a useful audit trail.

    Uses the real StandardizationService (no registry — defaults/missing only)
    and a mock grounder that returns a multi-step GroundedValues where step 1
    has a resolved temperature but no duration.
    """

    @pytest.fixture
    def mock_parser_multistep(self):
        from app.models.extraction import ExtractedEnvironmentalConditions
        parser = MagicMock()
        parser.classify_intent = AsyncMock(return_value=ExtractedIntent(
            is_prediction_request=True,
            is_information_query=False,
            confidence=0.95,
        ))
        parser.extract_scenario = AsyncMock(return_value=ExtractedScenario(
            food_description="ground beef",
            is_multi_step=True,
            single_step_temperature=ExtractedTemperature(),
            single_step_duration=ExtractedDuration(),
            time_temperature_steps=[],
            environmental_conditions=ExtractedEnvironmentalConditions(),
        ))
        return parser

    @pytest.fixture
    def mock_grounder_missing_duration(self):
        """
        Returns GroundedValues for a 2-step scenario where step 1 has a
        resolved temperature (room temperature → 25°C) but no duration.
        Step 2 is omitted to keep the fixture minimal.
        """
        grounder = MagicMock()

        async def _ground(_scenario):
            grounded = GroundedValues()
            grounded.set("organism", ComBaseOrganism.SALMONELLA, ValueSource.RAG_RETRIEVAL)
            grounded.add_step(
                step_order=1,
                temperature_celsius=25.0,
                duration_minutes=None,
                temp_provenance=ValueProvenance(
                    source=ValueSource.USER_INFERRED,
                    extraction_method="rule_match",
                    matched_pattern="room temperature",
                ),
                dur_provenance=None,  # grounding returned (None, None) for duration
            )
            return grounded

        grounder.ground_scenario = _ground
        return grounder

    @pytest.fixture
    def orchestrator_for_failure(self, mock_parser_multistep, mock_grounder_missing_duration, mock_engine):
        return Orchestrator(
            session_manager=SessionManager(),
            semantic_parser=mock_parser_multistep,
            grounding_service=mock_grounder_missing_duration,
            standardization_service=None,  # real standardizer, no registry
            combase_engine=mock_engine,
        )

    @pytest.mark.asyncio
    async def test_failure_result_is_failed(self, orchestrator_for_failure):
        result = await orchestrator_for_failure.translate("A2-style multi-step query")
        assert result.success is False
        assert result.state.status == SessionStatus.FAILED

    @pytest.mark.asyncio
    async def test_error_names_missing_field(self, orchestrator_for_failure):
        result = await orchestrator_for_failure.translate("A2-style multi-step query")
        assert "duration" in result.error.lower()
        assert "step 1" in result.error.lower()

    @pytest.mark.asyncio
    async def test_organism_in_provenance(self, orchestrator_for_failure):
        result = await orchestrator_for_failure.translate("A2-style multi-step query")
        assert result.metadata is not None
        assert "organism" in result.metadata.provenance

    @pytest.mark.asyncio
    async def test_step_temperature_bridged_to_provenance(self, orchestrator_for_failure):
        """Per-step temperature provenance must be visible in metadata after grounding."""
        result = await orchestrator_for_failure.translate("A2-style multi-step query")
        assert "temperature_celsius (step 1)" in result.metadata.provenance
        prov = result.metadata.provenance["temperature_celsius (step 1)"]
        assert prov.source == ValueSource.USER_INFERRED

    @pytest.mark.asyncio
    async def test_missing_duration_appears_with_null_source(self, orchestrator_for_failure):
        """The missing duration must appear in provenance with source=MISSING."""
        result = await orchestrator_for_failure.translate("A2-style multi-step query")
        assert "duration_minutes (step 1)" in result.metadata.provenance
        prov = result.metadata.provenance["duration_minutes (step 1)"]
        assert prov.source == ValueSource.MISSING

    @pytest.mark.asyncio
    async def test_defaults_imputed_populated_on_failure(self, orchestrator_for_failure):
        """Defaults imputed before the failure point must appear in metadata."""
        result = await orchestrator_for_failure.translate("A2-style multi-step query")
        imputed_fields = {d.field_name for d in result.metadata.defaults_imputed}
        # ph and water_activity are always defaulted when not grounded
        assert "ph" in imputed_fields
        assert "water_activity" in imputed_fields

    @pytest.mark.asyncio
    async def test_structured_warning_names_missing_field(self, orchestrator_for_failure):
        """audit.warnings must contain a structured message naming the missing field."""
        result = await orchestrator_for_failure.translate("A2-style multi-step query")
        warning_text = " ".join(result.metadata.warnings)
        assert "Validation failed" in warning_text
        assert "duration (step 1)" in warning_text

    @pytest.mark.asyncio
    async def test_prediction_is_null_on_failure(self, orchestrator_for_failure):
        result = await orchestrator_for_failure.translate("A2-style multi-step query")
        assert result.execution_result is None