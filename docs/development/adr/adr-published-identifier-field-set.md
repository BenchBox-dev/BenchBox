# ADR: Drop unread identifier fields from the published corpus

- Status: Accepted
- Date: 2026-08-04
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
publication boundary rather than pseudonymising them.

For the three that do have a consumer, keep publishing a pseudonym and treat
the salt question as open (see Consequences).

## Alternatives considered

**Mint a real default salt.** Preserves every field and closes the oracle for
future captures. Rejected as the primary remedy because it does not close it
for the corpus already published — those bytes are already public and the
history is retained — and because it keeps paying a privacy cost for data no
consumer reads. A hashed `working_dir` has no analytical value; the reductio is
`database_5d7b725135a6`, which decodes to the string `benchbox`. Salting is
still the right answer for the three fields with readers, which is why it stays
open rather than rejected outright.

**Accept the oracle and document it.** Defensible on the material exposed so
far — a repository path and a database name are low sensitivity. Rejected
because the exposure scales with contributors, not with us: `engine_host` and a
submitter's home directory carry real names, and the corpus is meant to accept
community submissions. Choosing to publish confirmable identifiers on other
people's behalf is not ours to make silently.

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
- The salt question stays open for `endpoint`, `database_name`, and
  `submission_path`. Whatever is decided must preserve the publication fixed
  point from #1512: an already-pseudonymised value passes through unchanged, so
  rotating the salt does not re-pseudonymise a stored corpus.

## What this does not change

`[COMMIT-IDENTITY-001]`, trust labels, and provenance are untouched. Pseudonym
identity was never a provenance signal and must not become one — a submitter
can choose a pseudonym-shaped value and have it pass through by design.
