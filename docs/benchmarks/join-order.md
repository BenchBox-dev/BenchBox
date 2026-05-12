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

Licensing status is separate from integrity status. The Dataverse record
declares the deposit as `CC0 1.0`, but IMDb's current dataset terms and the JOB
paper frame the underlying IMDb data as non-commercial. BenchBox therefore does
not treat its current re-hosted Parquet release asset as cleared for broad
redistribution until the remediation tracked from
`_project/decisions/joinorder-canonical-data-licensing-2026-05-12.md` lands.

The benchmark accepts only `--scale 1`. The old uniformly-random data generator
has been renamed to the internal `joinorder_synthetic` benchmark for loader and
schema smoke tests; it is not a substitute for JOB cardinality testing.

## First Run

```bash
uv run -- benchbox run --platform duckdb --benchmark joinorder --scale 1
```

On first use BenchBox downloads the compressed archive, verifies the archive
hash, extracts the 21 Parquet files, and verifies table-level hashes and row
counts from `benchbox/core/joinorder/data_manifest.toml`.

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

The DataFrame registry preserves the existing 13 translated query
implementations. The remaining 100 canonical query IDs are registered as
`NotImplementedError` stubs that point to the Track-2 DataFrame coverage TODO.
Default DataFrame query selection exposes only the implemented 13 until that
follow-up work lands.

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
BenchBox-cleared for commercial redistribution.

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
|-- dataframe_queries.py  # 13 implemented DataFrame queries + 100 stubs
`-- schema.py             # 21-table JOB schema
```
