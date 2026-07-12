---
id: 2026-07-12-164408-unpinned-cross-boundary-enums
date: 2026-07-12
status: open
finding_kind: bug-class
review_context: "tuning-system deep review / claude/tuning-system-review-7mzapy"
related_paths:
  - benchbox/core/schemas.py
  - results-explorer/src/lib/facetMatching.ts
  - _project/scripts/explorer_pipeline/transformer.py
suggested_sweep: "list every string enum that crosses Python -> bundle JSON -> TypeScript (status, mode, phase names) and check whether both sides pin the same value set"
todo_id: null
---

# String enums that cross the Python/JSON/TypeScript boundary are never pinned

## Finding
`tuning_mode` is a free string on both sides: Python emits `tuned/notuning/auto/<raw path>` plus
`balanced` from the wizard; the explorer defaults missing values to `untuned` — a token no
producer emits — and the ingest pipeline reads the field from a different JSON path than older
bundles wrote it to. Each side has tests using its own literals; no shared artifact pins the
vocabulary, so producers and consumers drift per-generation and per-language without any test
failing.

## Why this matters
Cross-boundary enums are contracts, but as bare strings they are invisible to both type systems.
The drift failure mode is semantic (facets match wrong things, badges show wrong labels), not a
crash, so it survives green CI indefinitely. The same class applies to validation statuses,
phase names, and comparability facets generally.

## Suggested next steps
- [ ] Pin shared vocabularies in one schema artifact consumed by both Python and TS tests.
- [ ] Make consumers distinguish "value absent" from "value = baseline" instead of defaulting.
