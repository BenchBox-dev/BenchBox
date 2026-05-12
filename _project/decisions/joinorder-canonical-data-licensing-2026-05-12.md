# ADR: JoinOrder Canonical Data Redistribution

Date: 2026-05-12

Status: Not clearly permitted; release-blocking remediation required

## Question

May BenchBox re-host and redistribute the canonical JoinOrder IMDb 2013 dataset
as a BenchBox-owned GitHub Release asset?

The current public `joinorder` data path downloads
`joinorder-imdb-2013-v1.tar.zst` from a BenchBox GitHub Release. That archive is
a Parquet conversion of the Harvard Dataverse `imdb_pg11` deposit for DOI
`10.7910/DVN/2QYZBT`, which itself derives from IMDb data used by the Join Order
Benchmark paper.

## Determination

BenchBox should not treat re-hosting the converted IMDb-derived archive as
clearly permitted without either written permission or a design change that
avoids BenchBox redistribution.

The Dataverse record is favorable because the deposited pg_dump is published
under CC0 1.0 and is unrestricted. That is not enough to clear the upstream IMDb
terms: IMDb's current public dataset terms limit IMDb data to personal and
non-commercial use, and the JOB paper describes the IMDb source as available for
non-commercial use. CC0 also does not remove rights held by other people or
entities in the work.

## Evidence Digest

Retrieved on 2026-05-12.

| Source | Evidence | Impact |
|---|---|---|
| IMDb Non-Commercial Datasets, `https://developer.imdb.com/non-commercial-datasets/` | States IMDb dataset subsets are for "personal and non-commercial use". | BenchBox's commercial-benchmarking audience makes GitHub Release redistribution risky. |
| IMDb help, `https://help.imdb.com/article/imdb/general-information/can-i-use-imdb-data-in-my-software/G5JTRESSHJBBHTGX` | Allows "Limited non-commercial use" and says data "must not be altered/republished/resold/repurposed". | Re-hosting converted Parquet is republishing/repurposing unless separately permitted. |
| Harvard Dataverse API, `https://dataverse.harvard.edu/api/datasets/:persistentId/?persistentId=doi:10.7910/DVN/2QYZBT` | Dataset license is "CC0 1.0"; file `imdb_pg11` is unrestricted and has MD5 `df3e976b235288005cb410cea09a115f`. | Positive for the depositor's rights in the deposit, but not dispositive for IMDb's upstream rights. |
| Creative Commons CC0 deed, `https://creativecommons.org/publicdomain/zero/1.0/` | CC0 permits use "even for commercial purposes" but does not affect "rights that other persons may have". | CC0 does not override IMDb's retained rights or terms. |
| JOB paper, `https://www.vldb.org/pvldb/vol9/p204-leis.pdf` | Describes IMDb as "freely available for non-commercial use". | The original benchmark publication does not support a broad commercial redistribution conclusion. |
| gregrahn JOB repository, `https://github.com/gregrahn/join-order-benchmark` | The repository has no GitHub-detected license and its README points readers to IMDb for "license and links". | The query repo distributes queries and references data sources; it does not grant BenchBox redistribution rights. |

## Rationale

The strongest permissive fact is the Dataverse record's CC0 1.0 license. If the
only rights at issue were the depositor's rights in the pg_dump packaging, CC0
would support redistribution and commercial use.

The upstream-data facts cut the other way. IMDb publishes the relevant data under
non-commercial terms and restricts republishing or repurposing. The JOB paper
itself describes the source data as non-commercial. Because BenchBox is
redistributing a transformed full dataset through a BenchBox-controlled release
asset, the safe engineering conclusion is that this redistribution path is not
clearly permitted.

This ADR is not legal advice. It is an engineering release-risk decision based on
published terms.

## Required Remediation

File and implement a follow-up before treating canonical `joinorder` as
release-ready with BenchBox-hosted data:

1. Stop re-hosting the converted archive and fetch directly from Dataverse, then
   convert/verify locally.
2. Or seek written permission covering BenchBox's GitHub Release redistribution
   and commercial-benchmarking context.
3. Or gate the current data path behind explicit user-provided data / BYO
   Dataverse download until permission is resolved.

Preferred remediation: fetch `imdb_pg11` directly from Dataverse and convert
client-side or cache locally under BenchBox's existing data directory. This keeps
BenchBox from redistributing IMDb-derived data while preserving canonical source
provenance.

## Consequences

- `benchbox/core/joinorder/data_manifest.toml` is not changed by this ADR.
- `DATA-LICENSE.md` and user-facing docs must stop implying that BenchBox's
  re-hosting is clearly permitted.
- Follow-up TODO: `_project/TODO/main/planning/joinorder-data-fetch-from-dataverse-remediation.yaml`.
- Canonical `joinorder` remains valuable and validated, but the release posture
  must track the unresolved redistribution risk until remediation lands.
