# ADR: BenchBox Development Loop Architecture (v2)

## Status

Accepted (2026-09-28).

Supersedes:
- [`docs/operations/merge-queue-governance.md`](../../operations/merge-queue-governance.md)
- [`docs/development/pr-base-branch-policy.md`](../pr-base-branch-policy.md)
- [`docs/development/adr/adr-independent-publication-authorities.md`](adr-independent-publication-authorities.md) (per decision D2)
- Version-branch release flow in [`docs/operations/release-guide.md`](../../operations/release-guide.md)

## Context

BenchBox previously relied on an intricate set of 46 separate GitHub Actions workflows,
a long-lived protected `release` branch alongside `develop`, an automated post-merge
safety net with complex reconciliation, numerous PR-loop Make targets and scripts, and
a multi-workflow publication control plane.

This design accumulated significant operational drag:
- CI runs often took 40–60 minutes across duplicate workflow fanouts.
- PR-loop checks and post-merge jobs drifted from each other.
- The `release` branch required continuous cherry-picks, version-branch maintenance,
  and canary runs that duplicated merge-queue work.
- The publication control plane relied on an external GitHub App and separate branch
  transactions that could stall or disconnect from trunk state.

This ADR establishes the architectural decisions, operational contracts, and migration
guardrails for a consolidated trunk-based development loop behind the GitHub merge queue.

Amended 2026-10-03: the merge queue and the strict up-to-date rule on `develop` are
retired, and a pull request merges by auto-merge once its required checks pass on its
own head. The queue's failures were mostly its own machinery: 38 of the 40 most recent
failed merge-group runs, with no confirmed cross-PR integration failure. A post-merge
workflow, `.github/workflows/trunk.yml`, tests `develop` after each merge, and a red
trunk is reverted first. Where this ADR names the merge queue, read the history of the
design, not the current gate. See
`_project/decisions/merge-queue-retirement-2026-10-03.md`.

## Decisions

### D1: Trunk branch remains `develop`

The primary development branch remains `develop`. Renaming `develop` to `main` is
rejected (see Rejected Alternatives) to avoid disruption across downstream forks,
clones, documentation, tooling, and repository configurations.

### D2: Replace the publication control plane

The multi-workflow publication control plane is replaced with a single unified
`site-deploy` workflow for `benchbox.dev`. Entry criteria for the replacement:
- Pinned source and corpus SHAs.
- Retained artifact identity across stages.
- Post-deploy route and digest health probes.
- Durable deployment receipts.
- Exact-artifact rollback support with last-known-good validation.
- One serialized production writer with generation checks.
- Route-manifest assembly (`/` and `/docs/` from latest release tag; `/docs/dev/`,
  blog, and `/results/` from trunk).
- Rollback verified with `github-pages` environment reviewers enabled.

Once `site-deploy` validates in shadow and cuts over, the legacy publication workflows,
publication transaction branch, and publication GitHub App are retired.

### D3: Results corpus layout unchanged

The results corpus homes remain unchanged:
- `results-data/` on `develop` for active working runs and staged data.
- `published-results` as the slim corpus-only branch for public submissions.

### D4: Soundness hold via CI flag and adversarial review

Soundness path protection moves from the legacy auto-merge predicate to an explicit
two-layer safety contract:
1. CI detection: the `tooling` check in `ci.yml` inspects changed paths against the
   soundness path manifest and flags any pull request modifying soundness-critical files.
2. Mandatory external review: agents and maintainers may enqueue pull requests touching
   soundness paths only after a dedicated external adversarial review (using an
   independent model such as Codex, Muse, or AGY) produces zero unresolved Critical or
   High findings, with review evidence and findings recorded in the PR body.

The repository's code-owner review setting remains configured but is not solely relied
upon as the authorization mechanism.

Amended 2026-10-02: the external review stays, but a PR-body attestation checked by CI
will no longer bind it. The author of a change writes its own attestation, so the check
can only test that the text is present; it never tests the review. The review is bound
by three controls:

1. Review findings. The external reviewer's Critical and High findings are posted as PR
   review threads, and the ruleset requires every thread to be resolved before a merge
   (`required_review_thread_resolution`). GitHub lets an author with write access resolve
   a thread, so resolution shows that someone dispositioned the finding, not that it was
   fixed. The digest below is the check on that.
2. Review signal as a required check. For changes on the narrowed soundness path list,
   the required `oracle-review` status check passes only when the Codex connector app has
   reviewed the current head: its submitted review or thumbs-up reaction. An "eyes"
   reaction alone means the review has started, not finished. A review that exists shows
   that a reviewer looked, not what it examined.
3. Post-merge digest. A scheduled report lists the commits that reached `develop` on the
   narrowed paths and records which review signal each had at merge. It also flags each
   review thread that was resolved with no later commit. It opens a tracker item for
   each commit with no signal or with such a thread. An agent then runs the external
   review and either records a clean result or opens a fix or revert PR.

The first two controls can be bypassed by an author acting alone with the owner's
rights, because every agent shares one account. They make a skipped review visible and
slower to skip; the digest detects a bypass after the merge and is the backstop. A
squash commit is one revert unit, but a revert on a busy trunk is not always clean, so
the backstop does not replace the review before the merge.

The `oracle-review` check is a merge-blocking automated review signal. It supersedes item 3 of
`_project/decisions/codeowner-approving-count-zero-constraint-2026-09-15.md` for paths on
the soundness list only, and only that item. That decision kept such signals advisory
because a batch of failing Codex reviews exhausted the usage limit and deadlocked the
queue. The `codex` CLI, `muse` and `agy` remain available as optional extra depth, each
with its own quota, but only the Codex connector's review satisfies the check.

When the connector has not reviewed the head within four hours, the owner, not an agent,
reviews the change in their own session. If the owner approves, they either re-request the
connector review, or merge the pull request themselves through the GitHub UI after
temporarily removing `oracle-review` from the required checks, and restore it afterwards.
Every human and agent posts as the owner account, so an owner comment cannot be told apart
from an agent's; for that reason `oracle-review` does not accept one, and agents never post
a review on the owner's behalf. All four reviewers were exhausted at once on 2026-10-02,
which blocked every workflow change for three days under the fail-closed rule alone.

The soundness path list is narrowed to code that produces, normalizes, compares or
validates results, every workflow, the release and binary paths, and `AGENTS.md`.
Documentation, decision records, runbooks and threat models leave the list, because a
review of prose gives no protection against a wrong result. The CI detection layer is
unchanged, and the external review requirement is unchanged except for the quota
fallback above. `AGENTS.md` still states the requirement without the fallback; the change
that removes the attestation check from `ci.yml` rewrites that sentence, because
`AGENTS.md` is itself a soundness path and must carry the attestation until then. The
`oracle-review` check, the digest and the narrowed list land in separate changes; until the
attestation check is removed from `ci.yml`, a PR on a soundness path must still carry a
valid `Soundness review:` section.

### D5: Retain agent write tooling, retire PR-loop scripts

Agent workspace safety tooling is retained:
- Worktree creation and lifecycle management (`make worktree-create`, `worktree-remove`).
- Git identity pinning and author verification (`agent-write-preflight`, `agent-git-identity`).
- Attribution trailer verification (`check_agent_trailers`).
- Issue tracker state branch operations (`todo-state`).

Legacy agent PR-loop scripts (`pr_landing.py`, `pr_followups.py`, `soundness_drain.py`,
`local_validation.py`) and their corresponding Make targets are retired.

### D6: Codecov retained as informational

Codecov code coverage tracking is retained. Coverage reports upload during the merge-queue
T2 tier. Coverage results remain informational and do not block the queue.

### D7: Ruleset drift detection retained

Ruleset drift verification (`ruleset_drift_check.py`) is retained. It executes as a
required check within the `tooling` unit of `ci.yml` and within the release workflow.
The `RULESET_DRIFT_TOKEN` secret is maintained.

### Tag signatures and release verification

Explicit cryptographic tag signatures are dropped. Release integrity relies on:
1. The `v-tag-restricted` ruleset preventing unauthorized tag creation or mutation.
2. Verification that the tagged commit exists on `develop` and passed the merge queue.
3. Matching artifact SHA-256 hashes between the queue build and release upload.
4. GitHub Actions build provenance attestations.

## Standing Administrative Approvals

The maintainer has granted standing approvals for the following operational changes
once corresponding preconditions and backups (per Guardrail G5) are satisfied:

1. **Rulesets and merge queue:**
   - Add new required checks (`core`, `explorer`, `results-data`, `docs`, `landing`, `tooling`).
   - Remove legacy checks after the transition window.
   - Adjust merge queue parameters: `max_entries_to_build` 5 -> 2, `max_entries_to_merge` 5 -> 3;
     the check timeout stays at 60 minutes.
   - Delete the obsolete `release-only` ruleset.

2. **Branches:**
   - Delete `release` and `publication` branches after creating immutable archive tags.
   - Delete stale `gh-readonly-queue/*` branches with no active queue entry.
   - Delete merged `auto-revert/*` branches and merged feature/fix branches.

3. **Labels and environments:**
   - Delete legacy incident labels (`incident:develop-red`, `incident:develop-red-revert-conflict`,
     `incident:release-canary-red`) and `no-auto-merge`.
   - Create `quarantine` and `t3:*` labels.
   - Delete the `publication-attestation` environment after site deployment cutover.

4. **Secrets and GitHub Apps:**
   - Delete `PUBLICATION_APP_ID` and `PUBLICATION_PRIVATE_KEY`, and uninstall the
     publication GitHub App after `site-deploy` cutover.
   - Delete unused legacy tracker secrets if no repository references exist.

5. **Self-service merge:**
   - Autonomous merge of modernization PRs targeting `develop` once all required checks,
     self-review, and required soundness reviews pass.

6. **Site deployment approval:**
   - Approve pending `github-pages` deployments via GitHub API once pre-deployment
     verification passes.

7. **Release flow rehearsal:**
   - Execute TestPyPI publication rehearsals autonomously.
   - Note: Real PyPI production publication remains strictly owner-initiated.

8. **Live cloud benchmarks (`t3:cloud`):**
   - Wired behind configuration defaulting to disabled; live cloud runs remain off.

9. **Merge-queue test budget:**
   - If T2 exceeds the 15-minute target, standard runner sharding may increase up to 10.
     If still exceeding 15 minutes, accept up to 20 minutes with durable rationale.
     Paid larger runners are not authorized.

10. **Waiting windows:**
    - Active observation windows (5 business days shadow, 7 nightly runs, 20 queue runs)
      are non-blocking for independent tasks.

## Guardrails

- **G1 Replacement before removal:** A required check is removed only after its replacement
  has passed a canary set of throwaway pull requests (one change per unit, one cross-unit
  change, one soundness-path change, and one deliberately broken change per unit) AND the
  property ledger (G3) maps every protected property to the replacement. Three real queue
  merges must then pass under the new checks before the flip is considered complete.
  (Amended 2026-09-29: the earlier 20-run window assumed the old and new workflows could
  run side by side; the merge groups already saturated the organization's runners, so
  side-by-side operation is not possible and the cutover is a single flip.)
- **G2 Shadow parity:** Superseded by the canary set in G1 for the pull-request and merge
  queue workflow. Scheduled workflows (nightly) still validate with dispatched runs
  before their predecessors retire.
- **G3 Property ledger (`docs/development/dev-loop-property-ledger.md`):** Every safety
  property -> current guard -> new guard -> proof. Properties include: correctness oracle
  (digest arming, query discrimination, no-skip), SQL self-binding lint, monotonic-clock
  policy, submission validation, corpus trust boundary, artifact privacy, publication
  rollback, explorer snapshot compatibility, public-site visual acceptance, binary integrity,
  wheel installability, dependency bounds, release curation, ruleset/settings drift,
  soundness-path owner hold, workflow context validity, merge_group triggers. A test or workflow
  is deleted only if the ledger shows coverage or classifies it pure-process.
- **G4 Reference sweep:** Each deletion PR proves zero references to deleted names in
  workflows, Makefile, make/, scripts/, _project/scripts/, tests/, docs/, AGENTS.md,
  CONTRIBUTING.md, .claude/, .pre-commit-config.yaml, and the skill-sync source, excluding
  CHANGELOG and archives.
- **G5 Backups first:** Export ruleset JSON, environments, labels, branch list, secret names,
  and Pages settings to `_project/archive/dev-loop-v2/` before any GitHub-side change; tag
  branches `archive/<name>-<date>` before deletion.
- **G6 One cluster per PR:** No PR mixes GitHub settings with code deletion; each PR is
  independently revertible.
- **G7 Release freeze:** Active from the start of required-check transition until the first
  new-path PyPI release; the old release path (release branch, test.yml, validate-release-pr,
  release-canary, drift scripts, release-cut targets) stays fully working until then.
- **G8 Secrets and Apps:** Removed only after no workflow, script, or doc references them
  and one full T3 cycle passed; PAT revoked at issuer; each removal is a separate owner-approved
  step.
- **G9 Admin changes:** Admin changes covered by the standing approvals are made by the
  agent after G5 backups; anything outside them stops.
- **G10 Instructions move in lockstep:** Any PR that removes or renames a Make target,
  script, or workflow used by AGENTS.md, CONTRIBUTING.md, .claude/commands, or skills updates
  those (skill-sync source, then re-sync) in the same PR.
- **G11 Settings-doc first:** Before any ruleset change, merge the PR that updates the drift
  checker's expected settings so the live change does not fail `ruleset-drift` closed and
  deadlock the queue.

## Rejected Alternatives

1. **Renaming default branch from `develop` to `main`:**
   Rejected because renaming causes wide disruption across forks, clones, CI scripts,
   git submodules, issue tracker references, and external links without delivering
   engineering value.

2. **Per-module test selection in PR builds:**
   Rejected because fine-grained dynamic test selection introduces blind spots where
   indirect interface dependencies fail to trigger tests. Coarse-grained unit classification
   with always-reporting checks provides deterministic coverage.

3. **Live cloud platform testing in PR or merge queue:**
   Rejected due to network flakiness, credential exposure risks, high API costs, and
   long runtimes that would violate the merge queue's 30-minute target. Live cloud testing
   is isolated to scheduled nightly T3 execution.

4. **CODEOWNERS-only hold for soundness paths:**
   Rejected because the repository's required approval count is 0 and automated agents
   acting with owner permissions would bypass the intended hold (observed empirically in
   PR #2416). Explicit CI path detection and external adversarial review ensure rigorous
   soundness verification.
