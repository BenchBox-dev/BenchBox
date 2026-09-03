# Adversarial Review

Review completed work skeptically and use evidence for every conclusion.
This is read-only under `shared-review-protocol/SKILL.md`
[REVIEW-AUTH-001]. Report findings without editing files, closing tracker
items, committing, or publishing. A later user message must authorize fixes.

## Scope

Choose one scope and name it in the report:

| Scope | Covers |
|---|---|
| `session` | Work completed in the current or a named prior session |
| `change` | A diff, branch, PR, or set of PRs |
| `feature` | One feature or subsystem across its recent changes |
| `project` | A whole project, including whether its value justifies its complexity |

## Review method

- Treat self-reports, commit messages, and PR descriptions as claims. Check
  the revision, CI result, implementation, and tests before accepting them.
- Treat known or suspected problems as the starting point. Check for other
  problems in the same scope.
- Apply the selected domain wrapper's review rubric. For example, use the
  code five-axis review for code, the documentation persona review for docs,
  and the critique rubric for blog posts.
- Apply the L2 blind-spot audit and L3 problem reframe from
  [REVIEW-DEPTH-001]. Keep concrete defects in the severity table.

## Verdict

For `session`, `change`, or `feature`, choose `Ship`, `Ship with caveats`, or
`Do not ship`. List every caveat or blocker.

For `project`, choose `Keep`, `Simplify`, or `Retire`. Support the verdict
with evidence about value, complexity, maintenance cost, and alternatives.

## Report

1. Scope, exact revisions reviewed, and verdict.
2. Severity table with `file:line` evidence.
3. Claims verified and claims that failed verification.
4. L2 blind spots and any L3 reframe.
5. What is done well.

Route defects through [REVIEW-DEFECT-001], solution-fit findings without
accompanying defect as action items under [REVIEW-FIT-001], and capture through
[REVIEW-CAPTURE-001].
