# Branch rename runbook: `main` -> `release` (and default -> `develop`)

This is the maintainer runbook for the two-part branching-strategy migration
recorded as `branch-default-switch-to-develop` (Decision A) and
`rename-release-branch-main-to-release` (Decision B). Both are naming
clarity changes with **no behavioral gain**: `main` is already release-only
(`validate-*-pr.yml` rejects any PR whose head is not a `vX.Y.Z` branch,
`release-finalize` fast-forwards + tags it, and its HEAD is always the exact
latest-release commit) and it is also, today, the repository's default
branch — a trap where the most-restricted branch reads as primary. `develop`
becomes the default branch; `release` becomes the accurate name for the
curated release branch.

## Ordered migration

Run these in order. Do not skip ahead — the ordering exists specifically to
avoid a window where release-cut PRs target a branch name that does not yet
exist on GitHub.

1. **Decision A (admin, separate item): switch the default branch to
   `develop`.**
   `gh api -X PATCH repos/joeharris76/BenchBox/ -f default_branch=develop`
   (or the repo Settings UI). Low-risk — GitHub scheduled (`on.schedule`)
   workflows begin running from `develop` instead of `main`; verify the
   `scheduled-workflow-liveness` job in `nightly.yml` stays green and that
   `release-canary.yml` / `phase3-promotion-review.yml` are already present
   on `develop` (they are), so their schedules keep firing without any
   further action. This item is tracked separately
   (`branch-default-switch-to-develop`) and is a prerequisite for step 2
   below, not part of this item's own work units.

2. **Decision B in-repo half (this item, w1-w4): merge the PR that renames
   `main` -> `release` across workflows, `Makefile`, docs/templates, and
   adds this runbook.** This lands on `develop` first, same as any other PR.
   At the moment this PR merges, the actual GitHub branch is still named
   `main` — only the in-repo *references* to it now say `release`. That is
   the expected, documented-safe intermediate state; see "No real gap"
   below for why this is safe to leave briefly inconsistent.

3. **Decision B admin half (w5/w6, maintainer-only, immediately after step 2
   merges — do not leave an open window):**
   a. Rename the branch:
      ```bash
      gh api -X POST repos/joeharris76/BenchBox/branches/main/rename \
        -f new_name=release
      ```
      GitHub automatically redirects old URLs (including `blob/main/...`
      links not pinned to a tag) and retargets any open PRs whose base was
      `main` to `release`.
   b. Recreate the release-only ruleset, targeting the renamed branch:
      - Name: `release-only` (was `main-release-only`).
      - Target: `refs/heads/release` (was `refs/heads/main`).
      - Required status checks: `validate-base`, `release-required-result`
        (unchanged — these are workflow job/context names, not branch
        names, and this PR's w1 already renamed the underlying jobs that
        satisfy them, e.g. `verify-tag-on-main` -> `verify-tag-on-release`).
      - Preserve every other property from the old ruleset: linear history
        required, non-fast-forward, no direct push, deletion blocked, no
        bypass actors.
      - Delete the old `main-release-only` ruleset once the new one is
        confirmed (GitHub does not rename rulesets when the underlying
        branch is renamed — recreation is a separate, explicit step).
   c. Update the ruleset-id reference(s) in
      `docs/operations/repo-admin-settings.md` (the `Branch ruleset —
      release` section's `<release-ruleset-id>` placeholder, and the
      "Re-applying after a transfer or restore" section's guidance to
      "update this file and the `Makefile`/`scripts/` references that
      hard-code it").
   d. Re-run the verification commands below and confirm all three pass.

## No real gap

The interval between step 2 (in-repo rename merges to `develop`) and step 3
(GitHub branch actually renamed) is safe to leave briefly open because:

- The release branch **only receives pushes via `release-cut` /
  `release-finalize`**, both maintainer-run Make targets — there is no
  automated or third-party process that pushes to it directly. As long as
  the maintainer does not run `make release-cut` / `make release-finalize`
  between steps 2 and 3, nothing exercises the renamed-but-not-yet-renamed
  branch reference.
- `develop` itself is unaffected either way — this migration never touches
  `develop`'s own ruleset, required checks, or default-PR flow.
- If `make release-cut` is accidentally run in that window, it fails fast
  and loudly: `gh pr create --base release ...` errors because the
  `release` branch does not exist yet on GitHub. No release is silently
  cut against the wrong base.
- Step 3 is a single maintainer session (rename + ruleset recreate done
  together), so in practice the window is minutes, not days.

## Verified safe / unchanged (do not touch)

These are branch-independent by construction and require no changes as
part of either decision:

- **PyPI trusted publishing**: keyed on repository + workflow filename
  (`release.yml`) + environment (`pypi` / `test-pypi`), never a branch name.
  Renaming `main` -> `release` and changing the default branch do not
  affect the trusted-publisher binding on PyPI's side.
- **GitHub Pages**: the Pages *source* is configured as "GitHub Actions"
  (the `deploy-pages` action), not a branch. The `docs.yml` `deploy` job's
  own trigger condition (`github.ref == 'refs/heads/release'` after w1) is
  a workflow-level gate on when the job runs, independent of the Pages
  source setting itself.
- **README badges**: pin no branch.

## Verification

Run after each stage:

```bash
# After step 2 merges (in-repo half) — no residual main-branch
# trigger/gate references in the touched surface:
grep -rn 'refs/heads/main' .github/workflows
grep -rn -- '--base main' Makefile
# expect: no output (both should show only 'release' now)

grep -n 'base release' Makefile
# expect: release-cut and release-finalize both present

uv run -- python -c "import yaml,glob; [yaml.safe_load(open(f)) for f in glob.glob('.github/workflows/*.yml')]; print('all workflows parse')"

uv run -- python -m pytest tests/unit/test_release_infrastructure.py -n 0 -q
```

```bash
# After step 3 (admin: branch renamed + ruleset recreated):
gh api repos/joeharris76/BenchBox/rulesets --jq '.[] | {name, target}'
# expect: a ruleset targeting refs/heads/release; none targeting refs/heads/main

gh api repos/joeharris76/BenchBox/branches/release --jq '.name'
# expect: "release"; a lookup of .../branches/main now 404s
```

## Rollback

Both steps are reversible independently, most recent first:

- **Undo step 3 (branch rename + ruleset)**: rename back
  (`gh api -X POST repos/joeharris76/BenchBox/branches/release/rename -f
  new_name=main`) and recreate the original `main-release-only` ruleset
  targeting `refs/heads/main` with the same required checks. GitHub's
  redirect/retarget behavior applies symmetrically.
- **Undo step 2 (in-repo rename)**: revert the merge commit on `develop`
  (or open a follow-up PR reversing the `main`<->`release` token swap across
  the same files). Since the actual GitHub branch may already be named
  `release` at this point (step 3 done), reverting step 2 without also
  reverting step 3 would reintroduce `main`-named references pointing at a
  branch that is actually called `release` — revert both together, or
  neither.
- **Undo step 1 (default branch)**: `gh api -X PATCH
  repos/joeharris76/BenchBox/ -f default_branch=main` (or `release`,
  depending on whether step 3 has run) reverts the default-branch switch
  independently of the rename; the two are separate GitHub settings.

## Related items

- `branch-default-switch-to-develop` (Decision A) — separate TODO, must
  complete before this item's step 3.
- `rename-release-branch-main-to-release` (Decision B) — this item; w1-w4
  are the in-repo half (steps above, part 2); w5/w6 are the admin half
  (step 3).
- `_project/decisions/single-repo-migration.md` — the architecture record
  for the two-branch flow this migration renames, not restructures.
- `docs/operations/release-guide.md` and `docs/operations/repo-admin-settings.md`
  — the maintainer runbook and admin-state runbook this migration updates.
