<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Self-hosted oracle review (shadow mode)

```{tags} contributor, operations, ci
```

`.github/workflows/oracle-review-shadow.yml` reviews soundness-path pull
requests with agent CLIs and posts a non-required `oracle-review-shadow` status
through the owner's GitHub App. The required `oracle-review` check is
unchanged. The policy lives in `.github/oracle-reviewers.yml`; the decision
record is `_project/decisions/oracle-review-v2-shadow-2026-10-05.md`.

## Setup

1. Create a GitHub App owned by the repository owner with **Commit statuses:
   write** and **Pull requests: write**, and install it on this repository
   only.
2. Create the `oracle` environment and limit its deployment branches to
   `develop`. Create it before the workflow first runs: GitHub creates a
   missing environment with no protection rules.
3. Add these environment secrets to `oracle`:
   - `ORACLE_APP_ID` and `ORACLE_APP_PRIVATE_KEY`, used only by the `post`
     job;
   - `CLAUDE_CODE_OAUTH_TOKEN`, from `claude setup-token`, used only by the
     claude jobs;
   - `OPENAI_API_KEY`, used only by the codex jobs through
     `codex login --with-api-key`;
   - `META_API_KEY`, used only by the muse jobs. muse is installed unpinned from
     `https://dev.meta.ai/install.sh`, so a compromised download would run with
     this key; the owner accepted that risk on 2026-10-05.

   agy is disabled and has no job, so it needs no secret yet.
4. Remove `CLAUDE_CODE_OAUTH_TOKEN` from the repository secrets, because
   same-repository pull request workflows can read those.

Without the App secrets, the `post` job logs the result and succeeds.

## How a run works

1. `plan` holds no secret. It resolves the pull request and its head through
   the API, refuses closed, draft and non-`develop` pull requests, classifies
   the change, applies the rerun rules and writes a 0600 brief. A fork's
   soundness change gets a pending `fork: owner review` status and never
   reaches a reviewer job. A change with no soundness path gets `success`.
2. `select-N` picks the next reviewer from the tier's order, skipping the
   author's family, disabled reviewers, quota-exhausted pools and, when the
   diff exceeds the brief cap, soft read-only reviewers.
3. `attempt-N-<harness>` runs that reviewer on a detached, credential-free
   checkout of the head. It never runs pull request code. The result is an
   artifact with the run ID, head SHA, reviewer and either a validated verdict
   or an absence.
4. `post` re-validates every artifact from this run, replays the selection,
   and posts the status and one pull request review on the head commit. Each
   finding on a diff line becomes its own review thread; the review body
   holds the summary and any finding outside the diff. A run with no verdict,
   such as one where every reviewer was absent, still posts a review whose
   body explains the pending result, so the latest review always reflects the
   latest run.

`plan` also limits spend to code that changed. The retry state records the
blob SHA of each changed file at the last success or failure, except prose
files (`.md`, `.mdx`, `.rst`, `.txt`) outside soundness paths, with the basis
of that result: the merge base of the head with `develop`, the tier, its
blocking severities and reviewer settings, the excluded author families, and a
hash of the policy file, brief template, verdict schema and reviewer code. When the basis is unchanged and the new
head has exactly those files at those SHAs, the run posts the recorded result
to the new head without running a reviewer, so a push that changes only prose
costs nothing. When the last result was a success below the very-high tier and some
of those files changed, the brief diffs only the changed files, lists the
others and any changed prose separately, and asks the reviewer to check the
effect on them. A file renamed between code and prose counts as code. Every other case gets a full
review: after a failure, because a scoped review cannot re-check findings in
files it does not read; at the very-high tier; and after a basis change, a
file leaving the diff, a diff that cannot be split by file, or a missing state.

Before posting, `post` drops any finding that matches an open review thread
from this App, by file and normalized title, unless the new finding is more
severe than the open thread. Each new thread carries a hidden `oracle-finding`
marker with that fingerprint. A dropped finding still counts toward this run's
result and is listed in the review body.

A blocking finding fails the review even when its line is outside the diff.
Such a finding cannot become a line comment, so it is listed under "Findings
outside the diff" with a note that it still fails the review. Ignoring it
would let a reviewer's report of a real defect pass because it cited an
unchanged line.

Reviewers run one at a time, so a blocking verdict stops the run and an absent
reviewer hands over to the next.

## Commands

- `/oracle-review` at the start of a top-level pull request comment, from an
  owner, member or collaborator, reruns the review on the current head. A reply
  on a review thread or a line comment does not trigger it, because those are
  review comments, not issue comments.
- `gh workflow run oracle-review-shadow.yml --ref develop -f pr=<number>`
  does the same. A dispatch from any other ref is refused.
- An hourly schedule retries pull requests whose last result on the current
  head is pending.

A rerun on the same head needs a previous run in which every attempted
reviewer was absent. A run that stayed pending because its artifacts failed
validation, or because a selected reviewer never reported, is not rerun on the
same head; push a new head instead. Comment, dispatch and scheduled reruns share a daily budget per pull
request (`retry.daily_budget`), with backoff that starts at one hour and
doubles. The retry state is the `oracle-review-shadow-state-<number>` artifact
of the latest run of this workflow whose commit is on `develop`; artifacts from
any other workflow or branch are ignored.

## Calibration

These checks must pass before the cut-over that makes the context required.

- **P2:** a `pull_request_target` run from a same-repository test pull request
  enters the `oracle` environment; a `pull_request` run from the pull request
  branch cannot.
- **P3:** each reviewer authenticates in CI. A reviewer that cannot is set to
  `enabled: false` with a `disabled_reason`. agy stays disabled until it
  passes; enabling it needs an agy job and a fifth reviewer slot.
- **P4:** capture each reviewer's quota, authentication and outage output from
  real runs. The attempt artifact's `diagnostic` field holds one redacted line
  of the output, at most 300 characters, with credentials and long tokens
  removed; raw output is never uploaded. Add the messages to the `CALIBRATED_*_PATTERNS` tables in
  `_project/scripts/oracle_reviewers/absence.py`; until then they count as
  errors, which never pass.

During the shadow period, compare each `oracle-review-shadow` result with the
review the pull request actually received.
