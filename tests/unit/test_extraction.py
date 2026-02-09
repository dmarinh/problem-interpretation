"""
Unit tests for extraction models.
"""

import pytest
from app.models.extraction import (
    ExtractedTemperature,
    ExtractedDuration,
    ExtractedTimeTemperatureStep,
    ExtractedEnvironmentalConditions,
    ExtractedScenario,
    ExtractedIntent,
)




class TestExtractedTemperature:
    """Tests for ExtractedTemperature model."""
    
    def test_default_values(self):
        """Should have sensible defaults."""
        temp = ExtractedTemperature()
        
        assert temp.value_celsius is None
        assert temp.description is None
        assert temp.is_range is False
    
    def test_explicit_value(self):
        """Should accept explicit temperature."""
        temp = ExtractedTemperature(value_celsius=25.0, description="room temperature")
        
        assert temp.value_celsius == 25.0
        assert temp.description == "room temperature"
    
    def test_range_values(self):
        """Should accept temperature ranges."""
        temp = ExtractedTemperature(
            is_range=True,
            range_min_celsius=20.0,
            range_max_celsius=25.0
        )
        
        assert temp.is_range is True
        assert temp.range_min_celsius == 20.0
        assert temp.range_max_celsius == 25.0


class TestExtractedDuration:
    """Tests for ExtractedDuration model."""
    
    def test_default_values(self):
        """Should have sensible defaults."""
        duration = ExtractedDuration()
        
        assert duration.value_minutes is None
        assert duration.is_ambiguous is False
    
    def test_explicit_value(self):
        """Should accept explicit duration."""
        duration = ExtractedDuration(value_minutes=180.0, description="3 hours")
        
        assert duration.value_minutes == 180.0
        assert duration.description == "3 hours"
    
    def test_ambiguous_duration(self):
        """Should flag ambiguous durations."""
        duration = ExtractedDuration(
            description="a few hours",
            is_ambiguous=True
        )
        
        assert duration.is_ambiguous is True
        assert duration.value_minutes is None


class TestExtractedScenario:
    """Tests for ExtractedScenario model."""
    
    def test_default_values(self):
        """Should have sensible defaults."""
        scenario = ExtractedScenario()
        
        assert scenario.food_description is None
        assert scenario.pathogen_mentioned is None
        assert scenario.is_multi_step is False
        assert scenario.time_temperature_steps == []
    
    def test_simple_scenario(self):
        """Should handle simple single-step scenario."""
        scenario = ExtractedScenario(
            food_description="raw chicken",
            single_step_temperature=ExtractedTemperature(value_celsius=25.0),
            single_step_duration=ExtractedDuration(value_minutes=180.0),
        )
        
        assert scenario.food_description == "raw chicken"
        assert scenario.single_step_temperature.value_celsius == 25.0
        assert scenario.single_step_duration.value_minutes == 180.0
    
    def test_multi_step_scenario(self):
        """Should handle multi-step scenario."""
        steps = [
            ExtractedTimeTemperatureStep(
                description="transport",
                temperature=ExtractedTemperature(value_celsius=20.0),
                duration=ExtractedDuration(value_minutes=60.0),
                sequence_order=1,
            ),
            ExtractedTimeTemperatureStep(
                description="storage",
                temperature=ExtractedTemperature(value_celsius=4.0),
                duration=ExtractedDuration(value_minutes=480.0),
                sequence_order=2,
            ),
        ]
        
        scenario = ExtractedScenario(
            food_description="salmon fillet",
            is_multi_step=True,
            time_temperature_steps=steps,
        )
        
        assert scenario.is_multi_step is True
        assert len(scenario.time_temperature_steps) == 2
        assert scenario.time_temperature_steps[0].temperature.value_celsius == 20.0
    
    def test_with_environmental_conditions(self):
        """Should handle environmental conditions."""
        scenario = ExtractedScenario(
            food_description="cured meat",
            environmental_conditions=ExtractedEnvironmentalConditions(
                ph_value=5.5,
                salt_percent=3.0,
                nitrite_ppm=150.0,
            ),
        )
        
        assert scenario.environmental_conditions.ph_value == 5.5
        assert scenario.environmental_conditions.salt_percent == 3.0
        assert scenario.environmental_conditions.nitrite_ppm == 150.0


class TestExtractedIntent:
    """Tests for ExtractedIntent model."""
    
    def test_prediction_request(self):
        """Should identify prediction requests."""
        intent = ExtractedIntent(
            is_prediction_request=True,
            is_information_query=False,
            confidence=0.95,
        )
        
        assert intent.is_prediction_request is True
        assert intent.is_information_query is False
    
    def test_information_query(self):
        """Should identify information queries."""
        intent = ExtractedIntent(
            is_prediction_request=False,
            is_information_query=True,
            reasoning="User asked about general food safety guidelines",
        )
        
        assert intent.is_prediction_request is False
        assert intent.is_information_query is True
    
    def test_confidence_bounds(self):
        """Confidence should be bounded 0-1."""
        intent = ExtractedIntent(
            is_prediction_request=True,
            is_information_query=False,
            confidence=0.5,
        )
        
        assert 0.0 <= intent.confidence <= 1.0