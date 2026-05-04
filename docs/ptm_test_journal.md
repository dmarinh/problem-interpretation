# PTM Test Journal

**System under test:** Predictive Microbiology Translation Module (PTM)
**Build:** ptm 6d8aa38 (canonical for Q01-Q17 captures)
**Capture window:** 2026-04-29 through 2026-05-01
**Author/operator:** Daniel
**Companion:** model evaluator companion

---

## Purpose

The PTM Test Journal is the structured record of running PTM against a
representative set of natural-language food-safety queries, documenting
each query's behavior across all audit layers, and surfacing the
findings — pass, partial, fail, scope boundary — that emerge from the
captures.

The journal serves four objectives equally:

1. **Test system capabilities.** Each query exercises one or more
   heuristics from the system's design (USER_EXPLICIT extraction, RAG
   retrieval, rule-matched values, embedding fallback, range
   selection, range clamping, conservative defaults, pathogen
   inference, multi-step prediction). The journal verifies which
   heuristics fire and whether they fire correctly.
2. **Detect bugs and architectural gaps.** Six bugs were discovered
   and closed during journal capture, all surfaced by reading audit
   JSON for queries that succeeded or failed in surprising ways. The
   journal continues to surface gaps in followups.
3. **Demonstrate to a technical audience.** The journal is the source
   from which the demo subset is selected. Each entry is intended to
   stand alone as evidence of system behavior under realistic
   conditions.
4. **Drive subsequent work.** Findings flow into Session 2 (RAG
   retrieval calibration), the thermal-inactivation prediction
   investigation, and a roadmap of audit-shape consistency items.

The journal is **not** a comprehensive test suite (that role belongs
to the unit and integration tests). It is **not** a benchmarking
exercise (that role belongs to Session 2's calibration experiment).
It is a structured record of representative behaviors that no test
suite would have captured at this density, and that no automated
benchmark would have surfaced as findings rather than metrics.

---

## What the journal is *not*

A few scope boundaries surfaced during capture that are explicit and
intentional:

**PTM predicts growth, not safety.** A user asking "is this food safe
to eat?" gets a growth prediction with full provenance, not a yes/no
verdict. Safety interpretation (translating predicted log-increase
into actionable verdicts using infectious-dose, the FDA 2-hour rule,
etc.) is the scope of a planned downstream project. Q11 surfaces this
boundary explicitly.

**PTM is a forward predictor.** Given (food, conditions, duration), it
predicts growth. Given (food, conditions, target growth), it does not
predict duration — there is no inverse-evaluation path. Q13 surfaces
this boundary; Q14 confirms the same architectural decision applies
even when the user simply omits duration without asking for it.
Duration is the integration variable; no "conservative default
duration" is honest in the way conservative defaults work for
parameters like pH or aw.

**PTM is grounded in ComBase models for a small set of organisms.**
Salmonella, B. cereus, Listeria, C. perfringens, E. coli, plus one
thermal-inactivation model (Salmonella) tested in this journal. Other
organisms or model types may exist in the implementation but are not
exercised by Q01-Q17.

---

## Conventions

### Entry format

Each query entry follows this structure:

```
## Q## — Title

### Goal
What the query is designed to test. Heuristics exercised. Demo intent.

### Query
The exact natural-language query as sent.

### Expected
What the system should produce, per the design contract.

### Actual (timestamp UTC, ptm version, verbose=true)
What the system actually produced. Field-by-field.

### Findings
The narrative interpretation of what the capture means: passes, the
shape of any failures, audit-honesty observations, demo-relevance
notes, comparative observations across captures.

### Conclusion
One-line status with rationale.

### Followups
Open items surfaced by this entry. Each carries a status icon and a
brief description.
```

### Status icons

- ✅ — Closed; the design intent was met or the issue was resolved
  during journal capture.
- 🟡 — Open; partial or non-blocking finding worth tracking.
- 🔴 — Open and consequential; affects demo or production behavior in
  a meaningful way.
- ✓ — Closed item from a prior session or upstream concern.

### Capture protocol

Every capture used:
- `verbose=true` (full audit JSON returned)
- ptm version recorded (almost all on `6d8aa38`)
- UTC timestamp recorded
- The full JSON paste preserved as the source of record

When a backend fix landed mid-journal, the affected entries were
re-captured against the post-fix build. The journal entries describe
both the pre-fix and post-fix behavior where this happened (notably
Q06, Q15, Q16).

---

## Quick index

| ID | Query (one-line) | Heuristic surface | Status |
|---|---|---|---|
| Q01 | B. cereus, all explicit | USER_EXPLICIT direct, all 5 fields | ✅ |
| Q02 | Salmonella on chicken, aw user-explicit | RAG single-field, Tier 1 fragility | ✅ |
| Q03 | Bread + B. cereus 25°C/4h | Multi-source citation | ✅ |
| Q04 | "Worst-case pathogen on raw chicken" | §2.4 + Tier 2 fallback + reranker_top | ✅ |
| Q05 | Bread "room temperature" | rule_match temperature | ✅ |
| Q06 | "Cooked rice sitting out for a while" | rule_match T+t, §2.4 deaths-ranking | ✅ post-fix |
| Q07 | Bread "sunny windowsill" | embedding_fallback | ✅ |
| Q08 | "Cooked chicken 65°C/10min — enough?" | thermal_inactivation, range_bound_selection lower | 🔴 prediction broken |
| Q09 | E. coli milk 50°C/6h | range_clamp on USER_EXPLICIT + KB ambiguity | ✅ |
| Q10 | Listeria cheese 4°C/14d | refrigeration-edge + long-duration + cultivar mismatch | ✅ |
| Q11 | "Was chicken left overnight at room temp safe?" | parser stress test, scope boundary | ✅ |
| Q12 | Bread, no pathogen specified | §2.4 fall-through to default | ✅ |
| Q13 | "How long until 3-log growth?" | Inverse-query failure mode | ✅ |
| Q14 | Salmonella chicken w/o duration (case study) | Missing-duration semantics | ✅ design Q open |
| Q15 | "zarblax burger" (fictional) | attempted_top + double default | ✅ post-fix |
| Q16 | "pH 5.5–6.0" user range | User-supplied range_bound_selection | ✅ post-fix |
| Q17 | "Chicken 4°C 24h then truck 13°C 6h" | Multi-step prediction | ✅ |

Status legend: ✅ pass, 🟡 partial, 🔴 fail, ✓ closed.

---

## Reading guide

The journal can be read in three modes:

**Cover-to-cover.** Q01 through Q17 in order, plus front and back
matter. ~3-4 hours to read carefully. Recommended for someone who
wants to understand both the system's behavior and the way the journal
was built.

**Demo selection only.** The demo subset is a separate document that
extracts 5-7 entries from this journal. If your goal is the
presentation, read the demo subset; the full journal is reference.

**Specific concern.** The cross-cutting findings section (back matter)
is the index for finding entries by theme: audit-honesty work, Tier 1
fragility, range_clamp into below-threshold conditions, failure-path
audit shape, etc. Each cross-cutting finding cites the queries where
it was observed; from there, individual entries.

The journal's followups section consolidates open work items in
priority order, decoupled from the per-entry sections. If your concern
is "what still needs doing before the demo," that's where to start.

---

# Cross-cutting findings

The journal's per-entry findings are the proximate observations. The
cross-cutting findings are themes that emerged across multiple
entries — patterns the journal surfaced by repetition rather than by
single capture.

## Audit-honesty thread (5 instances, 4 closed)

The single largest theme of the journal. The system's audit shape is
designed to make every value's provenance traceable: which retrieval
produced this value, which rule extracted that one, which default
imputed the third. Audit-honesty is the design contract that makes
the rest of the system trustworthy.

Five times during journal capture, a sharp reading of the audit
surfaced an inconsistency where the audit reported one thing but the
system actually did another. Four of those have closed. One remains
open as a separate small item.

**1. Organism field's retrieval block showed wrong retrieval. ✅**
Surfaced by Q06 post-fix. The audit's `field_audit.organism.retrieval`
reported the *pH retrieval* (food_properties_220, "rice white cooked,
pH range 6.0 to 6.7") as if it were the pathogen retrieval that drove
the §2.4 deaths-ranking selection. Cause: audit-routing Priority 2
heuristic was substring-matching `"pathogen"` on query content; the
prior Q06 fix had changed the pathogen query template from `"{food}
pathogen bacteria hazard contamination"` to `"{food} food hazard"`,
breaking the substring match. Fix: structural `attributed_field` on
the retrieval response, Priority 1 routing, independent of query
string content. One-line fix at grounding_service.py:823.

**Lesson recorded:** *audit routing should use structural field
handles (e.g. attributed_field), never substring matching on query
strings.* Generalizable to any future audit-routing work.

**2. reranker_top under-threshold doc not surfaced. ✓ pre-journal**
The audit was reporting `top_match` as the rerank-top doc (post-rerank
ordering) but extraction was using `top_result` (gate-passed doc). When
the cross-encoder promoted a wrong-field doc above field-relevant ones,
the audit silently absorbed the disagreement. Fix: distinct
`reranker_top` and `attempted_top` audit fields, with `skip_reason`.
Three audit shapes now distinct.

**3. attempted_top did not populate for fictional foods. ✅**
Surfaced by Q15. The `attempted_top` field is populated when retrieval
runs and yields candidates that fail threshold. For "zarblax burger,"
RAG ran correctly through both Tier 1 and Tier 2, all candidates failed
threshold (rerank scores down to -8.59 — actively bad matches), but the
audit showed `retrieval: null` rather than the populated empty-result
shape. Cause: defaulted-fields audit-population path didn't look up
`grounded.retrievals` for matching attempts; the retrieval data was
correctly built but orphaned from the audit entry. Fix: lookup by
`attributed_field` (mirroring the organism fix's pattern), 6 new
regression tests in `test_api_translation.py`. Three audit shapes now
unambiguous: `retrieval: null` (no retrieval needed) vs `retrieval: {
top_match: null, attempted_top: {...} }` (RAG attempted, all failed)
vs `retrieval: { top_match: {...} }` (RAG succeeded).

**4. User-supplied ranges silently flattened to lower bound. ✅**
Surfaced by Q16. Query `"pH 5.5–6.0"` produced `final_value: 5.5` with
no parsed_range, no range_bound_selection event, no record of "6.0"
ever existing. Cause: schema gap (`ExtractedEnvironmentalConditions`
had `ph_value: float | None` but no range fields), prompt gap (LLM had
nowhere to put both numbers), and consequent grounding gap (user-
supplied path never set `range_pending=True`). Fix: symmetric three-
touch-point change — schema fields, prompt instruction, grounding
routing through `range_bound_selection`. Post-fix audit for user
ranges is structurally identical to RAG-supplied ranges (Q03 pattern).

**Lesson recorded:** *symmetric paths to the same destination should
converge at the right point.* Generalizable beyond ranges.

**5. rule_match `matched_pattern` records canonical, not original. 🟡**
The only open audit-honesty thread. Surfaced by Q06: the query said
"sitting out" but `matched_pattern` recorded "room temperature" (the
canonical rule key). Q07 confirmed the audit fields support the
distinction (embedding_fallback correctly records original phrase in
matched_pattern and canonical in canonical_phrase). Fix is mechanical:
align rule_match's audit population with embedding_fallback's
convention. Same principle as the user-supplied-range fix; same shape
of work; smaller scope.

### Why this thread matters

Three of the five fixes were caused by *adjacent code changes*: a fix
in one place (Q06's pathogen retrieval template) broke an audit
routing assumption in another (the substring-match heuristic). A
schema extension for one input source (RAG ranges) silently excluded
another (user ranges). The underlying pattern: when two paths share a
destination, intentional convergence at the right point is more
robust than incidental alignment via brittle proxies (substrings,
existence-of-fields, position).

The journal surfaces these because audit reading at the JSON level is
unforgiving: a sharp reader notices when extraction.method says
"ranked_by_annual_deaths" but the retrieval block points at a pH doc.
Tests typically check field values, not field-to-retrieval
correspondence; audit-routing bugs slip past tests and surface in
journal captures.

A small structural test — *for every field with retrieval populated,
verify that the retrieval block content matches the field's
extraction source* — would catch this whole class going forward.
Filed as a Session 2 spinoff or pre-demo work item.

## Tier 1 / Tier 2 / pathogen-hazards thresholds: three uncalibrated values

Three retrieval thresholds gate the system's RAG behavior. All three
are derived ad hoc and remain uncalibrated.

- `food_properties_confidence: 0.70` (Tier 1 — primary food properties
  retrieval)
- `food_properties_fallback_confidence: 0.62` (Tier 2 — per-field
  fallback)
- `pathogen_hazards_confidence: 0.75` (§2.4 pathogen inference Stage 1)

Across the journal, **Tier 1 fired correctly on cheese (Q10) and bread
(Q03/Q05/Q07/Q12/Q15-pre), but failed on chicken (Q02/Q04/Q08/Q11/
Q13/Q17), milk (Q09), and rice (Q06)**. The pattern:

- **Generic single-word food names ("chicken", "milk")** consistently
  drop below the 0.70 gate. Embedding scores hover at 0.65-0.69 against
  their actual KB entries.
- **Multi-word qualified names ("white bread", "cheese parmesan", "raw
  chicken")** pass Tier 1 cleanly. Embedding scores at 0.75-0.80.
- **Cooked rice (Q06)** is at 0.72 — Tier 1 passes marginally, but the
  reranker promotes a wrong-field doc (uncooked rice aw) above the
  pH-relevant doc, triggering a different failure mode (cross-encoder
  field mismatch).

This is the **dominant retrieval mode for non-descriptor queries**, not
an edge case. Whatever Session 2's calibration produces, it should
explain *why* one single-word name passes and another fails, not just
pick a number that splits them. Otherwise the fix is per-food-name
calibration, which doesn't generalize.

Folded into Session 2's calibration experiment as a primary scope item.

## Cross-encoder field-mismatch and food-cultivar mismatch

Two related but separable failure modes for the cross-encoder reranker:

**Field-mismatch promotion** (Q04, Q06): the cross-encoder promotes a
doc whose primary content is a *different field* than the query
intends. Example: for a pH query, promotes a water_activity doc above
a pH doc. The `reranker_top` audit field surfaces this directly —
reranker promoted a doc that the embedding gate then rejected. Visible
class.

**Food-cultivar mismatch** (Q09, Q10): the cross-encoder confidently
ranks a wrong-cultivar doc above the right-cultivar doc, both of
which pass the gate. Example: for "milk" without qualifier, ranks
`milk acidophilus` (pH 4.09-4.25, fermented) above `milk evaporated`
(pH 5.9-6.3) and far above any baseline ordinary-milk entry (which
doesn't exist in the KB). Both docs pass the embedding threshold;
both rerank highly; the cross-encoder picks the lexically similar but
scientifically wrong cultivar. **Silent class** — invisible without
ground truth.

Q06 pre-fix combined both modes plus Tier 1 fragility plus a vocabulary
asymmetry — four overlapping failures in one query, each surfaced and
diagnosed separately.

For Session 2's calibration: the metric set should distinguish visible
field-mismatch (where reranker_top fires) from silent food-cultivar
mismatch (where the audit looks fine but ground truth disagrees).
Suggested labels: `correct`, `acceptable_fallback`, `wrong_cultivar`,
`wrong_state`, `wrong`. The middle three are all "high-confidence
retrieval per the audit" but represent different KB problems.

## Range_clamp into model boundary from below-threshold conditions

A quieter cross-cutting finding, surfaced by three captures: when a
user-supplied or retrieved value is *below the threshold for the
modeled phenomenon to occur at all*, range_clamp pushes it to the
model boundary and the model produces a small but non-zero growth
prediction. The audit is honest (clamp recorded, warning issued); the
prediction value misrepresents the science.

**Q06**: cooked rice aw retrieved as dry-rice aw [0.8, 0.87], clamped
to C. perfringens floor 0.971. Real cooked rice aw is sufficient for
growth; the wrong-physical-state retrieval forced the clamp. (KB
content gap.)

**Q10**: parmesan cheese aw [0.68, 0.76] correctly retrieved, clamped
to Listeria floor 0.934. Parmesan at aw 0.76 is *well below* where
Listeria can grow at all; clamp produces ~0.7 log growth over 14
days, science says no growth. (Model boundary issue.)

**Q17 step 1**: Salmonella temperature 4°C clamped to growth model
floor 7°C. Salmonella's biological growth threshold is ~5°C; at 4°C,
no growth occurs. Clamp produces step 1 contribution of 0.315 log
increase that shouldn't really exist. (Model boundary issue, multi-
step variant.)

The Q06 case has a clean fix path (add a cooked-rice aw KB entry).
Q10 and Q17 are the harder cases: the KB is right, the retrieval is
right, the math at the boundary is what the model produces — but the
prediction value is not what a microbiologist would say.

A stronger warning at this kind of boundary would help: "The clamped
value sits at the model's minimum for [phenomenon]; the original
value implies the modeled phenomenon does not occur. Treat the
prediction as model-faithful but science-divergent." Filed as a
single consolidated followup rather than three per-query items.

## Failure-path audit shape inconsistencies

Three captures (Q13, Q14, Q17-pre-recapture) confirm a small but
consistent pattern in the failure response shape:

- `field_audit.organism.final_value` uses internal id `"ss"`, not the
  display name `"Salmonellae"`.
- `audit.combase_model` is null.
- `audit.system` is null (no ptm_version, no manifest stamping).

The success path populates all three correctly. The failure path skips
display-name resolution, model selection, and manifest stamping —
honest about the failure point, but a frontend rendering a partial
response can't display the system manifest or the human-readable
organism name. Three captures of the same shape; not a one-off.

A small audit-shape consistency fix (populate display name and manifest
on failure responses) would close this. Low priority; non-blocking for
demo if the demo doesn't include failed queries (Q13, Q14, Q17-pre are
all in the journal but not the demo subset).

## KB content gaps surfaced by retrieval

Two cooked-vs-raw / cultivar gaps where retrieval succeeded by lexical
similarity but produced a scientifically wrong food selection:

- **Cooked rice aw** (Q06): no entry exists for cooked-rice water
  activity. Tier 2 fallback retrieved uncooked-rice aw, which is
  physically wrong for cooked rice (cooked is much wetter).
- **Ordinary fluid milk** (Q09): no entry exists for plain milk's pH.
  Tier 2 retrieved milk acidophilus (fermented, pH ~4) instead of any
  baseline milk reference.

Both gaps produce honest warnings via range_clamp + the warning
infrastructure, but the underlying issue is content, not retrieval
calibration. Filed as KB content work, separate from the schema
migration that's in flight in another session.

## Heuristic coverage summary

After Q01-Q17, every documented heuristic in the system's design has
been exercised at least once:

- USER_EXPLICIT direct extraction: Q01 (all fields), Q02/Q08/Q09/Q11
  (subsets), Q14 (failure variant)
- Rule-based extraction (temperature): Q05, Q06, Q07, Q11
- Rule-based extraction (duration): Q06, Q11
- Embedding fallback (temperature): Q07
- RAG retrieval Tier 1 (food properties): Q03, Q05, Q07, Q10, Q12, Q15
- RAG retrieval Tier 2 (food properties fallback): Q02, Q04, Q06, Q08,
  Q09, Q11, Q13, Q17
- §2.4 pathogen inference (deaths-ranking): Q04, Q06 post-fix, Q11,
  Q13, Q17
- §2.4 fall-through to CONSERVATIVE_DEFAULT: Q12, Q15
- range_bound_selection upper (growth): Q03, Q04, Q05, Q06, Q07, Q10,
  Q11, Q12, Q15-pre, Q16, Q17
- range_bound_selection lower (thermal_inactivation): Q08
- range_clamp on RAG-retrieved value: Q06, Q08, Q10, Q12
- range_clamp on USER_EXPLICIT value: Q09, Q17
- CONSERVATIVE_DEFAULT (organism): Q12, Q15
- CONSERVATIVE_DEFAULT (pH/aw): Q07-supplementary (tropical climate),
  Q11, Q12, Q14, Q15
- attempted_top (fictional food): Q15 post-fix
- Multi-source citation: Q03 (bread), Q10 (cheese parmesan), Q12 (bread)
- Multi-step prediction: Q17

Two heuristics in the design but not exercised by Q01-Q17:

- Cumulative bias warning (§11.1) at ≥3 conservative defaults: not yet
  implemented; reachable by query design but not captured.
- Inverse-query support: not implemented; PTM is forward-only.

---

# Open followups

Priority-ordered, drawn from per-entry followups. Each item names the
queries that surface it, the scope, and a recommendation.

## High priority — affects demo

**🔴 Thermal-inactivation prediction blow-up at temperature boundary.**
Q08. At T=65°C (model max), the polynomial evaluation produces μ_max =
-1931 and log_increase = -321.9 — a 50+ orders-of-magnitude error.
Q09 and Q17 confirm growth-model evaluation at boundary works
correctly, narrowing the bug to thermal-inactivation-specific causes
(unit handling, sign/formula error, or polynomial extrapolation).
Active investigation in flight.

Recommendation: investigate before demo. If unfixable in time, scope
the demo around in-range thermal queries (e.g. T=58°C) and frame Q08
as evidence of audit working correctly even when math is broken.

## Medium priority — closable before demo

**🟡 rule_match `matched_pattern` records canonical, not original.**
Q06 (surfacing), Q07 (positive evidence the audit fields support it).
Same fix pattern as Q16's user-range fix (extend the data structure,
populate honestly, mirror the embedding_fallback convention). Half-day
work. Fourth audit-honesty thread item; closing this completes the
audit-honesty narrative in the demo.

**🟡 Audit-shape consistency on failure path.** Q13, Q14, Q17-pre. Three
captures show: organism uses internal id; combase_model and system are
null. Small fix: populate display name and manifest stamping on failure
responses.

## Lower priority — defer past MVP if needed

**🟡 Stronger warning when range_clamp produces science-divergent
prediction.** Q06, Q10, Q17 (consolidated). When clamp moves a value
into the model's valid range *from* a value that implies the modeled
phenomenon doesn't occur, the warning should distinguish "model
boundary" from "below where modeling applies at all." Defense-in-depth
against misreading the prediction.

**🟡 KB content: ordinary fluid milk pH baseline; cooked rice aw entry.**
Q06, Q09. Both surfaced by retrieval succeeding via lexical similarity
to wrong-cultivar/wrong-state docs. Fix is data, not architecture.

**🟡 Multi-step audit shape inconsistencies.** Q17. Top-level
`temperature_celsius` is step-1 only; `duration_minutes` is aggregate.
Step identity in `range_clamps[]` is string-encoded ("(step 1)") rather
than structured. Document or reconcile.

**🟡 aw monotonicity at boundary.** Q04, Q11, Q17. Salmonella μ_max
peaks near aw 0.99; range_bound_selection upper picks 1.0, which gives
a slightly *less* conservative prediction than 0.99 default would. The
"upper bound = more conservative for growth" heuristic is approximate
at the aw boundary. Pre-existing; not surfaced by any new query.

**🟡 Tier 1 best-rejected candidate not surfaced when both tiers fail.**
Q15. When Tier 2's `attempted_top` populates, Tier 1's best-rejected
candidate (which may have been near-miss) is invisible. Audit
completeness item; low priority.

**🟡 Cumulative bias warning (§11.1) unimplemented.** Reachable only
with new query design (≥3 defaulted fields). Not in current heuristic
coverage; defer.

**🟡 Pathogen retrieval fall-through to pathogen_food_associations.csv.**
Q12. Bread isn't in food_pathogen_hazards.csv; §2.4 falls through to
CONSERVATIVE_DEFAULT Salmonella. The associations CSV has cereal-grains
entries (Salmonella, Staph, B. cereus, C. botulinum) that go unused.
Architecture question: should §2.4 consult associations as a secondary
fallback? The associations CSV lacks deaths counts, so a different
ranking heuristic would be needed. Defer.

**🟡 Partial-multi-step support.** Q17-pre. User provided enough info
to predict step 2 alone but not step 1. System fails closed entirely.
Architecturally, a "partial scenario" mode that runs step 2 with a
warning would be more useful for real-world food-safety scenarios.
Defer past MVP; design call.

**🟡 Inverse-query support.** Q13. PTM is forward-only by design;
inverse queries (target growth → predict duration) are out of scope.
The "3 logs" target in Q13's query is silently dropped. If inverse
queries become in-scope post-MVP, the parser needs a new
`target_growth_log_increase` field and the orchestrator needs an
inverse-evaluation path.

---

# Inputs to other sessions

## Session 2 (RAG retrieval calibration)

The journal accumulated multiple inputs to Session 2's calibration
experiment. Consolidated:

1. **Three uncalibrated thresholds.** Tier 1 (0.70), Tier 2 (0.62),
   pathogen_hazards (0.75). All three should be primary calibration
   targets.
2. **Query-template robustness as an axis.** The Q06 root cause was
   vocabulary asymmetry across documents in the same type. Tier 1's
   query template "{food} pH water activity properties" likely has
   the same fragility. Recommended: test query-template variation as a
   configurable axis alongside threshold and embedder.
3. **Cross-encoder failure-mode classification.** Field-mismatch
   (visible via `reranker_top`) vs food-cultivar mismatch (silent,
   detectable only with ground truth). Suggested ground-truth labels:
   correct / acceptable_fallback / wrong_cultivar / wrong_state /
   wrong. Stratify reranker accuracy by failure type.
4. **Tier 1 fragility on generic food names** is dominant, not edge
   case. Three foods consistently below threshold (chicken, milk, rice
   marginal); two foods consistently above (bread, cheese). The
   experiment should explain *why* one single-word name passes and
   another fails, not just pick a threshold that splits them.
5. **Audit-routing structural test.** "For every field with retrieval
   populated, the retrieval block content matches the field's
   extraction source." Catches the audit-routing class of bug
   directly. Scope into Session 2 if cheap, otherwise file as a
   separate small piece of work.
6. **Wrong-physical-state retrieval as failure mode.** Q06 cooked
   rice → uncooked rice aw. KB content gap distinct from threshold
   calibration but affects metric design.

## Thermal-inactivation prediction investigation

The Q08 finding spawned its own Claude Code session. Q09 and Q17
provide cross-reference data: growth-model evaluation at boundary
produces sensible predictions. The bug is thermal-inactivation
specific.

## Frontend Zod schema alignment

Just landed. The frontend's Zod schemas are now aligned with the
audit shapes documented through Q01-Q17. Five Zod errors on a live
bread capture have been resolved across schemas.ts and
AuditChecks.tsx (new RangeClampCategory component for structured
range_clamps[]).

## CSV schema migration (per-field source attribution)

A separate working session is in flight for `food_properties.csv` to
support per-field source attribution (currently single source_id per
row, with multi-source rows hiding secondary source in notes). Not
journal-blocking; runs in parallel.

---

# Body — query entries Q01 to Q17

The 17 query entries follow in numbered order. Each stands alone but
cross-references where relevant.

> **Note on Q01-Q05.** These entries were captured early in the
> journal's working session, before the assembly's reconstruction
> window. The text is derived from the journal's session-state
> summary and may be terser than Q06-Q17 where the full prose was
> developed during the reconstruction window. Replace with the
> original full-text entries if available in your local copy.

---

## Q01 — Bacillus cereus, all conditions explicit

### Goal
Baseline test: every input USER_EXPLICIT, no retrievals, no rules, no
defaults. Tests the simplest possible path through the system — direct
extraction for all five fields.

### Query
> "Predict Bacillus cereus growth at 25 C, pH 6.0, water activity 0.95, for 4 hours."

### Expected
- All five fields USER_EXPLICIT, extraction.method = "direct"
- No retrievals, no rules, no defaults, no clamps
- Sensible growth prediction for B. cereus at the given conditions

### Actual
- Five fields USER_EXPLICIT direct
- range_clamps, defaults_imputed, warnings all empty
- Prediction: small log_increase consistent with B. cereus at 25 C pH 6.0 aw 0.95 over 4 h

### Findings
The simplest possible path through the system, end to end. Useful baseline against which Q15 (fictional food, same conditions, two defaults) demonstrates the cost of conservative defaults: same B. cereus / 25 C / 4 h, but Q01's realistic pH and aw produce a far smaller predicted growth than Q15's defaults of pH 7.0 and aw 0.99.

### Conclusion
Pass.

### Followups
None.

---

## Q02 — Salmonella on chicken, aw user-explicit

### Goal
Test single-field RAG retrieval (pH for chicken) with one other field user-supplied (aw). Surfaces the priority ordering between USER_EXPLICIT and RAG_RETRIEVAL.

### Query
> "Predict Salmonella growth on chicken at 25 C, water activity 0.99, for 4 hours."

### Expected
- pH retrieved from chicken row (Tier 1 expected)
- aw USER_EXPLICIT
- Salmonella, T, duration USER_EXPLICIT
- Sensible growth prediction

### Actual
- pH = 6.4 from rag_retrieval_fallback (Tier 2, not Tier 1)
- aw = 0.99 USER_EXPLICIT
- Salmonella, T, duration USER_EXPLICIT
- range_bound_selection upper [6.2, 6.4]
- Prediction sensible

### Findings
USER_EXPLICIT takes priority over RAG retrieval cleanly: the user's aw 0.99 is preserved and not overridden by any retrieved range. Priority ordering works as designed.

The unexpected observation: chicken's pH retrieval went through Tier 2, not Tier 1. The query string "chicken pH water activity properties" failed the 0.70 embedding gate. Tier 2's per-field "chicken pH acidity" query passed the 0.62 gate. This is the first instance of the Tier 1 fragility pattern that recurs throughout the journal — generic single-word food names consistently drop below the Tier 1 threshold. See cross-cutting findings.

### Conclusion
Pass with finding: Tier 1 fragility on "chicken" surfaces here; folded into Session 2.

### Followups
- Tier 1 fragility on generic food names (folded into Session 2 calibration scope)

---

## Q03 — Bread + B. cereus 25 C / 4 h

### Goal
Tests multi-source citation. Bread's row in food_properties.csv has both pH and aw populated, with two separate source IDs (FDA-PH-2007 for pH, IFT-2003-T31 for aw). The §8.11 ingestion-layer notes-parsing extracts both source IDs into the per-field citations. Tests that both citations appear in the audit's full_citations block.

### Query
> "A slice of white bread was kept at 25 C for 4 hours. Predict Bacillus cereus growth."

### Expected
- pH and aw both retrieved from doc 211 (bread white)
- range_bound_selection upper for both (growth)
- Both source IDs populated in full_citations
- T, duration USER_EXPLICIT; B. cereus USER_EXPLICIT

### Actual
- pH = 6.2 RAG_RETRIEVAL, parsed_range [5.0, 6.2], range_bound_selection upper
- aw = 0.97 RAG_RETRIEVAL, parsed_range [0.94, 0.97], range_bound_selection upper
- Both retrievals point at doc 211; both have source_ids and full_citations populated for FDA-PH-2007 and IFT-2003-T31

### Findings
Multi-source citation works as designed. The audit cleanly surfaces both source IDs alongside both fields, with the full citation text for each. Demonstrates the §8.11 ingestion-layer parsing behavior in production output.

The retrieval is also a clean Tier 1 case (embed 0.79, rerank 6.22) — "white bread" qualifies the food name enough to clear the 0.70 gate, in contrast to the bare "chicken" / "milk" / "rice" pattern that surfaces in Q02, Q06, Q09.

### Conclusion
Pass.

### Followups
None.

---

## Q04 — "Worst-case pathogen growth on raw chicken"

### Goal
Tests §2.4 pathogen inference: when no organism is specified, the system runs Stage 1 retrieval against food_pathogen_hazards, Stage 2 ranks by annual_deaths_us. For chicken, Salmonella (238 deaths) wins over Campylobacter (197) and Listeria (172). Also tests Tier 2 fallback for chicken pH (per Q02), and the reranker_top audit field surfacing a cross-encoder field-mismatch promotion.

### Query
> "What's the worst-case pathogen growth on raw chicken left at 25 C for 4 hours?"

### Expected
- pH RAG (Tier 2 expected for chicken)
- aw RAG (Tier 2 expected — chicken row's aw field is blank)
- §2.4 fires, Salmonella selected by deaths-ranking
- T, duration USER_EXPLICIT

### Actual
- pH Tier 2 fallback ("chicken pH acidity") passes
- aw Tier 2 fallback to fresh poultry doc (range [0.99, 1.0], upper bound 1.0)
- organism = Salmonella, source = rag_retrieval, extraction.method = ranked_by_annual_deaths
- §2.4 audit shape: retrieval block populated with pathogen_hazards_370 (Salmonella primary hazard), runners_up showing Campylobacter and Listeria
- reranker_top fires on the aw retrieval: cross-encoder promoted a doc that the embedding gate rejected

### Findings
§2.4 deaths-ranking works cleanly for chicken. The audit transparently shows the deaths-ranking step: which doc ranked first, which were runners-up, what method was used for the final selection.

reranker_top surfaces a cross-encoder field-mismatch — for the aw retrieval, the cross-encoder promoted a doc that the embedding score then rejected. The audit field exists specifically to expose this kind of disagreement; this is the first capture where it fires. See cross-cutting findings on cross-encoder failure modes.

aw monotonicity is interesting at the boundary: range_bound_selection upper picks 1.0, but the Salmonella growth model peaks near 0.99, so 1.0 gives a slightly less-conservative prediction than the default 0.99 would. The "upper = more conservative for growth" heuristic is approximate at the boundary.

### Conclusion
Pass.

### Followups
- aw monotonicity at boundary (Salmonella peaks ~0.99, dips at 1.0) — heuristic approximation, low priority
- Tier 1 fragility on "chicken" (folded into Session 2)

---

## Q05 — Bread "room temperature"

### Goal
Tests rule-based temperature extraction. The rule registry maps phrases like "room temperature" to canonical values (25 C). Tests that the audit records the matched_pattern, the conservative flag, and the user_inferred source.

### Query
> "Predict Bacillus cereus growth on white bread at room temperature for 4 hours."

### Expected
- T = 25 USER_INFERRED, rule_match on "room temperature"
- pH, aw RAG retrieval on bread
- B. cereus, duration USER_EXPLICIT

### Actual
- T = 25, source = user_inferred, extraction.method = rule_match, matched_pattern = "room temperature", conservative = true
- pH = 6.2 RAG_RETRIEVAL upper bound from bread doc 211
- aw = 0.97 RAG_RETRIEVAL upper bound

### Findings
Rule-based temperature extraction works. The matched_pattern matches the user's exact phrasing here ("room temperature" appears verbatim in the query and is a registered rule key). The audit surfaces the conservative flag, indicating the system picked the upper bound of the 20-25 C range associated with the rule.

The matched_pattern audit-honesty issue (audit records canonical, not original) does not surface here because the user's phrase happens to be the canonical phrase. It surfaces in Q06 where the user phrases "sitting out" maps to canonical "room temperature."

### Conclusion
Pass.

### Followups
None directly; Q06 surfaces the audit-honesty thread on rule_match.

---

## Q06 — Cooked rice sitting out / pathogen growth

### Goal
Tests rule-based extraction for both temperature ("sitting out") and duration ("a while"), plus pathogen inference fall-through when no organism is specified. Designed as a deaths-ranking diagnostic: food_pathogen_hazards.csv has rice with B. cereus (rare CFR, 0 deaths) and C. perfringens (<1% CFR, 41 deaths). Expected: §2.4 deaths-ranking selects C. perfringens. (Pre-fix: §2.4 didn't fire — see Followups for the investigation that closed this.)

### Query
> "Cooked rice was sitting out for a while. Predict pathogen growth."

### Expected (post-fix to query_pathogen_hazards)
- T → user_inferred via rule, ~25 C
- duration → user_inferred via rule on "a while", ~60 min
- pH → RAG retrieval on cooked rice (food_properties_220, 6.0–6.7), upper = 6.7
- aw → Tier 2 fallback, retrieves dry-rice aw, clamped to model floor
- organism → §2.4 deaths-ranking → Clostridium perfringens (41 deaths > B. cereus 0 deaths)
- range_clamps[1], defaults_imputed[0], warnings[1]

### Actual (2026-05-01 14:20 UTC, ptm 6d8aa38, verbose=true, post-fix)
- T = 25.0 USER_INFERRED, rule_match
- duration = 60 USER_INFERRED, rule_match on "a while"
- pH = 6.7 RAG_RETRIEVAL, doc 220, range_bound_selection upper [6.0, 6.7]
- aw = 0.971 rag_retrieval_fallback, retrieved [0.8, 0.87] from doc 229 (uncooked rice), clamped to model floor (C. perfringens valid_ranges [0.971, 1])
- organism = Clostridium perfringens, source = rag_retrieval, extraction.method = "ranked_by_annual_deaths"
- pH retrieval has reranker_top: doc 229 promoted (rerank 3.93) but failed gate (embed 0.6373 < 0.70), walked to doc 220
- range_clamps[1], defaults_imputed[0], warnings[1]
- system block: 5/5 ✅
- μ_max = 0.267, log_increase = 0.116 ("minimal growth, <2× population")

### Findings

**§2.4 deaths-ranking works as designed on rice.** The expected diagnostic result: C. perfringens (41 annual deaths) selected over B. cereus (0 deaths). Both pathogens are real hazards for cooked rice; the system picked the one with higher mortality. C. perfringens spore germination after cooking is a documented rice hazard, so the answer is also food-science-defensible. The textbook B. cereus emetic toxin story is the more famous one, but the deaths data favors C. perfringens — and the system's audit transparently shows the deaths-ranking step.

**Six heuristics fire cleanly.** rule_match × 2 (T and duration), Tier 1 RAG (pH), Tier 2 fallback (aw), range_clamp (aw), §2.4 ranked-by-deaths (organism). All represented in the audit at appropriate levels. Densest audit-trail capture in the journal.

**Growth prediction is meaningfully smaller post-fix.** Pre-fix Salmonella default produced μ_max ≈ 0.55, log_increase ≈ 0.24. Post-fix C. perfringens produces μ_max = 0.267, log_increase = 0.116. C. perfringens kinetics are slower than Salmonella at 25 C in their respective models. So §2.4 picking the right hazard *reduced* the predicted growth — a more conservative pathogen identity does not always mean a more alarming prediction. Useful nuance for the demo.

**range_clamp is model-aware.** aw clamp value is 0.971 (C. perfringens floor), not 0.973 (Salmonella floor). The clamp uses the selected model's valid_ranges, not a generic floor. Right behavior, now with evidence.

**Rule-match audit honesty issue persists.** `temperature.matched_pattern = "room temperature"` despite the query saying "sitting out." This is the audit-honesty thread item that remains open — see cross-cutting findings.

**aw retrieval still pulls a wrong-physical-state doc.** Tier 2 fallback retrieved uncooked rice aw [0.8, 0.87]. CSV gap: no cooked-rice aw entry. The clamp + warning is the correct response; the underlying retrieval is wrong because the KB lacks the right doc.

**Cross-encoder field-mismatch promotion still happens.** pH retrieval's reranker_top is doc 229 (uncooked rice aw doc) with rerank 3.93, but it fails the embedding gate. Same pattern as Q04. Empirical evidence for the field-mismatch failure mode that Session 2's calibration experiment will quantify.

### Conclusion
Pass on capability. §2.4 fires correctly, deaths-ranking returns the expected pathogen, six heuristics surface cleanly. Demo-relevant: shows §2.4 picking a non-textbook pathogen with full deaths-ranking provenance, plus the densest audit display in the journal.

### Followups
- §2.4 silence on rice — closed 2026-05-01. Two changes to query_pathogen_hazards: query template changed to "{food} food hazard" (was "{food} pathogen bacteria hazard contamination" — vocabulary asymmetry across foods), and metadata filter added on data_type=food_pathogen_hazard. A subsequent Chroma syntax hotfix was needed: the multi-key where filter required explicit $and. The 0.75 threshold remains uncalibrated; folded into Session 2.
- Organism field's retrieval block showing wrong retrieval — closed 2026-05-01. Root cause: audit-routing Priority 2 heuristic was matching "pathogen" substring on query content, which the prior Q06 fix invalidated by changing the query template. One-line fix at grounding_service.py:823 sets attributed_field="organism". Same pattern as food-property fallback. Generalizable lesson recorded: audit routing should use structural field handles, never substring matching.
- Audit-honesty gap (broader): when a multi-stage retrieval's Stage 2 short-circuits on missing metadata, there's no signal in the audit. The Q06 fix prevents this by adding the metadata filter at Stage 1; a structured "Stage 2 was skipped" event would protect against the same class of bug in other retrieval paths. Low priority.
- Add `original_phrase` field to rule_match extraction blocks, matching embedding_fallback's convention. Q06 surfaces this; Q07 confirmed the audit shape supports it. (Open audit-honesty thread item.)
- Strengthen range_clamp warning when the clamped value comes from a Tier-2 retrieval that's a wrong-category match. Consolidated into the broader range_clamp-into-below-threshold finding.
- Knowledge base gap: no aw entry for cooked rice. Filed as KB content.

---

## Q07 — Bread on a sunny windowsill / Bacillus cereus growth

### Goal
Tests the embedding_fallback temperature interpretation path. The 23-entry temperature rule registry covers common phrasings (room temperature, warm, hot, in the car, etc.), but a sufficiently novel phrase should miss the exact/fuzzy match and trigger embedding similarity against a canonical-phrases set. Tests `extraction.method = "embedding_fallback"`, `similarity`, `canonical_phrase`. Same food/pathogen/duration as Q03 and Q05, isolating the temperature path.

### Query
> "A slice of white bread was left on a sunny windowsill for 4 hours. Predict B. cereus growth."

### Expected
- T → user_inferred via embedding_fallback, similarity float, canonical phrase populated, final value reasonable for a warm/sunny scenario
- pH, aw → identical to Q03/Q05 (same RAG retrieval)
- B. cereus, duration → USER_EXPLICIT
- range_clamps, defaults_imputed, warnings all []

### Actual (2026-05-01 12:55 UTC, ptm 6d8aa38, verbose=true)
- T = 30, source = user_inferred, **extraction.method = "embedding_fallback"** ✓
- similarity = 0.6115 (the embedding cosine score)
- canonical_phrase = "sunny spot" (note: not in the documented 23-entry rule registry — there's a separate canonical-phrases set for the embedding step)
- matched_pattern = "sunny windowsill" — the original query phrase, recorded correctly
- pH = 6.2 ✓ RAG, doc 211, range_bound_selection upper [5.0, 6.2]
- aw = 0.97 ✓ RAG, range_bound_selection upper [0.94, 0.97]
- B. cereus, duration USER_EXPLICIT ✓
- reranker_top: null on both retrievals
- range_clamps, defaults_imputed, warnings all empty ✓
- system block: 5/5 ✓
- μ_max = 0.536, log_increase = 0.93 (~9× population) — identical to a "warm car" capture (supplementary) since both routed to 30 C

### Findings

**Embedding_fallback path works as designed.** Confirms the schema fields (`similarity`, `canonical_phrase`) are real and populated when extraction goes through embedding similarity. The 0.61 similarity score crossed whatever internal threshold gates the embedding step — sunny windowsill → sunny spot was deemed close enough to commit to a value.

**Audit honesty for embedding_fallback is correct.** `matched_pattern` records the query phrase, `canonical_phrase` records the registry entry the embedder mapped to. A consumer can trace: user said "sunny windowsill" → embedder mapped to canonical "sunny spot" → that canonical is associated with 30 C. Full provenance.

**This refines the Q06 audit-honesty followup.** Q06's `rule_match` extraction recorded `matched_pattern: "room temperature"` even though the query said "sitting out" — the original phrase was lost. Q07's `embedding_fallback` records both correctly. So the audit *fields* support distinguishing original-vs-canonical; the *rule_match path* just doesn't populate them consistently. The fix is now scoped: align rule_match's audit shape with embedding_fallback's. Probably a small change.

**The canonical-phrases registry is larger than the rule registry.** "Sunny spot" doesn't appear in the 23-entry temperature rule registry returned in our investigation. The embedding step uses a separate (likely richer) set of canonical phrases. Worth understanding the structure if relevant for Session 2's calibration experiment.

**Side note: similarity threshold question.** The embedding fallback fired on a 0.61 similarity. We don't know what the gate is — could be 0.50, 0.55, 0.60, or no gate at all (commit to whatever the closest match is, however distant). For comparison, retrieval thresholds elsewhere are 0.70 (Tier 1 embedding) and 0.62 (Tier 2 embedding). 0.61 is close to Tier 2 territory. Worth noting for Session 2 or for any future investigation of when embedding_fallback should fail rather than commit.

### Conclusion
Pass — the cleanest test of the embedding_fallback path. Demo-relevant: shows the system handling a novel temperature phrase that's outside its rule registry, with full audit transparency about how the value was inferred.

### Followups
- Align rule_match audit shape with embedding_fallback. `matched_pattern` should record the original query phrase; `canonical_phrase` should record the matched rule key. Q06 was the surfacing case; Q07 is the positive evidence the audit fields support it. (Open audit-honesty thread item.)
- Document the canonical-phrases registry alongside the rule registry. A reader of §5 should be able to see both sets.
- Note for Session 2: embedding_fallback's similarity threshold is undocumented. The 0.61 hit committed; we don't know whether 0.50 would have. Worth measuring.

### Supplementary captures (kept for reference)

**"warm car" (2026-05-01 12:48 UTC):** *"A slice of white bread was kept in a warm car for 4 hours. Predict B. cereus growth."* T extraction: rule_match on "warm" → 30 C. Same final value as Q07's embedding_fallback result, different path.

**"tropical climate" (2026-05-01 12:56 UTC):** *"A slice of white bread was kept in a tropical climate for 4 hours. Predict B. cereus growth."* T extraction did NOT fire embedding_fallback. Instead: source = "conservative_default", extraction = null, final_value = 25 C. The parser layer apparently didn't classify "tropical climate" as a temperature description, so the rule/embedding extraction never ran. Parser-level gate finding, separate from rule/embedding layers.

---

## Q08 — Chicken cooked to 65 C for 10 min / thermal inactivation

### Goal
Tests the conservatism direction reversal: thermal inactivation model should narrow ranges to the LOWER bound (less kill = more conservative), the inverse of the growth-model behavior in Q02–Q05. Plus naturalistic question-form phrasing and pathogen inference. Headline cooking-mode demo case.

### Query
> "We cooked the chicken to 65 C for 10 minutes — was that enough?"

### Expected
- T = 65 (USER_EXPLICIT), duration = 10 (USER_EXPLICIT)
- model_type = thermal_inactivation (LLM inference)
- pH → RAG with range_bound_selection direction = lower (6.2 from [6.2, 6.4])
- aw → RAG (or Tier 2 fallback), possibly clamped if outside thermal model's range
- Organism → §2.4 inference for chicken → Salmonella
- Prediction: a sensible log reduction (typically 5–7 logs is the safety target)

### Actual (2026-05-01 14:32 UTC, ptm 6d8aa38, verbose=true)
- T = 65 ✓, duration = 10 ✓, USER_EXPLICIT direct
- model_type = thermal_inactivation ✓
- range_bound_selection direction = "lower" ✓, [6.2, 6.4] → 6.2, reason: "Range narrowed to lower bound for thermal_inactivation model (less pathogen kill = more conservative)"
- pH source = rag_retrieval_fallback (Tier 2, "chicken pH acidity" query, doc 24) — same Tier 1 fragility as Q02 holds
- aw = 0.997, source = rag_retrieval_fallback, clamped from 0.99 to 0.997 (thermal_inactivation model floor)
- Organism = Salmonella ✓, source = rag_retrieval, attributed_field routing works correctly (organism's retrieval shows pathogen retrieval, query "chicken food hazard")
- 🔴 prediction broken: μ_max = -1931, log_increase = -321.9 ("321.9 log decrease, >99.9999% killed")
- range_clamps[1] (aw), defaults_imputed[0], warnings[1]
- system block: 5/5 ✓

### Findings

**Conservatism reversal works as designed.** The range_bound_selection event records direction="lower" for thermal_inactivation, with explicit reasoning text. Same input pH range as Q02/Q04 (chicken 6.2–6.4) but the selected bound flips. This is the demo's headline cooking-mode story end-to-end: the system understands what "conservative" means in context, and the audit explains it in plain language.

**range_clamp is model-AND-model-type-aware.** Salmonella growth model floor is aw 0.973; Salmonella thermal_inactivation model floor is aw 0.997. The clamp value reflects which model was selected, not a generic "Salmonella floor." Same model-aware behavior as Q06 (C. perfringens floor 0.971). Two layers of model-specific clamping working together.

**Naturalistic question-form parsing works.** Query is conversational ("We cooked the chicken to 65 C for 10 minutes — was that enough?"), not imperative. Parser extracted T=65 and t=10 cleanly as USER_EXPLICIT. The em-dash and the question mark didn't disrupt extraction. Good parser robustness data point.

**Q06 audit-routing fix carries through.** Organism field's retrieval block correctly shows the pathogen retrieval (query "chicken food hazard", top_match pathogen_hazards_370 — Salmonella primary hazard). The attributed_field structural routing works for any organism inference, not just rice.

**🔴 Prediction is mathematically unphysical.** μ_max = -1931, log_increase = -321.9. A 321-log reduction means the bacterial population goes from 10⁰ to 10⁻³²¹, which is meaningless. Real thermal inactivation predictions are typically 5–7 log reductions for safety-relevant scenarios; FDA cooking guidance for chicken targets 6.5-log Salmonella reduction at 74 C for 10 sec, or equivalent time-temperature combinations.

The thermal_inactivation polynomial is being evaluated at the upper boundary of its valid temperature range (65 C is the model's max per valid_ranges) and producing a value ~50 orders of magnitude beyond physical reality. Likely causes: polynomial extrapolation at boundary, unit-handling mismatch, or a sign/formula error specific to thermal_inactivation. Q09 and Q17 confirm growth-model evaluation at boundary works correctly, narrowing the bug to thermal-inactivation-specific causes.

The system is reporting a prediction with no flag indicating it shouldn't be trusted. The audit is honest about every other layer (retrievals, citations, range_bound_selection direction, clamping), but the prediction layer hands back nonsense at face value. A food scientist reading "321 log decrease" would immediately spot the absurdity; a casual reader might accept it.

This is the most consequential finding in the journal. The heuristic-validation story works (every audit field is correct), but the *answer* the system gives to a real question is wrong by 50 orders of magnitude.

**Tier 1 fragility on chicken persists post-fix.** pH retrieval still goes through Tier 2 ("chicken pH acidity", embed 0.6871 < 0.70). Same finding as Q02. Folded into Session 2's california scope.

### Conclusion
🔴 Critical finding. The heuristic layer works perfectly (this is the cleanest cooking-mode reversal capture in the journal — direction correctly flipped, reasoning surfaced, citations present, model-type-aware clamping). But the underlying numerical prediction is broken in a way that makes the answer worthless. Cannot demo this query as-is without explanation.

Three options before demo:
1. Fix the math — investigate the polynomial evaluation at boundaries, patch the unit/extrapolation issue.
2. Cap predictions — clamp to a physical maximum (say, 12-log reduction is roughly the limit of measurability for any food safety process) and surface a warning.
3. Scope around the issue for the demo — use a thermal_inactivation query at a less extreme T (e.g. 55-58 C, well within the polynomial's reliable range) so the math returns sensible numbers; show this Q08 as evidence of the audit working correctly, without focusing on the prediction value.

### Followups
- 🔴 Investigate thermal_inactivation prediction blow-up. Polynomial evaluation at temperature boundary produces unphysical values. Probable unit issue or extrapolation issue. Active Claude Code session in flight.
- 🟡 Add "prediction outside expected range" warning. Independent of the math fix: any prediction with log_increase outside [-15, +15] (or similar physical bounds) should surface a warning. Defense-in-depth against model-coefficient bugs.
- ✅ Conservatism reversal direction logic — this query confirms it works for thermal_inactivation. No further work.
- ✅ attributed_field routing fix carries through to thermal_inactivation organism inference.
- Tier 1 fragility on chicken pH (same as Q02) — folded into Session 2.
- Naturalistic question-form parsing works — useful data for Q11 (the multi-rule natural-language test).

---

## Q09 — E. coli on milk at 50 C / 6 hours

### Goal
Tests range_clamp behavior on USER_EXPLICIT values (50 C above E. coli growth model's 42 C ceiling). Also exercises retrieval on a generic food name ("milk") to see what the KB returns. Designed primarily as a range_clamp coverage test.

### Query
> "Predict E. coli growth on milk at 50 C for 6 hours."

### Expected
- T → USER_EXPLICIT, clamped from 50 to model max (~40-42 C)
- duration → USER_EXPLICIT
- E. coli → USER_EXPLICIT
- pH → RAG retrieval (milk in some form is in the KB)
- aw → RAG or default
- range_clamps populated with the temperature clamp event
- warnings populated

### Actual (2026-05-01 14:54 UTC, ptm 6d8aa38, verbose=true)
- T = 42, source = USER_EXPLICIT, clamped from 50 (model max)
- pH = 4.5, source = rag_retrieval_fallback (Tier 2 query "milk pH acidity"), retrieved range [4.09, 4.25] from doc 4 (milk acidophilus), clamped from 4.25 up to 4.5 (model min)
- aw = 0.99, source = CONSERVATIVE_DEFAULT (no clamp; 0.99 within model's [0.961, 1.0])
- duration = 360, E. coli — USER_EXPLICIT
- range_clamps[] has 2 entries (temperature, pH); defaults_imputed[1] (aw)
- warnings[] has 2 messages (one per clamp)
- system block: 5/5 ✓
- μ_max = 0.287, log_increase = 0.75 ("moderate growth, ~6× population")

### Findings

**range_clamp coverage: three distinct value-source origins.** Temperature clamp fires on a USER_EXPLICIT value (50→42); pH clamp fires on a RAG_RETRIEVAL_FALLBACK value (4.25→4.5); aw is at default but doesn't clamp. All three field-source types now have range_clamp coverage.

**First capture where range_clamp fires on a USER_EXPLICIT value.** Audit shape: source stays USER_EXPLICIT, standardization.range_clamp records before/after, top-level range_clamps[] populated. The user's input is respected as their input but overridden for the model evaluation, with full traceability.

**Both bounds of model validity exercised.** Temperature clamped DOWN (50 → 42, ceiling). pH clamped UP (4.25 → 4.5, floor). One query, both directions of out-of-range handling.

**🟡 KB ambiguity: "milk" retrieves "milk acidophilus."** Tier 2 query "milk pH acidity" returns top match doc 4, milk acidophilus (pH 4.09-4.25, rerank 7.69), runners-up milk evaporated (5.9-6.3) and milk condensed (6.33). Acidophilus milk is fermented milk; its pH ~4 is correct *for that food*, but for the user's "milk" (almost certainly ordinary fluid milk, pH ~6.7), it's the wrong food. The KB doesn't appear to have an entry for ordinary fluid milk; the retrieval returned the closest-named match.

This is a different failure mode from Q06's cooked-rice aw. Q06 was a KB *gap* (no cooked-rice aw entry exists); Q09 is KB *ambiguity* (a generic food name maps lexically to a specific cultivar/preparation). Both result in clamped, warning-flagged predictions whose inputs are detached from the user's actual food.

The reranker confidently picked acidophilus over evaporated (rerank 7.69 vs 2.55) — the cross-encoder isn't catching the food-cultivar mismatch. See cross-cutting findings on cross-encoder failure modes.

**🟡 Tier 1 fragility on milk too.** ph.retrieval.query is "milk pH acidity" — the Tier 2 fallback. Tier 1 ("milk pH water activity properties") presumably missed the 0.70 gate. Same pattern as Q02 (chicken). Three foods now show this fragility.

**Prediction is sensible — different from Q08.** Despite hitting both the model's pH boundary (clamped to 4.5) and temperature boundary (clamped to 42), the prediction is physically reasonable: μ_max=0.287, log_increase=0.75 (~6× population). E. coli growth model evaluates sanely at boundary, even though Q08's Salmonella thermal_inactivation evaluates pathologically (321-log decrease) at its own boundary.

**Important diagnostic for Q08's thermal_inactivation bug.** Q09 is evidence that boundary-evaluation pathology is not universal across ComBase models. Same pattern (USER_EXPLICIT input above model max, RAG-retrieved input clamped to model min), different model: Q09 E. coli growth at boundary: sensible prediction; Q08 Salmonella thermal_inactivation at boundary: 50+ orders of magnitude off. This narrows the thermal_inactivation diagnosis: the bug is unlikely to be general polynomial extrapolation; more likely a unit mismatch or sign/formula error specific to thermal_inactivation.

### Conclusion
Pass. Three range_clamps fire correctly across three different value-source types, audit is fully populated, warnings are surfaced. Two real findings: (1) KB ambiguity with "milk" → "milk acidophilus" producing a scientifically wrong food selection, clamped and warned but detached from the user's intent; (2) the third instance of Tier 1 fragility on a generic food name. Demo-relevant: shows the system's honesty about out-of-range conditions, but the milk-acidophilus story needs framing if shown.

### Followups
- 🟡 KB ambiguity: ordinary fluid milk has no entry. Add a baseline milk row, OR teach the parser to disambiguate generic food names from named varieties. Probably both. Filed as KB content + parser work.
- 🟡 Cross-encoder food-cultivar mismatch is a related failure mode to the field-mismatch issues (Q04, Q06). Worth noting in Session 2's cross-encoder analysis as a distinct sub-class.
- ✅ range_clamp on USER_EXPLICIT — works correctly; audit shape uniform across all three value-source origins.
- Tier 1 fragility on generic food names — folded into Session 2.
- For the Q08 thermal_inactivation investigation: this Q09 capture is the comparison case (growth model at boundary works fine).

### Demo positioning
The honest framing: "the user said milk and 50 C; the system found a milk-related entry, recognized the temperature was beyond what the growth model can predict, clamped both pH and temperature to model limits, and gave a sensible answer for the boundary case — with warnings about every step." The acidophilus detail is best left in the audit for technical inspection rather than foregrounded in the live demo.

---

## Q10 — Listeria on cheese at 4 C / 14 days

### Goal
Smoke test for refrigeration-edge growth modeling and long-duration math. Listeria is famously cold-tolerant — does the growth model handle 4 C for two weeks correctly? Also tests range_clamp on a retrieved aw that's well below the Listeria model's floor (parmesan aw ~0.7 vs Listeria floor 0.934). Plus a generic single-word food name ("cheese") that might surface another Tier 1 fragility instance.

### Query
> "Predict Listeria growth in cheese at 4 C for 14 days."

### Expected
- T = 4 (USER_EXPLICIT), duration = 20160 min (USER_EXPLICIT)
- Listeria → USER_EXPLICIT
- pH → RAG retrieval on "cheese", upper bound (growth)
- aw → RAG retrieval, possibly clamped (cheese aw is variable; some varieties below model floor)
- Prediction: small but non-zero growth (Listeria optimum ~30 C; 4 C is on the cold edge of its growth range)

### Actual (2026-05-01 15:35 UTC, ptm 6d8aa38, verbose=true)
- T = 4 ✓ USER_EXPLICIT, duration = 20160 ✓ USER_EXPLICIT
- pH = 5.3 ✓ RAG_RETRIEVAL (Tier 1, query "cheese pH water activity properties", embed 0.7513, rerank 7.074), top_match doc 14 (cheese parmesan), range_bound_selection upper [5.2, 5.3]
- aw = 0.934, source = rag_retrieval, clamped from parmesan range [0.68, 0.76] up to model floor 0.934 (a 0.17-unit jump)
- Listeria USER_EXPLICIT ✓
- range_clamps[1] (aw), defaults_imputed[0], warnings[1]
- Multi-source citation populated (FDA-PH-2007 + IFT-2003-T31) ✓
- reranker_top: null on both retrievals (rerank winner = top_match)
- system block: 5/5 ✓
- μ_max = 0.0046, doubling time ≈ 149 hours, log_increase = 0.68 ("moderate growth, ~5× population over 14 days")

### Findings

**Long-duration math is sound.** 20,160 minutes (336 hours) is the longest duration in any capture. Prediction is physically sensible: Listeria at 4 C grows slowly but steadily; doubling time of ~149 hours over two weeks gives ~5× population, consistent with Listeria's known cold-tolerance and characteristic of the slow ripening that makes cheese a high-risk product for listeriosis. No precision issues, no overflow, no quirks at this time scale.

**Refrigeration-edge behavior works.** μ_max at 4 C is 0.0046 — about 200× slower than Q03's bread-at-25 C case (μ_max ≈ 0.35). The Listeria growth polynomial evaluates correctly far from optimum. The growth rate scales sensibly with temperature; the log_increase is comparable to short-duration warm-temperature cases because the duration compensates.

**Comparison with Q08: the prediction-layer pathology IS thermal-inactivation-specific.** Q08's thermal_inactivation evaluation produced unphysical results (321-log decrease) at the model's temperature boundary. Q09 showed E. coli growth at boundary working fine. Q10 shows Listeria growth across two weeks of duration plus aw clamp — also fine. Two confirmation cases that growth-model evaluation is well-behaved near boundaries; thermal_inactivation is the specific case that's broken. Strong evidence for the active investigation.

**🟡 Cheese retrieval — partial cultivar mismatch.** The Tier 1 retrieval returned cheese parmesan as the top match for the query "cheese pH water activity properties." Parmesan was selected because its row is fully populated (both pH and aw); runners-up include natural cheeses (aw only, no pH) and cheese cottage (pH only, no aw).

For "cheese" without qualifier, the user could plausibly mean parmesan, cheddar, mozzarella, cottage, or many others — each with substantially different pH (4.75-5.5) and aw (0.65-0.99). Parmesan's hard-aged values (low pH, very low aw) sit at the dehydrated end of the spectrum; soft cheeses are at the hydrated end. The system picked parmesan because the KB happens to have it as the most fully-populated row, not because it's the canonical "cheese."

This is the same pattern as Q09's milk acidophilus, but in a partial form: parmesan is *a* legitimate cheese, just not necessarily the one implied by "cheese." Both surface the same underlying issue: generic food names don't reliably retrieve a representative entry; they retrieve whichever row in the KB happens to score highest.

**🟡 The aw clamp obscures a "no growth" reality.** Parmesan's actual aw range is 0.68–0.76. Listeria's growth threshold is around aw 0.92 (above the model floor of 0.934). Parmesan at aw 0.76 is *well below* where Listeria can grow at all — under that condition, the right prediction is "no growth." But the system clamps to model floor 0.934 and predicts growth (~5× over 14 days).

The clamp is structurally honest (warning issued, audit shows the clamp), but the *prediction value* implies Listeria grows on aged parmesan in 14 days, which doesn't match the food microbiology. A reader of the prediction summary ("moderate growth, ~5× population") without reading the warning would conclude something the science doesn't support.

This is a third class of "the audit is honest but the prediction value is not what the science would say": Q06 (wrong physical state, dry rice aw clamped), Q09 (wrong cultivar, milk acidophilus), and Q10 (model-faithful but science-divergent: aw too low for any growth, but clamp produces a growth prediction). See cross-cutting findings.

A stronger warning at this kind of boundary would help: when the clamp moves the value into the model's valid range FROM a value that implies the modeled phenomenon doesn't occur, the warning could say so explicitly. "Listeria does not grow at aw 0.76; clamping aw to the model's minimum of 0.934 produces an artificial growth prediction."

**Tier 1 fired here, unlike Q02/Q06/Q09.** Embedding 0.7513 — comfortably above the 0.70 gate. Compare to chicken (Q02 < 0.70 → Tier 2), cooked rice (Q06 ~0.72 / Tier 1 marginal), milk (Q09 < 0.70 → Tier 2). So Tier 1 fragility is real but not universal across single-word food queries. "Cheese" hits Tier 1 cleanly because cheese-parmesan as a doc has a strong embedding signal for the bare word "cheese." Useful asymmetric data for Session 2.

**Reranker agrees with embedder cleanly.** rerank score gap from top to runner-up is 7.07 → 5.38 → -0.03 — wide, monotonic alignment with embedding scores. No reranker_top populated. Counter-example to Q04/Q06's field-mismatch pattern: when the docs are clearly distinguished, reranker and embedder cooperate.

**Multi-source citation, third confirmation.** Cheese parmesan row has both FDA-PH-2007 (pH) and IFT-2003-T31 (aw). The §8.11 ingestion-layer notes-parsing works on cheese alongside bread (Q03) and others.

### Conclusion
Pass on capability; refrigeration-edge growth modeling and long-duration math are sound. Two notable findings: (1) cheese-parmesan selection illustrates the partial-cultivar-mismatch pattern (defensible but non-disambiguated); (2) the aw clamp produces a model-faithful but food-microbiology-divergent prediction. Strong evidence (alongside Q09) that the Q08 thermal_inactivation prediction pathology is model-type-specific, not general.

### Followups
- 🟡 Stronger warning when range_clamp moves a value into model range from a value that implies the modeled phenomenon doesn't occur. Same shape of followup as Q06's wrong-physical-state warning improvement.
- 🟡 Cheese (and any food where the KB has multiple cultivar entries with different properties) needs disambiguation logic.
- For the Q08 thermal_inactivation investigation: Q10 confirms growth-model evaluation works correctly under a wide range of conditions.
- ✅ Multi-source citation pattern works across foods (bread, cheese confirmed).
- Tier 1 retrieval works asymmetrically across single-word food names (cheese ✓, chicken ✗, milk ✗, rice marginal). Folded into Session 2.

---

## Q11 — Chicken left out overnight / question form, multi-rule, pathogen inference

### Goal
Parser stress test. Query combines: question-form phrasing ("Was X still safe to eat?"), two simultaneous rule-extractions ("overnight" → duration, "room temperature" → temperature), pathogen inference (no organism specified), and a chicken food name that triggers Tier 1 fragility (per Q02). All four triggers in one query.

### Query
> "Was the chicken left out overnight at room temperature still safe to eat?"

### Expected
- T → user_inferred via rule on "room temperature" → 25 C
- duration → user_inferred via rule on "overnight" → ~8 hours (480 min)
- pH → RAG (chicken row, Tier 2 fallback expected per Q02 fragility)
- aw → Tier 2 fallback (chicken aw blank, fresh poultry doc)
- organism → §2.4 inference, deaths-ranked → Salmonella
- range_bound_selection upper on both pH and aw (growth model)
- Prediction: substantial growth at 25 C / 8h conditions

### Actual (2026-05-01 15:39 UTC, ptm 6d8aa38, verbose=true)
- T = 25 ✓ user_inferred, rule_match on "room temperature"
- duration = 480 ✓ user_inferred, rule_match on "overnight" (notes: "typically 6-10 hours; using 8")
- pH = 6.4 ✓ rag_retrieval_fallback (Tier 2 "chicken pH acidity"), range_bound_selection upper [6.2, 6.4]
- aw = 1.0 ✓ rag_retrieval_fallback (Tier 2 "chicken water activity aw moisture"), top_match fresh poultry doc, range_bound_selection upper [0.99, 1.0]
- organism = Salmonella ✓, source = rag_retrieval, ranked_by_annual_deaths (attributed_field routing correct: organism retrieval shows pathogen query "chicken food hazard")
- range_clamps[0], defaults_imputed[0], warnings[0]
- system block: 5/5 ✓
- μ_max = 0.926, log_increase = 3.22 over 8h (~1,650× population — "Extensive growth: 3.2 log increase, >1000x population")

### Findings

**Parser handles all four triggers in one query.** Question form, two rule-extractions, pathogen inference. Each fires correctly without interference. Per-field audit cleanly attributes each value to its respective extraction path. No errors, no defaults, no clamps. Strong positive evidence for parser robustness on naturalistic compound queries.

**Tier 2 fallback fires on both fields, predictably.** pH goes through Tier 2 (same Q02 fragility — "chicken" embedding < 0.70 on Tier 1). aw goes through Tier 2 because chicken row has aw blank. The audit distinguishes: pH's rag_retrieval_fallback is from Tier 1 missing threshold; aw's is from Tier 1 returning a doc that lacked the field. Same source label (rag_retrieval_fallback), different underlying causes — honest about *that* it fell back, less explicit about *why*.

**The aw monotonicity issue persists.** aw = 1.0 (range_bound_selection upper) gives a slightly *lower* μ_max than the 0.99 default would because Salmonella's polynomial peaks near 0.99 and dips at exactly 1.0. Same finding as post-fix Q04. The "upper bound = more conservative for growth" heuristic remains approximate at the aw boundary.

**Prediction value is food-microbiologically correct.** 3.22-log increase over 8 hours at 25 C for Salmonella on chicken is consistent with literature growth rates. ~1,000× population multiplication on food left at room temperature overnight matches what a food microbiologist would predict. The math is sound; the audit is honest about every input.

**✓ The user asked "is it safe to eat?" — the system answered with a growth number, not a safety verdict.** This is a genuine scope boundary, not a bug. PTM's contract is prediction, not interpretation. Safety verdicts (yes/no, "discard immediately," etc.) are the scope of a planned downstream project that will consume PTM's output and apply infectious-dose / 2-hour-rule / cooking-step reasoning. Q11 is useful demo material precisely because it shows where PTM's scope ends; the follow-on project's job begins where PTM's audit trail ends.

A non-microbiologist reading "moderate growth, 3.2 log increase" might parse it as "noticeable but not catastrophic." A food microbiologist reads it as "definitively unsafe." The system's output requires the microbiologist's interpretation to map to the user's question. The architecture has no place where "growth prediction" gets converted to "safety verdict" — and that's by design.

**Multi-trigger audit shape works well.** All four extraction layers (USER_EXPLICIT for organism's downstream use, rule_match × 2, RAG_RETRIEVAL_FALLBACK × 2, RAG_RETRIEVAL for pathogen inference) appear in their appropriate per-field audit blocks. Top-level lists are empty (no defaults, no clamps, no warnings — everything resolved without intervention). The audit shape scales correctly with parser complexity.

### Conclusion
Pass on all parser capabilities. Cleanest naturalistic-language capture in the journal: every heuristic layer fires correctly, no errors, no clamps, no defaults. The microbiology is right.

The user's question isn't directly answered (PTM gives growth, not verdict) — but this is the system's documented scope boundary, not a gap. Demo-relevant: shows the parser is excellent and the model is sound, while making the scope boundary explicit. A follow-on interpretation project will close the verdict gap; PTM stays in its lane.

### Followups
- ✓ PTM's "growth not safety" scope is documented behavior. Q11 is the cleanest illustration; pair with Q13/Q14 to also show "forward not inverse" as a parallel scope statement.
- aw monotonicity issue (Salmonella μ_max peaks at 0.99, dips at 1.0) unchanged from Q04. Pre-existing, unaddressed.
- Tier 1 fragility on chicken — same as Q02, same as multiple other queries; folded into Session 2 calibration.

---

## Q12 — Bread with no pathogen specified / pathogen inference fall-through

### Goal
Tests pathogen inference fall-through for a food that's NOT in food_pathogen_hazards.csv. Bread has no rows in that CSV (verified), unlike chicken or rice. Expected behaviors range from §2.4 fires and finds nothing, to §2.4 doesn't fire at all because Stage 1 has no candidates, to §2.4 fires but rapidly defaults. The capture clarifies which.

### Query
> "Predict pathogen growth on a slice of white bread at 25 C for 4 hours."

(Note: Q12 was originally captured as "How long can a slice of white bread sit out at 25 C before it goes bad?" — that query failed with a hard error. See Q12-supplementary below. This re-crafted version pins the heuristic target.)

### Expected
- T, duration → USER_EXPLICIT
- pH, aw → RAG (bread, both fields populated)
- organism → diagnostic question — see goal

### Actual (2026-05-01 15:53 UTC, ptm 6d8aa38, verbose=true)
- T = 25 ✓, duration = 240 ✓, USER_EXPLICIT
- pH = 6.2 ✓ RAG_RETRIEVAL, range_bound_selection upper [5.0, 6.2]
- aw = 0.973 ✓ RAG_RETRIEVAL, retrieved range [0.94, 0.97], clamped from 0.97 to 0.973 (Salmonella growth model floor)
- organism = Salmonella, source = CONSERVATIVE_DEFAULT. No retrieval block. §2.4 didn't fire.
- Multi-source citation populated (FDA-PH-2007 + IFT-2003-T31) ✓
- range_clamps[1], defaults_imputed[1], warnings[2]
- system block: 5/5 ✓
- μ_max = 0.537, log_increase = 0.93 (~9× population)

### Findings

**§2.4 doesn't fire when the food has no entries in food_pathogen_hazards.csv.** Bread has no rows in food_pathogen_hazards.csv (rice has 2 rows, chicken has 5, bread 0). Stage 1 retrieval has no candidates that match; Stage 2 deaths-ranking has nothing to rank; the orchestrator falls through to CONSERVATIVE_DEFAULT Salmonella.

This is defensible — the system shouldn't fabricate a pathogen choice when it has no data — but it surfaces a content gap. The KB has bread-relevant pathogen data in a *different* CSV: pathogen_food_associations.csv has a "cereal grains" entry mapping to Salmonella, Staph aureus, B. cereus, and C. botulinum. That data is currently unused; the §2.4 path only consults food_pathogen_hazards.csv.

The trade-off: pathogen_food_associations doesn't have annual_deaths_us counts, so deaths-ranking can't be applied. Some other selection heuristic would be needed.

**aw clamp at 0.973 is interesting.** Bread's aw range is 0.94–0.97 from IFT-2003-T31. range_bound_selection picks upper (0.97). Then Salmonella growth model's aw floor (0.973) clamps it up to 0.973 — a 0.003 nudge, but enough to qualify as a clamp. So bread is *just below* the Salmonella growth model's aw floor. Worth knowing: bread is on the edge of conditions where Salmonella can grow at all per this model.

**Conservative default produces a more-aggressive prediction than the textbook pathogen would.** μ_max = 0.537 with Salmonella default vs μ_max = 0.354 with explicit B. cereus (Q03), at identical conditions. Salmonella grows faster than B. cereus at 25 C / pH 6.2 / aw 0.973. This is the right thing for a conservative default to do — when the pathogen is unknown, the system errs toward the fastest-growing one present in the data. Worth noting in demo: "the default isn't 'something safe to assume,' it's 'the worst-case pathogen by growth rate at these conditions.'"

**Multi-source citation works (third confirmation).** Bread row's two sources (FDA-PH-2007, IFT-2003-T31) populate cleanly via the ingestion-layer notes-parsing. Same as Q03, Q05, Q10.

**No reranker disagreement.** Bread retrieval has a wide rerank gap (top 6.22, runners-up 0.62 and -5.12); reranker_top correctly null. Same well-shaped retrieval as Q03/Q05.

### Conclusion
Pass on capability. The system handles "food not in hazards CSV" by falling through to default Salmonella, with full audit transparency. One real finding: pathogen_food_associations.csv has bread-relevant data (cereal grains) that's currently unused by §2.4. Worth filing as a content / architecture question.

Demo-relevant: this is the cleanest case of "the system gives the honest answer when it doesn't have the right data." Pair with Q06 (rice, where §2.4 *does* find the right pathogen via deaths-ranking) to show the gradient: known-food-with-data vs known-food-without-data both produce honest-but-different-quality answers.

### Followups
- 🟡 Architecture question: should §2.4 fall through to pathogen_food_associations.csv when food_pathogen_hazards has no matches? Pros: closes the bread-style gap, uses available data. Cons: associations data lacks deaths counts, would need a different selection heuristic. Defer past MVP.
- ✅ §2.4 deaths-ranking and CONSERVATIVE_DEFAULT fall-through both work correctly across the foods tested (chicken: hits hazards, rice: hits hazards, bread: no hazards row → falls through cleanly).
- aw monotonicity (Salmonella μ_max peaks at 0.99, the model floor at 0.973 isn't far below) — pre-existing pattern from Q04, unchanged.

### Q12-supplementary — original failed capture

The original Q12 query *"How long can a slice of white bread sit out at 25 C before it goes bad?"* failed with `error: "Missing required values: duration"`. The user was asking *for* a duration, and the system can't extract one or default one. This led to recasting Q12 with an explicit duration (the canonical entry above) and to designing Q13 as the explicit inverse-query test. The original failure capture's value is in surfacing the inverse-query architectural boundary; that finding lives more cleanly in Q13.

---

## Q13 — Inverse query / time to specified growth target

### Goal
Isolated test of the inverse-query failure mode that appeared during the original Q12 capture (now Q12-supplementary). Pin the user's intent unambiguously: every input is explicit (food, temperature, organism, target growth) except duration, which is the unknown the user is asking for. Tests whether PTM's forward-only model architecture handles this gracefully.

### Query
> "How long can chicken be left at 25 C before Salmonella grows by 3 logs?"

### Expected
- Failure with `error: "Missing required values: duration"` (since PTM is forward-only — given duration, predict growth)
- Partial audit population for fields that did get extracted before the failure
- The "3 logs" target value: status unknown — depends on whether the parser attempts to capture it at all

### Actual (2026-05-01 18:45 UTC, ptm 6d8aa38, verbose=true)
- status: failed ✓
- error: "Missing required values: duration" ✓
- Partial audit:
  - pH = 6.4 ✓ rag_retrieval_fallback (Tier 2 "chicken pH acidity"), range_bound_selection upper [6.2, 6.4]
  - aw = 1.0 ✓ rag_retrieval_fallback (Tier 2), range_bound_selection upper [0.99, 1.0]
  - T = 25 ✓ USER_EXPLICIT
  - organism = "ss" (note: internal id, not display name)
  - duration: absent
- combase_model: null
- system: null
- 3-log target: not captured anywhere in the audit

### Findings

**Forward-only model boundary surfaced cleanly.** PTM's architecture takes (food + conditions + duration) as inputs and produces (log increase, μ_max). The user's question — "how long until 3 logs?" — is the inverse: (food + conditions + target log increase) → duration. PTM doesn't support that direction, and signals the limitation by hard-failing with `Missing required values: duration` rather than defaulting or fabricating. This is the right behavior for a model whose contract is forward-only.

This is a real architectural boundary, not a bug. PTM is for "given this scenario, predict growth"; inverse queries are for a different tool (or a different mode of PTM, if it ever supports one). The journal records the boundary cleanly here.

**Pre-failure audit is mostly complete and trustworthy.** All extraction and grounding steps for the fields that ARE present run normally. pH retrieval (Tier 2 due to the chicken Tier 1 fragility from Q02), aw fallback (chicken row aw blank, Q04 pattern), T direct, organism direct. Range_bound_selection fires on both retrieved ranges. Multi-source citation populates. The orchestrator fails late, at the required-fields check, after the rest of the pipeline has done real work. Honest partial audit.

**🟡 Audit-shape inconsistency on failure path.** Two issues:
- organism.final_value = "ss" (the internal organism_id), not "Salmonellae" (the display name). On successful captures the display name is used. The display-name resolution step apparently runs after the required-fields check and is skipped on failure.
- combase_model = null and system = null. The orchestrator stops before model selection and before manifest stamping.

This is the same shape of finding as Q14's null system block on the failed query: failure paths leak architectural seams that success paths hide. Worth filing as a small audit-shape consistency work item — not blocking, but it would be cleaner to either populate display-name and system on failure, or to note explicitly that those fields are unavailable when status=failed.

**The "3 logs" target value is silently dropped.** The query carries a specific target (3-log increase) that, in a hypothetical inverse-query mode, would be the prediction goal. The current parser apparently doesn't have a slot for this — it doesn't appear anywhere in the audit, not as a captured-but-unused parameter and not as a warning about an unrecognized input. Worth knowing: any future inverse-query feature would need a new field to capture the target, and the parser would need to be taught about target-growth phrasings.

This isn't a Q13 finding per se — PTM doesn't claim to support inverse queries — but it's a measurement of how close the system is to supporting them. The answer: there's parser work to do before architectural work can begin.

### Conclusion
Pass on the design intent: failure mode is clean and loud. The forward-only architectural boundary is surfaced honestly with a clear error. Demo-relevant: this is the cleanest case of "PTM is honest about what it can't do" — paired with Q11's "PTM gives growth, not safety verdicts" finding, the journal now characterizes both major scope boundaries.

### Followups
- 🟡 Audit shape on failure: populate display name for organism and the system manifest block even when status=failed. Frontends rendering partial responses benefit from consistency. Small fix.
- For the next iteration of PTM (post-MVP): if inverse queries ever become in-scope, the parser needs a new "target_growth_log_increase" field, and the orchestrator needs an inverse-evaluation path alongside the forward path. Filed as a roadmap question, not a current bug.
- The chicken-Tier-1 fragility (Q02) and the aw-monotonicity issue (Q04) both reproduce here as expected. No new finding; folded into Session 2.

### Demo positioning
This query is short, clear, and surfaces a real boundary. Pair with Q11 in the demo's "scope" segment: "the user can ask three kinds of questions — predict (Q01-Q10), interpret (Q11, deferred to a downstream project), and inverse-predict (Q13, not currently supported). The system handles each honestly: predicts when it can, declines when it can't, and explains the difference."

---

## Q14 — Missing duration, all else explicit (case study)

### Goal
Case study, not pass/fail. Q13 isolated the failure mode where the user asks for duration as the answer. Q14 isolates the inverse: every input explicit *except* duration, with no signal the user is asking for it. Three plausible behaviors:
1. Hard failure (same as Q13)
2. Default duration with warning (parallel to pH/aw/organism defaults)
3. Time-series response (μ_max + doubling time, no final log_increase)

The capture reveals which.

### Query
> "How will Salmonella grow on chicken at 25 C, pH 6.4, water activity 0.99?"

### Actual (2026-05-01 18:48 UTC, ptm 6d8aa38, verbose=true)
- status: failed ✓
- error: "Missing required values: duration" — identical to Q13
- pH = 6.4, aw = 0.99, T = 25, organism = "ss" — all USER_EXPLICIT, extraction.method = "direct"
- No retrieval blocks (all values explicit; RAG never runs)
- combase_model: null, system: null (same as Q13)

### Findings

**Outcome: behavior (1) — hard failure.** Same architectural response as Q13. PTM does not distinguish "user is asking for duration as the answer" (Q13) from "user didn't specify a duration in an otherwise complete query" (Q14). Both fail at the same required-fields check, with identical error messages and identical audit shape on failure.

This isn't a bug — it's an architectural decision visible in the audit. The orchestrator's required-fields check operates on extracted values without considering user intent. There's no parser-layer step that would say "the user phrased this as a question about duration; treat duration as the prediction target" or "the user didn't mention duration; use a default."

**The asymmetry of missing-field handling.** Looking across Q01–Q14, every other field has a default path when missing:
- pH missing → CONSERVATIVE_DEFAULT 7.0 (Q15 captured this for fictional food)
- aw missing → CONSERVATIVE_DEFAULT 0.99 (Q15)
- organism missing → §2.4 inference, fallback to default Salmonella (Q12, Q15)
- temperature missing → CONSERVATIVE_DEFAULT 25 (Q07-supplementary "tropical climate")

Duration is the only field that fails closed when truly absent. The system *can* default duration when it has a phrase to anchor to — "a while" → 60 min (Q06), "overnight" → 480 min (Q11) — but without a phrase, the slot stays empty and the orchestrator hard-fails.

**The architectural argument for "duration is special":** pH, aw, organism are *parameters*. The model's behavior at default values is well-defined; "conservative pH 7.0" means something. Duration is the *independent variable* — the integration variable in a forward model. Picking a default duration changes *what is being predicted*, not just how conservatively. There's no "worst-case duration" the way there's a worst-case pH.

**The argument for "this is a gap":** the existence of "a while" → 60 min shows the architecture *can* assign a duration default. The question is just whether to extend it to "no phrase at all." A clarification path — "you haven't specified a duration; should I assume 4 hours, or compute time-to-target?" — would be the cleanest solution, but it isn't implemented.

**Q14 is the minimum-information failure case.** No retrieval ran; no defaults fired except where they would have for missing values; no warnings, no clamps, no rule extractions. The simplest possible "missing duration" surface. Useful as a baseline: any future change to duration handling should re-capture Q14 to verify the new behavior.

**🟡 The Q13 audit-shape inconsistencies reproduce.** organism = "ss" (internal id, not display name); combase_model and system both null on failure. Two captures of the same pattern now (Q13, Q14) — confirms it's a path-level issue with the failure handler, not a Q13-specific quirk.

### Conclusion
Diagnostic confirmed: PTM treats "missing duration" uniformly as hard failure, regardless of whether the user is asking for duration or just omitted it. The journal records this as a real architectural boundary and a design decision point, not a bug.

Demo-relevant: Q14 paired with Q13 makes the "duration is special" finding explicit. PTM is forward-only; duration must be supplied; both the inverse-question case and the unspecified case fail the same way.

### Followups
- 🟡 **Design decision: how should "missing duration" be handled?** Three options live:
  1. Status quo (hard fail — defensible: duration is the integration variable, no "worst case" makes sense)
  2. Default to a reasonable duration (4h / 24h / something else, with an explicit `default_imputed` event) — easier UX, but the choice of default value is itself a product decision with no single right answer
  3. Clarification path — return a structured "needs clarification" response instead of a generic failure, ideally distinguishing Q13's case (user is asking for duration) from Q14's case (user didn't supply one). Requires parser intent-detection or a fallback question generator. Not currently implemented; flagged as a candidate for the not-yet-implemented clarification functionality.

  Recommendation: defer the decision past MVP demo, since none of the three is clearly right. The journal records the question; the product call comes later.

- 🟡 Audit-shape inconsistency on failure path — Q13/Q14 confirm: organism uses internal id; combase_model and system are null. Worth a small fix-up so failure-path responses are renderable consistently with success-path ones.

- The Q13 "3 logs target silently dropped" finding doesn't apply here (Q14 has no target). But the design discussion would benefit from Q14's outcome as input: even when nothing is being inverted, the failure mode is identical.

---

## Q15 — Fictional food / both pH and aw default

### Goal
Tests the audit shape when the user specifies a food that doesn't exist in the knowledge base. Tests `attempted_top` field — when retrieval runs but returns nothing above threshold, attempted_top should populate with the best-rejected candidate and a skip_reason.

### Query
> "Predict B. cereus growth on zarblax burger at 25 C for 4 hours."

### Expected
- B. cereus, T = 25, duration = 240 → USER_EXPLICIT
- pH and aw → retrieval attempted, all candidates fail thresholds, `top_match: null`, `attempted_top` populated with the best-rejected doc and skip_reason
- defaults_imputed[2]
- Source = CONSERVATIVE_DEFAULT for both, with retrieval block populated

### Actual (post-audit-shape-fix, 2026-05-01 19:46 UTC, ptm 6d8aa38, verbose=true)
- B. cereus, T = 25, duration = 240 ✓ USER_EXPLICIT
- pH = 7.0, source = CONSERVATIVE_DEFAULT, retrieval block populated ✓:
  - query = "zarblax burger pH acidity" (Tier 2 fallback fired)
  - top_match = null (no doc passed Tier 2 threshold 0.62)
  - attempted_top = food_properties_184 (pimiento canned acidified), embed 0.4914, rerank -6.3792, **skip_reason: "failed_embedding_threshold:0.62"**
  - runners_up: milk acidophilus, curry paste acidified (also far below threshold)
- aw = 0.99, source = CONSERVATIVE_DEFAULT, retrieval block populated ✓:
  - query = "zarblax burger water activity aw moisture" (Tier 2)
  - top_match = null
  - attempted_top = food_properties_25 (fresh meat), embed 0.4778, rerank -5.7527, skip_reason same
  - runners_up: pudding, cured meat
- defaults_imputed[2], range_clamps[0], warnings[0]
- system block: 5/5 ✓
- μ_max = 1.19, log_increase = 2.07 (~119× population)

### Findings

**Three audit shapes for retrieval-or-default outcomes are now distinct.** Pre-fix, the audit conflated three different states into two indistinguishable shapes. Post-fix:
- `retrieval: null` — no retrieval was needed (USER_EXPLICIT or rule_match value)
- `retrieval: { top_match: null, attempted_top: {...} }` — retrieval ran, all candidates failed threshold, defaulted (Q15's case)
- `retrieval: { top_match: {...} }` — retrieval succeeded, value used

Closes the third audit-honesty thread for retrieval representation. See cross-cutting findings.

**Both tiers ran before defaulting.** skip_reason references threshold 0.62 (Tier 2 fallback), confirming Tier 1 missed first (silent), then Tier 2 fired with the per-field query, then Tier 2 also missed, then default. So "zarblax burger" exercises the full retrieval pipeline before falling through. The audit shows the user that the system tried twice before guessing.

**The cross-encoder rerank scores are revealingly negative.** For pH, attempted_top has rerank -6.38; runners-up at -7.79 and -8.59. All candidates are scored as "actively bad matches" by the cross-encoder. The system's best-rejected candidate isn't a near-miss — it's the least-bad of a uniformly poor set. This is exactly what we should see for a fictional food, and the audit shows it honestly.

**🟡 Minor: Tier 1 attempt is not separately surfaced.** When both tiers fail, the audit shows only the Tier 2 best-rejected candidate. Tier 1's best-rejected (the doc Tier 1 came closest to passing threshold with) is invisible. For Q15 this loss is small because both tiers return uniformly poor results, but in a query where Tier 1 had a near-miss and Tier 2 returned something different and worse, only the worse Tier-2 result would show. Filed as a minor audit-completeness item, low priority.

**Q01 vs Q15 demo comparison.** Q01 (B. cereus, 25 C, 4h, pH 6.0, aw 0.95) gives log_increase = 0.21. Q15 (same conditions, defaulted pH 7.0 and aw 0.99) gives log_increase = 2.07 — about 600× more predicted growth. The defaults are *more* growth-favorable than realistic food properties, by design. **A fictional food gets a more alarming prediction than a real food with realistic properties.** This is what conservative defaults should do (produce maximum growth), but demo-relevant: the audit's transparency about defaults matters because the user wouldn't otherwise know the prediction was based on optimum-growth conditions, not their actual food.

### Conclusion
Pass. Audit shape now distinguishes "no retrieval needed" from "retrieval attempted and failed" from "retrieval succeeded." Q15's captured shape is the canonical example for the second case. Demo-relevant: pair with Q01 to illustrate the cost of defaults; pair with Q03 to illustrate the gradient from "known food" to "unknown food."

### Followups
- ✅ attempted_top populating for fictional foods — closed 2026-05-01. Two-direction Phase 2 design (Direction A: always run RAG, surface attempted_top; Direction B: structured retrieval_skipped event) was resolved in favor of Direction A. Fix landed in translation.py:228-290. Six new regression tests in test_api_translation.py.
- 🟡 Tier 1 best-rejected candidate not surfaced when both tiers fail. Audit currently shows only Tier 2 attempted_top. Low priority.
- 🟡 Cumulative bias warning (§11.1) still unimplemented. Q15 has 2 defaults; threshold is ≥3. Reachable by also dropping the organism. Out of scope for MVP.
- The Q01 vs Q15 prediction-comparison is a useful demo angle — demonstrates conservative defaults producing more aggressive predictions than realistic data would. Worth highlighting.

---

## Q16 — User-supplied range / structural test

### Goal
Tests whether user-supplied ranges (e.g. "pH 5.5–6.0") flow through the same range_bound_selection path as RAG-retrieved ranges. Q03 showed RAG-retrieved ranges narrowed transparently with full audit. Q16 tests the same heuristic on user input.

### Query
> "Predict B. cereus growth on white bread at pH 5.5–6.0, 25 C, for 4 hours."

### Expected (post-fix)
- pH → USER_EXPLICIT, parsed_range [5.5, 6.0], range_bound_selection upper → 6.0, raw_match preserved
- aw → RAG retrieval on bread (range narrowed to upper)
- T, duration, organism → USER_EXPLICIT
- range_clamps, defaults_imputed, warnings all empty

### Actual (2026-05-01 20:11 UTC, ptm 6d8aa38, verbose=true, post-fix)
- pH = 6.0 ✓, source = USER_EXPLICIT, extraction.method = "direct", **raw_match = "5.5–6.0"** (original en-dash preserved!), **parsed_range = [5.5, 6.0]** ✓, **standardization.rule = "range_bound_selection"** with direction="upper", before_value=[5.5, 6.0], after_value=6.0 ✓
- aw = 0.97 ✓ RAG_RETRIEVAL, range_bound_selection upper [0.94, 0.97]
- B. cereus, T, duration USER_EXPLICIT ✓
- range_clamps[0], defaults_imputed[0], warnings[0] ✓
- system block: 5/5 ✓
- μ_max = 0.318, log_increase = 0.55 (~4× population)

### Findings

**User-supplied ranges now structurally equivalent to RAG-supplied ranges.** Audit shape for pH (USER_EXPLICIT range) and aw (RAG_RETRIEVAL range) is identical in this response: both have parsed_range, both have range_bound_selection events with direction, before_value, and after_value. The only difference is the source field — which honestly represents where the value came from. Same architecture, two paths, one audit shape.

**The original phrasing is preserved.** raw_match = "5.5–6.0" with the en-dash. The audit records what the user typed, not a normalized form. Compare with the still-open Q06 finding where rule_match's matched_pattern records the canonical, not the original — range-extraction here demonstrates the better convention.

**Prediction shifted to conservative direction.** Pre-fix: Q16 returned pH=5.5 (lower bound, anti-conservative for growth), log_increase = 0.42. Post-fix: pH=6.0 (upper bound, conservative for growth), log_increase = 0.55 — about 30% higher prediction. Closer to optimum → faster growth → more alarming prediction → correctly conservative. Same input, more correct output.

### Conclusion
Pass. Closes the fourth audit-honesty thread for retrieval/extraction representation. Demo material now stronger: pair Q16 with Q03 to show user-supplied and RAG-supplied ranges being treated identically, with full traceability.

### Followups
- ✅ User-supplied ranges through range_bound_selection — closed 2026-05-01. Symmetric three-touch-point fix (ExtractedEnvironmentalConditions schema + parser prompt + _ground_environmental_conditions). Six new test cases. Lessons.md entry on "symmetric paths to the same destination" pattern. Files touched: app/models/extraction.py, app/services/extraction/semantic_parser.py, app/services/grounding/grounding_service.py, tests for both layers, ptm_context.md §5.1.
- 🟡 The Q06 rule_match audit-honesty issue (matched_pattern records canonical, not original) is structurally similar but at a different site. Same principle (audit should record original input); same pattern of fix (extend the data structure to carry both). Filed as separate followup; not in scope for this fix.
- The aw-monotonicity issue at boundary (Salmonella μ_max peaks at 0.99, dips at 1.0) — not relevant for B. cereus / aw 0.97 here. Pre-existing finding from Q04.

---

## Q17 — Multi-step refrigeration → transport scenario

### Goal
Tests multi-step prediction architecture — the only feature in the schema (`is_multi_step`, `steps`, `step_predictions`) that no captured response in Q01–Q16 has populated. Real-world cold-chain scenario: chicken refrigerated, then transferred to a warmer truck. Two temperature regimes across one continuous duration.

This is the canonical Q17. A pre-recapture attempt (*"Our chicken was held at 4 C until the chiller failed 6 hours ago. It's now reading 13 C..."*) failed with `Missing required values: duration (step 1)`. That capture proved the parser distinguishes multi-step from single-step queries, but didn't reach the prediction step. The re-crafted query supplies both step durations explicitly.

### Query
> "Our chicken was held at 4 C for 24 hours, then transferred to a truck where it spent 6 hours at 13 C. Predict pathogen growth across the whole period."

### Expected
- is_multi_step: true, steps[] has 2 entries, step_predictions[] populated for both
- Step 1: 4 C, 1440 min (24h) — likely clamped to model floor (7 C for Salmonella growth)
- Step 2: 13 C, 360 min (6h) — within model range
- pH, aw retrieved once at query level (Tier 2 fallback patterns from Q04)
- organism inferred via §2.4 (Salmonella by deaths-ranking)
- Aggregate log_increase across both steps

### Actual (2026-05-01 20:15 UTC, ptm 6d8aa38, verbose=true)
- is_multi_step: true ✓
- steps[]: [{step_order: 1, T: 7 C, t: 1440 min}, {step_order: 2, T: 13 C, t: 360 min}] ✓
- step_predictions[]: [{step 1: μ_max=0.030, log_increase=0.315}, {step 2: μ_max=0.132, log_increase=0.343}]
- Aggregate total_log_increase = 0.659 (~5× population)
- Step 1 temperature clamped from 4 C to 7 C ✓, range_clamp event recorded
- pH = 6.4 RAG_RETRIEVAL_FALLBACK (Tier 2, Q04 pattern), upper bound
- aw = 1.0 RAG_RETRIEVAL_FALLBACK (Tier 2, Q04 pattern), upper bound
- Salmonella ✓ §2.4 ranked_by_annual_deaths
- system block: 5/5 ✓

### Findings

**Multi-step prediction works end-to-end.** The orchestrator parses the two-regime structure, evaluates the growth model for each step with its own duration, and aggregates log_increase by summation. Step durations are honored (1440 min and 360 min, not split or averaged). Step temperatures are honored (7 C clamped from 4 C; 13 C unchanged). The prediction is internally consistent — sum of step log_increases equals the aggregate, which is the correct kinetic combination for consecutive growth phases.

**Cross-step shared retrievals work as expected.** pH and aw are retrieved once at the query level and apply to both steps. This is correct (the chicken's properties don't change between refrigeration and transport). The audit shows a single retrieval block per field. The step_predictions[] entries don't carry their own pH/aw — the inputs that vary across steps are temperature and duration only.

**🟡 Audit shape inconsistency: aggregate vs step-1 conventions.** The top-level prediction has two fields:
- `temperature_celsius: 7` — step 1's clamped value (not aggregate, not step 2's)
- `duration_minutes: 1800` — sum of step 1 + step 2 durations (1440 + 360)

So the top-level represents temperature as "step 1 only" but duration as "aggregate." Two conventions for two fields. A frontend reading top-level prediction values needs to know that some fields aggregate across steps and some don't. Probably an artifact of the schema being extended for multi-step — the single-step shape was preserved at the top level, with `steps[]` and `step_predictions[]` added underneath.

**Per-step range_clamp uses string-encoded step identity.** The `range_clamps[].field_name` is `"temperature_celsius (step 1)"` — the step identifier is a string suffix. The structured `step_order: 1` exists in `steps[]` and `step_predictions[]` but not in `range_clamps[]`. A consumer parsing the field_name needs to do string matching to extract the step identity. Minor structural inconsistency; could be addressed by adding a structured `step_order` field to the range_clamp entry.

**🟡 Same "clamp produces science-divergent prediction" pattern as Q06 and Q10.** Salmonella growth threshold in reality is ~5 C; the ComBase model floor is 7 C. Step 1 at 4 C is below the actual biological threshold for any growth. The clamp pushes evaluation to 7 C and the model produces μ_max = 0.030 — slow growth, but *non-zero growth*. Real-world answer at 4 C is ~zero growth. Net effect: step 1 contributes a 0.315 log_increase to the aggregate that shouldn't really be there if the science said "no growth at 4 C."

This is the third capture demonstrating the pattern (Q06, Q10, Q17). In each, the clamped value is at the model's growth boundary; the model evaluates and produces non-zero growth; the actual physical condition was below where any growth occurs. The audit is honest (clamp recorded, warning issued) but the prediction *value* implies growth where the science says there isn't. See cross-cutting findings.

**Aggregate prediction is reasonable.** Total log_increase = 0.66, ~5× population over the 30-hour scenario. Sanity-checks: step 2's contribution (0.343 over 6h at 13 C) is ~half the rate Q11 produced for chicken-Salmonella at 25 C/8h (which gave log_increase = 3.22). 13 C vs 25 C and 6h vs 8h together give roughly 0.343/3.22 ≈ 11%, which is consistent with the ~10× growth-rate reduction from 25 C to 13 C. The math is consistent across captures.

**The previous Q17 failure capture (multi-step parsing without step 1 duration) is supplementary evidence.** The error message "Missing required values: duration (step 1)" proved the orchestrator distinguishes multi-step from single-step queries even when the prediction can't run. With the canonical Q17 capture, multi-step prediction is now fully verified.

### Conclusion
Pass. Multi-step parsing AND prediction work end-to-end. Audit shape scales to multi-step correctly (steps[] and step_predictions[] populated, range_clamp identifies the affected step, single-shared-retrieval pattern for cross-step properties). Two minor audit-shape inconsistencies (aggregate vs step-1 conventions at top level; string-encoded vs structured step identity in range_clamps) — non-blocking but worth flagging.

The "clamp produces science-divergent prediction" pattern surfaced for the third time, now consolidated as a cross-cutting finding rather than a per-query one.

### Followups
- 🟡 **Consolidated finding: range_clamp into model boundary from below-threshold conditions.** Q06, Q10, Q17 all surface this. See cross-cutting findings. Filed as a single concern rather than three.
- 🟡 Aggregate vs step-1 conventions at top level: temperature_celsius is step-1, duration_minutes is aggregate. Document or reconcile.
- 🟡 String-encoded step identity in range_clamps: add structured step_order field.
- ✅ Multi-step capability is now demonstrated end-to-end in the journal. Closes the journal's last major heuristic coverage gap.

### Demo positioning
This is the journal's strongest "complete capability" capture. Multi-step parsing, multi-step prediction, range_clamp on a step-specific field, §2.4 pathogen inference, Tier 2 fallback for both pH and aw, single-shared-retrieval pattern across steps — all in one response. Worth highlighting in the demo as the integration test the journal arrived at by the end. The audit-shape inconsistencies are real but small enough to mention briefly rather than dwell on.

---

