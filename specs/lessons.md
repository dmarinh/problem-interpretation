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

*End of lessons.md. Append future sessions below.*
