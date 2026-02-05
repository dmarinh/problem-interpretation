"""
Unit tests for health check endpoints.
"""

import pytest
from fastapi.testclient import TestClient


class TestLivenessEndpoint:
    """Tests for GET /health/live"""
    
    def test_liveness_returns_200(self, client: TestClient):
        """Liveness probe should always return 200 if app is running."""
        response = client.get("/health/live")
        
        assert response.status_code == 200
    
    def test_liveness_returns_alive_status(self, client: TestClient):
        """Liveness probe should return status: alive."""
        response = client.get("/health/live")
        data = response.json()
        
        assert data["status"] == "alive"


class TestReadinessEndpoint:
    """Tests for GET /health/ready"""
    
    def test_readiness_returns_200(self, client: TestClient, patch_llm_client):
        """Readiness probe should return 200 when components are healthy."""
        response = client.get("/health/ready")
        
        assert response.status_code == 200
    
    def test_readiness_returns_ready_true(self, client: TestClient, patch_llm_client):
        """Readiness probe should return ready: true when healthy."""
        response = client.get("/health/ready")
        data = response.json()
        
        assert data["ready"] is True
        assert "message" in data


class TestHealthEndpoint:
    """Tests for GET /health"""
    
    def test_health_returns_200(self, client: TestClient, patch_llm_client):
        """Health check should return 200."""
        response = client.get("/health")
        
        assert response.status_code == 200
    
    def test_health_contains_required_fields(self, client: TestClient, patch_llm_client):
        """Health check should contain all required fields."""
        response = client.get("/health")
        data = response.json()
        
        assert "status" in data
        assert "timestamp" in data
        assert "version" in data
        assert "debug" in data
        assert "components" in data
    
    def test_health_contains_components(self, client: TestClient, patch_llm_client):
        """Health check should report status of all components."""
        response = client.get("/health")
        data = response.json()
        
        components = data["components"]
        assert "vector_store" in components
        assert "llm_client" in components
        assert "engine" in components
    
    def test_health_component_structure(self, client: TestClient, patch_llm_client):
        """Each component should have status and message."""
        response = client.get("/health")
        data = response.json()
        
        for name, component in data["components"].items():
            assert "status" in component, f"Component {name} missing status"
            assert component["status"] in ["healthy", "degraded", "unhealthy"]


class TestConfigEndpoint:
    """Tests for GET /health/config"""
    
    def test_config_requires_debug_mode(self, client: TestClient, production_settings):
        """Config endpoint should be restricted in production."""
        response = client.get("/health/config")
        data = response.json()
        
        assert "message" in data
        assert "debug mode" in data["message"].lower()
    
    def test_config_returns_info_in_debug(self, client: TestClient, debug_settings, patch_llm_client):
        """Config endpoint should return info in debug mode."""
        response = client.get("/health/config")
        data = response.json()
        
        assert "app_name" in data
        assert "llm_model" in data
        assert "debug" in data
    
    def test_config_hides_api_key(self, client: TestClient, debug_settings, patch_llm_client):
        """Config endpoint should not expose actual API key."""
        response = client.get("/health/config")
        data = response.json()
        
        # Should only indicate if key is set, not the actual key
        assert "llm_api_key_set" in data
        assert "llm_api_key" not in data