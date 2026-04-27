# Problem Translation Module (PTM) — Session Context

**Version:** 1.1
**Date:** 2026-04-25
**Purpose:** Self-contained context document for new Claude sessions working on PTM. Feed this document in at the start of any session and work from it rather than from cross-session memory.

---

## How to use this document

This document is the **authoritative source of truth** for PTM context at the date above. In any session where it is provided:

- Base your answers and reasoning on this document, not on prior-session memories about PTM. Memories may be stale or conflated; this document is current.
- If you encounter a gap — something you need to reason about that is not covered here — **stop and ask**. Do not infer from prior memory. Expanding the document is preferred over silent assumption.
- When the user updates the project meaningfully, ask them to update this document's changelog and re-feed it in new sessions.

**Naming:** Throughout this document, the project is referred to as **PTM (Problem Translation Module)**. "Problem Interpretation Module" is a tentative name for a broader project of which PTM is the first component; a future result-interpretation module will be the second. If you encounter "Problem Interpretation Module" in config or old code (e.g., `app.app_name`), treat it as a naming inconsistency, not a different system.

**Conventions used in this document:**
- ✅ = done / closed
- 🟡 = in progress / partially addressed
- 🔴 = open / not yet started
- ❓ = unconfirmed / needs verification with the user

---

## 1. Project context

### 1.1 What PTM is

PTM translates natural-language food safety queries into precise, scientifically-grounded parameters for predictive microbiology models (the ComBase family). It takes a user question like *"Is raw chicken safe after sitting on the counter for 3 hours?"* and produces a structured execution payload — food, pathogen, temperature, duration, pH, water activity, model type — that a ComBase calculator can run. It returns the mathematical result (μ_max, doubling time, log increase/reduction) along with full provenance for every input value.

**What PTM does not do:**
- Interpret or communicate results in natural language. That is the job of the future **Result Interpretation Module** (not built yet).
- Ask the user clarifying questions interactively. Currently the system makes assumptions with documented provenance when information is missing. An interactive clarification loop is planned for Phase 12.

### 1.2 The broader project

The overall project was tentatively named **"Problem Interpretation Module"** and is envisioned as a two-stage pipeline:

1. **PTM (this project)** — natural language → scientifically-grounded model parameters → model execution → raw mathematical output.
2. **Result Interpretation Module (planned)** — raw mathematical output → natural-language guidance calibrated to the audience.

All work in this session context is scoped to PTM unless stated otherwise.

### 1.3 Who is working on it

Daniel is the lead engineer. He is a Senior AI Engineer at the FoodigIT Centre with a physics background, ~25 years of software/AI engineering experience (space data pipelines, ML in finance, large-scale data architectures), and is the original IT architect of ComBase. He has a longstanding research collaboration with Professor Baranyi. His current focus is bringing AI into the Centre's research workflow and generating publications. He works in a cross-border context with European institutions and is based in Spain.

### 1.4 Working preferences

These preferences apply throughout:

- **Start simple; add complexity iteratively.** Do not pre-optimize.
- **Readable, simple code over DRY abstractions.** If two places need similar logic with small variations, duplicate rather than abstract.
- **Ask clarifying questions rather than make assumptions.**
- **Concise responses.** No redundant preamble or summaries of what was just said.
- **Explanatory code comments** that convey meaning and how to interpret metrics, not just what the code does.
- **Sequential walkthroughs** when explaining — one element at a time, with thorough conceptual grounding.

---

## 2. Scientific philosophy and project vision

This section captures the scientific framing and strategic vision behind PTM. It is the "why", not the "how", and it is the lens through which proposed features, simplifications, and trade-offs should be evaluated. The philosophy is **not immutable** — it can evolve through discussion. But it should be the default reference frame for design decisions until explicitly revised.

### 2.1 The thesis

Predictive microbiology has spent decades refining two layers of mathematical models:

- **Primary models** (e.g., Baranyi) describe bacterial population dynamics over time.
- **Secondary models** describe how those dynamics respond to environmental conditions (temperature, pH, aw, fourth factors).

In practice these are treated as one composite model — when an operator uses ComBase, they are using primary + secondary together — and that composite has been refined to a high degree of accuracy. **What has been left outside the modelling landscape is the human input/output layer.** A risk assessor poses an ambiguous question; the operator parameterises it through their own interpretation, biases, and gaps in knowledge; the model returns a number; another human translates that number into an actionable conclusion. The math in the middle is precise; the bookends are not. Human-induced variability has historically been unmodellable, and the total uncertainty of the food safety assessment has been correspondingly intractable.

The thesis of this project is that **LLMs, for the first time, allow the human input/output layer to be modelled, instrumented, and reduced to manageable variability** — bringing the entire risk assessment workflow inside the modelling landscape rather than leaving its bookends outside.

PTM is the input-side instantiation of this thesis. It models the translation from natural-language food safety queries to mathematical model parameters. The future Result Interpretation Module will model the output side.

> **Note on empirical status.** The claim "human-induced variability is the dominant *reducible* source of uncertainty in food safety assessment" is the rhetorical core of the project. It has not yet been quantitatively proven against alternative uncertainty sources (model structural error ~2–4×, strain variability, measurement error). Two studies are planned to address this — a Sobol-style variance decomposition and a paired human-vs-system comparison study (see §12, concern #1). Until those land, the philosophy stands as the design hypothesis; the empirical work will validate, refine, or refute it.

### 2.2 The Holistic Risk Model — three layers

The project's framing of a complete food safety assessment is a three-layer composite model:

| Layer | What it does | Status |
|---|---|---|
| **Layer 1 — Problem Interpretation (LLM)** | Translates natural-language queries into mathematical model parameters with curated, cited values | PTM (this project) |
| **Layer 2 — Predictive (math)** | Existing primary + secondary models calculating bacterial dynamics under environmental conditions | Existing (ComBase ecosystem) |
| **Layer 3 — Result Interpretation (LLM)** | Translates numerical model output into safety insights, regulatory actionables, audience-appropriate guidance | Future module |

PTM is the **standardisation layer ahead of the predictive models**. Its purpose is to ensure that whatever query a human poses, the predictive model receives a well-formed, bibliographically-grounded set of parameters.

### 2.3 The three work packages

The broader project is organised into three work packages. PTM is WP1.

| WP | Focus | Status |
|---|---|---|
| **WP1** | Automatic Problem Interpreter — natural-language query → standardised model parameters (PTM) | Active focus |
| **WP2** | Enhanced secondary models using ML/DL techniques | Future |
| **WP3** | Real-time decision support tool — model output → HACCP actionables, regulatory compliance guidance | Future (depends on WP1) |

WP3 is where the regulatory value is highest, but it depends on WP1 being solid. WP1 is therefore the foundation deliverable.

### 2.4 What PTM is targeting — two distinct sources of variability

PTM is designed to attack **two different kinds of variability simultaneously**, and it is important to keep them distinct because they require different solutions.

#### A. Human variability

The operator's interpretation is the dominant source of error in current practice. Specific failure modes:

- **Hidden variables.** When an operator uses ComBase manually for "cooked turkey breast left out", they typically input temperature and time but ignore pH and aw — leaving them at neutral defaults (often pH 7.0). Small changes in these values drastically alter the predicted growth curve. PTM eliminates this by retrieving authoritative pH/aw for the named food matrix from RAG.
- **Optimistic / confirmation bias.** Given a temperature range "10–15 °C", an operator under economic pressure tends to choose 12.5 °C (average) or 10 °C (favourable) to avoid discarding a batch. PTM applies an unwavering precautionary principle (model-type-aware — see §8.1) so the conservative choice is structurally enforced rather than left to operator judgement.
- **Hazard mis-identification.** An operator may select a generic "Total Viable Count" or fail to identify the relevant pathogen for the specific food matrix. PTM infers the matrix-relevant hazard from food-pathogen association data.
- **Vague time-temperature profiling.** Real-world scenarios involve dynamic conditions (a truck losing refrigeration over hours, a dish cooling). PTM decomposes a narrative into discrete time-temperature steps for the predictive engine.

The aspiration here is not just "get the right value" — it is **standardisation**. The same ambiguous query, asked twice, must produce the same standardised parameters. PTM is, in effect, a "standardised parameter extraction protocol" that turns subjective operator interpretation into a reproducible process.

#### B. LLM stochasticity

The LLM that does the interpretation is itself a probabilistic system, which creates a tension at the heart of the project: the system is meant to reduce variability, but its first stage introduces some. Experiment 1.1 (§7.1) measures this directly — Monte Carlo queries of frontier models for the pH of foods like ceviche or kimchi return distributions wide enough to flip safety conclusions (§7.1 propagates pH variance through a ComBase growth model to demonstrate this).

The answer is **RAG with curated sources**: LLM knowledge is constrained — bounded — to authoritative documents (USDA FoodData Central, FDA pH list, IFT/FDA PHF report, CDC epidemiology, etc.). The LLM is not asked to *know* the pH of chicken; it is asked to *use* the cited authority for it. This delivers:

- **Reproducibility:** the same query produces the same standardised values (within the determinism the curated database supplies).
- **Bibliographic validation:** every value carries its source. This is a regulatory and audit requirement, not just a nice-to-have.
- **Reduced input variability:** the LLM's role becomes interpretation and routing, not knowledge retrieval.

For values not cleanly retrievable (e.g., converting salt percentage to aw, multi-step lookups), an agentic approach with tool calls is the future direction.

### 2.5 Scientific framing — language for biology-oriented audiences

When presenting PTM to wet-lab or experimental audiences, the project must be framed as **methodological science, not software engineering**. Five framings work well together:

- **Reproducibility and methodological standardisation.** Predictive models are useless if different operators feed them different inputs from the same scenario. PTM quantifies and reduces inter-operator variability — that is itself a scientific contribution.
- **Bibliographic validation.** RAG over curated sources functions as an "automated systematic review", binding every prediction to traceable, published authority. This addresses the "data hallucination" problem in applied predictive microbiology.
- **Translational science.** The best published microbiological model is unused if industry cannot parameterise it correctly. PTM is implementation engineering for translation between operator vocabulary and model syntax.
- **Isothermal-to-dynamic.** Lab studies are mostly isothermal; reality is dynamic. PTM's multi-step time-temperature decomposition validates predictive models in non-linear dynamic conditions that cannot be replicated statically in a Petri dish.
- **PTM as a real-time quality auditor.** The system's role is not to "think" but to act as a structured filter that intercepts operator simplifications and enforces conservative, source-validated inputs *before* the data touches the predictive model.

The validation argument: PTM is not "an AI that thinks about food safety". It is a protocolised interpretation method whose accuracy can be — and will be — empirically compared to manual human operators.

### 2.6 RAG vs. frontier-model web search — why curation still matters

A reasonable question, given the rate at which frontier models (GPT-5, Gemini 3, etc.) gain web-search capabilities: does an open-web-search frontier model make RAG redundant? **No, and the reasoning matters because the answer shapes how PTM is designed and defended in publications.**

| Concern | Web-search frontier model | PTM with curated RAG |
|---|---|---|
| **Source authority** | Optimises for relevance; may surface a high-SEO cooking blog over a USDA technical note | Retrieves only from authoritative scientific sources |
| **Determinism** | Output drifts as the web (and the model's search algorithm) changes; same query may produce different outputs across days | Same query produces the same value until the curated DB is deliberately updated |
| **Tabular data access** | Web crawlers handle structured tables (USDA databases, ComBase exports, CSVs behind search forms) poorly | Direct, structured access to the curated tables |
| **Liability and audit trail** | "The model retrieved this from somewhere on the web" | "The curated database, sourced from the cited regulatory document, states this" |
| **Latency and cost** | Higher (multi-second search, higher token cost) | Lower (local embeddings, single retrieval round) |

The framing for publications: **RAG is not an information-retrieval tool, it is a regulatory safety filter.** Web search optimises for relevance; PTM's RAG optimises for authority. Industry and regulators will not entrust million-dollar batch-disposition decisions to a Google-search-equivalent. The existence of capable web-search models *strengthens* the case for curated RAG by making the alternative concrete and visibly inferior for this specific use case.

A planned comparative study (cited in concern #5, §12) will measure PTM-with-RAG accuracy against an open-web-search frontier model on the same queries, expected to demonstrate reduced variance and elimination of un-cited sources.

### 2.7 Strategic vision — the ComBase integration target

The MVP of PTM can run as a standalone web service. Its **highest-impact deployment**, however, is as an integrated interpretation layer inside ComBase itself.

ComBase is the daily driver for USDA regulators and industry HACCP planners; it has substantially greater reputational weight in applied predictive microbiology than any single university or research centre. Embedding PTM inside ComBase transforms it from a calculator into an **AI-driven food safety risk assistant**, enabling:

- HACCP plan validation without expensive challenge studies
- Real-time field assessments by regulators
- Standardised parameterisation across the regulator/industry boundary

This is also a reproducibility multiplier: when many users access the same canonical interpretation layer, inter-operator variability collapses across the entire regulatory ecosystem, not just within one organisation. The technical and political dimensions of this integration are tracked as concern #8 in §12.

### 2.8 What this philosophy means for ongoing work

In short, the philosophy frames every design conversation as: *does this proposal increase reproducibility, increase bibliographic groundedness, reduce inter-operator variability, or improve translational accessibility — without silently overriding user judgement or hiding sources?* If yes, it is aligned. If it does the opposite, it warrants pushback or a clear scientific justification for the trade-off.

The philosophy is a **guide, not a constraint**. It is expected to evolve as the empirical work (sensitivity analysis, human-vs-system comparison, cumulative bias quantification) generates evidence. When it does evolve, this section should be updated and the changelog entry should record what shifted and why.

---

## 3. Architecture overview

### 3.1 The five-stage pipeline

```
User query
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ 1. SEMANTIC PARSER                                              │
│    LLM + Instructor extracts ExtractedScenario                  │
│    (food, temperature, duration, pathogen, environmental        │
│    conditions, implied_model_type, is_multi_step)               │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. GROUNDING SERVICE                                            │
│    Resolves vague terms via interpretation rules                │
│    ("room temperature" → 25 °C) and retrieves food              │
│    properties (pH, aw), pathogen associations via RAG.          │
│    Tracks provenance and confidence per value.                  │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. STANDARDIZATION SERVICE                                      │
│    Applies conservative defaults for missing values, clamps     │
│    to model-valid ranges, applies bias corrections (direction   │
│    now correctly flips by model type — see §8.1), builds the    │
│    ComBase execution payload.                                   │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. MODEL EXECUTION (ComBase engine)                             │
│    Selects the correct ComBase model (growth / thermal          │
│    inactivation / non-thermal survival), runs the calculator,   │
│    returns μ_max, doubling time, log change, per-step           │
│    predictions for multi-step profiles.                         │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. ORCHESTRATOR                                                 │
│    Coordinates the above, manages SessionState and              │
│    InterpretationMetadata, returns TranslationResult with       │
│    full provenance, warnings, corrections, retrievals.          │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
TranslationResult (to caller — API or Streamlit)
```

### 3.2 Supporting systems

- **RAG knowledge base** — ChromaDB vector store with ~7 CSV-derived data files (food properties, pathogen characteristics, pathogen-food associations, pathogen aw limits, TCS classification rules, pathogen transmission, food-pathogen hazards). Embeddings via `all-MiniLM-L6-v2`, optional reranking via `cross-encoder/ms-marco-MiniLM-L-6-v2`. See §6.
- **Interpretation rules** — static rule table mapping linguistic phrases to numeric values (e.g., "overnight" → 480 min at confidence 0.75), with an embedding-similarity fallback for novel phrases (0.50 cosine threshold). See §5.2.
- **ComBase model registry** — loaded from `data/combase_models.csv`. 15 organisms; supports growth, thermal inactivation, and non-thermal survival model types, with optional fourth-factor support (CO₂, lactic acid, acetic acid, nitrite).

---

## 4. Technology stack

| Category | Technology |
|----------|-----------|
| Language | Python 3.11+ |
| Web framework | FastAPI (API endpoints are live; `/api/v1/translate` is covered by tests) |
| LLM integration | LiteLLM + Instructor (structured outputs) |
| Vector database | ChromaDB (PersistentClient) |
| Embeddings | sentence-transformers `all-MiniLM-L6-v2` (384-dim, normalised) |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| Data validation | Pydantic v2 |
| IR evaluation | ranx (MRR, nDCG) |
| Benchmark tracking | MLflow (local SQLite backend due to Windows path issues) |
| Benchmark UI | Streamlit + Plotly Express |

**LLM providers supported via LiteLLM:** OpenAI (gpt-4o, gpt-4-turbo, gpt-3.5-turbo), Anthropic (claude-3-sonnet, claude-3-haiku), Ollama (local). Fourteen models across five tiers are evaluated in the benchmark suite (see §7).

---

## 5. Component deep-dives

### 5.1 Semantic Parser
**Location:** `app/services/extraction/semantic_parser.py`

Uses Instructor over LiteLLM to extract an `ExtractedScenario` Pydantic model from a natural-language query. Three public async methods:

- `extract_scenario(user_input, conversation_context=None) → ExtractedScenario`
- `classify_intent(user_input) → ExtractedIntent` (prediction request vs. information query vs. ambiguous)
- `extract_clarification_response(user_response, original_question, options=None)` — for future interactive clarification loop (Phase 12)

Three system prompts: `SCENARIO_EXTRACTION_PROMPT`, `INTENT_CLASSIFICATION_PROMPT`, `CLARIFICATION_RESPONSE_PROMPT`.

**Key extracted fields:**
- `food_description`, `food_state`, `pathogen_mentioned`
- `is_multi_step` (bool) + either `single_step_temperature`/`single_step_duration` or `time_temperature_steps[]`
- `environmental_conditions` (ph_value, water_activity)
- `implied_model_type` — growth / thermal_inactivation / non_thermal_survival

### 5.2 Grounding Service
**Location:** `app/services/grounding/grounding_service.py`

Resolves `ExtractedScenario` fields into a `GroundedValues` container with full provenance.

**Resolution hierarchy (highest priority first):**

| Priority | Source | Confidence | Description |
|---|---|---|---|
| 1 | USER_EXPLICIT | 0.90 | User stated the value directly ("temperature was 25 °C") |
| 2 | USER_INFERRED | 0.65–0.85 | Value from interpretation rules ("room temperature" → 25 °C) |
| 3 | RAG_RETRIEVAL | 0.50–0.95 | Value retrieved from knowledge base |
| 4 | CONSERVATIVE_DEFAULT | ~0.30–0.50 | Safety-first fallback (applied in standardization) |

**Invariant:** higher-priority sources are never overwritten by lower-priority ones.

**Two knowledge types, handled separately:**
- **RAG** — scientific facts (food pH, aw, pathogen associations). Updates as science evolves.
- **Rules** — linguistic conventions ("room temperature" = 25 °C). Stable.

**Numeric extraction from text:** regex handles single values (`pH 6.0`), ranges with hyphen (`pH 5.9-6.2`), ranges with "to" (`pH 5.5 to 6.0`), ranges with "and" (`pH between 5.5 and 6.0`). When ranges are extracted, the upper bound is used (conservative for growth; see §8.1 for the model-type-aware directionality fix).

**Interpretation rules (excerpt):**

Temperature: `room temperature`/`counter`/`ambient`/`left out` → 25 °C; `refrigerated`/`fridge`/`chilled` → 4 °C; `frozen`/`freezer` → -18 °C; `warm`/`in the car`/`summer` → 30 °C; `hot` → 40 °C; `cold` → 10 °C; `cool` → 15 °C. Confidence ranges 0.60–0.90.

Duration: `overnight`/`all night` → 480 min; `all day` → 600 min; `few hours`/`couple of hours` → 120–180 min; `half a day` → 360 min; `briefly`/`few minutes` → 10–15 min; `long time`/`many hours` → 360 min.

When no rule matches, embedding similarity finds the closest canonical phrase (0.50 cosine threshold); below threshold, field is marked ungrounded.

### 5.3 Standardization Service
**Location:** `app/services/standardization/standardization_service.py`

Prepares `GroundedValues` for model execution: applies conservative defaults for still-missing values, clamps values to the selected ComBase model's valid ranges, applies model-type-aware bias corrections, builds the `ComBaseExecutionPayload`.

**Conservative defaults:**
- `default_temperature_abuse_c = 25.0`
- `default_ph_neutral = 6.5` (note: some places in config read 7.0; pre-April default; §12 lists this as a minor inconsistency to verify)
- `default_water_activity = 0.99`

**Bias correction types** (tracked in `StandardizationResult.bias_corrections[]`):
- `OPTIMISTIC_DURATION` — ±20 % for inferred durations (sign depends on model type — see §8.1)
- `OPTIMISTIC_TEMPERATURE` — ±5 °C bump for low-confidence temperatures
- `MISSING_VALUE_IMPUTED` — default applied
- `OUT_OF_RANGE_CLAMPED` — value clamped to model valid range

### 5.4 ComBase Engine
**Location:** `app/engines/combase/`

- `engine.py` — entry point. Singleton via `get_combase_engine()`. Loads models at startup.
- `calculator.py` — mathematical core (`bw` computation, μ_max, doubling time, log change). Different `bw` formulas for growth vs. thermal inactivation: growth uses `bw = √(1 − aw)`, thermal inactivation uses `bw = aw`.
- `models.py` — `ComBaseModel`, `ComBaseModelConstraints`, `ComBaseModelRegistry`. Models are loaded from `data/combase_models.csv` with 15-coefficient polynomial strings.

**Model types supported** (from `ModelType` enum):
1. `GROWTH` — positive μ_max, doubling time defined
2. `THERMAL_INACTIVATION` — negative μ_max (kill rate), no doubling time
3. `NON_THERMAL_SURVIVAL` — for acid exposure, drying, nitrite, etc.

**Fourth-factor types** (`Factor4Type`): NONE, CO2, LACTIC_ACID, ACETIC_ACID, NITRITE.

**Supported organisms (15):** Salmonella, Listeria monocytogenes, E. coli, Staphylococcus aureus, Bacillus cereus, C. botulinum (proteolytic + non-proteolytic), C. perfringens, Yersinia enterocolitica, Pseudomonas, and others in `ComBaseOrganism`.

**Multi-step execution:** accepts a `TimeTemperatureProfile` with ordered `TimeTemperatureStep`s; accumulates log change across steps. Validated in `TimeTemperatureProfile` Pydantic model (step order contiguous, sum of step durations matches `total_duration_minutes`).

**Implementation note — model form (❓ to verify):** The main technical documentation and some code paths describe the engine as Baranyi primary with a second-order polynomial secondary. An advisory-board critique (see §11, concern #8) referred to it as "a standalone Ratkowsky implementation". Per the April advisory-review record, the authoritative implementation is Baranyi + 2nd-order polynomial secondary; a documentation/code inconsistency around Ratkowsky was surfaced and is being tracked.

### 5.5 Orchestrator
**Location:** `app/core/orchestrator.py`

Coordinates the full pipeline. Singleton via `get_orchestrator()`. Returns a `TranslationResult` with `.success`, `.error`, `.state` (SessionState), `.execution_result`, `.metadata` (InterpretationMetadata with provenance, bias corrections, retrievals, warnings, overall confidence).

Session state transitions go through `SessionStatus` (PENDING → EXTRACTING → GROUNDING → STANDARDIZING → EXECUTING → COMPLETED / FAILED).

### 5.6 Metadata & provenance
**Location:** `app/models/metadata.py`

- `ValueProvenance` — source, confidence, retrieval_source, original_text, transformation_applied
- `BiasCorrection` — bias_type, field_name, original_value, corrected_value, correction_reason, correction_magnitude
- `RangeClamp` — field_name, original_value, clamped_value, valid_min, valid_max, reason
- `RetrievalResult` — query, confidence_level, confidence_score, source_document, retrieved_text, fallback_used
- `ClarificationRecord` — for future interactive clarification
- `InterpretationMetadata` — top-level container with session_id, original_input, status, provenance dict, lists of corrections/clamps/retrievals/clarifications, warnings, `compute_overall_confidence()` method

**Overall confidence formula** (from `compute_overall_confidence()`): `min(field confidences) − 0.05 × len(bias_corrections) − 0.10 × len(low-confidence retrievals)`, clamped to [0, 1].

---

## 6. Data sources and RAG knowledge base

### 6.1 Authoritative sources

Four primary source documents, 14 registered source-IDs (tracked in `data/sources/source_references.csv`):

| Source ID | Document | Publisher | Year | Role |
|-----------|----------|-----------|------|------|
| CDC-2011-T2 / T3 / A1 | *Foodborne Illness Acquired in the United States—Major Pathogens* (Scallan et al.) | CDC / EID | 2011 | Historical pathogen epidemiology baseline |
| CDC-2019-T1T2 / A3 | *Foodborne Illness … 2019* (Scallan Walter et al.) | CDC / EID | 2025 | Current pathogen epidemiology (2019 data) |
| IFT-2003-T1 / T31 / T32 / T33 / TA / TB | *Evaluation and Definition of Potentially Hazardous Foods* | IFT/FDA | 2003 | Food parameters, TCS rules, pathogen-food associations, pathogen aw limits |
| FDA-PH-2007 | *Approximate pH of Foods and Food Products* | FDA/CFSAN | 2007 | Food pH values (~400 foods) |
| FDA-BBB-2012 | *Bad Bug Book*, 2nd Edition | FDA/CFSAN | 2012 | Pathogen characteristics (uploaded to repo; usage is partial) |

**2011 → 2019 epidemiology update (critical ranking change):** The CDC 2019 data are incorporated as a merged dataset with 2011 for backward comparison. Key change: Campylobacter now causes more deaths (197) than norovirus (174), reversing the 2011 ranking. Salmonella deaths down from 378 → 238, Listeria 255 → 172, Toxoplasma 327 → 44.

### 6.2 Processed data files

| File | Records | Source | Content |
|------|---------|--------|---------|
| `food_properties.csv` | 252 (post-audit) | FDA-PH-2007 + IFT-2003-T31/T33 | pH, water activity per food |
| `pathogen_characteristics.csv` | 30 | CDC-2011-T3 (+ merge with CDC-2019 pending — see below) | Annual illnesses, deaths, CFR |
| `pathogen_transmission_details.csv` | 27 | CDC-2011-A1 | Transmission routes, % foodborne |
| `pathogen_food_associations.csv` | 46 | IFT-2003-T1 | Food category → pathogen mapping |
| `pathogen_aw_limits.csv` | 14 | IFT-2003-T32 | Minimum aw for pathogen growth |
| `tcs_classification_tables.csv` | 25 | IFT-2003-TA / TB | TCS classification rules |
| `food_pathogen_hazards.csv` | — | Derived from IFT-2003-T1 + CDC-2011-T3 | Food-pathogen hazard records |

### 6.3 Extraction and audit history

**2026-03-11** — Initial extraction from 5 source PDFs, performed by a prior Claude model (Opus 4.5).
**2026-04-17** — Full audit pass. Key corrections in `food_properties.csv`:
- 7 fabricated rows removed (beef ripened, lamb, pork, turkey roasted, avocado duplicate, mayonnaise, salsa — not present in any attached source, hallucinated from LLM training data).
- Chicken pH corrected from 6.5–6.7 (incorrect) to **6.2–6.4 (IFT-2003-T33)**. Highest-impact single error, as chicken pH directly affects Salmonella and Campylobacter growth predictions.
- 4 `WRONG_SOURCE` corrections for meats (butter, beef ground, ham, veal): values were correct but wrongly attributed to FDA-PH-2007; actual source is IFT-2003-T33. This is classic LLM cross-source contamination during multi-document extraction.
- 2 aw value corrections (bread white 0.93 → 0.94; maple syrup 0.90 → 0.85).
- 4 source annotation fixes for rows where pH came from one source and aw from another.

**Recommended process for future updates** (per post-audit notes):
1. One PDF per extraction session — never process multiple source PDFs in the same LLM context (the dominant error mode is cross-source contamination).
2. Verification pass with only the single source PDF, quoting exact source text for each extracted value.
3. Human stratified spot-check: minimum 5 % per source × per food category.
4. Automated range checks (pH 0–14, aw 0–1.00, source_id must match a registered source).
5. For aw data: USDA FoodData Central is a future target for food-specific aw (replacing the category-level IFT estimates).

**Open items:**
- 🟡 CDC-2019 2019-data rows not yet merged into `pathogen_characteristics.csv`; the source_id is registered but no rows currently use it.
- 🟡 `data_year` and `notes` columns specified in schema are absent from `pathogen_characteristics.csv`.
- 🟡 `food_pathogen_hazards.csv` `annual_deaths_us` represents pathogen totals across all food sources, not food-specific deaths — potential interpretive issue for food-scoped RAG queries.

### 6.4 RAG system (ChromaDB)

- Single ChromaDB collection (`knowledge_base`) with metadata filtering by doc_type.
- Document types: `food_properties`, `pathogen_hazards`, `conservative_values`.
- Each RAG document is a natural-language sentence with an inline source tag, e.g.:
  > "Listeria monocytogenes epidemiology: 1591 annual illnesses. 255 annual deaths. Case fatality rate 15.9%. 99% foodborne transmission. [CDC-2011-T3]"
- Confidence levels: HIGH ≥ 0.85, MEDIUM ≥ 0.70, LOW > 0.50, FAILED ≤ 0.50.
- Reranking is enabled by default; `test_rag_evaluation.py` supports baseline vs. reranker comparison with MRR and nDCG@5.

---

## 7. Benchmark suite

The benchmark suite lives under `benchmarks/` and is part of the broader PTM scope. It drives the experimental validation that justifies key design decisions and feeds publications.

### 7.1 Experiments currently implemented

#### Experiment 3.3 — LLM Model Comparison for Semantic Extraction
**File:** `benchmarks/experiments/exp_3_3_model_comparison.py`

Compares candidate LLMs on the extraction task using the **real** `SemanticParser` — same code path, same system prompt, same Pydantic schema as production. Uses monkey-patched `litellm.acompletion` for per-call token and cost tracking; cost via `litellm.completion_cost()`.

**Dataset:** `benchmarks/datasets/extraction_queries.json` — structured with difficulty tiers (easy / medium / hard / non-scenario).

**Metrics:**
1. Overall accuracy (fraction of ground-truth fields correct, averaged across queries)
2. Overall consistency (reproducibility across N runs of the same query)
3. **Model type accuracy** — safety-critical; misclassification reverses bias direction and can make unsafe food look safe
4. Schema compliance (fraction of calls producing valid `ExtractedScenario`)
5. Latency P50 and P95
6. Actual cost per call (USD)
7. Accuracy by difficulty tier
8. Accuracy by field (food, model_type, pathogen, temperature, duration, range_preserved)

**Model roster:** 14 models across 5 tiers (frontier reference, established frontier, cost-optimized, reasoning, open-source Ollama). Local Ollama models require `instructor_mode="JSON"` because they lack tool-call support; API models use Instructor's default tool-call mode.

**Result outputs:**
- `benchmarks/results/exp_3_3_model_comparison/results_YYYYMMDD_HHMMSS.json` — full per-query, per-run data
- `summary_YYYYMMDD_HHMMSS.csv` — one row per model with all metrics
- `latest.json` / `latest.csv` — copies of most recent run
- MLflow tracking via local SQLite backend (`mlruns.db`)

#### Experiment 1.1 — LLM Stochasticity for Physicochemical Parameters
**File:** `benchmarks/experiments/exp_1_1_ph_stochasticity.py`
**Spec:** `SPEC_exp_1_1_ph_stochasticity.md`

Monte Carlo simulation proving **Claim 1**: ungrounded LLM pH/aw retrieval is unreliable. For each food, asks each LLM "What is the pH of [food]?" N times and records the response. Compares distribution to the authoritative FDA reference. Propagates pH variance through a ComBase growth model to show that LLM uncertainty alone can flip a safety conclusion.

**Dataset:** `benchmarks/datasets/ph_aw_foods.json` — food list with reference pH and aw values, difficulty tiers, and a propagation scenario (default: Salmonella, 25 °C, aw 0.99, 4 hours).

**Metrics:**
1. MAE (|LLM pH − reference pH|)
2. Standard deviation across runs
3. CV (stdev / mean)
4. Boundary crossing rate (fraction of runs landing on the wrong side of pH 4.6 — the TCS acid/low-acid boundary)
5. Growth prediction range (min–max predicted log increase purely from pH variance)

### 7.2 Benchmark datasets — two separate query artefacts

This is important and has caused confusion. **PTM has two distinct query sets, serving different purposes:**

| Artefact | Location | Purpose | Size | Organized by |
|----------|----------|---------|------|--------------|
| Sensitivity analysis queries | `sensitivity_analysis_queries.md` | Human-vs-system comparison study + Sobol sensitivity analysis (publications) | 30 | User category (A: Risk Assessors, B: Inspectors, C: Industry QA) |
| Extraction queries (benchmark) | `benchmarks/datasets/extraction_queries.json` | Engineering ground truth for `exp_3_3` runtime comparisons | ❓ size to confirm | Difficulty tier (easy / medium / hard / non-scenario) |

Whether these overlap in content, and whether one should be derived from the other, is an **open question to resolve**. Daniel's working knowledge is of the 30-query md set; the JSON was built for the benchmark harness and is loaded automatically by the experiment script.

### 7.3 Streamlit dashboard
**Location:** `benchmarks/visualizations/`
**Spec:** `visualization_specs.md`

Web-based dashboard for the benchmark suite. Built with Streamlit + Plotly Express + Pandas. Entry point: `streamlit run benchmarks/visualizations/app.py`.

**Page layout:**
- `1_overview.py` — landing page with status cards across experiments, cost-vs-accuracy pick ("best cost-efficient model"), summary metrics.
- `2_model_comparison.py` — Experiment 3.3 viewer. Includes a safety-critical red banner that fires whenever any query × model cell shows a GROWTH vs. THERMAL_INACTIVATION misclassification.
- `3_run_experiments.py` — runner page. Subprocess wrapper around `python -m benchmarks.experiments.exp_X_Y` with model selection, run count, `--no-mlflow` toggle, and (for 1.1) temperature and log-threshold sliders.
- `4_ph_stochasticity.py` — Experiment 1.1 viewer (per `SPEC_exp_1_1_ph_stochasticity.md`). Violin plots per food ordered by stdev, MAE bar chart, growth propagation chart with configurable log-threshold slider.

**Design rules** (from `visualization_specs.md` — mirror Daniel's preferences):
- Favor readability and simplicity over DRY. Duplicate chart code across pages when variations are needed.
- Each page should be understandable on its own without reading `lib/`.
- No global state; Streamlit reruns each page on every interaction.
- `lib/` contains only genuinely identical logic (data loading, subprocess runners).

**Primary decision-driving visualization:** cost-vs-accuracy scatter plot on the Overview page.

### 7.4 Benchmark infrastructure conventions

- API keys in `.env` with provider-specific names (e.g., `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`).
- ASCII substitutes for Unicode symbols in experiment output (Windows cp1252 encoding constraint).
- LLM switching via singleton `LLMClient` — each experiment calls `configure_model()` before running.
- Cost returns 0 for unknown models (e.g., custom Ollama). Some reasoning models ("thinking" tokens) may produce underestimates if the provider does not report them.
- All experiments write to `benchmarks/results/<experiment_id>/` with timestamped JSON + CSV and `latest.*` symlink/copy.

---

## 8. Design decisions — closed (will not be re-litigated)

These decisions are settled. Re-opening them requires explicit user instruction.

### 8.1 Model-type-aware conservative bias
**Status:** ✅ Implemented in Phase 9.1 (April 2026).

**The principle:** "Conservative" always means predicting the worse food safety outcome — but the direction of corrections depends on the model type.

| Model type | Worse outcome | Conservative direction for temperature & duration |
|---|---|---|
| GROWTH | More bacterial growth | ↑ temperature, ↑ duration |
| THERMAL_INACTIVATION | Less pathogen kill | ↓ temperature, ↓ duration |
| NON_THERMAL_SURVIVAL | More pathogen survival | ↑ temperature, ↑ duration (same as growth) |

Implementation (in `StandardizationService` and `GroundingService`):
- `DURATION_MARGIN_GROWTH = 1.2` (+20 %); `DURATION_MARGIN_INACTIVATION = 0.8` (−20 %)
- `TEMPERATURE_BUMP_GROWTH = +5.0 °C`; `TEMPERATURE_BUMP_INACTIVATION = −5.0 °C`
- Range-bound selection: growth uses upper bound, inactivation uses lower bound
- Non-thermal survival currently uses growth direction; this is correct for most survival scenarios but may need refinement for specific cases (acid treatment, drying) — tracked.

This fix resolved advisory-board concern #2. Previously the system was anti-conservative for cooking queries (the "Chicken Nuggets Bug" — query C2: chicken at 68 °C for 8 minutes was being made to look *more* cooked and therefore safer than reality).

### 8.2 Predictive model form
**Status:** ✅ Closed — Baranyi primary with second-order polynomial secondary.

Decided in the April advisory review. The documentation inconsistency (some places referenced Ratkowsky) is a known artefact and is not a signal to revisit the decision.

### 8.3 Lag phase treatment (current implementation)
**Status:** ✅ Current — fixed default h₀ per organism (ComBase-style).

The earlier no-lag approach (λ = 0) compounded with other conservative biases and undermined credibility with predictive microbiology reviewers. The current approach uses ComBase default h₀ values per organism, matching what ComBase Predictor itself does. LLM-based h₀ inference was evaluated and **rejected as infeasible**.

A **text-based retrieval corpus for lag** (via RAG) is an open research direction (concern #3 in §11) but not the MVP path.

### 8.4 Two-tier knowledge separation: Rules vs. RAG
**Status:** ✅ Architectural.

Linguistic interpretations (e.g., "room temperature" = 25 °C) live in `app/config/rules.py`. Scientific facts (food pH, pathogen associations) live in the RAG knowledge base. Different update cycles, different confidence characteristics, different testing strategies (rules are pure functions; RAG needs integration tests).

### 8.5 CSV-to-RAG over direct PDF ingestion
**Status:** ✅ For structured quantitative data.

Manual extraction of tables to CSV, then ingesting CSV into ChromaDB, was chosen over direct PDF ingestion because:
- PDF tables extract poorly through automated chunking (column fragmentation, header/footnote separation).
- Manual extraction allows per-value verification.
- Source tags can be added per row.

A **hybrid** approach is planned: CSV pipeline for structured quantitative facts (the current set), direct PDF/text ingestion for unstructured regulatory and scientific text (future lag corpus, guidance documents). Each approach is used where it is strongest.

### 8.6 Strict user priority in value resolution
**Status:** ✅ Architectural.

User-provided values are never overwritten by system inferences, even if the system has higher nominal confidence. Liability and trust trump single-case accuracy gains. A bias-detection layer (planned — concern #6 in §11) will flag when user values diverge meaningfully from RAG references, but will never silently override them.

### 8.7 User-explicit confidence = 0.90, not 1.0
**Status:** ✅ Architectural.

Users can misremember or mistype; LLM extraction can misparse. 0.90 is still clearly HIGH confidence and leaves room for uncertainty propagation.

### 8.8 Ground truth evaluation framework (methodology)
**Status:** ✅ Agreed.

Ground truth for this system is not a single correct answer per query but the distribution of expert parameterisations. The sensitivity analysis queries (§7.2) are designed to collect this distribution from 15–25 food-safety professionals stratified across categories A/B/C. The system's output must fall within the expert-consensus range to be "correct."

---

## 9. Working conventions and code style

### 9.1 Code style (PTM codebase)
- Python 3.11+, Pydantic v2, async/await throughout the service layer.
- Singletons via `get_X()` / `reset_X()` pattern (one live instance per service).
- No global state across requests; each session has its own `SessionState` and `InterpretationMetadata`.
- Every bias correction, range clamp, and retrieval is recorded in metadata — silence is never the answer.

### 9.2 Benchmark code style (per `visualization_specs.md`)
- Readability and simplicity over DRY. Duplicate chart code across pages rather than abstract prematurely.
- Each page file should be understandable on its own.
- Comments explain *why*, not *what*.
- No global state (Streamlit re-runs the whole page on every interaction).

### 9.3 Testing conventions
- Unit tests in `tests/unit/` (pytest).
- Manual test scripts in `scripts/` — end-to-end runners with print output, useful for interactive validation.
- Test data: the same small set of canonical queries (e.g., chicken nuggets at 68 °C / 8 min for the thermal inactivation sanity check) appears across multiple tests.

### 9.4 Session conventions (for Claude)
- Daniel prefers walkthroughs that proceed one element at a time, with thorough conceptual grounding before moving on.
- When explaining code or metrics, lead with the concept, then the formula, then how to interpret the result.
- Avoid self-references to Claude's memory or to prior sessions; treat this document as the source of truth.

---

## 10. Current status and roadmap

### 10.1 Component status (end of Phase 9.1)

| Component | Status | Notes |
|---|---|---|
| Semantic Parser | ✅ Complete | LLM + Instructor; three extraction methods |
| Grounding Service | ✅ Complete | Rules + RAG integration; embedding fallback |
| Standardization Service | ✅ Complete | Model-type-aware bias direction (Phase 9.1) |
| ComBase Engine | ✅ Complete | Growth, thermal inactivation, non-thermal survival |
| RAG System | ✅ Complete | ChromaDB + reranking; verification queries |
| RAG Data Population | 🟡 Partial | CDC-2019 not yet merged into pathogen_characteristics |
| Orchestrator | ✅ Complete | Full pipeline coordination with session state |
| API (`/api/v1/translate`) | ✅ Live | Covered by `test_api_translation.py` |
| Benchmark suite (exp_3_3) | ✅ Live | Running on 14 models; results in `benchmarks/results/` |
| Benchmark suite (exp_1_1) | ✅ Live | pH stochasticity Monte Carlo |
| Streamlit dashboard | 🟡 In progress | Pages 1/2/3 exist; page 4 (pH stochasticity) per spec |
| Documentation | 🟡 Mixed | Main tech doc current as of 2026-03-19; post-April updates not yet merged into it |

### 10.2 Roadmap

| Phase | Focus | Status |
|---|---|---|
| 9.1 | Model-type-aware conservative bias | ✅ Done |
| 10 | Result Interpretation Module — model output → natural language | 🔴 Not started |
| 11 | Multi-step scenarios with per-step model-type inference | 🔴 Designed, not built |
| 12 | Clarification loop — interactive questions for missing data | 🔴 Not started |
| 13 | Production deployment — Docker, CI/CD, monitoring, rate limiting | 🔴 Not started |

---

## 11. Open issues and advisory-board concerns

Nine of the ten advisory-board concerns raised in `issues.md` remain open. Only concern #2 has been resolved (documented in §8.1).

For each open concern, the table below captures the concern in one line and the agreed direction from the issues document. Detailed responses and literature grounding are in `issues.md`; this summary is enough for session-level reasoning about priorities.

| # | Concern | Status | Agreed direction |
|---|---------|--------|------------------|
| 1 | **Human variability dominance claim** — Central thesis claims human parameterisation variability is the dominant reducible uncertainty source; not yet quantitatively proven vs. model structural uncertainty (~2–4× per validation literature) or strain variability. | 🔴 Open | Two studies planned: (a) variance decomposition (Sobol / ANOVA) across parameterisation, model structure, strain variability; (b) paired human-vs-system study with 15–25 food-safety professionals on 30 sensitivity queries. The human-vs-system study is the centrepiece publication. |
| 2 | **Conservative bias direction for thermal inactivation** — Bias rules only correct for growth; were anti-conservative for cooking queries (Chicken Nuggets bug). | ✅ Resolved | Model-type-aware bias implemented in Phase 9.1 (§8.1). Non-thermal survival still uses growth direction; refinement for acid-treatment / drying edge cases tracked. |
| 3 | **Lag phase handling** — Current λ=0 over-predicts growth and compounds with other conservative biases. | 🔴 Open | Two-step plan: (1) MVP — full Baranyi with fixed default h₀ per organism (ComBase-compatible). (2) Research — curated lag-phase RAG corpus from 30–50 papers structured as (organism, prior conditions, current conditions, observed lag, matrix, reference). LLM-based numerical h₀ prediction was evaluated and rejected as infeasible. |
| 4 | **RAG coverage, currency, governance** — CDC 2011 outdated (2019 update available); 259 foods skewed to Western agriculture; no formal curation protocol; no RAG version tracking. | 🟡 Partial | CDC-2019 source registered but rows not yet merged (§6.3). Governance protocol and RAG version tracking not yet designed. Hybrid architecture (structured CSV + direct PDF for regulatory/literature text) is the agreed future state. USDA FoodData Central is the target for food-specific aw in a future sprint. |
| 5 | **LLM as a single point of failure / reproducibility paradox** — Extraction is a probabilistic LLM call; the system claims reproducibility but the first stage is stochastic. Reproducibility is not empirically verified. | 🔴 Open | Experiment 3.3 measures extraction consistency (same query × N runs → field-level agreement) as a first-class metric. Targeted response: reproducibility claim will be reframed as "process transparency and structured standardisation" rather than deterministic output. |
| 6 | **Silent acceptance of potentially biased user inputs** — User priority means user values are respected, but the system does not flag when a user's stated value is suspiciously optimistic (e.g., at the safety-favourable end of a stated range). | 🔴 Open | Planned: bias-detection layer between grounding and standardization. Detects (a) user values at growth-favourable end of stated ranges, (b) user values diverging from RAG references beyond a threshold (e.g., > 0.5 pH units, > 5 °C), (c) compound optimism across parameters. Flags only — never modifies user values. |
| 7 | **End-to-end validation strategy** — Unit tests validate components in isolation, but there is no end-to-end validation against expert judgement. No ground truth dataset. No failure-mode analysis for compounding defaults. | 🔴 Open | Ground truth via expert distribution collected in the human-vs-system study (§7.2). Failure modes catalogued: food-not-in-RAG, scenario-type misclassification, wrong pathogen inference, numeric-extraction failure, compounding fallbacks. Recommended mitigations: "grounding score" (fraction of parameters grounded vs. defaulted, warned if < 50 %), rule-based sanity checks (temp > 55 °C forces inactivation mode; temp < 5 °C + mesophile → flag negligible growth). |
| 8 | **ComBase integration — technical and political** — Production impact requires real ComBase integration, not a standalone engine. Daniel's role as original ComBase architect is an advantage. | 🔴 Open | Architecture supports pluggable engines (`EngineType` enum). Integration strategy, API availability, and timeline not yet finalised. |
| 9 | **Publication strategy** — Target venues not settled. | 🔴 Open | Leading candidates: *International Journal of Food Microbiology* (for the human-vs-system study), *Food Microbiology*, *Computers and Electronics in Agriculture*. The Monte Carlo pH study (Experiment 1.1) is a plausible quick-win standalone publication. |
| 10 | **Scope risk** — Three work packages (WP1 problem interpretation, WP2 enhanced secondary models, WP3 real-time decision support) plus ComBase integration and publications is ambitious given team size. WP1 MVP timeline unclear. | 🔴 Open | Phases 10–13 still ahead for WP1 alone. WP3 is where real regulatory value lies but depends on WP1 being solid. |

### 11.1 Cumulative conservative bias (a subsidiary concern under #1 and #2)

The system stacks multiple conservative heuristics (upper-bound temperature + upper-bound duration + +20 % duration margin + growth-permissive pH + λ=0). Compounded, the predicted log increase can be 2.5–3.5× higher than a reasonable human calculation. Risk: "crying wolf" — operators learn to discount the tool.

**Two agreed mitigations, both planned:**
- **Short-term:** cumulative bias indicator in the output ("this prediction uses 3 conservative assumptions; it represents a precautionary upper bound, not a best estimate") with a threshold that flags when more than two conservative corrections have been applied.
- **Research version:** move toward distributional uncertainty propagation (Monte Carlo) aligned with standard QMRA methodology. Itself a publishable contribution.

---

## 12. Known inconsistencies and items to confirm

Items worth verifying the next time Daniel works on the related area:

1. **Project name in `settings.py` / tests.** `Settings.app_name` reads "Problem Interpretation Module" (see `test_config.py`). Current project name is PTM; "Problem Interpretation Module" is the broader tentative project name (§1.2). Low-priority rename, but ensure current sessions don't get misled by the config value.
2. **Ratkowsky vs. Baranyi in documentation.** Implementation is Baranyi + 2nd-order polynomial secondary (§5.4); some legacy text and an advisory-review aside described it as Ratkowsky. Main tech doc should be updated.
3. **`default_ph_neutral` value.** Two documented defaults appear in notes: 6.5 (in the bias-correction table of the main tech doc) and 7.0 (in the LLM Monte Carlo / issues.md discussion). Confirm the current value in `app/config/settings.py`.
4. **Two query artefacts.** `sensitivity_analysis_queries.md` (30 queries, paper-oriented) vs. `benchmarks/datasets/extraction_queries.json` (engineering ground truth for exp_3_3). Overlap unknown; consolidation or derivation relationship not documented.
5. **CDC-2019 rows missing from `pathogen_characteristics.csv`.** Source is registered; rows not yet populated (§6.3).
6. **`test_llm_client.py` content.** Inspection shows its test classes duplicate `test_config.py` rather than testing the LLM client (likely a mis-saved file). Verify and restore.
7. **`data_year` and `notes` columns** specified in the pathogen-characteristics schema but not present in the CSV. Schema documentation should be aligned with file content.

---

## 13. Glossary

| Term | Definition |
|------|------------|
| **aw (water activity)** | Measure of water available for microbial growth, scale 0–1. |
| **Baranyi model** | Primary growth model for bacterial populations that explicitly models the lag phase via a physiological-state parameter. |
| **CFR (case fatality rate)** | Percentage of infections resulting in death. |
| **ComBase** | Database and predictive-microbiology platform for bacterial growth and inactivation in foods. Daniel is the original IT architect. |
| **ExtractedScenario** | Pydantic model produced by `SemanticParser` representing what was extracted from the user's query. |
| **Grounding** | The process of converting vague or missing inputs into precise numeric values via rules and RAG. |
| **GroundedValues** | The container object produced by `GroundingService`, carrying resolved values plus per-field provenance. |
| **h₀** | In the Baranyi model, a parameter capturing the physiological state of cells at time zero. Determines lag duration. Treated as a default per-organism constant in the current PTM MVP. |
| **Instructor** | Python library that constrains LLM outputs to Pydantic schemas via tool-calls or JSON mode. |
| **InterpretationMetadata** | Session-level object carrying full provenance, bias corrections, range clamps, retrievals, warnings, and overall confidence. |
| **LiteLLM** | Provider-agnostic wrapper for LLM APIs used throughout the PTM. |
| **μ_max** | Maximum specific growth rate (units: 1/hour). Negative for inactivation models. |
| **PHF** | Potentially Hazardous Food. Older terminology; TCS is the modern equivalent. |
| **PTM** | Problem Translation Module — this project. |
| **QMRA** | Quantitative Microbiological Risk Assessment. |
| **RAG** | Retrieval-Augmented Generation. In PTM, restricted to scientific-fact retrieval (food properties, pathogen data); linguistic conventions are separate (rules). |
| **Ratkowsky** | Secondary model for bacterial growth rate. PTM does NOT use Ratkowsky (see inconsistency #2 in §12). |
| **StandardizationResult** | Output of `StandardizationService`: the execution payload plus the list of corrections, clamps, and defaults applied. |
| **TCS** | Time/Temperature Control for Safety. Food classification for regulatory purposes. |
| **Thermal inactivation** | Pathogen death via heat (cooking). Model type that produces negative μ_max. |
| **TranslationResult** | Top-level return object from the orchestrator. |

---

## 14. References

### Primary sources (authoritative documents in the RAG)
- Scallan E, et al. (2011). *Foodborne Illness Acquired in the United States—Major Pathogens*. Emerging Infectious Diseases 17(1):7–15. DOI: 10.3201/eid1701.P11101
- Scallan Walter EJ, et al. (2025). *Foodborne Illness Acquired in the United States—Major Pathogens, 2019*. Emerging Infectious Diseases 31(4):669–677. DOI: 10.3201/eid3104.240913
- Institute of Food Technologists (2003). *Evaluation and Definition of Potentially Hazardous Foods*. Comprehensive Reviews in Food Science and Food Safety 2(s1):1–108. DOI: 10.1111/j.1541-4337.2003.tb00052.x
- FDA/CFSAN (2007). *Approximate pH of Foods and Food Products*.
- FDA/CFSAN (2012). *Bad Bug Book: Foodborne Pathogenic Microorganisms and Natural Toxins Handbook*, 2nd Edition.

### Key project documents (in `/mnt/user-data/uploads/` or equivalent)
- `problem_translation_module_complete_techincal_documentation.md` — main technical doc (dated 2026-03-19; predates Phase 9.1).
- `issues.md` — the ten advisory-board concerns with full responses.
- `sensitivity_analysis_queries.md` — 30 queries across Categories A/B/C for the human-vs-system study.
- `model_type_aware_conservative_bias.md` — Phase 9.1 fix specification and rationale.
- `grounding_service_architecture_expanded.md` — detailed grounding service design.
- `rag_data_sources_architecture.md` — RAG ingestion pipeline design.
- `rag_system.md` — RAG runtime architecture.
- `extraction_notes.md` / `extraction_notes_updated.md` — extraction methodology and 2026-04-17 audit record.
- `sources.md`, `source_references.csv` — source citation register.
- `visualization_specs.md` — Streamlit dashboard spec.
- `SPEC_exp_1_1_ph_stochasticity.md` — Experiment 1.1 dashboard-page spec.

### Ideas / future work
- `ideas.md` — human-variability study; lag-phase RAG; ComBase observation mining.

---

## 15. Changelog

| Version | Date | Change |
|---------|------|--------|
| 1.0 | 2026-04-24 | Initial consolidated context document. Covers PTM core + benchmark suite through end of Phase 9.1. Synthesises 15+ source files (technical doc, issues, sensitivity queries, grounding architecture, RAG system, extraction notes, benchmark experiments, dashboard specs) and the 2026-04-17 RAG audit. Naming normalised to PTM throughout. |
| 1.1 | 2026-04-25 | Added §2 "Scientific philosophy and project vision" — captures the project thesis (LLMs as the means to model the previously-unmodellable human input/output layer of food safety assessment), the Holistic Risk Model three-layer framing, the three work packages with PTM as WP1, the two distinct sources of variability (human + LLM stochasticity), the scientific framing for biology-oriented audiences, the case for curated RAG over frontier-model web search, and the strategic ComBase integration target. Sections 3–15 renumbered accordingly (cross-references updated throughout). The philosophy is the lens for evaluating future design decisions but is explicitly not immutable. |

---

*End of PTM session context document.*
