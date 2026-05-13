# Join Order Benchmark

```{tags} intermediate, concept, join-order, custom-benchmark
```

> **CLI name:** `joinorder` - use `benchbox run --benchmark joinorder --scale 1`

BenchBox's public Join Order Benchmark implementation uses the canonical IMDb
2013 dataset used by the JOB paper, "How Good Are Query Optimizers, Really?"
by Leis et al. The benchmark is designed to expose cardinality-estimation and
join-order planning behavior across many-table SQL queries.

## Data Source

`joinorder` downloads and verifies the BenchBox Parquet package for
`joinorder-imdb-2013-v1`. The package is derived from the Harvard Dataverse
`imdb_pg11` archive, DOI `10.7910/DVN/2QYZBT`, restored into PostgreSQL and
converted to 21 Parquet tables for repeatable benchmark execution.

The provenance attestation lives at
`_project/joinorder/provenance-attestation.md`. It records that the
Dataverse-published MD5 for file id `3590041` matches the cached source pg_dump,
that the restored source has 21 tables and 74,190,187 rows, and that the
Postgres-to-Parquet conversion fidelity check passes for row counts,
null/empty-string preservation, integer ranges, and UTF-8 samples.

BenchBox does not define JoinOrder source recovery as byte-identical
Parquet/archive reproduction. A 2026-05-12 rebuild check produced different
archive hashes across two local rebuilds, with byte-hash drift in
`cast_info.parquet`, while conversion-fidelity checks passed. The rebuild
contract is therefore logical table-content equivalence: maintainer rebuilds
export PostgreSQL rows in `id` order, read rebuilt Parquet rows in `id` order,
and compare versioned typed row-content hashes before packaging. The downloaded
published archive is still verified by its pinned `archive_sha256` and
per-table Parquet file hashes.

Licensing status is separate from integrity status. The Dataverse record
declares the deposit as `CC0 1.0`, but IMDb's current dataset terms and the JOB
paper frame the underlying IMDb data as non-commercial. BenchBox records the
current re-hosted Parquet release asset as an accepted project-owner
redistribution risk, keeps it as the default fast path, and does not treat it as
BenchBox-cleared for broad commercial redistribution.

The benchmark accepts only `--scale 1`. There is currently no public small,
comparable JOB workload; the decision is recorded in
`_project/decisions/joinorder-small-workload-2026-05-12.md`. The old
uniformly-random data generator has been renamed to the internal
`joinorder_synthetic` benchmark for loader and schema smoke tests; it is not a
substitute for JOB cardinality testing.

## First Run

```bash
uv run -- benchbox run --platform duckdb --benchmark joinorder --scale 1
```

On first use BenchBox downloads the compressed archive, verifies the archive
hash, extracts the 21 Parquet files, and verifies table-level hashes and row
counts from `benchbox/core/joinorder/data_manifest.toml`.

The manifest hash fields have separate roles:

- `archive_sha256`: sha256 of the downloadable `.tar.zst`, consumed by the
  downloader before extraction.
- `data_archive_hash`: aggregate sha256 over sorted per-table Parquet hashes,
  used to identify the extracted canonical Parquet file set in result metadata.
- `manifest_hash`: sha256 of the stable manifest content with transport-only
  fields excluded, consumed by manifest parsing before runtime use.

Subsequent runs reuse the verified data under:

```text
benchmark_runs/datagen/joinorder_sf1/
```

If `BENCHBOX_OUTPUT_DIR` is set, the same relative datagen path is resolved
under that root. Air-gapped environments can pre-populate that directory with
the 21 Parquet files; BenchBox still verifies the manifest before running.

## Query Set

`JoinOrderQueryManager` exposes all 113 canonical JOB SQL queries:

```python
from benchbox.core.joinorder.queries import JoinOrderQueryManager

queries = JoinOrderQueryManager()
assert queries.get_query_count() == 113
query_1a = queries.get_query("1a")
```

The SQL text is imported from the Greg Rahn JOB query corpus pinned by the
canonical build. Runtime platform adapters handle dialect translation.

## Python API

```python
from benchbox import JoinOrder

benchmark = JoinOrder(scale_factor=1.0)
data_files = benchmark.generate_data()
schema_sql = benchmark.get_create_tables_sql(dialect="duckdb")
query_sql = benchmark.get_query("1a")
```

Passing any scale other than `1.0` raises a clear error pointing to
`joinorder_synthetic` for synthetic smoke-test data.

## DataFrame Mode

The DataFrame registry exposes all 113 canonical query IDs. The original 13
queries keep their hand-written expression-family and pandas-family
translations; the rest use a restricted translator for the canonical JOB SQL
shape: comma-join tables, WHERE predicates, equality joins, and top-level
`MIN(...)` projections.

DataFrame `joinorder` still has a different benchmark interpretation from SQL
`joinorder`: SQL mode stresses optimizer join ordering, while DataFrame mode
executes an explicit join sequence and primarily measures multi-join execution
through the DataFrame APIs.

## License And Attribution

Dataset provenance and redistribution notes live in:

```text
benchbox/core/joinorder/DATA-LICENSE.md
```

Decision record:

```text
_project/decisions/joinorder-canonical-data-licensing-2026-05-12.md
```

IMDb attribution:

```text
Information courtesy of IMDb (https://www.imdb.com). Used with permission.
```

Use this dataset for research, database systems evaluation, and query optimizer
benchmarking. It is not intended for republication as a general-purpose movie
database, and BenchBox does not treat the current converted archive as
BenchBox-cleared for broad commercial redistribution. Optional follow-up work may
seek explicit permission or add an advanced direct-Dataverse/BYO path, but the
default user experience remains the verified BenchBox-hosted Parquet archive.

## References

- Paper: https://www.vldb.org/pvldb/vol9/p204-leis.pdf
- Query corpus: https://github.com/gregrahn/join-order-benchmark
- Dataset DOI: https://doi.org/10.7910/DVN/2QYZBT

## Implementation Files

```text
benchbox/core/joinorder/
|-- benchmark.py          # canonical IMDb 2013 benchmark driver
|-- data_manifest.toml    # archive, table hash, schema, row-count manifest
|-- DATA-LICENSE.md       # dataset provenance and redistribution notes
|-- queries.py            # 113 canonical JOB SQL queries
|-- dataframe_queries.py  # 113 DataFrame query implementations
`-- schema.py             # 21-table JOB schema
```
