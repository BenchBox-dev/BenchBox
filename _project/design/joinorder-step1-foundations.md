# JoinOrder canonical IMDb 2013 — Step 1 foundations design

Anchor doc for joinorder-canonical-foundation work units w2-w16.
Locks the reusable patterns w2 (`benchbox/core/data_fetch/`) and w3
(registry `surface` field + `validate_scale_factor()` gate)
implement, plus the manifest schema w7 assembles. Cutover TODO
consumes the contracts defined here.

## Scale-factor enforcement gate

### Current state

`scale_factor` is plumbed through several paths today:

- `benchbox/core/benchmark_registry.py` declares `scale_options:
  list[float]` and `min_scale: float` per benchmark
  (`BENCHMARK_METADATA` dict). joinorder already declares
  `scale_options: [1.0]`, `min_scale: 1.0`.
- `benchbox/cli/benchmarks.py` reads `scale_options` for help text
  and selection prompts (lines 231, 606, 626, 736).
- `benchbox/core/runner/runner.py:131` reads
  `benchmark_config.scale_factor` and forwards it through preflight,
  load, and result phases.
- TPC-DS has separate compliance-driven scale validation in
  `benchbox/core/tpcds/compliance.py`; that classifier stays.
- No central rejection point exists today: a caller can construct a
  benchmark with sf=0.5 for joinorder and the runner will pass it
  through. Validity is enforced indirectly by generators that
  silently degrade or by ad-hoc checks.

### Pattern

```python
# benchbox/core/errors.py
class ScaleFactorNotSupportedError(ValueError):
    """Raised when scale_factor is not in the benchmark's declared
    scale_options."""

# benchbox/core/benchmark_registry.py
def validate_scale_factor(
    benchmark_id: str, scale_factor: float
) -> None:
    """Raise ScaleFactorNotSupportedError if `scale_factor` is not
    in the benchmark's declared scale_options.

    Reads from BENCHMARK_METADATA[benchmark_id]["scale_options"];
    no per-benchmark hard-coding. tpcds_obt, joinorder, and any
    benchmark with a single-element scale_options list will reject
    everything else.
    """
```

Rationale: registry-driven, benchmark-agnostic. Adding a new
single-scale benchmark in the future is one registry edit, not a
runner-side branch.

### Wiring

- `benchbox/core/runner/runner.py` calls `validate_scale_factor()`
  before any data-generating step (currently around line 131 where
  `scale_factor` is first read for preflight).
- `benchbox/cli/orchestrator.py` and `benchbox/cli/commands/run.py`
  rely on the runner's gate; no separate CLI-side check needed
  (avoids duplicate error paths).
- Surfacing: `ScaleFactorNotSupportedError`'s message names the
  benchmark and the accepted `scale_options` list, e.g.:
  `joinorder accepts scale_factor in [1.0]; got 0.5`.

### Tests

- `tests/unit/core/test_scale_factor_validation.py`: parametrized
  across all registered benchmarks. joinorder rejects sf!=1.0;
  tpch/tpcds accept their declared ranges; tpcds_obt rejects
  sf!=1.0.

## Data-fetch infrastructure (`benchbox/core/data_fetch/`)

### Module layout

```
benchbox/core/data_fetch/
    __init__.py    # public API: fetch_data, ChecksumMismatchError, etc.
    manifest.py    # parse data_manifest.toml; pydantic-style validation
    manager.py     # orchestrate path resolution, fetch, validate
    downloader.py  # HTTP GET + progress + resume + retry
    errors.py      # exception hierarchy
```

### `data_manifest.toml` schema

Per-benchmark file at `benchbox/core/<benchmark>/data_manifest.toml`.
Fields (TOML keys):

| Key | Type | Purpose |
|---|---|---|
| `dataset_version` | str | Logical immutable id, e.g. `joinorder-imdb-2013-v1`. Stable across metadata-only manifest changes; bumped on intentional data revisions. |
| `manifest_hash` | str | sha256 over the manifest contents (computed/verified at runtime). |
| `data_archive_hash` | str | sha256 of the packaged tar.zst on disk. |
| `url` | str | Public download URL (GitHub Release asset). |
| `archive_sha256` | str | sha256 of the downloaded tar.zst (must match `data_archive_hash`). |
| `[[tables]]` array | table | Per-table block: `name`, `file` (relative path inside archive), `sha256`, `row_count`, `schema` (`{column → postgres_type}`). |
| `[provenance]` | table | `source_doi`, `retrieval_timestamp` (ISO-8601 UTC), `pg_dump_sha256`, `postgres_image`, `duckdb_version`, `gregrahn_commit`, `script_git_sha`. |
| `license_file` | str | Relative path to `DATA-LICENSE.md`. |

`dataset_version` and `manifest_hash` are surfaced separately because
a metadata-only correction (e.g., fixing a typo in an attribution
string) bumps `manifest_hash` without bumping the logical
`dataset_version`. Result-bundle comparisons can decide which
identity field they need.

### Path resolution (no new env vars)

The data_fetch manager reuses BenchBox's existing convention:

- `benchbox.utils.path_utils.resolve_benchmark_runs_dir()` →
  base directory (honors `BENCHBOX_OUTPUT_DIR`).
- `benchbox.cli.config.DirectoryManager.get_datagen_path(name, sf)`
  → `<base>/datagen/<name>_<sf>/`.

`fetch_data(benchmark, registry, output_dir=...)` resolves
`output_dir` through `get_datagen_path()` by default. Air-gapped
users pre-populate that directory with the same files; the
manifest's `archive_sha256` + per-table sha256 fields gate validity.
No new CLI flag, no benchmark-specific env var.

### Failure modes (all in `benchbox/core/data_fetch/errors.py`)

```python
class DataFetchError(Exception):
    """Base."""

class ManifestValidationError(DataFetchError):
    """data_manifest.toml is malformed or missing required fields."""

class ChecksumMismatchError(DataFetchError):
    """Downloaded or pre-populated data does not match manifest hash."""

class DownloadError(DataFetchError):
    """HTTP-layer failure with no successful retry."""
```

All are benchmark-agnostic — joinorder-specific exceptions are
forbidden by the foundation TODO's anti_patterns.

### Reuse over nyctaxi pattern

`benchbox/core/nyctaxi/downloader.py:311` (`NYCTaxiDataDownloader`)
uses `output_path.exists()` as the presence check. Foundation w2
generalizes that pattern by adding a manifest-driven sha256 gate on
top: `.exists()` is necessary but not sufficient; the bytes have to
match the manifest. nyctaxi itself is unchanged in Step 1 (potential
follow-up to back-port the gate).

## Dataset versioning in result bundles

(Implementation lands in cutover TODO's w12; design here so the
schema is locked.)

`benchbox/core/publishing/bundle_publisher.py` writes a manifest
field block. Foundation defines three new identity fields:

- `dataset_version` (str | null) — copies the manifest's
  `dataset_version`. Null for purely-generated benchmarks (tpch,
  tpcds, the synthetic generator).
- `manifest_hash` (str | null) — copies the manifest's
  `manifest_hash`. Null for purely-generated benchmarks.
- `data_archive_hash` (str | null) — copies the manifest's
  `data_archive_hash`. Null for purely-generated benchmarks.

Surfaced for forensic comparison only. The result-explorer UI is not
changed (per Joe's constraint). A future TODO can decide whether
to expose the field.

## Registry surface field

`benchbox/core/benchmark_registry.py` `BENCHMARK_METADATA[<id>]`
gains an optional `"surface"` key:

| Value | Meaning |
|---|---|
| `"public"` | Default. Visible to result-publisher's public surface, explorer, MCP discovery. |
| `"internal"` | Hidden from result-publisher's public surface. Still runnable; bundles publish locally; explorer ignores them. |

Existing benchmarks default to `"public"` (no behavior change).
Foundation only adds the registry plumbing; cutover TODO uses
`"internal"` for `joinorder_synthetic`.

The result-publisher path filters bundles by reading
`BENCHMARK_METADATA[benchmark_id].get("surface", "public")`. No UI
changes needed.

### Tests

- `tests/unit/core/test_registry_surface_field.py`:
  - existing benchmarks default to `"public"` (regression guard)
  - a benchmark registered with `surface: "internal"` is filtered
    out by the publisher's public-surface query
  - `surface: "internal"` benchmarks remain runnable and produce
    bundles locally (their visibility is controlled at the publish
    layer)

## Build pipeline architecture (w4-w14)

The offline build pipeline lives in `_project/scripts/` (its own uv
project per established convention). Only `_project/scripts/`
imports Docker/Postgres/network-heavy deps; the runtime code in
`benchbox/` stays free of those deps.

```
build_joinorder_data.py
    download-pgdump   # w4: Harvard Dataverse DOI:10.7910/DVN/2QYZBT
    restore-postgres  # w4: ephemeral container, image tag pinned
    extract-csv       # w5: COPY ... TO with FORCE_QUOTE *
    convert-parquet   # w6: DuckDB read_csv_auto + COPY (zstd)
    assemble-manifest # w7: data_manifest.toml with provenance
    encoding-gate     # w8: Parquet → DuckDB → Postgres-row-byte compare
    predicate-gate    # w9: ≥1 row per query against canonical Postgres
    import-queries    # w10: gregrahn → build-inputs/queries/*.sql
    cardinalities     # w11: Postgres oracle, 113 queries
    cross-check       # w12: Leis 2015 published values
    package           # w13: tar.zst + checksums
    tiny-fixture      # w14: ~50 rows × 21 tables, predicate-satisfying
```

Each subcommand is idempotent and writes to a single
`build/<dataset_version>/` work directory. Re-running with the same
upstream pg_dump must produce a byte-identical archive (modulo
manifest timestamps).

### Validation gates (build-time, not runtime)

w8 encoding gate samples 100 rows × 21 tables of "tricky" classes
(non-ASCII names, ideographic chars, punctuation-heavy notes) and
asserts byte-for-byte UTF-8 match against Postgres source rows. The
gate fires AFTER Parquet conversion and BEFORE manifest assembly.

w9 predicate-domain gate parses each of the 113 canonical queries
for predicates on key string columns and asserts ≥1 row in the
converted data satisfies that predicate (computed via Postgres on
the restored canonical). Per-column null-fraction assertions
against published reference values are also part of this gate
(numbers TBD during w4 from the actual restore).

Both gates abort the pipeline (non-zero exit) on any failure. The
TODO's anti-pattern catalog explicitly forbids skipping w8 because
silent NFC/NFD normalization in the Parquet writer is invisible
without the gate.

## Migration / backwards compatibility

Step 1 foundation does NOT touch:

- `benchbox/core/joinorder/` runtime files (cutover renames them)
- existing benchmark `surface` defaults (all stay public)
- the result-explorer UI (zero changes)
- `benchmark_runs/datagen/` users have already populated for other
  benchmarks (joinorder's directory is the only new entry)

A user running `joinorder` after foundation merges sees no behavior
change because foundation produces only the offline archive +
infrastructure skeleton. The user-visible cutover (rename +
canonical wiring) is the cutover TODO's job.

## Open questions (rolled forward)

- Harvard Dataverse pg_dump may differ from the CWI mirror.
  Mitigation: w4 cross-checks restored row counts against Leis 2015
  Table 3; if material drift, document the chosen snapshot in the
  manifest.
- DuckDB Parquet writer's encoding behavior on edge-case Unicode
  (combining characters, RTL text) is not certified. Mitigation:
  w8 round-trip gate; fall back to Polars/pyarrow if it fails.
- Tiny fixture (~1MB checked in) regen strategy: deterministic
  re-derivation via the build pipeline (w14), but the Parquets are
  checked in so unit tests don't need the full archive.
- Whether to back-port the manifest sha256 gate to nyctaxi: deferred
  to a follow-up TODO.
