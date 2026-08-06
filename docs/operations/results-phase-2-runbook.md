# Phase 2 Results Operations Runbook

Phase 2 is the PR-based community submission flow for the BenchBox public results
corpus. The product boundary and launch rationale live in
[`docs/development/benchbox-results-platform-strategy.md`](../development/benchbox-results-platform-strategy.md).
This runbook documents the current operating model only: contributor PRs target
`published-results`, CI validates them, maintainers review them, merges trigger the
static explorer rebuild, and no hosted API is involved.

## 1. Submission Lifecycle

### 1.1 Community submission (Phase 2)

1. Contributor runs `benchbox run ...` and `benchbox submit --output ./submission`.
2. Contributor copies the bundle files plus the generated `<result>.manifest.json` into `results-data/bundles/`.
3. Contributor regenerates `results-data/corpus-inventory.json`.
4. Contributor opens a PR against `published-results`.
5. `Validate Submission` checks schema, hash integrity, timing sanity, and inventory drift.
6. Maintainer reviews, requests fixes if needed, and merges.

### 1.2 Maintainer-run additions (sync from develop)

Maintainer-side corpus changes — the `seed-corpus.yml` workflow's on-demand
(`workflow_dispatch`) refresh, ad-hoc UAT integrations like PR #164, validator updates — land on
`develop` first because that is where the project's tooling and tests live.
The
[`sync-results-data-to-published.yml`](../../.github/workflows/sync-results-data-to-published.yml)
workflow watches `develop` for changes under the slim-branch allowlist
paths (`results-data/bundles/`, the corpus docs, the two vendored
validators, plus `corpus-inventory.json`) and opens a **draft** PR against
`published-results` mirroring those changes. The mirror PR never
auto-merges — a maintainer reviews and flips it ready when the develop-side
change is ready to surface on the public corpus branch.

**Publication fixed-point gate.** Before building a mirror branch or opening
a PR, the sync workflow runs the same check as
`tests/unit/scripts/test_corpus_privacy_invariant.py::test_rederived_corpus_publishes_byte_identically_to_what_is_stored`
against the develop content at `GITHUB_SHA` (the bytes about to be mirrored).
If re-anonymization would rewrite any primary bundle, the run fails loudly and
does **not** open a mirror. That keeps `published-results` from receiving a
corpus that Explorer publication would immediately rewrite, and sequences any
in-flight re-derivation automatically: the mirror waits until develop is at
the fixed point, then proceeds unattended. A red sync run with drift still
present is the expected signal while re-derivation is open — not a stuck
manual gate.

If the workflow's heuristics ever miss a path (or a one-off mirror is
needed outside the trigger conditions), trigger it manually via
`workflow_dispatch` from the Actions tab.

#### Why the mirror PR needs its own check, and what still doesn't run there

The mirror PR is opened by `sync-results-data-to-published.yml` using its own
`GITHUB_TOKEN`, so its author is `github-actions[bot]`. GitHub never starts
`pull_request`-triggered workflow runs for events raised by `GITHUB_TOKEN`
(documented recursion prevention) — so `validate-submission.yml`, despite
being wired to fire on exactly this PR's base and paths, never actually runs
on it. #1542 shipped with an empty `statusCheckRollup` for exactly this
reason: not zero failures, zero checks.

The sync workflow now closes that gap itself: before opening or updating the
PR, it runs the same two corpus gates `validate-submission.yml` would have
(bundle validation via `scripts/validate_submission.py`, inventory freshness
via `scripts/generate_corpus_inventory.py --check`) against the exact content
it is about to mirror, and posts the result as a `corpus-mirror/validate-bundles`
commit status on the mirror branch's head SHA. A commit status is a plain
Statuses-API write, not a workflow trigger, so it is unaffected by the
GITHUB_TOKEN recursion rule above and needed no new credential — only a
`statuses: write` permission grant on the token this workflow already holds.

A separate, narrower gap remains and is **not** fixed by the above:
`published-results` carries exactly one workflow file
(`validate-submission.yml`). `pr-base-guard.yml` — the repo-wide check that
every PR gets regardless of base, added precisely so a PR against an
unexpected base branch cannot show zero checks — cannot run against
`published-results` because its file simply does not exist there, whatever
its trigger says. It cannot be added by the sync workflow either:
`GITHUB_TOKEN` cannot push changes under `.github/workflows/` regardless of
the `permissions:` block granted to it (a hard-coded GitHub Actions
restriction — see the "workflow file itself is NOT auto-mirrored" section of
[`adr-published-results-slim-corpus-branch.md`](../development/adr/adr-published-results-slim-corpus-branch.md),
which already documents this exact restriction for `validate-submission.yml`
edits). Porting `pr-base-guard.yml` (or any future repo-wide guard) onto
`published-results` is therefore a **manual** maintainer step, using the same
diff-and-reapply protocol the ADR already prescribes for validator changes:

```bash
git diff origin/develop:.github/workflows/pr-base-guard.yml \
         origin/published-results:.github/workflows/pr-base-guard.yml
```

then apply and push directly to `published-results` (or a PR against it) as
a maintainer with `contents: write` access. In practice this matters less
than it sounds: `pr-base-guard.yml` only protects against a PR whose base is
some *other* branch entirely, and every route onto `published-results`
(contributor submissions, this sync workflow) already targets it directly —
but a future stacked-PR mistake against this branch would still see zero
checks until this manual port happens. Treat it as tracked debt, not a
silent gap.

Two honest limits on what the new status does and does not buy, so nobody
reads more protection into a green badge than is there:

- **It is advisory, not enforcing.** No ruleset targets `published-results` —
  the repo's rulesets target `develop`, `release`, `v*` branches, and tags — so
  a maintainer can still flip a mirror PR ready and merge it with the status
  red. The status makes the verdict *visible*; the maintainer review step the
  draft state exists for is still what enforces it.
- **It is self-attested.** The run that builds the mirror content is the run
  that validates it and posts the verdict, so it catches bad *content*
  (a bundle that fails schema, hash, or privacy validation; a stale inventory)
  but not tampering with the mirror branch after the fact. A later
  `--force-with-lease` push from another run re-posts against the new head SHA,
  so a stale green status cannot ride on top of new bytes — but a direct manual
  push to `auto/results-mirror-*` would leave the last status attached to an
  older SHA, and the PR would show no status for the new one rather than a
  wrong one.

### 1.3 Explorer publish path

The static explorer at `benchbox.dev/results/` is intended to build and
deploy from `main` via [`docs.yml`](../../.github/workflows/docs.yml): the
`build` job runs on pushes and PRs to `main`, and the `deploy` job (Pages)
runs only on pushes to `main`. `published-results` is **not** the explorer's
build source — it is the corpus-archive branch that contributor PRs target
and that mirrors develop's `results-data/`.

> **Current state (pre-launch):** the explorer steps in `docs.yml` are gated
> on `hashFiles('results-explorer/package.json')`, and `release-cut`
> (`Makefile`) currently `git rm`s `results-explorer/` and `results-data/`
> from the release branch, so those paths are **not on `main`** and the
> explorer build/deploy steps are a deliberate no-op there today. The site is
> therefore not yet published from `main`. For the explorer to go live from
> `main`, the develop → main release flow must stop curating
> `results-explorer/`/`results-data/` out of the release branch — a maintainer
> decision tracked separately. Until then, treat `benchbox.dev/results/` as a
> develop-built preview, not a main-deployed site.

## 2. Maintainer Review Checklist

- Accept only complete benchmark runs with plausible metadata and timings.
- Reject bundles that fail CI, omit required schema-v2 fields, or obviously misstate environment details.
- Reject partial cohorts that would mislead the compare view.
- Confirm the bundle path and filenames are coherent with the existing corpus naming.
- Close stale contributor PRs after 14 days without response, with a short thank-you note.

Suggested review reply for missing fixes:

```text
Thanks for the submission. CI found issues we need fixed before merge. Please address the failing checks, rerun the local validation commands from docs/contributing-results.md, and push an update to this PR.
```

## 3. CI Failure Triage

Use the exact validator output in `scripts/validate_submission.py` when replying so the
guidance matches the code.

- `Unsupported schema version`: the submitter exported an old result shape; ask them to rerun with a current BenchBox build.
- `Hash mismatch`: the bundle changed after packaging; ask them to rerun `benchbox submit`.
- `All query timings are 0ms` or negative durations: reject until the benchmark is rerun.
- `Unknown benchmark id` or `Unknown platform name`: verify whether this is a legitimate new surface before merging.
- Inventory drift: ask the contributor to run `uv run -- python scripts/generate_corpus_inventory.py --write` and recommit.

Never bypass red validation checks and merge anyway. If the validator is wrong, fix the
validator in a separate PR first.

## 4. Backfilling `corpus-inventory.json`

When a PR updates bundles but forgets the inventory:

```bash
uv run -- python scripts/generate_corpus_inventory.py --write
git add results-data/corpus-inventory.json
git commit -m "chore: refresh corpus inventory"
```

If you are fixing the contributor branch yourself, explain that in the PR before pushing.

## 4b. Corpus Path Privacy

Every JSON file under `results-data/` must be free of private absolute paths.
`tests/unit/scripts/test_corpus_privacy_invariant.py` scans the whole corpus on
every code CI run, not just the files a PR touched. #1467 cleaned the corpus;
this gate is what stops it regressing. A changed-files scan cannot do that job:
a bundle merged before the scan existed is invisible to it permanently.

The gate is marked `fast`, so it runs inside `code-test`, which
`ci-required-result` gates on. A corpus-only diff still routes to `code-test`;
the same test file pins both facts so the gate cannot become decorative.

To re-migrate after importing legacy bundles:

```bash
uv run -- python _project/scripts/results_explorer_corpus_migrate.py
```

Dry run by default; add `--write` to apply. It reuses the canonical
`AnonymizationManager` and preserves values that are already public hashes, so
re-running it on the current corpus is a verified no-op (207 unchanged). It
writes an audit trail to
`results-data/bundles/path-privacy-migration.manifest.json` recording old/new
hashes and result IDs — never a private value.

Migrating rewrites `result_id` for every changed bundle. The Explorer derives
result IDs from the *published* bytes, so regenerate the inventory afterwards
(§4) and expect detail URLs to move.

## 5. Rolling Back a Bad Merge

Use a fresh branch off the affected target branch. Set `REMOTE` to the repo you are
operating against.

```bash
REMOTE=public
git fetch "$REMOTE" published-results
git switch -c rollback-results "$REMOTE/published-results"
MERGE_SHA="$(git log --merges --oneline -n 1)"
echo "$MERGE_SHA"
git revert -m 1 "${MERGE_SHA%% *}"
git push "$REMOTE" HEAD:published-results
```

Then comment on the reverted PR explaining whether the bundle was broken or merely
misleading, and whether a corrected resubmission is welcome.

## 6. Re-triggering an Explorer Rebuild

If the corpus is correct but the explorer build needs to rerun:

```bash
gh workflow run docs.yml --repo joeharris76/BenchBox
gh run watch --repo joeharris76/BenchBox
```

Use `workflow_dispatch` only after confirming there is no newer push already
rebuilding the site. Note that `workflow_dispatch` runs the `build` job but
**not** the `deploy` job — the Pages deploy is gated on
`github.event_name == 'push' && github.ref == 'refs/heads/release'` — so a manual
run validates the build without publishing. A publish requires a push to
`main` (and, per §1.3, the explorer paths actually being present on `main`).

## 7. Data Locations

- Target branch: `published-results`
- Corpus root: `results-data/`
- Bundles: `results-data/bundles/`
- Inventory: `results-data/corpus-inventory.json`
- Community sidecar: `<result>.manifest.json` (legacy `submission-manifest.json` is still accepted)
- Generated explorer read model: `results-explorer/public/data/`

The explorer pipeline treats sidecar presence as the trust-label contract for community
submissions.

`published-results` is a slim, corpus-only branch by design. The exact allowlist of
paths that may live on it (and the matching exclusion list applied at the slim-down)
is documented in
[`docs/development/adr/adr-published-results-slim-corpus-branch.md`](../development/adr/adr-published-results-slim-corpus-branch.md).
A submission PR that adds files outside the allowlist should be redirected to
`develop` instead.

## 8. Code Locations

| Surface | Path |
| --- | --- |
| Submit CLI | `benchbox/cli/commands/submit.py` |
| Inventory generator | `scripts/generate_corpus_inventory.py` |
| Submission validator | `scripts/validate_submission.py` |
| Validation workflow | `.github/workflows/validate-submission.yml` |
| Explorer pipeline | `_project/scripts/explorer_pipeline/` |
| Contributor guide | `docs/contributing-results.md` |

## 9. Verification Commands

Run these locally before concluding the platform is healthy:

```bash
uv run -- python scripts/validate_submission.py results-data/bundles/
uv run -- python scripts/generate_corpus_inventory.py --check
uv run -- python results-data/validate_corpus.py
uv run -- python -m pytest tests/unit/scripts/test_validate_submission.py tests/unit/scripts/test_generate_corpus_inventory.py -q
cd results-explorer && npm run typecheck && npm run build
```

## 10. Escalation

Escalate when any of the following are true:

- The validator or inventory generator appears wrong rather than the submission.
- The docs workflow rebuild fails after a clean merge.
- A trust-label or visibility bug would publish misleading provenance.
- A rollback would remove more than the intended submission.
- The failure depends on infrastructure or GitHub permissions rather than repo code.

When escalating, link the relevant PR, the failing workflow run, and the exact file or
validator message that triggered the escalation.
