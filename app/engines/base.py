"""
Base Engine Interface

Abstract interface that all predictive model engines must implement.
Allows swapping between local and API implementations.
"""

from abc import ABC, abstractmethod

from app.models.execution.base import BaseExecutionPayload, BaseExecutionResult


class BaseEngine(ABC):
    """
    Abstract base class for predictive model engines.
    
    All engines (ComBase local, ComBase API, future engines) must implement this interface.
    """
    
    @property
    @abstractmethod
    def engine_name(self) -> str:
        """Human-readable engine name."""
        pass
    
    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Whether the engine is currently available."""
        pass
    
    @abstractmethod
    async def execute(self, payload: BaseExecutionPayload) -> BaseExecutionResult:
        """
        Execute a prediction.
        
        Args:
            payload: Engine-specific execution payload
            
        Returns:
            Execution result with predictions
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> dict:
        """
        Check engine health/availability.
        
        Returns:
            Dict with 'healthy' bool and 'message' str
        """
        pass