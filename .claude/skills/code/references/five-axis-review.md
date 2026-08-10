# Five-Axis Code Review Reference

Every review evaluates five dimensions with severity classification.

> **Scope:** This file is for code reviews only. Use it to check the five axes, what to delete, how to rate issues, size limits, and code-specific branches.
>
> It does not control permissions or workflow. `SHARED/review-protocol/SKILL.md` controls those. It covers authorization, defect handling, L1/L2/L3 steps, saving findings, and parity (`REVIEW-AUTH-001` to `REVIEW-PARITY-001`).
>
> `SHARED/review-protocol/SKILL.md` defines the authorization boundary. Only a later user message, in a separate turn, can authorize remediation. This file cannot authorize changes.

## Router-specific checks

- Accept any review scope: a file path, directory, staged changes, recent commits, a PR, a topic, or no scope. List severity findings first: Critical, Required, Nit, Consider.
- Route L2 blind-spot audits through `SHARED/review-protocol/SKILL.md`.
- For review-shape triggers, use the matching branch below: matrix/audit-doc,
  mixed tooling+data, repo-shape ADR, multi-W spec, defect follow-up
  artifact-freshness, or verification-only.
- For multi-PR work, run `gh pr diff <N> --name-only` and classify blockers
  before content; avoid `--json body,files` unless needed.
- Put project-specific checks (for example, SQLGlot dialect checks) in `code.review_checklist` (`code/skill.yaml:28`). Do not add them to this shared rubric. Use them only when `skill-sync.config.yaml` sets `code.review_checklist`.
- `review --chain` stays read-only unless a later user message explicitly authorizes remediation in a separate turn under `SHARED/review-protocol/SKILL.md` [REVIEW-AUTH-001]. If authorized, it can fix only non-structural issues. Verify the fixes. Then use the commit framework to save, push, or open a PR.

## The Five Axes

### 1. Correctness
- Matches spec/task requirements?
- Edge cases handled (null, empty, boundary)?
- Error paths handled (not just happy path)?
- Tests adequate and testing the right things?
- Off-by-one, race conditions, state inconsistencies?
- **Empirical-claim durability**: if you change numbers that were measured (like `verified <tool>` comments, doc storage sizes, or expected-bytes limits), add two things. First, a check-in smoke or make target that reproduces the measurement. Second, a test that fails when the docs no longer match the catalog.

### 2. Readability & Simplicity
- Names descriptive, consistent with project conventions?
- Control flow straightforward (no nested ternaries, deep callbacks)?
- Abstractions earning their complexity?
- Dead code removed (`_unused` vars, compat shims, stale comments)?

**Deletion sub-checklist (what can be cut):**
- What in this diff can be deleted while preserving the specification?
- Look for: reinvented stdlib, unneeded dependencies, speculative
  abstractions, and dead flexibility (unused options/params/branches).
- One line per finding: location (`file:line`), what to cut, what replaces
  it (stdlib call, existing helper, or nothing).
- These are report-only findings: deletions are structural changes and are
  never auto-applied by a review.

### 3. Architecture
- Follows existing patterns or introduces justified new one?
- Clean module boundaries, no circular deps?
- Code duplication that should be shared?
- Abstraction level appropriate (not over-engineered, not too coupled)?

### 4. Security
- User input validated/sanitized at boundaries?
- Secrets out of code, logs, version control?
- SQL parameterized (no string concatenation)?
- External data treated as untrusted?

### 5. Performance
- N+1 query patterns?
- Unbounded loops or unconstrained data fetching?
- Large objects in hot paths?
- Sync operations that should be async?

## Severity Classification

| Prefix | Meaning | Author Action |
|--------|---------|---------------|
| **Critical** | Blocks merge -- security, data loss, broken functionality | Must fix |
| *(none)* | Required change | Must address |
| **Nit** | Minor, optional | May ignore |
| **Consider** | Suggestion worth evaluating | Not required |

Critical and Required findings are **defects** per
`SHARED/review-protocol/SKILL.md` §2; they belong in the severity table and
action items, never in the blind-spot directory.

## Change Sizing

- ~100 lines: Good (reviewable in one sitting)
- ~300 lines: Acceptable (single logical change)
- ~1000 lines: Too large (split it)

## Rules

- Every review must include "What's Done Well" -- criticism-only reviews are incomplete
- Separate refactoring from feature work
- Approve when change definitely improves code health, even if imperfect
- No rubber-stamps -- "LGTM" without evidence helps no one

## Branches

Apply when the change matches a trigger; skip otherwise.

### Matrix/audit-doc branch
Trigger: doc whose payload is tables of numbers (audit/curation/inventory).
- Regenerate every numeric claim from source and diff; stale arithmetic is the dominant failure mode.
- Policy-gated recommendations need an "Alternatives considered" section that quantifies, not narrates.

### Mixed tooling+data branch
Trigger: PR bundles tooling artifacts (CI/lint/build) with data artifacts (fixtures, JSON, bundles).
- Assess reversibility per component, not aggregate.
- If tooling silences a data-side defect, require a follow-up TODO id for the upstream fix.

### Repo-shape ADR branch
Trigger: ADR proposes branch-shape changes, CI moves, or cross-branch vendoring.
- Enumerate consumers (CI, contributors, automation, downstream).
- Confirm each works under the stated allowlist; undocumented carve-outs mean the ADR isn't ready.

### Multi-W spec branch
Trigger: spec decomposes into W1..Wn.
- Estimate LOC per W from the module breakdown.
- Flag any W >300 LOC pre-approval; require a split or rationale.

### Defect follow-up branch
Trigger: orchestration/phase-output fix where artifacts are parsed by another phase.
- Confirm parsed files came from the current invocation, not an earlier failed run.
- Flag stale-file reuse: `os.path.exists` + skip, cached-result short-circuits.

### Verification-only branch
Trigger: verification-only PR, or a commit asserts evidence without a committed artifact.
- Require a committed transcript or pin file (for example, the project's verification-log convention) a later reviewer can replay.
- Reject "trust me, I ran it" — transient terminal output isn't durable.
