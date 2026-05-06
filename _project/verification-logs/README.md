# Verification Logs

Committed stdout transcripts for verification-only commits and TODO
`w0:` re-validation work units. Terminal output cited in commit
messages isn't replayable; checked-in logs are.

## Layout

```text
_project/verification-logs/<todo-id>/<work-id>.log
```

`<todo-id>` matches the TODO `id:` field. `<work-id>` is the work slot
(use `w0` for re-validation runs that gate the rest of the work).

## Capture

The exact command (including tool versions) and the output the TODO's
claim depends on. Trim aggressively; don't dump megabytes.

Do not capture secrets, signed URLs, or runtime traces -- this is for
upstream-evidence transcripts, not benchmark artifacts.
