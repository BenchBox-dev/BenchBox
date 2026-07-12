# Tuning System: Deep Holistic Architecture & Correctness Review

## Role and objective

You are conducting a **read-only architecture and correctness review** of
BenchBox's tuning subsystem — everything between "a user decides how a run
should be tuned" and "another user judges a published result bundle that
claims a tuning". Your job is to assess whether the system is sound,
honest, and coherent end-to-end, and to surface **blind spots and
unanswered product questions**, not to fix anything.

This is a review-shaped action. Per
`~/.claude/skills/SHARED/review-protocol/SKILL.md` and CLAUDE.md: no
commits, no pushes, no PRs, no auto-merge. The only permitted writes are
local blind-spot capture files (see "Deliverables"). Long command output
goes to `/tmp/<slug>.log`; report summary + tail. Always `uv run`, never
bare `python`/`pytest`.

## Why this matters (the stakes)

Tuning metadata is a **soundness-adjacent surface**. BenchBox publishes
result bundles that other users compare in the results explorer. If the
recorded tuning is wrong, unverifiable, or means different things on
different platforms, cross-submission comparisons are silently corrupted —
the same failure class as a broken comparator. Treat "could this mislead an
evaluator?" as the top severity criterion.

## The two user lenses — hold both for every finding

**Lens A — the run author configuring tunings.** They expect:
- *Discoverability*: what can I tune on MY platform? (`benchbox tuning
  platforms/list/show`, docs)
- *Predictability*: what will `--tuning tuned` actually do here, before I
  burn hours on a run? (dry-run DDL preview, wizard)
- *Honest feedback*: if a requested tuning is unsupported, dropped, or
  silently no-ops, I must be TOLD at run time — not discover it in the
  bundle later (or never).
- *Sane precedence*: CLI flag vs `benchbox.yaml` vs env vars
  (`BENCHBOX_TUNING_ENABLED`/`BENCHBOX_TUNING_CONFIG`/`BENCHBOX_TUNING_PATH`)
  vs wizard vs smart defaults — deterministic and documented.
- *Portability*: a tuning template that works on my machine works in CI and
  on a colleague's machine.

**Lens B — the evaluator of someone else's submitted result.** They expect:
- To know what tuning was **actually applied** — not merely requested.
- To reproduce the run: is the template content recoverable from the bundle
  or only a hash + a local path that means nothing off the author's laptop?
- Hashes that are meaningful: same semantic config ⇒ same hash; different
  effective tuning ⇒ different hash.
- `tuning_validation_status` that means what it sounds like.
- "tuned vs tuned" comparisons across platforms to be apples-to-apples —
  or clearly labeled when they are not.
- "notuning" to mean genuinely untuned — including session settings, not
  just DDL.

## System map (orientation — verify, do not trust)

Data flow: `--tuning` flag / `benchbox.yaml` / wizard →
`benchbox/cli/tuning_resolver.py:resolve_tuning()` (mode + source +
template discovery) → `cli/config.py:load_unified_tuning_config()` →
`core/tuning/interface.py:UnifiedTuningConfiguration` → adapter
`apply_unified_tuning` (`platforms/base/tuning_config.py`: constraints →
platform optimizations → per-table DDL clauses via
`core/tuning/ddl_generator.py` generators) →
`core/tuning/metadata.py:TuningMetadataManager` writes a
`benchbox_tuning_metadata` DB table (rerun drift detection) → result
capture (`platforms/base/adapter.py` ~L743-872,
`platforms/base/result_capture.py:_build_tuning_profile_metadata`) records
`tunings_applied` + `tuning_config_hash` + `tuning_validation_status` +
logical-profile metadata → `core/results/schema.py` (~L1208-1399) emits the
`platform.tuning` bundle block + `.tuning.json` companion →
`core/results/loader.py` → results-explorer (`TuningBadge.tsx`,
`ComparabilityReceipt.tsx`, `lib/facetMatching.ts` — `tuning_mode` is a
matchable comparability facet).

Parallel world: **DataFrame tuning** (`core/dataframe/tuning/`,
`platforms/dataframe/tuning_mixin.py`, `cli/tuning_runtime.py`) tunes
runtime execution (threads/memory/chunks), not DDL, plus
`write_config.py` for Parquet physical layout.

Logical-profile machinery: `core/tuning/profiles/tpc.yaml` (single evidence
source, `tpc-v1`), `workload_profiles.py`, `platform_capabilities.py`
(logical→physical mapping), `profile_validation.py` (template-vs-profile
validation + the compact metadata that lands in bundles),
`coverage.py`/`coverage.yaml` + `tests/uat/test_tuning_coverage.py`
(which platform/benchmark pairs have `examples/tunings/{platform}/{benchmark}_tuned.yaml`).

Load-bearing files to actually read (in order):
1. `benchbox/core/tuning/interface.py` — all data models;
   `TuningType.is_compatible_with_platform`, `TableTuning`,
   `UnifiedTuningConfiguration.validate_for_platform`,
   `BenchmarkTunings.get_configuration_hash`.
2. `benchbox/core/tuning/ddl_generator.py` — `TuningClauses`,
   `get_ddl_generator()` registry, `NoOpDDLGenerator`.
3. `benchbox/core/tuning/platform_capabilities.py` +
   `workload_profiles.py` + `profile_validation.py`.
4. `benchbox/cli/tuning_resolver.py` + `cli/commands/run.py`
   (`_resolve_tuning`, `_load_unified_tuning_config`, ~L938-1060) +
   `cli/config.py` tuning paths.
5. `benchbox/platforms/base/tuning_config.py`, `base/tuning.py`,
   `base/adapter.py` L700-900, `base/result_capture.py` tuning sections;
   `platforms/clickhouse/tuning.py` and `platforms/starrocks/tuning.py`
   as the two "real" platform implementations.
6. `benchbox/core/results/schema.py` `build_tuning_payload` /
   `_build_tuning_summary`; `core/results/models.py` tuning fields;
   `results-explorer/src/**` tuning components + `facetMatching.ts`.
7. `benchbox/core/tuning/metadata.py`.
8. Docs as promised contracts: `docs/usage/tpc-tuning-profiles.md`,
   `docs/reference/cli/tuning.md`, `docs/advanced/performance-tuning.rst`,
   `examples/tunings/README.md`.

## Seeded leads (unverified — confirm, refute, or reframe each)

These came from a prior mapping pass. Do not treat them as findings until
you have verified them at the current HEAD with file:line evidence:

1. **Requested-vs-applied gap.** `tunings_applied` appears to be the
   *requested/effective* `UnifiedTuningConfiguration.to_dict()`, and
   `tuning_validation_status = "APPLIED"` appears to be gated only on
   whether the metadata-table write succeeded — not on inspecting the live
   schema. If true: a bundle can claim APPLIED tuning that a platform
   silently no-op'd.
2. **Unregistered generators.** `generators/` ships `questdb.py`,
   `pg_duckdb.py`, `pg_mooncake.py` (exported in `generators/__init__.py`)
   but `get_ddl_generator()` reportedly does not map them → silent
   `NoOpDDLGenerator` fallback for those platforms.
3. **Three inconsistent notions of "supported".**
   `TuningType.is_compatible_with_platform` (hardcoded map in
   interface.py), the `get_ddl_generator()` registry (~16 platforms), and
   `platform_capabilities.map_candidate_to_platform()` (only databricks/
   duckdb/bigquery/redshift/snowflake; everything else UNSUPPORTED). Which
   is authoritative? Where do they disagree, and what does each
   disagreement do to (a) run-time warnings, (b) bundle metadata?
4. **`tuned` fallback semantics.** In `tuning_resolver.py`, mode `tuned`
   with no template falls back to "basic constraints". Is such a run then
   labeled `tuned` in the bundle and explorer, despite carrying only
   baseline constraints? What does that do to the comparability facet?
5. **Corpus evidence of the gap.** At least one seed-corpus bundle
   (`results-data/bundles/ai_primitives_*_duckdb*`) reportedly has
   `execution.tuning_mode: "tuned"` with no `platform.tuning` /
   `tunings_applied` block, and `platform.raw_config.tuning_config` stored
   as a Python `repr()` string. Sweep the whole corpus for field
   consistency (script it; log to /tmp).
6. **Vocabulary drift.** Explorer `facetMatching.ts` defaults the tuning
   facet to `"untuned"` while the pipeline emits `notuning`/`tuned`/`auto`/
   `custom`. Check every producer/consumer of the mode vocabulary
   (schemas.py `RunConfig.tuning_mode`, TuningBadge, receipt, facet).
7. **Session settings escape the tuning record.** ClickHouse/StarRocks
   mixins apply session-level settings. Are those captured anywhere in the
   bundle? Can a run be heavily session-tuned while reporting `notuning`?
8. **Blocked Databricks work.** `_project/TODO/main/active/
   databricks-liquid-clustering-tuning-review-20260526.yaml` is Blocked
   after a failed live run — read it; its open questions may overlap yours.
9. **Env-dependent discovery.** Template auto-discovery honors
   `$BENCHBOX_TUNING_PATH` and cwd. Same command, different tuning by
   environment — is the resolved source recorded well enough for an
   evaluator to notice?

## Deeper questions to answer (or explicitly mark unanswerable)

**Hashing & identity**
- Is `tuning_config_hash` canonical? Can two semantically identical configs
  hash differently (dict ordering, defaults materialized vs omitted,
  version drift)? Can two *effectively different* runs share a hash (hash
  covers the requested config, but platform capability filtering drops
  clauses after hashing)?
- Should the hash cover the effective post-filtering config? The generated
  DDL? Both? What would an evaluator actually want the hash to certify?
- `hash_tuning_template()` is truncated to 16 chars — collision posture at
  corpus scale?

**Trust & verification**
- Is there ANY mechanism by which an evaluator can verify reported tuning
  against reality? Could `.plans.json` (plan companion) or post-load schema
  introspection corroborate physical layout? Is that worth designing, or is
  the honest answer "submissions are self-attested" — and if so, do docs
  and explorer UI say that anywhere?
- What are the exact semantics of each `tuning_validation_status` value,
  and does `TuningMetadataManager` drift-validation ever feed back into a
  published bundle?
- What happens to metadata persistence on in-memory engines, external
  tables (`--table-mode external` is guarded against `tuned` — is the guard
  complete?), or read-only endpoints — and does `FAILED_TO_SAVE` leak into
  bundles as an alarming-but-benign status?

**Fairness & cross-platform comparability**
- When platform X's "tuned" renders 6 physical mechanisms and platform Y's
  "tuned" renders zero (NoOp generator or UNSUPPORTED capability mapping),
  the explorer still facet-matches them as both "tuned". Is that
  defensible? Should the facet match on `physical_rendering_id` /
  mechanism count instead of mode?
- Logical profile `tpc-v1` covers TPC-H/DS only. What do
  `tuning_profile` metadata and template validation mean for the other ~20
  benchmarks? Is absence-of-profile distinguishable from
  failed-validation in the bundle?
- Profile/version evolution: when `tpc.yaml` moves past `2026-05-26`, are
  old and new bundles comparable? Is profile version part of facet
  matching?

**The DataFrame world**
- Is DF tuning metadata symmetric with SQL tuning in bundles, companions,
  explorer badge, and facet matching? Does a polars run with aggressive
  thread/memory tuning surface that to an evaluator at all?
- `write_config.py` Parquet layout (sort/partition at write time) is
  physical tuning by another name — does it flow into `tunings_applied`?

**Author experience**
- Trace `--tuning tuned` on a platform with (a) a real generator, (b) an
  unregistered generator, (c) UNSUPPORTED capability mapping: at which
  point, if any, does the author see a warning? Is dry-run
  (`core/dryrun.py` `ddl_preview`) faithful to what execution would do?
- Are `unmapped_logical_candidates` surfaced at run time or only buried in
  metadata?
- Does wizard/smart-defaults/auto provenance (`TuningSource`) survive into
  the bundle so an evaluator can distinguish curated template from
  autofill?
- Precedence: write the actual precedence table from code (flag > env >
  yaml > discovery > fallback?) and diff it against
  `docs/reference/cli/tuning.md`. Any undocumented or surprising rule is a
  finding.

**Architecture**
- Is the layering right? `interface.py` is ~57KB with Databricks-specific
  validation inline; platform knowledge lives in at least four places
  (interface compat map, generators, capability map, platform mixins).
  Propose the consolidation you'd want — one authoritative capability
  registry? — without implementing it.
- Two deprecated CLI shims (`commands/tuning.py`, `df_tuning.py`) — dead
  weight or still load-bearing?
- Test adequacy: given the failure modes above, which have zero test
  coverage? (e.g., is there any test asserting a bundle's
  `tunings_applied` matches what the adapter actually executed?)

## Method

1. **Read** the load-bearing files (list above). Build your own model;
   correct this prompt's map where it is wrong.
2. **Trace one bundle end-to-end**: pick a tuned seed-corpus bundle in
   `results-data/bundles/` and walk every tuning field back to the line of
   code that produced it.
3. **Sweep the corpus**: script a scan of all bundles' tuning fields
   (mode × presence of platform.tuning × hash × validation_status ×
   companion file) into a table; anomalies are evidence.
4. **Exercise, don't just read**, where cheap and read-only: `uv run --
   python -m pytest tests/unit/core/tuning tests/unit/cli/test_tuning*`
   (log to /tmp), `benchbox tuning list/show/platforms`, and a dry-run DDL
   preview for 2-3 platforms including one suspected-NoOp platform.
5. **Adversarial pass per lens**: for Lens A, try to construct a config the
   system accepts but misapplies silently; for Lens B, try to construct two
   bundles the explorer calls comparable that are not (and the converse).
6. **Docs diff**: promised behavior in the four doc files vs observed
   behavior.

## Deliverables

Produce a single report (chat + `/tmp/tuning-review-report.md`):

1. **Severity-ranked findings table** — Critical / Required / Nit /
   Consider — each with file:line evidence, the lens it harms, and a
   one-line failure scenario. Soundness-of-comparison issues rank above
   crashes.
2. **Architecture assessment** — sources-of-truth inventory for "what
   tuning does platform X support", the layering diagram as-built, and a
   recommended target shape (no code changes).
3. **Answered questions** — for each question above: answer + evidence.
4. **Open product questions for Joe** — decisions code cannot make:
   trust/attestation model for submissions, hash semantics, fallback
   labeling, cross-platform "tuned" facet semantics. State each as a crisp
   decision with options and your recommendation.
5. **Blind-spot capture** — framework gaps, bug-classes, and dormant
   assumptions (NOT concrete defects — those go in the severity table; apply
   the SHARED §2 defect gate) as files in `_project/blind-spots/` per
   `_project/blind-spots/README.md`, validated with
   `uv run --project _project/scripts -- python _project/scripts/validate_blind_spot.py <file>`.
   Capture is local-only: do not commit, push, or open a PR.

Do not propose or apply fixes in this session. The review report is the
deliverable; remediation is a separate, explicitly authorized task.
