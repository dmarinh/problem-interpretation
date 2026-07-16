# PTM Specifications

**Version:** 1.0  
**Date:** 2026-04-29  
**Source:** Reverse-engineered from codebase  

This file describes what the code does. Where a docstring or context document describes intended behaviour that differs from the code, the code's behaviour is documented and the discrepancy is noted.

---

## 1. Purpose and Scope

The Predictive Microbiology Translation Module (PTM) is a FastAPI service that translates natural-language food safety queries into structured parameters for ComBase predictive microbiology models, executes those models locally, and returns the mathematical results with a full, post-standardization audit trail.

PTM does not interpret results in natural language (that is the planned future Result Interpretation Module) and does not ask the user clarifying questions interactively (planned for Phase 12). When information is missing, PTM makes documented conservative assumptions.

The module is scoped to the ComBase broth-model family: polynomial secondary models for growth, thermal inactivation, and non-thermal survival. Three model types are supported (GROWTH, THERMAL_INACTIVATION, NON_THERMAL_SURVIVAL), mapping to ComBase ModelIDs 1, 2, and 3 respectively.

---

## 2. Architecture Overview

```
User Query (natural language)
    │
    ▼
┌──────────────────────────────────────────────────┐
│  1. SEMANTIC PARSER                               │
│  LLM + Instructor → ExtractedScenario            │
│  (food, temperature, duration, pathogen,          │
│   environmental conditions, implied_model_type,   │
│   is_multi_step, scenario-type flags)             │
└──────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────┐
│  2. GROUNDING SERVICE                             │
│  ExtractedScenario → GroundedValues               │
│  Rules: "room temperature" → 25°C                 │
│  RAG: chicken → pH 6.2–6.4, aw 0.99              │
│  Ranges stored with range_pending=True            │
│  No bound selection here                          │
└──────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────┐
│  3. STANDARDIZATION SERVICE                       │
│  GroundedValues → ComBaseExecutionPayload         │
│  (1) Range-bound selection (model-type-aware)     │
│  (2) Conservative default imputation              │
│  (3) Range clamping to model valid ranges         │
│  (4) Payload construction                         │
│  No bias-correction layer                         │
└──────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────┐
│  4. COMBASE ENGINE                                │
│  ComBaseExecutionPayload → ComBaseExecutionResult │
│  Polynomial secondary model (15 coefficients)    │
│  Per-step μ_max, log change, doubling time        │
└──────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────┐
│  5. ORCHESTRATOR                                  │
│  Coordinates all stages                           │
│  Captures audit metadata POST-standardization     │
│  Builds InterpretationMetadata                    │
│  Returns TranslationResult                        │
└──────────────────────────────────────────────────┘
    │
    ▼
TranslationResult → API → TranslationResponse
```

The orchestrator (stage 5) is the coordination layer, not a processing stage in itself. Each of stages 1–4 is a separate service with a singleton accessor.

---

## 3. Pipeline Stages

### 3.1 SemanticParser

**Location:** `app/services/extraction/semantic_parser.py`

**Responsibilities:** Translate free-text user input into a typed `ExtractedScenario` using LLM + Instructor structured extraction. Also classifies intent and supports clarification responses.

**I/O:**
- Input: `str` (natural language query), optional conversation context
- Output: `ExtractedScenario` (Pydantic model)

**Methods:**
- `extract_scenario(user_input, conversation_context=None) → ExtractedScenario`
- `classify_intent(user_input) → ExtractedIntent`
- `extract_clarification_response(user_response, original_question, options=None) → ExtractedClarificationResponse`
- `extract_generic(response_model, user_input, system_prompt) → T` (generic extraction)

**LLM call:** `SCENARIO_EXTRACTION_PROMPT` instructs the model to extract food description, state, pathogen, temperatures, durations, environmental conditions, scenario-type flags (`is_cooking_scenario`, `is_storage_scenario`, `is_non_thermal_treatment`), `implied_model_type`, and `initial_inoculum_log_cfu`. Temperature is converted to Celsius; duration to minutes. Ranges are captured if given. Initial inoculum is converted from raw CFU/g to log₁₀ CFU/g (e.g., 1000 CFU/g → 3.0); left null if not explicitly stated.

**`implied_model_type` inference rules (in system prompt):**
- Temperature > 50°C for cooking → `thermal_inactivation`
- Storage / holding → `growth`
- Non-thermal treatment (acid, drying, preservatives, HPP) → `non_thermal_survival`
- Null if unclear

**Edge cases:**
- All `ExtractedScenario` fields are optional (user rarely provides complete information)
- `is_multi_step=True` with populated `time_temperature_steps[]` triggers the multi-step path in GroundingService
- LLM temperature is 0.1 (`settings.llm_temperature`) for determinism

**Side effects:** None. SemanticParser does not write to GroundedValues or InterpretationMetadata.

**Singleton:** `get_semantic_parser()` / `reset_semantic_parser()`

---

### 3.2 GroundingService

**Location:** `app/services/grounding/grounding_service.py`

**Responsibilities:** Resolve `ExtractedScenario` fields to numeric values with provenance, using a strict priority hierarchy. Preserve both bounds for any range value; do not select bounds here.

**I/O:**
- Input: `ExtractedScenario`
- Output: `GroundedValues` (flat key-value store with per-field `ValueProvenance`)

**Value source priority (highest to lowest):**
1. `USER_EXPLICIT` — value stated directly by user ("pH 6.5", "25°C")
2. `USER_INFERRED` — value derived from linguistic rules ("room temperature" → 25°C)
3. `RAG_RETRIEVAL` — value retrieved from the primary food-properties query (specific-food doc above 0.70 threshold)
4. `RAG_RETRIEVAL_FALLBACK` — value retrieved via per-field secondary query (category-level doc, threshold 0.62)
5. `RAG_RETRIEVAL_CATEGORY_BRIDGE` — value retrieved via the FoodEx2 taxonomy bridge (Tier 3; see below)
6. `CONSERVATIVE_DEFAULT` — safety default (applied in StandardizationService, not here)
6. `COMPOSITE_FOOD_DEFAULT` — same safety-floor tier as `CONSERVATIVE_DEFAULT` but distinguished by reason: retrieval was deliberately skipped because the food description matched a composite-dish keyword. The matched keyword is recorded on `GroundedValues.composite_skip` and surfaces in the `DefaultImputed.reason` string.

Higher-priority sources are never overwritten by lower-priority sources.

**Processing sequence for `ground_scenario()`:**
1. Ground environmental conditions (pH, aw, CO2, nitrite, lactic acid, acetic acid) from `ExtractedScenario.environmental_conditions` — `USER_EXPLICIT` source
2. Ground pathogen from `scenario.pathogen_mentioned` — `USER_EXPLICIT` via `ComBaseOrganism.from_string()` alias dict lookup
3. Three-tier RAG retrieval for food pH and aw (only if not already grounded) — see **Food property retrieval** below
4. Two-stage RAG lookup for pathogen (only if organism not yet grounded): Stage 1 calls `query_pathogen_hazards()` to resolve the food description to a canonical `food_name` metadata key; Stage 2 calls `get_hazards_for_food(food_name)` to fetch all hazard documents for that food and selects the pathogen with the highest `annual_deaths_us` (deterministic danger ranking). `extraction_method` is `"ranked_by_annual_deaths"` on success. When Stage 1 is below threshold, Stage 2 returns empty, or Stage 2's top document has no `ComBaseOrganism` mapping, the **category-level pathogen fallback** fires instead: resolves food → `ptm_category` (FoodEx2 bridge, threshold 80) → IFT-2003-T1 categories (from `data/rag/ift_category_alignment.csv`) → union of pathogens (from `data/rag/pathogen_food_associations.csv`) → ranked by `annual_deaths_us` (from `data/rag/pathogen_characteristics.csv`) → top `ComBaseOrganism`-mappable candidate. `extraction_method` is `"category_fallback_ranked_by_annual_deaths"`; `source` is `RAG_PATHOGEN_CATEGORY_FALLBACK`. Full provenance is attached as `ValueProvenance.pathogen_category_fallback` (`PathogenCategoryFallbackInfo`). A transparency warning is appended to `GroundedValues.warnings`. The fallback fails closed at every step (bridge disabled, bridge miss, no IFT mapping, no candidate pathogens, no characteristics entry, all candidates unmapped) — the organism stays ungrounded, not defaulted. Each of these six early-return points populates `GroundedValues.organism_failure` with a structured `OrganismGroundingFailure` (`stage`, `detail`, and — for the category-resolved-but-no-hazard-data case — `resolved_category`/`match_score`) in addition to the existing `mark_ungrounded()` warning string, mirroring how `bridge_attempts` records a structured near-miss for ph/aw (see Tier 3 below). `None` when organism grounding succeeds via any path. Pathogens absent from `pathogen_characteristics.csv` are excluded from ranking; pathogens with `annual_deaths_us = 0` are ranked last but not excluded.

**Food property retrieval (`_ground_food_properties`):** Composite-food guard followed by a three-tier design.

*Composite-food guard (pre-Tier-1):* Before any retrieval call, `_ground_food_properties` normalises the food description (lowercase, punctuation-stripped, whitespace-collapsed) and checks it against `_COMPOSITE_KEYWORDS` (`grounding_service.py`). If a keyword token matches (e.g. "soup", "chili", "lasagna") or the multi-word string "stir-fry"/"stir fry" is present, the method records the matched keyword in `GroundedValues.composite_skip` for each field still needing grounding (`"ph"` and/or `"water_activity"`), then returns immediately — no retrieval is attempted. Downstream, the orchestrator copies `composite_skip` to `InterpretationMetadata.composite_skip`; the standardization service generates a reason string naming the matched keyword; and the route builder assigns `ValueSource.COMPOSITE_FOOD_DEFAULT` rather than `CONSERVATIVE_DEFAULT` for the affected fields. The guard fires before all three retrieval tiers so composite queries cannot reach even Tier 1 and accidentally match a single-ingredient doc at high confidence.

*Tier 1 — primary query* (`query_food_properties`, threshold 0.70): single query `"{food} pH water activity properties"` against `TYPE_FOOD_PROPERTIES`. If above threshold, extracts pH and aw from the top document's text using hybrid regex+LLM extraction. Source tier: `RAG_RETRIEVAL`. A specific-food row may have only one field populated (e.g., the `chicken` row has pH but no aw); in that case only the present field is grounded.

*Tier 2 — per-field fallback* (`_ground_field_fallback`, threshold 0.62): fires for each field still ungrounded after Tier 1, regardless of whether Tier 1 missed threshold entirely or the top doc lacked the field. Issues a targeted single-property query:
- Missing pH: `"{food} pH acidity"` via `query_food_ph()`
- Missing aw: `"{food} water activity aw moisture"` via `query_food_water_activity()`

Tier 2 can match category-level docs (e.g., `"fresh poultry water activity 0.99–1.0"`) that Tier 1 may miss or not extract from. Source tier: `RAG_RETRIEVAL_FALLBACK`. The `RetrievalResult` for a Tier 2 retrieval has `attributed_field` set to the specific field name (`"ph"` or `"water_activity"`); the Tier 1 food-properties retrieval has `attributed_field=None` (it may populate both fields from a single doc). The pathogen retrieval (`_ground_pathogen_from_rag`) sets `attributed_field="organism"` so the audit routing selects it unambiguously regardless of the query string's vocabulary.

*Tier 3 — FoodEx2 taxonomy bridge* (`_ground_via_taxonomy_bridge`, `app/services/grounding/taxonomy_bridge.py`): fires after both Tier 1 and Tier 2 for any field still ungrounded. By the time a query reaches the bridge it has already passed the composite-food guard above. Disabled when `PTM_TAXONOMY_BRIDGE_ENABLED=false` (env-var switch, default enabled). Performs deterministic food-name fuzzy matching against `data/rag/food_taxonomy.csv` (2,917 FoodEx2 MTX entries) to resolve a `ptm_category` and `matched_state`, then performs a **state-aware curated lookup** against `data/rag/category_level_rows.csv`. Source tier: `RAG_RETRIEVAL_CATEGORY_BRIDGE`. Scoring uses composite `(token_set_ratio, fuzz.ratio)` — token_set_ratio for recall, fuzz.ratio as tiebreaker (penalises length mismatch). Threshold: 80 (calibrated: min true-positive 90.9, max true-negative 57.1, gap 33.8 points; 80 provides 23-point margin above nearest true-negative). An alias map (`data/food_taxonomy_aliases.csv`) rewrites consumer vocabulary (e.g. "beef" → "bovine") before fuzzy matching. State-aware curated lookup: `TaxonomyBridge.lookup_category_level_row(category, state, field)` looks up the single curated row in `category_level_rows.csv` for the resolved `(ptm_category, state, field)` triple. The curated file holds exactly 5 rows: fresh-poultry aw, fresh-meat aw, cured-meat aw, fresh-fish pH, eggs aw. The `matched_state` from the taxonomy CSV is normalised by `_apply_state_default` ("unspecified"/"" → "fresh"); the conversion is recorded as `CategoryBridgeInfo.assumed_state`. When no curated row exists for the resolved triple, `GroundedValues.bridge_attempts[field]` is populated with a `CategoryBridgeInfo` (including `query_state`) so StandardizationService can emit an informative reason string rather than a silent default. Provenance carries a `CategoryBridgeInfo` on `ValueProvenance.category_bridge`.

`CONSERVATIVE_DEFAULT` fires only when all three tiers produce no hit.

*Threshold calibration (2026-04-30):* 13 known-good food/property pairs scored ≥ 0.6587 on Tier 2 queries; 8 should-not-match cases scored ≤ 0.5991. The gap is 0.0596; 0.62 sits in it with ~0.04 margin on each side. Key validated cases: `"chicken" → water_activity` finds the `"fresh poultry"` aw doc at 0.7145; `"poultry" → ph/aw` finds category docs at 0.6896/0.7584.
5. If `scenario.is_multi_step and scenario.time_temperature_steps` → `_ground_multi_step_profile()` (results to `grounded.steps`, not to flat key-value store)
6. Otherwise → single-step `_ground_temperature()` and `_ground_duration()`
7. Ground initial inoculum — if `scenario.initial_inoculum_log_cfu is not None`, sets `"initial_inoculum_log_cfu"` in the flat key-value store with `ValueSource.USER_EXPLICIT`, `extraction_method="llm_extraction"`. No default is applied here; the default is applied downstream in StandardizationService.

**Range handling:** When a range is extracted from user input or from RAG text, the lower bound is stored as the placeholder value in `grounded.values`, and `ValueProvenance.range_pending=True` and `parsed_range=[min, max]` are populated. Bound selection happens in StandardizationService. Grounding never collapses a range to a single value.

**Multi-step path:** `_ground_multi_step_profile()` iterates `scenario.time_temperature_steps`, sorts by `sequence_order`, resolves temperature and duration for each step, and appends `GroundedStep` objects to `grounded.steps`. Steps with unresolvable values store `None`; StandardizationService handles defaults per step. Multi-step results are in `grounded.steps`, never in `grounded.values`.

**Numeric extraction from RAG text:** Hybrid extraction:
1. Regex (fast): handles single values (`pH 6.0`), ranges with hyphen (`pH 5.9-6.2`), `to` ranges, `between/and` ranges
2. LLM fallback (when regex fails and `use_llm_extraction=True`): calls `LLMClient.extract()` with `FOOD_PROPERTIES_EXTRACTION_PROMPT`
3. Domain validation applied after extraction: pH must be 0–14; aw must be 0–1; values outside these bounds are discarded

**Temperature interpretation (embedding fallback):** When a temperature description matches no substring rule in `TEMPERATURE_INTERPRETATIONS`, `find_temperature_by_similarity()` encodes the description with `all-MiniLM-L6-v2` and computes cosine similarity against `TEMPERATURE_CANONICAL_PHRASES`. Threshold: `EMBEDDING_SIMILARITY_THRESHOLD = 0.50` (`app/config/rules.py:448`). If above threshold, returns a synthetic `InterpretationRule` with `similarity` and `canonical_phrase` set. For duration, no embedding fallback exists; unresolved descriptions mark the field ungrounded.

**Provenance fields populated by GroundingService:**
- `source` (ValueSource enum)
- `extraction_method` ("direct", "regex", "llm", "regex+llm", "rule_match", "embedding_fallback", "ranked_by_annual_deaths", "category_fallback_ranked_by_annual_deaths")
- `original_text` (raw text from RAG or user)
- `retrieval_source` (doc_id for RAG values)
- `raw_match` (matched text fragment from regex before parsing)
- `parsed_range` ([min, max] when extracted from a range)
- `range_pending` (True when both bounds preserved; always False after standardization)
- `matched_pattern`, `rule_conservative`, `rule_notes` (for USER_INFERRED values)
- `embedding_similarity`, `canonical_phrase` (for embedding-fallback values)

**Side effects:** Appends `RetrievalResult` objects to `grounded.retrievals` (one per RAG call; Tier 2 fallback retrievals have `attributed_field` set). Appends warning strings to `grounded.warnings` for unresolvable fields.

**Confidence levels:** Defined in `RetrievalService._classify_confidence()`:
- HIGH: cosine similarity ≥ 0.85
- MEDIUM: similarity ≥ `settings.global_min_confidence` (default 0.65)
- LOW: similarity > 0.0
- FAILED: similarity ≤ 0.0

**Retrieval thresholds (`settings.py`):**
- `food_properties_confidence = 0.70` — used by `query_food_properties()` (Tier 1 primary)
- `food_properties_fallback_confidence = 0.62` — used by `query_food_ph()` and `query_food_water_activity()` (Tier 2 per-field fallback)
- `pathogen_hazards_confidence = 0.75` — used by `query_pathogen_hazards()`
- `global_min_confidence = 0.65` — default for other queries

**Singleton:** `get_grounding_service()` / `reset_grounding_service()`

---

### 3.3 StandardizationService

**Location:** `app/services/standardization/standardization_service.py`

**Responsibilities:** Transform `GroundedValues` into a `ComBaseExecutionPayload`. Performs exactly four operations:
1. Range-bound selection for pending ranges
2. Conservative default imputation for missing required values
3. Range clamping to ComBase model valid ranges
4. Payload construction

There is no bias-correction layer. Conservatism is committed in exactly two places: (a) default values and (b) range-bound selection.

**I/O:**
- Input: `GroundedValues`, `ModelType`
- Output: `StandardizationResult` (contains `payload`, `defaults_imputed[]`, `range_clamps[]`, `warnings[]`, `missing_required[]`)

**Conservative direction by model type:**
- `GROWTH` / `NON_THERMAL_SURVIVAL`: upper bound = more growth/survival = worse outcome
- `THERMAL_INACTIVATION`: lower bound = less kill = worse outcome

**Operation 1 — Range-bound selection (`_select_range_bound()`):**  
When `prov.range_pending=True` and `prov.parsed_range=[min, max]`:
- Selects `range_max` for GROWTH/NON_THERMAL_SURVIVAL
- Selects `range_min` for THERMAL_INACTIVATION
- Writes `RangeBoundSelection(rule="range_bound_selection", direction, reason, before_value=[min,max], after_value)` to `prov.standardization`
- Sets `prov.range_pending=False`
- Does NOT add to `defaults_imputed` or emit a warning (it is mechanical and routine)

**Operation 2 — Default imputation (conservative defaults):**  
When a required value is absent from `GroundedValues`:

| Field | Default | Rationale |
|---|---|---|
| `temperature_celsius` (GROWTH/NON_THERMAL) | `25.0°C` (`settings.default_temperature_abuse_c`) | Abuse temperature — warm enough for rapid growth |
| `temperature_celsius` (THERMAL_INACTIVATION) | `60.0°C` (`settings.default_temperature_inactivation_conservative_c`) | Below typical pasteurization — conservative for less kill |
| `ph` | `7.0` (`settings.default_ph_neutral`) | Neutral; near-optimal for pathogen growth; no protective acidity |
| `water_activity` | `0.99` (`settings.default_water_activity`) | High; maximizes predicted growth |
| `duration_minutes` (single-step only) | `10080.0 min` (7 days) (`settings.default_long_window_minutes`) | Single-step only — long window ensuring trajectory reaches cap. Source: `LONG_WINDOW_DEFAULT`. Multi-step duration is a required field. |
| `initial_inoculum_log_cfu` | `model.defaults.inoculum` from `DefaultInoc` CSV column; fallback `3.0` when registry unavailable | Model-specific experimental inoculum; fallback used only when the ComBase registry lookup fails |

`organism` is not in this table — it is not defaulted. See "Missing required values" below.

Each imputation produces a `DefaultImputed(field_name, imputed_value, reason, source)` appended to `StandardizationResult.defaults_imputed`. `source` carries the `ValueSource` variant (`LONG_WINDOW_DEFAULT` for duration; `None` for older defaults that predate the field). A warning string is also emitted for missing critical fields (organism, temperature) and for the long-window duration default.

**Operation 3 — Range clamping:**  
When a value falls outside the ComBase model's valid range (from `ComBaseModelConstraints`):
- Clamps to nearest boundary using `max(min_val, min(value, max_val))`
- Produces `RangeClamp(field_name, original_value, clamped_value, valid_min, valid_max, reason)` appended to `StandardizationResult.range_clamps`
- Emits a warning string
- The model is evaluated at the clamped value (no extrapolation)

When range-bound selection AND clamping both fire on the same field, `prov.standardization` records only the clamp (last event wins). The pre-clamp range is recoverable from `prov.parsed_range`. This is a known limitation (deferred refactor: standardization-block-as-a-list).

**Operation 4 — Payload construction:**  
Assembles `ComBaseExecutionPayload` with:
- `ComBaseModelSelection(organism, model_type, factor4_type)`
- `ComBaseParameters(temperature_celsius, ph, water_activity, initial_inoculum_log_cfu, factor4_type, factor4_value)`
- `TimeTemperatureProfile` (multi-step or single-step)

**Initial inoculum resolution (`_get_initial_inoculum`):**  
Called during operation 2. Priority: (1) user-supplied value from `grounded.get("initial_inoculum_log_cfu")`; (2) `model.defaults.inoculum` from the ComBase registry; (3) fallback `3.0` when no registry match. A plausibility guard discards user-supplied values outside `(-2.0, 16.0)` log CFU/g with a warning, then falls through to the default. No range-bound selection applies to inoculum.

For multi-step scenarios, `_build_multi_step_profile()` iterates `grounded.steps`, applies per-step defaults and clamping, re-numbers steps sequentially (filling LLM-generated gaps like [1,2,4]), and validates that `step_order` is contiguous starting from 1.

**Duration pass-through:** Duration is passed unchanged. USER_INFERRED values carry their own conservatism via the rule's chosen point.

**Missing required values:** `StandardizationResult.missing_required` is populated in exactly three reachable cases:
- `organism` ungrounded after all grounding paths (user statement, food-specific RAG hazard lookup, category-level pathogen fallback) fail — `standardization_service.py:133-136`. Organism has no default.
- `organism` grounded but not executable for the resolved `(model_type, factor4_type)` — no `data/combase_models.csv` row exists for that exact combination (Phase A0.5b, 2026-07-16) — `standardization_service.py:145-150`, checked via `ComBaseModelRegistry.is_executable()`. The entry is `"organism ({name} is not supported for {model_type} predictions)"`, human-readable rather than a short code; `_missing_key_to_audit_key()` (`orchestrator.py`) maps both this and the plain ungrounded-organism case to the same `"organism"` audit key. See §5.4 for the current example (`sf`/Shigella flexneri, no plain-growth row).
- A multi-step step with an unresolvable duration, recorded as `"duration (step N)"` — `standardization_service.py:742`. Multi-step temperature falls back to its conservative default; multi-step duration does not.

Single-step duration can never populate `missing_required` — it always falls back to `LONG_WINDOW_DEFAULT` (see the table above). Single-step temperature likewise always falls back to a default and cannot populate it.

Consequence: `orchestrator.py:181-184` sets `SessionStatus.FAILED`, `success=False`, `error="Missing required values: ..."`. These three cases are the only reachable end-user failure modes of the pipeline (excluding out-of-scope/information-query intent classification and unhandled exceptions).

**Singleton:** `get_standardization_service()` / `reset_standardization_service()`

---

### 3.4 ComBase Engine

**Location:** `app/engines/combase/`

**Responsibilities:** Execute ComBase polynomial model predictions. Loads model coefficients from CSV at startup. Executes predictions for each time-temperature step. Returns `ComBaseExecutionResult` with per-step and total log change.

**I/O:**
- Input: `ComBaseExecutionPayload`
- Output: `ComBaseExecutionResult`

**Mathematical model:** 15-coefficient second-order polynomial secondary model.

The polynomial:
```
ln(μ) = b0 + b1·T + b2·pH + b3·bw + b4·T·pH + b5·T·bw + b6·pH·bw
       + b7·T² + b8·pH² + b9·bw² + b10·F4 + b11·T·F4 + b12·pH·F4
       + b13·bw·F4 + b14·F4²
```

where:
- `T` = temperature (°C)
- `pH` = pH value
- `bw` = water activity term (model-type dependent, see below)
- `F4` = fourth factor value (0.0 when `Factor4Type.NONE`)
- `b0`–`b14` = model coefficients from CSV

**Water activity term `bw` (model-type dependent):**
- GROWTH: `bw = sqrt(max(0, 1 - aw))` (`app/engines/combase/calculator.py:170`)
- THERMAL_INACTIVATION: `bw = aw` (`app/engines/combase/calculator.py:170`)
- NON_THERMAL_SURVIVAL: `bw = sqrt(max(0, 1 - aw))` (same as GROWTH)

**μ_max sign (model-type dependent):**
- GROWTH: `μ_max = exp(ln_mu)` — positive
- THERMAL_INACTIVATION: `μ_max = -exp(ln_mu)` — negative (kill rate)
- NON_THERMAL_SURVIVAL: `μ_max = -exp(ln_mu)` — negative

**Doubling time:** `ln(2) / μ_max` — computed only for GROWTH models with positive μ_max; `None` for inactivation/survival.

**Log increase per step:** `μ_max × duration_hours / ln(10)` — negative for inactivation. For inactivation/survival models (`μ_max ≤ 0`), the formula is `μ_max × duration_hours` (no ln(10) division — the polynomial outputs a log₁₀ rate for these models). See `calculator.py:calculate_log_increase`.

**Physical plausibility cap:** After computing the per-step log change, the engine (`engine.py`) enforces a `_PHYSICAL_LOG_LIMIT = 15.0` threshold. If `|log_increase| > 15.0`, the value is clamped to `±15.0` and a warning is appended to `ComBaseExecutionResult.warnings` with the raw uncapped value. The warning propagates to `state.metadata.warnings` and surfaces in the API response `warnings` array. The cap does not alter any other audit field (provenance, range_clamps, defaults_imputed, or coefficients). The capped value is what appears in `step_predictions[*].log_increase` and `total_log_increase`.

**Multi-step execution:** Iterates `payload.time_temperature_profile.steps` in order. pH and aw are shared across all steps (from `payload.parameters`). Per-step temperature and duration come from each `TimeTemperatureStep`. `total_log_increase` is the sum across all steps. The `model_result` (scalar summary) uses the first step's calculation for `mu_max` and `doubling_time_hours` (back-compat for single-step consumers).

**Absolute population tracking:** After computing `total_log_increase`, the engine computes:
- `initial_log_cfu = payload.parameters.initial_inoculum_log_cfu`
- `final_log_cfu = initial_log_cfu + total_log_increase`

Both are returned in `ComBaseExecutionResult` and exposed in the API response.

**Note on model form:** The secondary model is a second-order polynomial. The `app/engines/combase/engine.py` comment describes this as "ComBase broth models". The ptm_context.md (§8.2) states the model is "Baranyi primary with second-order polynomial secondary". The calculator code implements the secondary model polynomial but does not implement a primary model (lag-phase dynamics). The `h0` and `y_max` values are present in the CSV and loaded into `ComBaseModel` but are not used in any calculation in `calculator.py`. This is a discrepancy between the model's metadata and the current calculator implementation.

**Validation:** `engine.execute()` raises `ValueError` if the requested organism/model_type/factor4_type combination is not found in the registry. `ComBaseEngine.is_available` is `True` only after `load_models()` has loaded at least one model.

**Singleton:** `get_combase_engine()` / `reset_combase_engine()`

---

### 3.5 Orchestrator

**Location:** `app/core/orchestrator.py`

**Responsibilities:** Coordinate the pipeline. Manage `SessionState` and `InterpretationMetadata`. Determine model type. Capture audit metadata post-standardization. Return `TranslationResult`.

**I/O:**
- Input: `str` (user query), optional `ModelType` override
- Output: `TranslationResult` (contains `.state`, `.success`, `.error`, `.execution_result`, `.metadata`)

**Pipeline execution sequence:**
1. Create `SessionState`, transition to `EXTRACTING`
2. Classify intent (`SemanticParser.classify_intent()`)
3. If `OUT_OF_SCOPE` or `INFORMATION_QUERY`, return error immediately
4. Extract scenario (`SemanticParser.extract_scenario()`)
5. Determine model type (`_determine_model_type()`)
6. Ground values (`GroundingService.ground_scenario()`), store provenance in metadata
7. Standardize (`StandardizationService.standardize()`), record defaults and clamps in metadata
8. Execute model (`ComBaseEngine.execute()`)
9. Record `ComBaseModelAudit` (post-execution, after organism is known)
10. Transition to `COMPLETED`, attach `SystemAudit`

**Model type determination priority (`_determine_model_type()`):**
1. Explicit `model_type` parameter (API caller override)
2. LLM inference: `scenario.implied_model_type` (if not None)
3. Temperature heuristic: `scenario.single_step_temperature.value_celsius > 50` → `THERMAL_INACTIVATION`
4. Scenario flag: `scenario.is_cooking_scenario` → `THERMAL_INACTIVATION`
5. Scenario flag: `scenario.is_non_thermal_treatment` → `NON_THERMAL_SURVIVAL`
6. Environmental condition: `env.ph_value < 4.5` → `NON_THERMAL_SURVIVAL`
7. Environmental condition: `env.water_activity < 0.90` → `NON_THERMAL_SURVIVAL`
8. Preservatives present (nitrite, lactic acid, acetic acid) → `NON_THERMAL_SURVIVAL`
9. Default: `GROWTH`

`_determine_model_type()` returns `tuple[ModelType, str]`, not a bare `ModelType`. Each of the nine branches above constructs and returns its own reason string inline (some are static, e.g. `"scenario flag: is_cooking_scenario"`; others are f-strings embedding the triggering value, e.g. `f"temperature heuristic ({temp}°C > 50°C → thermal inactivation)"`) — there is no separate reason-formatting step. The caller unpacks both into `effective_model_type, model_type_reason` and passes `model_type_reason` into `ComBaseModelAudit.selection_reason`.

**Audit metadata is post-standardization:** The orchestrator calls `_ground_values()` before standardization, but `add_provenance()` writes `ValueProvenance` objects to `metadata.provenance`. Since `StandardizationService` mutates `ValueProvenance` objects in-place (setting `prov.standardization`, clearing `prov.range_pending`), the provenance objects in `metadata.provenance` already carry the post-standardization state by the time the API layer reads them.

**`ComBaseModelAudit` capture:** Called after engine execution so the model's coefficients, valid ranges, and organism display name can be fetched from the registry (same lookup the engine used).

**SystemAudit:** `build_system_audit()` (`app/services/audit/system.py`) reads `data/vector_store/ingest_manifest.json` for RAG provenance, runs `git rev-parse --short HEAD` for `ptm_version`, and computes SHA-256 of `data/combase_models.csv`. If the manifest is absent, a warning is added to `metadata.warnings` ("RAG manifest missing — store provenance unknown") and manifest-sourced fields are emitted as `None`.

**Singleton:** `get_orchestrator()` / `reset_orchestrator()`

---

## 4. Data Model

### 4.1 ExtractedScenario (`app/models/extraction.py`)

| Field | Type | Description |
|---|---|---|
| `food_description` | `str \| None` | Food item as described (free text) |
| `food_state` | `str \| None` | raw / cooked / frozen / thawed (free text) |
| `pathogen_mentioned` | `str \| None` | Pathogen if explicitly stated |
| `is_multi_step` | `bool` | Whether the scenario has multiple time-temperature steps |
| `single_step_temperature` | `ExtractedTemperature` | Temperature for single-step scenarios |
| `single_step_duration` | `ExtractedDuration` | Duration for single-step scenarios |
| `time_temperature_steps` | `list[ExtractedTimeTemperatureStep]` | Steps for multi-step scenarios |
| `environmental_conditions` | `ExtractedEnvironmentalConditions` | pH, aw, CO2, nitrite, lactic/acetic acid |
| `concern_type` | `str \| None` | safety / spoilage / shelf life |
| `additional_context` | `str \| None` | Free text context |
| `is_cooking_scenario` | `bool` | LLM-inferred flag |
| `is_storage_scenario` | `bool` | LLM-inferred flag |
| `is_non_thermal_treatment` | `bool` | LLM-inferred flag |
| `implied_model_type` | `ModelType \| None` | LLM-inferred model type |
| `initial_inoculum_log_cfu` | `float \| None` | Initial bacterial count in log₁₀ CFU/g if stated by user; null if not mentioned |

`ExtractedTemperature` carries `value_celsius`, `description`, `is_range`, `range_min_celsius`, `range_max_celsius`. `ExtractedDuration` carries `value_minutes`, `description`, `is_ambiguous`, `range_min_minutes`, `range_max_minutes`.

### 4.2 GroundedValues (`app/services/grounding/grounding_service.py`)

A flat key-value store (not a Pydantic model):
- `values: dict[str, object]` — grounded values by field name
- `provenance: dict[str, ValueProvenance]` — per-field provenance
- `retrievals: list[RetrievalResult]` — all RAG calls made
- `warnings: list[str]` — unresolvable-field messages
- `ungrounded_fields: list[str]` — fields that could not be resolved
- `steps: list[GroundedStep]` — multi-step time-temperature steps (separate from flat values)
- `bridge_attempts: dict[str, CategoryBridgeInfo]` — keyed by field name ("ph", "water_activity"); populated when the taxonomy bridge resolved a category but no curated row exists in `category_level_rows.csv` for the `(category, state, field)` triple; read by StandardizationService to emit bridge-aware reason strings in `DefaultImputed` (includes `query_state` so the reason can name both category and state)
- `organism_failure: OrganismGroundingFailure | None` — the organism equivalent of `bridge_attempts`: populated at each of the six early-return points in `_category_pathogen_fallback()` (see §3.2) with `stage`, `detail`, and — for `CATEGORY_HAS_NO_HAZARD_DATA` only — `resolved_category`/`match_score`; `None` when organism grounding succeeds

Key names in `values`: `"temperature_celsius"`, `"duration_minutes"`, `"ph"`, `"water_activity"`, `"organism"`, `"co2_percent"`, `"nitrite_ppm"`, `"lactic_acid_ppm"`, `"acetic_acid_ppm"`.

`GroundedStep`: `step_order`, `temperature_celsius`, `duration_minutes`, `temp_provenance`, `dur_provenance`.

### 4.3 ComBaseExecutionPayload (`app/models/execution/combase.py`)

| Field | Type |
|---|---|
| `model_selection` | `ComBaseModelSelection` (organism, model_type, factor4_type) |
| `parameters` | `ComBaseParameters` (temperature_celsius, ph, water_activity, initial_inoculum_log_cfu, factor4_type, factor4_value) |
| `time_temperature_profile` | `TimeTemperatureProfile` (is_multi_step, steps[], total_duration_minutes) |
| `engine_type` | `EngineType` (default: `COMBASE_LOCAL`) |
| `model_type` | `ModelType` (synced from model_selection via validator) |

`TimeTemperatureProfile` validates that step orders are sequential from 1, and that `total_duration_minutes` equals the sum of step durations.

### 4.4 InterpretationMetadata (`app/models/metadata.py`)

Top-level session audit container. Fields:

| Field | Type | Description |
|---|---|---|
| `session_id` | `str` | Unique session identifier |
| `status` | `SessionStatus` | Pipeline status |
| `original_input` | `str` | User's raw query |
| `provenance` | `dict[str, ValueProvenance]` | Per-field provenance (written by orchestrator from grounded.provenance; mutations by standardization are in-place) |
| `defaults_imputed` | `list[DefaultImputed]` | Structured default-imputation events |
| `range_clamps` | `list[RangeClamp]` | Structured range-clamp events |
| `retrievals` | `list[RetrievalResult]` | All RAG calls |
| `warnings` | `list[str]` | String warning messages |
| `clarifications` | `list[ClarificationRecord]` | (Unused in current pipeline) |
| `combase_model` | `ComBaseModelAudit \| None` | Model selection audit block |
| `system` | `SystemAudit \| None` | Software/data state at prediction time |

### 4.5 ValueProvenance (`app/models/metadata.py`)

Tracks origin and transformations of a single value. Key fields:

| Field | Type | Description |
|---|---|---|
| `source` | `ValueSource` | Categorical source tier (USER_EXPLICIT, USER_INFERRED, RAG_RETRIEVAL, RAG_RETRIEVAL_FALLBACK, RAG_RETRIEVAL_CATEGORY_BRIDGE, CONSERVATIVE_DEFAULT, LONG_WINDOW_DEFAULT, etc.) |
| `original_text` | `str \| None` | Raw text from user or RAG |
| `retrieval_source` | `str \| None` | RAG doc_id |
| `transformation_applied` | `str \| None` | Free-text description of transformation (legacy, supplemented by structured `standardization` block) |
| `extraction_method` | `str \| None` | "regex", "llm", "regex+llm", "rule_match", "embedding_fallback", "direct" |
| `raw_match` | `str \| None` | Regex-matched text fragment |
| `parsed_range` | `list[float] \| None` | [min, max] when extracted from a range |
| `range_pending` | `bool` | Pipeline signal: True when bound selection not yet performed; always False in serialized output |
| `standardization` | `RangeBoundSelection \| None` | Structured record of the standardization event that fired (range_bound_selection or range_clamp); None if no event fired. When both fire on the same field, clamp overwrites range_bound_selection (last-event-wins; known limitation) |
| `matched_pattern` | `str \| None` | Rule pattern (USER_INFERRED values) |
| `rule_conservative` | `bool \| None` | Whether the matched rule was flagged conservative |
| `rule_notes` | `str \| None` | Human-readable rationale from rule |
| `embedding_similarity` | `float \| None` | Cosine similarity score (embedding-fallback only) |
| `canonical_phrase` | `str \| None` | Closest canonical phrase in embedding lookup |
| `category_bridge` | `CategoryBridgeInfo \| None` | Taxonomy bridge resolution record; non-null only when source is `RAG_RETRIEVAL_CATEGORY_BRIDGE`. Carries: `species` (food_description input), `resolved_category`, `taxonomy_code`, `taxonomy_label`, `taxonomy_source_id` (e.g. `EFSA-FoodEx2-MTX-12.0`), `matched_food_name`, `match_score` (token_set_ratio), `property_row_food_name`, `property_row_source_ids`, `query_state` (state used for curated lookup), `assumed_state` (non-empty when _apply_state_default converted "unspecified"/"" → "fresh"; empty when the taxonomy already carried a concrete state). |

**No confidence numbers.** The `source` enum tier is the reliability signal. The only numeric reliability score is `RetrievalResult.embedding_score` (cosine similarity = 1 - ChromaDB distance).

### 4.6 field_audit map

The API response's `field_audit` (under `audit` when `verbose=true`) is a `dict[str, FieldAuditEntry]`. It is the canonical post-standardization view of every value that reached the model.

`FieldAuditEntry` fields:
- `final_value: float | str | None` — post-standardization value (priority: clamped > range-bound-selected > organism display name > grounded value)
- `source: str` — ValueSource enum value string
- `retrieval: RetrievalAuditInfo | None` — RAG call details: query, `top_match` (the doc that supplied the value — null when no doc passed threshold), `runners_up`, and two optional diagnostic fields: `reranker_top` (present when the cross-encoder's top-ranked doc failed the embedding threshold gate and a lower-ranked doc was used instead) and `attempted_top` (present when all docs failed threshold; `top_match` is null in this case). Both carry `doc_id`, `content_preview`, `embedding_score`, `rerank_score`, and `skip_reason` (e.g. `"failed_embedding_threshold:0.70"`)
- `extraction: ExtractionAuditInfo | None` — how the value was extracted (method, raw_match, matched_pattern, conservative, notes, similarity, canonical_phrase)
- `standardization: StandardizationAuditInfo | None` — structured event (rule, direction, before_value, after_value, reason)

The `field_audit` map includes both grounded fields (from `metadata.provenance`) and defaulted fields (from `metadata.defaults_imputed`). It is the single complete map of all values used by the model. The legacy top-level `provenance` array is auto-derived from `field_audit` for backward compatibility.

`StandardizationAuditInfo.rule` values: `"range_bound_selection"`, `"range_clamp"`, `"default_imputed"`.

---

## 5. ComBase Model Registry

**Location:** `app/engines/combase/models.py`, `data/combase_models.csv`

### 5.1 CSV Schema

The CSV is semicolon-delimited with a BOM header. Columns:

| Column | Type | Description |
|---|---|---|
| `ModelID` | int | 1=Growth, 2=Thermal inactivation, 3=Non-thermal survival |
| `OrganismID` | str | Short code (e.g., "ss", "lm") |
| `Org` | str | Human-readable organism name |
| `Factor4ID` | str | "NULL", "co2", "nitrite", "lactic_acid", "acetic_acid" |
| `Factor4` | str | Display name for factor4 |
| `ymax` | float | Maximum population density |
| `h0` | float | Initial physiological state |
| `Coefficients` | str | Semicolon-separated 15-float string, quoted |
| `TempMin`, `TempMax` | float | Valid temperature range (°C) |
| `PHMin`, `PHMax` | float | Valid pH range |
| `AwMin`, `AwMax` | float | Valid aw range |
| `Factor4Min`, `Factor4Max` | float\|NULL | Valid factor4 range |
| `DefaultTemp`, `DefaultPH`, `DefaultAw`, `DefaultNaCl` | float | Model defaults |
| `DefaultFactor4` | float\|NULL | Default factor4 value |
| `DefaultInoc` | float | Default inoculum (log CFU) |
| `StdErr` | float | Model standard error |
| `H0StdErr` | float | h0 standard error |

**Note:** `ymax`, `h0`, `StdErr`, `H0StdErr` are loaded into `ComBaseModel` but are not used in the calculator (`calculator.py`). The calculator uses only `Coefficients` and model type.

### 5.2 Model Selection

Registry key: `f"{model_id}_{organism_id}_{factor4_type.value}"` (e.g., `"1_ss_co2"`)

`ComBaseModelRegistry.get_model(organism, model_type, factor4_type)` looks up by this compound key. Factor4 defaults to `Factor4Type.NONE`.

### 5.3 Valid Range Enforcement

`ComBaseModelConstraints` provides `is_temperature_valid()`, `is_ph_valid()`, `is_aw_valid()`, `clamp_temperature()`, `clamp_ph()`, `clamp_aw()`. Clamping is `max(min_val, min(value, max_val))`.

Clamping is applied by StandardizationService before payload construction. The engine's `ComBaseCalculator.calculate()` also validates ranges and can clamp internally when `clamp_to_range=True`, but the engine is called with `clamp_to_range=False` (`app/engines/combase/engine.py:115`) — meaning the engine relies on StandardizationService having already clamped. Warning messages from the calculator are still appended to `ComBaseExecutionResult.warnings`.

### 5.4 Supported Organisms (15)

| Enum Value | Code | Full Name |
|---|---|---|
| `AEROMONAS_HYDROPHILA` | ah | Aeromonas hydrophila |
| `BACILLUS_CEREUS` | bc | Bacillus cereus (with CO2) |
| `BROCHOTHRIX_THERMOSPHACTA` | bt | Brochothrix thermosphacta |
| `BACILLUS_SUBTILIS` | bs | Bacillus subtilis |
| `BACILLUS_LICHENIFORMIS` | bl | Bacillus licheniformis |
| `CLOSTRIDIUM_BOTULINUM_NONPROT` | cbn | Clostridium botulinum (non-prot.) |
| `CLOSTRIDIUM_BOTULINUM_PROT` | cbp | Clostridium botulinum (prot.) |
| `CLOSTRIDIUM_PERFRINGENS` | cp | Clostridium perfringens |
| `ESCHERICHIA_COLI` | ec | Escherichia coli (with CO2) |
| `LISTERIA_MONOCYTOGENES` | lm | Listeria monocytogenes/innocua (with CO2/nitrite/lactic/acetic) |
| `PSEUDOMONAS` | ps | Pseudomonas spp. |
| `SALMONELLA` | ss | Salmonellae (with CO2/nitrite) |
| `SHIGELLA_FLEXNERI` | sf | Shigella flexneri (with nitrite) |
| `STAPHYLOCOCCUS_AUREUS` | sa | Staphylococcus aureus |
| `YERSINIA_ENTEROCOLITICA` | ye | Yersinia enterocolitica (with CO2/lactic) |

**Enum-CSV reconciliation (Phase A0.5a, 2026-07-15):** A prior version of this table documented `BROCHOTHRIX_THERMOSPHACTA = "bl"` / `BACILLUS_STEAROTHERMOPHILUS = "bt"` as a harmless naming inconsistency, reasoning that "predictions still execute correctly since the registry key is the code, not the name." That was false: `ComBaseOrganism.from_string("brochothrix")` returned `"bl"`, which loaded the *Bacillus licheniformis* CSV row's coefficients under the Brochothrix name — a wrong-answer bug on a live path, not a cosmetic label mismatch. `BACILLUS_STEAROTHERMOPHILUS` had no corresponding row in `data/combase_models.csv` at all (verified across all `ModelID`s) and has been removed; its aliases ("bacillus stearothermophilus", "b. stearothermophilus") now resolve to `None`, so an unresolvable organism fails closed rather than silently loading the wrong model. `BACILLUS_LICHENIFORMIS` (`bl`) was added since its CSV row is real and was previously unreachable. This mapping is now verified by two parametrized tests in `tests/unit/test_combase_models.py::TestComBaseOrganismMatchesCSV`: `test_organism_value_resolves_to_matching_csv_row` (alias-dict self-consistency — the `get_models_for_organism()`/`_by_organism` path, built via `from_string()`) and `test_organism_value_matches_raw_csv_organism_id` (`.value` resolved directly against the CSV's raw `OrganismID`, with no enum machinery in between — the thing `registry.get_model()`'s execution path actually keys off). The class of drift this section previously documented as benign is now caught automatically rather than trusted to a spec note.

**`sf` (Shigella flexneri) has no plain-growth row (Phase A0.5b, 2026-07-16):** Its only CSV row is `ModelID=1, Factor4=nitrite` — there is no `(ModelID=1, Factor4=NONE)` row, and no row at all for `ModelID=2`/`3`. Shigella is therefore not executable for a growth prediction unless the scenario supplies nitrite. This is now enforced in `StandardizationService.standardize()` via `ComBaseModelRegistry.is_executable(organism, model_type, factor4_type)`, checked before payload construction: if the grounded organism is not executable for the resolved `(model_type, factor4_type)`, standardization fails closed with a `missing_required` entry naming the organism and model type in plain language (e.g. `"organism (Shigella flexneri is not supported for growth predictions)"`), the same path as an ungrounded organism. Previously this surfaced only at `engine.execute()` as `ValueError("Model not found: sf / growth / none")`, caught by the orchestrator's generic exception handler — internal short codes reaching the API caller with no audit block. `ComBaseEngine`'s `ValueError` remains in place as a defensive backstop (see §3.4); standardization catching it earlier is a better error, not a replacement for the invariant. `ComBaseModelRegistry.get_executable_organisms(model_type, factor4_type)` derives the full executable set from the loaded registry (no hardcoded organism lists) — see `tests/unit/test_combase_models.py::TestExecutableOrganisms`.

**`bt` Org spelling duplicate (data-quality artifact, not corrected):** `data/combase_models.csv` has two rows under `OrganismID=bt`: `Org="Brochothrix thermosphacta"` (`ModelID=1`) and `Org="Brochotrix thermosphacta"` (`ModelID=2`, missing the "h"). The CSV is authoritative and this is deliberately left as-is — both rows correctly bucket under `BROCHOTHRIX_THERMOSPHACTA` (the typo is in the genus spelling, not the `OrganismID`, so it doesn't affect model selection), and the reconciliation tests above are written to tolerate it (substring match on `"thermosphacta"`, present in both spellings).

### 5.5 Startup Loading

`app/main.py` lifespan handler loads `data/combase_models.csv` at startup. If the file is absent, the engine logs a warning and `is_available` remains `False`.

---

## 6. RAG Knowledge Base

### 6.1 Data CSV Files

All files in `data/rag/`. Loaded by `app/rag/data_sources/food_safety.py`.

| File | Vector Type | Source |
|---|---|---|
| `food_properties.csv` | `food_properties` | FDA-PH-2007, IFT-2003-T31/T33 |
| `pathogen_aw_limits.csv` | `pathogen_hazards` | IFT-2003-T32 |
| `pathogen_characteristics.csv` | `pathogen_hazards` | CDC-2011-T3 (CDC-2019 registered but not yet merged) |
| `pathogen_transmission_details.csv` | `pathogen_hazards` | CDC-2011-A1 |
| `pathogen_food_associations.csv` | `pathogen_hazards` | IFT-2003-T1 |
| `food_pathogen_hazards.csv` | `pathogen_hazards` | Derived from CDC + IFT |
| `tcs_classification_tables.csv` | `conservative_values` | IFT-2003-TA/TB |

### 6.2 Ingestion Pipeline

**Location:** `app/rag/ingestion.py`

`IngestionPipeline.ingest_text()` calls `TextLoader.chunk_text()` to split text, then adds chunks to ChromaDB via `VectorStore.add_documents()`.

**Document construction for food_properties.csv:** Each row produces a natural-language sentence. The `notes` field is appended as-is. Source attribution is read from dedicated per-field columns: `ph_source_id` (authority for pH values) and `aw_source_id` (authority for water activity values). The document's source list is derived as an ordered, deduplicated union — pH source first, aw source second if different — via `dict.fromkeys`. Each source ID is appended as a `[SOURCE-ID]` tag to the document text; the merged comma-separated string is stored in ChromaDB metadata as `source_id`.

Validation at ingestion: any row with a populated pH or aw range must declare its source ID; every declared source ID must appear in `data/sources/source_references.csv`. Either condition failing raises `ValueError` that aborts ingestion. `EXPECTED_FOOD_PROPERTIES_COUNT = 253` is asserted at end of function (`food_safety.py:169`).

### 6.3 RAG Manifest

Written by `IngestionPipeline.write_manifest()` to `data/vector_store/ingest_manifest.json`.

Fields:
- `ingested_at`: ISO-8601 UTC timestamp of ingestion
- `rag_store_hash`: SHA-256 (first 16 hex chars) of concatenated `{filename}:{size}:{mtime_ns}` for all CSVs in `data/rag/`
- `source_csv_audit_date`: mtime of `data/rag/rag_audit_changelog.md` (ISO-8601 UTC) or `null` if absent
- `total_chunks`: count of ingested chunks

Read at request time by `build_system_audit()` and attached to `SystemAudit` in every audit response.

### 6.4 ChromaDB Vector Store

**Location:** `app/rag/vector_store.py`

- Single collection `"knowledge_base"` with `hnsw:space = "cosine"` distance metric
- Persistent storage at `settings.vector_store_path` (default `./data/vector_store`)
- Metadata filtering by `type` field (document types: `food_properties`, `pathogen_hazards`, `conservative_values`)
- Embeddings: `all-MiniLM-L6-v2` (384-dim, normalized) via `sentence-transformers`
- Similarity: cosine similarity = 1 - ChromaDB distance

### 6.5 Retrieval Service

**Location:** `app/rag/retrieval.py`

`RetrievalService.query()` fetches n_results from ChromaDB, optionally applies a reranker (cross-encoder), sorts by confidence, and returns the top result above threshold as `has_confident_result`.

Queries:
- `query_food_properties(food_description)`: `"{food} pH water activity properties"`, threshold 0.70 — Tier 1 primary
- `query_food_ph(food_description)`: `"{food} pH acidity"`, threshold 0.62 — Tier 2 per-field fallback for pH
- `query_food_water_activity(food_description)`: `"{food} water activity aw moisture"`, threshold 0.62 — Tier 2 per-field fallback for aw
- `query_pathogen_hazards(food_description)`: `"{food} food hazard"`, `where={"data_type": "food_pathogen_hazard"}`, threshold 0.75 — Stage 1 food-name resolver in `_ground_pathogen_from_rag`. Query restricted to `food_pathogen_hazard` subtype so Stage 1 only returns documents that carry `food_name` metadata (required for Stage 2). "food hazard" appears universally in the ingestion template ("Hazard for {food}: {pathogen}..."); earlier terms "pathogen bacteria contamination" were removed because they are only present in some foods' CDC notes, creating vocabulary asymmetry that suppressed retrieval for foods like rice.
- `get_hazards_for_food(food_name)`: metadata filter `{"food_name": food_name, "type": "pathogen_hazards"}` via `VectorStore.get_documents()`, sorted by `annual_deaths_us` descending — no embedding ranking involved

`_build_retrieval_metadata()` (`grounding_service.py`) converts `RetrievalResponse` to `RetrievalResult`, computing `embedding_score = 1.0 - distance` and capturing up to 3 runners-up with previews.

### 6.6 Source References

**Location:** `data/sources/source_references.csv`

Registry of all citable sources with columns: `source_id`, `short_name`, `document_title`, `authors`, `year`, `publisher`, `table_or_section`, `url`, `doi`, `access_date`.

`get_full_citations(source_ids)` (`app/services/audit/citations.py`) looks up source IDs and formats full bibliographic citations. These are included in `RetrievalResult.full_citations` and surfaced in the verbose audit response.

---

## 7. Audit Trail

### 7.1 Per-Field Structure

Every value that flows through the pipeline accumulates a `ValueProvenance` in `metadata.provenance[field_name]`. The `field_audit` map in the verbose API response is the post-standardization view of this provenance.

**Four event types:**

| Event | Emitter | Structured Record | Top-Level List | Warning String |
|---|---|---|---|---|
| RAG retrieval | GroundingService | `RetrievalResult` in `metadata.retrievals` | — | When retrieval fails |
| Range-bound selection | StandardizationService | `RangeBoundSelection` on `prov.standardization` | — | No warning |
| Default imputation | StandardizationService | `DefaultImputed` in `defaults_imputed` | `defaults_imputed` list | Yes (for temperature) |
| Range clamp | StandardizationService | `RangeClamp` in `range_clamps` | `range_clamps` list | Yes |

### 7.2 Audit Snapshot Timing

Audit metadata is captured post-standardization. The orchestrator writes `ValueProvenance` objects to `metadata.provenance` during grounding (before standardization), but StandardizationService mutates these objects in-place. By the time the API layer reads them, `prov.range_pending` is `False` and `prov.standardization` is populated.

`field_audit[X].final_value` reflects the value that reached the ComBase model:
1. Clamped value (if clamping occurred)
2. Range-bound-selected value (if `prov.standardization` is set)
3. Organism display name from `combase_model.organism_display_name` (for the `organism` field)
4. Pre-standardization grounded value (for explicit non-range fields)

### 7.3 System Context Block

`SystemAudit` (exposed as `audit.system` in verbose response):

| Field | Source |
|---|---|
| `rag_store_hash` | `ingest_manifest.json` |
| `rag_ingested_at` | `ingest_manifest.json` |
| `source_csv_audit_date` | `ingest_manifest.json` |
| `ptm_version` | `git rev-parse --short HEAD` |
| `combase_model_table_hash` | SHA-256 of `data/combase_models.csv` |

### 7.4 Empty-Array Policy

`range_clamps`, `defaults_imputed`, and `warnings` emit `[]` when no events fired. They never emit sentinel strings like `["(none applied)"]`. That rendering is a UI concern.

### 7.5 Legacy provenance Array

The top-level `provenance: list[ProvenanceInfo]` in `TranslationResponse` is auto-derived from `field_audit` in `_build_provenance_list()`. It is present for backward compatibility. `field_audit` is the authoritative map.

---

## 8. Out-of-Range Behaviour

When an input parameter falls outside a ComBase model's valid range:

1. StandardizationService calls `constraints.clamp_*(value)` to obtain the boundary value
2. `RangeClamp` is appended to `StandardizationResult.range_clamps` (structured, machine-readable)
3. `StandardizationAuditInfo(rule="range_clamp")` is written to `prov.standardization` (per-field structured record)
4. A warning string is appended to `StandardizationResult.warnings`

The model is evaluated at the clamped value. No extrapolation occurs.

**Rationale for clamping rather than refusal:** A prediction at the model boundary is more practically useful than a refusal. The user receives the closest defensible answer plus full audit transparency showing the original and clamped values.

**Known limitation:** When range-bound selection and clamping both fire on the same field, `prov.standardization` records only the clamp. The pre-clamp range remains recoverable from `prov.parsed_range`. A deferred refactor (standardization-block-as-a-list) would make both events visible; the trigger for this refactor is when a regulator asks why a clamp event "lost" its preceding range-bound selection.

---

## 9. Conservative Direction

### 9.1 The Two-Places Rule

Conservatism is committed in exactly two places:
1. **Default values** — applied by StandardizationService when a required field is absent
2. **Range-bound selection** — applied by StandardizationService when a value arrives as a range

There is no bias-correction layer. No duration multiplier. No temperature bump. Rules in `config/rules.py` carry their own conservatism by choosing the upper end of their underlying interval (e.g., "room temperature" → 25°C is the high end of 20–25°C). Adding a multiplier on top of that would double-count.

### 9.2 Default Values

| Field | Default | Conservative direction |
|---|---|---|
| temperature (GROWTH/NON_THERMAL) | 25.0°C | Abuse temperature — rapid growth |
| temperature (THERMAL_INACTIVATION) | 60.0°C | Below pasteurization — less kill |
| pH | 7.0 | Neutral — optimal for growth, no acid protection |
| water_activity | 0.99 | High — maximizes growth |
| duration_minutes (single-step only) | 10080.0 min | Long window — trajectory reaches physical cap |

`organism` is not defaulted — it fails closed. If unresolved after grounding, it populates `missing_required` (see §3.3).

### 9.3 Range-Bound Selection Direction

| Model type | Direction | Reason |
|---|---|---|
| GROWTH | upper bound | More pathogen growth = worse outcome |
| NON_THERMAL_SURVIVAL | upper bound | More pathogen survival = worse outcome |
| THERMAL_INACTIVATION | lower bound | Less pathogen kill = worse outcome |

---

## 10. Interpretation Rules

**Location:** `app/config/rules.py`

### 10.1 Temperature Rules (`TEMPERATURE_INTERPRETATIONS`)

Substring matching, longest pattern first. Each rule has `pattern`, `value` (°C), `conservative` (bool), `notes`.

Key rules:
- `"room temperature"`, `"counter"`, `"ambient"`, `"left out"`, `"sitting out"`, `"bench"`, `"table"`, `"unrefrigerated"`, `"out of the fridge"`, `"in my bag"` → 25°C (conservative=True)
- `"warm"`, `"summer"`, `"in the car"`, `"in my car"` → 30°C (conservative=True)
- `"hot"` → 40°C (conservative=True)
- `"refrigerated"`, `"refrigerator"`, `"fridge"`, `"chilled"` → 4°C (conservative=False)
- `"cold"` → 10°C (conservative=True)
- `"cool"` → 15°C (conservative=True)
- `"freezer"`, `"frozen"` → -18°C (conservative=False)

### 10.2 Duration Rules (`DURATION_INTERPRETATIONS`)

Key rules:
- `"briefly"`, `"quick"` → 10 min
- `"a few minutes"` → 15 min (conservative=True)
- `"a moment"` → 5 min
- `"a while"`, `"some time"` → 60 min (conservative=True)
- `"a bit"` → 30 min (conservative=True)
- `"an hour"` → 60 min
- `"a couple hours"`, `"a couple of hours"` → 120 min
- `"a few hours"` → 180 min (conservative=True)
- `"several hours"` → 300 min (conservative=True)
- `"many hours"`, `"half a day"`, `"half the day"`, `"a long time"`, `"ages"` → 360 min
- `"overnight"`, `"all night"` → 480 min (conservative=True)
- `"all day"`, `"the whole day"` → 720 min (conservative=True)
- `"forever"` → 480 min (conservative=True)

**Note:** `ptm_context.md §5.2` states `"all day" → 600 min`. The code (`app/config/rules.py:316`) defines `"all day" → 720 min`. The code takes precedence.

### 10.3 Embedding Fallback (Temperature Only)

`TEMPERATURE_CANONICAL_PHRASES` (`app/config/rules.py:399`) defines canonical phrases per temperature category: 25°C, 30°C, 35°C, 4°C, -18°C. Duration has no embedding fallback.

`find_temperature_by_similarity()` encodes the description with `all-MiniLM-L6-v2` (lazy-loaded, cached with `@lru_cache(maxsize=1)`), computes cosine similarity against all canonical phrase embeddings, returns the best match if above `EMBEDDING_SIMILARITY_THRESHOLD = 0.50`.

When an embedding match fires, `ValueProvenance.extraction_method = "embedding_fallback"`, `embedding_similarity` carries the similarity score, `canonical_phrase` carries the best-matching canonical phrase.

---

## 11. API Contract

### 11.1 Endpoint

`POST /api/v1/translate` — translates a food safety query.

**Request body (`TranslationRequest`):**
```json
{
  "query": "string (1-2000 chars, required)",
  "model_type": "growth | thermal_inactivation | non_thermal_survival | null"
}
```

**Query parameter:** `verbose: bool = false` — when `true`, includes the full `audit` block in the response.

**Response (`TranslationResponse`):**

| Field | Always present | Description |
|---|---|---|
| `success` | Yes | Whether translation succeeded |
| `session_id` | Yes | UUID for the session |
| `status` | Yes | SessionStatus enum value |
| `created_at`, `completed_at` | Yes | UTC datetimes |
| `original_query` | Yes | The query string verbatim |
| `prediction` | When success=True | `PredictionResult` (see below) |
| `provenance` | Yes | List of `ProvenanceInfo` (legacy, derived from field_audit) |
| `warnings` | Yes | List of `WarningInfo` (type, message, field?) |
| `error` | When success=False | Error message string |
| `audit` | When verbose=True | `AuditDetail` (see below) |

**`PredictionResult` fields:**

| Field | Type | Notes |
|---|---|---|
| `organism` | `str` | Enum name (e.g., "SALMONELLA") |
| `model_type` | `str` | Enum value (e.g., "growth") |
| `engine` | `str` | "combase_local" |
| `temperature_celsius` | `float` | First-step temperature (back-compat scalar) |
| `duration_minutes` | `float` | Total across all steps |
| `ph` | `float` | pH used |
| `water_activity` | `float` | aw used |
| `mu_max` | `float` | First-step μ_max (negative for inactivation) |
| `doubling_time_hours` | `float \| None` | First-step value; null for inactivation |
| `total_log_increase` | `float` | Sum across all steps (negative = log reduction) |
| `initial_log_cfu` | `float` | Initial bacterial count (log₁₀ CFU/g) — user-supplied or model default |
| `final_log_cfu` | `float` | Final bacterial count (log₁₀ CFU/g) = `initial_log_cfu + total_log_increase` |
| `is_multi_step` | `bool` | Whether scenario had multiple steps |
| `steps` | `list[StepInput]` | Always populated (length 1 for single-step) |
| `step_predictions` | `list[StepPrediction]` | Always populated (length 1 for single-step) |
| `growth_description` | `str` | Human-readable description of predicted change |

`growth_description` thresholds (from `_format_growth_description()`):
- log_increase < 0 and ≥ -1: "Minor reduction"
- < 0 and ≥ -3: "Moderate reduction"
- < 0 and ≥ -6: "Major reduction: >99.9% killed"
- < 0 and < -6: "Significant reduction: >99.9999% killed"
- 0–0.3: "Minimal growth: <2x population"
- 0.3–1.0: "Moderate growth: ~Nx population"
- 1.0–3.0: "Significant growth: ~Nx population"
- ≥ 3.0: "Extensive growth: >1000x population"

**`AuditDetail` (`verbose=true` only):**

| Field | Description |
|---|---|
| `field_audit` | `dict[str, FieldAuditEntry]` — canonical per-field post-standardization map |
| `combase_model` | `ComBaseModelAuditInfo` — organism, model_type, model_id, coefficients_str, valid_ranges, selection_reason |
| `audit` | `AuditSummary` with `range_clamps`, `defaults_imputed`, `warnings` (all structured, emit `[]` when empty) |
| `system` | `SystemAuditInfo` — rag_store_hash, rag_ingested_at, source_csv_audit_date, ptm_version, combase_model_table_hash |

### 11.2 Error Responses

On orchestrator exception: returns `TranslationResponse(success=False, error=str(e))`.

On missing required values: `success=False, error="Missing required values: organism"` (ungrounded), or `success=False, error="Missing required values: organism (Shigella flexneri is not supported for growth predictions)"` (grounded but not executable for the resolved model type/factor4 — Phase A0.5b; see §3.3).

On intent classification failure: `success=False, error="Query is out of scope..."` or `"Information queries not yet implemented"`.

### 11.3 Other Endpoints

`GET /health` — health check (from `app/api/routes/health.py`). ComBase engine and vector store availability reported.

### 11.4 Startup

FastAPI lifespan handler (`app/main.py`):
1. Loads `data/combase_models.csv` into `ComBaseEngine`
2. Initializes `VectorStore` (logs doc count; warns if 0)

---

## 12. Testing Strategy

**Unit tests:** `tests/unit/` — pytest, `asyncio_mode = "auto"` (set in `pyproject.toml`). Test fixtures in `tests/conftest.py` provide `client`, `async_client` (httpx.AsyncClient).

**Integration tests:** `tests/integration/` — use `mock_semantic_parser` (AsyncMock) to avoid live LLM calls. Real ComBase engine, real ChromaDB (in-memory temp dir), real standardization. Tests are parametrized across pathogen types where applicable. `data/combase_models.csv` must exist; tests skip if not available.

**Manual scripts:** `scripts/` — call live LLM APIs, require `.env` keys. Not in pytest. On Windows, must add `sys.stdout.reconfigure(encoding="utf-8")` for Unicode output.

**Benchmark suite:** `benchmarks/experiments/` — uses MLflow for tracking. Results in `benchmarks/results/`. Streamlit dashboard at `benchmarks/visualizations/app.py`.

**`benchmarks/config.py`** defines two constants consumed by benchmark scripts and the dashboard:
- `MODELS` — LLM candidates for Exp 3.1 (model comparison).
- `EMBEDDERS` — sentence-transformer candidates for Exp 2.1 (embedder comparison). Each entry has: `id`, `name`, `hf_model`, `dim`, `params_m`, `is_baseline`, `training_objective`, `input_prefix_query`, `input_prefix_passage`. Four embedders in a 2×2 design (size: 384-dim / 768-dim × objective: general / retrieval-optimised). Baseline is `all-MiniLM-L6-v2` (22M, 384-dim, general).

**Experiment 2.1 — Embedder Comparison** (`benchmarks/experiments/exp_2_1_embedder_comparison.py`):
- Ground-truth corpus: `benchmarks/datasets/retrieval_queries.json` — 30 queries stratified as easy (10), medium (10), hard (6 negative controls), pathogen (4).
- Each corpus entry has: `id`, `food_description`, `field`, `production_tier`, `tier`, `acceptable_food_names` (empty list for hard-tier negative controls).
- **Negative control polarity**: for hard-tier entries, `correct_at_1 = True` means NO document cleared the confidence threshold.
- **Query reformulation** mirrors `app/rag/retrieval.py` verbatim: `ph_aw_combined` → `"{food} pH water activity properties"`, `ph` → `"{food} pH acidity"`, `water_activity` → `"{food} water activity aw moisture"`, `pathogen` → `"{food} food hazard"`.
- **Thresholds** are read from `app.config.settings` (never hard-coded): `tier_1` → `settings.food_properties_confidence`, `tier_2` → `settings.food_properties_fallback_confidence`, `pathogen_stage_1` → `settings.pathogen_hazards_confidence`.
- **Isolation**: each embedder gets its own ChromaDB PersistentClient at `benchmarks/results/exp_2_1_embedder_comparison/_chroma/<embedder_id>/`. The production store at `data/vector_store/` is never touched.
- Results saved to `benchmarks/results/exp_2_1_embedder_comparison/latest.json` (full dict) and `latest.csv` (one row per embedder). JSON root is a dict with `experiment_id`, `timestamp`, `corpus`, `embedders` — NOT a top-level list. The Streamlit page (`pages/5_embedder_comparison.py`) uses its own `_load_latest()` loader rather than the shared `data_loader.load_latest_results()` (which expects a list).

---

## 13. Configuration

### 13.1 Environment Variables (`.env` file)

Loaded by `pydantic_settings.BaseSettings` from `.env` at project root.

| Variable | Default | Description |
|---|---|---|
| `LLM_MODEL` | `gpt-4o` | LiteLLM model identifier |
| `LLM_API_KEY` | None | API key for LLM provider |
| `LLM_API_BASE` | None | Base URL override |
| `LLM_TEMPERATURE` | `0.1` | LLM sampling temperature |
| `LLM_MAX_TOKENS` | `4096` | Max tokens per response |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | sentence-transformers model |
| `VECTOR_STORE_PATH` | `./data/vector_store` | ChromaDB persistence path |
| `CHUNK_SIZE` | `512` | Document chunk size |
| `CHUNK_OVERLAP` | `50` | Chunk overlap |
| `GLOBAL_MIN_CONFIDENCE` | `0.65` | Global retrieval threshold |
| `FOOD_PROPERTIES_CONFIDENCE` | `0.70` | Food properties retrieval threshold |
| `PATHOGEN_HAZARDS_CONFIDENCE` | `0.75` | Pathogen hazards retrieval threshold |
| `DEFAULT_TEMPERATURE_ABUSE_C` | `25.0` | Conservative growth temperature default |
| `DEFAULT_TEMPERATURE_INACTIVATION_CONSERVATIVE_C` | `60.0` | Conservative inactivation temperature default |
| `DEFAULT_PH_NEUTRAL` | `7.0` | Conservative pH default |
| `DEFAULT_WATER_ACTIVITY` | `0.99` | Conservative aw default |
| `DEBUG` | `false` | Enable debug mode |
| `HOST` | `0.0.0.0` | Server host |
| `PORT` | `8000` | Server port |

### 13.2 LLM Provider

LiteLLM + Instructor. Model specified via `LLM_MODEL`. Supported providers include OpenAI (gpt-4o, gpt-4-turbo, gpt-3.5-turbo), Anthropic (claude-3-sonnet, claude-3-haiku), and Ollama (local models). `LLM_TEMPERATURE` defaults to 0.1.

### 13.3 Key File Dependencies

| File | Required at | Consequence if absent |
|---|---|---|
| `data/combase_models.csv` | Startup | Engine unavailable (`is_available=False`); all predictions fail |
| `data/vector_store/` (ChromaDB) | Startup | Vector store empty; RAG queries return no confident results; defaults applied everywhere |
| `data/vector_store/ingest_manifest.json` | Per-request | `system.rag_store_hash` etc. are null; warning appended |
| `data/sources/source_references.csv` | Ingestion | Citations missing from RAG metadata |

---

## 14. Glossary

| Term | Definition |
|---|---|
| `aw` | Water activity — measure of free water available for microbial growth (0–1 scale) |
| `bw` | Water activity term in the ComBase polynomial: `sqrt(1-aw)` for growth/non-thermal, `aw` for thermal inactivation |
| `ComBaseExecutionPayload` | The standardized, engine-ready payload produced by StandardizationService |
| `ComBaseModelRegistry` | In-memory registry of all ComBase models loaded from CSV, keyed by `{model_id}_{organism_id}_{factor4_type}` |
| `conservative_default` | A value substituted when the user's input is absent, chosen to predict the worst-case food safety outcome |
| `LONG_WINDOW_DEFAULT` | `ValueSource` variant emitted when a single-step query provides no duration. The 7-day (10080 min) window ensures the prediction trajectory reaches the physical growth cap (±15 log CFU) under all model types. Epistemically distinct from `CONSERVATIVE_DEFAULT`: duration is a scenario dimension (how long to simulate), not an environmental property with a scientifically-defensible worst-case value. |
| `ExtractedScenario` | Pydantic model produced by SemanticParser from the user's query |
| `Factor4Type` | Optional fourth environmental factor: NONE, CO2, NITRITE, LACTIC_ACID, ACETIC_ACID |
| `field_audit` | Canonical post-standardization per-field map in the verbose API response |
| `GroundedValues` | Container produced by GroundingService with resolved numeric values and per-field ValueProvenance |
| `h0` | Initial physiological state parameter from Baranyi model — present in CSV data but not used in the current calculator |
| `InterpretationMetadata` | Session-level audit container accumulating provenance, defaults, clamps, warnings, and context blocks |
| `μ_max` | Maximum specific growth rate (1/h); negative for inactivation models |
| `OrganismGroundingFailure` | Structured record on `GroundedValues.organism_failure` of where organism grounding failed closed: `stage` (`OrganismGroundingFailureStage`), `detail`, and — for `CATEGORY_HAS_NO_HAZARD_DATA` only — `resolved_category`/`match_score`. The organism equivalent of `bridge_attempts`/`CategoryBridgeInfo`. `None` on success. Purely additive to the existing `mark_ungrounded()` warning string. |
| `OrganismGroundingFailureStage` | Enum naming which of the six early-return points in `_category_pathogen_fallback()` fired: `BRIDGE_DISABLED`, `FOOD_UNRECOGNISED`, `CATEGORY_HAS_NO_HAZARD_DATA`, `INTERNAL_NO_MAPPABLE_CANDIDATE` (merges three branches unreachable with current CSVs — empty candidate union, all candidates absent from characteristics, all ranked candidates unmappable — distinguished only by `detail`) |
| `range_pending` | Pipeline signal on `ValueProvenance`: True when the stored value is the range lower bound and bound selection has not yet occurred; always False in serialized output |
| `RangeBoundSelection` | Structured record of a range-bound selection event (direction, before_value, after_value, reason) |
| `RangeClamp` | Structured record of a range clamping event (original_value, clamped_value, valid_min, valid_max) |
| `StandardizationResult` | Output of StandardizationService: payload + lists of DefaultImputed, RangeClamp, warnings, missing_required |
| `TCS` | Time/Temperature Control for Safety — regulatory food classification |
| `TranslationResult` | Top-level return from the orchestrator (.state, .success, .error, .execution_result, .metadata) |
| `ValueProvenance` | Per-field metadata tracking source, extraction method, range bounds, and standardization events |
| `ValueSource` | Categorical reliability tier: USER_EXPLICIT, USER_INFERRED, RAG_RETRIEVAL (primary food-properties query), RAG_RETRIEVAL_FALLBACK (per-field Tier 2 fallback query), RAG_RETRIEVAL_CATEGORY_BRIDGE (Tier 3 FoodEx2 bridge), RAG_PATHOGEN_CATEGORY_FALLBACK (organism inferred from food category via IFT-2003-T1, ranked by CDC annual deaths), CONSERVATIVE_DEFAULT, COMPOSITE_FOOD_DEFAULT (retrieval deliberately skipped — food identified as composite dish), LONG_WINDOW_DEFAULT (single-step duration unspecified; 7-day window assumed), FUZZY_MATCH, CALCULATED, CLAMPED_TO_RANGE, CLARIFICATION_RESPONSE, MISSING (field required but neither user nor grounding supplied a value; surfaces in `field_audit` with `final_value=null` on validation failure) |

---

## 15. Appendix: File-to-Responsibility Map

| File | Responsibility |
|---|---|
| `app/main.py` | FastAPI app factory, lifespan startup (load models, init vector store) |
| `app/config/settings.py` | `Settings` (pydantic_settings), all env-var defaults |
| `app/config/rules.py` | Temperature + duration interpretation rule tables, embedding fallback |
| `app/models/enums.py` | `ModelType`, `ComBaseOrganism` (with alias dict), `Factor4Type`, `SessionStatus`, etc. |
| `app/models/extraction.py` | `ExtractedScenario`, `ExtractedTemperature`, `ExtractedDuration`, `ExtractedIntent`, etc. |
| `app/models/metadata.py` | `ValueProvenance`, `RangeBoundSelection`, `DefaultImputed`, `RangeClamp`, `RetrievalResult`, `InterpretationMetadata`, `ComBaseModelAudit`, `SystemAudit` |
| `app/models/execution/base.py` | `TimeTemperatureStep`, `TimeTemperatureProfile`, `GrowthPrediction`, base execution classes |
| `app/models/execution/combase.py` | `ComBaseParameters`, `ComBaseModelSelection`, `ComBaseExecutionPayload`, `ComBaseExecutionResult` |
| `app/services/extraction/semantic_parser.py` | `SemanticParser` — LLM + Instructor extraction |
| `app/services/grounding/grounding_service.py` | `GroundingService`, `GroundedValues`, `GroundedStep` |
| `app/services/standardization/standardization_service.py` | `StandardizationService`, `StandardizationResult` |
| `app/services/audit/system.py` | `build_system_audit()` — reads manifest, git sha, CSV hash |
| `app/services/audit/citations.py` | `get_full_citations()` — source ID → bibliographic citation |
| `app/core/orchestrator.py` | `Orchestrator` — pipeline coordinator |
| `app/core/state.py` | `SessionState`, `SessionManager` |
| `app/engines/combase/engine.py` | `ComBaseEngine` — loads models, orchestrates execution |
| `app/engines/combase/calculator.py` | `ComBaseCalculator` — polynomial evaluation, bw, μ_max, log increase |
| `app/engines/combase/models.py` | `ComBaseModel`, `ComBaseModelConstraints`, `ComBaseModelRegistry` |
| `app/rag/vector_store.py` | `VectorStore` — ChromaDB wrapper |
| `app/rag/ingestion.py` | `IngestionPipeline` — document loading, manifest writing |
| `app/rag/retrieval.py` | `RetrievalService` — confidence scoring, threshold gating, optional reranking |
| `app/rag/embeddings.py` | Embedding model wrappers |
| `app/rag/reranker.py` | `BaseReranker`, `NoOpReranker` — reranking interface |
| `app/rag/data_sources/food_safety.py` | Seven loader functions (food_properties, pathogen types, TCS), multi-source citation parsing |
| `app/rag/data_sources/citations.py` | `load_source_references()`, `format_citation()`, `expand_citation_tags()` |
| `app/api/routes/translation.py` | `POST /translate` handler, `_build_field_audit()`, `_build_provenance_list()`, `_build_audit_detail()` |
| `app/api/schemas/translation.py` | `TranslationRequest`, `TranslationResponse`, `PredictionResult`, `AuditDetail`, `FieldAuditEntry`, etc. |
| `data/combase_models.csv` | ComBase polynomial model registry (15 organisms, semicolon-delimited) |
| `data/rag/*.csv` | Authoritative food safety knowledge base (FDA, IFT, CDC sources) |
| `data/sources/source_references.csv` | Source ID registry for citation lookup |
| `data/vector_store/ingest_manifest.json` | RAG store provenance manifest (written at ingestion, read per request) |
