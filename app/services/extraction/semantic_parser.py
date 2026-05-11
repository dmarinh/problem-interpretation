"""
Semantic Parser

Uses Instructor to extract structured information from user input.
This is the bridge between free-text user input and typed extraction models.

Design Principles:
- Single responsibility: only extracts, does not validate or standardize
- Returns extraction models, not engine payloads
- Handles extraction failures gracefully
- Supports both single-step and multi-step scenarios
"""

from typing import TypeVar

from pydantic import BaseModel

from app.config import settings
from app.services.llm.client import LLMClient, get_llm_client
from app.models.extraction import (
    ExtractedScenario,
    ExtractedIntent,
    ExtractedClarificationResponse,
)


T = TypeVar("T", bound=BaseModel)


# =============================================================================
# SYSTEM PROMPTS
# =============================================================================

SCENARIO_EXTRACTION_PROMPT = """You are a food safety expert assistant. Your task is to extract structured information from a user's description of a food safety scenario.

Extract the following information if present:
- Food item description (what food is involved)
- Food state (raw, cooked, frozen, thawed, etc.)
- Pathogen if explicitly mentioned
- Temperature information: set value_celsius for explicit numeric values only; for descriptive
  phrases ("home refrigerator", "room temperature") leave value_celsius null and put the original
  phrasing verbatim in description — see temperature extraction section below
- Duration information: set value_minutes by converting to minutes using the conversion table below;
  for vague terms ("overnight", "a few hours") leave value_minutes null and put the phrasing in description
- Environmental conditions (pH, salt content, atmosphere, etc.)
- Whether this is a multi-step scenario (e.g., transport then storage)
- What the user is concerned about (safety, spoilage, shelf life)

Scenario type inference:
- is_cooking_scenario: True if the scenario involves cooking, heating, pasteurizing, boiling, grilling, or any high-temperature treatment intended to kill pathogens
- is_storage_scenario: True if the scenario involves storing, holding, leaving out, sitting at temperature, or ambient/refrigerated conditions
- is_non_thermal_treatment: True if the scenario involves non-thermal preservation or inactivation methods (acidification, drying, salting, high pressure, UV, irradiation, preservatives)
- implied_model_type:
  - "thermal_inactivation" if cooking/heating at high temperatures (typically >50°C) to kill pathogens
  - "growth" if storage/holding where bacterial growth is the concern
  - "non_thermal_survival" if non-thermal treatments affecting pathogen survival (acid exposure, drying, preservatives, high pressure processing)
  - null if unclear or ambiguous

Examples of scenario type inference:
- "Chicken left out for 3 hours" → is_storage_scenario=True, implied_model_type="growth"
- "Cooking chicken to 75°C for 5 minutes" → is_cooking_scenario=True, implied_model_type="thermal_inactivation"
- "Will pasteurization kill Salmonella?" → is_cooking_scenario=True, implied_model_type="thermal_inactivation"
- "Beef stored in fridge for a week" → is_storage_scenario=True, implied_model_type="growth"
- "Reheating leftovers to 70°C" → is_cooking_scenario=True, implied_model_type="thermal_inactivation"
- "Marinating chicken in lemon juice (pH 3)" → is_non_thermal_treatment=True, implied_model_type="non_thermal_survival"
- "Adding vinegar to preserve vegetables" → is_non_thermal_treatment=True, implied_model_type="non_thermal_survival"
- "Salting fish for preservation" → is_non_thermal_treatment=True, implied_model_type="non_thermal_survival"
- "High pressure processing of juice" → is_non_thermal_treatment=True, implied_model_type="non_thermal_survival"
- "Drying meat into jerky" → is_non_thermal_treatment=True, implied_model_type="non_thermal_survival"
- "Adding nitrites to cured meat" → is_non_thermal_treatment=True, implied_model_type="non_thermal_survival"

Important guidelines:
- Only extract what is explicitly stated or clearly implied
- Do not invent or assume values not mentioned
- If a range is given (e.g., "20-25C"), capture it as a range; this also applies to pH (e.g., "pH 5.5-6.0" → ph_min=5.5, ph_max=6.0) and water activity (e.g., "aw 0.92-0.95" → water_activity_min=0.92, water_activity_max=0.95)
- If time/temperature is ambiguous (e.g., "a while"), mark it as ambiguous
- Convert all temperatures to Celsius
- For multi-step scenarios, capture each step in sequence order

Duration extraction — conversion table and examples:

  Conversion table (use for unit arithmetic):
    30 seconds =     0.5 minutes
    1 minute   =     1 minutes
    1 hour     =    60 minutes
    1 day      = 1,440 minutes
    1 week     = 7 days = 10,080 minutes
    2 weeks    = 14 days = 20,160 minutes
    35 days    = 5 weeks = 50,400 minutes

  Worked examples:
    "for 35 days"                  → value_minutes=50400,  description="35 days"
    "a 35-day shelf life"          → value_minutes=50400,  description="35-day shelf life"
    "shelf life of 12 days"        → value_minutes=17280,  description="12-day shelf life"
    "5-7 days at 4°C"              → value_minutes=10080,  description="5-7 days"  (use upper bound; conservative for growth)
    "approximately 2 weeks"        → value_minutes=20160,  description="approximately 2 weeks"
    "for 840 hours"                → value_minutes=50400,  description="840 hours"
    "cook for 30 seconds at 72°C"  → value_minutes=0.5,    description="30 seconds"
    "overnight"                    → value_minutes=null,   description="overnight",              is_ambiguous=true
    "during retail display"        → value_minutes=null,   description="during retail display",  is_ambiguous=true
    "a few days"                   → value_minutes=null,   description="a few days",             is_ambiguous=true
    "throughout transport"         → value_minutes=null,   description="throughout transport",   is_ambiguous=true

  Multi-step example:
    "24 hours at 4°C then 6 hours at 10°C"
      step 1: value_minutes=1440, description="24 hours"
      step 2: value_minutes=360,  description="6 hours"

  Rules:
    - Set value_minutes whenever the input contains a number followed by a time unit.
    - Use the upper bound for ranges ("5-7 days" → 10080; conservative for growth modelling).
    - Do NOT set value_minutes when no number is present. "During retail display" has no number.
    - Do NOT interpret "shelf life" as a numeric duration unless a number accompanies it.
    - Do NOT estimate vague magnitudes. "A few days" is not 3 days. Leave value_minutes null.
    - Do NOT perform date arithmetic ("from 1 Jan to 5 Feb"). Put the phrasing in description.
    - Always populate description even when value_minutes is null — downstream resolution depends on it.

Temperature extraction — numeric vs. descriptive phrases:

  Principle: Your role is recognition, not estimation. Set value_celsius only when the user states
  an explicit numeric temperature. For descriptive phrases, leave value_celsius null and copy the
  original phrasing verbatim into description — downstream rule resolution handles category terms
  deterministically. The same principle applies to duration: neither field should receive inferred
  numeric values.

  Conversion table (Fahrenheit / Kelvin → Celsius):
    °C = (°F − 32) × 5/9
    °C = K − 273.15
    Common reference points:
       0°C =  32°F  (freezing)
       4°C =  39.2°F (standard refrigeration)
      22°C =  72°F  (room temperature)
      72°C = 162°F  (poultry pasteurisation)
     -18°C =   0°F  (standard freezer)

  Worked examples:
    "4°C"                          → value_celsius=4.0,    description=null
    "around 4°C"                   → value_celsius=4.0,    description="around 4°C"
    "72°F"                         → value_celsius=22.2,   description="72°F"
    "refrigerator set to 38°F"     → value_celsius=3.3,    description="38°F"
    "home refrigerator"            → value_celsius=null,   description="home refrigerator"
    "domestic refrigerator"        → value_celsius=null,   description="domestic refrigerator"
    "household freezer"            → value_celsius=null,   description="household freezer"
    "typical retail refrigeration" → value_celsius=null,   description="typical retail refrigeration"
    "room temperature"             → value_celsius=null,   description="room temperature"
    "stored cold"                  → value_celsius=null,   description="stored cold"
    "ambient"                      → value_celsius=null,   description="ambient"

  Rules:
    - Set value_celsius when the input contains a number followed by a temperature unit (°C, °F,
      K, degrees).
    - For ranges ("4–7°C"), use the upper bound (conservative for growth modelling).
    - Do NOT infer a numeric value from descriptive phrases. "Home refrigerator" is not 4°C; it is
      a category term. Do not apply world knowledge to convert appliance names, location names, or
      seasonal descriptors into numbers.
    - Do NOT paraphrase. Copy the user's phrasing verbatim into description. Do not collapse "stored
      cold" to "cold", "kitchen counter" to "room temperature", or "home freezer" to "freezer" —
      the original phrasing is what the downstream rule library matches against.
    - Always populate description when any descriptive phrasing is present, even when value_celsius
      is also populated (e.g., "around 4°C" → both fields; plain "4°C" → value_celsius only).
    - Do not infer temperature from container type, appliance name, season, or location alone unless
      the user states a number alongside it.

Initial inoculum extraction:

  Rules:
    - Extract only if the user explicitly states a starting bacterial count.
    - Convert raw CFU/g to log10 CFU/g: 1000 CFU/g → 3.0, 10^4 CFU/g → 4.0, 100 CFU/g → 2.0.
    - Leave initial_inoculum_log_cfu null if not mentioned. Do NOT infer or guess.

  Worked examples:
    "starting with 10^4 CFU/g"        → initial_inoculum_log_cfu=4.0
    "inoculated at 10^3 CFU/g"        → initial_inoculum_log_cfu=3.0
    "1000 CFU/g initial count"         → initial_inoculum_log_cfu=3.0
    "3 log CFU/g initial"              → initial_inoculum_log_cfu=3.0
    "initial load of 100 CFU/g"        → initial_inoculum_log_cfu=2.0
    "raw chicken left out for 3 hours" → initial_inoculum_log_cfu=null  (not mentioned)
"""

INTENT_CLASSIFICATION_PROMPT = """You are a food safety expert assistant. Classify the user's intent.

A PREDICTION REQUEST is when the user:
- Wants to know if food is safe to eat
- Asks about microbial growth or contamination risk
- Describes a scenario and wants a safety assessment
- Asks about shelf life or how long food can be kept
- Uses action verbs like predict, calculate, estimate, determine, or model with a specific scenario
- Requests a specific microbial outcome (e.g. log reduction, growth rate, inactivation, survival)
- Uses technical model-type terms (thermal inactivation, non-thermal survival, growth rate) in the context of a specific food/pathogen/condition scenario

An INFORMATION QUERY is when the user:
- Asks general questions about food safety with no specific scenario
- Wants to know about pathogens or foodborne illness in the abstract
- Asks about food safety guidelines or regulations
- Wants educational information, not a specific prediction

If the intent is unclear or could be either, mark requires_clarification as true.
"""

CLARIFICATION_RESPONSE_PROMPT = """You are a food safety expert assistant. The user is responding to a clarification question.

Extract:
- The specific value or information they provided
- If they selected from given options, which option
- If they want to skip the question and use defaults
- Any additional context they provided
"""


# =============================================================================
# SEMANTIC PARSER
# =============================================================================

class SemanticParser:
    """
    Extracts structured information from user input using LLM + Instructor.
    
    Usage:
        parser = SemanticParser()
        scenario = await parser.extract_scenario("Raw chicken left out for 3 hours")
        intent = await parser.classify_intent("Is my chicken still safe to eat?")
    """
    
    def __init__(self, llm_client: LLMClient | None = None):
        """
        Initialize the semantic parser.
        
        Args:
            llm_client: Optional LLM client. If not provided, uses the global client.
        """
        self._client = llm_client or get_llm_client()
    
    async def extract_scenario(
        self,
        user_input: str,
        conversation_context: str | None = None,
    ) -> ExtractedScenario:
        """
        Extract a food safety scenario from user input.
        
        Args:
            user_input: The user's description of their food safety scenario
            conversation_context: Optional previous conversation for context
        
        Returns:
            ExtractedScenario with all extracted information
        """
        messages = [
            {"role": "system", "content": SCENARIO_EXTRACTION_PROMPT},
        ]
        
        if conversation_context:
            messages.append({
                "role": "user",
                "content": f"Previous context:\n{conversation_context}\n\nCurrent input:\n{user_input}"
            })
        else:
            messages.append({"role": "user", "content": user_input})
        
        result = await self._client.extract(
            response_model=ExtractedScenario,
            messages=messages,
        )
        
        return result
    
    async def classify_intent(
        self,
        user_input: str,
    ) -> ExtractedIntent:
        """
        Classify the user's intent.
        
        Args:
            user_input: The user's message
        
        Returns:
            ExtractedIntent with classification
        """
        messages = [
            {"role": "system", "content": INTENT_CLASSIFICATION_PROMPT},
            {"role": "user", "content": user_input},
        ]
        
        result = await self._client.extract(
            response_model=ExtractedIntent,
            messages=messages,
        )
        
        return result
    
    async def extract_clarification_response(
        self,
        user_response: str,
        original_question: str,
        options: list[str] | None = None,
    ) -> ExtractedClarificationResponse:
        """
        Extract information from user's response to a clarification question.
        
        Args:
            user_response: The user's response
            original_question: The clarification question that was asked
            options: The options that were provided (if any)
        
        Returns:
            ExtractedClarificationResponse with extracted information
        """
        context = f"Original question: {original_question}"
        if options:
            context += f"\nOptions provided: {', '.join(options)}"
        
        messages = [
            {"role": "system", "content": CLARIFICATION_RESPONSE_PROMPT},
            {"role": "user", "content": f"{context}\n\nUser response: {user_response}"},
        ]
        
        result = await self._client.extract(
            response_model=ExtractedClarificationResponse,
            messages=messages,
        )
        
        return result
    
    async def extract_generic(
        self,
        response_model: type[T],
        user_input: str,
        system_prompt: str,
    ) -> T:
        """
        Generic extraction for custom models.
        
        Args:
            response_model: The Pydantic model to extract into
            user_input: The user's input
            system_prompt: The system prompt for extraction
        
        Returns:
            Instance of response_model with extracted data
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ]
        
        result = await self._client.extract(
            response_model=response_model,
            messages=messages,
        )
        
        return result


# =============================================================================
# SINGLETON
# =============================================================================

_parser: SemanticParser | None = None


def get_semantic_parser() -> SemanticParser:
    """Get or create the global SemanticParser instance."""
    global _parser
    if _parser is None:
        _parser = SemanticParser()
    return _parser


def reset_semantic_parser() -> None:
    """Reset the global parser (for testing)."""
    global _parser
    _parser = None