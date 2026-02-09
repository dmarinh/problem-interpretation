"""
Extraction Models (Semantic Layer)

These models are targets for Instructor-based LLM extraction.
They capture WHAT THE USER SAID, not engine-compliant parameters.

Key Principles:
- Free-text fields are allowed here (this is the semantic layer)
- These models are NEVER passed directly to engines
- Values are grounded/validated in later pipeline stages
- Optional fields are common (users often omit information)

Flow:
    User Input → [Instructor] → ExtractedScenario → [RAG + Standardization] → ExecutionPayload
"""

from pydantic import BaseModel, Field


# =============================================================================
# CORE EXTRACTION MODELS
# =============================================================================

class ExtractedTemperature(BaseModel):
    """
    Temperature information extracted from user input.
    
    Captures both explicit values and descriptive terms.
    """
    value_celsius: float | None = Field(
        default=None,
        description="Explicit temperature value in Celsius if mentioned"
    )
    description: str | None = Field(
        default=None,
        description="Descriptive term used (e.g., 'room temperature', 'refrigerated', 'warm')"
    )
    is_range: bool = Field(
        default=False,
        description="Whether a range was specified"
    )
    range_min_celsius: float | None = Field(
        default=None,
        description="Minimum of range if specified"
    )
    range_max_celsius: float | None = Field(
        default=None,
        description="Maximum of range if specified"
    )


class ExtractedDuration(BaseModel):
    """
    Duration/time information extracted from user input.
    
    Captures both explicit values and vague expressions.
    """
    value_minutes: float | None = Field(
        default=None,
        description="Explicit duration in minutes if mentioned"
    )
    description: str | None = Field(
        default=None,
        description="Descriptive term used (e.g., 'a few hours', 'overnight', 'briefly')"
    )
    is_ambiguous: bool = Field(
        default=False,
        description="Whether the duration is vague/ambiguous"
    )
    range_min_minutes: float | None = Field(
        default=None,
        description="Minimum of range if specified"
    )
    range_max_minutes: float | None = Field(
        default=None,
        description="Maximum of range if specified"
    )


class ExtractedTimeTemperatureStep(BaseModel):
    """
    A single step in a time-temperature history.
    
    Used for multi-step scenarios (e.g., transport → storage → display).
    """
    description: str | None = Field(
        default=None,
        description="Description of this step (e.g., 'during transport', 'in the fridge')"
    )
    temperature: ExtractedTemperature = Field(
        default_factory=ExtractedTemperature,
        description="Temperature during this step"
    )
    duration: ExtractedDuration = Field(
        default_factory=ExtractedDuration,
        description="Duration of this step"
    )
    sequence_order: int | None = Field(
        default=None,
        description="Order in the sequence (1, 2, 3...)"
    )


class ExtractedEnvironmentalConditions(BaseModel):
    """
    Environmental conditions extracted from user input.
    
    These are the inhibitory factors beyond temperature.
    """
    ph_value: float | None = Field(
        default=None,
        description="pH value if explicitly mentioned"
    )
    ph_description: str | None = Field(
        default=None,
        description="pH description (e.g., 'acidic', 'neutral')"
    )
    water_activity: float | None = Field(
        default=None,
        description="Water activity (aw) if explicitly mentioned"
    )
    salt_percent: float | None = Field(
        default=None,
        description="Salt/NaCl percentage if mentioned"
    )
    salt_description: str | None = Field(
        default=None,
        description="Salt description (e.g., 'salty', 'brined')"
    )
    co2_percent: float | None = Field(
        default=None,
        description="CO2 percentage if mentioned (modified atmosphere)"
    )
    nitrite_ppm: float | None = Field(
        default=None,
        description="Nitrite concentration in ppm if mentioned"
    )
    lactic_acid_ppm: float | None = Field(
        default=None,
        description="Lactic acid concentration in ppm if mentioned"
    )
    acetic_acid_ppm: float | None = Field(
        default=None,
        description="Acetic acid concentration in ppm if mentioned"
    )
    atmosphere_description: str | None = Field(
        default=None,
        description="Atmosphere description (e.g., 'vacuum packed', 'modified atmosphere')"
    )


class ExtractedScenario(BaseModel):
    """
    Complete extraction from a user's food safety scenario.
    
    This is the main model that Instructor populates from user input.
    All fields are optional because users rarely provide complete information.
    
    Example input:
        "I left raw chicken on the counter for about 3 hours, 
         it was pretty warm in the kitchen, maybe 25°C"
    
    Example extraction:
        food_description: "raw chicken"
        pathogen_mentioned: None (not explicitly mentioned)
        temperature: {value_celsius: 25, description: "warm kitchen"}
        duration: {value_minutes: 180, description: "about 3 hours"}
    """
    # Food information
    food_description: str | None = Field(
        default=None,
        description="The food item as described by user (e.g., 'raw chicken breast', 'leftover pasta')"
    )
    food_state: str | None = Field(
        default=None,
        description="State of the food (e.g., 'raw', 'cooked', 'frozen', 'thawed')"
    )
    
    # Pathogen information
    pathogen_mentioned: str | None = Field(
        default=None,
        description="Pathogen if explicitly mentioned by user (e.g., 'salmonella', 'listeria')"
    )
    
    # Time-temperature profile
    is_multi_step: bool = Field(
        default=False,
        description="Whether the scenario involves multiple time-temperature steps"
    )
    single_step_temperature: ExtractedTemperature = Field(
        default_factory=ExtractedTemperature,
        description="Temperature for single-step scenarios"
    )
    single_step_duration: ExtractedDuration = Field(
        default_factory=ExtractedDuration,
        description="Duration for single-step scenarios"
    )
    time_temperature_steps: list[ExtractedTimeTemperatureStep] = Field(
        default_factory=list,
        description="Multiple steps for complex scenarios"
    )
    
    # Environmental conditions
    environmental_conditions: ExtractedEnvironmentalConditions = Field(
        default_factory=ExtractedEnvironmentalConditions,
        description="Additional environmental factors"
    )
    
    # Context
    concern_type: str | None = Field(
        default=None,
        description="What the user is concerned about (e.g., 'safety', 'spoilage', 'shelf life')"
    )
    additional_context: str | None = Field(
        default=None,
        description="Any other relevant context mentioned"
    )


# =============================================================================
# INTENT CLASSIFICATION
# =============================================================================

class ExtractedIntent(BaseModel):
    """
    Classification of user intent.
    
    Used in Step 2 of the workflow to determine if this is a prediction
    request or a general information query.
    """
    is_prediction_request: bool = Field(
        description="Whether the user wants a microbial growth/safety prediction"
    )
    is_information_query: bool = Field(
        description="Whether the user is asking a general food safety question"
    )
    requires_clarification: bool = Field(
        default=False,
        description="Whether the intent is unclear and needs clarification"
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence in the intent classification"
    )
    reasoning: str | None = Field(
        default=None,
        description="Brief explanation of why this intent was assigned"
    )


# =============================================================================
# CLARIFICATION MODELS
# =============================================================================

class ClarificationQuestion(BaseModel):
    """
    A question to ask the user for clarification.
    """
    question: str = Field(
        description="The clarification question to ask"
    )
    reason: str = Field(
        description="Why this clarification is needed"
    )
    options: list[str] | None = Field(
        default=None,
        description="Suggested options for the user (if applicable)"
    )
    default_if_skipped: str | None = Field(
        default=None,
        description="What value will be used if user doesn't respond"
    )


class ExtractedClarificationResponse(BaseModel):
    """
    Extraction from user's response to a clarification question.
    """
    understood_value: str | None = Field(
        default=None,
        description="The value extracted from user's clarification"
    )
    selected_option: str | None = Field(
        default=None,
        description="Which option the user selected (if options were provided)"
    )
    wants_to_skip: bool = Field(
        default=False,
        description="Whether user wants to skip and use default"
    )
    additional_info: str | None = Field(
        default=None,
        description="Any additional information provided"
    )