# PTM Backend — Lessons Learned

**Purpose:** Record durable lessons from PTM backend development that should inform future work. Companion to the frontend project's `lessons.md`. Append to this file as a session closes.

---

## Sessions

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
