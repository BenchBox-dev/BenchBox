# Independent publication A6 provisional out-of-order lane authorization

**Status:** Accepted (provisional)
**Date:** 2026-09-02
**Tracker:** `independent-publication-a6-site-and-api-docs-lane`
**Incidents / Reviews:** Adversarial pre-publication review 2026-09-02 (BLOCK: 1 Critical + 7 Required)

## Context

The ratified freeze (`_project/decisions/independent-publication-a0-freeze-2026-08-31.md`)
fixes the order A0→A11 and states: *"A later TODO is not ready merely because it
exists. Its predecessor's named gate must have fresh evidence."*

At landing time, A0, A1, A2 have shipped (`origin/develop` 80589d68e); **A3
(control-plane and artifact contract), A4 (hermetic build and shadow assembly),
A5 (no-op deploy and automatic rollback) have not**. A6 invents the artifact
names (`prose_site`, `api_docs`) and retention policy that A3 is chartered to
define. The build is not hermetic (floating `uv sync`, moving action tags,
`python-version` pinned in-workflow, no `--frozen` lock) and no provenance or
artifact digest is recorded beyond a printed source digest.

## Decision

A6 is authorized to land **out of order as a provisional, non-gating lane**
subject to the following constraints. This decision does not amend the freeze
order; it explicitly subordinates A6 to A3/A4/A5.

1. **Subordinate artifacts.** `prose_site` and `api_docs` as defined in
   `.github/workflows/publication-lane-docs.yml` are **provisional** and will
   be superseded by A3's artifact contract. Retention `90 days` is the
   provisional durable retention pending A3's provenance/digest binding. No
   promotion may consume these artifacts until G2/G3 evidence replaces them.

2. **Non-deploying lane.** The workflow remains `permissions: contents: read`
   with `if-no-files-found: error` and no `pages: write` / `id-token: write`
   / `deploy-pages`. The `prose_only` assembler emits a **non-deployable**
   slice (no `CNAME`, no `404.html`) so a future lane cannot silently deploy
   an incomplete Pages tree.

3. **Provenance gap acknowledged.** The source digest printed by
   `scripts/publication/verify_lane_isolation.py` is **not** a recorded
   provenance artifact. A3 promotion step 5 (*"Build immutable artifacts from
   the pinned inputs and record provenance and digests"*) remains unsatisfied
   and must be closed before the lane is promoted to a required check.

4. **Hermetic build remains A4.** The current `uv sync --group dev` against a
   floating lock, `actions/checkout@v4` / `setup-uv@v4` / `setup-python@v5` on
   moving tags, and in-workflow `python-version: "3.11"` are accepted as
   **non-hermetic provisional build inputs**. A4 must pin the toolchain
   (lockfile frozen, action SHAs, toolchain version from repo) before the lane
   produces anything a promotion consumes.

5. **Soundness gating.** `.github/workflows/publication-lane-docs.yml` and
   `scripts/publication/verify_lane_isolation.py` are added to
   `_project/scripts/auto_merge_soundness_paths.py:SOUNDNESS_FILES` and the
   1:1 `CODEOWNERS` mirror in this same PR, per AGENTS.md
   *"A drift/pinning guard and its required-CI wiring must land in the same PR"*.

## Consequences

- A6's lane is artifact-only and does not gate `develop` tip or package release.
  Push-drop for this lane is accepted risk per
  `docs/operations/develop-push-drop-inventory.md`; recovery is
  `gh workflow run publication-lane-docs.yml --ref develop`.
- The `cancel-in-progress: true` concurrency on pushes to `develop`/`release`
  is accepted while the lane is non-gating; it must be revisited before the
  lane produces anything a promotion consumes (cancelled build is a third
  push-drop class not yet distinguished in the inventory).
- The `SHARED_BUILD_INPUTS` (`benchbox/`, `pyproject.toml`, `uv.lock`) folded
  into every lane digest and the removal of `_blog/` from the site lane close
  the digest/input mismatch found in review finding 4. The workflow trigger set
  is now a subset of `LANE_PREFIXES[site] ∪ SHARED_BUILD_INPUTS`, pinned by
  `tests/unit/scripts/publication/test_verify_lane_isolation.py`.
- `_blog/` remains on `develop` for draft authoring but is stripped from the
  curated `release` tree (`Makefile:1093`) and no longer triggers the A6 lane
  (avoiding wasted 20-minute builds for byte-identical artifacts).
- The `Verify lane isolation` step now wires the PR diff (`git diff --name-only
  origin/${{ github.base_ref }}...HEAD`) into `--changed-paths` and fails closed
  on unclassified inputs; job-level `permissions:` escalation is also detected.

## Alternatives considered

- **Sequence behind A3/A4/A5.** Rejected: would delay the decoupled prose
  build unnecessarily; the provisional lane provides value as an artifact
  producer without promotion authority, with explicit debt documented here.
- **Keep retention 7 days.** Rejected: shorter than the 90-day default and
  materially worsens the artifact-expiry limitation already recorded as a
  required input to G1/G3 in `docs/operations/independent-publication-contract.md`.

## Verification

- `uv run python -m pytest -n 0 tests/unit/scripts/publication/test_verify_lane_isolation.py tests/unit/workflows/test_publication_lane_docs.py tests/unit/scripts/test_assemble_public_site.py tests/unit/workflows/test_develop_post_merge_gaps.py tests/unit/test_auto_merge_soundness_paths.py -q`
- `make compat-docs-check` (no DDL rewrite)
- `ruff check` / `ruff format --check`
