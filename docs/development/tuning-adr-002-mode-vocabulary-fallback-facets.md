# ADR-002: Tuning Mode Vocabulary, Fallback Labeling, and Facet Semantics

**Status**: Accepted (2026-07-12, decided by Joe)
**Decision gate**: `_project/DONE/main/active/tuning-adr-mode-vocabulary-fallback-facets-20260712.yaml`
**Source review**: tuning-system deep review 2026-07-12 (`claude/tuning-system-review-7mzapy`), findings C4-C6, evidence pinned to commit `acfb8992`

## Context

Three related gaps surfaced in the 2026-07-12 tuning-system review:

1. **Silent fallback mislabeling.** When `--tuning tuned` is requested but no platform/benchmark
   template can be found, `benchbox/cli/tuning_resolver.py:295-307` falls back to a bare
   constraints-only config and logs `"Tuning mode: tuned (fallback - no template found)"` — the
   run is still recorded with mode `tuned`. `benchbox/cli/commands/run.py:1016-1022` does not
   surface this distinction to the run record either. Downstream, this fallback run
   facet-matches genuinely curated-template `tuned` runs with no indication that it used a
   different code path (`TuningSource.FALLBACK` already exists internally in
   `tuning_resolver.py:47` but is not reflected in the recorded `tuning_mode`).

2. **No pinned vocabulary.** `benchbox/cli/tuning.py:52,56` and callers emit `tuned`,
   `notuning`, `auto`, the wizard's `"balanced"` string (a template flavor, not a mode), and,
   for custom configs, the raw file path passed to `--tuning` (`RunArgs.tuning_mode` docstring
   in the CLI args model: `# "tuned", "notuning", "auto", or path`). Raw paths leak local
   filesystem layout into shared result bundles and are not a stable comparability key. On the
   explorer side, `results-explorer/src/lib/facetMatching.ts:99` defaults a missing
   `tuning_mode` to the invented string `"untuned"`, which exists nowhere in the Python
   vocabulary and is indistinguishable from an intentional `notuning` run.
   `results-explorer/src/components/TuningBadge.tsx` (`TUNING_CONFIG`) independently hardcodes
   `tuned` / `notuning` / `auto` with an unlabeled fallback bucket for anything else — including
   `"balanced"` and raw paths — as `"Custom Tuning"`.

3. **Coarse cross-platform facet.** `tuning_mode` is currently the sole signal
   `matchesFacetKey` uses for the `tuning_mode` facet (`facetMatching.ts`, `case "tuning_mode"`).
   Two `tuned` runs on different platforms facet-match even when one platform renders six
   physical tuning mechanisms (indexes, clustering keys, distribution styles, etc.) and another
   renders zero for the same benchmark, because platform capability differences are invisible
   at the mode-string level.

## Decision

1. **Fallback labeling.** A `--tuning tuned` run that resolves via
   `TuningSource.FALLBACK` (no template found) is recorded with a distinct canonical mode value,
   `tuned-fallback`, instead of `tuned`. `tuned-fallback` runs are refused under `--official`
   (non-interactive/official runs must either find a real template or explicitly choose
   `notuning`/`custom`). Wizard-produced configs (`TuningSource.INTERACTIVE_WIZARD`) get source
   provenance `wizard` recorded alongside the mode, distinguishing "tuned via wizard" from
   "tuned via auto-discovered template" without inventing a new mode value.

2. **Vocabulary pin.** The canonical `tuning_mode` value set is exactly:

   - `tuned` — auto-discovered or explicit curated template applied
   - `tuned-fallback` — `--tuning tuned` requested, no template found, basic constraints used
   - `notuning` — tuning explicitly disabled
   - `auto` — platform/engine automatic tuning selected
   - `custom` — user-supplied tuning file, recorded as a template reference/hash, never a raw
     local path

   Raw file paths are not a legal `tuning_mode` value under any circumstance; a custom-file run
   emits `custom` plus a separate template reference/hash field, keeping bundles free of local
   path leakage. The wizard's `"balanced"` string is a template flavor selector, not a mode, and
   must map into this set (typically `tuned`, with the flavor recorded as a separate attribute)
   rather than appearing verbatim as `tuning_mode`. Absent/unrecorded `tuning_mode` (older
   bundles, ingest gaps) is represented as a distinct "not recorded" state in both ingest and UI
   — never coerced to `notuning` or to an invented string like `"untuned"`. The vocabulary is
   defined once in a single shared artifact consumed by both the Python and TypeScript test
   suites, so the two sides cannot drift independently again.

3. **Facet rule.** `tuning_mode` remains the coarse comparability facet with exact-match
   semantics over the pinned vocabulary above (no fuzzy or path-based matching).
   `ComparabilityReceipt` gains a warning — not a match failure — when two runs both labeled
   `tuned` have disjoint physical tuning mechanism sets, so cross-platform "tuned vs tuned"
   comparisons stay facet-matchable but visibly flagged. `physical_rendering_id` becomes a
   secondary, independently matchable facet for TPC benchmarks, letting users narrow to runs
   that rendered the same physical mechanisms without changing the coarse facet's semantics.
   Unknown/not-recorded `tuning_mode` never silently matches `notuning` under exact-match
   comparison.

## Consequences

- `tuning-mode-vocabulary-and-facet-implementation-20260712` implements the vocabulary pin,
  fallback labeling, `wizard` source provenance, and the shared vocabulary artifact across
  `benchbox/cli/tuning_resolver.py`, `benchbox/cli/tuning.py`, `benchbox/cli/commands/run.py`,
  and `benchbox/core/schemas.py`.
- `tuning-explorer-ingest-mode-extraction-20260712` updates explorer ingest and
  `facetMatching.ts`/`TuningBadge.tsx` to consume the shared vocabulary, drop the invented
  `"untuned"` default in favor of an explicit "not recorded" state, and add the
  `physical_rendering_id` secondary facet.
- `tuning-soundness-test-coverage-20260712` adds cross-language test coverage asserting Python
  and TypeScript agree on the pinned vocabulary and that the `--official` refusal for
  `tuned-fallback` is enforced.
- Existing bundles with `tuning_mode: tuned` produced via the fallback path, or with raw file
  paths as `tuning_mode`, are not silently reclassified retroactively; ingest treats
  unrecognized values as "not recorded" rather than guessing which bucket they belong in.

## Rejected options

- **Keep the `tuned` label for fallback runs.** Rejected: it is the root cause of finding C4 —
  fallback runs facet-match curated-template runs with no signal that a materially different
  (unoptimized) configuration was used, which silently corrupts head-to-head comparisons.
- **Strict mechanism-based facet matching** (fold physical mechanism sets directly into the
  `tuning_mode` facet match, so platforms with different mechanism counts never match even when
  both are `tuned`). Rejected as the default: it would fragment comparability across platforms
  that legitimately differ in how many physical mechanisms a given template exercises, making
  routine cross-platform "tuned" comparisons unreasonably hard to find. The receipt-level warning
  plus the new `physical_rendering_id` secondary facet gives users the same visibility on demand
  without narrowing the default facet.
