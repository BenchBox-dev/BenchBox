# Decision: approving-review count stays zero; review gates stay advisory

Date: 2026-09-15
Status: Accepted. This record pins two constraints so they are not re-derived
from first principles in a later review.
Observed tip: `origin/develop` `41f35aad30deae66caa996f43858fc6eda9e9e41`.

Related: `_project/decisions/auto-merge-policy-consolidation-2026-08-06.md`
(D7); `docs/operations/repo-admin-settings.md` ("Soundness-path review
enforcement"); `_project/scripts/ruleset_review_enforcement.py`;
`.github/CODEOWNERS`.

## Decision

1. `required_approving_review_count` stays `0` on the `develop-squash-only`
   ruleset. The count is branch-wide: raising it gates every `develop` PR,
   not just soundness-path PRs. That is why the review predicate
   (`ruleset_review_enforcement.py`) asserts `require_code_owner_review`
   without asserting the count. Revisit only if the identity model changes
   (a second code owner, or a non-self-approval PR identity); even then,
   GitHub offers no CODEOWNERS-scoped count, so a branch-wide count still
   gates all PRs and needs its own decision.
2. `require_code_owner_review: true` stays on for the CODEOWNERS-owned
   soundness surface. The sole owner authors every PR and GitHub forbids
   self-approval, so soundness-path PRs merge manually, never hands-free.
   The drift check (`scripts/ruleset_drift_check.py`,
   `DEVELOP_REVIEW_RULE_ENFORCED`) keeps this blocking.
3. No merge-blocking review gate (D7). The 08-06 batch showed every Codex
   review failing on usage limits with zero completed external reviews;
   coupling merge availability to reviewer quota deadlocks the queue.
   Reviews are funded author-paced — PRs stay unarmed until reviewed when
   the author chooses — and any automated-review signal (for example a
   Codex-reviewed-this-head check) stays advisory: recorded, never a member
   of the readiness failure set.

## What this item does not do

- No ruleset mutation, no required-context change, no workflow edit.
- No claim about future identity models beyond the revisit condition above.
