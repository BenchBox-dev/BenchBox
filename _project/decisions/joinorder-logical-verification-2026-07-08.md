# ADR: JoinOrder Canonical Dataset — Logical Content Verification

Date: 2026-07-08

Status: Accepted. Supersedes the byte-hash-only verification assumption of the
canonical cutover; extends (does not replace) the redistribution decision in
`joinorder-canonical-data-licensing-2026-05-12.md`.

## Question

The canonical JoinOrder archive
(`joinorder-imdb-2013-v1.tar.zst`, `archive_sha256 = 669c97…c5fd`) is
unrecoverable: the GitHub Release asset 404s, the release object is gone, no
byte-identical copy survives in any local/backup storage, and the Parquet build
is **non-deterministic** — the two attested rebuilds produced
`e24bc0…` and `adf28…`, and even differed from each other at the `cast_info`
table (`provenance-attestation.md`). The runtime therefore cannot be restored by
re-uploading the pinned bytes, and cannot be restored by rebuilding either,
because `data_manifest.toml` is hash-locked to per-table **byte** SHA-256 values
that a rebuild will never reproduce.

How should canonical JoinOrder be made downloadable again **and** be made
rebuildable-forever, so that losing the transport archive can never again strand
the dataset?

## Determination

Adopt **logical row-content hashing** as the canonical dataset identity, keep
the dataset at **`joinorder-imdb-2013-v1`**, and re-publish a freshly rebuilt
transport archive under the existing tag.

### 1. Identity is logical, not byte-level

The logical content of the dataset is unchanged: same Harvard Dataverse source
pg_dump (`pg_dump_sha256 = 1390a7…`, Dataverse MD5 `df3e976b…`), same
`gregrahn/join-order-benchmark` corpus commit, same conversion. A rebuild that
reproduces that logical content is a **transport-wrapper change, not a new
dataset**. Per the manifest schema's own intent — `manifest_hash` "bumps on
logical data or metadata corrections, not transport-wrapper changes" — the
identity must therefore stay `…-v1`. Bumping to `-v2` would assert a difference
that does not exist and would strand every already-published result bundle that
records `dataset_version = …-v1`.

The logical hash algorithm already exists and is proven: `joinorder-logical-content-v1`
(`build_joinorder_data.py`), which hashes canonical rows in `id` order via
DuckDB, with type-tagged, encoding-independent cell rendering, so CSV-source and
Parquet-output hash identically. It is promoted from a build-only equivalence
gate into a **pinned, shared, runtime-consulted** identity.

### 2. Layered verification (Design A)

Three verification layers, each with a distinct job:

| Field | Kind | Purpose | Regenerated per rebuild? |
|---|---|---|---|
| `archive_sha256` | byte SHA-256 of tarball | transport integrity of the download | **yes** |
| per-table `sha256` | byte SHA-256 of Parquet | fast extracted-file integrity (hot fetch path) | **yes** |
| per-table `logical_sha256` | logical row-content hash | reproducible dataset identity / rebuild-equivalence | **no (stable)** |
| `data_archive_hash` | aggregate over per-table `logical_sha256` | dataset content identity embedded in result bundles | **no (stable)** — *redefined from byte-aggregate to logical-aggregate* |
| `manifest_hash` | hash of logical+structural projection | manifest identity, stable across transport rebuilds | **no (stable)** — *redefined to exclude byte hashes/provenance* |

The **hot fetch path is unchanged and stays byte-only** (fast; `manager.py`
keeps verifying per-table `sha256` + `archive_sha256`). Logical verification is
an **explicit, opt-in assurance step** (a `verify-logical` entrypoint that
recomputes per-table `logical_sha256` from the extracted Parquet and compares to
the manifest), plus the build/republish equivalence gate. Rationale:
performance-first on the runtime path; a full logical recompute is a
74M-row scan+sort and must not tax every cold fetch.

### 3. `manifest_hash` and `data_archive_hash` become logical identities

Both are redefined to be functions of **logical content + stable structural
metadata only**, excluding everything that legitimately varies per build
(per-table byte `sha256`, `archive_sha256`, `[provenance]` build-run fields).
Consequence: after this migration, any future rebuild that preserves logical
content yields **identical** `manifest_hash` and `data_archive_hash`, so no
result-bundle churn and no version bump are ever needed again. This is the
property that "ends this class of blocker."

`manifest_hash` is computed over a canonical **structured** projection
(`dataset_version`, `data_archive_hash`, `url`, `license_file`, and per-table
`name`/`file`/`logical_sha256`/`row_count`/ordered `schema`), not raw file text,
so it is independent of TOML formatting. The identical function is shared by the
build script and the runtime loader to prevent algorithm drift.

### 4. Single source of truth for the hash algorithm

The logical-hash primitives move to `benchbox/core/data_fetch/logical_hash.py`
and are imported by both the runtime (`manifest.py`, `manager.py`) and the build
script (which runs under the repo-root `uv` environment and can import
`benchbox`). Build and runtime therefore cannot compute the hash differently.
A golden test pins the algorithm against a known fixture.

### 5. Backward-compatible migration

The manifest parser is **dual-mode, feature-detected**: a manifest whose tables
lack `logical_sha256` is parsed in legacy mode (current byte-inclusive
`manifest_hash`); a manifest carrying `logical_sha256` uses the new logical mode.
This lets the code land independently and green while the shipped v1 manifest is
still the old one; the rebuild then regenerates the manifest into logical mode.
The one-time migration regenerates, **atomically**, all cross-locked artifacts:
`data_manifest.toml`, `reference_cardinalities.json`,
`tiny_reference_cardinalities.json`, `release-notes.md`,
`provenance-attestation.md`, and the three published bundles under
`results-data/bundles/joinorder_sf1_*` whose embedded `manifest_hash` /
`data_archive_hash` change once (algorithm change) and then never again.

## Alternatives rejected

- **Re-upload the exact archive** — impossible; no byte-identical copy exists
  anywhere and the release object is gone.
- **Bump to `joinorder-imdb-2013-v2`** — churns tag/URL/every reference and
  makes prior published results read as an older version despite byte-for-byte
  identical logical data; the logical content is unchanged, so a new logical
  identity is unjustified.
- **Replace byte verification with logical on the hot fetch path (Design B)** —
  imposes a 74M-row scan+sort on every cold fetch and loses cheap corruption
  detection; violates performance-first.
- **Keep byte-based `manifest_hash`/`data_archive_hash`, add logical only as
  metadata (Design C)** — leaves both identities churning on every rebuild, so
  the "never recurs" property is only half-achieved and each future rebuild
  still needs a bundle migration.
- **Change the download host** — a separate decision governed by the licensing
  ADR; out of scope here.

## Consequences

- Canonical JoinOrder is downloadable again and rebuildable-forever: any future
  rebuild validates logically and can be re-published without identity churn.
- One-time: the three published bundles' `manifest_hash`/`data_archive_hash`
  change (algorithm change); regenerated together with the manifest.
- The Docker/Dataverse rebuild remains the only owner-environment step; it is
  gated on local disk headroom (the IMDb restore + CSV + Parquet working set
  exceeds the ~8.5 GiB currently free).
- Licensing posture is unchanged: `DATA-LICENSE.md` still ships in the archive
  and the redistribution disclaimer stays in `release-notes.md`.
