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
| D5 | Merge strategy | (a) Dev PRs → `develop`: squash-merge. (b) Release PRs `develop` → `main`: curated overwrite (one commit per release). (c) Phase 4 one-time `_project/**` filter-merge → `develop`: regular merge commit (squashing defeats the purpose). | Keeps `main` lineage release-only; preserves filter-merge value; standard squash for routine dev. |
| D6 | Continuous CI surface | Every push to `develop`, every push to `main`, every PR targeting either branch. Same checks as today's `automate_release.py:run_ci_checks` (ruff check, ruff format --check, ty check, fast pytest with coverage gate). | Removes CI gating from the release path. Both branches stay green at all times. |
| D7 | Reproducibility | Keep `SOURCE_DATE_EPOCH=$(git log -1 --format=%ct ${tag})` in `release.yml`. Drop the rest of the timestamp-normalization machinery. | The wheel was the only consumer that mattered; the rest was unverified. |
| D8 | Disposition of `/Users/joe/Developer/BenchBox` (private clone) after Phase 5 | Rename to `BenchBox.retired-YYYYMMDD/`. Future development happens in `~/Developer/benchbox-public` on the `develop` branch (not `main`). Delete after 60-day soak. | Renaming prevents shell muscle-memory mistakes; the soak preserves an emergency reference. |

## Architectural facts (apply across all phases)

- **A1 — Branch name**: long-lived dev branch is `develop`.
- **A2 — Default branch on GitHub**: stays `main`, so the canonical URL shows the release tree.
- **A3 — Tree split**:
  - **`main` only**: `benchbox/`, `tests/`, `docs/`, `examples/`, `_binaries/`, `_sources/`, `_chart_data/`, release-related contents of `scripts/`, `pyproject.toml`, `MANIFEST.in`, `Makefile`, `README.md`, `CHANGELOG.md`, `LICENSE`, `COPYRIGHT.md`, `DISCLAIMER.md`, `CONTRIBUTING.md`, `pytest.ini`, `pytest-ci.ini`, `uv.lock`, `.gitignore`, `.codespell-ignore.txt`, `landing/`, `.github/` (workflows + templates).
  - **`develop` only** (in addition to everything on `main`): `_project/`, `_blog/`, `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.claude/`, `.codex/`, `.gemini/`, `.pre-commit-config.yaml`, `_benchbox_pytest_xdist_safety.py`, `todo.config.yaml`, `skill-sync.yaml`, `skill-sync.lock`, `.coveragerc_core`, `.dockerignore`, `.env.example`, `.mcp.json`, dev-only scripts.
- **A4 — Release flow**: `develop` contents → curated overwrite onto `main` (single commit per release) → tag `main` → `release.yml` publishes to PyPI. The curated-sync engine survives the migration repurposed for branch-to-branch use.

## Knock-on effects on subsequent TODOs

- **Phase 1 (wheel hygiene)** — defence-in-depth, not the primary barrier: `main`'s tree no longer carries `_project/`/`_blog/`/dev tooling at all.
- **Phase 4 (final sync + history merge + first release)** — restructures: create `develop` from current public `main`, sync the working-tree into `develop`, `_project/**` filter-merge into `develop`, cut the release `develop` → curated → `main`, tag `main`.
- **Phase 5 (dev-locus migration + branch protection)** — separate rulesets per branch: strict release-only on `main`, squash-merge on `develop`. Linear-history rule on `main` only; `develop` retains its filter-merge commit.
- **Phase 6 (delete obsolete tooling)** — shrinks substantially. Keep `benchbox/release/workflow.py` and `scripts/prepare_release.py` (repurposed for `develop` → `main`). Likely delete: `automate_release.py`, `sync_repos.py`, bidirectional `sync.py` helpers, divergence preflight. The Phase 6 TODO will be revised when reached.
- **Phase 7 (docs)** — describes the two-branch model and the release-PR flow.

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
      if author_ts < 1735689600 or committer_ts < 1735689600:
          commit.skip()
    ' \
    --force
  ```
  (Unix timestamp `1735689600` = 2026-01-01 00:00:00 UTC.)

- **Surviving commit count**: 1523 commits dated 2026-01-01 or later.
  This preserves the great majority of the decision archaeology the
  filter-merge was designed to carry forward; the dropped 400 are early
  exploratory commits with low residual value.
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
