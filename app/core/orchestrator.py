"""
Workflow Orchestrator

Coordinates the full translation pipeline:
1. Intent classification
2. Semantic extraction
3. RAG grounding
4. Standardization
5. Engine execution
"""

from app.config import settings
from app.core.state import SessionState, SessionManager, get_session_manager
from app.models.enums import SessionStatus, IntentType, ModelType
from app.services.extraction.semantic_parser import SemanticParser, get_semantic_parser
from app.services.grounding.grounding_service import GroundingService, get_grounding_service
from app.services.standardization.standardization_service import (
    StandardizationService,
    get_standardization_service,
)
from app.engines.combase.engine import ComBaseEngine, get_combase_engine


class TranslationResult:
    """Result of the translation pipeline."""
    
    def __init__(self, state: SessionState):
        self.state = state
        self.success = state.status == SessionStatus.COMPLETED
        self.error = state.error
    
    @property
    def execution_result(self):
        return self.state.execution_result
    
    @property
    def metadata(self):
        return self.state.metadata


class Orchestrator:
    """
    Orchestrates the full translation pipeline.
    
    Usage:
        orchestrator = Orchestrator()
        result = await orchestrator.translate("Raw chicken left out for 3 hours at 25C")
    """
    
    def __init__(
        self,
        session_manager: SessionManager | None = None,
        semantic_parser: SemanticParser | None = None,
        grounding_service: GroundingService | None = None,
        standardization_service: StandardizationService | None = None,
        combase_engine: ComBaseEngine | None = None,
    ):
        self._sessions = session_manager or get_session_manager()
        self._parser = semantic_parser or get_semantic_parser()
        self._grounder = grounding_service or get_grounding_service()
        self._standardizer = standardization_service or get_standardization_service()
        self._engine = combase_engine or get_combase_engine()
    
    async def translate(
        self,
        user_input: str,
        model_type: ModelType = ModelType.GROWTH,
    ) -> TranslationResult:
        """
        Run the full translation pipeline.
        
        Args:
            user_input: User's natural language input
            model_type: Type of model to run
            
        Returns:
            TranslationResult with execution result and metadata
        """
        # Create session
        state = self._sessions.create_session(user_input)
        
        try:
            # Step 1: Classify intent
            state.update_status(SessionStatus.EXTRACTING)
            await self._classify_intent(state)
            
            if state.intent_type == IntentType.OUT_OF_SCOPE:
                state.set_error("Query is out of scope for food safety predictions")
                return TranslationResult(state)
            
            if state.intent_type == IntentType.INFORMATION_QUERY:
                state.set_error("Information queries not yet implemented")
                return TranslationResult(state)
            
            # Step 2: Extract scenario
            await self._extract_scenario(state)
            
            # Step 3: Ground values via RAG
            grounded = await self._ground_values(state)
            
            # Step 4: Standardize and build payload
            state.update_status(SessionStatus.STANDARDIZING)
            std_result = self._standardizer.standardize(grounded, model_type)
            
            if std_result.missing_required:
                state.set_error(
                    f"Missing required values: {', '.join(std_result.missing_required)}"
                )
                return TranslationResult(state)
            
            state.execution_payload = std_result.payload
            
            # Record corrections in metadata
            if state.metadata:
                for correction in std_result.bias_corrections:
                    state.metadata.add_bias_correction(correction)
                for clamp in std_result.range_clamps:
                    state.metadata.add_range_clamp(clamp)
                state.metadata.warnings.extend(std_result.warnings)
            
            # Step 5: Execute model
            state.update_status(SessionStatus.EXECUTING)
            await self._execute_model(state)
            
            # Complete
            state.update_status(SessionStatus.COMPLETED)
            if state.metadata:
                state.metadata.compute_overall_confidence()
            
            return TranslationResult(state)
            
        except Exception as e:
            state.set_error(str(e))
            return TranslationResult(state)
    
    
    async def _classify_intent(self, state: SessionState) -> None:
        """Classify user intent."""
        state.intent = await self._parser.classify_intent(state.user_input)
        
        if state.intent.is_prediction_request:
            state.intent_type = IntentType.PREDICTION_REQUEST
        elif state.intent.is_information_query:
            state.intent_type = IntentType.INFORMATION_QUERY
        elif state.intent.requires_clarification:
            state.intent_type = IntentType.PREDICTION_REQUEST
        else:
            state.intent_type = IntentType.OUT_OF_SCOPE
    
    async def _extract_scenario(self, state: SessionState) -> None:
        """Extract scenario from user input."""
        state.extracted_scenario = await self._parser.extract_scenario(state.user_input)
    
    async def _ground_values(self, state: SessionState) -> "GroundedValues":
        """Ground extracted values via RAG."""
        grounded = await self._grounder.ground_scenario(state.extracted_scenario)
        
        # Store grounded values and provenance
        state.grounded_values = grounded.values
        
        if state.metadata:
            for field, prov in grounded.provenance.items():
                state.metadata.add_provenance(field, prov)
            for retrieval in grounded.retrievals:
                state.metadata.add_retrieval(retrieval)
        
        return grounded
    
    async def _execute_model(self, state: SessionState) -> None:
        """Execute the ComBase model."""
        if not self._engine.is_available:
            raise RuntimeError("ComBase engine not available")
        
        state.execution_result = await self._engine.execute(state.execution_payload)
        
        # Add execution warnings to metadata
        if state.metadata and state.execution_result:
            state.metadata.warnings.extend(state.execution_result.warnings)


# =============================================================================
# SINGLETON
# =============================================================================

_orchestrator: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    """Get or create the global Orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator


def reset_orchestrator() -> None:
    """Reset the global orchestrator (for testing)."""
    global _orchestrator
    _orchestrator = None