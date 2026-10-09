# ADR-002: Tuning Mode Vocabulary, Fallback Labeling, and Facet Semantics

**Status**: Accepted (2026-07-12, decided by the project maintainer)

## Context

Three related gaps surfaced in a 2026-07-12 review of the tuning system:

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
   for custom configs, the raw file path passed to `--tuning` (`ExecutionContext.tuning_mode` comment
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

- The vocabulary pin, fallback labeling, `wizard` source provenance, and the shared vocabulary
  artifact apply across `benchbox/cli/tuning_resolver.py`, `benchbox/cli/tuning.py`,
  `benchbox/cli/commands/run.py`, and `benchbox/core/schemas.py`.
- Explorer ingest and `facetMatching.ts`/`TuningBadge.tsx` consume the shared vocabulary, drop
  the invented `"untuned"` default in favor of an explicit "not recorded" state, and add the
  `physical_rendering_id` secondary facet.
- Cross-language tests assert that Python and TypeScript agree on the pinned vocabulary and that
  the `--official` refusal for `tuned-fallback` is enforced.
- Existing bundles with `tuning_mode: tuned` produced via the fallback path, or with raw file
  paths as `tuning_mode`, are not silently reclassified retroactively; ingest treats
  unrecognized values as "not recorded" rather than guessing which bucket they belong in.

## Rejected options

- **Keep the `tuned` label for fallback runs.** Rejected: it is the root cause of the mislabeling in
  Context item 1 — fallback runs facet-match curated-template runs with no signal that a materially different
  (unoptimized) configuration was used, which silently corrupts head-to-head comparisons.
- **Strict mechanism-based facet matching** (fold physical mechanism sets directly into the
  `tuning_mode` facet match, so platforms with different mechanism counts never match even when
  both are `tuned`). Rejected as the default: it would fragment comparability across platforms
  that legitimately differ in how many physical mechanisms a given template exercises, making
  routine cross-platform "tuned" comparisons unreasonably hard to find. The receipt-level warning
  plus the new `physical_rendering_id` secondary facet gives users the same visibility on demand
  without narrowing the default facet.

## Addendum (2026-10-04): `--tuning tuned` on DataFrame platforms

Curated DataFrame profiles exist in `examples/tunings/dataframe/`
(`polars_optimized.yaml`, `pandas_optimized.yaml`, `cudf_optimized.yaml`, and
others). `--tuning tuned` searched only `<platform>/<benchmark>_tuned.yaml`
(`get_tuning_template_paths` in `benchbox/cli/tuning_resolver.py`), so on
DataFrame platforms it always resolved to `tuned-fallback`. On Polars that
fallback applied three streaming-runtime settings while the console said it was
"using basic constraints".

**Decision: resolve the curated profile, and keep the fallback distinct.**

- **Resolution order** in `get_tuning_template_paths`:
  1. `<platform>/<benchmark>_tuned.yaml`;
  2. `examples/tunings/dataframe/<platform>_optimized.yaml`, and its packaged
     mirror if one exists;
  3. `tuned-fallback`.
  A platform with no `<platform>_optimized.yaml` (Dask ships
  `dask_distributed.yaml` and no `dask_optimized.yaml`) continues to step 3.
- **Facet.** A run that resolves a curated profile reports mode `tuned`, with
  the resolved file recorded as the tuning source.
- **The fallback stays distinct.** `tuned-fallback` keeps its separate facet
  from Decision 1 above and never facet-matches a curated run. Tests cover both
  directions: a fallback run does not match a curated `tuned` run, and a curated
  `tuned` run does not match a fallback run.
- **Console text for the fallback comes from the capability registry per
  platform**, describing what that platform's fallback actually applies, for
  example "basic constraints", "engine runtime defaults (streaming)" or "OLAP
  session pack". A fixed string such as "using basic constraints" is not
  allowed, because it misdescribes platforms whose fallback applies more.

## Addendum (2026-10-09): what `tuned` promises

Decision 2 above defines `tuned` mechanically: a curated template is applied. It
says nothing about benefit, vendor guidance or comparability, so a template
that runs slower than `notuning` could not be called a defect, and a
tuned/notuning ratio could be read as a ranking of platforms. This addendum
states the promise. It does not rename a mode or change the vocabulary.

**Definition.** `tuned` is a curated template that follows each vendor's
documented guidance for the benchmark's data size. It is applied to the whole
workload, and every statement it applies is recorded in the result.

**What `tuned` does not promise.** `tuned` is not guaranteed to be faster than
`notuning`. Whether a template helps is a separate fact about that template,
recorded as one of four evidence states:

- `unmeasured`: no calibrated comparison with `notuning` exists for the template.
- `measured-benefit`: a calibrated comparison shows the template faster than
  `notuning` beyond noise, with no query failing that passes untuned.
- `measured-neutral`: a calibrated comparison shows no difference beyond noise.
- `measured-regression`: a calibrated comparison shows the template slower than
  `notuning` beyond noise, or failing a query that passes untuned.

Each measured state is recorded with the scale factor, the memory limit and the
engine version of the measurement. A measurement at one scale or memory limit
says nothing about another. The numeric thresholds that separate the measured
states belong to the benefit rule and are stored with the measurements, not in
this ADR.

**A ratio is a diagnostic, not a ranking.** A tuned/notuning ratio describes
how one template behaves against its own platform's baseline. It is not
comparable across platforms, because the platforms differ in what `notuning`
means, in which mechanisms their templates can apply, and in how much the
baseline already does by default. Any report, chart or console summary that
shows the ratio must say that it is a single-platform diagnostic.

### Decisions

**D1. Per-query settings are banned in `tuned`.** A template applies the same
settings to every query. A statement-level setting is allowed only as a declared
harness requirement, and all three conditions must hold:

1. the query cannot complete in `notuning` at the supported memory limit
   without it;
2. it is applied identically in every tuning mode;
3. it is recorded in the result.

A setting that exists only to make `tuned` faster, or only to make `tuned`
complete, is not a harness requirement. The ClickHouse TPC-H Q21 override
introduced by the 2026-10-07 addendum to ADR-003 is the known case, and it is
held to this test. If Q21 completes in `notuning`, the override does not
qualify and a workload-wide change replaces it.

The reasons are comparability and ledger completeness. If `tuned` may change
settings query by query, two tuned results differ by an unbounded set of
choices, and a per-query ratio no longer measures the template. The ledger also
has to hold an exact record of what was applied, and a per-query exception list
that varies by template and platform is easy to leave incomplete.

*Rejected: declared per-query settings in the template.* Declaring a setting and
recording it keeps the record complete, but it still makes tuned results
incomparable across queries and platforms, and it lets each platform tune
individual queries toward a better ratio.

**D2. The ClickHouse merge settle runs in every mode.** After every ClickHouse
server-mode load, in every tuning mode including `notuning`, the harness waits
for background merges to settle before the first timed query. Each result
records the wait. The wait is not counted as load time. chDB runs
in local mode and does not settle. This extends the
settle that the 2026-10-07 addendum to ADR-003 applied after tuned loads only.

*Rejected: settle after tuned loads only.* Merges overlap timed queries after
any load. Settling one mode and not the other adds merge contention to the
baseline alone, which inflates the tuned/notuning ratio for a reason unrelated
to the template.

**D3. Label templates without benefit evidence; do not quarantine them.** A
shipped template carries its evidence state, and a template in `unmeasured` is
labeled as such in the console and in the result. A shipped template may not stay at
`measured-regression`: it is adjusted and measured again.

*Rejected: quarantine templates without evidence.* Quarantine would stop
shipping `tuned` on three platforms because they lack benefit evidence, and that
evidence cannot be produced locally. The label keeps the template available
and makes the gap visible.

### Consequences

- Implementation follows in separate changes: the Q21 handling under D1, the
  settle in every mode under D2, and the evidence label and its use in reports
  under D3.
- Templates for which no comparison has been run stay labeled `unmeasured` until
  one is.
- ADR-003 keeps its 2026-10-07 per-template table as the record of the ClickHouse
  SF1 measurements. Where that table or the text beside it differs from D1 or D2,
  this addendum governs.
