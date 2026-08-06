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

**The pseudonyms are a confirmation oracle.** `machine_id_salt` defaults to
`None`, so the digest is computed over an empty salt, and the algorithm is
documented in `docs/reference/result-formats.md`. Anyone can hash a candidate
value and match it against the corpus with certainty — no false positives, no
rate limit, no server involved. A 1550-candidate dictionary sweep over the 1615
pseudonym occurrences in `results-data/` confirmed two distinct tokens in about
a second, and the double-hashed form of one of them is present on the public
`published-results` branch. Double hashing provides no protection: the
transform is deterministic and public, so an attacker simply applies it twice.

The existing gate cannot see this. `find_public_path_leaks` detects *plaintext*
absolute paths, so it reports the corpus clean while the corpus is recoverable
by dictionary. It measures the wrong property.

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

The read model has no machine or host column. The stated motivation for the
idempotence fix in #1512 — "pseudonym stability is what lets the Explorer
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

Retained published identifiers (`endpoint`, `database_name`,
`submission_path`) therefore remain a **residual confirmation oracle** under
the empty default: anyone who knows the documented algorithm can hash a
candidate and match corpus tokens with certainty. That residual is accepted for
the curated maintainer seed corpus and documented; it is **not** accepted as
the right default for an operator who will publish other people's submissions.

| Option | Outcome | Decision |
|---|---|---|
| Keep empty default salt | Residual oracle on retained fields; fixed point and current corpus bytes unchanged | **Chosen for OSS default** |
| Mint a baked-in non-empty default salt | Salt is public in git, so the oracle remains; only obscures the empty-string case | **Rejected** |
| One-time rehash of retained fields under a new salt | Breaks the #1512 publication fixed point; rotates `result_id` again; history still holds the old tokens; without a *secret* salt the oracle returns | **Rejected** |
| Require a non-empty operator-configured salt before public export | Closes the oracle for deployments that set it; needs a secret outside the repo | **Recommended for community-facing operators** (documented; not a hard fail of the OSS default path in this ADR) |

Rationale:

1. **A salt in the repository is not a secret.** Hashing with a public constant
   is still a confirmation oracle. "Mint a default salt" only helps if the salt
   never ships in the open tree.
2. **The publication fixed point stays.** Already-public-shaped
   `endpoint_` / `database_` / `path_` tokens continue to pass through. A
   one-time rehash would not remove retained history tokens on
   `published-results` and would force another free-only-once `result_id`
   rotation after #1578.
3. **The unread-field drop already removed the highest-risk empty-salt
   surfaces** (`machine_id`, home-directory paths, `engine_host`, …). What
   remains is low-entropy product material (database names, local endpoints)
   plus whatever community submitters put in retained keys — the latter is why
   operators must set a real salt before accepting third-party submissions.
4. **Operators close the residual.** Set `AnonymizationConfig.machine_id_salt`
   (or the equivalent export config) to a non-empty value known only to the
   deployment *before* the first public publish. New raw values then hash under
   that salt; already-published tokens still pass through by design.

## Alternatives considered (field-set)

**Mint a real default salt (in-repo).** Preserves every field and appears to
close the oracle for future captures. Rejected as the primary remedy for the
*unread* fields because it does not close the oracle for the corpus already
published, keeps paying a privacy cost for data no consumer reads, and — once
the salt question is examined for retained fields — a baked-in salt is still
public. A hashed `working_dir` has no analytical value; the reductio is
`database_5d7b725135a6`, which decodes to the string `benchbox`.

**Accept the oracle and document it (for unread fields).** Defensible on the
material exposed so far — a repository path and a database name are low
sensitivity. Rejected for the six unread fields because the exposure scales
with contributors: `engine_host` and a submitter's home directory carry real
names. Choosing to publish confirmable identifiers on other people's behalf is
not ours to make silently. For the three retained fields the residual is
documented instead of denied (see salt decision above).

**Keep pseudonymising but stop publishing the bundles.** Not a real option; the
bundles are the product.

## Consequences

- Every bundle's bytes change, so **every `result_id` changes**. That is free
  exactly once, while no Explorer is deployed and `published-results` records
  no `result_id`. It is not free later. See
  `public-result-id-permanence-and-documented-format`.
- This supersedes the re-derivation in progress in #1537, which re-derives to a
  single anonymization pass but keeps the field set. Doing both as one
  re-derivation avoids rotating every id twice.
- `find_public_path_leaks` stays, but is no longer sufficient on its own. A
  recovery gate that attempts dictionary confirmation against the corpus is
  required alongside it.
- Retained `published-results` history keeps the superseded values reachable.
  That decision was recorded in `adr-published-results-history-retention.md`
  before reversibility was known, and is re-examined separately under
  `published-history-retention-premise-predates-oracle`.
- Retained-field salt decision (2026-08-05): empty OSS default; residual
  confirmation oracle documented; operator-configured non-empty salt recommended
  for community-facing publishes; publication fixed point from #1512 preserved.
- Residual local-path keys (2026-08-05): additional pure-FS compact keys dropped
  at the public boundary; remote-ish path/host keys remain hashed; no corpus
  re-derive when tip bundles lack those keys.

## What this does not change

`[COMMIT-IDENTITY-001]`, trust labels, and provenance are untouched. Pseudonym
identity was never a provenance signal and must not become one — a submitter
can choose a pseudonym-shaped value and have it pass through by design.
