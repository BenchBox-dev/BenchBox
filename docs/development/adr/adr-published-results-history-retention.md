<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# ADR: Retain `published-results` git history after the 2026-08-04 corpus leak

```{tags} adr, privacy, operations
```

**Status:** Accepted — 2026-08-04
**Scope:** the `published-results` branch only

## Context

Between 2026-08-03 and 2026-08-04 the public `published-results` branch served
the pre-#1467 corpus. Measured with the repository's own canonical detector
(`find_public_path_leaks`):

| | value |
|---|---|
| primary bundles carrying private absolute paths | **183 of 207** |
| bundles exposing the raw 16-hex internal `machine_id` | **206 of 207** |
| repository visibility | public |

The leaked material is **machine-local absolute paths** — home directories
containing a username, working directories, and Python executable paths — plus
the capture-side machine identifier, which is itself a salted SHA-256 and not a
hardware ID. No credentials, tokens, keys, connection strings, or customer data
were exposed; those are redacted on a separate path that was working correctly.

The tip was corrected by #1535, which mirrored develop's sanitized corpus.
Verified after merge: 0 leaking files across 400, and all 206 `machine_id`
values are 12-hex public pseudonyms.

The commits carrying the old content remain reachable in that branch's history.

## Decision

**Retain the history. Do not rewrite `published-results`.**

## Rationale

1. **Rewriting does not retract.** The content has been public and cloneable.
   A force-push cannot recall clones, forks, GitHub's cached commit views, or
   anything already fetched or indexed. It converts a known exposure into an
   exposure plus a false belief that it was undone.
2. **The exposure class is low severity.** Usernames and directory layout, not
   secrets. The realistic harm is minor deanonymization of contributors whose
   bundles are in the corpus — and the corpus is authored by the maintainer.
3. **The cost is real and borne by others.** A force-push breaks every existing
   clone and fork of a branch whose entire purpose is to be consumed by
   outside contributors, and by the Explorer build pipeline.
4. **Rotation is available and cheaper.** Pseudonym identity can be rotated by
   re-deriving the corpus under a new `machine_id_salt`, which changes every
   published pseudonym without touching history. See the "Salt rotation"
   section of `docs/reference/result-formats.md`.

## Consequences

- The pre-#1467 values stay retrievable by commit SHA on a public branch. This
  is accepted, not overlooked.
- If material of a **higher** severity class (a credential, a token, customer
  data) is ever found on that branch, this decision does not apply: that is a
  rotate-the-secret-and-then-decide situation, and rewriting may be justified
  because the secret can actually be invalidated.
- The detection gap that allowed this is addressed separately by
  `.github/workflows/corpus-drift-check.yml`, a **scheduled** canary. It is
  scheduled rather than push-triggered because the root cause was lost push
  events, not a bad path filter — see that workflow's header for the evidence.

## Alternatives rejected

| Alternative | Why rejected |
|---|---|
| `git filter-repo` + force-push | Does not retract already-public content; breaks all clones and forks; disproportionate for path/username exposure |
| Delete and recreate the branch | Same non-retraction problem, plus loses the mirror audit trail linking each corpus state to a develop SHA |
| Make the repository private | Defeats the purpose of a public results corpus |
