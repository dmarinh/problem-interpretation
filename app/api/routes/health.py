"""
Health Check Endpoints

Provides endpoints for monitoring application health and readiness.
"""

from datetime import datetime, timezone
from enum import Enum
import time

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app import __version__
from app.config import settings


router = APIRouter(prefix="/health")


class ServiceStatus(str, Enum):
    """Status of individual services."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ComponentHealth(BaseModel):
    """Health status of an individual component."""
    status: ServiceStatus
    message: str | None = None
    latency_ms: float | None = None


class HealthResponse(BaseModel):
    """Comprehensive health check response."""
    status: ServiceStatus = Field(description="Overall application status")
    timestamp: datetime = Field(description="Time of health check")
    version: str = Field(description="Application version")
    debug: bool = Field(description="Debug mode status")
    components: dict[str, ComponentHealth] = Field(
        default_factory=dict,
        description="Health status of individual components"
    )


class ReadinessResponse(BaseModel):
    """Readiness probe response."""
    ready: bool
    message: str


async def check_components() -> dict[str, ComponentHealth]:
    """Check health of all critical components."""
    from app.services.llm.client import get_llm_client
    
    components = {}
    
    # Vector store check (placeholder)
    components["vector_store"] = ComponentHealth(
        status=ServiceStatus.HEALTHY,
        message="Not yet implemented"
    )
    
    # LLM client check
    try:
        start = time.perf_counter()
        client = get_llm_client()
        health = await client.health_check()
        latency = (time.perf_counter() - start) * 1000
        
        components["llm_client"] = ComponentHealth(
            status=ServiceStatus.HEALTHY if health["healthy"] else ServiceStatus.DEGRADED,
            message=health.get("message"),
            latency_ms=round(latency, 2),
        )
    except Exception as e:
        components["llm_client"] = ComponentHealth(
            status=ServiceStatus.UNHEALTHY,
            message=f"Error: {str(e)}",
        )
    
    # Engine check (placeholder)
    components["engine"] = ComponentHealth(
        status=ServiceStatus.HEALTHY,
        message=f"ComBase URL: {settings.combase_api_url or 'Not configured'}"
    )
    
    return components


def determine_overall_status(components: dict[str, ComponentHealth]) -> ServiceStatus:
    """Determine overall status from component statuses."""
    statuses = [c.status for c in components.values()]
    
    if all(s == ServiceStatus.HEALTHY for s in statuses):
        return ServiceStatus.HEALTHY
    elif any(s == ServiceStatus.UNHEALTHY for s in statuses):
        return ServiceStatus.UNHEALTHY
    else:
        return ServiceStatus.DEGRADED


@router.get(
    "",
    response_model=HealthResponse,
    summary="Health Check",
    description="Returns the health status of the application and its components."
)
async def health_check() -> HealthResponse:
    """Comprehensive health check endpoint."""
    components = await check_components()
    overall_status = determine_overall_status(components)
    
    return HealthResponse(
        status=overall_status,
        timestamp=datetime.now(timezone.utc),
        version=__version__,
        debug=settings.debug,
        components=components
    )


@router.get(
    "/live",
    summary="Liveness Probe",
    description="Simple liveness check - returns 200 if application is running."
)
async def liveness() -> dict[str, str]:
    """Liveness probe endpoint."""
    return {"status": "alive"}


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness Probe",
    description="Checks if application is ready to serve traffic."
)
async def readiness() -> ReadinessResponse:
    """Readiness probe endpoint."""
    components = await check_components()
    
    critical_healthy = all(
        c.status != ServiceStatus.UNHEALTHY 
        for c in components.values()
    )
    
    if critical_healthy:
        return ReadinessResponse(ready=True, message="All components ready")
    else:
        unhealthy = [
            name for name, c in components.items() 
            if c.status == ServiceStatus.UNHEALTHY
        ]
        return ReadinessResponse(
            ready=False, 
            message=f"Unhealthy components: {', '.join(unhealthy)}"
        )


@router.get(
    "/config",
    summary="Configuration Info",
    description="Returns non-sensitive configuration (debug mode only)."
)
async def config_info() -> dict:
    """Returns current configuration (debug mode only)."""
    if not settings.debug:
        return {"message": "Config info only available in debug mode"}
    
    return {
        "app_name": settings.app_name,
        "debug": settings.debug,
        "log_level": settings.log_level.value,
        "llm_model": settings.llm_model,
        "llm_api_key_set": settings.llm_api_key is not None,
        "embedding_model": settings.embedding_model,
        "vector_store_path": str(settings.vector_store_path),
        "global_min_confidence": settings.global_min_confidence,
        "max_clarification_turns": settings.max_clarification_turns,
        "combase_api_url": settings.combase_api_url or "Not configured",
        "constraint_cache_ttl_seconds": settings.constraint_cache_ttl_seconds,
    }