# Single-repo migration: decisions (D1–D8)

**Date**: 2026-04-26
**Plan**: `~/.claude/plans/single-repo-migration.md` (Option B, amended to a two-branch model)
**Status**: approved; gates Phase 0.

## Context

BenchBox is migrating from a two-repo split — `joeharris76/benchbox-private`
for development, `joeharris76/BenchBox` for the public release-shaped mirror —
to a single canonical repository on GitHub. The plan called this **Option B**:
keep `joeharris76/BenchBox` canonical, archive the private repo, leave bulk
private history behind, and preserve `_project/**` history via
`git filter-repo` merge.

A user-driven amendment refines Option B: **`main` is reserved for released
code only.** All development work happens on a long-lived **`develop`** branch.
Maintainer scaffolding (`_project/`, `_blog/`, agent instructions, dev-only
tooling) lives only on `develop`. Releases land on `main` via curated overwrite
from `develop` — one release-shaped commit per release. The existing
curated-sync engine (`benchbox/release/workflow.py`,
`scripts/prepare_release.py`) survives the migration repurposed for
branch-to-branch use; it is no longer a two-repo bridge but a `develop` →
`main` filter.

## Decisions

| ID | Decision | Choice | Reason |
|---|---|---|---|
| D1 | Canonical GitHub URL | `joeharris76/BenchBox` stays canonical, default branch stays `main`. Archive `joeharris76/benchbox-private` after dev-locus migration. | Avoids the only irreversible step (no rename, no visibility flip). Visitors see the polished release tree at the default URL. |
| D2 | Bulk private commit history | Leave behind. Working-tree contents only via the final curated sync, into the new `develop` branch on public. **D2a (`_project/**` history)**: preserve via `git filter-repo --path _project/` + `--allow-unrelated-histories` merge into `develop`. Reconfirm D2a after Phase 0 audit. | No archaeological value in a year of solo `wip:`/`hack:` commits; removes audit burden on every commit message. `_project/**` carries decision rationale worth preserving on a narrow filter. |
| D3 | `_project/TODO` and `_project/DONE` location | On `develop` only; never reaches `main`. | Per the `main`-is-released-code directive. Released wheels never carry TODO/DONE under any model. |
| D4 | `_blog/` location | Entire `_blog/` on `develop` only; never reaches `main`. Working-tree only (no history preserved). | Per the `main`-is-released-code directive. Drafts and published posts alike are dev-side artefacts under the new model. |
| D5 | Merge strategy | (a) Dev PRs → `develop`: squash-merge. (b) Releases use a short-lived `vX.Y.Z` release branch cut from `develop`: curate the tree on the release branch, **squash-merge** to `main` (one commit per release on main), tag the resulting `main` commit, then **rebase `develop` onto `main`** so the next dev cycle starts from the release-shaped state. (c) Version-branch lifecycle: keep `vX.Y.Z` until the next release branch is cut, then delete (option c). (d) Phase 4 one-time `_project/**` filter-merge → `develop`: regular merge commit (squashing defeats the purpose). | Keeps `main` lineage release-only; supports clean hotfix re-cuts during the active release window; rebase keeps `develop` linear off `main` rather than diverging; standard squash for routine dev. |
| D6 | Continuous CI surface | Every push to `develop`, every push to `main`, every PR targeting either branch. Same checks as today's `automate_release.py:run_ci_checks` (ruff check, ruff format --check, ty check, fast pytest with coverage gate). | Removes CI gating from the release path. Both branches stay green at all times. |
| D7 | Reproducibility | Keep `SOURCE_DATE_EPOCH=$(git log -1 --format=%ct ${tag})` in `release.yml`. Drop the rest of the timestamp-normalization machinery. | The wheel was the only consumer that mattered; the rest was unverified. |
| D8 | Disposition of `/Users/joe/Developer/BenchBox` (private clone) after Phase 5 | Rename to `BenchBox.retired-YYYYMMDD/`. Future development happens in `~/Developer/benchbox-public` on the `develop` branch (not `main`). Delete after 60-day soak. | Renaming prevents shell muscle-memory mistakes; the soak preserves an emergency reference. |

## Architectural facts (apply across all phases)

- **A1 — Branch name**: long-lived dev branch is `develop`.
- **A2 — Default branch on GitHub**: stays `main`, so the canonical URL shows the release tree.
- **A3 — Tree split**:
  - **`main` only**: `benchbox/`, `tests/`, `docs/`, `examples/`, `_binaries/`, `_sources/`, `_chart_data/`, release-related contents of `scripts/`, `pyproject.toml`, `MANIFEST.in`, `Makefile`, `README.md`, `CHANGELOG.md`, `LICENSE`, `COPYRIGHT.md`, `DISCLAIMER.md`, `CONTRIBUTING.md`, `pytest.ini`, `pytest-ci.ini`, `_benchbox_pytest_xdist_safety.py`, `uv.lock`, `.gitignore`, `.codespell-ignore.txt`, `landing/`, `.github/` (workflows + templates).
  - **`develop` only** (in addition to everything on `main`): `_project/`, `_blog/`, `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.claude/`, `.codex/`, `.gemini/`, `.pre-commit-config.yaml`, `todo.config.yaml`, `skill-sync.yaml`, `skill-sync.lock`, `.gitattributes`, `.coveragerc_core`, `.dockerignore`, `.env.example`, `.mcp.json`, dev-only scripts.
- **A4 — Release flow** (post-migration, repeated each release):

  ```
  1. develop is at SHA D (current dev state).
  2. Cut release branch:
       git checkout -b vX.Y.Z develop
  3. Curate the vX.Y.Z branch tree (drop _project/, _blog/, agent
     configs, dev-tooling root files via `git rm` directly in the
     Makefile target; bump version; generate CHANGELOG entry; commit on
     vX.Y.Z). Note: an earlier draft of this plan kept `workflow.py` /
     `prepare_release.py` repurposed for branch-to-branch curation, but
     the actual `make release-prepare` implementation uses `git rm`
     directly, so those modules were deleted in Phase 6 alongside the
     other release tooling.
  4. Squash-merge vX.Y.Z into main:
       git checkout main && git merge --squash vX.Y.Z
       git commit -m "Release vX.Y.Z"
  5. Tag the release on main:
       git tag vX.Y.Z && git push origin main vX.Y.Z
     → release.yml workflow fires; publishes to PyPI.
  6. Rebase develop onto main, dropping commits that became the release:
       git rebase --onto main vX.Y.Z develop
     → develop now starts from the release-shaped main HEAD; only
       post-release dev work replays.
  7. Delete the previous release branch (option c lifecycle):
       once the next release branch (vX.Y.Z+1) is cut, delete vX.Y.Z
       (the tag on main is the canonical reference). The branch is kept
       in the meantime so any same-version hotfix can re-cut from it.
  ```
- **A5 — Version-branch lifecycle (option c)**: a `vX.Y.Z` branch is
  cut at step 2, used for curation + squash-merge at step 4, kept alive
  until step 7 of the *next* release. Hotfix re-cuts during the active
  window: branch from `vX.Y.Z`, cherry-pick the fix, bump to `vX.Y.Z.1`,
  squash-merge to `main`, tag, rebase. The retained branch lets a hotfix
  re-cut the release without rebuilding the curation.

## Knock-on effects on subsequent TODOs

The TODO YAML files in `_project/TODO/main/active/` and `_project/TODO/main/planning/` for phases 2 onwards will be amended in-place when each phase becomes the active work, to reflect the version-branch flow. Specifically:

- **Phase 1 (wheel hygiene)** — completed 2026-04-27. Defence-in-depth MANIFEST.in prunes added; wheel + sdist verified clean of maintainer scaffolding.
- **Phase 2 (continuous CI)** — surface widens to: every push to `develop`, every push to `main`, every push to `v*` release branches, every PR targeting any of those.
- **Phase 3 (new release flow)** — Makefile `release` target rewires to the new flow: cut `vX.Y.Z` from `develop` → curate (re-using `workflow.py` / `prepare_release.py` outputs) → squash-merge to `main` → tag → rebase `develop`. The release.yml workflow stays the same shape (triggered by tag push, builds, publishes to PyPI).
- **Phase 4 (final sync + history merge + first release)** — restructures: create `develop` from current public `main`, sync the working-tree into `develop`, `_project/**` filter-merge into `develop` (with date filter dropping pre-2026 commits per Phase 0 D2a), cut `v0.3.0` release branch from `develop`, curate, squash-merge to `main`, tag, rebase `develop` onto `main`.
- **Phase 5 (dev-locus migration + branch protection)** — three rulesets:
  - `main`: squash-merge only, source restricted to `vX.Y.Z` PR sources, status checks required, linear history (post-Phase-4 only).
  - `develop`: squash-merge only, status checks required, linear history.
  - `v*` release branches: minimal protection (short-lived; maintainer-owned). Block force-pushes; allow direct commits during curation.
- **Phase 6 (delete obsolete tooling)** — shrinks substantially. Keep `benchbox/release/workflow.py` and `scripts/prepare_release.py` (repurposed for branch-to-branch curation). Likely delete: `automate_release.py`, `sync_repos.py`, bidirectional `sync.py` helpers, divergence preflight. The Phase 6 TODO will be revised when reached.
- **Phase 7 (docs)** — `docs/operations/release-guide.md` describes the version-branch flow (the seven steps in A4 above).
- **Phase 8 (first post-migration release)** — exercises the full flow end-to-end on `v0.3.1`: cut `v0.3.1` from `develop`, curate, squash-merge to `main`, tag, rebase `develop`, then optionally delete `v0.3.0` branch (option c lifecycle).

## Phase 0 D2a reconfirmation hooks

D2a is reconfirmed after the Phase 0 gitleaks scan and content audit. Three downstream paths:

1. **PROCEED** — gitleaks clean, content acceptable: filter-merge `_project/**` into `develop` as planned.
2. **SCRUB** — secrets or embarrassing content found: scrub via `git filter-repo --replace-text` / `--invert-paths` before the merge.
3. **WORKING-TREE-ONLY** — content risk too high: drop `_project/**` history; sync the working tree only as part of the final curated sync. Loses TODO/DONE archaeology but eliminates content risk.

The Phase 0 TODO records the final D2a choice in this same document.

## Phase 0 audit results (2026-04-27)

Audit completed on 2026-04-27. All seven checks ran against the working tree
of `/Users/joe/Developer/BenchBox` and the `_project/**` git history.

| # | Check | Result |
|---|---|---|
| w1 | Working-tree gitleaks (`gitleaks detect --no-git --source .`) | **122 raw findings, 0 real secrets.** All `generic-api-key` rule matches. 21 unique files: 13 in gitignored paths (`benchmark_runs/databases/*.duckdb`, `docs/_build/.doctrees/*.doctree`, `.ruff_cache/`) — random byte matches in binary build artefacts, never sync'd. 8 tracked files (13 findings total) are documentation/test placeholders: `DATABRICKS_TOKEN=dapi1234567890abcdef`, `private_key_passphrase="key_password"`, TPC SQL column refs (`c2.c_nationkey = s2.s_nationkey`). All confirmed false positives. |
| w2 | `_project/**` history gitleaks (`gitleaks detect --source . --log-opts='--all -- _project/'`) | **1 finding, false positive.** `_project/specs/platforms/snowpark_connect.md` (now at `_project/_archive/specs/platforms/snowpark_connect.md`) line 510 — placeholder code example. 1844 commits scanned; ~23 MB of content. |
| w3 | `_project/` sensitive-content keyword scan | **21 keyword matches, all placeholders/env-vars.** All in `_project/_archive/`, `_project/_trash/`, platform-spec docs, or migration TODOs. Examples: `password="password"`, `DATABEND_PASSWORD=benchbox` (test fixture user/pwd both literal "benchbox"), `password: "${REDSHIFT_PASSWORD}"`. No real credentials. |
| w4 | `_blog/` content review | **5 `drafts/` subdirs, no confidential markers.** No top-level `_blog/drafts/`; drafts live as `_blog/<category>/drafts/` in `benchbox-in-action`, `building-benchbox`, `cloud-cost-controls`, `free-trial-benchmarking`, `platform-deep-dives`, `table-formats`. No `INTERNAL`/`CONFIDENTIAL`/`DO NOT PUBLISH` markers. Acceptable for `develop` (which under amended D4 is the only branch where `_blog/` lives). |
| w5 | `_project/**` commit-message scan | **0 hits** with strict word-boundary regex `\b(wip\|hack\|fixme\|fixup\|stupid\|fuck\|shit)\b`. No embarrassing language. (The original loose pattern from the YAML produced 12 false positives by matching `temp` in "template" and `broken` in legitimate fix descriptions.) |
| w6 | Divergence (`comm -23 public-msgs private-msgs`) | **Empty.** Every commit subject on `public/main` is also represented in `private`'s all-history. No fix-ups applied to public-only. |
| w7 | Large blobs in `_project/**` history | **0 blobs >5 MB.** Clean. |

### Final D2a choice — **PROCEED with date-filtered filter-merge**

Audit clean of real secrets, embarrassing language, large blobs, and
public-only divergence. The `_project/**` filter-merge proceeds as
planned, **with one amendment driven by a separate constraint**: nothing
dated before 2026-01-01 may appear in the public repo (commits or file
dates).

- **Existing public state**: already compliant. All 7 commits on
  `public/main` are dated 2026-02-04 or later; all tags `v0.1.0..v0.2.1`
  are 2026-01-19 or later. No pre-2026 content visible on public today.
- **`_project/**` filter-merge**: as-found, would carry 1923 commits, of
  which **400 (21%) are pre-Jan 1 2026** (earliest: `727a655b3 2025-06-18
  Initial working version`). To honour the constraint, the Phase 4 w5
  filter step adds a commit-callback that drops pre-2026 commits.

  **Phase 4 w5 command (revised)**:
  ```bash
  git filter-repo --path _project/ \
    --commit-callback '
      author_ts = int(commit.author_date.split()[0])
      committer_ts = int(commit.committer_date.split()[0])
      if author_ts < 1767225600 or committer_ts < 1767225600:
          commit.skip()
    ' \
    --force
  ```
  (Unix timestamp `1767225600` = 2026-01-01 00:00:00 UTC.)

- **Surviving commit count** (executed 2026-04-27): **1537 commits**
  dated 2026-01-01 or later landed on public's `develop` branch via the
  filter-merge. The dropped 380 commits were early exploratory work
  (earliest: 2025-06-18) with low residual value.
- **File modification dates on public**: the curated `develop` → `main`
  sync uses `_normalize_timestamps()` from `benchbox/release/workflow.py`
  to set every file's mtime to the release timestamp (current whole
  hour UTC), which is inherently 2026 today. File-system mtimes on the
  `develop` branch itself are set at clone/checkout time and are
  therefore also 2026.

### Optional follow-ups (not blockers; deferred)

1. **`.gitleaksignore`** for the 13 documentation/test placeholders
   (`dapi1234567890abcdef`, `password="password"`, `key_password`, etc.)
   — they will re-trigger any future gitleaks run. Either add a
   `.gitleaksignore` file or refactor the docs to use more obvious
   placeholders like `<your-databricks-token>`.
2. **`_project/_archive/` and `_project/_trash/`** carry through the
   filter-merge. Content is benign (stale planning docs) but the user
   may want to either keep them as historical record or do a follow-up
   cleanup PR. Discuss after Phase 4 lands.

Phase 0 audit complete. Phase 1 (wheel hygiene) is now unblocked.

## Amendment 2026-04-27 — 2-command release flow (A4 + A5 supersession)

The 4-target release flow originally specified by A4 (`bump` →
`changelog-draft` → `release-prepare` → `release-rebase-develop`) is
replaced by a 2-target flow: `make release-cut` and `make
release-finalize`. Two semantic changes accompany the consolidation:

- **A4 step 6 (rebase develop) is removed.** `develop` is intentionally
  NOT modified by `release-finalize`. Dev-only paths (`_project/`,
  `_blog/`, agent configs, dev-tooling root files) live only on
  `develop` by design (per A3); the release squash on `main` does not
  add anything to develop's content surface that isn't already there.
  The original A4 step 6 (`git rebase --onto main vX.Y.Z develop`)
  would have deleted those dev-only paths from `develop` on every
  release.
- **A5 option-c deletion moves from manual to automatic.** The previous
  `vX.Y.Z` branch on origin is auto-deleted by `release-cut` after the
  new branch is pushed (loop sweeps any stale `v*` branches a hotfix
  path may have left behind, not just the highest one).

The 7-step A4 procedure block is preserved as historical record; the
runbook of record is now `docs/operations/release-guide.md`.

## Amendment 2026-04-27 — A3 main-only allowlist extension

The original A3 main-only enumeration omitted several top-level paths
that have always shipped on main but were never explicitly listed.
Discovered while implementing the curation-drift CI guard
(`scripts/check_release_curation.py`); the script enforces that every
top-level tracked path is in either the main-only allowlist or the
release-cut curation list.

- **`main` only** (extension to A3): `docker/`, `quality/`, `setup.cfg`,
  `setup.py`, `tox.ini`, `index.html`.

These are all build/release/UI artefacts that belong on the released
tree. They are therefore NOT in the release-cut curation list. This
amendment is the source of truth for the script; the original A3 row
remains unchanged.

## Amendment 2026-05-01 — codecov config to main-only allowlist

Adding `codecov.yml` (Codecov coverage thresholds and PR-comment
suppression) as a new top-level path. CI workflows (`pr.yml`,
`nightly.yml`, `test.yml`) reference `codecov/codecov-action@v4`, which
loads this config on every coverage upload. The config is needed on
both `develop` and the released `main` tree, so it goes in the
main-only allowlist (not the release-cut curation list).

- **`main` only** (extension to A3): `codecov.yml`.

This amendment extends the 2026-04-27 amendment; both bullets are
authoritative.

## Amendment 2026-05-18 — v0.3.0 release scope curation

The v0.3.0 release intentionally ships the generated `/prompts/` landing
surface under `landing/prompts/`, canonical JoinOrder runtime code and
metadata under `benchbox/core/joinorder/`, and promoted release posts under
`docs/blog/`. It intentionally does not ship the results explorer.

Release branches therefore curate the following develop-only/deferred
surfaces with `git rm` in `make release-cut`:

- `results-explorer/`
- `results-data/`
- `.github/workflows/results-explorer-browser.yml`
- `.github/workflows/seed-corpus.yml`
- `.github/workflows/sync-results-data-to-published.yml`
- `.github/workflows/validate-submission.yml`

The top-level results paths were removed from the 2026-04-27 main-only
extension above because they are not part of the v0.3.0 release tree.
`scripts/check_release_curation.py` now pins these required removals in
addition to the top-level split, so the drift guard fails if a future edit
accidentally reclassifies the results explorer as shipping content.

## Amendment 2026-07-09 — v0.3.1 recovery release; Phase 4 closed, Phase 8 retired

The `v0.3.1` recovery release published successfully (tag `v0.3.1`,
`release.yml` run 29055922350, squash commit `7550c423d` on `main`). A clean
isolated install of `benchbox==0.3.1` imports without pandas, resolving the
`v0.3.0` installability failure. `0.3.0` was neither re-tagged nor re-uploaded;
it remains permanently broken on PyPI and is superseded, not repaired.

Bookkeeping consequences, decided explicitly rather than left implicit:

- **Phase 4 is `Completed`** — its w8 installability gate is closed as
  recovery-complete on the `v0.3.1` evidence.
- **Phase 8 is `Completed` (RETIRED), satisfied by `v0.3.1`.** Phase 8 exists
  to exercise the new flow end-to-end in the canonical single-repo state with
  no fallback; `v0.3.1` did exactly that, with `automate_release.py` already
  deleted (Phase 6) and docs aligned (Phase 7). Its w1-w7 are deliberately
  skipped. A `v0.3.2` cut solely to re-run a passed exercise would be a public
  release with no user-facing content.

### Two release-flow gaps this release exposed

1. **`release-cut` did not align release histories.** *(Closed — folded into
   `release-cut`; see the note below.)* Because the 2026-04-27
   amendment removed A4 step 6 (`rebase develop onto main`), `main` and
   `develop` diverge permanently — `main` carries one squash commit per release
   that `develop` never sees, and the two have unrelated roots since the Phase 4
   filter-merge. A `vX.Y.Z` branch cut cleanly from `develop` is therefore
   *not mergeable* into `main`: GitHub cannot compute a merge ref, so **no CI
   runs at all** and the release PR sits at `CONFLICTING`. The fix, applied by
   hand on `v0.3.1` (and, in hindsight, by every prior aborted cut):

   ```bash
   git merge -s ours --allow-unrelated-histories origin/main \
     -m "Merge main into vX.Y.Z (strategy: ours) to align release histories"
   ```

   `-s ours` preserves the curated release tree byte-for-byte and only records
   `main` as a second parent. `release-finalize`'s squash-merge then collapses
   the branch into a single commit on `main`, so this merge never pollutes
   `main`'s release-only ledger.

   **Now automated.** `release-cut` performs this merge itself, between the
   `Release vX.Y.Z` commit and the push, and guards it by asserting the tree is
   unchanged across the merge (a non-`ours` strategy would drag `main`-only
   content back into the curated tree). Pinned by
   `tests/unit/test_release_infrastructure.py::TestReleaseInfrastructure::test_release_cut_aligns_release_histories_before_pushing`.
   Ordering matters: the merge must follow `generate_changelog_entry.py
   --since-ref origin/main`, which needs `main` to still be a non-ancestor.

2. **`validate-base` bootstrap under-restored its helpers.** The trusted-base
   bootstrap path (taken while `main` lacks `scripts/release_readiness_check.py`)
   restored `_project/scripts/ruleset_review_enforcement.py` from `develop` but
   not its sibling import `auto_merge_soundness_paths`, so the ruleset-drift
   step died with `ModuleNotFoundError`. Prior cuts never reached that step —
   they failed earlier on the non-fast suite — which is why it stayed latent.
   Fixed in `.github/workflows/validate-main-pr.yml` and pinned by
   `tests/unit/test_release_infrastructure.py::TestReleaseInfrastructure::test_validate_main_pr_restores_ruleset_helper_before_drift_check`.

### Operational notes for the next release

- The **emergency override variables were never set.** While `main` lacks
  `scripts/release_readiness_check.py`, `validate-base` short-circuits into the
  trusted-base bootstrap *before* `release_readiness_check.py` runs, so
  `RELEASE_READINESS_OVERRIDE_SHA`/`_REASON` are not consulted and the circular
  `pypi-latest-installability` canary failure does not gate the release. The
  real gates on that path are the inline non-fast suite and the inline ruleset
  drift check (which requires the `RULESET_DRIFT_TOKEN` repo secret). Once
  `v0.3.1` lands the readiness script on `main`, later releases return to the
  canary-consuming path and the override becomes meaningful again.
- Release-branch pushes and `release-finalize`'s tag push trip the local
  pre-commit **pre-push** hook, because curation removes
  `.pre-commit-config.yaml` from the release tree. Use
  `PRE_COMMIT_ALLOW_NO_CONFIG=1`; do not disable hooks wholesale.
- `release-finalize`'s `git push origin v$(VERSION)` is ambiguous once both a
  `vX.Y.Z` branch and tag exist (`src refspec ... matches more than one`). Push
  the tag explicitly: `git push origin refs/tags/vX.Y.Z`.
- `scripts/generate_changelog_entry.py` shells out to a nested `claude` CLI
  (`CLAUDE_TIMEOUT_SECONDS = 120`) to summarize commits. That stalls when
  `release-cut` is driven from inside a Claude Code session; the generated
  section is raw commit subjects anyway and needs hand-curation, so the
  changelog should be curated deliberately rather than accepted as generated.
