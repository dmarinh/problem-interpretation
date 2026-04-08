# Problem Translation Module: Complete Technical Documentation

A system for translating natural language food safety queries into predictive microbiology model executions.

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Problem Statement](#problem-statement)
3. [Solution Architecture](#solution-architecture)
4. [System Components](#system-components)
5. [Data Flow](#data-flow)
6. [Technology Stack](#technology-stack)
7. [Module Deep Dives](#module-deep-dives)
8. [Data Sources and Knowledge Base](#data-sources-and-knowledge-base)
9. [Design Principles](#design-principles)
10. [Key Design Decisions](#key-design-decisions)
11. [Project Structure](#project-structure)
12. [Configuration](#configuration)
13. [Testing Strategy](#testing-strategy)
14. [Current Status and Roadmap](#current-status-and-roadmap)
15. [Extending the System](#extending-the-system)
16. [Glossary](#glossary)
17. [References](#references)

---

## Executive Summary

The **Problem Translation Module** bridges the gap between natural human language and predictive microbiology models. It enables users to ask food safety questions in plain English ("Is raw chicken safe after sitting on the counter for 3 hours?") and receive scientifically-grounded predictions based on established bacterial growth models.

### Key Capabilities

| Capability | Description |
|------------|-------------|
| **Natural Language Understanding** | Accepts queries in everyday language, no scientific notation required |
| **Scientific Grounding** | Retrieves food properties (pH, water activity) from authoritative sources (FDA, CDC) |
| **Intelligent Model Selection** | Automatically determines whether to use growth or thermal inactivation models |
| **Conservative Safety Bias** | When uncertain, errs on the side of caution |
| **Complete Provenance** | Every value is traceable to its source with confidence scores |
| **Transparent Processing** | All assumptions, defaults, and corrections are documented |

### What It Does

1. **Understands** the user's question (growth risk? cooking safety? shelf life?)
2. **Extracts** key details (food type, temperature, duration, conditions)
3. **Retrieves** scientific data (pH, water activity, pathogen associations)
4. **Interprets** vague terms ("room temperature" → 25°C, "overnight" → 8 hours)
5. **Standardizes** inputs (applies defaults, validates ranges)
6. **Executes** the appropriate ComBase predictive model
7. **Returns** mathematical results with full provenance

### What It Doesn't Do (Yet)

- **Interpret results**: The module outputs raw model results (μ_max, log increase, doubling time). A future "Result Interpretation Module" will translate these into natural language guidance.
- **Interactive clarification**: Currently, the system makes assumptions when information is missing. A future clarification loop will ask users for missing critical information.

---

## Problem Statement

### The Challenge

Food safety scientists and regulators rely on predictive microbiology models to answer critical questions:
- How quickly will bacteria grow on chicken left at room temperature?
- Will cooking at 75°C for 5 minutes kill Salmonella?
- Is that deli meat still safe after a week in the fridge?

These models (like ComBase) are powerful but require precise scientific inputs:
- pH values (e.g., 6.0)
- Water activity coefficients (e.g., 0.99)
- Specific pathogen identifiers (e.g., `ss` for Salmonella)
- Exact temperatures in Celsius

**The gap**: Users think "I left chicken out for a few hours on a warm day" while models need `temperature_celsius=28.0, duration_minutes=180, organism=ss, ph=6.0, aw=0.99`.

### Who Benefits

| Audience | Benefit |
|----------|---------|
| **Food Safety Professionals** | Instant routine calculations, focus on complex cases |
| **Regulators & Inspectors** | Field assessments without manual calculations |
| **Food Industry Personnel** | Informed decisions without deep microbiology expertise |
| **Educators & Students** | Interactive exploration of food safety scenarios |
| **Researchers** | Rapid scenario prototyping and validation |

---

## Solution Architecture

### High-Level Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              USER QUERY                                     │
│      "I left raw chicken on the counter overnight, is it still safe?"       │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         1. SEMANTIC PARSER                                  │
│  • LLM-based extraction using Instructor                                    │
│  • Output: ExtractedScenario (food, temperature, duration, pathogen...)     │
│  • Infers scenario type (storage/cooking/non-thermal)                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         2. GROUNDING SERVICE                                │
│  • Resolves vague terms ("room temperature" → 25°C)                         │
│  • Retrieves food properties from RAG (pH, water activity)                  │
│  • Identifies relevant pathogens from food-pathogen associations            │
│  • Tracks provenance and confidence for every value                         │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       3. STANDARDIZATION SERVICE                            │
│  • Applies conservative defaults for missing values                         │
│  • Clamps values to model-valid ranges                                      │
│  • Applies bias corrections (e.g., +20% for uncertain durations)            │
│  • Builds execution payload                                                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          4. MODEL EXECUTION                                 │
│  • Selects appropriate ComBase model (growth/thermal inactivation)          │
│  • Calculates μ_max, doubling time, log increase/reduction                  │
│  • Supports multi-step time-temperature profiles                            │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            5. ORCHESTRATOR                                  │
│  • Coordinates all services                                                 │
│  • Manages session state and metadata                                       │
│  • Aggregates results and provenance                                        │
│  • Returns TranslationResult                                                │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          TRANSLATION RESULT                                 │
│  • Model results: μ_max, doubling time, log increase                        │
│  • Full provenance: source and confidence for every input value             │
│  • Warnings: assumptions made, defaults applied                             │
│  • Metadata: corrections, clamps, retrievals performed                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Supporting Systems

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          RAG KNOWLEDGE BASE                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│  • ChromaDB vector store with semantic search                               │
│  • Food properties (259 foods with pH, aw from FDA/IFT sources)             │
│  • Pathogen characteristics (30 pathogens from CDC epidemiology)            │
│  • Pathogen-food associations (46 mappings from IFT/FDA)                    │
│  • TCS classification rules (25 rules from IFT/FDA)                         │
│  • All data traceable to source documents with citations                    │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                        INTERPRETATION RULES                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│  • Temperature interpretations ("room temperature" → 25°C)                  │
│  • Duration interpretations ("overnight" → 480 minutes)                     │
│  • Embedding similarity fallback for novel phrases                          │
│  • Conservative selection for ranges (upper bound for temp/duration)        │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                         COMBASE MODELS                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│  • 15 organisms supported                                                   │
│  • Growth models (bacterial multiplication over time)                       │
│  • Thermal inactivation models (pathogen death during cooking)              │
│  • Non-thermal survival models (acid exposure, drying, etc.)                │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## System Components

### Core Services

| Service | Location | Responsibility |
|---------|----------|----------------|
| **Orchestrator** | `app/core/orchestrator.py` | Coordinates full translation pipeline |
| **SemanticParser** | `app/services/extraction/semantic_parser.py` | LLM-based scenario extraction |
| **GroundingService** | `app/services/grounding/grounding_service.py` | Value resolution and RAG retrieval |
| **StandardizationService** | `app/services/standardization/standardization_service.py` | Defaults, clamping, bias correction |
| **ComBaseEngine** | `app/engines/combase/engine.py` | Model execution |
| **ComBaseCalculator** | `app/engines/combase/calculator.py` | Mathematical calculations |

### RAG System

| Component | Location | Responsibility |
|-----------|----------|----------------|
| **VectorStore** | `app/rag/vector_store.py` | ChromaDB interface |
| **RetrievalService** | `app/rag/retrieval.py` | Query and reranking |
| **IngestionPipeline** | `app/rag/ingestion.py` | Document processing |
| **DataSources** | `app/rag/data_sources/` | Domain-specific loaders |

### Supporting Components

| Component | Location | Responsibility |
|-----------|----------|----------------|
| **LLMClient** | `app/services/llm/client.py` | LiteLLM + Instructor wrapper |
| **Rules** | `app/config/rules.py` | Interpretation rules |
| **Settings** | `app/config/settings.py` | Configuration management |
| **Models** | `app/models/` | Pydantic data models |

---

## Data Flow

### Detailed Processing Example

**User Input:** "I left raw chicken on the counter for 3 hours at room temperature"

#### Step 1: Semantic Parsing (LLM)
```python
ExtractedScenario(
    food_description="raw chicken",
    food_state="raw",
    single_step_temperature=ExtractedTemperature(
        value_celsius=None,
        description="room temperature",
    ),
    single_step_duration=ExtractedDuration(
        value_minutes=180.0,  # "3 hours" converted
        description="3 hours",
    ),
    is_storage_scenario=True,
    implied_model_type=ModelType.GROWTH,
)
```

#### Step 2: Grounding
```python
GroundedValues(
    values={
        "temperature_celsius": 25.0,      # "room temperature" interpreted
        "duration_minutes": 180.0,         # From extraction
        "ph": 6.0,                          # From RAG: raw chicken pH
        "water_activity": 0.99,             # From RAG: raw chicken aw
        "organism": ComBaseOrganism.SALMONELLA,  # From RAG: primary hazard
    },
    provenance={
        "temperature_celsius": ValueProvenance(
            source=ValueSource.USER_INFERRED,
            confidence=0.80,
            transformation_applied="Interpreted 'room temperature' as 25°C",
        ),
        "ph": ValueProvenance(
            source=ValueSource.RAG_RETRIEVAL,
            confidence=0.85,
            retrieval_source="food_properties:chicken",
            original_text="chicken (poultry): pH 5.9-6.2 [FDA-PH-2007]",
            transformation_applied="Range 5.9-6.2, using upper bound 6.0",
        ),
        # ... etc
    },
)
```

#### Step 3: Standardization
```python
StandardizationResult(
    payload=ComBaseExecutionPayload(
        model_selection=ComBaseModelSelection(
            organism=ComBaseOrganism.SALMONELLA,
            model_type=ModelType.GROWTH,
        ),
        parameters=ComBaseParameters(
            temperature_celsius=25.0,
            ph=6.0,
            water_activity=0.99,
        ),
        time_temperature_profile=TimeTemperatureProfile(
            steps=[TimeTemperatureStep(
                temperature_celsius=25.0,
                duration_minutes=180.0,
            )],
        ),
    ),
    bias_corrections=[],  # None needed in this case
    defaults_applied=[],   # All values were grounded
)
```

#### Step 4: Model Execution
```python
ComBaseExecutionResult(
    model_result=ComBaseModelResult(
        organism=ComBaseOrganism.SALMONELLA,
        mu_max=0.52,  # Growth rate per hour
        doubling_time_hours=1.33,
        temperature_used=25.0,
        ph_used=6.0,
        aw_used=0.99,
    ),
    total_log_increase=1.13,  # ~13x population increase in 3 hours
    step_predictions=[...],
)
```

---

## Technology Stack

### Core Technologies

| Category | Technology | Purpose |
|----------|------------|---------|
| **Language** | Python 3.11+ | Primary implementation language |
| **Web Framework** | FastAPI | API endpoints (future) |
| **LLM Integration** | LiteLLM + Instructor | Structured extraction from natural language |
| **Vector Database** | ChromaDB | Semantic search for RAG |
| **Embeddings** | sentence-transformers (all-MiniLM-L6-v2) | Text to vector conversion |
| **Reranking** | cross-encoder/ms-marco-MiniLM-L-6-v2 | Search result reranking |
| **Data Validation** | Pydantic v2 | Schema definition and validation |
| **Evaluation** | ranx | IR metrics (MRR, nDCG) |

### LLM Support

The system uses LiteLLM for provider-agnostic LLM access:

| Provider | Models Tested |
|----------|---------------|
| OpenAI | gpt-4-turbo, gpt-4o, gpt-3.5-turbo |
| Anthropic | claude-3-sonnet, claude-3-haiku |
| Ollama | llama2, mistral (local) |

---

## Module Deep Dives

### Semantic Parser

The SemanticParser uses Instructor (structured outputs from LLMs) to extract food safety scenarios from natural language.

**Key Features:**
- Extracts food description, temperature, duration, pathogen mentions
- Infers scenario type (cooking vs. storage vs. non-thermal treatment)
- Handles multi-step scenarios (transport → storage → display)
- Classifies user intent (prediction request vs. information query)

**System Prompts:**
- `SCENARIO_EXTRACTION_PROMPT`: Guides extraction of all scenario elements
- `INTENT_CLASSIFICATION_PROMPT`: Determines if user wants a prediction
- `CLARIFICATION_RESPONSE_PROMPT`: Processes user responses to questions

### Grounding Service

The GroundingService resolves extracted values into precise numeric inputs.

**Resolution Hierarchy (highest to lowest priority):**
1. **User Explicit**: Values directly stated ("the temperature was 25°C") — confidence 0.90
2. **User Inferred**: Values from interpretation rules ("room temperature" → 25°C) — confidence 0.65-0.85
3. **RAG Retrieval**: Values from knowledge base (chicken pH → 6.0) — confidence 0.50-0.95
4. **Conservative Defaults**: Safety-first fallbacks (applied by StandardizationService)

**Key Principle:** Higher priority sources are never overwritten by lower priority sources.

**Two Knowledge Types:**
- **RAG (Scientific Facts)**: Food pH, water activity, pathogen associations
- **Rules (Linguistic Conventions)**: "room temperature" = 25°C, "overnight" = 8 hours

**GroundedValues Container:**
```python
grounded = GroundedValues()
grounded.set("ph", 6.0, ValueSource.RAG_RETRIEVAL, confidence=0.85)
grounded.get("ph")  # → 6.0
grounded.has("ph")  # → True
grounded.provenance["ph"]  # → ValueProvenance with source, confidence, etc.
grounded.mark_ungrounded("organism", "No pathogen found")  # Tracks missing values
```

**Numeric Extraction:**
The service extracts numeric values from text using regex patterns:
- Single values: `pH 6.0`, `pH: 6.5`, `aw 0.98`
- Ranges with hyphen: `pH 5.9-6.2`
- Ranges with "to": `pH 5.5 to 6.0`
- Ranges with "and": `pH between 5.5 and 6.0`

When ranges are found, the upper bound is used (conservative bias).

### Standardization Service

The StandardizationService prepares grounded values for model execution.

**Responsibilities:**
1. Apply conservative defaults for missing values
2. Clamp values to model-valid ranges
3. Apply bias corrections for uncertain estimates
4. Build the execution payload

**Bias Corrections:**
| Type | Description | Example |
|------|-------------|---------|
| `OPTIMISTIC_DURATION` | +20% for inferred durations | 180 min → 216 min |
| `MISSING_VALUE_IMPUTED` | Default applied | pH defaulted to 6.5 |
| `OUT_OF_RANGE_CLAMPED` | Value adjusted to valid range | 60°C clamped to model max |

### ComBase Engine

The ComBaseEngine executes predictive microbiology models.

**Supported Model Types:**
- **Growth** (ModelType.GROWTH): Bacterial multiplication over time
- **Thermal Inactivation** (ModelType.THERMAL_INACTIVATION): Pathogen death during cooking
- **Non-Thermal Survival** (ModelType.NON_THERMAL_SURVIVAL): Survival under non-heat treatments

**Supported Organisms (15):**
- Salmonella, Listeria monocytogenes, E. coli, Staphylococcus aureus
- Bacillus cereus, Clostridium botulinum (proteolytic and non-proteolytic)
- Clostridium perfringens, Yersinia enterocolitica
- And more (see `ComBaseOrganism` enum)


### RAG System

The RAG system provides scientific knowledge retrieval.

**Architecture:**
```
Query → Embedding → Vector Search → Reranking → Confidence Scoring → Results
```

**Document Types:**
- `food_properties`: pH, water activity for 259 foods
- `pathogen_hazards`: Growth parameters, epidemiology for 30 pathogens
- `conservative_values`: TCS classification rules

**Confidence Levels:**
| Level | Score Range | Interpretation |
|-------|-------------|----------------|
| HIGH | ≥ 0.85 | Strong semantic match |
| MEDIUM | ≥ 0.70 | Reasonable match |
| LOW | > 0.50 | Weak match |
| FAILED | ≤ 0.50 | No reliable match |

---

## Data Sources and Knowledge Base

### Primary Sources

| Source ID | Document | Publisher | Content |
|-----------|----------|-----------|---------|
| CDC-2011-T2/T3/A1 | Scallan et al. 2011 | CDC / EID Journal | Foodborne illness epidemiology (30 pathogens) |
| IFT-2003-T1/T31-33/TA/TB | PHF Report 2003 | IFT/FDA | Food safety parameters, TCS rules |
| FDA-PH-2007 | pH List | FDA/CFSAN | Food pH values (259 foods) |
| FDA-BBB-2012 | Bad Bug Book 2nd Ed | FDA/CFSAN | Pathogen characteristics |

### Processed Data Files

| File | Records | Source | Content |
|------|---------|--------|---------|
| `food_properties.csv` | 259 | FDA-PH-2007, IFT-2003 | pH, water activity per food |
| `pathogen_characteristics.csv` | 30 | CDC-2011-T3 | Annual illnesses, deaths, CFR |
| `pathogen_transmission_details.csv` | 27 | CDC-2011-A1 | Transmission routes, % foodborne |
| `pathogen_food_associations.csv` | 46 | IFT-2003-T1 | Food category → pathogen mapping |
| `pathogen_aw_limits.csv` | 14 | IFT-2003-T32 | Minimum aw for growth |
| `tcs_classification_tables.csv` | 25 | IFT-2003-TA/TB | TCS classification rules |

### Citation System

Every document in the knowledge base includes a source tag for LLM visibility:

```
"Listeria monocytogenes epidemiology: 1591 annual illnesses. 255 annual deaths.
Case fatality rate 15.9%. 99% foodborne transmission. [CDC-2011-T3]"
```

This enables:
- LLM to reason about source authority during generation
- Citation expansion to full references in output
- Complete traceability of all facts

---

## Interpretation Rules

The system uses linguistic interpretation rules to convert vague descriptions into precise values. These rules are separate from scientific facts (which come from RAG).

### Temperature Interpretations

| Pattern | Value (°C) | Confidence | Notes |
|---------|------------|------------|-------|
| `room temperature` | 25.0 | 0.80 | Standard indoor temperature |
| `refrigerated`, `fridge`, `refrigerator`, `chilled` | 4.0 | 0.85 | Standard refrigeration |
| `frozen`, `freezer` | -18.0 | 0.90 | Standard freezer |
| `warm`, `in the car`, `summer` | 30.0 | 0.65 | Warmer than room temp |
| `hot` | 40.0 | 0.60 | Hot conditions |
| `cold` | 10.0 | 0.70 | Cold but not refrigerated |
| `cool` | 15.0 | 0.70 | Cool conditions |
| `counter`, `bench`, `table` | 25.0 | 0.80 | Implies room temp |
| `left out`, `sitting out`, `sat out` | 25.0 | 0.75 | Implies ambient |
| `unrefrigerated`, `out of the fridge` | 25.0 | 0.80 | No refrigeration |
| `ambient` | 25.0 | 0.80 | Environmental temperature |
| `in my bag` | 25.0 | 0.70 | Body heat proximity |

### Duration Interpretations

| Pattern | Value (min) | Confidence | Notes |
|---------|-------------|------------|-------|
| `overnight` | 480 | 0.75 | ~8 hours |
| `all day` | 600 | 0.70 | ~10 hours |
| `few hours`, `couple hours`, `couple of hours` | 120-180 | 0.70 | 2-3 hours |
| `half a day` | 360 | 0.70 | ~6 hours |
| `briefly`, `few minutes` | 10-15 | 0.80 | Short exposure |
| `a while`, `some time`, `an hour` | 60 | 0.65 | ~1 hour |
| `long time`, `many hours` | 360 | 0.60 | Extended period |
| `all night` | 480 | 0.75 | Same as overnight |

### Bias Correction Rules

| Rule Name | Correction Type | Factor | Condition |
|-----------|-----------------|--------|-----------|
| `inferred_duration_margin` | multiply | 1.2 | Duration was inferred (not explicit) |
| `temperature_range_upper` | use_upper | — | Temperature given as range |
| `duration_range_upper` | use_upper | — | Duration given as range |
| `low_confidence_temperature_bump` | add | +5.0°C | Retrieval confidence < 0.5 |

### Embedding Similarity Fallback

When no rule matches exactly, the system uses embedding similarity to find the closest canonical phrase:

```python
# Novel phrase → closest canonical → interpretation
"sitting on the kitchen bench" → similar to "on the counter" → 25°C
"left in the vehicle" → similar to "in the car" → 30°C
```

**Similarity threshold:** 0.50 cosine similarity minimum

---

## Design Principles

### 1. Conservative Safety Bias

When uncertain, choose values that predict more bacterial growth:
- Temperature ranges → use upper bound
- Duration ranges → use upper bound
- pH ranges → use value closer to neutral (better for growth)
- Missing values → use growth-permissive defaults

**Rationale:** In food safety, false negatives (declaring unsafe food as safe) are far worse than false positives.

### 2. User Priority

User-provided values are never overwritten by system inferences, even if the system has higher confidence.

**Rationale:** Users may have actual measurements or specific context. Respecting their input builds trust.

### 3. Full Transparency

Every value carries:
- Source (where it came from)
- Confidence (how certain we are)
- Transformation (what processing was applied)
- Original text (what we extracted from)

**Rationale:** Food safety decisions need to be auditable. Users should understand exactly how answers were determined.

### 4. Graceful Degradation

System continues with warnings rather than failing on missing data. Defaults are applied when necessary, with clear documentation.

**Rationale:** A conservative answer with documented assumptions is better than no answer.

### 5. Separation of Concerns

Scientific facts (RAG) and linguistic conventions (Rules) are handled separately:
- Scientific data can be updated as knowledge evolves
- Linguistic interpretations are stable conventions
- Different confidence characteristics for each

---

## Key Design Decisions

### Decision 1: CSV over Direct PDF Ingestion

**Choice:** Extract PDF data to structured CSV, then ingest CSV to vector store.

**Rationale:**
- PDF tables are poorly structured for semantic search
- Manual extraction allows quality verification
- CSV enables consistent schema and metadata
- Source tags can be added per-row

**Trade-off:** Manual effort vs. data quality. Worth it for authoritative sources.

### Decision 2: Semantic Documents over Raw Data

**Choice:** Transform CSV rows to natural language sentences before embedding.

**Example:**
```
Raw:    Listeria,1591,1455,255,94.0,15.9
Semantic: "Listeria monocytogenes epidemiology: 1591 annual illnesses..."
```

**Rationale:**
- Embedding models understand natural language better than tabular data
- Enables richer queries ("most dangerous pathogen" vs. exact column match)
- Context is preserved in each chunk

### Decision 3: Hybrid Citation System

**Choice:** Short source tag in document text (`[CDC-2011-T3]`) + full citation in metadata.

**Rationale:**
- LLM sees source during reasoning (can assess authority)
- Full citation available for bibliography generation
- Minimal document size increase (~10 chars)

### Decision 4: Rules vs. RAG Separation

**Choice:** Linguistic interpretations in rules, scientific facts in RAG.

**Rationale:**
- Different update cycles (language stable, science evolves)
- Different confidence characteristics
- Easier testing (rules are pure functions)
- Clear user understanding of value sources

### Decision 5: Embedding Fallback for Novel Phrases

**Choice:** When rule matching fails, use embedding similarity to find closest canonical phrase.

**Example:** "sitting on the kitchen bench" → similar to "left out on counter" → 25°C

**Rationale:**
- Impossible to enumerate all phrasings
- Embedding similarity handles paraphrases
- Graceful fallback if no match (default to safe value)

### Decision 6: Confidence of 0.90 for User Explicit

**Choice:** User-provided values get 0.90 confidence, not 1.0.

**Rationale:**
- Users can misremember or mistype
- LLM extraction might misparse
- Leaves room for uncertainty propagation
- Still clearly "HIGH" confidence

---

## Project Structure

```
project_root/
├── app/
│   ├── core/
│   │   ├── orchestrator.py          # Main pipeline coordinator
│   │   └── log_config.py            # Logging configuration
│   │
│   ├── services/
│   │   ├── extraction/
│   │   │   └── semantic_parser.py   # LLM-based extraction
│   │   ├── grounding/
│   │   │   └── grounding_service.py # Value resolution
│   │   ├── standardization/
│   │   │   └── standardization_service.py
│   │   └── llm/
│   │       └── client.py            # LiteLLM wrapper
│   │
│   ├── engines/
│   │   └── combase/
│   │       ├── engine.py            # Model execution
│   │       ├── calculator.py        # Mathematical calculations
│   │       └── models.py            # Model registry
│   │
│   ├── rag/
│   │   ├── vector_store.py          # ChromaDB interface
│   │   ├── retrieval.py             # Query service
│   │   ├── ingestion.py             # Document processing
│   │   ├── embeddings.py            # Embedding models
│   │   ├── loaders/                 # Format-specific loaders
│   │   │   ├── csv_loader.py
│   │   │   ├── pdf_loader.py
│   │   │   └── ...
│   │   └── data_sources/            # Domain-specific loaders
│   │       ├── food_safety.py
│   │       └── citations.py
│   │
│   ├── models/
│   │   ├── extraction.py            # Extraction models
│   │   ├── metadata.py              # Provenance models
│   │   ├── enums.py                 # Enumerations
│   │   └── execution/               # Execution payloads
│   │       ├── base.py
│   │       └── combase.py
│   │
│   └── config/
│       ├── settings.py              # Configuration
│       └── rules.py                 # Interpretation rules
│
├── cli/
│   └── rag_admin.py                 # RAG administration tool
│
├── data/
│   ├── rag/                         # Processed ingestion data
│   │   ├── food_properties.csv
│   │   ├── pathogen_characteristics.csv
│   │   └── ...
│   ├── sources/                     # Reference materials
│   │   ├── source_references.csv
│   │   ├── CDC_Scallan_2011.pdf
│   │   └── ...
│   ├── vector_store/                # ChromaDB persistence
│   └── combase_models.csv           # ComBase model parameters
│
├── scripts/                         # Manual test scripts
│   ├── test_semantic_parser.py
│   ├── test_combase_engine.py
│   ├── test_full_pipeline.py
│   ├── test_orchestrator.py
│   └── test_rag_retrieval.py
│
├── tests/                           # Unit tests
│   └── unit/
│       ├── test_grounding_service.py  # Grounding, numeric extraction
│       ├── test_rules.py              # Interpretation rules
│       ├── test_semantic_parser.py
│       └── ...
│
└── docs/
    ├── problem_translation_module.md    # This document
    ├── rag_data_sources_architecture.md
    ├── grounding_service_architecture.md
    └── rag_system.md
```

---

## Configuration

### Environment Variables

```bash
# LLM Configuration
LLM_MODEL=gpt-4-turbo           # Or claude-3-sonnet, ollama/llama2
LLM_API_KEY=sk-...               # API key for provider
LLM_API_BASE=                    # Optional: custom API base URL

# Paths
VECTOR_STORE_PATH=data/vector_store
COMBASE_MODELS_PATH=data/combase_models.csv

# RAG Settings
EMBEDDING_MODEL=all-MiniLM-L6-v2
CHUNK_SIZE=512
CHUNK_OVERLAP=50

# Confidence Thresholds
GLOBAL_MIN_CONFIDENCE=0.5
FOOD_PROPERTIES_CONFIDENCE=0.7
PATHOGEN_HAZARDS_CONFIDENCE=0.7

# Defaults (conservative)
DEFAULT_TEMPERATURE_ABUSE_C=25.0
DEFAULT_PH_NEUTRAL=6.5
DEFAULT_WATER_ACTIVITY=0.99
```

### Settings Module

All configuration is centralized in `app/config/settings.py` using Pydantic Settings for validation and environment variable loading.

---

## Testing Strategy

### Test Script Overview

| Script | Purpose | Tests |
|--------|---------|-------|
| `test_semantic_parser.py` | Extraction quality | Scenario extraction, intent classification |
| `test_combase_calculator.py` | Math correctness | μ_max calculation, growth at different temps |
| `test_combase_engine.py` | Engine execution | Single-step, multi-step, thermal models |
| `test_full_pipeline.py` | End-to-end | Complete translation from query to result |
| `test_orchestrator.py` | Coordination | Pipeline orchestration, error handling |
| `test_rag_retrieval.py` | RAG accuracy | Food properties, pathogen hazards queries |
| `test_rag_evaluation.py` | RAG metrics | MRR, nDCG with/without reranker |
| `test_llm_client.py` | LLM integration | Health check, extraction, complex scenarios |

### Running Tests

```bash
# Manual test scripts
python scripts/test_full_pipeline.py
python scripts/test_rag_retrieval.py

# Unit tests
pytest tests/unit/

# RAG administration
python -m cli.rag_admin status      # Check database
python -m cli.rag_admin --clear     # Clear and reload
python -m cli.rag_admin verify      # Run verification queries
```

### Unit Test Coverage

#### Grounding Service Tests (`test_grounding_service.py`)

| Test Class | Tests |
|------------|-------|
| `TestGroundedValues` | set/get, defaults, provenance tracking, ungrounded marking |
| `TestExtractNumericValue` | Single values, ranges (hyphen, "and", "to"), keywords |
| `TestGroundEnvironmentalConditions` | Explicit pH/aw, multiple conditions, None handling |
| `TestGroundDuration` | Explicit values, ranges (upper bound), descriptions |
| `TestGroundScenario` | User priority over RAG, RAG skipped when not needed, pathogen grounding |
| `TestExtractFoodProperties` | Regex extraction, range extraction |
| `TestSingleton` | Singleton pattern, reset behavior |

**Key behaviors verified:**
- User explicit values (confidence 0.90) are never overwritten by RAG
- Ranges use upper bound for conservative bias
- RAG is only called when necessary (missing pH, aw, or pathogen)
- Numeric extraction handles various formats: `pH 6.0`, `pH: 6.5`, `pH 5.9-6.2`, `pH between 5.5 and 6.0`

#### Rules Tests (`test_rules.py`)

| Test Class | Tests |
|------------|-------|
| `TestTemperatureInterpretations` | 20+ patterns including room temp, fridge, car, counter |
| `TestDurationInterpretations` | 15+ patterns including overnight, all day, briefly |
| `TestBiasCorrections` | Duration margin, range upper, temperature bump |
| `TestRuleDataStructureIntegrity` | All rules have required fields, reasonable values |
| `TestRuleNotes` | All rules have explanatory notes |

**Key behaviors verified:**
- Case-insensitive matching
- Longer patterns match before shorter ones
- Temperature values are in range -30°C to 60°C
- Duration values are in range 1 to 1440 minutes (24 hours)
- No duplicate patterns or rule names

### Verification Queries

The RAG system includes built-in verification queries:

| Query | Expected |
|-------|----------|
| "chicken pH" | Chicken food properties |
| "Salmonella water activity" | Salmonella growth parameters |
| "Listeria case fatality rate" | Listeria epidemiology with 15.9% |
| "Vibrio vulnificus mortality" | V. vulnificus with 34.8% CFR |
| "norovirus foodborne transmission" | Norovirus 26% foodborne |

---

## Current Status and Roadmap

### Current Status (Phase 9 Complete)

| Component | Status | Notes |
|-----------|--------|-------|
| Semantic Parser | ✅ Complete | LLM extraction working |
| Grounding Service | ✅ Complete | Rules + RAG integration |
| Standardization Service | ✅ Complete | Defaults, clamping, bias |
| ComBase Engine | ✅ Complete | Growth + thermal models |
| RAG System | ✅ Complete | ChromaDB + reranking |
| RAG Data Population | ✅ Complete | 7 CSV files, 11 sources |
| Orchestrator | ✅ Complete | Full pipeline coordination |
| Documentation | ✅ Complete | Architecture docs |

### Roadmap

| Phase | Focus | Status |
|-------|-------|--------|
| 10 | **Result Interpretation** | Pending |
| | Model output → natural language explanation | |
| | Risk communication appropriate to audience | |
| 11 | **Multi-step Scenarios** | Pending |
| | Sequential time-temperature handling | |
| | Transport → storage → display chains | |
| 12 | **Clarification Loop** | Pending |
| | Interactive user clarification for missing data | |
| | Confidence-triggered questions | |
| 13 | **Production** | Pending |
| | Docker deployment, CI/CD, monitoring | |
| | API endpoints, rate limiting | |

### Future Enhancements

- **Hybrid Search**: Combine vector similarity with BM25 keyword matching
- **Regional Variations**: "Room temperature" varies by region/climate
- **Seasonal Adjustments**: "Left in the car" differs summer vs. winter
- **Multiple Pathogens**: Parallel analysis for all relevant pathogens
- **Uncertainty Propagation**: Carry confidence through to final predictions
- **Mobile Applications**: Real-time food safety decisions
- **Integration APIs**: Connect to food safety management systems

---

## Extending the System

### Adding a New Data Source

1. **Prepare the source document** in `data/sources/`
2. **Extract to CSV** with standardized schema in `data/rag/`
3. **Add source reference** to `data/sources/source_references.csv`
4. **Create loader function** in `app/rag/data_sources/food_safety.py`
5. **Register in aggregator** `load_all_sources()`
6. **Run bootstrap**: `python -m cli.rag_admin --clear --verify`

### Adding a New Interpretation Rule

1. **Add rule** to `app/config/rules.py`:
```python
InterpretationRule(
    pattern="in the sun",
    value=35.0,
    confidence=0.65,
    notes="Direct sunlight, can get warm"
)
```
2. **Add canonical phrases** for embedding fallback
3. **Add test case**

### Adding a New Pathogen

1. **Add to `ComBaseOrganism` enum** in `app/models/enums.py`
2. **Add fuzzy matching aliases** in `_get_fuzzy_map()`
3. **Add model parameters** to `data/combase_models.csv`
4. **Add RAG documents** for pathogen characteristics

---

## Glossary

| Term | Definition |
|------|------------|
| **aw (Water Activity)** | Measure of water available for microbial growth (0-1 scale) |
| **CFR (Case Fatality Rate)** | Percentage of infections resulting in death |
| **ComBase** | Database of predictive microbiology models |
| **Grounding** | Converting vague descriptions to precise values |
| **μ_max** | Maximum specific growth rate (1/hour) |
| **Provenance** | Record of where a value came from and how it was processed |
| **RAG** | Retrieval-Augmented Generation |
| **TCS** | Time/Temperature Control for Safety (food classification) |
| **Thermal Inactivation** | Pathogen death during heating/cooking |

---

## References

### Authoritative Sources

1. Scallan E, et al. (2011). Foodborne Illness Acquired in the United States—Major Pathogens. *Emerging Infectious Diseases*, 17(1):7-15. doi:10.3201/eid1701.P11101

2. Institute of Food Technologists. (2003). Evaluation and Definition of Potentially Hazardous Foods. *Comprehensive Reviews in Food Science and Food Safety*, 2(s1):1-108. doi:10.1111/j.1541-4337.2003.tb00052.x

3. FDA/CFSAN. (2007). Approximate pH of Foods and Food Products.

4. FDA/CFSAN. (2012). Bad Bug Book: Foodborne Pathogenic Microorganisms and Natural Toxins Handbook, 2nd Edition.

### Internal Documentation

- `rag_data_sources_architecture.md` — RAG data ingestion system design
- `grounding_service_architecture.md` — Grounding service design
- `rag_system.md` — RAG system technical documentation

### Technology References

- [LiteLLM Documentation](https://docs.litellm.ai/)
- [Instructor Documentation](https://python.useinstructor.com/)
- [ChromaDB Documentation](https://docs.trychroma.com/)
- [ComBase Database](https://www.combase.cc/)

---

*Last updated: 2026-03-19*
