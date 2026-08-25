---
name: clamping_decouple_review
description: Independent verification of the two-commit clamping decouple (ffcc242 dead-path removal, 9ecdeb5 clamp-arithmetic relocation to PTM) — 2026-08-22
type: project
---

## What happened
Two commits on `main`, following the `predictive/` relocation (`51b4369`, out of scope):
- `ffcc242` (Step 1): removed `ComBaseCalculator.calculate()`'s dead `clamp_to_range: bool`
  parameter and its four internal clamp branches. Engine still validates and warns on
  out-of-range input, just never clamps.
- `9ecdeb5` (Step 2): deleted `ComBaseModelConstraints.clamp_temperature/clamp_ph/clamp_aw/
  clamp_factor4()` (each exactly `max(min, min(v, max))`, factor4 had a `None`-bounds
  passthrough guard). `StandardizationService._clamp_to_constraints()` now computes the
  clamp itself inline instead of taking an injected `Callable`; one hand-inlined multi-step
  temperature site got the same treatment.

## Verification techniques used (reusable)
- **Dead-path proof, done properly**: don't just trust "grep confirms X passed once" in the
  commit message — re-run the grep yourself at the *parent* commit (`git grep -n <term>
  <parent-sha> -- <paths>`), not at HEAD where the code is already gone. Confirmed
  `clamp_to_range=True` appeared exactly once repo-wide (the removed test), and the
  production caller (`engine.py`) had it as a hardcoded literal `False`, not a variable —
  the strongest form of dead-code proof (no config or future caller could flip it without a
  code change).
- **mypy content-identical, not just count-identical**: matching error *counts* (151/151) is
  not proof of no behavioral mypy delta — build a worktree at the pre-change commit, run
  mypy on both trees, normalize `:LINE:COL:` away, sort, diff. Zero diff confirms the error
  *set* is identical, not just its size. (Same technique as the `predictive_relocation_review`
  memory; reused here for a much smaller diff and it still mattered — `_clamp_to_constraints`
  changed its signature substantially, so count-matching alone would have been weak evidence.)
- **Bare-name grep, not just call-pattern grep**: after confirming `\.clamp_temperature(` etc.
  return zero hits, also grepped the bare method names (`clamp_temperature` etc. with no
  `.` or `(`) across `*.py` to catch stray docstring/comment/dynamic-attribute-access
  references. Also zero — confirms no stale prose describing the engine as still clamping.
- **Factor4 None-guard deadness re-derived independently**: read
  `standardization_service.py`'s `_get_factor4()` (around line 466-492) directly — confirmed
  it fails closed via `missing_required` at line 475-480 (`constraints.factor4_min is None or
  constraints.factor4_max is None`) *before* ever calling `_clamp_to_constraints()`, so the
  deleted `clamp_factor4()`'s `None`-bounds passthrough branch really was unreachable from
  this caller. This is a claim worth re-deriving per review, not taking on faith, since it's
  the one deleted branch with logic beyond the bare one-liner.

## Confirmed-clean claims (independently re-verified)
- `clamp_to_range` and all four `clamp_temperature`/`clamp_ph`/`clamp_aw`/`clamp_factor4`
  references (calls AND bare mentions) are zero repo-wide at current HEAD.
- `is_temperature_valid`/`is_ph_valid`/`is_aw_valid`/`is_factor4_valid` untouched — same
  bodies, still present, only the four `clamp_*` action methods were deleted.
- `predictive/` still imports nothing from `app.*` (grep clean, unaffected by either commit).
- `tests/unit/test_model_type_aware_bias.py::TestRangeClamping`,
  `test_factor4_standardization.py`, `test_full_pipeline.py`: zero diff in `9ecdeb5` per
  `--stat`, confirmed by reading `TestRangeClamping`'s asserted values (50→42, 2→10 against
  a test-local `_make_registry_with_constraints`, not the real CSV — self-contained, doesn't
  depend on production bounds data) and factor4's 500→200 nitrite clamp test — arithmetic is
  correct and matches pre-refactor behavior.
- Full suite: 1416 passed at current HEAD (matches commit message's post-Step-2 count
  exactly). `mypy app`: 151 errors, content-identical pre/post Step 2 (worktree-diffed, not
  just counted). `pytest tests/integration/test_response_snapshot_baseline.py`: 4/4 passed
  (clean_growth, multi_step, thermal_inactivation, clamped_temperature) — byte-identical
  proof of output equivalence. `ruff check` and `black --check` clean on all 6 touched files
  across both commits.
- `Callable` import in `standardization_service.py` still used (for the `is_valid` param
  type) — not an orphaned import after the `clamp: Callable` param was removed.

## Real finding from this review (process, not correctness)
- **specs/specifications.md and specs/lessons.md were NOT committed in either `ffcc242` or
  `9ecdeb5`** (`git show <sha> --stat` for both lists only the 3 code/test files each; `git
  log -1 -- specs/specifications.md` / `specs/lessons.md` both point to the *earlier*
  `51b4369` relocation commit, not either of the two reviewed commits). The current working
  tree DOES have well-written uncommitted edits to both files describing the "2026-08-22
  clamping decouple" accurately (verified via `git diff --stat`: +14/-0 lessons.md, +10/-5
  specifications.md) — content is good, just not yet landed in the commits it documents.
  This is a direct miss of CLAUDE.md's "Update them in the same change that motivates the
  update, not at session end" for the Living Documents section. Flagged as MEDIUM severity:
  the content itself is accurate and thorough, but as of this review the two commits on
  `main` are not accompanied by their documentation in the same change.

## Domain-specific note
This is a pure policy-relocation refactor (moving 4 one-line arithmetic formulas + deleting
one always-`False` dead flag) with no clamping *direction* or *default* changes — the model-
type-aware bias direction (`UPPER` for growth, `LOWER` for thermal) and conservative defaults
are untouched by both commits, confirmed by reading the surrounding
`_get_temperature`/`_get_factor4` methods directly rather than assuming from the diff stat.
