# Internal documents

This directory is never published: `docs/publish-exclusions.txt`, which both
doc builds read, excludes it.

Put maintainer documents here: runbooks, repository and CI governance, release
and deploy procedure, evidence and measurement records, incident records, and
planning or design notes that are not for users.

Pages under `docs/development/` and `docs/operations/` are published only when
`docs/publish-allowlist.txt` lists them. Many existing maintainer documents
still live in those two directories, each listed in
`docs/publish-exclusions.txt`.
