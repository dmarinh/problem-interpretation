---
name: predictive_relocation_review
description: Findings and verification techniques from the app/engines + app/models/execution + engine-enum relocation to top-level predictive/ package (2026-08-22)
type: project
---

## What happened
`app/engines/*` and `app/models/execution/*` (9 files) moved verbatim to a new top-level
`predictive/` package (peer of `app/`). `app/models/enums.py` was split: engine-owned enums
(ModelType, ComBaseOrganism, Factor4Type, EngineType, plus ComBaseOrganism.from_text() /
all_matches_in_text()) moved to `predictive/models/enums.py`; orchestration-only enums
(IntentType, ClarificationReason, OrganismGroundingFailureStage, SessionStatus,
RetrievalConfidenceLevel) stayed in `app/models/enums.py`. Reviewed pre-merge, uncommitted.

## Verification techniques that worked well (reusable for future relocation reviews)
- **Purity diff**: `git show HEAD:<old-path>` piped to a temp file, diffed against the new
  file with CRLF stripped (`sed -e 's/\r$//'`) — cleanly isolates import-line-only changes
  from real edits. All 9 moved files were byte-identical except import statements.
- **Enum-split correctness, repo-wide**: don't just spot-check the 2-3 files the task names.
  Grep every file importing from either enum module, then script-parse each `from X import
  (...)` block's names and check set membership against the known engine-enum /
  orchestration-enum lists. Caught zero misclassifications across ~30 files in this review —
  but this is exactly the kind of defect a 3-file spot-check would miss if the bug were in
  file #4.
- **mypy baseline via git worktree + normalized diff**: `git worktree add <tmp> HEAD` gives a
  true pre-move tree to run `mypy app` against, side by side with the current tree. Normalize
  both outputs (strip `:LINE:COL:`, rewrite `app\engines\`/`app\models\execution\` →
  `predictive\...`), sort, diff. Zero diff = true behavioral equivalence, not just matching
  counts. Matching *error counts* (151 vs 151) alone is not sufficient proof — this project's
  history already has one recorded incident of an agent concluding "16 baseline errors don't
  exist" from a raw grep that silently dropped the `app\engines\*` lines entirely (a filtering
  bug, not a real regression). Always sort+diff full normalized content, never trust a count
  match or a raw grep alone.
- **ruff/black pre-vs-post via the same worktree**, with `--no-cache` on both sides. Comparing
  just the touched-file list is not enough — run `ruff check .` (whole repo, `--no-cache`) on
  both trees and diff, because config changes（e.g. `known-first-party` in pyproject.toml) or
  even just the existence of a new top-level package directory can silently change ruff's
  isort classification for **unrelated, untouched files** elsewhere in the repo. Confirmed
  empirically in this review: adding `predictive/` as a real populated package (not just an
  empty dir, not just the pyproject.toml line alone — needed the full combination) caused two
  pre-existing I001 findings to vanish on files that had zero diff
  (`tests/unit/test_viz_charts.py`, `tests/unit/test_viz_data_loader.py`,
  `benchmarks/visualizations/app.py` + 2 more pages). Isolate variables (config-only, empty-dir-only,
  both) with the worktree to pin down what's actually causing a ruff delta before reporting it as
  either a regression or a non-issue.

## Confirmed-clean claims (independently re-verified, not just trusted)
- `predictive/` imports nothing from `app.*` (grep clean).
- No stray `app.engines` / `app.models.execution` references anywhere in the repo.
- Enum split is exact: engine-enum class bodies match byte-for-byte between original
  `app/models/enums.py` and new `predictive/models/enums.py`; orchestration-enum class bodies
  unchanged in `app/models/enums.py`.
- Every import site across app/tests/scripts/benchmarks correctly classified (engine enums
  from `predictive.models.enums`, orchestration enums from `app.models.enums`) — checked
  programmatically across every file importing either module, not just the 3 named in the
  task.
- `ComBaseOrganism.from_text()`/`all_matches_in_text()` travel with the enum, pure stdlib
  (`from enum import Enum` only), called only from orchestration code
  (orchestrator.py, grounding_service.py, clarification_service.py, metadata.py) — never
  from `predictive/engines/`.
- mypy baseline: 151 errors before and after, content-identical after path normalization
  (independently re-run, not just re-derived from provided capture files).
- ruff on `app tests`: findings that moved (enums.py → predictive/models/enums.py) net to
  zero as expected (5 UP042+SIM118 findings relocated intact).
- black on scripts/benchmarks: same 7-of-8 files need reformatting before and after — debt is
  genuinely pre-existing, not introduced (scripts/benchmarks aren't covered by the documented
  `black app tests` command anyway).

## Real (if minor) findings from this review
- `app/core/orchestrator.py` gained one new E402 (mechanical: splitting one combined
  `from app.models.enums import (...)` block into two statements — one `app.models.enums`,
  one `predictive.models.enums` — adds one more "import after `_log = ...`" line). Pre-existing
  E402 debt in this file (already 11 instances), so a 12th is low severity but is a genuine,
  verifiable new finding, not zero-diff.
- `scripts/test_multistep_pipeline.py` and `scripts/test_translate.py`: identical pattern in
  both — a 3-line local (in-function) import block where `app.engines.combase.engine` became
  `predictive.engines.combase.engine`; the repointed line is now out of alphabetical order
  relative to its neighbors (`app.core...`, `predictive.engines...`, `app.rag...`), triggering
  new I001. Auto-fixable with `ruff check --fix`, cosmetic only, but real — not covered by the
  "scripts/benchmarks pre-existing debt only" exemption since these are newly introduced.
- `_get_engine_registry()`'s "circular-import chain" comment in `standardization_service.py`
  (verbatim pre-existing, not reworded by this refactor) is now more clearly stale: since
  `predictive/` provably imports zero `app.*` (confirmed via repo-wide grep), a module-level
  import of `predictive.engines.combase.engine` from `app/services/standardization/` cannot
  participate in any cycle through `predictive` — there's no path back to `app`. Pre-existing
  ambiguity, not introduced by the move, but the move is a natural point to fix/clarify it.

## Domain-specific note
This relocation is declared zero-logic-change / zero-behavior-change, and independent
verification (byte-diff purity, mypy/ruff/black baselines) supports that claim overall — the
only deltas found are cosmetic lint findings (E402/I001), not logic. Standard safety-critical
review dimensions (conservative defaults, provenance, model-type bias direction) are out of
scope for this specific review since no clamping/default/provenance logic was touched — only
import paths and enum module location.
