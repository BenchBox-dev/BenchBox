# Calibrated SF=1 Uncompressed Source-Data Sizes

Measured 2026-09-26 with `scripts/measure_sf1_sizes.py`: each benchmark's
generator ran at `scale_factor=1.0` with compression disabled, and every
file the generator owns under its output root was summed (returned table
paths plus auxiliary corpora such as the primitives bulk-load files).
Real-data benchmarks (nyctaxi, flightdata) were decompressed from retained
SF=1 caches; `ai_primitives` reuses TPC-H data; `metadata_primitives`
generates no data files.

These are uncompressed source bytes. They are larger than the retained
on-disk caches, which stay zstd- or gzip-compressed: `flightdata` measures
2.6 GiB uncompressed against a ~0.5 GiB compressed cache, and `nyctaxi`
measures 0.8 GiB against a smaller compressed cache.

GiB figures use 1024^3 bytes. Row counts come from retained SF=1 manifests
where available; otherwise the generator baseline.

| Benchmark | Measured bytes | Measured GiB | Approx GB | Method |
|-----------|----------------|--------------|-----------|--------|
| tpch | 1,092,043,700 | 1.017 | ~1.1 GB | generated |
| tpcds | 1,235,064,003 | 1.150 | ~1.2 GB | generated |
| tpcdi | 160,094,804 | 0.149 | ~0.2 GB | generated |
| ssb | 609,810,151 | 0.568 | ~0.6 GB | generated |
| tpch_skew | 1,072,122,706 | 0.998 | ~1.1 GB | generated |
| tpchavoc | 1,092,043,700 | 1.017 | ~1.1 GB | generated (TPC-H data) |
| ai_primitives | 1,092,043,700 | 1.017 | ~1.1 GB | generated (TPC-H data) |
| metadata_primitives | 0 | 0.000 | 0 | no data files |
| amplab | 679,784,321 | 0.633 | ~0.7 GB | generated |
| h2odb | 1,413,528,658 | 1.316 | ~1.4 GB | generated |
| coffeeshop | 900,141,206 | 0.838 | ~0.9 GB | generated |
| tsbs_devops | 919,491,614 | 0.856 | ~0.9 GB | generated |
| joinorder | 959,479,691 | 0.894 | ~1.0 GB | generated (canonical IMDB) |
| joinorder_synthetic | 444,365,227 | 0.414 | ~0.4 GB | generated |
| read_primitives | 1,092,043,700 | 1.017 | ~1.1 GB | generated (TPC-H data) |
| write_primitives | 1,849,207,752 | 1.722 | ~1.8 GB | generated |
| transaction_primitives | 1,849,207,752 | 1.722 | ~1.8 GB | generated |
| vector_search | 1,342,083,621 | 1.250 | ~1.3 GB | generated |
| clickbench | 552,136,075 | 0.514 | ~0.6 GB | generated |
| nyctaxi | 863,567,123 | 0.804 | ~0.9 GB | decompressed SF=1 cache |
| flightdata | 2,750,362,238 | 2.561 | ~2.8 GB | decompressed SF=1 cache |
| tpcds_obt | 2,406,484,046 | 2.241 | ~2.4 GB | generated (includes TPC-DS source) |
| datavault | 4,795,724,939 | 4.466 | ~4.8 GB | generated (includes TPC-H source) |

## Notes

- The harmonization target (~1 GB at SF=1) holds for the adjustable
  synthetic benchmarks: coffeeshop, amplab, h2odb, tsbs_devops, nyctaxi,
  and joinorder all land within or near the 0.8-1.3 GB band. FlightData
  (2.6 GiB) and datavault (3.4 GiB) sit above it; joinorder_synthetic
  (0.4 GiB) and clickbench (0.5 GiB) sit below.
- TPC-H, TPC-DS, SSB, and DataVault follow external spec or derived
  semantics and were never harmonization targets.
- `read_primitives` and `ai_primitives` reuse TPC-H source data, so they
  match TPC-H exactly.
- `write_primitives` and `transaction_primitives` exceed the TPC-H base
  because the total includes each generator's bulk-load auxiliary corpus
  alongside the TPC-H tables.
- Row counts below come from the summed `_datagen_manifest.json`
  `row_count` entries where generators write them; generators without
  manifest row metadata report no row count.
- `tpcds_obt` and `datavault` derive from TPC-DS and TPC-H source data;
  the totals include the source corpus the measurement generated alongside
  the derived tables. A run that reuses an existing source cache needs
  only the incremental derived bytes.
- `nyctaxi` at SF=1 samples the 2019 corpus at rate 0.1 (one month slice);
  `flightdata` at SF=1 spans ~41 months of BTS data.
- Regenerate with `uv run -- python scripts/measure_sf1_sizes.py --output <path>`
  (add `--jobs N` for bounded parallel runs with ample scratch space).
  The full run needs roughly 20 GB of scratch space and 30-45 minutes
  sequential; `flightdata` downloads its BTS slice and dominates wall time.
  Copy changed byte counts into
  `tests/unit/generators/sf1_size_baseline.json` in the same commit so the
  baseline test keeps mirroring this table.
