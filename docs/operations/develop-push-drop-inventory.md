<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Develop push-drop coverage inventory

```{tags} contributor, operations, ci
```

Companion to [`develop-post-merge-gaps.md`](develop-post-merge-gaps.md).
That doc explains the **class** (GitHub can drop `push` delivery for consecutive
develop merges) and the **backstop already installed for
`develop-post-merge.yml`** (hourly slim schedule + daily gap detector).

This inventory answers the next question: **which other workflows share the
same silent push-drop risk**, and for each, is the residual risk accepted or
does it still need a follow-up?

## Inventory method

1. Enumerate every workflow under `.github/workflows/` whose `on.push` can fire
   for a push that updates `refs/heads/develop` — either an explicit
   `branches: [develop]` (or a list containing `develop`), or a bare `push:`
   with no branch filter (all branches, including develop).
2. Record whether `on.schedule` and `on.workflow_dispatch` are present.
3. Classify **role**:
   - **Safety-critical** — failure or silence can leave develop tip ungated,
     public corpus stale, merge hygiene broken, or a required integrity signal
     missing.
   - **Advisory / metrics** — observability, hygiene, or secondary signals
     that do not alone bound develop tip or public publication safety.
4. For each safety-critical row **without** a schedule: either document
   **accepted risk** (with the compensating control) or mark **follow-up
   needed**. Prefer documentation over adding expensive hourly full suites.

Snapshot date: **2026-08-15** (workflow tree on `develop` at inventory time).
Re-run the method when adding a new develop-push workflow.

## Inventory table

| Workflow | Push scope | Schedule | Dispatch | Role | Push-drop residual | Disposition |
| --- | --- | --- | --- | --- | --- | --- |
| `develop-post-merge.yml` | `develop`, all paths | hourly `17 * * * *` (slim gates only) | yes | Safety-critical — lint / fast-test / explorer-tokens / medium-test + mutation jobs | Tip re-gated ≤~1h via schedule; per-SHA gaps instrumented daily | **Covered** — see [`develop-post-merge-gaps.md`](develop-post-merge-gaps.md) |
| `orphaned-commit-detector.yml` | bare `push:` (every branch, including develop) | daily `0 7 * * *` | yes | Safety-critical — stranded post-merge commits never reach develop | Schedule is the true backstop (push alone is structurally too early for the race); daily bounds detection | **Covered** — schedule primary; push is secondary/early signal |
| `submission-validator-drift-check.yml` | `develop` + validator path filter | weekly Mon `0 6 * * 1` | yes | Safety-critical integrity — develop vs `published-results` validator copy | Weekly schedule + dispatch bound drift even if path-matched push is dropped | **Covered** — schedule present; path filter already limits push volume |
| `sync-results-data-to-published.yml` | `develop` + `results-data/**` (and related validator paths) | **none** | yes | Safety-critical — only automated mirror of develop corpus → `published-results` | Dropped path-matched push leaves public corpus stale until human recovery | **Accepted risk** — daily `corpus-drift-check.yml` canary detects develop-ahead drift and recommends `gh workflow run sync-results-data-to-published.yml`; workflow retains write-heavy mirror on push/dispatch only (no schedule mutation of public branch) |
| `results-explorer-browser.yml` | `release` + `develop` + explorer/`results-data` path filter | **none** | yes | Mixed — required PR gate (`Results Explorer browser gate`); develop push is post-merge tip re-build for path-matched merges | Dropped develop push can leave tip without a post-merge browser rebuild until the next matching push or dispatch | **Accepted risk** — pre-merge required check on every PR into develop is the primary safety property; develop push is additive tip verification; suite is expensive (Chromium full + smoke browsers) so no hourly schedule; recover with `gh workflow run results-explorer-browser.yml --ref develop` |
| `docs.yml` | `develop`, all paths | **none** | yes | Mixed — assembles the Pages-shaped site and produces the SHA-bound public-site visual baseline | A dropped push delays baseline refresh; exact-base PR comparison fails closed once any baseline exists | **Accepted risk** — the develop PR visual job remains the review gate; the protected push is an additive baseline producer; recover with `gh workflow run docs.yml --ref develop` |
| `publication-lane-explorer.yml` | `release` + `develop` + `results-explorer/**`/`scripts/publication/**` path filter | **none** | yes | Advisory — builds/typechecks the Explorer SPA, runs unit and contract tests, and validates the compatibility manifest; lane is **not** a required status check and does not block merges (primary required gate remains `Results Explorer browser gate`) | Dropped develop push delays tip re-verification of the Explorer build and manifest until the next matching push or dispatch; job holds no deploy or write credentials (`permissions: contents: read` only; output is a CI artifact upload, not a publish step) | **Accepted risk** — lane is advisory; pre-merge validation does not gate merges; develop push is additive tip verification with no elevated permissions or external publish surface; recover with `gh workflow run publication-lane-explorer.yml --ref develop` |

### Explicit non-entries (push, but not develop)

These fire on `push` but **not** for develop tip, so they are out of this
inventory's risk class:

| Workflow | Why excluded |
| --- | --- |
| `docs.yml` | Pages deployment occurs only on `release`; the `develop` push is baseline production and is included above |
| `lint.yml` / `test.yml` | `push.branches: [release]` only |
| `release.yml` | tag push `v*` only |

### Related scheduled canaries (no develop push)

Not push-drop *subjects*, but they **mitigate** the class for other workflows:

| Workflow | Cadence | Role relative to push-drop |
| --- | --- | --- |
| `develop-post-merge-gap-detector.yml` | daily `47 7 * * *` | Instruments missing `develop-post-merge` runs for recent develop SHAs (read-only) |
| `corpus-drift-check.yml` | daily `37 6 * * *` | Detects develop-ahead / content-changed corpus drift when the mirror push path was silent (incident class of 2026-08-03) |

## Classification notes

### Safety-critical without schedule

Only two develop-push workflows lack a schedule:

1. **`sync-results-data-to-published.yml`** — The 2026-08-03 incident was
   exactly this failure mode: three consecutive develop merges got no push
   delivery, the mirror never opened, and `published-results` stayed stale
   with private path leaks until a human noticed. The deliberate design
   response was **not** to put the write-capable mirror on a cron (mutation of
   a public branch from schedule is a higher blast radius). Instead
   `corpus-drift-check.yml` is schedule-only, read-only, fails loud on
   develop-ahead content changes, and points maintainers at a one-shot
   `workflow_dispatch` of the mirror. That is an accepted residual risk with a
   bounded detection window (≤ ~1 day), not an untracked gap.

2. **`results-explorer-browser.yml`** — Develop inclusion exists so a
   squash-merge combination no PR exercised still rebuilds the browser lane
   on tip (see workflow header comment and
   [`browser-ci.md`](browser-ci.md)). The **merge gate** is the ruleset
   required check on PRs; that does not depend on develop push delivery.
   Adding an hourly (or even daily) full browser suite would be the expensive
   medium-tier pattern this inventory deliberately rejects for cost. Residual
   tip drift after a dropped path-matched push is accepted; recovery is
   dispatch or the next explorer-touching PR. No follow-up TODO filed: if a
   future tip-only browser regression becomes a real incident class, prefer a
   **cheap liveness** signal (did a push event create a run for path-matching
   SHAs?) over re-running Playwright on a schedule.

### Covered rows (schedule present)

- **`develop-post-merge.yml`** — model solution for the class: additive slim
  schedule, mutation/medium excluded from schedule, separate gap detector.
  Do not copy the full medium suite onto hourly schedules elsewhere.
- **`orphaned-commit-detector.yml`** — daily schedule is required for the
  stranding race; bare push covers all branches cheaply (~1 min, read-only).
- **`submission-validator-drift-check.yml`** — weekly is enough for a rarely
  changing dual-branch validator sync; path-filtered push is an early signal.

## Cost and policy constraints (standing)

When extending this inventory or adding backstops:

| Do | Do not |
| --- | --- |
| Prefer schedule + `workflow_dispatch` as additive coverage | Replace the `push` trigger |
| Keep schedule paths slim / read-only when possible | Add ~24× daily full medium or full browser suites on tip |
| Keep write/mutation jobs push + dispatch only | Give scheduled jobs new permission classes without review |
| Document accepted risk with the compensating canary | Paper over drops with `pull_request` / `workflow_run` spam |

## Verification (local, offline)

Confirm this inventory still names the primary covered workflow and at least
one other develop-push subject:

```bash
test -f docs/operations/develop-push-drop-inventory.md
rg -q "develop-post-merge" docs/operations/develop-push-drop-inventory.md
rg -q "sync-results-data-to-published|results-explorer-browser|orphaned-commit-detector" \
  docs/operations/develop-push-drop-inventory.md
rg -q "push-drop|schedule" docs/operations/develop-post-merge-gaps.md
```

Re-enumerate develop-push workflows (must match the table's subject set):

```bash
python3 - <<'PY'
from pathlib import Path
import yaml

subjects = []
for path in sorted(Path(".github/workflows").glob("*.yml")):
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    on = doc.get(True) or doc.get("on")
    if not isinstance(on, dict) or "push" not in on:
        continue
    push = on["push"]
    hits = False
    if push is None:
        hits = True
    elif isinstance(push, dict):
        if "tags" in push and "branches" not in push:
            hits = False
        else:
            branches = push.get("branches")
            if branches is None and "branches-ignore" not in push:
                hits = "tags" not in push
            else:
                hits = branches is not None and "develop" in list(branches)
    if hits:
        sched = [e.get("cron") for e in (on.get("schedule") or [])]
        subjects.append((path.name, sched or None))
for name, sched in subjects:
    print(f"{name}\tschedule={sched}")
PY
```

Expected subject set (names only):
`develop-post-merge.yml`, `docs.yml`, `orphaned-commit-detector.yml`,
`publication-lane-explorer.yml`, `results-explorer-browser.yml`,
`submission-validator-drift-check.yml`, `sync-results-data-to-published.yml`.

## Manual recovery cheatsheet

| If this is silent / red after a develop burst | Recover |
| --- | --- |
| Post-merge gates | `gh workflow run develop-post-merge.yml --ref develop` |
| Gap class instrumentation | `gh workflow run develop-post-merge-gap-detector.yml --ref develop` |
| Corpus mirror lag | `gh workflow run corpus-drift-check.yml` then, if develop-ahead, `gh workflow run sync-results-data-to-published.yml --ref develop` |
| Browser tip rebuild | `gh workflow run results-explorer-browser.yml --ref develop` |
| Explorer publication lane artifact | `gh workflow run publication-lane-explorer.yml --ref develop` |
| Orphan scan | `gh workflow run orphaned-commit-detector.yml --ref develop` |
| Validator drift | `gh workflow run submission-validator-drift-check.yml --ref develop` |
