"""
Session State Management

Tracks the state of an interpretation session through the pipeline.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import SessionStatus, IntentType
from app.models.extraction import ExtractedScenario, ExtractedIntent
from app.models.execution.combase import ComBaseExecutionPayload, ComBaseExecutionResult
from app.models.metadata import InterpretationMetadata, ValueProvenance


class SessionState(BaseModel):
    """
    Complete state of an interpretation session.
    
    Tracks progress through the pipeline and holds intermediate results.
    """
    # Identity
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Status
    status: SessionStatus = Field(default=SessionStatus.PENDING)
    
    # Original input
    user_input: str = Field(description="Original user input")
    
    # Intent classification
    intent: ExtractedIntent | None = Field(default=None)
    intent_type: IntentType | None = Field(default=None)
    
    # Extraction results
    extracted_scenario: ExtractedScenario | None = Field(default=None)
    
    # Grounded values (after RAG)
    grounded_values: dict = Field(
        default_factory=dict,
        description="Values grounded via RAG retrieval"
    )
    
    # Execution payload (after standardization)
    execution_payload: ComBaseExecutionPayload | None = Field(default=None)
    
    # Execution result
    execution_result: ComBaseExecutionResult | None = Field(default=None)
    
    # Metadata and provenance
    metadata: InterpretationMetadata | None = Field(default=None)
    
    # Clarification state
    clarification_count: int = Field(default=0)
    pending_clarifications: list[str] = Field(default_factory=list)
    
    # Errors
    error: str | None = Field(default=None)
    
    def update_status(self, status: SessionStatus) -> None:
        """Update session status and timestamp."""
        self.status = status
        self.updated_at = datetime.utcnow()
    
    def set_error(self, error: str) -> None:
        """Set error and mark as failed."""
        self.error = error
        self.update_status(SessionStatus.FAILED)
    
    def initialize_metadata(self) -> None:
        """Initialize metadata tracking."""
        self.metadata = InterpretationMetadata(
            session_id=self.session_id,
            original_input=self.user_input,
            status=self.status,
        )
    
    def add_provenance(self, field: str, provenance: ValueProvenance) -> None:
        """Add provenance for a grounded value."""
        if self.metadata:
            self.metadata.add_provenance(field, provenance)


class SessionManager:
    """
    Manages active interpretation sessions.
    
    Simple in-memory storage for now.
    """
    
    def __init__(self):
        self._sessions: dict[str, SessionState] = {}
    
    def create_session(self, user_input: str) -> SessionState:
        """Create a new session."""
        state = SessionState(user_input=user_input)
        state.initialize_metadata()
        self._sessions[state.session_id] = state
        return state
    
    def get_session(self, session_id: str) -> SessionState | None:
        """Get a session by ID."""
        return self._sessions.get(session_id)
    
    def update_session(self, state: SessionState) -> None:
        """Update a session."""
        state.updated_at = datetime.utcnow()
        self._sessions[state.session_id] = state
    
    def delete_session(self, session_id: str) -> None:
        """Delete a session."""
        self._sessions.pop(session_id, None)
    
    def list_sessions(self) -> list[SessionState]:
        """List all sessions."""
        return list(self._sessions.values())


# =============================================================================
# SINGLETON
# =============================================================================

_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:
    """Get or create the global SessionManager instance."""
    global _manager
    if _manager is None:
        _manager = SessionManager()
    return _manager


def reset_session_manager() -> None:
    """Reset the global manager (for testing)."""
    global _manager
    _manager = None