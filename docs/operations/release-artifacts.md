# Release artifact contract

Release admission consumes the exact wheel and sdist from a successful
merge-queue CI attempt. It never rebuilds or publishes packages.

## Producer

The `dist-artifact` job of `.github/workflows/ci.yml` runs only on
`merge_group`. Its artifact name is
`dist-<full head SHA>-attempt-<positive run attempt>`.

The artifact contains exactly four regular files at its root:

- one wheel (`*.whl`);
- one sdist (`*.tar.gz`);
- `SHA256SUMS`, containing exactly their two SHA-256 hashes and basenames;
- `producer-receipt.json`.

The receipt has schema `1` and records `repository`, `repository_id`,
`head_repository_id`, `workflow_path`, `head_sha`, `run_id`, `run_attempt`,
`job_id`, `job_name`, `artifact_name`, `sha256sums_sha256`, and `files`.
`files` maps each distribution basename to its `size` and `sha256`.
The producer reads its actual job ID from the attempt-scoped GitHub jobs API.
It cannot record the artifact ID or ZIP digest before upload; admission obtains
those values from GitHub and binds them to this receipt.

This replaces the former three-file `dist-<SHA>` format. Older artifacts lack
attempt evidence and are refused. They cannot be upgraded by local metadata or
by choosing an earlier successful run.

## Admission

Run from an exact checkout of an annotated `v*` version tag:

```bash
uv run -- python scripts/release_artifact_consumer.py admit \
  --source . --tag v0.4.2 --output /tmp/benchbox-release-admission
```

The command fetches `develop`, checks tag/version agreement and ancestry, and
selects the latest exact-SHA CI run. The run must belong to
`BenchBox-dev/BenchBox`, use `.github/workflows/ci.yml`, and have completed
successfully on `merge_group`. Its exact attempt must have one successful
`dist-artifact` job and one unexpired attempt-qualified artifact.

Admission verifies the API ZIP digest before reading any archive member. It
rejects paths, duplicate names, links, nonregular members, encryption, extra
files, and payloads larger than 256 MiB. It recomputes the distribution hashes,
requires the producer receipt to match the actual run and job attempt, and
checks package/version identity. The exact tagged source's distribution binary
verifier must exist and pass. Metadata is read again before an admission receipt
and verified files appear in the new output directory.

An admission receipt is byte and producer evidence. It is not a cryptographic
attestation or permission to release. Admission does not change hosted tag
rules, environments, or publishing workflows.

## Release requirements

The publishing workflow still requires the live `v-tag-restricted` rule,
verifiable provenance attestation, all twelve Python 3.11–3.14 installation and
smoke cells across Linux/macOS/Windows, artifact-bound release UAT, the binary
manifest, `make release-check`, ruleset drift checks, and no open
release-blocking `t3:*` issue. Linux correctness evidence remains separate from
the deferred Darwin digest certification.

TestPyPI rehearsals must exercise refusal paths and verify installed hashes.
Production PyPI retains owner approval. The existing `release.yml` remains
operational until its approved replacement is accepted.
