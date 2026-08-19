# PTM — Consolidate & simplify organism clarification (free-text only)

Read `coding_guidelines.md` and `specs/lessons.md` first. Commit as one coherent change (or two: backend, then the frontend-contract note).

## Why this change exists

Confirmed live: the organism reply path runs the user's answer through an LLM (`extract_clarification_response()`), and that LLM returns an **empty extraction ~50% of the time** for a clean, one-word menu label ("Salmonellae") — same input, 2/6 success across identical runs. The failure is LLM nondeterminism on data that was never ambiguous. The fix is not to make the LLM reliable; it is to **remove the LLM from the reply path entirely** and let the user answer in free text, resolved by the same deterministic path a first-turn pathogen mention already uses.

This is a **simplification** — it deletes the options menu, the LLM extraction step, the menu-vs-freetext fork, and the offered-set validation gate. Four things removed, one nondeterministic bug killed, one code path (`all_matches_in_text()`) reused instead of duplicated.

## The design

**Organism clarification becomes: ask a question, accept free text, resolve deterministically.**

1. **No options array, no menu.** The organism clarification response no longer carries an `options` list. It carries a question string only.

2. **The question names a few example pathogens in prose** — e.g. "…tell me which pathogen you're concerned about (for example Salmonella, Listeria, or E. coli)." This restores discoverability (the one thing the menu gave) with zero mechanism: it's words in the question the frontend already renders verbatim, not a structured options list. Pick 3–4 common, executable examples for the prose hint.

3. **The reply is free text, resolved by `all_matches_in_text()`** — the exact deterministic substring-alias path a first-turn `pathogen_mentioned` uses (`grounding_service.py:~606` area). Recon confirmed this resolves "Salmonellae", "Salmonella", and sentences containing them correctly, every time. Run the raw `user_reply` through it directly. **No LLM.**

4. **Remove `extract_clarification_response()` from the organism reply path.** It is the confirmed failure point and step 3 bypasses it. Leave the function defined if anything else references it, but confirm the organism path no longer calls it.

5. **Drop the offered-set gate** (`candidate not in offered_codes → reject`). There is no offered set anymore. The **executability check stays** — it is the real safety boundary. A reply may name any *executable* organism; a non-executable one still fails closed with its plain reason.

6. **Keep the existing fail-closed guards:** empty match (no organism named) → fail closed; multiple distinct organisms named → fail closed (ambiguous); skip/refusal → fail closed with no default. These are correct and unchanged.

7. **Reframe the clarification copy** to match the confirmed mechanism. ComBase models are broth — the food never enters the polynomial; its only job was pathogen inference (and, for one stage, pH/aw lookup). So the honest framing asks for the *pathogen*, not "more about the food":
   - `food_unrecognised`: the food couldn't be used to infer which pathogen to model. Ask for the pathogen directly; note rephrasing the food *might* also help.
   - `category_has_no_hazard_data`: the food was recognized and its pH/water-activity resolved fine — this is *purely* about pathogen inference, the hazard source doesn't cover this food's category. Ask for the pathogen; note that rephrasing the food won't help (it's a data-coverage limit).
   - Keep the two stages' wording distinct — the difference is the whole point of the two-stage machinery.

## Duration clarification — explicitly unchanged

Do **not** touch duration clarification. It stays structured-numeric (a number per step, no LLM). Duration is a continuous open quantity with no deterministic text parser — free-texting it would re-introduce exactly the LLM-guess this change removes from organism. The two paths stay different because the data types differ and safety follows the data type. This is deliberate, not an oversight.

## Frontend contract impact — REPORT BEFORE CHANGING

This changes the response and request shapes. **Report the exact new shapes; do not modify the frontend from here** (it has its own Claude Code):

- **Response:** the organism `clarification` object loses its `options` array. Confirm what it now carries (`reason`, `stage`, `question` — question now contains the prose pathogen examples). The frontend currently renders a menu from `options`; with `options` gone it must render a free-text input instead. State this clearly for the frontend spec.
- **Request:** the reply no longer needs `options_offered` echoed back (there are no options). Confirm the minimal `transcript` shape now — likely just `original_query` + `user_reply` (free text). If `options_offered` becomes optional/removed, say so.
- Report both shapes precisely; I will spec the frontend change separately from your report.

## Non-goals

- No change to duration clarification (see above).
- No change to the executability check itself.
- No new organism default or substitution.
- No change to first-turn scenario extraction — only the *reply* path.

## Acceptance

- **The flakiness is gone (the key test):** a reply of "Salmonellae" resolves to `SALMONELLA` **6/6 across 6 runs**, not 2/6. Determinism is the whole point.
- A free-text reply naming an executable organism that would *not* have been in the old top-5 menu (e.g. Staphylococcus aureus) now resolves and predicts.
- A reply naming a non-executable organism (e.g. Shigella in a growth scenario) still fails closed with the plain reason.
- A reply naming two organisms still fails closed (ambiguous).
- An empty/irrelevant reply still fails closed.
- The organism clarification response contains **no** `options` array; its `question` contains prose pathogen examples.
- No organism reply path calls `extract_clarification_response()` (grep to confirm).
- `pytest`, `black`, `ruff`, `mypy` on touched lines.

## Docs

- `specs/specifications.md`: organism clarification section (options removed, free-text resolution, copy reframed), §3.5/§4.4/§11.1 for the response-shape change, §14 if terms change.
- `docs/ptm_context.md` if the clarification flow is described there.
- `specs/lessons.md`: the mechanism and the lesson — *a deterministic user choice (or a string resolvable by a deterministic matcher) should never be routed through an LLM; the LLM was a nondeterministic round-trip on data that was already clean, and deleting it was simpler and more correct than hardening it.* Note this is the organism-specific counterpart to the duration decision (structured input, no LLM) — same principle, arrived at from opposite directions.

Report the frontend contract shapes before/alongside implementing. Invoke the code-reviewer agent with commit-history context.
