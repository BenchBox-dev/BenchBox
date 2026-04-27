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
