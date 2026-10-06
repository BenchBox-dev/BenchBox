# Internal documents

This directory is never published. Both doc builds exclude it: see
`EXCLUDED_ROOTS` in `website/src/converter/sources.ts` and `exclude_patterns`
in `docs/conf.py`.

Put maintainer documents here: runbooks, repository and CI governance, release
and deploy procedure, evidence and measurement records, incident records, and
planning or design notes that are not for users.

Pages under `docs/development/` and `docs/operations/` are published only when
`docs/publish-allowlist.txt` lists them. Many existing maintainer documents
still live in those two directories, excluded from the builds one by one.
