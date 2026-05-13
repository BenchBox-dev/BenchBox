# Verification Evidence

Local or CI stdout transcripts for verification-only work and TODO `w0:`
re-validation work units. Raw terminal output is useful during review, but it is
usually temporary evidence and should not be committed.

## Layout

```text
_project/verification-logs/<todo-id>/<work-id>.log
```

`<todo-id>` matches the TODO `id:` field. `<work-id>` is the work slot
(use `w0` for re-validation runs that gate the rest of the work). This layout is
for ignored local files or CI artifacts; keep only this README tracked in git.

## Review enforcement

No schema field is required. Reviewers enforce the convention textually: if a
TODO description cites upstream behavior, a dependency version, or a harness
PASS, look for a leading `w0` re-validation work unit plus a compact committed
summary that includes the command, checked SHA/version, result, and the specific
lines/counts the claim depends on. Missing summarized evidence is a review
finding, not a validator failure.

## Capture

Capture raw transcripts outside git, then copy only the durable facts into the
TODO, audit, or PR body. A good committed summary includes:

- exact command, including tool versions when relevant
- checked commit SHA, dependency version, or external evidence pin
- PASS/FAIL result
- small counts, line excerpts, or identifiers needed to replay the claim
- raw artifact location when available, such as a CI artifact name or local
  `BENCHBOX_OUTPUT_DIR` path

Do not capture secrets, signed URLs, or runtime traces -- this is for
upstream-evidence transcripts, not benchmark artifacts.

## Exceptions

Commit a raw log only when it is a deliberate small fixture or durable reference
artifact, not a run transcript. The PR must state the consumer, size, and why a
compact markdown summary is insufficient.
