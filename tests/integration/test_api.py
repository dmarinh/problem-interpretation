"""
Integration tests for API endpoints.
"""

import pytest
from httpx import AsyncClient


class TestAPIIntegration:
    """Integration tests for the full API."""
    
    @pytest.mark.asyncio
    async def test_full_health_check_flow(self, async_client: AsyncClient, patch_llm_client):
        """Test complete health check flow."""
        # Check liveness
        live_response = await async_client.get("/health/live")
        assert live_response.status_code == 200
        
        # Check readiness
        ready_response = await async_client.get("/health/ready")
        assert ready_response.status_code == 200
        
        # Check full health
        health_response = await async_client.get("/health")
        assert health_response.status_code == 200
        
        health_data = health_response.json()
        assert health_data["status"] in ["healthy", "degraded", "unhealthy"]
    
    @pytest.mark.asyncio
    async def test_openapi_schema_available(self, async_client: AsyncClient):
        """OpenAPI schema should be accessible."""
        response = await async_client.get("/openapi.json")
        
        assert response.status_code == 200
        data = response.json()
        assert "openapi" in data
        assert "paths" in data
    
    @pytest.mark.asyncio
    async def test_docs_available(self, async_client: AsyncClient):
        """Swagger docs should be accessible."""
        response = await async_client.get("/docs")
        
        assert response.status_code == 200