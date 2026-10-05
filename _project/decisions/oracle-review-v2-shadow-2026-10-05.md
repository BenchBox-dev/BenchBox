# Self-hosted oracle review, shadow mode

Date: 2026-10-05
Status: Decided. The shadow workflow is added; the required `oracle-review`
check and `_project/scripts/oracle_review_check.py` are unchanged.
Related: `.github/workflows/oracle-review-shadow.yml`,
`.github/oracle-reviewers.yml`, `_project/scripts/oracle_reviewers/`,
`docs/operations/oracle-review-v2.md`.

## Context

Soundness-path pull requests merge only after the required `oracle-review`
check passes. Today that check needs the Codex connector's review or a
stand-in approval comment from an account that local automation also uses, so
the signal can be forged. The replacement runs agent reviewers from `develop`,
decides pass or fail in deterministic code, and posts the result through a
GitHub App that only the owner controls. No third-party GitHub app is
involved.

## Decision

One workflow, run from the `develop` copy, reviews each soundness-path pull
request with one reviewer chosen by complexity tier and by which reviewers
have usage left.

- **Tiers.** A deterministic classifier, read from `develop`, sorts the change
  into low–medium (data-only paths such as answer files, or a small
  single-area diff), medium–high (comparison, equivalence, validation or
  result-capture logic, or a larger diff) or very high (the gate itself, or a
  large multi-area diff). A label may raise the tier, never lower it. Files
  that make up the gate count as soundness paths even before the manifest
  lists them.
- **Reviewers.** Low–medium: muse `muse-spark-1.3`, agy
  `gemini-3.8-flash-medium`, codex `gpt-6-luna` at high effort, then the
  medium–high reviewers. Medium–high: claude `claude-sonnet-5-5`, codex
  `gpt-6.1-sol`, then the low–medium reviewers. Very high: claude
  `claude-opus-5-5` at medium effort, then `gpt-6.1-sol` at medium effort,
  then pending. Opus never serves a lower tier.
- **Blocking severities.** Critical and High in the lower tiers; Critical,
  High and Medium in the very-high tier.
- **Diversity.** Reviewers from the author's family are skipped, including
  through fallback, except Opus in the very-high tier. The family comes from an
  `author-family:<family>` label; a missing or unknown label means Claude.
- **Quota pools.** Claude (Opus and Sonnet), Codex (Sol and Luna), muse and
  agy. A quota absence skips the rest of the pool for the run, and a reported
  reset time skips the pool until it passes. Any other absence lets pool peers
  try.
- **One reviewer per pull request.** A blocking verdict is final for the head;
  fallback happens only when a reviewer is absent. A blocking finding whose
  line is outside the diff still fails the review: it is posted in the summary
  rather than as a line comment, and dropping it would let a real defect pass
  on a citation detail. Unknown or failed outcomes
  are absent, which leaves the result pending, never passing.
- **Integrity.** Each reviewer job enters the `oracle` environment and loads
  only its own credential. Only the final job holds the App key, and it posts
  only artifacts from its own run that name the head the workflow checked out.
  Verdicts must match a strict schema; findings are cleaned of secrets,
  mentions and links before posting.
- **Usage limits.** A rerun needs a new head or a previous run in which every
  attempted reviewer was absent; a run left pending by invalid artifacts or a
  reviewer that never reported is not rerun on the same head. `/oracle-review`
  works only as a top-level pull request comment. `/oracle-review` comments and hourly scheduled retries
  share a daily budget per pull request, with backoff starting at one hour.

## What shadow mode does and does not do

The workflow posts a separate, non-required `oracle-review-shadow` status and,
for failures, pending results and findings, one pull request comment. It posts
findings as a comment rather than review threads, because the ruleset requires
every review thread to be resolved and shadow findings must not block merges.

It does not change the required `oracle-review` check, the ruleset, the digest
or the soundness manifest. It does not post a pending status when a run
starts, because only the final job holds the App key. Without the App secrets
it logs the result and succeeds.

## Disabled or not yet proven

- agy is disabled in the policy and has no job, because its CI authentication
  and quota output are not calibrated and its usage is exhausted.
- The quota and authentication messages of claude and codex are not
  calibrated. Until they are, those failures are recorded as errors, which
  still never pass; the pattern tables in `absence.py` take the calibrated
  messages.
- codex and agy have no turn-cap flag, so their timeout is the only bound.
- muse is disabled in the policy and has no job. Meta's only documented
  installer, `https://dev.meta.ai/install.sh`, has no version or published
  checksum: it fetches an unversioned launcher, and the launcher downloads the
  channel's latest binary each time it runs, so nothing can be pinned. Until
  Meta publishes a versioned, checksummed release, low–medium changes from a
  Claude author go to `gpt-6-luna`, then `gpt-6.1-sol`.
- The policy's `max_attempts`, and so the number of reviewer slots in the
  workflow, must cover the longest chain of enabled reviewers; enabling muse
  or agy needs more slots and a job for that harness.
- Retry state is read only from artifacts of this workflow's runs whose commit
  is on `develop`, so a pull request's own workflow cannot forge it. That a
  `pull_request_target` run records the base commit as its head SHA is
  assumed, not yet observed; if it does not, those runs' state is ignored, and
  a comment rerun after a decisive pull request event is not refused.

## Cut-over

A later change renames the context to `oracle-review`, retires the connector
check and the stand-in marker, switches findings to review threads, adds the
gate files to `.github/soundness-paths.txt`, and pins the context to the App's
integration ID in the ruleset.
