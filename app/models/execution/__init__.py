"""
Execution models for predictive model engines.

Each engine has its own module with specific models.
Base classes define the common interface.
"""

from app.models.execution.base import (
    BaseExecutionPayload,
    BaseExecutionResult,
    BaseModelResult,
    TimeTemperatureProfile,
    TimeTemperatureStep,
)
from app.models.execution.combase import (
    ComBaseExecutionPayload,
    ComBaseExecutionResult,
    ComBaseModelResult,
    ComBaseModelSelection,
    ComBaseParameters,
)

__all__ = [
    # Base classes
    "BaseExecutionPayload",
    "BaseModelResult",
    "BaseExecutionResult",
    "TimeTemperatureStep",
    "TimeTemperatureProfile",
    # ComBase
    "ComBaseParameters",
    "ComBaseModelSelection",
    "ComBaseExecutionPayload",
    "ComBaseModelResult",
    "ComBaseExecutionResult",
]
