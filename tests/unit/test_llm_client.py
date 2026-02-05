"""
Unit tests for configuration module.
"""

import pytest
from pathlib import Path


class TestSettings:
    """Tests for Settings class."""
    
    def test_settings_loads_defaults(self):
        """Settings should have sensible defaults."""
        from app.config import Settings
        
        # Create fresh instance (ignores .env)
        s = Settings(_env_file=None)
        
        assert s.app_name == "Problem Interpretation Module"
        assert s.debug is False
        assert s.port == 8000
    
    def test_settings_llm_defaults(self):
        """LLM settings should have defaults."""
        from app.config import Settings
        
        s = Settings(_env_file=None)
        
        assert s.llm_model == "gpt-4-turbo-preview"
        assert s.llm_temperature == 0.1
        assert s.llm_max_tokens == 4096
    
    def test_settings_confidence_thresholds(self):
        """Confidence thresholds should be between 0 and 1."""
        from app.config import Settings
        
        s = Settings(_env_file=None)
        
        assert 0.0 <= s.global_min_confidence <= 1.0
        assert 0.0 <= s.food_properties_confidence <= 1.0
        assert 0.0 <= s.pathogen_hazards_confidence <= 1.0
    
    def test_settings_conservative_defaults(self):
        """Conservative defaults should be set."""
        from app.config import Settings
        
        s = Settings(_env_file=None)
        
        assert s.default_temperature_abuse_c == 25.0
        assert s.default_ph_neutral == 7.0
        assert s.default_water_activity == 0.99
    
    def test_settings_path_conversion(self):
        """Path settings should be converted to Path objects."""
        from app.config import Settings
        
        s = Settings(_env_file=None)
        
        assert isinstance(s.vector_store_path, Path)
        assert isinstance(s.constraint_cache_path, Path)


class TestSettingsValidation:
    """Tests for settings validation."""
    
    def test_temperature_bounds(self):
        """LLM temperature should be bounded."""
        from app.config import Settings
        
        # Valid temperature
        s = Settings(llm_temperature=0.5, _env_file=None)
        assert s.llm_temperature == 0.5
    
    def test_invalid_temperature_rejected(self):
        """Invalid temperature should raise error."""
        from app.config import Settings
        from pydantic import ValidationError
        
        with pytest.raises(ValidationError):
            Settings(llm_temperature=3.0, _env_file=None)
    
    def test_confidence_bounds(self):
        """Confidence thresholds should be bounded 0-1."""
        from app.config import Settings
        from pydantic import ValidationError
        
        with pytest.raises(ValidationError):
            Settings(global_min_confidence=1.5, _env_file=None)