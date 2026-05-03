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

Maintainer-side corpus changes — the `seed-corpus.yml` workflow's quarterly
refresh, ad-hoc UAT integrations like PR #164, validator updates — land on
`develop` first because that is where the project's tooling and tests live.
The
[`sync-results-data-to-published.yml`](../../.github/workflows/sync-results-data-to-published.yml)
workflow watches `develop` for changes under the slim-branch allowlist
paths (`results-data/bundles/`, the corpus docs, the two vendored
validators, plus `corpus-inventory.json`) and opens a **draft** PR against
`published-results` mirroring those changes. The mirror PR never
auto-merges — a maintainer reviews and flips it ready when the develop-side
change is ready to surface on the public corpus branch.

If the workflow's heuristics ever miss a path (or a one-off mirror is
needed outside the trigger conditions), trigger it manually via
`workflow_dispatch` from the Actions tab.

### 1.3 Explorer publish path

The static explorer at `benchbox.dev/results/` is built from `main` via
[`docs.yml`](../../.github/workflows/docs.yml) on every push and pull
request to that branch. `published-results` is **not** the explorer's
build source — it is the corpus-archive branch that contributor PRs
target and that mirrors develop's `results-data/`. The explorer
publishes from `main`'s view of `results-data/`, which is what eventually
reaches `main` via the develop → main release flow.

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

Use `workflow_dispatch` only after confirming there is no newer push already rebuilding the site.

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
| Explorer pipeline | `benchbox/core/explorer_pipeline/` |
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
