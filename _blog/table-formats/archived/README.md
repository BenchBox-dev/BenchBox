# Archived Drafts

These files are early drafts that contain **fabricated or unverified benchmark data** and should not be published as-is.

## Files

| File | Issue |
|------|-------|
| `01-parquet-basics.md` | Fabricated SF1 compression numbers (500/310/290 MB); wrong ratios. Real measurements in `drafts/01-parquet-basics.md`. |
| `02-delta-lake.md` | `[^5]` cites "Databricks DBR 14.3 LTS, January 2026" - this run was never conducted. Numbers (1.35s/1.22s, 12% overhead) are invented. |
| `03-iceberg.md` | `[^6]` cites "AWS us-east-1, Glue catalog, January 2026" - this run was never conducted. Cross-engine numbers (Spark 1.15s, Trino 0.95s, Athena 1.8s) are invented. |
| `04-vortex.md` | No fabricated data, but Vortex availability claims may be outdated. |
| `table-formats-announcement.md` | Fabricated performance numbers throughout; wrong CLI syntax. Superseded by `docs/blog/2026-03-04-table-formats-what-we-learned.md`. |

## What to do with these files

- **Do not publish** these files without replacing all fabricated benchmark data with real measurements.
- Use `research/format_benchmark.py` to generate real data for posts 1-2.
- Posts 2 (Delta Lake) and 3 (Iceberg) require cloud platform access for the performance benchmarks.
- The educational content in these drafts (concepts, explanations) is generally sound; only the benchmark numbers are problematic.

## Real measurements (SF1, March 2026)

| Format | Size | Notes |
|--------|------|-------|
| Parquet (none) | 604 MB | Uncompressed |
| Parquet (snappy) | 319 MB | |
| Parquet (lz4) | 329 MB | |
| Parquet (zstd:3) | 230 MB | BenchBox default |
| Parquet (zstd:9) | 230 MB | Same as :3 at SF1 |
| Delta Lake (snappy) | 320 MB | delta-rs default |
| DuckLake (snappy) | 309 MB | 4.3 MB catalog + 304.4 MB data |
