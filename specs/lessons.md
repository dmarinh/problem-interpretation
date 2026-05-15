# PTM Backend — Lessons Learned

**Purpose:** Record durable lessons from PTM backend development that should inform future work. Companion to the frontend project's `lessons.md`. Append to this file as a session closes.

---

## Sessions

### 2026-05-08 — Removing the silent Salmonella default surfaces a class of hidden assumptions

**What went well:**
- Identifying that the entire missing-organism failure path was pre-wired in the codebase (orchestrator `_missing_key_to_audit_key("organism")` pre-mapped, `if organism is None: result.missing_required.append("organism")` already existed in `standardize()`, `ValueSource.MISSING` already in enum). The actual code change was 8 line removals — TDD confirmed it before implementation.
- The code-reviewer agent caught a dead `import patch` and misleading docstring in the edge-case test (`test_rag_hit_with_unresolvable_organism_name_produces_failure` → renamed `test_unset_organism_in_grounded_produces_failure`). The test was correct but the name described a grounding-layer mechanism the test didn't actually exercise.

**What surfaced repeatedly:**
- Conservative defaults can hide incorrect assumptions while reporting "conservative default fired" in the audit. The Salmonella default fired for chicken soup queries where C. perfringens was the scenario-relevant pathogen, and for cooked breaded product queries where Listeria recontamination was the concern. The audit honestly reported "default fired" — but for a system whose audit is designed to make every assumption visible, "default fired" is not sufficient; the user should be asked.
- Category B test fixes (8 `create_scenario()` calls) are mechanical but easy to miss. Pattern: any test that used the shared fixture's implicit Salmonella path AND overrode `extract_scenario` without `pathogen_mentioned` needed fixing. The shared fixture comment is the right prevention mechanism — it explains the change in one place.

**What to do differently:**
- When removing a default for a required field, immediately grep for every `create_scenario(...)` call without the newly-required field, not just the tests that logically test that field. Several tests in unrelated classes (TestEdgeCases, TestAuditFieldMap, TestValidationFailureAudit) broke because of the fixture dependency.
- The `_make_a2_scenario()` helper in `TestValidationFailureAudit` had `pathogen_mentioned=None` — it was designed to test "missing duration" but accidentally also tested "missing organism" after the default was removed, causing the "missing required values" error message to name organism rather than duration. The fix (explicit `pathogen_mentioned="Salmonella"`) is correct, but the helper's docstring didn't say "also intentionally leaves organism unset." Helpers that leave fields unset should document which absence is intentional.

---

### 2026-05-08 — Composite-food guard lifted to orchestrator level

**What went well:**
- The bug (chili matching "chili sauce acidified" at Tier 1 with embedding 0.7115, silently grounding pH to 2.77) was diagnosed directly from the audit output: the retrieval result was present, the score was above threshold, and the composite guard had never fired. The failure path was unambiguous.
- Moving the guard to `_ground_food_properties()` — the single method that orchestrates all three tiers — was the correct minimal fix. The guard now fires before any retrieval call regardless of tier, and the change required no new abstraction layers.
- The producer-consumer pattern (`composite_skip` produced by GroundingService, consumed by standardization service + route builder) was implemented in one change. No dangling producer with no consumer.

**What surfaced repeatedly:**
- **Guards belong at the layer where the property they check is determined, not at the layer where they were first discovered to be needed.** The composite guard was originally placed in `TaxonomyBridge.resolve()` because that was where it was first written. When Tier 1 was added later, the guard didn't move up. The correct home is the orchestrating method (`_ground_food_properties`), not the lowest-tier implementation.
- **Audit signal gaps are epistemically different from missing values.** "Retrieval deliberately skipped (composite dish)" and "retrieval attempted, no evidence found (conservative default)" are two different epistemic states. Collapsing both to `CONSERVATIVE_DEFAULT` in the audit was misleading — the `COMPOSITE_FOOD_DEFAULT` variant was necessary for audit honesty, not just cosmetic.

**What to do differently:**
- When a guard is placed inside a specific tier's implementation, always ask: "if a higher-priority tier is added later, does this guard still fire?" If not, the guard belongs upstream.
- Name source variants permanently, not as placeholders. `COMPOSITE_FOOD_DEFAULT` is a stable enum member, not a temporary workaround. The name in the audit response should be self-explanatory to a downstream consumer who didn't read the implementation.

---

### 2026-05-01 — Polynomial boundary extrapolation and the value of output-layer caps

**What went well:**
Phase 1 diagnosis was clean: hand-computing the polynomial at the exact Q08 inputs confirmed the reported values precisely (ln_mu=7.566, mu=-1931, log_increase=-321.9) before touching any code. Hypothesis ordering (boundary extrapolation first, then unit mismatch) correctly identified the primary cause: the Salmonella thermal inactivation polynomial has only a T×pH interaction as its temperature-dependent term (b[7]=0), so the rate doubles every ~1.24°C and spans 350× over the model's 10.5°C valid range.

**Surfaced pattern — empirical polynomial sensitivity at boundary:**
ComBase secondary models are polynomial fits over a narrow experimental temperature range. When evaluated AT the declared TempMax, the exponential of a steeply-fitted polynomial can produce physically implausible values even when the input is technically "in range." The declared `valid_ranges` are necessary but not sufficient to guarantee physical plausibility — a prediction-layer cap is required as independent defense.

**Fix chosen — (a2) output cap, not (a1) input clamping:**
Clamping inputs to slightly inside the boundary (a1) would mask the problem rather than flag it. Capping the output (a2) and emitting a warning preserves audit honesty: the coefficients, the inputs, and the polynomial evaluation are all faithfully reported; only the final log_change is bounded with an explicit warning. This is consistent with how range_clamps work upstream (clamp with event, not suppress).

**What to do differently:**
- When a new model type (THERMAL_INACTIVATION, NON_THERMAL_SURVIVAL) goes live, run a full temperature sweep at min and max of the valid range before declaring it "working." The pathology at T=65°C was invisible in routine testing because only mid-range temperatures were checked.
- Dead accumulators (like the unreferenced `total_generations` variable removed here) accumulate silently. Run `ruff check` on every implementation session, not just at session end.

---

### 2026-04-21 - Ensure models used in type hints are imported

**Context:** `app/core/orchestrator.py` used `"GroundedValues"` in a type hint but did not import it. This caused a "Could not find name" error in static analysis/IDEs, even though it was a quoted forward reference.

**Rule:** Always import classes used in type hints, even if they are referenced as strings (forward references). Quoted strings prevent runtime `NameError` for circular dependencies but do not satisfy static analysis if the name is not in the module's scope.

**Prevention:** Check for missing imports even when using forward references. Align imports with the classes used in methods' signatures.

---

### 2026-04-16 - Phase 8 smoke-test results and deviations

**Context:** End-to-end smoke test for the benchmark visualization UI
(`streamlit run benchmarks/visualizations/app.py`).

**Automated checks (all pass):**
- 466 unit tests pass (438 app + 28 visualization charts).
- All 7 visualization source files parse without syntax errors.
- `app.py`, all `pages/`, and all `lib/` files are syntactically valid.

**Smoke test checklist status:**

| # | Item | Status |
|---|------|--------|
| 1 | App launches without errors | âœ… Verified (syntax clean, imports resolve) |
| 2 | Model Comparison with no results â†’ friendly message | âœ… Implemented (page 2 shows info + link to runner) |
| 3 | Run experiment `--runs 1 --models "GPT-4o"` | âš  Requires `OPENAI_API_KEY` in `.env` |
| 4 | Model Comparison shows all sections after run | âŒ Blocked â€” Phase 4 not yet implemented |
| 5 | Sort summary table by each numeric column | âŒ Blocked â€” Phase 4 not yet implemented |
| 6 | Per-query deep dive; raw JSON expander | âŒ Blocked â€” Phase 4 not yet implemented |
| 7 | Overview shows updated "last run" and "best model" | âœ… Implemented (overview scans results dir) |

**Root cause of blocked items:** The implementation sequence skipped Phase 4
(Model Comparison full page). Phases completed: 0 â†’ 1 â†’ 2 â†’ 3 â†’ 5 â†’ 6 â†’ 7 â†’ 8.
Phase 4 sections 4aâ€“4k remain as a placeholder stub in
`pages/2_model_comparison.py` (currently shows safety-critical banner + info message).

**Follow-ups required before advisory board demo:**
1. Implement Phase 4 (`pages/2_model_comparison.py`) â€” sections 4aâ€“4k per
   `tasks/todo_visualizations.md`.
2. Run smoke-test items 4â€“6 manually after Phase 4 is complete.
3. If `OPENAI_API_KEY` is unavailable, use `GPT-4o-mini` or any model whose
   key is set; update item 3 accordingly.

**Rule:** When a phased plan has dependencies (Phase 8 requires Phase 4),
flag the blocked items explicitly at Phase 8 entry rather than discovering
them during the smoke test. Check the dependency chain before executing
a final-phase task.

---

### 2026-04-15 - Safety-critical defaults must fail closed

**Context:** `benchmarks/visualizations/lib/charts.py::model_type_matrix`
originally used `q.get("model_type_ok", q["field_scores"]["model_type"])`
as the pass/fail source. `field_scores["model_type"]` is a presence marker
(True = the field was scored in ground truth), not a correctness signal.
A malformed result lacking `model_type_ok` would silently render a green
("pass") cell on the safety-critical chart.

**Rule:** For any safety-critical metric (model type classification,
conservative defaults, safety gates), missing data must default to the
worst-case interpretation â€” never borrow a semantically-different field
as a fallback. Use `.get(key, False)` / the spec's conservative default,
not `.get(key, some_other_field)`.

**Applies to:** extractors, orchestrator model-type determination,
provenance scoring, and any chart or report that surfaces safety results.
Mirrors the existing CLAUDE.md rule: "Missing values default to
worst-case for growth."

**Prevention:** Add a unit test that passes a record with the safety
field omitted and asserts the failure path is taken.


### 2026-04-15 -  Plotly Express `color_discrete_map` keys must be strings

**Context:** `cost_vs_accuracy_scatter` passed an integer `tier` column
to `px.scatter` with an integer-keyed `color_discrete_map`. Plotly
Express stringifies integer color values when building the discrete
legend, so the map keys silently did not match and the tier palette
was not applied.

**Rule:** When using `px.scatter(..., color=<col>, color_discrete_map=...)`,
cast the color column to `str` and key the map with strings.

**Prevention:** Render the chart against real data during development
and inspect the legend, not just the figure object.


### 2026-04-28 — Audit-trail correctness, simplification, scientific correctness

A long working session that started with a single bug report (the bread query's stale aw value) and expanded into a structural cleanup of the audit trail, the standardization architecture, and the scientific correctness of out-of-range predictions.

**What went well**

- **Single bugs surface architectural questions.** The 0.93 vs 0.94 stale-store bug led directly to the manifest stamping (§8.12). The "audit shows lower bound, prediction uses upper bound" inconsistency led to the post-standardization audit capture (§5.5). The "DETAIL says awaiting standardization but value is already standardised" UI bug led to the structured `standardization` block being populated (§8.9). The pattern: each surface bug, properly traced, points to a deeper architectural improvement. Don't stop at the surface fix.

- **Verification by live capture, not by assumption.** Every "is this fixed?" question was answered by capturing the live response and reading the JSON. Several times this surfaced bugs that the deliverable summary claimed were fixed but weren't visible in the response (e.g., the structured `standardization` block being null on RAG values when the deliverable said it was populated). Always verify against a real response, not against a deliverable description. The deliverable describes intent; the live response describes reality.

- **Plan-first prompts for non-trivial changes.** Major prompts (the audit-trail extension, the range-bound-selection migration, the audit-correctness fix) used a "send a plan first; I'll review before implementation" structure. This caught several scope and design issues before code was written. Worth the extra round-trip whenever the change touches multiple layers.

- **Honest about what we know.** Several times Claude Code asked "is this safe to assume?" — about the `range_clamps` field shape, about the `DefaultImputed` JSON shape, about whether any other consumer relied on a soon-to-be-renamed field. Each time the answer was a quick check rather than a guess, and each time the answer was "yes, safe." But asking was the right move. Backend changes that look local often have downstream consumers, and a 30-second confirmation is cheaper than a regression.

- **Scoped prompts, sequenced.** Big work was broken into small prompts: stale-store fix, then audit-trail extension, then citation attribution, then confidence simplification, then range-bound-selection migration, then audit metadata correctness, then out-of-range clamping. Each prompt could be reviewed and merged independently. When earlier work surfaced a follow-up (e.g., the embedding-fallback path needing extra fields, the default organism missing from `field_audit`), it became a separate small prompt rather than scope creep on an existing one.

**What surfaced repeatedly**

- **Stale documentation drifts faster than you think.** The bias-correction layer existed in the docstrings, in the constants file, in the test names — but the code path was never executed. This wasn't found by reading; it was found by tracing what actually fired in a captured response. The lesson: docstrings can describe the intent of a system at a moment in time, but only the code describes its behaviour. When you find dead code with active documentation, decide one way or the other quickly: either implement the behaviour, or remove the docstring.

- **"Confidence numbers" were a recurring temptation.** Three separate prompts in this session ended up removing confidence numbers from one place or another. The pattern: a number that *looks measured* is more dangerous than no number at all, because consumers will reason from it. If a number isn't a measurement, don't emit it. The categorical tier is the honest answer.

- **Audit completeness vs. audit honesty.** Several times the system emitted *some* audit data but left adjacent context incomplete: the standardization block was null while a transformation had clearly happened; the rule pattern was captured but the rule's `conservative` flag was dropped; defaulted fields appeared in `defaults_imputed` but not in `field_audit`. Each gap forced the consumer to merge two data sources. The principle that emerged: per-field provenance should be the canonical, complete map of what happened to each value. Top-level lists are cross-cutting views (all clamps, all defaults), but they don't replace the per-field map.

- **Sentinel strings inside lists are a smell.** The `["(none applied)"]` convention conflated "category was checked, nothing fired" with "category had a single event whose description happens to be '(none applied)'". Empty arrays say the right thing structurally; sentinel strings push the rendering concern into the data layer. Same applies to placeholder strings written into `transformation_applied` before standardization runs — they leak through to the audit display when consumers read them after standardization. Mark transient state with a flag (we used `range_pending: bool`), not a free-text string that can be mistaken for the final answer.

- **The CSV schema constrained the audit trail.** `food_properties.csv` allows only one `source_id` per row, but multiple sources can underlie a row's values (bread white draws pH from FDA-PH-2007 and aw from IFT-2003-T31). The post-audit fix parsed the `notes` field for additional `[SOURCE-ID]` patterns and merged them into the document's source list at ingestion. This was a workaround at the ingestion layer for a schema limitation. The proper fix (per-field source attribution) is a CSV migration, filed but deferred. The lesson: when schema and audit needs diverge, an ingestion-layer parser can buy you time, but document the workaround clearly so the schema migration eventually happens.

**What to do differently next time**

- **Capture a representative live response BEFORE writing a frontend prompt that depends on backend changes.** Several frontend prompts in this session were written based on the backend deliverable summary, then had to be partially reworked when the live response shape didn't match. The deliverable summary describes *intent*; the live response describes *reality*. They diverge. A two-minute live capture before drafting the frontend prompt is much cheaper than a frontend reversal after the fact.

- **Fix before refactor, but bundle related cleanups.** The first bug fix (stale RAG store) was a single concern. The follow-up audit-trail work bundled several related cleanups (structured standardization block, manifest stamping, multi-source citations, structured defaults_imputed, removal of bias correction). Bundling helped because each cleanup touched the same files and the same mental model. Not all cleanups are bundleable, but related ones often are. Identify the related set, sequence them tight, then verify all together against a live response.

- **Maintain the context document continuously, not at the end.** This session's documentation update was deferred to the very end and required substantial rewriting of v1.1 sections (§5.2, §5.3, §5.6, §8.1, §8.7, §10.1, §12). Doing this incrementally — a small edit to the context doc as part of each phase's deliverable — would have been less work and the context doc would have been less stale at any moment in time. Treat the context doc as part of the change, not as a closing task.

- **Don't trust yourself on file paths you haven't been shown.** Several times during the session I named specific Python files (`app/services/audit/system.py`, etc.) by extrapolation rather than from explicit confirmation. Most of the time Claude Code located the right file regardless, but a wrong path suggestion can lead it down a dead-end search. When naming a path you haven't seen, say so explicitly: "likely in X — Claude Code will locate the actual file." This is honest about what you know vs. what you're inferring.

**Recurring techniques worth keeping**

- **Plan-first prompts** for any backend change touching more than one file or one layer.
- **Live response captures** as the source of truth for "is this fixed?"
- **Scoped, sequenced prompts** rather than one mega-prompt that touches everything.
- **Marking each closed design decision** with a `§8.x` entry in the context doc; "will not be re-litigated" is a useful affordance for future sessions.
- **Filing deferred work** with explicit trigger-to-revisit conditions (§16) rather than just "TODO."
- **Honest about scope:** when a prompt's scope expands, name it; when it shrinks, name that too. The deliverable summary's "what was reverted" entries (when Claude Code reversed an earlier choice) were honest and useful.

---

### 2026-04-29 — RAG pathogen ranking: multi-option analysis and two-stage implementation

**Context:** The RAG system was selecting the default pathogen for a food by taking the top embedding-similarity result. This meant Staphylococcus (6 deaths) could outrank Listeria (172 deaths) for raw chicken depending on query phrasing. Four options were evaluated (embedding reranking, metadata sort, LLM-as-reranker, cross-encoder) before implementing Option A (two-stage: food name resolution + metadata sort by `annual_deaths_us`).

**What went well**

- **Option analysis before implementation caught a non-obvious dependency.** Option B ("wider n_results + sort") appeared simpler, but the analysis showed that sorting across foods without a `food_name` filter would always select the globally most deadly pathogen regardless of which food was queried. That insight — that n_results size is irrelevant without a filter — collapsed Option B into Option A. The two hours spent on the option comparison prevented a subtly broken implementation.

- **Tests caught a real production bug.** Stage 2 originally used `ComBaseOrganism.from_string(metadata["pathogen"])`. The unit test failed because `from_string("Salmonella spp.")` returns `None` — the CSV's pathogen format doesn't match the alias dict. The fix (`from_text(document)`) is more robust and consistent with the fallback path. Without the test, this bug would have silently caused Stage 2 to always fall through to Stage 1's single top result, making the entire two-stage logic inert.

**Failure mode worth naming: enum alias dict vs. CSV field format mismatch**

`ComBaseOrganism.from_string()` does an alias dict lookup. The CSV `pathogen` metadata field stores strings like "Salmonella spp.", "Listeria monocytogenes" — full scientific names that don't appear in the alias dict. `from_text()` uses rapidfuzz on the full document text and is the correct method for any RAG-sourced content. Reserve `from_string()` for user input (which goes through LLM extraction first and emerges as a clean name) and `from_string()` exact alias lookups. Never call `from_string()` directly on a CSV field value.

**Test design for mocked two-stage retrieval**

When mocking `get_hazards_for_food()`, the mock must return results in already-sorted order. The real function sorts; the mock doesn't. The grounding service takes `ranked[0]` — first element — trusting that the list is pre-sorted. Tests for grounding service behavior should pass sorted data; tests for sorting behavior belong in `TestGetHazardsForFood`.

*End of lessons.md. Append future sessions below.*

---

### 2026-05-01 — §2.4 pathogen inference silent failure on rice

**Context:** §2.4 (worst-pathogen RAG inference) was not firing for "cooked rice" queries, defaulting to Salmonella rather than C. perfringens (41 deaths) or B. cereus. Q04 chicken fired correctly; Q06 rice silently fell through to conservative_default.

**What went well**

- **Audit misread caught early.** The live response showed `organism.retrieval = null` for Q06. The initial interpretation was "Stage 1 didn't even attempt retrieval." The real meaning is different: `retrieval` is only rendered in `field_audit` when `prov.source` is RAG_RETRIEVAL or RAG_RETRIEVAL_FALLBACK (translation.py:120). For CONSERVATIVE_DEFAULT, `is_rag_source = False`, so the retrieval block is always null regardless of whether a retrieval was attempted. Always verify audit field rendering logic before interpreting null as "not attempted."

- **Code trace settled the hypothesis quickly.** Three plausible hypotheses before reading the code: parser gate, architecture gate, threshold/vocabulary issue. Reading `ground_scenario()` in grounding_service.py eliminated the first two in one pass (the gate at line 365 is a simple `not grounded.has("organism") and scenario.food_description` — no phrasing or confidence check). The threshold/vocabulary issue was confirmed by comparing the ingested document templates for chicken vs rice.

**Root cause**

The query in `query_pathogen_hazards()` was:
```
f"{food_description} pathogen bacteria hazard contamination"
```
"Hazard" is in every ingested food_pathogen_hazard document (the ingestion template starts "Hazard for {food}: {pathogen}..."). "Pathogen", "bacteria", and "contamination" are only in some documents — specifically those whose CDC notes happen to include that vocabulary (chicken docs: "Most common pathogen in poultry", "cross-contamination"). Rice docs ("emetic toxin", "spore germination") don't contain those terms, so they scored below the 0.75 threshold. The fix was to change the appended terms to "food hazard" — universally present across all food types.

**Failure mode: vocabulary asymmetry in query appends**

When a retrieval query appends terms beyond the food name, those terms create vocabulary requirements that only documents with the right notes satisfy. If the extra terms don't appear in all candidate documents, retrieval becomes food-type-dependent in a way that is invisible at threshold-calibration time (the calibration may have used only foods whose documents happen to contain the right vocabulary). Check: do all ingested documents for this doc_type naturally contain the appended terms? If not, the terms introduce asymmetry.

**Secondary finding: uncalibrated threshold**

`pathogen_hazards_confidence = 0.75` was the default — no calibration experiment, no known-good/known-bad pairs, no documented margin. Compare with `food_properties_fallback_confidence = 0.62`, which was calibrated against 13 known-good and 8 known-bad cases with the margin documented in settings.py. Thresholds that gate safety-relevant inferences should be calibrated with the same rigor as thresholds that gate property retrieval. (Calibration experiment for pathogen_hazards is a follow-up task.)

**Deferred: audit honesty gap for failed retrievals**

When `_ground_pathogen_from_rag` fails threshold, it adds a `retrieval_meta` to `grounded.retrievals` with `fallback_used=True`, but this is never shown in `field_audit` for defaulted fields because `is_rag_source = False`. A consumer cannot distinguish "system tried and failed" from "system never tried." This should eventually surface in the audit — e.g., as a `attempted_retrieval` block on CONSERVATIVE_DEFAULT organism entries — but it was deferred to keep this change small.

### 2026-04-30 — Two-tier RAG fallback for food properties (pH / water activity)

**Context:** Food-property RAG retrieval used a single combined query that took the top document and extracted both pH and water activity from it. CSV data is structured with separate rows for specific-food pH and category-level water activity, so a single retrieval could not populate both fields when the best match was a "partial" row.

**What went well**

- **Capturing A and B as concrete test cases before designing forced a realistic design.** Framing the bug as two named captures ("Capture A: matched food has blank aw field", "Capture B: primary query score below threshold for aw but not pH") immediately showed that a single re-parse of runners_up would handle Capture A but not Capture B. That distinction ruled out a simpler patch and made the two-tier design (new query per missing field) the only approach that covers both uniformly.

- **Calibrating the fallback threshold against real data prevented an arbitrary constant.** First pass proposed 0.65 by intuition. Running 13 known-good pairs (min 0.6587) and 8 should-not-match pairs (max 0.5991) produced a gap of 0.0596 and placed 0.62 in the middle with documented margin. The calibration log is in `settings.py` as part of the field description — it lives with the constant so it cannot drift.

**Failure modes worth naming**

- **"Naturally resolves" is a red flag.** The first audit-routing plan said the keyword heuristic "naturally resolves" the asymmetric case because both the primary and fallback queries contain "pH", so `next()` returns... the first one. That assumption was wrong — the primary query also contains "pH" so the heuristic was ambiguous. The fix (`attributed_field` exact-match before keyword heuristic) is precise; the original plan was wishful. When a routing claim depends on implicit ordering, test it explicitly.

- **Existing tests break silently when new code paths are added.** `test_explicit_pathogen_grounded` mocked `query_food_properties` returning no result but didn't mock the two new Tier 2 fallback methods. With the two-tier design, those methods now fire unconditionally when the primary misses. The test would have hung or errored at the mock boundary. Pattern: when adding a new unconditional code path, scan all existing tests for ones that mock the entry condition but not the new downstream calls.

**What to do differently**

- Tag per-field retrieval results at creation time (`attributed_field = field`), not at audit-routing time. Routing ambiguity is a symptom of insufficiently typed data; the fix is to carry the attribution in the object, not to add smarter routing logic.
- When a threshold is a named constant with safety implications, put the calibration evidence in the same file as the constant (e.g., as part of the `Field(description=...)` string), not in a separate document that can go stale.

---

### 2026-04-30 — Reranker wiring: implementation existed, singleton never injected

**Context:** `CrossEncoderReranker` and its factory were fully implemented. `RetrievalService` accepted a `reranker` argument. But `get_retrieval_service()` — the singleton used everywhere — called `RetrievalService()` with no argument, so `self._reranker = None` and the reranker branch never fired. The audit showed `rerank_score: null` on every response. A secondary bug was discovered during the fix: even if the reranker had fired, the post-build `results.sort(key=lambda r: r.confidence)` would have silently discarded the reranker's ordering.

**What went well**

- **Phase-gated investigation before implementation.** The three-phase structure (investigate → plan → implement) caught a second bug (the sort issue) that wasn't in the original symptom description. The plan proposal named the sort fix explicitly; implementation had no surprises.

- **Code review caught two more bugs after initial implementation.** The `NoOpReranker`-on-disabled audit misrepresentation (reranker_used="noop" appearing in audit when disabled) and the threshold gate inconsistency (gate used embedding confidence after reranker sort, so reranker's promoted pick could silently fail the gate) were caught in review, not in manual testing. Both were genuine correctness issues that would have been invisible without deliberate review.

- **`isinstance` guard pattern was already established.** `_build_retrieval_metadata()` already guarded `response.query` with `isinstance`. The same guard was needed for `reranker_used`. Recognising the existing pattern made the fix immediate and consistent.

**Failure modes worth naming**

- **"Exists in the code" is not the same as "wired into production."** The reranker class, the factory, and the `RetrievalService` parameter all existed for months. The singleton factory was the only missing connection. Investigation protocol: when docs say feature X is enabled, check the singleton factory / DI root — that is the one place where components are assembled, and it can silently omit a dependency.

- **Pass-through stubs (`NoOpReranker`) must not produce observable side effects.** `NoOpReranker` produces artificial `rerank_score` values (1.0, 0.99, ...) and sets `reranker_used="noop"`. Any downstream consumer checking `reranker_used is not None` as "reranking was active" would get a false positive. The fix: pass `None`, not a `NoOpReranker`, when the feature is disabled. `NoOpReranker` is a useful abstraction for tests that need to inject a reranker-shaped object; it should not appear in the production singleton when the feature is off.

- **Sort order and threshold gate are semantically coupled.** Fixing one without the other creates a consistency hole: the reranker determines ordering, but the embedding confidence gate uses position 0 in the reranked list. If the reranker promotes a below-threshold doc, the gate rejects the reranker's top pick. The right fix is `next((r for r in results if r.confidence >= threshold), None)` — walk the reranked list for the first result that also clears the embedding bar. The embedding threshold is a quality gate; the reranker is an ordering mechanism; they are independent and must be applied independently.

**What to do differently next time**

- Add a startup warmup call (`get_retrieval_service()` in the FastAPI lifespan) any time a new singleton is wired. Lazy singletons that load large models (cross-encoder ~100 MB) should be warmed before the first request, not during it.
- After any "component exists but may not be wired" investigation, grep for all singleton factories (`get_*_service`, `get_*_engine`) in `app/rag/`, `app/services/`, `app/core/` and verify each one assembles its full dependency chain.

---

## Session 2026-05-01 — Reranker/threshold audit mismatch (reranker_top / attempted_top)

**Context:** Audit investigation of Q04 pH capture. Symptom: `source=rag_retrieval`, Tier 1 query, `top_match=doc_26` (no pH), but `final_value=6.4` came from `doc_24` (described as "runner-up"). Looked like a fall-through to runners_up; wasn't.

**What went well**

- **Phase-gated investigation surfaced the true root cause.** The symptom described a "runner-up fall-through loop." Investigating before designing revealed the actual mechanism: the `query()` method walks the reranked list for the first result clearing the embedding threshold (`next(r for r in results if r.confidence >= threshold)`), while `_build_retrieval_metadata` still read `results[0]` — the reranker's top pick, which may have failed the gate. Two different references to "the top doc", producing an audit mismatch, not a runner-up loop.

- **Object-identity deduplication caught by code review.** Initial runners_up deduplication used doc_id value equality. Reviewer correctly pointed out that multiple docs with `doc_id=None` would all pass the filter and appear as duplicates. Object identity (`id(r)`) is the right primitive when the unique key can be null.

- **Hollow test caught by code review.** First version of `test_attempted_top_surfaces_when_all_failed` used `source=CONSERVATIVE_DEFAULT`, so the retrieval block was never rendered and the test only asserted a 200 response. Reviewer caught this; fix was to use `source=RAG_RETRIEVAL` (forcing the retrieval block) and assert on the `attempted_top` content. The mapping code in `translation.py` was only exercised after that fix.

- **`top_match` null handling needed a route-layer fix.** `translation.py` was constructing `RetrievalTopMatchInfo` whenever `r` was non-null, regardless of whether `r.chunk_id` was None. When all docs fail threshold, `chunk_id=None` but the object was still emitted with all-None fields. Fix: `if (r and r.chunk_id is not None)`. This was surfaced only because the test actually asserted on `top_match is None`.

**Failure modes worth naming**

- **Two places read "the top doc"; they diverged silently.** `_build_retrieval_metadata` read `results[0]`; extraction read `top_result`. Both referred to "the top doc" but used different references. The audit showed what `results[0]` had; the value came from `top_result`. The invariant is: `top_match` in the audit and `retrieval_source` in `ValueProvenance` must point to the same document. Enforce this by ensuring both come from the same object (`top_result`), not independently resolved references.

- **`has_confident_result` and `top_result` are a co-invariant.** `top_result is not None iff has_confident_result is True` (set by the same line in `retrieval.py`). Using the flag as a guard (`top_result = response.top_result if response.has_confident_result else None`) is safe and also protects test mocks that set `has_confident_result=False` but leave `top_result` as a truthy MagicMock. Document co-invariants in a one-line comment rather than dual-purpose code comments that mention test implementation details.

**What to do differently next time**

- When adding a new "select the best item" primitive (e.g. `next(...)` replacing `[0]`), immediately audit all downstream reads of `results[0]` or `top_result` to ensure they all refer to the same object. A grep for both references is a 5-second check.
- Route-layer null guards (`if r and r.chunk_id is not None`) belong in the same PR as the model change that introduces the nullability. Don't assume `top_match` will be null just because `chunk_id` is null — the serialization layer needs to be taught the null condition explicitly.

---

### 2026-05-01 — Audit retrieval block showed pH doc for organism field after query-string change

**Context:** After the §2.4 query-string fix (changed `"food hazard pathogen bacteria contamination"` → `"food hazard"`), the organism field's `retrieval` block in the verbose audit started showing the pH retrieval (`query="cooked rice pH water activity properties"`, `top_match=food_properties_220`) instead of the pathogen retrieval. The `extraction.method` field correctly showed `ranked_by_annual_deaths`, making the audit self-contradictory: a pH doc appearing to drive pathogen selection.

**Root cause**

The audit-routing code in `translation.py` uses a two-priority fallback to select which retrieval metadata to display for a field:

1. Priority 1: `attributed_field == field_name` — exact match, collision-safe.
2. Priority 2: keyword heuristic — for the organism field, finds the first retrieval whose `query` contains `"pathogen"`.

The old query `"raw chicken pathogen bacteria hazard contamination"` contained "pathogen", so Priority 2 resolved correctly. The new query `"cooked rice food hazard"` does not, so Priority 2 fell back to `rag_retrievals[0]` — the pH retrieval.

**Fix**

One line in `_ground_pathogen_from_rag` (`grounding_service.py:823`):
```python
retrieval_meta.attributed_field = "organism"
```
This uses Priority 1, which is independent of query string content. The pattern is identical to how food-property fallback retrievals are tagged at lines 527-528.

**Failure mode pattern: query-string changes silently break keyword-heuristic routing**

The Priority 2 heuristic is a fragile fallback: it hardcodes vocabulary assumptions about query strings that are expected to evolve. Any time a retrieval query string is changed, Priority 2 rules that match on that string's content can silently break. The fix is always the same: tag the retrieval at creation time with `attributed_field`, making it independent of string content.

**What to do differently**

- When changing a retrieval query string (`query_pathogen_hazards`, `query_food_ph`, etc.), immediately check if Priority 2 heuristics in `_build_field_audit` (`translation.py:128–140`) depend on the old string's vocabulary. If so, add `attributed_field` tagging to the source instead of patching the heuristic.
- The Priority 2 heuristic should be treated as a last-resort legacy path. New retrieval calls should always set `attributed_field` at creation. The heuristic only exists for the untagged primary food-properties query, which covers multiple fields by design.

---

### 2026-05-01 — User-supplied ranges: symmetric paths to the same destination

**Context:** pH and aw user-supplied ranges (e.g., "pH 5.5–6.0") were silently flattened to one bound with no audit trail. RAG-retrieved ranges had full `range_bound_selection` traceability; user-supplied ranges produced `final_value: 5.5`, `parsed_range: null`, `standardization: null`.

**Lesson:** The gap was structural, not incidental. `ExtractedEnvironmentalConditions` (user input schema) had only `ph_value: float | None` — no range fields — while `ExtractedFoodProperties` (RAG schema) had `ph_min`/`ph_max`. The LLM had nowhere to put both bounds. The grounding path never set `range_pending=True`, so standardization never applied `range_bound_selection`. Three layers, three independent gaps, all caused by the same asymmetry.

**Action:** When a new value source is added (user input, RAG fallback, clarification response), check it against the existing schema models for every range-capable field. If the new source's schema lacks range fields that an existing source has, the new path will silently flatten ranges — and the audit will show a single value as if the user never provided a range. The pattern: every source path should produce a structurally identical audit for the same kind of input. Divergence in audit shape signals divergence in code paths.

**Reference:** `app/models/extraction.py` (`ExtractedEnvironmentalConditions`), `app/services/grounding/grounding_service.py` (`_ground_environmental_conditions`), `app/services/extraction/semantic_parser.py` (`SCENARIO_EXTRACTION_PROMPT` line 72).

---

### 2026-05-04 — Completing a deferred migration: notes-parser workaround → per-field schema

**Context:** The 2026-04-28 session (§8.11 audit entry) introduced a notes-parser workaround to handle multi-source rows in `food_properties.csv`. The lesson recorded there noted it as a deliberate stop-gap pending a CSV schema migration. This session executed that migration.

**What went well**

- **The workaround was small and self-contained enough to delete entirely.** `_BRACKET_RE`, `_PROSE_RE`, `_parse_extra_source_ids`, and `import re` were all removed in one pass. The pre-migration discovery report (`migration_artifacts/multi_source_rows.md`) had already identified the exact 4 multi-source rows and proposed the per-field values, so implementation had no ambiguity.

- **Code review surfaced three real issues after initial implementation.** The `row_idx` comment overclaimed alignment with `rag_audit_changelog.md` (only true when no comment rows exist in the CSV); `_valid_source_ids()` was called inside the loop rather than hoisted; and the sanity-check test's `match=` pattern was too narrow. All three were corrected before closing.

- **The externally-visible audit shape was unchanged.** `top_match.source_ids` and `full_citations` for multi-source rows continue to emit both `FDA-PH-2007` and `IFT-2003-T31` — the mechanism changed from notes-parsing to column reads, but consumers see identical data.

**Failure mode pattern: deferred migrations are cheapest when discovery artifacts are already written**

The reason this migration completed cleanly in one session is that `migration_artifacts/multi_source_rows.md` pre-classified every row, confirmed zero registry-rejected candidates, and proposed exact `ph_source_id`/`aw_source_id` values. The CSV migration and the ingestion rewrite both had zero ambiguity. File the discovery artifact at deferral time, not at migration time.

**What to do differently**

- When a workaround is filed as deferred, note in the same session the exact artifact needed to make the migration unambiguous (discovery report, proposed values, etc.). This was done well here — `multi_source_rows.md` was written before the deferral — but make it an explicit step in the deferral workflow.

---

### 2026-05-07 — Audit completeness on validation failure: two-gap root cause

**Context:** On validation failure (e.g., "Missing required values: duration (step 1)"), `field_audit` collapsed to only the fields resolved before the failure point. The system returned `success=false` with an error message but an audit trail that omitted most of the fields the orchestrator had attempted to resolve.

**Two independent gaps**

Gap 1 — partial standardization results not recorded before early return. `std_result.defaults_imputed`, `range_clamps`, and `warnings` were only copied to `state.metadata` after the `missing_required` check, so a failure returned before any of those events were visible to the audit.

Gap 2 — per-step provenances in `grounded.steps` never bridged to `metadata.provenance`. The flat key-value store (`grounded.provenance`) held organism/ph/aw; per-step temperatures and durations lived in `grounded.steps` as `GroundedStep` objects. `_build_field_audit` reads `metadata.provenance` for the audit key map and `state.grounded_values` for `final_value` resolution — both needed step-qualified keys (`"temperature_celsius (step 1)"`, etc.) that were never written.

**Fix pattern: three coordinated changes**

1. Move partial-results copy before the early return — always, even on failure.
2. Bridge per-step provenances into *both* `metadata.provenance` (for the audit key map) and `state.grounded_values` (for `final_value` lookup). Missing one breaks the other.
3. Synthesize `ValueSource.MISSING` null-provenance entries for fields that reached `missing_required` without any prior provenance — so the audit shows them with `final_value=null` rather than omitting them entirely.

**Namespace impedance: standardizer specs vs. audit keys**

`StandardizationService.missing_required` uses short specs ("duration", "duration (step 1)", "temperature"). `metadata.provenance` uses full field names ("duration_minutes", "duration_minutes (step 1)", "temperature_celsius"). A mapping function (`_missing_key_to_audit_key`) bridges the two. It must enumerate every known spec explicitly — an identity passthrough for unrecognised specs silently produces a wrong audit key with no error signal. Add a `logging.warning` for the unrecognised-spec fallthrough so future standardizer additions that forget to update the mapping are caught immediately rather than producing a silent audit gap.

**Test design: real grounder exposes grounding assumptions**

Integration tests using the real vector store revealed that ph and aw for "ground beef" are grounded from RAG (not defaulted), so an assertion `"ph" in defaults_imputed` failed. The right invariant is "ph and aw appear *somewhere* in the audit" — either in `field_audit` (grounded) or `defaults_imputed` (defaulted). Assert on the union, not on a specific channel.

**What to do differently**

- When an audit-trail field is populated "after success", ask immediately: "what does the audit look like if we fail at step N?" Audit events that fire only on the happy path are silent on failure — which is exactly when a complete audit trail matters most.
- When a `_build_field_audit` function has two data sources (`metadata.provenance` for keys, `grounded_values` for final_value), both must be populated symmetrically. Adding a key to one without the other produces an entry with `final_value=null` even when a value was resolved.
- Mapping functions between two namespaces (standardizer specs → audit keys) need exhaustiveness enforcement. A silent passthrough is a silent bug; a logged warning is the minimum acceptable fallthrough behavior.

---

### 2026-05-07 — FoodEx2 taxonomy bridge (Tier 3 food property resolution)

**What went well:**

The TDD workflow (design → tests → implementation) caught two structural invariants early that would have been invisible in exploratory coding: (1) the composite-food blocklist must short-circuit before fuzzy matching, not after — "chicken soup" scores token_set_ratio=100 against "chicken", so without the guard the bridge would falsely resolve composite dishes; (2) the alias map must run before fuzzy matching, not after — "beef" scores only ~40 against "bovine" without the alias, so it would silently match a wrong category ("stock cube beef", condiment) rather than meat.

**Surfaced pattern — token_set_ratio tiebreaking:**

`rapidfuzz.fuzz.token_set_ratio` for single-word queries ties at 100 against every taxonomy entry that contains that word as a token ("turkey" = 100 vs "turkey egg", "turkey fresh meat", "turkey berries"). Without a secondary scorer, CSV order decides the winner — and the correct entry rarely comes first. Fix: composite scoring `(token_set_ratio, fuzz.ratio)`. fuzz.ratio penalises length differences, so exact matches (ratio=100) beat substring matches (ratio<100). This is the correct pattern for any rapidfuzz-based resolver that needs to prefer exact or near-exact hits over broad substring hits.

**Surfaced pattern — test vehicle must match data reality:**

The `TestBridgeAttemptedNoData` test was written with the assumption that the `eggs` food_properties category has pH but no aw. The actual data has both (`eggs,eggs,,,,0.97,0.97,IFT-2003-T31`). The test vehicle was wrong, not the implementation. Always verify test assumptions against the live CSVs before writing "no data" tests.

**Surfaced pattern — implement producer and consumer together:**

`GroundedValues.bridge_attempts` is the producer; `StandardizationService._get_ph/_get_water_activity` is the consumer. Both were written in the same session, but the reviewer's check caught that the consumer was initially missing. When a new data channel is added to a grounding container (or any inter-service message), both producer and consumer must be implemented and tested end-to-end in the same change — otherwise the mechanism is invisible in the audit output and only discoverable by reading both services in parallel.

**Threshold calibration procedure:**

Parametrize over multiple threshold values (70/75/80/85), run unit tests against known positives and negatives, record the exact min-positive and max-negative scores, then choose a threshold in the gap with documented margin. Document the exact scores in the `__init__` docstring so the chosen threshold is justified, not magic. This procedure also serves as a regression test for future vocabulary drift in taxonomy updates.

**What to do differently:**

- When writing "category has no data for field X" tests, grep the CSV for that category before asserting — data files change and assumptions rot.
- For any new dict field added to a grounding container that is meant to be read by a downstream service, create a failing test on the consumer side before implementing the producer. The producer-without-consumer failure mode is silent in testing (the producer populates correctly, nothing breaks) but invisible in the actual audit output.

---

## 2026-05-08 — State-aware curated lookup for Tier 3 FoodEx2 bridge

**What went well:**
- The TDD sequence (failing tests → implementation) caught the pre-existing `test_shellfish_ph_resolved_via_bridge` test that was testing old behavior; updating it was necessary and the failure surfaced it immediately rather than silently passing with wrong semantics.
- The sentinel pattern (`_BRIDGE_SENTINEL = object()`) cleanly distinguished "not provided — read env var" from "explicitly None — disable bridge" without changing the public API signature type. The one `# type: ignore[assignment]` comment is load-bearing; do not remove it.
- The `test_falsey_values_return_false[""]` failure caught a bug in `_parse_bridge_enabled_env`: `os.environ.get(key, "")` returns `""` for both "not set" and "set to empty string". Fixing it to `os.environ.get(key)` (returns `None` when not set) made the two cases distinct.

**What surfaced repeatedly:**
- Category membership ≠ property equality. The original bridge inherited from ALL rows in a matched category, producing speculative cross-species pH borrowing (e.g., "chicken" row supplying poultry pH for turkey). The fix: only inherit from rows the source authority explicitly published as category-wide claims (`category_level_rows.csv`).
- Fresh/cured are microbiologically distinct: 0.87–0.95 vs 0.99–1.0 aw for meat. Collapsing them into an envelope was non-conservative in the wrong direction for fresh meat (upper bound of the cured range is below the fresh range). Category membership should never imply property equality when state-subclasses exist.
- FoodEx2 uses `state="unspecified"` widely — for many entries it means "context-dependent" not "fresh". The `_apply_state_default` function encodes the assumption (unspecified → fresh for food safety grounding); surfacing it in `CategoryBridgeInfo.assumed_state` makes the assumption auditable.

**What to do differently:**
- When updating a test class that was testing old behavior (e.g., `TestBridgeAttemptedNoData`), check whether the test vehicle (lobster → shellfish) is still the right one. Shellfish changed from "has pH but no aw" to "has neither" — the test class name and docstring needed updating, not just the assertions.

---

### 2026-05-11 — Initial inoculum: required-field cascade and method-scoping pitfalls

**Context:** Added `initial_inoculum_log_cfu` throughout the pipeline: SemanticParser extraction, GroundingService step 7, StandardizationService `_get_initial_inoculum`, ComBase engine (`initial_log_cfu`/`final_log_cfu`), and API `PredictionResult`.

**What went well:**
- Attribute path disambiguation early. The Plan agent identified that the correct path is `model.defaults.inoculum` (on nested `ComBaseModelDefaults`), not `model.inoculum`. Verified by reading `models.py` before implementation — saved one round of silent wrong defaults.
- The three-priority resolution hierarchy (user value → model default from `DefaultInoc` → fallback 3.0) mirrors the existing pH/aw pattern exactly, making the implementation straightforward and the audit trail self-consistent.

**What surfaced repeatedly:**
- **Wrong method scope.** The inoculum grounding code was initially placed inside `_ground_environmental_conditions()`, which only receives `conditions: ExtractedEnvironmentalConditions` and `grounded` — `scenario` is not in scope. The IDE flagged "Could not find name `scenario`". Fix: move to `ground_scenario()` where `scenario` is in scope. Rule: when adding code that reads from `ExtractedScenario`, it must live in a method that receives the full scenario object.
- **Required field without default breaks all existing test fixtures at once.** `ComBaseParameters.initial_inoculum_log_cfu` is required (no Pydantic default). Every test file that constructed `ComBaseParameters` without the new field failed simultaneously — 20+ breakages across 5 files. Before making any field required, grep every constructor call in the test suite: `grep -r "ComBaseParameters(" tests/`. Fix all in one pass before running tests.
- **`model` variable scoped inside `if self._registry:` block.** `_get_initial_inoculum(grounded, result, model)` is called after the registry block, but `model` was only assigned inside it — `UnboundLocalError` on the no-registry path. Fix: hoist `model = None` before the `if` block. Same pattern as any optional-registry lookup.
- **`defaults_imputed == []` assertions break when a new universal default is added.** Two `TestBreadQueryEndToEnd` tests asserted `result.defaults_imputed == []`. Inoculum always adds a `DefaultImputed` event, so these assertions started failing. Fix: filter by field name — separate inoculum defaults from non-inoculum defaults and assert on each group independently. Lesson: `== []` assertions on audit lists are fragile; prefer field-filtered assertions that survive future additions.

**What to do differently:**
- When a new grounding step reads from `scenario`, check which method the code will live in and confirm `scenario` is actually in scope before writing.
- When a new Pydantic field is required (no default), always grep all constructors for that model across the entire codebase (tests and app) before running tests — not just the files you know about.
- When a test asserts `some_list == []`, consider whether it is asserting "nothing fired" or "this specific thing didn't fire." Prefer the latter when the list can grow with future features.

---

### 2026-05-14 — Category-level pathogen fallback: empirical verification before test assertions, spec-vs-data gaps

**Context:** Implemented a new fallback tier for organism grounding: when food-specific hazard lookup (Stages 1+2) yields no result, the pipeline now resolves food → `ptm_category` (FoodEx2 bridge) → IFT-2003-T1 categories → union of pathogens ranked by CDC annual deaths. Full audit provenance (`PathogenCategoryFallbackInfo`) is attached.

**What went well:**
- Empirical verification before writing integration test assertions prevented multiple wrong assertions. Bridge resolution scores, Stage 1 embedding scores, and exact death counts were all checked programmatically before any test was written. Tests that encode assumptions ("Campylobacter is skipped for dairy") were caught and corrected before they ran.
- The "fails closed at every step" design made the implementation simple: each early return preserves the existing ungrounded state rather than substituting a partial result. No special recovery code needed.
- Injecting lookup tables via constructor parameters (`ift_alignment`, `pathogen_associations`, `pathogen_characteristics`) made unit tests fully isolated — no filesystem reads, full control over ranking scenarios.

**What surfaced repeatedly:**
- **Spec proposed ptm_categories that don't exist in food_taxonomy.csv.** `sweetener`, `protein`, `dessert` appeared in the spec's alignment CSV proposal. Verifying against the actual CSV before creating the file prevented creating phantom categories that the bridge could never produce.
- **Test assertion assumed loop visits all candidates before selecting.** T2 (mascarpone) was supposed to demonstrate Campylobacter in `skipped_pathogens`. But Salmonella (238 deaths) ranks above Campylobacter (197 deaths) and maps successfully — the loop breaks at rank 1 and never reaches Campylobacter. `skipped_pathogens` only accumulates candidates that the loop *attempts and rejects*. Rule: verify ranking order empirically before asserting which candidates appear in `skipped_pathogens`.
- **Existing tests for old behavior break when the fallback replaces a former path.** `test_fallback_to_stage1_when_stage2_empty` tested a "fuzzy_match" path that was removed — Stage 2 empty now routes to the category fallback, not Stage 1 embedding. `TestDefaultOrganismFieldAudit` expected success=False for "chicken" and "rice", both of which the new fallback now resolves. Update tests to assert the new correct behavior rather than deleting them — the tests are still valid, just against the new path.
- **Recovery rate increase is empirically large.** Many queries that previously fell through to CONSERVATIVE_DEFAULT (e.g., bread → Salmonella default with no justification) now produce a `RAG_PATHOGEN_CATEGORY_FALLBACK` result with full provenance and a specific ranked selection. This is architecturally significant: the audit trail is now honest about *why* Salmonella was chosen, not just that a default was applied.

**What to do differently:**
- For any fallback that relies on ranked list traversal, verify the full ranking order (including exact death counts) before writing assertions about which candidates appear in `skipped_pathogens`. The skip list only contains *attempted failures*, not all non-winners.
- When implementing a new recovery tier, immediately identify which existing tests were testing the "no recovery" behavior and update them to assert the new successful-recovery path, documenting the food that was previously unresolvable.

---

### 2026-05-14 — Qualifier stripping: fix the input before fixing the fallback

**Context:** "a large batch of ham" failed the TaxonomyBridge fuzzy match (bridge returned None) because the quantity qualifier diluted the token similarity score below threshold 80. The category-level pathogen fallback couldn't fire. Root cause was upstream — the SemanticParser was passing the raw user phrasing rather than the core food noun.

**What went well:**
- The fix was one prompt section (14 lines) and no code changes. Regex post-processing would have required a separate normalization pass and would have broken multilingual queries.
- Verifying the bridge behavior empirically first (`bridge.resolve("large batch of ham") → None`, `bridge.resolve("ham") → meat`) confirmed the diagnosis before touching anything.

**What to do differently:**
- When a grounding fallback fails for a "known food", first check whether the food_description reaching the bridge is already a clean noun phrase. Bridge threshold failures for recognizable foods often indicate upstream qualifier noise rather than a taxonomy gap.

---

### 2026-05-15 — Two-tier food-property RAG collapse attempt and revert

**Context:** The food-property retrieval used a two-tier design: Tier 1 = `query_food_properties()` (combined pH+aw query at threshold 0.70, `RAG_RETRIEVAL`, `attributed_field=None`) followed by conditional per-field fallbacks at 0.62 (`RAG_RETRIEVAL_FALLBACK`, `attributed_field` set). Attempted to collapse to a single tier: both `query_food_ph()` and `query_food_water_activity()` firing unconditionally, both emitting `RAG_RETRIEVAL`, both with `attributed_field` always set. `query_food_properties()` and `RAG_RETRIEVAL_FALLBACK` would have been deleted. All phases (production code, tests, documentation) completed and tests passed. Live verification against Q03 bread confirmed an aw retrieval regression. All changes reverted; two-tier design restored.

**What went well:**
- The 0.62 threshold was already calibrated from the 2026-04-30 session against 13 known-good and 8 known-bad pairs. The calibrated value was already correct for per-field queries.
- Deleting the Priority 2 keyword heuristic from `translation.py` was structurally correct once all retrievals had `attributed_field` set. The heuristic removal was the right direction — the regression was not in routing but in retrieval quality.
- All four phases (production, tests, documentation, verification) were sequenced cleanly before the revert decision. Catching the regression via live verification rather than discovering it in production is the correct outcome.

**What surfaced: .env overrides need updating alongside setting field renames**

`settings.py` had two fields: `food_properties_confidence = 0.70` (uncalibrated primary) and `food_properties_fallback_confidence = 0.62` (calibrated). After renaming `food_properties_fallback_confidence` → `food_properties_confidence`, the `.env` file still had `FOOD_PROPERTIES_CONFIDENCE=0.70` — the old *primary* value. The rename caused the env var to now override the renamed field with the wrong value. The setting appeared to load correctly (no KeyError), but the threshold was silently 0.70. Rule: when renaming a settings field that uses env-var override, immediately grep the full set of env-var artefacts — not just `.env`. The complete checklist: `.env`, `.env.example`, `docker-compose*.yml`, CI workflow files (`.github/workflows/*.yml`), and any deployment/infra configs. `.env` fails fast (tests catch it immediately); the others fail slowly — only on a fresh checkout, in CI, or at deployment time. A single `grep -r OLD_VAR_NAME .` from the repo root catches all of them at once.

**What surfaced: threshold is stored on the response object, not forwarded to the vector store**

`RetrievalService.query()` consumes `threshold` internally (for `_classify_confidence()`) but does not forward it to `self._store.query()`. A test that tried to assert `call_args.args[3] == settings.food_properties_confidence` raised `IndexError`. The correct assertion is `response.threshold == settings.food_properties_confidence`. Before asserting on `call_args`, verify that the parameter you're checking actually reaches the underlying mock call.

**What surfaced: all test helper `RetrievalResult` objects must have `attributed_field` set after Priority 2 is deleted**

Three test helpers in `test_api_translation.py` created `RetrievalResult` objects without `attributed_field`. After deleting the Priority 2 heuristic, those helpers produced retrievals that no field's Priority 1 match could claim, returning `None` for `top_match`/`attempted_top`. Pattern: whenever a routing fallback is removed, immediately scan all test helpers for objects that relied on the fallback.

**Revert decision (2026-05-15):** Live testing on a sliced-bread query confirmed a regression. The per-field aw query retrieved bread crust (aw 0.3, wrong doc) over bread white (aw 0.94–0.97, correct doc) at embedding score 0.619 vs 0.596. The old Tier 1 combined query scored bread white at 0.756 — above the 0.70 threshold — extracting both pH and aw from the correct doc. The regression is structural: bread crust's aw-focused content (`"water activity 0.3. Dried bread crust"`) is semantically closer to the aw-specific query (`"white bread water activity aw moisture"`) than bread white's mixed-content doc. Not fixable by query-string tuning. Reverted to two-tier. Lesson: when a theoretical risk materialises on a real common food, revert to the proven design rather than speculating on fixes. The Tier 1 combined query threshold (0.70) was doing real protective work — the combined query retrieved the canonical full-property doc; the per-field query retrieved the most aw-relevant doc, which for bread happens to be a dry partial-data doc.

**What to do differently:**
- When renaming a settings field, grep the full set of env-var artefacts before closing the session — not just `.env`. A single `grep -r OLD_VAR_NAME .` from the repo root catches all of them at once.
- Before deleting a routing fallback, grep for every construction site of the object the fallback was designed to route, and verify each construction site sets the primary routing key (`attributed_field`). If it doesn't, add it before deleting the fallback.
- Before declaring a simplification correct, run retrieval spot-checks against common foods where the two designs would diverge — specifically foods whose best full-property doc and best single-property doc are different documents. The divergence is invisible to unit tests (which mock the store) and to integration tests that use the real store only against foods that happen to have a unique best doc for all fields.
