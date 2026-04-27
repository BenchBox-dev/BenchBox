# Publishing Module Gap Matrix

**Created:** 2026-04-02
**Originating TODO:** `productize-result-publishing-and-artifact-sharing` (w1, w2)
**Status:** Decision — PRUNE

## Context

BenchBox has two overlapping publishing surfaces:

1. **Prototype** (`benchbox/core/publishing/`): A standalone pipeline module written
   as part of the `automated-data-publishing-pipeline` effort (genesis commit `97138d3a5`).
   It implements artifact lifecycle tracking, content deduplication, permalink generation,
   and multi-format publishing. It has 105 unit tests and no runtime consumers.

2. **Canonical** (`benchbox/core/results/exporter.py` + `benchbox export` CLI): The
   actively integrated result export path that powers `benchbox run`, `benchbox export`,
   and `benchbox results`. It writes schema-v2 JSON with companion `.plans.json` and
   `.tuning.json` files, supports cloud paths via `benchbox.utils.cloud_storage`, and
   includes anonymization, validation, and comparison.

This document compares them to inform a prune/integrate/extract decision.

## Capability Comparison

| Capability | Prototype (core/publishing/) | Canonical (core/results/exporter.py + benchbox export) | Notes |
|-----------|------------------------------|--------------------------------------------------------|-------|
| Export to JSON | Yes — via `Publisher._serialize_result()`, produces a different shape than schema-v2 | Yes — schema-v2 compliant via `build_result_payload()` | Prototype produces a second, non-canonical JSON shape |
| Export to CSV | Yes — flat key-value dump via `Publisher._generate_csv()` | Yes — per-query rows with typed columns (`query_id`, `execution_time_ms`, `rows_returned`, `status`) | Canonical CSV is richer and query-oriented |
| Export to HTML | Yes — basic pre-formatted dump via `Publisher._generate_html()` | Yes — full summary table with query stats, timing grid, and styled layout | Canonical HTML is significantly more detailed |
| Export to Parquet | Declared (`PublishFormat.PARQUET`) but never implemented; falls through to raw JSON | Not supported | Both are effectively absent; prototype's declaration is misleading |
| Local storage | Yes | Yes | Both write to local filesystem |
| S3 storage | Yes — via `benchbox.utils.cloud_storage.create_path_handler()` | Yes — `is_cloud_path()` + `create_path_handler()` accept `s3://` paths | Same underlying utility; exporter is more integrated |
| GCS storage | Yes — via `create_path_handler()` with `gs://` | Yes — exporter detects `gcs`/`gs` scheme via `is_cloud_path()` | Same underlying utility |
| Azure Blob storage | Yes — `StorageProvider.AZURE` with `abfss://` URIs | Yes — `is_cloud_path()` accepts `abfss://`, `az://`, `azure://` schemes | Same underlying utility |
| Databricks Volumes | Yes — `StorageProvider.DATABRICKS` with `dbfs:` URIs | Yes — full `DatabricksPath` adapter with `databricks-sdk` | Canonical exporter has more complete Databricks support |
| Content deduplication | Yes — SHA-256 hash index in `ArtifactManager` prevents duplicate artifacts in-session | No | Prototype-only; state is process-local and lost on exit |
| Artifact lifecycle tracking | Yes — `ArtifactStatus` enum (PENDING, PUBLISHED, ARCHIVED, DELETED, ERROR) via in-memory `ArtifactManager` | No | Prototype-only; not persisted |
| Retention policies | Yes — `RetentionPolicy` with `max_artifacts`, `max_age_days`, `keep_latest`; enforced in-memory only | No | Prototype-only; not persisted |
| Batch publishing | Yes — `Publisher.publish_batch()` | No | Prototype-only |
| Schema v2 compliance | No — `Publisher._serialize_result()` produces an ad-hoc dict, not a schema-v2 bundle | Yes — `build_result_payload()` + `SchemaV2Validator` | Critical gap: prototype does not produce canonical artifacts |
| Companion files (.plans.json, .tuning.json) | No | Yes — `_write_companion_files()` writes plans and tuning data alongside primary result | Prototype writes only a single JSON file |
| Anonymization | No — `anonymize` flag exists in config but `_serialize_result()` only sets a metadata flag; no actual field suppression | Yes — `AnonymizationManager` redacts system identifiers, provides anonymous machine IDs | Canonical anonymization is real and configurable |
| Schema validation on export | No | Yes — `SchemaV2Validator.validate()` before writing | |
| Result comparison | No | Yes — `compare_results()` with per-query delta and regression assessment | |
| Result listing | No | Yes — `list_results()` scans output directory for schema-v2 files | |
| CLI integration | No — zero CLI consumers; module is never imported by any command | Yes — `benchbox export`, `benchbox results`, `benchbox run` all use the canonical exporter | Decisive difference: prototype has no user-facing entry point |
| Permalink generation | Yes — `PermalinkGenerator` produces `bx_XXXXXXXX` short codes with expiry | No | Prototype-only; no resolver service exists; generated URLs resolve to nothing |
| Publication state persistence | No — `ArtifactManager` and `PermalinkRegistry` are in-memory only; state is lost on process exit | No | Both lack persistence; canonical exporter is stateless by design |
| Notification webhooks | Declared but unimplemented (`notify_on_publish = False`, empty list) | No | Dead placeholder in prototype |
| Secondary/mirror storage | Declared (`secondary_storage` list) but never used in `publish_result()` or `_write_to_storage()` | No | Dead placeholder in prototype |
| Test coverage | 105 unit tests across 4 files (artifacts, config, permalink, publisher) | Covered by existing results/export/CLI test suite | Prototype tests are high-quality but test an orphaned module |

## Consumer Analysis

**Non-test, non-docstring imports of `benchbox.core.publishing`:**

```
grep -r "from benchbox.core.publishing" . --include="*.py" \
  | grep -v test_ | grep -v __pycache__
```

Results (excluding worktrees and build artifacts): **zero runtime consumers**.

Every occurrence of `from benchbox.core.publishing import ...` in the production codebase
is inside `benchbox/core/publishing/__init__.py` itself (re-exporting its own submodules)
or in docstring `>>> from benchbox.core.publishing import ...` examples within the same
package. No CLI command, no benchmark adapter, no result pipeline, and no utility module
imports from this package at runtime.

This is the decisive evidence. The module was built, tested, and never wired in.

## Recommendation

**PRUNE**

The prototype publishing module (`benchbox/core/publishing/`) should be removed rather
than integrated or extracted. The evidence:

1. **Zero runtime consumers.** No production code imports the module. It exists in complete
   isolation from every supported BenchBox workflow.

2. **Schema incoherence.** The prototype's `Publisher._serialize_result()` produces an
   ad-hoc JSON shape that is not a schema-v2 bundle. Publishing it would create a second
   result format that is not readable by `benchbox results`, `benchbox export`, or any
   schema-aware consumer. The canonical exporter is the only valid serialization path.

3. **Persistent capabilities are illusory.** Artifact lifecycle tracking, deduplication,
   retention policies, and permalink registry all live in memory. They are destroyed when
   the process exits. The capabilities advertised in the module do not exist for any
   real multi-session workflow.

4. **Unique capabilities are unfinished.** The two capabilities the prototype has that
   the canonical exporter lacks — content deduplication and artifact lifecycle tracking —
   are explicitly in-memory only and therefore not useful for the stated use case.
   Permalink generation produces codes that resolve to nothing (no HTTP resolver service
   exists or is planned for the near term).

5. **Canonical exporter already covers the core use cases.** JSON, CSV, and HTML export
   to local and all four cloud backends (S3, GCS, Azure, Databricks) are fully supported
   via `benchbox export`. The prototype adds no production-ready capability on top of this.

6. **Parquet and secondary storage are dead declarations.** `PublishFormat.PARQUET` is
   declared but falls through to raw JSON. `secondary_storage` is defined but never
   consumed in any code path.

Pruning removes ~800 lines of production code and 105 tests that validate behavior no
user can reach. The `docs/design/future-state/prune-publishing-subsystem/README.md`
already anticipates this outcome.

If a `benchbox publish` command is later warranted, it should be built on top of the
canonical exporter (see CLI surface design below), not on the prototype's architecture.

## CLI Surface for `benchbox publish` (Design Note)

Even though the recommendation is to prune, the design intent of a future `benchbox publish`
command is documented here for reference. This surface is intentionally not implemented
by this work item; it would be the output of `productize-result-publishing-and-artifact-sharing`
w3–w10 if the feature is later prioritized.

### Distinction from existing commands

```
benchbox export   → One-shot write to disk. No tracking, no dedup, no metadata store.
                    Already implemented. Produces schema-v2 bundles in benchmark_runs/results/.

benchbox submit   → Packages a result bundle + submission manifest for PR-based contribution
                    to the public results-data/ corpus. Already implemented.

benchbox publish  → Tracked, deduplicated copy of an existing exported bundle to a named
                    destination. Would add durable publication metadata, addressable references,
                    and optional retention management. NOT yet implemented.
```

### Proposed CLI surface

```
benchbox publish [RESULT_FILE | --last]
  --destination PATH_OR_URL    # local dir, s3://bucket/prefix, gs://, abfss://, dbfs://
  --format json,csv,html       # formats to write (delegates to canonical ResultExporter)
  --no-dedup                   # skip content-hash deduplication check
  --benchmark NAME             # filter when using --last
  --platform NAME              # filter when using --last
  --dry-run                    # preview without writing

benchbox publish list          # show publication history (requires persistent metadata store)
benchbox publish rm ID         # remove publication record (does not delete remote artifact)
```

### Key design constraints for any future implementation

- **Must publish schema-v2 bundles**, not a re-serialized result. The input is always
  an already-exported `.json` (+ optional companion files) from `benchmark_runs/results/`.
- **Persistence is required.** Publication history, deduplication state, and artifact
  references must survive process exit. A lightweight SQLite or JSON index beside the
  result directory is sufficient for local backends; cloud backends need a manifest object.
- **Links must be truthful.** For local and private cloud targets, emit a storage path or
  reference, not a short code. Short-code permalinks are only meaningful when a resolver
  service exists and is documented.
- **Reuse `benchbox.utils.cloud_storage`** for all backend path handling. The existing
  `create_path_handler()` already covers S3, GCS, Azure, and Databricks.
- **Do not add a second serialization pathway.** The prototype's failure mode was writing
  a different JSON shape. Any `benchbox publish` implementation must delegate format
  conversion to the canonical `ResultExporter`.
