# Results Explorer - browser testing

**Audience:** Maintainers making changes to `results-explorer/` and release
drivers who need to know what browser coverage exists and what still must be
checked by hand.

This note is the operational counterpart to
[`browser-test-architecture.md`](browser-test-architecture.md). The architecture
note records *why* the suite is shaped the way it is; this note records *what
to run, when to run it, and what to do when it fails*.

## What's covered by automation

The Playwright suite under `results-explorer/e2e/` runs against the built
explorer (`dist/`) served via the static test server at
`results-explorer/scripts/serve-browser-tests.mjs`. Fixtures are generated
per run into `results-explorer/test-fixtures/.generated/` - the curated
public corpus is never modified.

Routes and behaviours with at least one browser-functional test:

| Route / surface | Happy path | Failure path |
|-----------------|------------|--------------|
| Home            | ✅          | -            |
| BenchmarkIndex  | ✅          | -            |
| PlatformIndex   | ✅          | -            |
| ResultDetail    | ✅          | ✅ (unreachable `results.duckdb`, sidecar fetch failure, unknown id) |
| Compare         | ✅ (deep link, share URL, sticky-bar flow) | ✅ (benchmark mismatch, scale mismatch, unknown id) |
| Query workbench | ✅ (sort, column toggle, starter query, CSV + JSON download) | ✅ (read-only write surfaces error) |
| NotFound        | ✅ (unknown `/results/...` path renders the 404 card) | - |
| DuckDB-WASM attach | ✅ (cold load, `waitForDataLoaded`) | ✅ (RG-2 range-read capability via test server) |

## Running the suite locally

Prerequisites: a Python toolchain with `uv`, Node 20+, and the explorer's
dependencies installed.

```bash
cd results-explorer
npm ci
npm run test:e2e:install       # one-time: installs Chromium/Firefox/WebKit
npm run test:e2e:chromium      # deterministic local/CI entrypoint
npm run test:e2e:full          # local full-matrix convenience entrypoint
```

On a clean machine, `npm run test:e2e:chromium:setup` wraps the one-time
browser install plus the same deterministic Chromium run.

Each browser script regenerates the fixture corpus and rebuilds `dist/`
before Playwright starts the static server, so the command stays aligned
with the shipped harness contract. `npm run test:e2e:full` is the
one-command local convenience path; CI stays split into per-browser jobs
so Chromium can block independently while Firefox/WebKit remain
non-blocking `@smoke`.

Cross-browser smoke passes:

```bash
npm run test:e2e:firefox
npm run test:e2e:webkit
```

Failure artifacts (traces, screenshots, video, HTML report) land under
`results-explorer/test-results/` and `results-explorer/playwright-report/`
and are both gitignored.

## Public-site visual baseline policy

The full public-site visual suite is broader than the Explorer's current
functional gate. Its baseline policy is recorded in
`_project/audits/public-site-visual-baseline-policy-2026-08-15.md`:
raw screenshots stay out of Git, protected `develop` produces SHA-bound
baseline artifacts, and pull requests compare against the exact base-SHA
artifact. Missing or unverifiable baselines fail closed; a PR diagnostic
artifact is never promoted directly to a baseline. The capture harness at `results-explorer/e2e/captures/public-site-pages.spec.ts`
and Pages-shaped server are reusable building blocks. `.github/workflows/docs.yml`
uploads the protected baseline from `develop` and retrieves the exact
base-SHA artifact for pull requests and merge groups. A changed public-site
tree cannot pass without that comparison. `Public-site visual acceptance`
reports on every develop PR and merge group; it skips the build only when
the former documentation input paths are unaffected.

A merge group that passes its comparison also uploads a candidate baseline for
its own `merge_group.head_sha`. The next queue group uses that head as its base,
so the candidate is the capture of the exact tree that group merges onto. The
download script accepts a candidate only from a `merge_group` Documentation run
on this repository's `gh-readonly-queue/develop/*` branch at that SHA, and it
prefers a protected `develop` artifact when both exist. Merge groups capture
their own tree first, then wait up to 30 minutes for the exact-base artifact
before failing closed. Pull requests keep a short retry.

If a protected `develop` push was dropped or its baseline expired, dispatch
Documentation on `develop` with `baseline_source_sha` set to the exact base
SHA shown by the failing PR or merge group:

```bash
gh workflow run docs.yml --ref develop -f baseline_source_sha=<full-protected-develop-base-sha>
```

The dispatch validates that the SHA is an ancestor of protected `develop`,
checks out that exact tree, and uploads a SHA-named artifact. The downloader
verifies the protected run and manifest source SHA. Wait for its visual job to
finish, then rerun the failed workflow. A PR diagnostic artifact cannot serve
as recovery input.

An intentional visual change or route/viewport addition needs explicit
maintainer acceptance, recorded **before the PR is enqueued**. Approve the
change by its content and its pull request, not by a commit SHA:

1. Open the PR's failing `Public-site visual regression` run. Its log and the
   failure message print `approval entry: <pull request number>:<digest>`.
   Download the `public-site-visual-diagnostics-*` artifact and review every
   changed or new capture at every viewport.
2. Add that entry to the repository variable `APPROVED_VISUAL_CHANGE_DIGESTS`
   (several entries are separated by spaces or commas, so reviewed PRs do not
   compete for one slot) and set `VISUAL_CHANGE_APPROVAL_REASON` to a nonempty
   review note.
3. Rerun the failed PR workflow, then enqueue the PR.

The merge group recomputes the digest from its own captures. It lists the pull
requests the group contains from the commits the group adds on top of its base
(each squash commit ends with the `(#<number>)` GitHub appends), and accepts the
change only when `<number>:<digest>` is a recorded entry for one of them. The
queue can compose several PRs into one group (`max_entries_to_merge`), and the
queue branch name carries only the last one, so the branch name is not used. The
digest covers each changed
capture as baseline digest to new digest, plus each new capture, so it matches
only the exact change that was reviewed against the exact baseline it was
reviewed against. It stops matching, and the group fails closed, when the group
renders a reviewed capture differently, when another change appears, or when the
base now renders the capture differently. In that case review the new
diagnostics and record the new entry. A digest never accepts a capture missing
from the current matrix.

A group's digest covers the whole group's change, so a group in which two or more
PRs each change what renders matches no single PR's entry and fails closed; it is
never approved on part of its change. Let such PRs land one at a time: dequeue one
and enqueue it again after the other merges. If the list of PRs cannot be read in
full (a commit without a PR number, a truncated or failed comparison), no PR is
named and no digest approval applies, though the comparison itself still runs.

The member list comes from the GitHub compare API and is retried a few times
on a network failure, a rate limit (an HTTP 429, or a 403 carrying rate-limit
headers or a "secondary rate limit" message) or a 5xx server error, but never on
another client error such as a plain 403 or 404, so one transient blip does not
eject an approved group. A rate limit that says how long to wait (`retry-after`, or
the reset time of a spent limit) is waited out up to 60 seconds; a longer wait fails
at once instead of holding the runner. It
relies on the queue's merge method being `SQUASH`, which makes GitHub write each
commit's trailing `(#<number>)` itself; `scripts/ruleset_drift_check.py` pins that
method, and a rebase or merge-commit queue would let an author set the subject.

A limit of the entry format: in a composed group, an entry for one member also
covers an identical change introduced by another member of the same group, because
the digest cannot say which PR produced the pixels. Withdraw an entry when the PR it
names changes or drops its visual change, so a stale entry cannot cover another
PR's change. The failure message prints every candidate entry for a group; record the
one for the pull request that introduces the change.

The code that decides whether a visual change passes (`publicSiteVisual.ts`,
`public-site-pages.spec.ts` and the two approval-member scripts) is in
`.github/soundness-paths.txt`, so a PR that edits it needs an external soundness
review and a manual enqueue; a PR author can otherwise rewrite the check in the same
PR that relies on it.

Because the entry names the pull request, it cannot approve the same pixels in
another PR, for example one that reapplies a reverted change. It does stay valid
for its own PR: closing and reopening the PR, or force-pushing it, keeps the
approval for any head that produces exactly the reviewed change, and a changed
rendering stops matching. To withdraw an approval, remove its entry; checks that
already finished are not affected. Once a PR has merged, its entry cannot
authorize any later PR or new queue entry (a rerun of that PR's original workflow
run could still match it), so merged entries can be removed whenever you tidy the
variable.
Digest approval is not available while the baseline still uses the legacy
capture profile (the one-time landing migration leaves the landing captures out
of the comparison, so a digest would not cover them); use the exact-head
approval below for that case.

Why not approve a head SHA for the queue: a merge group's `head_sha` is a
synthetic commit that does not exist until the group forms, and a group whose
required check fails is removed from the queue within minutes. By the time a
maintainer can read the group's diagnostics and set `APPROVED_MERGE_GROUP_SHA`,
the group is usually gone, and a rerun cannot put it back. The PR-level exact-head approval
(`APPROVED_HEAD_SHA` and `APPROVAL_REASON`, which must equal the PR's current
head SHA) still works for the `pull_request` check but does not carry into the
queue. The merge-group variables (`APPROVED_MERGE_GROUP_SHA`,
`MERGE_GROUP_APPROVAL_REASON`) remain only for a group that is still running
when its diagnostics are reviewed; do not rely on them for queued PRs.

A group stacked behind a leader that changed the site compares against the
leader's candidate baseline, which the lookup accepts from the CI workflow's
merge-queue run (see the follower baseline policy in
`docs/operations/merge-queue-governance.md`), so an approved PR can also be a
follower. A leader that is itself removed from the queue rebuilds its followers
on a new base, and an approval stops matching if that base renders a reviewed
capture differently.

This approval does not replace a baseline. The protected `develop` push or its
validated `workflow_dispatch` run uploads the SHA-bound baseline after the
reviewed PR merges. An approved merge group also uploads a candidate for its own
head, which only the queue group stacked on that exact head consumes. PR
diagnostic artifacts remain short-lived and non-promotable.

## What CI gates

The `explorer-e2e` job in [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)
(Chromium full suite, blocking) runs on **pull requests** and **merge groups**
when the change touches the explorer unit (with the `explorer` unit result
always reporting; the job is skipped when no relevant files change).

- **Blocking:** `chromium` job - full suite must pass.
- **Non-blocking:** `firefox-smoke` and `webkit-smoke` jobs - `@smoke`-tagged
  subset only, `continue-on-error: true`. These graduate to blocking once the
  flake data collected during w9 of
  `implement-results-explorer-browser-functional-tests` supports it.

All three jobs upload Playwright reports on failure with a 3-day retention
so maintainers can download a full trace from the PR checks page. The CI
jobs call the same shared browser scripts that maintainers run locally,
rather than re-encoding fixture/build/test sequencing in the workflow.

## Manual release check

Automation does not replace the short cross-browser pass a maintainer should
run before shipping a meaningful explorer change. "Meaningful" means any PR
that touches routing, `src/db.ts`, a page component, or the pipeline that
produces `results.duckdb`.

Check the following in Chrome, Firefox, and Safari - one pass each, not a
full regression run:

1. **Home** - header, counts, recent-results table render; deep link into a
   benchmark index from the browse-by-benchmark card works.
2. **BenchmarkIndex** - the SF filter updates the URL; each platform row
   links to a ResultDetail.
3. **ResultDetail** - run header, badges, and timings table render; "Compare
   this result" deep-links into Compare.
4. **Compare** - two-platform compare renders side-by-side cards; Share URL
   button copies the current URL; hard-block error renders cleanly for a
   mismatched cohort.
5. **Query** - schema-driven table renders; a starter query populates the
   SQL textarea; Download CSV and Download JSON both emit a file.
6. **NotFound** - an unknown `/results/...` path renders the 404 card and
   the "Back to Results" recovery link.

Focus on layout, font rendering, scroll behaviour, and clipboard/download
permissions - the parts that Playwright covers functionally but cannot
judge visually.

## When a CI run fails

1. Open the failed job, download the `playwright-report-*` artifact, and
   open `index.html` in a browser. The trace viewer is the fastest path to
   understanding the failure.
2. If the failure is browser-specific and reproduces locally, keep the
   browser-specific fix scoped to that browser.
3. If the failure does not reproduce locally, capture it as a flaky-test
   TODO rather than re-running the PR until it passes. See w9 of the parent
   TODO for the flake-triage pattern.

## Adding new tests

- Put happy paths under `results-explorer/e2e/routes/` and tag the primary
  spec per route with `@smoke`.
- Put failure paths under `results-explorer/e2e/failures/`. Assertions must
  target user-visible error states (a visible heading or message), not just
  thrown exceptions or console output.
- Put server/runtime contract checks that are not user failure paths
  under `results-explorer/e2e/capability/` (e.g. the RG-2 range-read
  gate in `capability/range-read-budget.spec.ts`).
- If a test depends on fixture data that does not yet exist, add a variant
  to `results-explorer/scripts/generate-browser-fixtures.mjs` - do not
  mutate the curated public corpus.
- If a test needs failure injection, prefer Playwright's `page.route()`,
  `context.setOffline`, permission grants, and download events. Do not
  introduce a production-code test seam.
