# Problem Translation Module (PTM) — Session Context

**Version:** 1.2
**Date:** 2026-04-28
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
│    Selects bound from pending ranges (model-type aware:         │
│    upper for growth/non-thermal-survival, lower for thermal     │
│    inactivation), applies conservative defaults for missing     │
│    values, clamps to model-valid ranges, builds the ComBase     │
│    execution payload. No bias-correction layer (see §8.7).     │
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

| Priority | Source | Description |
|---|---|---|
| 1 | USER_EXPLICIT | User stated the value directly ("temperature was 25 °C"). User-supplied ranges (e.g., "10–15 °C") also use this source with `parsed_range` populated; bound selection happens downstream in standardization. |
| 2 | USER_INFERRED | Value from interpretation rules ("room temperature" → 25 °C). The rule's structured details (matched_pattern, conservative flag, notes, method) are captured on the provenance entry. |
| 3 | RAG_RETRIEVAL | Value retrieved from knowledge base. Ranges pass through with `parsed_range` populated and a `range_pending` flag; bound selection happens downstream in standardization. |
| 4 | CONSERVATIVE_DEFAULT | Safety-first fallback (applied in standardization, not grounding). |

**Invariant:** higher-priority sources are never overwritten by lower-priority ones.

**Two knowledge types, handled separately:**
- **RAG** — scientific facts (food pH, aw, pathogen associations). Updates as science evolves.
- **Rules** — linguistic conventions ("room temperature" = 25 °C). Stable.

**Numeric extraction from text:** regex handles single values (`pH 6.0`), ranges with hyphen (`pH 5.9-6.2`), ranges with "to" (`pH 5.5 to 6.0`), ranges with "and" (`pH between 5.5 and 6.0`). When ranges are extracted, BOTH bounds are preserved on the provenance (`parsed_range = [min, max]`); the standardization service later picks the model-type-appropriate bound (see §8.1, §8.8). Grounding does NOT collapse ranges to a single value.

**Reliability signals:**
- The `source` enum tier (USER_EXPLICIT / USER_INFERRED / RAG_RETRIEVAL / CONSERVATIVE_DEFAULT) is the categorical reliability signal.
- For RAG retrievals, the embedding cosine similarity is the only mathematically-grounded numeric signal (`embedding_score`). Reranker scores are reported separately when the reranker is in use.
- For rule-based interpretations, the rule's `conservative: bool` flag indicates whether the rule already errs on the conservative side of the underlying interval. No per-rule confidence number is reported (see §8.7).

**Interpretation rules (excerpt):**

Temperature: `room temperature`/`counter`/`ambient`/`left out` → 25 °C; `refrigerated`/`fridge`/`chilled` → 4 °C; `frozen`/`freezer` → -18 °C; `warm`/`in the car`/`summer` → 30 °C; `hot` → 40 °C; `cold` → 10 °C; `cool` → 15 °C. Each rule carries a `conservative: bool` flag and a `notes` string.

Duration: `overnight`/`all night` → 480 min; `all day` → 600 min; `few hours`/`couple of hours` → 120–180 min; `half a day` → 360 min; `briefly`/`few minutes` → 10–15 min; `long time`/`many hours` → 360 min.

When no rule matches, embedding similarity finds the closest canonical phrase (0.50 cosine threshold); the matched canonical phrase and similarity score are recorded on the provenance. Below threshold, the field is marked ungrounded and standardization will apply a conservative default.

**Sourcing of rules.py interpretation values (deferred):** The rules currently encode plausible defaults for linguistic conventions. Some are sourceable (refrigeration → 4°C from FDA Food Code; freezer → -18°C from Codex Alimentarius; room temperature 20–25°C from USP). Some are convention-backed (warm, hot, in the car). Some are linguistic-only and not sourceable in any standard ("a while" → 60 min). Adding source attribution per rule is filed as a future enhancement; see §16.

### 5.3 Standardization Service
**Location:** `app/services/standardization/standardization_service.py`

Prepares `GroundedValues` for model execution by performing four operations, each recorded as a structured event on the per-field standardization block:

1. **Range-bound selection.** For values that arrive with `range_pending=True` (RAG-retrieved ranges and user-supplied ranges), picks the model-type-appropriate bound: upper for GROWTH and NON_THERMAL_SURVIVAL, lower for THERMAL_INACTIVATION. Recorded as `rule = "range_bound_selection"`.
2. **Default imputation.** When a value is still missing after grounding, applies a conservative default:
   - Organism: Salmonella (broadly applicable, leading cause of foodborne illness)
   - Temperature: abuse temperature (25°C for growth, conservative cooking temperature for inactivation)
   - pH: 7.0 (neutral, near-optimal for pathogen growth)
   - Water activity: 0.99 (high, maximises predicted growth)
   Recorded as `rule = "default_imputed"` and added to the top-level `defaults_imputed` list as a structured `DefaultImputedInfo` entry.
3. **Range clamping.** When a value falls outside the selected ComBase model's valid range, clamps to the nearest boundary. Recorded as `rule = "range_clamp"` AND added to the top-level `range_clamps` list as a structured `RangeClampInfo` entry. A warning string is also emitted alongside.
4. **Payload construction.** Builds the `ComBaseExecutionPayload` from the (now standardised) values.

**No bias-correction layer.** Earlier versions applied a +20% / −20% duration margin and a (never-implemented) ±5°C temperature bump to USER_INFERRED values. This was removed (see §8.7). Conservatism is now committed in exactly two places: (a) the default values themselves, and (b) range-bound selection. Mapped values from rules carry their own conservatism via the rule's chosen point and the `conservative: bool` flag.

**Audit signals.** When events fire, three signals are emitted:
- The structured `standardization` block on the per-field `ValueProvenance` (per-field view of "what happened to this field").
- The relevant top-level list (`range_clamps`, `defaults_imputed`) as a structured object (cross-field view of "what events of this type fired").
- A warning string in the top-level `warnings` list, when the event is safety-relevant (clamps and missing-critical-field defaults). Range-bound selection does NOT emit a warning — it's mechanical and routine.

Empty audit categories emit truly empty arrays (`[]`), not sentinel strings. The "(none applied)" rendering is a UI concern, not a data-layer concern.

**Conservative defaults (current):**
- `default_temperature_abuse_c = 25.0`
- `default_ph_neutral = 7.0`
- `default_aw_high = 0.99`
- `default_organism = SALMONELLA`

**Structured event types** (recorded in `StandardizationResult` and on the per-field `ValueProvenance.standardization` block):
- `range_bound_selection` — direction (upper/lower), before_value (the range), after_value (selected bound), reason. Mechanical, fires whenever a range_pending value is processed; not a safety event.
- `default_imputed` — field_name, default_value, reason. Recorded both on the per-field block AND in the top-level `defaults_imputed` list (as `DefaultImputedInfo`).
- `range_clamp` — field_name, original_value, clamped_value, valid_min, valid_max, reason. Recorded both on the per-field block AND in the top-level `range_clamps` list (as `RangeClampInfo`). Also emits a warning string.

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

Coordinates the full pipeline. Singleton via `get_orchestrator()`. Returns a `TranslationResult` with `.success`, `.error`, `.state` (SessionState), `.execution_result`, `.metadata` (`InterpretationMetadata` with provenance, structured standardization events, retrievals, warnings).

Session state transitions go through `SessionStatus` (PENDING → EXTRACTING → GROUNDING → STANDARDIZING → EXECUTING → COMPLETED / FAILED).

**Audit capture is post-standardization.** The orchestrator captures the audit metadata snapshot AFTER standardization completes, not before. This means `field_audit[X].final_value` is the value that reached the model (post-clamp, post-default, post-range-bound-selection), not a pre-standardization placeholder. Fields that were defaulted (e.g., a missing organism imputed to Salmonella, missing pH imputed to 7.0) are added to `field_audit` with `source = "conservative_default"` and a populated `standardization` block. The legacy top-level `provenance` array is auto-derived from `field_audit` for backward compatibility.

### 5.6 Metadata & provenance
**Location:** `app/models/metadata.py`

- `ValueProvenance` — `source` (categorical: USER_EXPLICIT / USER_INFERRED / RAG_RETRIEVAL / CONSERVATIVE_DEFAULT), `parsed_range`, `range_pending` (internal flag, cleared by standardization), `extraction` (method, raw_match, parsed_range, plus rule-specific fields: matched_pattern, conservative, notes, similarity, canonical_phrase), `retrieval` (query, top_match with embedding_score and rerank_score, runners_up, full_citations), and `standardization` (the structured event block; null when no standardization fired).
- `RangeBoundSelection` — rule="range_bound_selection", direction, before_value (range), after_value (selected bound), reason. Populated on the per-field block when a pending range was narrowed.
- `RangeClamp` — field_name, original_value, clamped_value, valid_min, valid_max, reason. Populated both on the per-field block (`rule="range_clamp"`) and as a structured `RangeClampInfo` in the top-level `range_clamps` list.
- `DefaultImputed` — field_name, imputed_value (float | str — strings used for organism), reason. Populated both on the per-field block (`rule="default_imputed"`) and as a structured `DefaultImputedInfo` in the top-level `defaults_imputed` list.
- `RetrievalResult` — query, top_match (doc_id, embedding_score, rerank_score, retrieved_text, source_ids, full_citations), runners_up. The only mathematically-grounded numeric reliability signal is the embedding_score (cosine similarity).
- `InterpretationMetadata` — top-level container: session_id, original_input, status, `field_audit` dict (canonical per-field map), `range_clamps` list, `defaults_imputed` list, `warnings` list, `combase_model` block (organism, organism_id, organism_display_name, model_type, model_id, coefficients_str, valid_ranges, selection_reason), `system` block (rag_store_hash, rag_ingested_at, source_csv_audit_date, ptm_version, combase_model_table_hash). The legacy `provenance` array is auto-derived from `field_audit` for backward compatibility.

**No confidence numbers.** Earlier versions emitted a `confidence: float` per provenance entry, an `overall_confidence` at the top level, and a `confidence_formula` string. These were removed (see §8.7) because they were not mathematically grounded — they were authoring intuition (rules), hardcoded constants (USER_EXPLICIT = 0.90), or LLM self-reports. The categorical `source` tier carries the auditability signal those numbers were pretending to convey. The only numeric reliability signal in the audit is the RAG retrieval's embedding similarity, reported under its own name.

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

### 8.1 Model-type-aware range-bound selection
**Status:** ✅ Implemented in Phase 9.1 (April 2026); refined in Phase 9.2 (April 2026) to live in the StandardizationService rather than the GroundingService.

**The principle:** "Conservative" always means predicting the worse food safety outcome — but the direction of corrections depends on the model type.

| Model type | Worse outcome | Range-bound selection direction |
|---|---|---|
| GROWTH | More bacterial growth | upper bound |
| THERMAL_INACTIVATION | Less pathogen kill | lower bound |
| NON_THERMAL_SURVIVAL | More pathogen survival | upper bound (same as growth) |

**Implementation:** when a value (RAG-retrieved or user-supplied) carries a range, the GroundingService stores both bounds with `range_pending=True`. The StandardizationService then picks the model-type-appropriate bound at standardization time, recording the event as a structured `range_bound_selection` entry on the per-field provenance block.

This fix resolved advisory-board concern #2. Previously the system was anti-conservative for cooking queries (the "Chicken Nuggets Bug" — query C2: chicken at 68 °C for 8 minutes was being made to look *more* cooked and therefore safer than reality).

**No bias-correction layer.** Earlier iterations of the design also applied a duration multiplier (×1.2 / ×0.8) and a temperature bump (±5°C) to USER_INFERRED values. These were removed in Phase 9.3 (April 2026) — see §8.7. Conservatism is now committed in exactly two places: in the default values themselves, and in range-bound selection. Mapped values from rules carry their own conservatism via the rule's `conservative: bool` flag.

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

### 8.7 No confidence numbers; no bias-correction layer
**Status:** ✅ Architectural (Phase 9.3, April 2026).

The system does not emit per-field confidence numbers, an overall confidence number, or a confidence-derivation formula. Earlier versions did, but those numbers were not mathematically grounded:
- USER_EXPLICIT confidence was a hardcoded constant (0.90).
- USER_INFERRED confidence was authoring intuition baked into the rule (0.50–0.95).
- LLM intent confidence was an LLM self-report, not calibrated.
- The "overall confidence" was a min over heterogeneous numbers, mixing real cosine similarities with hardcoded constants.

The categorical `source` tier (USER_EXPLICIT / USER_INFERRED / RAG_RETRIEVAL / CONSERVATIVE_DEFAULT) carries the auditability signal. For RAG retrievals, the embedding cosine similarity is the only mathematically-grounded numeric signal and is reported as `embedding_score`. For rule-based interpretations, the rule's `conservative: bool` flag indicates whether the rule already errs on the conservative side.

The system also does not apply a bias-correction layer to inferred values. The earlier ×1.2 / ×0.8 duration margin and the (never implemented) ±5°C temperature bump were removed because they double-counted conservatism: rules already commit to conservative points within their underlying intervals, and adding a margin on top produced values past the rule's own range. Conservatism is now committed in two well-defined places: default values, and range-bound selection.

**Audit consequence.** The audit response is more honest under this regime: every number in it is something the system actually measured (embedding similarities, ComBase model coefficients, the prediction's μ_max). No fabricated confidence values pretending to be measurements. The four audit categories that remained (range_clamps, defaults_imputed, warnings) are surfaces where genuine events fire — bias_corrections was removed because, with no bias-correction layer, no events of that type can occur.

### 8.8 Range-bound selection lives in StandardizationService
**Status:** ✅ Architectural (Phase 9.2, April 2026).

When a value (RAG-retrieved or user-supplied) carries a range, the GroundingService stores both bounds with `range_pending=True` on the provenance and lets the value pass through. The StandardizationService picks the model-type-appropriate bound at standardization time. This separates concerns cleanly: grounding handles "where did this value come from" (user, RAG, rule, default); standardization handles "what was done to make this value safe to feed the model" (range-bound selection, defaulting, clamping).

This split was made because range-bound selection is conceptually a standardization decision — it picks one value from an interval based on model-type direction, the same kind of operation as bias correction and clamping — even though it was originally implemented in the GroundingService.

### 8.9 Audit trail data shape
**Status:** ✅ Architectural (Phase 9.3, April 2026).

The audit response on `/api/v1/translate?verbose=true` exposes a fully structured per-field map (`field_audit`) plus three top-level lists (`range_clamps`, `defaults_imputed`, `warnings`) and three context blocks (`combase_model`, `system`, `provenance` — the latter is auto-derived from `field_audit` for backward compatibility).

Each per-field entry on `field_audit` carries:
- `final_value`: the value that reached the model (post-standardization)
- `source`: categorical tier
- `retrieval`: RAG details (when applicable) — query, top_match, runners_up, full_citations
- `extraction`: extraction method and rule-specific details (matched_pattern, conservative flag, similarity, canonical_phrase)
- `standardization`: the structured event block — `rule`, `direction`, `before_value`, `after_value`, `reason` — populated when an event fired

**Three structured event types** under `standardization`:
- `range_bound_selection` — mechanical, fires on every range-typed value
- `default_imputed` — fires when a value was missing
- `range_clamp` — fires when a value was outside the model's valid range

The first is mechanical and routine; the other two are safety events. The first does NOT trigger a UI warning marker; the other two do.

**Empty audit categories emit truly empty arrays (`[]`)**, not sentinel strings. The "(none applied)" rendering is a UI concern.

### 8.10 Out-of-range values are clamped, not extrapolated
**Status:** ✅ Architectural (Phase 9.4, April 2026).

When an input parameter (temperature, pH, water activity, factor4) falls outside the selected ComBase model's valid range, the system clamps to the nearest boundary and records three audit signals: a structured `RangeClampInfo` entry in the top-level `range_clamps` list, a structured `range_clamp` event on the per-field `standardization` block, and a warning string in the top-level `warnings` list. The model is then evaluated at the clamped value.

Earlier behaviour passed the out-of-range value through unchanged with only a warning string. The polynomial extrapolated, producing a numeric prediction with no scientific basis, while the user received a number that looked valid. The new behaviour ensures every prediction is evaluated within the model's calibration range; the user sees explicitly that clamping occurred and the original value.

The alternative — refusing the prediction outright — was rejected as less practically useful. A user asking "what happens at 50°C with E. coli" probably wants the closest defensible answer (the prediction at 42°C, the model's max) plus full transparency, not a refusal.

**Known limitation.** When a value is range-narrowed AND then clamped on the same field, the per-field `standardization` block records only the clamp (last event wins). The pre-clamp range is recoverable from the `extraction.parsed_range` field. A future refactor making the standardization block a list rather than a single object will resolve this; see §16.

### 8.11 Multi-source citation attribution
**Status:** ✅ Architectural (Phase 9.3, April 2026).

The `food_properties.csv` schema allows only one `source_id` per row, but some rows carry values from two sources (e.g., bread white draws pH from FDA-PH-2007 and aw from IFT-2003-T31 Table 3-1). At ingestion, the document-builder parses the row's `notes` field for additional `[SOURCE-ID]` patterns and merges them into the document's source list, validated against `data/sources/source_references.csv`. The retrieval response then reports both source_ids and full bibliographic citations.

This fix does NOT establish per-field attribution (which source supports pH vs which supports aw); per-field attribution requires a CSV schema migration that is filed but not scheduled. Per-row multi-source attribution is the current state and is sufficient for regulatory cross-checking.

### 8.12 RAG store provenance manifest
**Status:** ✅ Architectural (Phase 9.3, April 2026).

A small JSON manifest is written alongside the ChromaDB persistence directory at ingestion time, recording `rag_store_hash`, `rag_ingested_at`, and `source_csv_audit_date`. At request time, the orchestrator reads this manifest and populates the response's `system` block with these values plus `ptm_version` (git sha) and `combase_model_table_hash`.

This provenance stamping was the safeguard that would have caught the 2026-04-27 stale-RAG-store bug (where the post-audit aw value 0.94 was correct in the CSV but the RAG store still served the pre-audit 0.93). When the manifest is absent, a warning is appended to `metadata.warnings` ("RAG manifest missing — store provenance unknown") and the system fields are emitted as null.

### 8.13 Default organism imputation as structured event
**Status:** ✅ Architectural (Phase 9.4, April 2026).

When a query does not specify a pathogen, the system imputes Salmonella as the default. The imputation is recorded as a structured `DefaultImputed` event in the top-level `defaults_imputed` list with `field_name = "organism"`, `default_value = "Salmonella"`, and the canonical reason string. The same event is written to `field_audit["organism"].standardization` with `rule = "default_imputed"`. A warning string is also retained in `warnings` to give the missing-critical-field event extra prominence; this duplication is deliberate (the structured `defaults_imputed` entry is the canonical machine-readable record; the warning is a user-facing notice).

### 8.14 Ground truth evaluation framework (methodology)
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

### 10.1 Component status (end of Phase 9.4)

| Component | Status | Notes |
|---|---|---|
| Semantic Parser | ✅ Complete | LLM + Instructor; three extraction methods. Intent classifier prompt extended for action verbs and technical model-type terms (Phase 9.4). |
| Grounding Service | ✅ Complete | Rules + RAG integration; embedding fallback. Range-bound selection moved out (now in Standardization, §8.8). Rule details (matched_pattern, conservative, notes, similarity, canonical_phrase) propagated to provenance. |
| Standardization Service | ✅ Complete | Range-bound selection (model-type aware), default imputation, range clamping. No bias-correction layer (§8.7). |
| ComBase Engine | ✅ Complete | Growth, thermal inactivation, non-thermal survival. Out-of-range inputs are clamped (§8.10). |
| RAG System | ✅ Complete | ChromaDB + reranking; verification queries; manifest at ingestion (§8.12); multi-source citation attribution from notes field (§8.11). |
| RAG Data Population | 🟡 Partial | CDC-2019 not yet merged into pathogen_characteristics |
| Orchestrator | ✅ Complete | Audit metadata captured post-standardization; `field_audit` is canonical, legacy `provenance` array auto-derived |
| API (`/api/v1/translate`) | ✅ Live | `verbose=true` exposes the full structured audit shape |
| Audit trail data shape | ✅ Architectural | Per-field `field_audit` map + three top-level lists (range_clamps, defaults_imputed, warnings) + three context blocks (combase_model, system, provenance auto-derived) — see §8.9 |
| Benchmark suite (exp_3_3) | ✅ Live | Running on 14 models; results in `benchmarks/results/` |
| Benchmark suite (exp_1_1) | ✅ Live | pH stochasticity Monte Carlo |
| Streamlit dashboard | 🟡 In progress | Pages 1/2/3 exist; page 4 (pH stochasticity) per spec |
| Documentation | 🟡 Mixed | This document (`ptm_context.md`) is current. Older `*_documentation.md` and `*_architecture_expanded.md` files in the repo are pre-Phase-9.2 and are out of date — they describe the bias-correction layer that has been removed and the range-bound-selection-in-grounding architecture that has been replaced. Pending task: generate a `specifications.md` from the codebase via reverse engineering and maintain it from there forward. |

### 10.2 Roadmap

| Phase | Focus | Status |
|---|---|---|
| 9.1 | Model-type-aware conservative bias direction | ✅ Done |
| 9.2 | Range-bound selection moved to StandardizationService | ✅ Done |
| 9.3 | Audit trail correctness; bias-correction layer removed; confidence numbers removed; multi-source citations; manifest | ✅ Done |
| 9.4 | Out-of-range clamping; default-organism structured event; thermal_inactivation routing fix | ✅ Done |
| 9.5 | Sourcing of `rules.py` interpretation values | 🔴 Designed (tier split: standards-backed / convention-backed / linguistic-only), not started |
| 9.6 | Standardization-block-as-a-list refactor (chained events) | 🔴 Filed in §16, deferred |
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

The system stacks several conservative heuristics: upper-bound selection from RAG ranges (for growth direction), conservative defaults for missing values (Salmonella, abuse temperature, neutral pH, high aw), and ComBase default lag h₀ values per organism. Compounded, the predicted log increase can be 2.5–3.5× higher than a reasonable human calculation. Risk: "crying wolf" — operators learn to discount the tool.

**Note (2026-04-28):** The earlier ×1.2 / ×0.8 duration multiplier was part of this stack until Phase 9.3, when it was removed (see §8.7). Conservatism is now committed in two well-defined places only — default values and range-bound selection — which simplifies the bias-stack analysis but does not eliminate it. Multiple conservative defaults can still compound; the principle is unchanged.

**Two agreed mitigations, both planned:**
- **Short-term:** cumulative bias indicator in the output ("this prediction uses N conservative assumptions; it represents a precautionary upper bound, not a best estimate") with a threshold that flags when more than two conservative defaults have been applied. Discoverable from the audit response (`defaults_imputed` count + range_bound_selection event count where direction = upper).
- **Research version:** move toward distributional uncertainty propagation (Monte Carlo) aligned with standard QMRA methodology. Itself a publishable contribution.

---

## 12. Known inconsistencies and items to confirm

Items worth verifying the next time Daniel works on the related area:

1. **Project name in `settings.py` / tests.** `Settings.app_name` reads "Problem Interpretation Module" (see `test_config.py`). Current project name is PTM; "Problem Interpretation Module" is the broader tentative project name (§1.2). Low-priority rename, but ensure current sessions don't get misled by the config value.
2. **Ratkowsky vs. Baranyi in documentation.** Implementation is Baranyi + 2nd-order polynomial secondary (§5.4); some legacy text and an advisory-review aside described it as Ratkowsky. Old tech docs (`problem_translation_module_complete_techincal_documentation.md`, `grounding_service_documentation.md`, `grounding_service_architecture_expanded.md`) should be either updated or formally retired in favour of the planned `specifications.md`.
3. **Two query artefacts.** `sensitivity_analysis_queries.md` (30 queries, paper-oriented) vs. `benchmarks/datasets/extraction_queries.json` (engineering ground truth for exp_3_3). Overlap unknown; consolidation or derivation relationship not documented.
4. **CDC-2019 rows missing from `pathogen_characteristics.csv`.** Source is registered; rows not yet populated (§6.3).
5. **`test_llm_client.py` content.** Inspection shows its test classes duplicate `test_config.py` rather than testing the LLM client (likely a mis-saved file). Verify and restore.
6. **`data_year` and `notes` columns** specified in the pathogen-characteristics schema but not present in the CSV. Schema documentation should be aligned with file content.
7. **Embedding-fallback path verification.** The temperature embedding-fallback path exists in `rules.py` but no captured live query has triggered it during testing. The path's structural correctness has been verified against synthetic fixtures only. Worth a query that genuinely fires this path before relying on its production behaviour.

### Resolved in this session (2026-04-28)

The following inconsistencies present in v1.1 have been resolved in v1.2:

- ~~`default_ph_neutral` value (6.5 vs 7.0)~~ — resolved: 7.0 is the current default (§5.3).
- ~~Bias correction direction documentation~~ — resolved: bias correction layer removed entirely (§8.1, §8.7); the documentation now reflects the simpler architecture.
- ~~Audit metadata pre-standardization snapshot~~ — resolved: orchestrator now captures post-standardization (§5.5).
- ~~`bias_corrections` list with optimistic-duration entries~~ — resolved: list removed from response shape; replaced by `defaults_imputed` (structured) for the only case that remained.

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
| 1.2 | 2026-04-28 | Major audit-trail and architecture cleanup landed. Phases 9.2 / 9.3 / 9.4 closed. Specific changes: (a) range-bound selection moved from GroundingService to StandardizationService — §5.2, §5.3, §8.8; (b) bias-correction layer removed entirely (no duration multiplier, no temperature bump) — §5.3, §8.1, §8.7; (c) confidence numbers removed (per-rule, per-field, overall, intent) — §5.2, §5.6, §8.7; (d) audit metadata captured post-standardization with structured per-field `standardization` block populated for all events — §5.5, §5.6, §8.9; (e) out-of-range values clamped (not extrapolated) with structured `RangeClampInfo` — §8.10; (f) multi-source citation attribution at ingestion — §8.11; (g) RAG manifest at ingestion for store provenance stamping — §8.12; (h) default organism imputation as structured event — §8.13; (i) thermal_inactivation routing fixed via intent classifier prompt — §10.1. Closed inconsistencies #2 (default_ph_neutral), #3 (bias direction), #6 (audit pre-standardization snapshot), and removed `bias_corrections` from response shape. Standardization-block-as-a-list refactor filed in §16 as a deferred future enhancement. Older tech docs (`problem_translation_module_complete_techincal_documentation.md`, `grounding_service_documentation.md`, `grounding_service_architecture_expanded.md`) are now formally out of date pending replacement by a `specifications.md` reverse-engineered from the codebase (planned). |

---

## 16. Deferred changes (filed but not yet implemented)

### standardization-block-as-a-list refactor (deferred)
Convert `ValueProvenance.standardization` from T | None to list[T] so chained events on the same field (e.g., range_bound_selection followed by range_clamp) are explicit rather than collapsed to last-event-wins.

Scope: small, mechanical. ~half day.
Touches: metadata model, API schema, standardization service (append vs overwrite), audit builder, tests, frontend (Zod + disclosure rendering).
Risk: one design question — does the disclosure render chained events as a sequence or stack them as parallel events? Resolve before implementation.
Why deferred: current "last-event-wins" workaround is correct for the common case. Refactor only matters when the chain case occurs in practice and audit honesty for it becomes load-bearing.
Trigger to revisit: when a regulator or downstream consumer asks why a clamp event "lost" its preceding range-bound selection in the audit, or when chained events become common enough to misread.


*End of PTM session context document.*
