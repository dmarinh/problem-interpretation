# Specification: Category-Level Pathogen Fallback for Organism Grounding

**Project:** PTM (Problem Translation Module)
**Phase:** [to be assigned — likely Phase 9.7 or 10.x]
**Date:** 2026-05-14
**Status:** Specification, ready for implementation planning

---

## 1. Background and rationale

Phase 9.5 (May 2026) made `organism` a required field with no default. The Salmonella default that fired silently when a specific food was not in `food_pathogen_hazards.csv` was producing wrong predictions for many queries (e.g. cooked breaded products got Salmonella when Listeria recontamination was the real concern; chicken soup got Salmonella when *C. perfringens* was scenario-relevant). Removing the default made the audit honest but introduced a practical problem: many realistic queries now return `success=False` with `error="Missing required values: organism"` because `food_pathogen_hazards.csv` only covers ~20 named foods, mostly raw/RTE.

This specification adds a **category-level fallback for organism grounding that uses data already loaded in the RAG**. It is not a return to silent defaulting; the fallback is itself a documented, cited, ranked retrieval whose every step appears in the audit.

The test journal's Q12 entry explicitly filed this architectural question as a `🟡` followup ("should §2.4 fall through to `pathogen_food_associations.csv` when `food_pathogen_hazards` has no matches? ... Defer past MVP"). This phase closes that followup.

---

## 2. Approach summary

When the existing two-stage food-specific pathogen retrieval (`_ground_pathogen_from_rag` Stages 1 and 2) returns no confident result, fall back to:

1. Resolve the food description to a `ptm_category` via the existing FoodEx2 taxonomy bridge.
2. Map the `ptm_category` to one or more IFT-2003-T1 categories via a new explicit alignment file.
3. Gather the union of pathogens listed for those IFT categories from `pathogen_food_associations.csv`.
4. Rank that pathogen set by `annual_deaths_us` from `pathogen_characteristics.csv`.
5. Select the top-ranked pathogen that also maps to a `ComBaseOrganism`, with full provenance.

No new ingestion. No new authoritative source. The data is already on disk.

---

## 3. Inputs (verify before designing)

All files already present under `data/rag/` and `data/sources/`:

- `pathogen_food_associations.csv` — 46 rows over 9 IFT-2003-T1 categories. Schema: `food_category, pathogen, control_methods, notes, source_id`. All rows sourced to `IFT-2003-T1`.
- `pathogen_characteristics.csv` — 30 pathogens with `annual_deaths_us`. Mix of CDC-2019-T1T2 (8 pathogens, merged 2026-04-29) and CDC-2011-T3 (22 pathogens).
- `food_taxonomy.csv` — 2,917 FoodEx2 MTX entries with `ptm_category` and `state`.
- `category_level_rows.csv` — curated category lookup for pH/aw via the FoodEx2 bridge (referenced for design parallel; not directly used by this fallback).
- `app/services/grounding/taxonomy_bridge.py` — the FoodEx2 bridge that resolves food → `ptm_category` with calibrated threshold 80.
- `app/services/grounding/grounding_service.py` — contains `_ground_pathogen_from_rag` and the composite-food guard.

**The first step of implementation is to verify these contents and locations match this spec.**

---

## 4. New artifact: PTM-to-IFT category alignment

Add `data/rag/ift_category_alignment.csv` with schema:

```
ptm_category, ift_category, notes
```

Proposed initial content (verify against actual `ptm_category` enumeration in `food_taxonomy.csv` and `food_category` enumeration in `pathogen_food_associations.csv`):

| ptm_category | ift_category | Notes |
|---|---|---|
| meat | meats and poultry | IFT does not split meat from poultry |
| poultry | meats and poultry | Same IFT row |
| fish | fish and seafood | IFT does not split fish from shellfish |
| shellfish | fish and seafood | Same IFT row |
| eggs | eggs and egg products | Direct |
| dairy | milk and milk products | Primary dairy class |
| dairy | cheese and cheese products | Additional dairy class — distinct pathogen profile |
| dairy | butter and margarine | Additional dairy class |
| fruit | fruits and vegetables | IFT combines produce |
| vegetable | fruits and vegetables | IFT combines produce |
| grain | cereal grains | Direct |
| sweetener | sugars and syrups | Direct |
| condiment | — | No IFT match; fallback returns ungrounded |
| beverage | — | No IFT match |
| protein | — | No IFT match |
| dessert | — | No IFT match |

For `ptm_category` values mapping to multiple IFT categories (e.g., `dairy`), the candidate pathogen set is the **union** of pathogens listed across all mapped IFT categories. Ranking happens once over the union.

The alignment file is mechanically loaded at startup. It is *not* ingested into ChromaDB.

---

## 5. Algorithm (functional specification)

Given an `ExtractedScenario` where `pathogen_mentioned` is `None` and the existing pipeline has reached `_ground_pathogen_from_rag` without confidently grounding an organism:

1. **Run existing Stages 1 and 2 unchanged.** If a confident food-specific pathogen is returned, use it; the fallback does not fire.
2. **Resolve food → `ptm_category`** via the FoodEx2 taxonomy bridge. If the bridge fails to resolve a category at its calibrated threshold (currently 80), return ungrounded (no fallback fires).
3. **Map `ptm_category` → IFT category list** via `ift_category_alignment.csv`. If no mapping exists, return ungrounded.
4. **Gather candidate pathogens** as the union, across all mapped IFT categories, of pathogens listed in `pathogen_food_associations.csv`. Deduplicate by normalized pathogen name.
5. **Normalize pathogen names** to match `pathogen_characteristics.csv` names. See §6.
6. **Rank candidates** by `annual_deaths_us` in `pathogen_characteristics.csv`, descending. Pathogens with **no entry** in `pathogen_characteristics.csv` are excluded from ranking entirely (absence of evidence is not zero deaths).
7. **Map top candidate to `ComBaseOrganism` enum** via `ComBaseOrganism.from_text()` (per lessons.md 2026-04-29 — `from_string()` is wrong for RAG content). If the top pathogen does not map to any supported organism, descend to the next-ranked candidate until one maps or the list is exhausted. If exhausted, return ungrounded.
8. **Record provenance** per §8.

The fallback **fails closed**: every step has a defined exit to "ungrounded" so the existing `success=False, error="Missing required values: organism"` path still fires when the fallback cannot resolve.

---

## 6. Pathogen name normalization

`pathogen_food_associations.csv` and `pathogen_characteristics.csv` use slightly different conventions. The mapping below is the **starting point — verify against actual CSV content** before locking in:

| In associations CSV | In characteristics CSV | Notes |
|---|---|---|
| Salmonella spp. | Salmonella nontyphoidal | Associations uses genus; characteristics uses serogroup label |
| Campylobacter jejuni | Campylobacter spp. | Associations uses species; characteristics uses genus aggregate |
| Escherichia coli O157:H7 | STEC O157 | Different naming conventions for the same organism |
| Vibrio cholerae | Vibrio cholerae toxigenic | Characteristics is more specific |
| Clostridium botulinum | Clostridium botulinum | Direct match |
| Clostridium perfringens | Clostridium perfringens | Direct match |
| Listeria monocytogenes | Listeria monocytogenes | Direct match |
| Yersinia enterocolitica | Yersinia enterocolitica | Direct match |
| Staphylococcus aureus | Staphylococcus aureus | Direct match |
| Bacillus cereus | Bacillus cereus | Direct match |
| Shigella spp. | Shigella spp. | Direct match |
| Vibrio vulnificus | Vibrio vulnificus | Direct match |
| Vibrio parahaemolyticus | Vibrio parahaemolyticus | Direct match |

This normalization belongs in code (a constant in the grounding service module) — it is a fixed mapping that changes only when source pathogen taxonomies change, and putting it in a CSV would create a third pathogen-name authority.

---

## 7. Pipeline placement

The fallback fires inside `_ground_pathogen_from_rag` after the existing Stages 1 and 2 conclude without a confident grounding.

The current behavior of **falling back to Stage 1's top embedding result** when Stage 2 returns no hazard documents is **replaced** by the new fallback. That existing fallback is exactly the silent-wrong-organism pattern this work is removing — a Stage 1 embedding match against an irrelevant document was producing values that *looked* grounded but were not.

If the new fallback also fails, the function returns no grounding (current ungrounded behavior preserved); the orchestrator receives a missing-organism signal and the request fails with the existing `missing_required` path.

---

## 8. Provenance and audit shape

### 8.1 New `ValueSource` enum variant

**Recommended name:** `RAG_PATHOGEN_CATEGORY_FALLBACK`.

Rationale: it sits in the same epistemic position as `RAG_RETRIEVAL_CATEGORY_BRIDGE` (used by the FoodEx2 bridge for pH/aw) but uses a different file (`pathogen_food_associations.csv` rather than `category_level_rows.csv`) and a different mechanism (ranking by deaths rather than direct curated lookup). Distinct variants prevent the per-tier semantic muddiness flagged in lessons.md 2026-04-30 ("naturally resolves" warning).

Alternative considered: extending `RAG_RETRIEVAL_CATEGORY_BRIDGE` to cover both pH/aw and pathogen. Rejected because the two mechanisms differ in their data sources, ranking logic, and audit needs; conflating them would force the audit consumer to inspect the value to know which mechanism fired.

### 8.2 `ValueProvenance` fields

For an organism grounded via the new fallback:

- `source = RAG_PATHOGEN_CATEGORY_FALLBACK`
- `extraction_method = "category_fallback_ranked_by_annual_deaths"`
- `retrieval`: populated with the `RetrievalResult` of the FoodEx2 bridge call (the food → category resolution). `attributed_field = "organism"` (per lessons.md 2026-04-30 — tag attribution at creation time; do not rely on query-string keyword heuristics).
- `category_bridge`: populated with the `CategoryBridgeInfo` returned by the bridge. This field is shared with the pH/aw bridge path; the downstream lookup differs.
- **New nested block** on `ValueProvenance`, proposed name `pathogen_category_fallback`:
  - `ptm_category` — the resolved PTM category
  - `ift_categories: list[str]` — the IFT categories the PTM category mapped to
  - `candidate_pathogens: list[{pathogen, normalized_name, annual_deaths_us, source_id}]` — the union, ranked
  - `selected_pathogen` — the chosen candidate after enum mapping
  - `skipped_pathogens: list[{pathogen, reason}]` — any pathogens that ranked higher but did not map to a `ComBaseOrganism`

### 8.3 Warning

Emit a top-level `metadata.warnings` entry naming the resolved category and the selected pathogen. Suggested format:

> "Organism *Listeria monocytogenes* inferred from food category 'dairy' (IFT-2003-T1) — no specific hazard data for 'mascarpone'. Pathogen ranked by CDC annual deaths."

This is informational, not safety-critical in the clamp/default sense — it does not trigger the same red banner as `range_clamp`. It is a transparency signal that a category-level inference occurred.

### 8.4 Citations

The selected pathogen's citation chain is two-source: `IFT-2003-T1` for the qualitative pathogen-category association, and the relevant CDC source (`CDC-2019-T1T2` or `CDC-2011-T3`) for the ranking. Both source IDs must appear in `top_match.source_ids` and `full_citations` for the organism field's retrieval block in `field_audit`.

---

## 9. Standardization-service implications

None expected. Organism resolution happens entirely in grounding. Standardization continues to treat organism as required and surfaces `missing_required = ["organism"]` only when grounding (now including the new fallback) returns no organism.

**Verify** that the `field_audit["organism"]` entry continues to render correctly when source is the new `RAG_PATHOGEN_CATEGORY_FALLBACK` variant. The translation route's audit-routing logic (`_build_field_audit` in `app/api/routes/translation.py`) reads `attributed_field` to bind the retrieval block to the organism field — this must continue to work with the new tier (lessons.md 2026-05-01 on query-string changes silently breaking keyword-heuristic routing).

---

## 10. Edge cases and how each is tested

### 10.1 Exercisable via integration tests against the live RAG

These cases are reachable by sending natural-language queries through the live `/api/v1/translate` endpoint. They form the integration-test backbone (§12 T/N/U queries).

| Case | Test ID | Mechanism exercised |
|---|---|---|
| Bridge resolves; single IFT mapping; candidates rank cleanly | T1 | Happy path — single category |
| Bridge resolves; multi-IFT union; ranking over union | T2 | Multi-IFT union (dairy) |
| Bridge resolves; single-pathogen IFT category | T3 | Degenerate ranking — one candidate |
| Bridge fails on unknown food | N1 | Fail-closed at bridge step |
| Bridge resolves to PTM category with no IFT mapping | N2 | Fail-closed at alignment step |
| Stages 1+2 succeed (specific-food hazard exists) | U1 | Fallback does not fire |
| User explicitly supplies pathogen | U2 | USER_EXPLICIT wins |
| Composite-food guard interacts with pathogen path | U3 | Verifies composite handling does not perturb pathogen resolution |

### 10.2 Requires unit tests with mocked CSV content

These cases are real code paths but unreachable through any natural query against the current data (every top-by-deaths pathogen per category maps to a `ComBaseOrganism`; every pathogen in `pathogen_food_associations.csv` has a row in `pathogen_characteristics.csv`). They must be exercised with synthetic CSV content in unit tests.

| Case | Test approach |
|---|---|
| Top-ranked pathogen does not map to `ComBaseOrganism` | Mock associations CSV row with `Campylobacter jejuni` only (or similar unmapped); verify descend behavior; verify `skipped_pathogens` populated with reason |
| All candidates fail enum mapping | Mock associations row with no enum-mappable pathogens; verify ungrounded return |
| Pathogen present in associations but absent from characteristics | Mock associations row with a pathogen name absent from characteristics; verify it is excluded from ranking, not ranked as 0 |
| Pathogen name normalization | Unit-test each row of §6 normalization table directly |

---

## 11. Out of scope for this phase

- Painter et al. 2013 ingestion (alternative empirical source — future enhancement if IFT × CDC composition proves inadequate).
- IFSAC 2023 ingestion (same).
- Refining the FoodEx2 bridge or extending its category coverage.
- Splitting IFT `meats and poultry` or `fish and seafood` into finer subcategories.
- Adding category-level food-specific defaults for pH/aw beyond the existing five rows in `category_level_rows.csv` (separate concern).
- Pathogen-level CFR or severity weighting in the ranking — `annual_deaths_us` is the single ranking signal, consistent with the existing `food_pathogen_hazards.csv` Stage 2.
- New journal entry. Q12's followup gets updated; no Q18 in this phase.

---

## 12. Acceptance criteria

### 12.1 Integration tests — T/N/U query set

All queries use explicit T and duration to neutralise the missing-duration architectural boundary and isolate the organism resolution path.

**T-class (Trigger the fallback successfully):**

| ID | Query | Expected behavior |
|---|---|---|
| T1 | "barley at 25 °C for 4 hours" | Bridge → `grain` → `cereal grains`. Candidates: Salmonella (238), *C. botulinum* (9), *S. aureus* (6), *B. cereus* (0 — excluded). Selected: **Salmonella**. `source=RAG_PATHOGEN_CATEGORY_FALLBACK`. Warning emitted. Citations: `IFT-2003-T1` + the CDC source for Salmonella nontyphoidal. |
| T2 | "mascarpone at 25 °C for 4 hours" | Bridge → `dairy` → union over {milk and milk products, cheese and cheese products, butter and margarine}. Selected: **Salmonella** (238) over Listeria (172). Verifies union mechanic. Warning names `dairy`. |
| T3 | "maple syrup at 25 °C for 4 hours" | Bridge → `sweetener` → `sugars and syrups` → only *C. botulinum* listed. Selected: ***C. botulinum***. Verifies degenerate ranking (single candidate). |

**N-class (fallback returns ungrounded; request fails):**

| ID | Query | Expected behavior |
|---|---|---|
| N1 | "frobnitz at 25 °C for 4 hours" | Bridge returns no category. Fallback exits at step 2. `success=False, missing_required=["organism"]`. |
| N2 | "mustard at 25 °C for 4 hours" | Bridge → `condiment`. No row in `ift_category_alignment.csv`. Fallback exits at step 3. `success=False, missing_required=["organism"]`. |

**U-class (fallback does not fire — regression of existing behavior):**

| ID | Query | Expected behavior |
|---|---|---|
| U1 | "raw chicken at 25 °C for 4 hours" | Stages 1+2 succeed; pick Salmonella from `food_pathogen_hazards.csv`. Source remains the existing Stage-2 source (not the new variant). New code path not exercised. |
| U2 | "Salmonella on bread at 25 °C for 4 hours" | USER_EXPLICIT wins. Fallback does not fire. |
| U3 | "chicken soup at 25 °C for 4 hours" | Composite-food guard fires for pH/aw (existing `COMPOSITE_FOOD_DEFAULT` behavior). Verifies the new fallback does not interfere with composite handling on adjacent fields. Pathogen path behavior to be **observed and documented** in the implementation plan (likely: Stage 1 matches `chicken raw` via embedding similarity, so the fallback does not fire; confirm). |

### 12.2 Unit tests — unreachable edge cases

Per §10.2, four cases must be exercised with synthetic CSV content in unit tests:
1. Top candidate fails enum mapping → descend
2. All candidates fail enum mapping → ungrounded
3. Pathogen in associations absent from characteristics → excluded from ranking
4. Pathogen name normalization table — direct unit tests per row

### 12.3 Audit assertions (apply to T-class)

5. `field_audit["organism"]` carries `source = "rag_pathogen_category_fallback"`, with `retrieval` populated with the FoodEx2 bridge call details, `category_bridge` populated with the resolved category, and the new `pathogen_category_fallback` block populated with the candidate list and ranking.
6. `top_match.source_ids` contains both `IFT-2003-T1` and the CDC source ID for the selected pathogen.
7. `metadata.warnings` contains an entry naming the resolved category and the selected pathogen.

### 12.4 Adjacent-dimension light regression (test journal)

The journal is a representative-behavior capture, not a regression suite, so it is used here only to confirm this change does not perturb adjacent audit dimensions. Re-run 2–3 journal queries chosen for the adjacent dimensions they exercise:

- **Q03** (Bread + *B. cereus* 25 °C / 4 h) — multi-source citation, range_bound_selection on a RAG-retrieved range. Pathogen is USER_EXPLICIT so the new fallback does not fire. Assert audit shape unchanged for the non-organism fields.
- **Q10** (Listeria on cheese at 4 °C / 14 days) — refrigerated storage, USER_EXPLICIT pathogen. Same assertion.
- **Q06** (Cooked rice sitting out) — Stages 1+2 fire successfully on `rice cooked`. U1 analog from the journal. Confirms the existing Stage-2 path is untouched.

These three are sufficient. Full Q01–Q17 re-run is not required.

---

## 13. Implementation risks drawn from `lessons.md`

- **Wired-but-not-used pattern** (2026-04-30 reranker): the new fallback must be invoked from the singleton/factory and its dependencies (alignment CSV loader, pathogen-characteristics index) injected. Verify the call chain end to end.
- **Producer-consumer in one change** (2026-05-07 bridge): the new `pathogen_category_fallback` provenance block needs both producer (grounding service) and consumer (audit route in `translation.py` + Zod schema on the frontend if relevant + tests) implemented together.
- **`from_text()` not `from_string()`** for pathogen → enum (2026-04-29): the pathogen strings in `pathogen_food_associations.csv` include species suffixes (`Salmonella spp.`, `Campylobacter jejuni`) that may not match `ComBaseOrganism`'s alias dict. Use `from_text()` for robustness.
- **Test fixtures broke when defaults landed/lifted** (2026-05-11, 2026-05-08): any test that constructs an `ExtractedScenario` without `pathogen_mentioned` and asserts on `defaults_imputed == []` will need filtering. Grep all `create_scenario(...)` calls before modifying.
- **`== []` assertions are fragile** (2026-05-11): prefer field-filtered assertions in new tests.
- **Guards belong at the orchestrating layer** (2026-05-08): when adding the new tier, place its dispatch at the same level as the existing Stage 1/Stage 2 dispatch in `_ground_pathogen_from_rag`, not nested inside Stage 2.
- **Audit-shape contract** (Q03/Q06/Q10 light regression per §12.4): verify the new code does not perturb multi-source citations, range_bound_selection events, or existing Stage-2 success paths.

---

## 14. Documentation updates required

- `CLAUDE.md` — add the new fallback to the architectural overview if listed there.
- `ptm_context.md` — new subsection under §5.2 describing the category-level pathogen fallback; update §8.13 (organism required field) to note the fallback now exists; add a new §8.x design-decision section; add a §15 changelog entry.
- `specifications.md` — update §3.2 (GroundingService) with the new tier; update §4.5 (ValueProvenance) with the new field; update §11.1 (API contract) if the warning text format is treated as a contract.
- `ptm_test_journal.md` — update Q12's `🟡` followup (`"should §2.4 fall through to pathogen_food_associations.csv when food_pathogen_hazards has no matches?"`) to `✅ resolved by Phase [X.Y]` with a one-line reference to this work. **No new journal entry in this phase.**
- `lessons.md` — append a session entry at session close.
- `data/sources/source_references.csv` — verify `IFT-2003-T1` is registered (should be already).

---

## 15. Open design questions (to resolve in the implementation plan, before code)

1. **Final `ValueSource` name.** Recommended: `RAG_PATHOGEN_CATEGORY_FALLBACK`. Alternatives in §8.1.
2. **Where the pathogen name normalization map lives.** Recommended: code constant in `grounding_service.py`. Rejected alternative: a CSV (would create a third pathogen-name authority).
3. **Exact name of the new provenance block.** Recommended: `pathogen_category_fallback`. Must sit alongside `category_bridge` cleanly without name collision.
4. **Whether to deduplicate pathogens across IFT subcategories before ranking, or after.** Both produce the same result; before-dedup is cheaper.
5. **Whether `pathogen_food_associations.csv` schema needs an `annual_deaths_us` denormalized column.** Recommended: no — keep `pathogen_characteristics.csv` as the single source of death counts; join at runtime.
6. **Whether the `ift_category_alignment.csv` is ingested into ChromaDB or read directly.** Recommended: read directly at startup, like `category_level_rows.csv` is loaded by `TaxonomyBridge`.
7. **U3 expected behavior** — does the composite-food guard affect pathogen resolution? Determine in Phase 1 verification by reading the existing pipeline; document the answer in the plan before writing the U3 test.

End of specification.
