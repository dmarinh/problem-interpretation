# Filed: standardization-block-as-a-list refactor (deferred)
Convert ValueProvenance.standardization from T | None to list[T] so chained events on the same field (e.g., range_bound_selection followed by range_clamp) are explicit rather than collapsed to last-event-wins.

Scope: small, mechanical. ~half day.
Touches: metadata model, API schema, standardization service (append vs overwrite), audit builder, tests, frontend (Zod + disclosure rendering).
Risk: one design question — does the disclosure render chained events as a sequence or stack them as parallel events? Resolve before implementation.
Why deferred: current "last-event-wins" workaround is correct for the common case. Refactor only matters when the chain case occurs in practice and audit honesty for it becomes load-bearing.
Trigger to revisit: when a regulator or downstream consumer asks why a clamp event "lost" its preceding range-bound selection in the audit, or when chained events become common enough to misread.

