# JoinOrder Canonical Data Provenance Attestation

Date: 2026-05-12

Status: Dataverse source attested; conversion fidelity verified; byte-identical
rebuild not established.

## Source Checksum Attestation

Canonical source:

- DOI: `10.7910/DVN/2QYZBT`
- Dataverse file: `imdb_pg11`
- File id: `3590041`
- File persistent id: `doi:10.7910/DVN/2QYZBT/TGYUNU`
- Access URL: `https://dataverse.harvard.edu/api/access/datafile/3590041`
- Retrieval method: Dataverse native API at
  `https://dataverse.harvard.edu/api/datasets/:persistentId?persistentId=doi:10.7910/DVN/2QYZBT`

Dataverse-published metadata retrieved on 2026-05-12:

- Dataset license: `CC0 1.0`
- Restricted: `false`
- File size: `1277543282`
- Checksum type: `MD5`
- Checksum value: `df3e976b235288005cb410cea09a115f`

Local cached pg_dump verification:

- Local MD5:
  `df3e976b235288005cb410cea09a115f`
- Local SHA256:
  `1390a764ee76d03d80fd6743ec7a6e5f22493411967582e4f1ecc2e282c1a59c`
- Manifest pin:
  `benchbox/core/joinorder/data_manifest.toml [provenance].pg_dump_sha256`
- Verdict: the Dataverse-published MD5 matches the cached source pg_dump; the
  pinned SHA256 is a local stronger digest over that same file.

The restore validation in
`/Users/joe/Developer/benchmark_runs/logs/joinorder_canonical_data_assurance_20260512T1348Z/restore.log`
matched 21/21 expected tables and 74,190,187 rows.

## Query Corpus Pin

The canonical SQL corpus is pinned to gregrahn/join-order-benchmark commit
`a39603662e023e449cb2121997a5034df9e02ebf`, matching
`benchbox/core/joinorder/data_manifest.toml [provenance].gregrahn_commit`.

## Rebuild Check

Command family:

```bash
uv run -- python _project/scripts/build_joinorder_data.py rebuild-local \
  --work-dir /Users/joe/Developer/benchmark_runs/joinorder/rebuild-check/20260512T1348Z/run1 \
  --container-name benchbox-joinorder-assurance-pg

uv run -- python _project/scripts/build_joinorder_data.py rebuild-local \
  --work-dir /Users/joe/Developer/benchmark_runs/joinorder/rebuild-check/20260512T1348Z/run2 \
  --container-name benchbox-joinorder-assurance-pg
```

Full log:
`/Users/joe/Developer/benchmark_runs/logs/joinorder_canonical_data_assurance_20260512T1348Z/rebuild-check.log`

Archive hashes:

| Artifact | SHA256 |
|---|---|
| Committed `archive_sha256` | `669c97ce7e9e7498c7ce0cad018153aa93a9b8eefff0f77e436d690f64ebc5fd` |
| Rebuild run 1 | `e24bc0f1a12ab7619942da4b985d2eae809686b0d986005334bada93692e0a49` |
| Rebuild run 2 | `adf28547f5c2b90884a0e2564cdf8a42b9a1c16192461dcc02a78677e21fa952` |

Table byte-hash mismatches:

| Table | Committed Parquet SHA256 | Run 1 SHA256 | Run 2 SHA256 |
|---|---|---|---|
| `cast_info` | `078034cb5caeefba342b0ab53128c8785da0338bfe9581e621b8b070f8cd66b1` | `b9816816e8ee8cadb2f5d1f5fdc53f7be19b80be0d512f75d41ebcb4cb7a03c2` | `9301218b89737395845487ce14a36bc64a1ca918f8490058db940cfda7a39c7a` |
| `title` | `a0510d815b83acb29e61aacead72c0c5777b3169f49bab982184c8dbbc3be48f` | `da8cb57b754c60f37124ea327ba9ffa53f4e929f26f6d7d1d45e77b5f2cddbfd` | `da8cb57b754c60f37124ea327ba9ffa53f4e929f26f6d7d1d45e77b5f2cddbfd` |

Verdict: the rebuild is not byte-identical to the committed release artifact,
and at least `cast_info.parquet` is not byte-deterministic between two local
rebuilds. Do not claim byte-identical archive reproducibility until the
follow-up decision is resolved.

## Conversion Fidelity Check

Command:

```bash
uv run -- python _project/scripts/build_joinorder_data.py verify-conversion-fidelity \
  --work-dir /Users/joe/Developer/benchmark_runs/joinorder/rebuild-check/20260512T1348Z/run2 \
  --container-name benchbox-joinorder-assurance-pg
```

Full log:
`/Users/joe/Developer/benchmark_runs/logs/joinorder_canonical_data_assurance_20260512T1348Z/conversion-fidelity.log`

Result:

- 21 row-count checks passed.
- 37 null/empty-string checks passed.
- 59 integer-width checks passed.
- 4 UTF-8 column groups passed.

## Current Integrity Statement

The current released archive is still protected by its pinned transport
`archive_sha256`, per-table Parquet `sha256` values, row counts, and
manifest-level hashes. The external source pg_dump is now anchored to the
Dataverse-published MD5 plus the pinned local SHA256.

The unresolved gap is rebuild reproducibility: rebuilding from the same restored
source does not currently reproduce byte-identical Parquet/archive artifacts.
Follow-up TODO:
`_project/TODO/main/planning/joinorder-parquet-rebuild-determinism-decision.yaml`.
