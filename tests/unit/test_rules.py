"""
Unit tests for interpretation rules.

These test LINGUISTIC INTERPRETATION rules, not scientific facts.
Scientific knowledge (pH, aw, pathogens) comes from RAG.
"""

import pytest

from app.config.rules import (
    InterpretationRule,
    BiasCorrectionRule,
    TEMPERATURE_INTERPRETATIONS,
    DURATION_INTERPRETATIONS,
    BIAS_CORRECTIONS,
    find_temperature_interpretation,
    find_duration_interpretation,
    get_bias_correction,
)


class TestTemperatureInterpretations:
    """Tests for temperature interpretation rules."""
    
    def test_room_temperature(self):
        """Should find room temperature rule."""
        rule = find_temperature_interpretation("left at room temperature")
        
        assert rule is not None
        assert rule.value == 25.0
        assert rule.conservative is True
    
    def test_refrigerated(self):
        """Should find refrigeration rule."""
        rule = find_temperature_interpretation("kept refrigerated overnight")
        
        assert rule is not None
        assert rule.value == 4.0
    
    def test_fridge(self):
        """Should find fridge rule."""
        rule = find_temperature_interpretation("in the fridge")
        
        assert rule is not None
        assert rule.value == 4.0
    
    def test_refrigerator(self):
        """Should find refrigerator rule."""
        rule = find_temperature_interpretation("stored in the refrigerator")
        
        assert rule is not None
        assert rule.value == 4.0
    
    def test_frozen(self):
        """Should find frozen rule."""
        rule = find_temperature_interpretation("kept frozen")
        
        assert rule is not None
        assert rule.value == -18.0
    
    def test_freezer(self):
        """Should find freezer rule."""
        rule = find_temperature_interpretation("in the freezer")
        
        assert rule is not None
        assert rule.value == -18.0
    
    def test_warm(self):
        """Should find warm rule."""
        rule = find_temperature_interpretation("in a warm kitchen")
        
        assert rule is not None
        assert rule.value == 30.0
    
    def test_hot(self):
        """Should find hot rule."""
        rule = find_temperature_interpretation("left in a hot car")
        
        assert rule is not None
        assert rule.value == 40.0
    
    def test_cold(self):
        """Should find cold rule."""
        rule = find_temperature_interpretation("somewhere cold")
        
        assert rule is not None
        assert rule.value == 10.0
    
    def test_cool(self):
        """Should find cool rule."""
        rule = find_temperature_interpretation("in a cool place")
        
        assert rule is not None
        assert rule.value == 15.0
    
    def test_chilled(self):
        """Should find chilled rule."""
        rule = find_temperature_interpretation("kept chilled")
        
        assert rule is not None
        assert rule.value == 4.0
    
    def test_counter(self):
        """Should find counter rule (implies room temp)."""
        rule = find_temperature_interpretation("left on the counter")
        
        assert rule is not None
        assert rule.value == 25.0
    
    def test_ambient(self):
        """Should find ambient rule."""
        rule = find_temperature_interpretation("at ambient temperature")
        
        assert rule is not None
        assert rule.value == 25.0
    
    def test_summer(self):
        """Should find summer rule."""
        rule = find_temperature_interpretation("during summer")
        
        assert rule is not None
        assert rule.value == 30.0
    
    def test_no_match(self):
        """Should return None for explicit numeric."""
        rule = find_temperature_interpretation("at exactly 37 degrees celsius")
        
        assert rule is None
    
    def test_case_insensitive(self):
        """Should match case-insensitively."""
        rule = find_temperature_interpretation("ROOM TEMPERATURE")
        
        assert rule is not None
        assert rule.value == 25.0
    
    def test_partial_match_in_sentence(self):
        """Should match within longer text."""
        rule = find_temperature_interpretation(
            "The chicken was sitting at room temperature for hours"
        )
        
        assert rule is not None
        assert rule.value == 25.0
    
    def test_empty_string(self):
        """Should return None for empty string."""
        rule = find_temperature_interpretation("")
        
        assert rule is None
    
    def test_none_input(self):
        """Should return None for None input."""
        rule = find_temperature_interpretation(None)
        
        assert rule is None


class TestDurationInterpretations:
    """Tests for duration interpretation rules."""
    
    def test_overnight(self):
        """Should find overnight rule."""
        rule = find_duration_interpretation("left out overnight")
        
        assert rule is not None
        assert rule.value == 480.0  # 8 hours
    
    def test_all_night(self):
        """Should find all night rule."""
        rule = find_duration_interpretation("sitting there all night")
        
        assert rule is not None
        assert rule.value == 480.0
    
    def test_few_hours(self):
        """Should find few hours rule."""
        rule = find_duration_interpretation("for a few hours")
        
        assert rule is not None
        assert rule.value == 180.0  # 3 hours
    
    def test_several_hours(self):
        """Should find several hours rule."""
        rule = find_duration_interpretation("for several hours")
        
        assert rule is not None
        assert rule.value == 300.0  # 5 hours
    
    def test_couple_hours(self):
        """Should find couple hours rule."""
        rule = find_duration_interpretation("for a couple hours")
        
        assert rule is not None
        assert rule.value == 120.0  # 2 hours
    
    def test_couple_of_hours(self):
        """Should find 'couple of hours' rule."""
        rule = find_duration_interpretation("for a couple of hours")
        
        assert rule is not None
        assert rule.value == 120.0
    
    def test_all_day(self):
        """Should find all day rule."""
        rule = find_duration_interpretation("left out all day")
        
        assert rule is not None
        assert rule.value == 720.0  # 12 hours
    
    def test_whole_day(self):
        """Should find whole day rule."""
        rule = find_duration_interpretation("the whole day")
        
        assert rule is not None
        assert rule.value == 720.0
    
    def test_half_day(self):
        """Should find half day rule."""
        rule = find_duration_interpretation("for half a day")
        
        assert rule is not None
        assert rule.value == 360.0  # 6 hours
    
    def test_briefly(self):
        """Should find briefly rule."""
        rule = find_duration_interpretation("just briefly")
        
        assert rule is not None
        assert rule.value == 10.0
    
    def test_few_minutes(self):
        """Should find few minutes rule."""
        rule = find_duration_interpretation("for a few minutes")
        
        assert rule is not None
        assert rule.value == 15.0
    
    def test_a_while(self):
        """Should find 'a while' rule."""
        rule = find_duration_interpretation("sitting there a while")
        
        assert rule is not None
        assert rule.value == 60.0
    
    def test_some_time(self):
        """Should find 'some time' rule."""
        rule = find_duration_interpretation("for some time")
        
        assert rule is not None
        assert rule.value == 60.0
    
    def test_an_hour(self):
        """Should find 'an hour' rule."""
        rule = find_duration_interpretation("for about an hour")
        
        assert rule is not None
        assert rule.value == 60.0
    
    def test_long_time(self):
        """Should find 'long time' rule."""
        rule = find_duration_interpretation("for a long time")
        
        assert rule is not None
        assert rule.value == 360.0
    
    def test_many_hours(self):
        """Should find many hours rule."""
        rule = find_duration_interpretation("for many hours")
        
        assert rule is not None
        assert rule.value == 360.0
    
    def test_no_match_explicit_duration(self):
        """Should return None for explicit duration."""
        rule = find_duration_interpretation("for exactly 2.5 hours")
        
        assert rule is None
    
    def test_no_match_numeric(self):
        """Should return None for purely numeric."""
        rule = find_duration_interpretation("for 180 minutes")
        
        assert rule is None
    
    def test_longer_pattern_priority(self):
        """Should prefer longer patterns over shorter ones."""
        # "a couple of hours" (17 chars) should match before "a couple hours" (14 chars)
        rule = find_duration_interpretation("left out for a couple of hours")
        
        assert rule is not None
        assert rule.value == 120.0
    
    def test_case_insensitive(self):
        """Should match case-insensitively."""
        rule = find_duration_interpretation("LEFT OUT OVERNIGHT")
        
        assert rule is not None
        assert rule.value == 480.0
    
    def test_empty_string(self):
        """Should return None for empty string."""
        rule = find_duration_interpretation("")
        
        assert rule is None
    
    def test_none_input(self):
        """Should return None for None input."""
        rule = find_duration_interpretation(None)
        
        assert rule is None


class TestBiasCorrections:
    """Tests for bias correction rules."""
    
    def test_get_inferred_duration_margin(self):
        """Should find duration margin rule."""
        rule = get_bias_correction("inferred_duration_margin")
        
        assert rule is not None
        assert rule.correction_type == "multiply"
        assert rule.factor == 1.2
    
    def test_get_temperature_range_upper(self):
        """Should find temperature range rule."""
        rule = get_bias_correction("temperature_range_upper")
        
        assert rule is not None
        assert rule.correction_type == "use_upper"
    
    def test_get_duration_range_upper(self):
        """Should find duration range rule."""
        rule = get_bias_correction("duration_range_upper")
        
        assert rule is not None
        assert rule.correction_type == "use_upper"
    
    def test_get_low_confidence_temperature_bump(self):
        """Should find low confidence temperature rule."""
        rule = get_bias_correction("low_confidence_temperature_bump")
        
        assert rule is not None
        assert rule.correction_type == "add"
        assert rule.factor == 5.0
    
    def test_get_nonexistent_returns_none(self):
        """Should return None for unknown rule."""
        rule = get_bias_correction("nonexistent_rule")
        
        assert rule is None


class TestRuleDataStructureIntegrity:
    """Tests for rule data structure integrity."""
    
    def test_all_temperature_rules_have_required_fields(self):
        """All temperature rules should have valid structure."""
        for rule in TEMPERATURE_INTERPRETATIONS:
            assert rule.pattern is not None
            assert len(rule.pattern) > 0
            assert rule.value is not None
            assert isinstance(rule.value, (int, float))
            assert 0.0 <= rule.confidence <= 1.0
            assert isinstance(rule.conservative, bool)
    
    def test_all_temperature_values_reasonable(self):
        """Temperature values should be in reasonable range."""
        for rule in TEMPERATURE_INTERPRETATIONS:
            # Temperatures should be between -30 and 60 C
            assert -30 <= rule.value <= 60, f"Unreasonable temp {rule.value} for {rule.pattern}"
    
    def test_all_duration_rules_have_required_fields(self):
        """All duration rules should have valid structure."""
        for rule in DURATION_INTERPRETATIONS:
            assert rule.pattern is not None
            assert len(rule.pattern) > 0
            assert rule.value is not None
            assert isinstance(rule.value, (int, float))
            assert rule.value > 0, f"Duration should be positive for {rule.pattern}"
            assert 0.0 <= rule.confidence <= 1.0
            assert isinstance(rule.conservative, bool)
    
    def test_all_duration_values_reasonable(self):
        """Duration values should be in reasonable range (minutes)."""
        for rule in DURATION_INTERPRETATIONS:
            # Durations should be between 1 minute and 24 hours (1440 min)
            assert 1 <= rule.value <= 1440, f"Unreasonable duration {rule.value} for {rule.pattern}"
    
    def test_all_bias_rules_have_required_fields(self):
        """All bias correction rules should have valid structure."""
        for rule in BIAS_CORRECTIONS:
            assert rule.name is not None
            assert len(rule.name) > 0
            assert rule.condition is not None
            assert rule.correction_type in ["multiply", "use_upper", "use_lower", "add"]
    
    def test_bias_rules_with_factor_have_valid_factor(self):
        """Bias rules with multiply/add should have valid factor."""
        for rule in BIAS_CORRECTIONS:
            if rule.correction_type in ["multiply", "add"]:
                assert rule.factor is not None, f"Rule {rule.name} needs factor"
                assert rule.factor > 0, f"Factor should be positive for {rule.name}"
    
    def test_no_duplicate_temperature_patterns(self):
        """Temperature patterns should be unique."""
        patterns = [r.pattern for r in TEMPERATURE_INTERPRETATIONS]
        assert len(patterns) == len(set(patterns)), "Duplicate temperature patterns found"
    
    def test_no_duplicate_duration_patterns(self):
        """Duration patterns should be unique."""
        patterns = [r.pattern for r in DURATION_INTERPRETATIONS]
        assert len(patterns) == len(set(patterns)), "Duplicate duration patterns found"
    
    def test_no_duplicate_bias_rule_names(self):
        """Bias rule names should be unique."""
        names = [r.name for r in BIAS_CORRECTIONS]
        assert len(names) == len(set(names)), "Duplicate bias rule names found"


class TestRuleNotes:
    """Tests that rules have explanatory notes."""
    
    def test_temperature_rules_have_notes(self):
        """Temperature rules should have notes for auditability."""
        for rule in TEMPERATURE_INTERPRETATIONS:
            assert rule.notes is not None
            assert len(rule.notes) > 0, f"Missing notes for {rule.pattern}"
    
    def test_duration_rules_have_notes(self):
        """Duration rules should have notes for auditability."""
        for rule in DURATION_INTERPRETATIONS:
            assert rule.notes is not None
            assert len(rule.notes) > 0, f"Missing notes for {rule.pattern}"
    
    def test_bias_rules_have_notes(self):
        """Bias rules should have notes for auditability."""
        for rule in BIAS_CORRECTIONS:
            assert rule.notes is not None
            assert len(rule.notes) > 0, f"Missing notes for {rule.name}"