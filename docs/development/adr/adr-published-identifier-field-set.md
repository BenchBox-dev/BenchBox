# ADR: Drop unread identifier fields from the published corpus

- Status: Accepted (implemented at the public anonymization boundary;
  retained-field salt closed 2026-08-05; residual local-path drop 2026-08-05)
- Date: 2026-08-04; salt amendment 2026-08-05; residual path/host keys 2026-08-05
- Supersedes nothing. Constrains `benchbox/core/results/anonymization.py` and
  any future re-derivation of `results-data/`.

## Context

The public anonymization boundary replaces machine-local strings with
`<prefix>_<12 hex>` pseudonyms. Two facts about that scheme were established
together and change the picture:

**The pseudonyms did not prevent re-identification.** The published identifier
fields allowed the original values to be re-identified.

The existing gate cannot see this. `find_public_path_leaks` detects *plaintext*
absolute paths, so it reports the corpus clean even when its pseudonyms can be
re-identified. It measures the wrong property.

**Most of the protected fields have no reader.** An audit across the publication
pipeline, the Explorer application, and the published contract found that six of
the nine pseudonymised field names are consumed by nothing:

| field | pipeline | Explorer app | contract |
|---|---|---|---|
| `machine_id` | – | – | – |
| `working_dir` | – | – | – |
| `driver_runtime_python_executable` | – | – | – |
| `database_path` | – | – | – |
| `data_path` | – | – | – |
| `engine_host` | – | – | – |
| `submission_path` | – | – | yes |
| `database_name` | – | yes | – |
| `endpoint` | yes | yes | yes |

The read model has no machine or host column. The stated motivation for making
anonymization idempotent — "pseudonym stability is what lets the Explorer
correlate results from the same machine" — describes a capability that is not
implemented. Nothing correlates by machine today.

## Decision

**Do not publish the six fields that have no consumer.** Remove them at the
publication boundary rather than pseudonymising them. Also omit compact-form
**aliases** of those fields (`workdir`, `workingdirectory`, `workingroot`,
`datadir`, `datadirectory`, `pythonexecutable`) so alternate spellings cannot
reintroduce empty-salt path tokens. `host` / `hostname` / `server` stay hashed
rather than dropped: they are broader than `engine_host`.

For the three that do have a consumer, keep publishing a pseudonym. The
retained-field salt decision is recorded below (closed 2026-08-05).

## Residual path/host keys (2026-08-05)

After the six-field drop and alias rows, several **pure local filesystem**
keys could still mint empty-salt `path_` tokens under `path_keys` / suffix
rules, with no Explorer or publication-pipeline consumer. Treat them like the
other unread local identifiers: **drop**, do not hash.

| compact key class | policy | rationale |
|---|---|---|
| `outputdir`, `outputdirectory`, `outputpath`, `outputlocation` | **drop** | Local run output location; no public reader |
| `resultdir`, `resultpath` | **drop** | Local results location; no public reader |
| `logpath`, `logfile` | **drop** | Local log location; no public reader |
| `filepath`, `path` | **drop** | Exact key name only (compact); not `submission_path` / `*_path` retained consumers |
| `sourceroot` | **drop** | Local source tree root; no public reader |
| `credentialfile` | **drop** | Local credential path; omit entirely (stronger than redact-in-place) |
| `datadir` / `datadirectory` / `workdir` family | **drop** | Already covered by unread-field aliases |
| `sslrootcert` | **keep hash** | libpq spelling; intentional privacy hash for cert path material |
| `s3stagingurl`, `staginglocation`, `stagingurl`, `httppath` | **keep hash** | May embed account/tenant; not pure local FS |
| `host`, `hostname`, `server` | **keep hash** | Broader than `engine_host`; may be remote endpoints |
| `endpoint`, `database_name`, `submission_path` | **keep hash** | Retained consumers (see field-set table above) |

Corpus inventory (tip `results-data/` JSON): none of the newly dropped compact
keys appear as object keys, so **no full re-derive** is required for this
amendment. Fixed-point / privacy gates remain the regression bar.

## Retained-field salt decision (2026-08-05)

**Keep the empty default salt in open-source BenchBox. Do not mint a
repository-baked default salt. Do not one-time rehash retained fields.**

The published pseudonym contract on retained fields (`endpoint`,
`database_name`, `submission_path`) uses deployment-configured salting.
Community-facing deployments configure a deployment-private salt prior to
exporting or submitting public bundles.

| Option | Outcome | Decision |
|---|---|---|
| Keep empty default salt | Default behavior in open-source repository; local fixed point preserved | **Chosen for OSS default** |
| Mint a baked-in non-empty default salt | Public in repository; does not provide deployment privacy | **Rejected** |
| One-time rehash of retained fields under a new salt | Breaks publication fixed point and rotates public identifiers | **Rejected** |
| Require a non-empty operator-configured salt before public export | Deployment-private salting for community-facing operators | **Recommended for community-facing operators** |
Rationale:

1. **A salt in the repository is not secret.** A repository constant does not provide
   deployment-specific privacy for third-party submissions.
2. **The publication fixed point stays.** Already-public-shaped
   `endpoint_` / `database_` / `path_` tokens continue to pass through. A
   one-time rehash would force another `result_id` rotation, which is a
   compatibility event for public routes.
3. **The unread-field drop already removed unused local identifier surfaces.**
   Retained fields represent explicit readers (`endpoint`, `database_name`,
   `submission_path`).
4. **Operators configure deployment salts.** Set `AnonymizationConfig.machine_id_salt`
   or the `BENCHBOX_MACHINE_ID_SALT` environment variable to a non-empty value
   before exporting third-party submissions. `benchbox submit` validates that a
   non-empty salt is configured before community submission.
## Alternatives considered (field-set)

**Mint a real default salt (in-repo).** Rejected because a baked-in salt in an
open-source repository is not private and does not eliminate the need for
operator-managed deployment salts.

**Retain unread fields.** Rejected because unread local identifiers carry
unnecessary privacy overhead for fields with no analytical consumers.

**Keep pseudonymising but stop publishing the bundles.** Not a real option; the
bundles are the product.

## Consequences

- Every bundle's bytes change, so **every `result_id` changes**. The rotation
  happened before result routes were publicly served, so it needed no redirect.
  Any later rotation of a public id is a compatibility event; see
  [ADR: `public_result_id` permanence attaches at publication](adr-public-result-id-permanence.md).
- The field-set drop and the move to a single anonymization pass share one
  re-derivation, so every id rotates once rather than twice.
- `find_public_path_leaks` verifies that plaintext paths do not appear in public bytes.
- Retained `published-results` history keeps earlier revisions accessible under standard git history.
- Retained-field salt decision (2026-08-05): empty OSS default; operator-configured
  non-empty salt required for community-facing submissions; publication fixed point preserved.
- Residual local-path keys (2026-08-05): additional pure-FS compact keys dropped
  at the public boundary; remote-ish path/host keys remain hashed; no corpus
  re-derive when tip bundles lack those keys.

## What this does not change

Trust labels and provenance are untouched. Pseudonym
identity was never a provenance signal and must not become one — a submitter
can choose a pseudonym-shaped value and have it pass through by design.
