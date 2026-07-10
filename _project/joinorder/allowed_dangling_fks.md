# JoinOrder Allowed-Dangling Foreign-Key Census

Date: 2026-07-10

Status: Generated and human-reviewed against the sha256-verified canonical
archive.

The canonical IMDb 2013 data has legitimate dangling references: foreign keys
are opt-in metadata, not load-time constraints
(`benchbox/core/joinorder/schema.py`). A full-archive FK-integrity test needs a
durable, reviewed census of which declared FKs dangle and by how much, so
corruption is distinguishable from known-source noise. That census is
`_project/joinorder/allowed_dangling_fks.json`.

## Provenance

- Generator: `_project/scripts/build_joinorder_data.py fk-dangling-census`
- FK source: `benchbox/core/joinorder/schema_specs.yaml` (the same declarations
  the DDL uses; parsed via `JoinOrderSchema`, no PostgreSQL container required)
- Computed with DuckDB over the sha256-verified shipped Parquet extracted by the
  runtime loader (`JoinOrderBenchmark.generate_data()`)
- `dataset_version`: `joinorder-imdb-2013-v1`
- `data_archive_hash`: `0f9061ba7c429cc45922ab1ff0f0417f8760c9ae63150978a2d42321b8fdb0f0`
- `manifest_hash`: `3b8ab6f01620c07c95898ced94e430cee4b715b80c2ff537e683d54bfe501477`

The artifact records `data_archive_hash`, so a future dataset version cannot
silently reuse this census: `load_allowed_dangling_fks()` (and consumers) reject
it once the manifest hash changes.

## Census summary

- 27 declared foreign keys across 11 child tables; all parent columns are the
  primary key `id`.
- Total dangling child rows: **93**, in a single foreign key.

| Foreign key | Non-NULL child rows | Dangling |
| --- | --- | --- |
| `aka_title.movie_id` → `title.id` | 361,472 | **93** |
| all 26 other declared FKs | — | 0 |

## Human review

- **Only `aka_title.movie_id` dangles** (93 of 361,472 rows), and those 93 rows
  reference exactly **one** `movie_id` that is absent from `title` — a classic
  minor IMDb source artifact (an absent parent title orphaning its
  alternative-title rows), not corruption.
- **Zero dangling on every closure-guaranteed relationship FK**: `cast_info`,
  `movie_companies`, `movie_info`, `movie_info_idx`, `movie_keyword`,
  `movie_link`, `complete_cast`, `person_info`, and the dimension FKs
  (`kind_id`, `role_id`, `link_type_id`, `info_type_id`, `company_type_id`,
  `subject_id`/`status_id`). This matches the expectation that the Dataverse
  pg_dump restore is referentially clean apart from documented source noise.
- **NULL fidelity cross-check**: `title.episode_of_id` has 1,543,264 non-NULL
  values ⇒ 985,048 NULLs, which matches the build pipeline's hardcoded
  `CANONICAL_NULL_COUNTS[("title", "episode_of_id")] = (985_048, 2_528_312)`.
  The dangling census's counting logic therefore agrees with an independent
  in-repo oracle.

## Regenerating / checking

```
# Regenerate (writes the JSON):
uv run -- python _project/scripts/build_joinorder_data.py fk-dangling-census

# Verify the committed artifact is reproducible (recompute + compare):
uv run -- python _project/scripts/build_joinorder_data.py fk-dangling-census --check
```

Both commands fetch and sha256-verify the shipped archive through the runtime
loader before computing, reusing a locally present archive without re-download.
