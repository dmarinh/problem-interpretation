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
from app.models.metadata import ComBaseModelAudit, SystemAudit
from app.services.audit.system import build_system_audit
from app.services.extraction.semantic_parser import SemanticParser, get_semantic_parser
from app.services.grounding.grounding_service import (
    GroundedValues,
    GroundingService,
    get_grounding_service,
)
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
        model_type: ModelType | None = None,
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

            # Step 3: Determine model type. Model type should have been extracted in step 2 by the LLM.
            # However, we determine it here with rules as a fallback, and we make sure that model type is
            # in any case set to the explicit model type if that was provided (overriding the LLM's decision).
            effective_model_type, model_type_reason = self._determine_model_type(
                model_type,
                state.extracted_scenario,
            )

            # Step 4: Ground values via RAG
            grounded = await self._ground_values(state)

            # Step 5: Standardize and build payload
            state.update_status(SessionStatus.STANDARDIZING)
            std_result = self._standardizer.standardize(grounded, effective_model_type)

            if std_result.missing_required:
                state.set_error(
                    f"Missing required values: {', '.join(std_result.missing_required)}"
                )
                return TranslationResult(state)

            if std_result.payload is None:
                error_detail = "; ".join(std_result.warnings) if std_result.warnings else "Failed to build execution payload"
                state.set_error(error_detail)
                return TranslationResult(state)

            state.execution_payload = std_result.payload

            # Record defaults and range clamps in metadata
            if state.metadata:
                state.metadata.defaults_imputed.extend(std_result.defaults_imputed)
                for clamp in std_result.range_clamps:
                    state.metadata.add_range_clamp(clamp)
                state.metadata.warnings.extend(std_result.warnings)

            # Step 6: Execute model
            state.update_status(SessionStatus.EXECUTING)
            await self._execute_model(state)

            # Record ComBase model selection audit after execution (organism known now)
            if state.metadata and state.execution_payload:
                self._record_combase_model_audit(state, effective_model_type, model_type_reason)

            # Complete
            state.update_status(SessionStatus.COMPLETED)
            if state.metadata:
                sys_audit_data = build_system_audit()
                manifest_missing = sys_audit_data.pop("manifest_missing", False)
                state.metadata.system = SystemAudit(**sys_audit_data)
                if manifest_missing:
                    state.metadata.warnings.append(
                        "RAG manifest missing — store provenance unknown"
                    )
            
            return TranslationResult(state)
            
        except Exception as e:
            state.set_error(str(e))
            return TranslationResult(state)
    
    def _determine_model_type(
        self,
        explicit_type: ModelType | None,
        scenario,
    ) -> tuple[ModelType, str]:
        """
        Determine model type from explicit parameter or scenario inference.

        Returns (model_type, selection_reason) so the orchestrator can record
        the rationale in InterpretationMetadata for audit traceability.

        Priority:
        1. Explicit parameter (if provided)
        2. LLM-extracted inference (implied_model_type)
        3. Temperature heuristic (>50°C → thermal inactivation)
        4. Scenario flags (is_cooking_scenario, is_non_thermal_treatment)
        5. Environmental conditions (low pH / low aw / preservatives)
        6. Default to Growth

        Model types:
        - GROWTH: Bacterial multiplication during storage/holding
        - THERMAL_INACTIVATION: Pathogen death from heat treatment
        - NON_THERMAL_SURVIVAL: Pathogen survival under non-thermal stress
        """
        if explicit_type is not None:
            return explicit_type, "explicit model_type parameter override"

        if scenario.implied_model_type is not None:
            return scenario.implied_model_type, "LLM inference (implied_model_type field)"

        temp = scenario.single_step_temperature
        if temp.value_celsius is not None and temp.value_celsius > 50:
            return (
                ModelType.THERMAL_INACTIVATION,
                f"temperature heuristic ({temp.value_celsius}°C > 50°C → thermal inactivation)",
            )

        if scenario.is_cooking_scenario:
            return ModelType.THERMAL_INACTIVATION, "scenario flag: is_cooking_scenario"

        if scenario.is_non_thermal_treatment:
            return ModelType.NON_THERMAL_SURVIVAL, "scenario flag: is_non_thermal_treatment"

        env = scenario.environmental_conditions
        if env.ph_value is not None and env.ph_value < 4.5:
            return (
                ModelType.NON_THERMAL_SURVIVAL,
                f"environmental condition: pH {env.ph_value} < 4.5",
            )
        if env.water_activity is not None and env.water_activity < 0.90:
            return (
                ModelType.NON_THERMAL_SURVIVAL,
                f"environmental condition: aw {env.water_activity} < 0.90",
            )
        if env.nitrite_ppm is not None or env.lactic_acid_ppm is not None or env.acetic_acid_ppm is not None:
            return ModelType.NON_THERMAL_SURVIVAL, "environmental condition: preservative detected"

        return ModelType.GROWTH, "default (no thermal/non-thermal signals detected)"

    def _record_combase_model_audit(
        self,
        state: "SessionState",
        model_type: ModelType,
        selection_reason: str,
    ) -> None:
        """
        Populate InterpretationMetadata.combase_model after engine execution.

        The organism is read from the execution payload (already resolved by
        grounding + standardization).  Model coefficients and valid ranges are
        fetched from the registry — the same lookup the engine used, so there
        is no risk of mismatch.
        """
        if not state.metadata or not state.execution_payload:
            return

        sel = state.execution_payload.model_selection
        model = self._engine.registry.get_model(
            organism=sel.organism,
            model_type=sel.model_type,
            factor4_type=sel.factor4_type,
        )

        coefficients_str: str | None = None
        valid_ranges: dict | None = None
        model_id: int | None = None

        if model:
            model_id = model.model_id
            coefficients_str = ";".join(f"{c:.6g}" for c in model.coefficients)
            c = model.constraints
            valid_ranges = {
                "temperature_celsius": (c.temp_min, c.temp_max),
                "ph": (c.ph_min, c.ph_max),
                "water_activity": (c.aw_min, c.aw_max),
            }

        state.metadata.combase_model = ComBaseModelAudit(
            organism=sel.organism.name,
            organism_id=sel.organism.value,
            organism_display_name=(
                model.organism_name
                if model and isinstance(model.organism_name, str)
                else None
            ),
            model_type=model_type.value,
            model_id=model_id,
            coefficients_str=coefficients_str,
            valid_ranges=valid_ranges,
            selection_reason=selection_reason,
        )

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