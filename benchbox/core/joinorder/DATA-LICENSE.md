# JoinOrder Canonical Data License Notes

## Dataset Provenance

BenchBox's canonical `joinorder` dataset is derived from the Harvard Dataverse
`imdb_pg11` archive, DOI `10.7910/DVN/2QYZBT`. The source represents the May
2013 IMDb plain-text list-files snapshot parsed with IMDbPY into the 21-table
relational schema used by the Join Order Benchmark paper, then restored into
PostgreSQL and converted by BenchBox to Parquet for reproducible benchmark use.

The Harvard Dataverse record declares the deposit as `CC0 1.0` and lists
`imdb_pg11` as unrestricted. IMDb's current dataset terms, however, describe the
underlying IMDb data as personal / non-commercial and restrict republication or
repurposing. The JOB paper also describes the IMDb source data as non-commercial.

## IMDb Attribution

Information courtesy of IMDb (https://www.imdb.com). Used with permission.

## Current Redistribution Posture

BenchBox does not treat the current BenchBox-hosted Parquet release asset as
clearly permitted for broad commercial redistribution. The project-owner
decision accepts the remaining redistribution risk for this 2013 academic
benchmark dataset and keeps the verified BenchBox-hosted Parquet archive as the
default data path because direct Dataverse restore/conversion would make first
use substantially heavier. The engineering decision record is:

```text
_project/decisions/joinorder-canonical-data-licensing-2026-05-12.md
```

Use this dataset only under the IMDb and Dataverse terms. Do not treat
BenchBox's converted archive as BenchBox-cleared for broad commercial
redistribution or republication.

## Scope

This data is provided for research, database systems evaluation, and query
optimizer benchmarking. It is not intended for consumer IMDb replacement
services, republication as a general-purpose movie database, or commercial
redistribution outside benchmark reproducibility.

## Redistribution Disclaimer

BenchBox redistributes a derivative form of this dataset as a convenience for
benchmark reproducibility. Optional follow-up work may seek explicit permission
or add an advanced direct-Dataverse/BYO data path, but the default user
experience remains the verified BenchBox-hosted Parquet archive. BenchBox makes
no claim of ownership over the underlying IMDb data and will honor takedown
requests.

## Takedown Contact

Send takedown or licensing concerns to `joeharris76@gmail.com`.
