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
   diff exceeds the brief cap, any reviewer that is not hard read-only with
   `reads_files: true`.
3. `attempt-N-<harness>` runs that reviewer on a detached, credential-free
   checkout of the head. It never runs pull request code. The result is an
   artifact with the run ID, head SHA, reviewer and either a validated verdict
   or an absence.
4. `post` re-validates every artifact from this run, replays the selection,
   and posts the status and the findings. `findings_delivery` in
   `.github/oracle-reviewers.yml` chooses how:
   - `comment` posts one pull request comment, so findings never block a
     merge.
   - `review` posts one pull request review per result on the head commit.
     Under SHIP WITH FIXES, each defect that lands on a diff line opens a
     thread; a defect that spans lines gets a multi-line thread when every
     line of the span is in the diff, and a single-line thread at its first
     line otherwise. Every other defect is listed in the review body with the
     summary. DO NOT SHIP opens no thread. A run with no verdict still
     posts a review that explains the pending result, so the latest review
     always reflects the latest run. The ruleset requires every thread to be
     resolved, so these threads block merges like the connector's. The
     policy uses `review` from the start of the parity period before the
     cut-over.

`plan` also limits spend to code that changed. The retry state records the
blob SHA and tree mode of each changed file at the last success or failure, except prose
files (`.md`, `.mdx`, `.rst`) outside soundness paths, with the basis
of that result: the merge base of the head with `develop`, the tier and its
reviewer settings, the excluded author families, and a
hash of the policy file, brief template, read rules, verdict schema, reviewer code and this
workflow. When the basis is unchanged and the new
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

A defect fails the review even when its line is outside the diff. Such a
defect cannot become a line comment, so it is listed in the review body with a
note that it counts like the others. Ignoring it would let a reviewer's report
of a real defect pass because it cited an unchanged line.

Reviewers run one at a time, so a decision stops the run and an absent
reviewer hands over to the next.

## Decisions

The reviewer answers with schema 2 of the verdict (`VERDICT_SCHEMA` in
`_project/scripts/oracle_reviewers/verdict.py`). Every property is required,
because Codex structured outputs reject optional keys: `status` (`complete` or
`incomplete`), `incomplete_reason`, `decision` (`SHIP`, `SHIP_WITH_FIXES`,
`DO_NOT_SHIP`, or `NONE` when incomplete), `summary`, `files_examined`,
`defects` and `prior_defects`. A reviewer that adds any other key, such as a
defect count, is invalid. The brief asks for must-fix defects only, at
most `protocol.max_defects` (10), and for `DO_NOT_SHIP` when the change needs
rework or more defects would have to be listed.

The code, not the model, decides, and the stricter outcome wins:

| Reviewer reports | Result |
|---|---|
| SHIP or SHIP_WITH_FIXES, no defects | SHIP |
| SHIP or SHIP_WITH_FIXES, 1 to 10 defects | SHIP WITH FIXES |
| more than 10 defects | DO NOT SHIP; the defects are dropped and the summary notes the count |
| DO_NOT_SHIP | DO NOT SHIP; the summary is kept, at most 1500 characters |
| `incomplete` | the reviewer is absent (`incomplete`) and the next one runs |

Severity orders the list and never gates: any listed defect, even a Low one,
makes the result SHIP WITH FIXES. SHIP posts `success`; SHIP WITH FIXES and
DO NOT SHIP post `failure`. The first line of the review body,
`### oracle-review-shadow: <state> for <sha>`, is unchanged, and a
`Decision:` line follows it. A list of more than 10 defects is not treated as
an invalid verdict, because every reviewer would then fail in turn and leave
the pull request pending.

## Evidence that a review happened

A verdict without a defect can be hollow: a reviewer that could not read the
files may still answer. The review job checks each verdict against the head
checkout before it records it; a failed check records the reviewer as absent
(`incomplete`), so the next reviewer runs and a hollow answer never passes.

- In every mode, each defect must cite a file in the head commit and a line
  within it. A defect that does not is kept, with a note that its citation was
  not found, so it still fails the change; discarding the verdict would hand the
  change to the next reviewer, which might pass it.
- When the brief lists files instead of carrying the diff (`file-list` mode),
  a verdict that would ship (no defect and not DO NOT SHIP) must name, in
  `files_examined`, every soundness-path
  file the pull request changes that still exists at the head, and the
  reviewer's trace must show it read each one. Claude runs with
  `--output-format stream-json`, and each file needs a successful Read or Grep
  that names it; the structured-output call does not count. Codex runs with
  `--json`, and each file needs a successful content-reading command (`cat`,
  `sed`, `head`, `tail`, `nl`, `awk`, `grep` or `rg` on the file, or `git
  show`, `git diff` or `git blame`) with that exact path as an operand. A
  listing, an existence check, `echo`, a search of a directory, a path used as
  a search pattern and a read of the staged diff do not count.
- An inline brief carries the diff, so no read is required there.

The brief no longer forbids running commands. Its `<<read-rule>>` slot is
filled per harness when the review runs: Codex may run read-only shell
commands (`cat`, `sed -n`, `head`, `rg`, `git show` and similar) but nothing
that writes, builds, tests or uses the network, and its `--sandbox read-only`
still blocks writes; Claude reads with Read, Grep and Glob; muse uses its
workspace file tools with shell disabled. A file-list brief also gets the
whole pull request diff staged in the checkout.

muse and agy leave no trace of what they read, so for them only the citation
check and the reviewer's own `files_examined` apply. agy also cannot read files
in headless plan mode (its reads are denied), so it has `reads_files: false`
and never takes a file-list brief. The workflow-level group for the pull request
serializes runs on one pull request; the attempt jobs have no concurrency group
of their own.

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

## Cut-over

The required `oracle-review` check takes `--signal connector` (the default) or
`--signal oracle`. With `connector` it requires the Codex connector's review
of the head, or its thumbs-up, and counts the connector's open threads. With
`oracle` it requires, from the `benchbox-oracle` App's Bot account:

- a review of the head, not pending or dismissed, submitted after any retarget,
  whose latest one opens with `### oracle-review-shadow: success for` the head
  SHA, because the oracle posts every verdict as a comment review and a
  defect outside the diff has no thread;
- no unresolved review thread from the App.

The verdict is read from the pull request's own review, not from the commit
status, which any pull request with the same head commit could set. The
oracle signal needs `findings_delivery: review`, under which every run that
reaches a result, including a pending one, posts a review, so the latest
review is the latest result.

The stand-in attestation passes under either signal. Under `oracle` it must be
posted after the oracle's latest review of the head, so overriding a failing
verdict is a deliberate act; it never overrides an open thread.

Every run also evaluates the signal it does not require and logs the result on
two `parity:` lines. That evaluation fetches its own inputs, and an error in it
is logged and never changes the check's result. Compare those lines across real
pull requests before the cut-over.

The checker runs from the base commit, so the workflow can pass `--signal`
only after `develop`'s copy of the script accepts it. The cut-over sets
`mode: enforce` in `.github/oracle-reviewers.yml` and adds `--signal oracle`
to `.github/workflows/oracle-review.yml` in the same change; a unit test fails
if they disagree or if delivery is not `review`.
