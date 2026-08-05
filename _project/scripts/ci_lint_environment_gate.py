#!/usr/bin/env python3
"""Decide whether a `make ci-lint` guard is meaningful on a CI runner.

`ci-lint` (Makefile) exists to mirror the `pr.yml` `code-lint` job locally
(docs/operations/ci-local-parity.md), but `develop-post-merge.yml` also runs
`make ci-lint` directly on a real, ephemeral GitHub-hosted runner -- not as a
local-parity convenience, but as a blocking gate wired into auto-revert. Most
guards are equally meaningful there: they inspect the checked-out tree, the
installed venv, or the registries the repo ships, none of which differ
between a laptop and a runner.

A small number of guards instead read state that only exists on a developer
machine -- a resolved Git identity, a tool installed at a hardcoded local
path -- and behave one of two bad ways on a runner that lacks it: they fail
for a reason that has nothing to do with the code under test (the pre-#1558
`agent-identity-check` behavior), or worse, they silently no-op and report
success while checking nothing (`skill-sync-check` against a `$(SKILL_SYNC)`
path that plainly does not exist on the runner). The second failure mode is
the more dangerous one: a guard that cannot fail reads as coverage in the
Actions log and is never investigated.

This module is the single place that draws that boundary. Before the
Makefile recipe runs a runner-inapplicable guard, it asks this module; if the
guard is listed AND the process is actually running on a GitHub Actions
runner (`GITHUB_ACTIONS=true`, the platform-set variable -- never
hand-toggled), the guard is skipped with a printed reason instead of run and
either silently passing or noisily failing. Every other guard -- the
overwhelming majority -- is untouched: this is a narrow allowlist of
documented exceptions, not a generic on/off switch, and adding a guard here
requires the same reasoning as removing coverage, because that is exactly
what it does on a runner.

Local and CI-local-parity invocations (`GITHUB_ACTIONS` unset) are never
affected by this table -- every guard always runs there, including the two
listed below, exactly as before this module existed.
"""

from __future__ import annotations

import argparse
import os
import sys

# Guard slugs that are structurally incapable of producing a meaningful
# result on an ephemeral GitHub-hosted runner -- not merely inconvenient to
# run there. Each entry is the ci-lint recipe's own `failed="$$failed <slug>"`
# tag, so the mapping to a specific guard is unambiguous. Adding an entry
# here removes real CI coverage for that guard inside `make ci-lint`'s own
# CI invocation (develop-post-merge.yml) -- do it only when the guard is
# ALSO covered for real elsewhere in CI (see each reason below), never to
# quiet a guard that is merely awkward to satisfy on a runner.
RUNNER_INAPPLICABLE_GUARDS: dict[str, str] = {
    "agent-identity": (
        "agent-identity-check resolves the runner's own `git config user.*`, "
        "which an ephemeral runner does not have. Since #1558, an absent "
        "identity makes the check pass (audit_git_identity returns [] rather "
        "than fail); supplying a synthetic identity instead only swaps one "
        "always-passing input for another synthetic one that can never match "
        "a known agent identity either. Either way the check cannot fail on a "
        "runner, so it verifies nothing there -- see pr.yml's `code-lint` job, "
        "which already has no counterpart step for the same reason. "
        "agent-commit-range-check is the real merge-time control (it reads "
        "the commits the branch actually carries, not resolved config) and is "
        "never in this table."
    ),
    "skill-sync-check": (
        "skill-sync-check shells out to $(SKILL_SYNC), a local absolute "
        "developer path that does not exist on a runner; left ungated it "
        "hits the target's own 'not installed; skipping' branch and exits 0, "
        "reporting success while verifying nothing. The real CI-side "
        "skill-sync integrity check is pr.yml's `guard-skill-sync-verify` "
        "step, a pinned-SHA network checkout of the public skill-sync tool "
        "run against every PR before it can reach develop -- see "
        "docs/operations/ci-local-parity.md's 'Pinned skill-sync checkout "
        "verify' section for why that check has no local/ci-lint equivalent "
        "of its own."
    ),
}


def runs_on_runner(guard: str, *, github_actions: bool) -> tuple[bool, str | None]:
    """Return `(should_run, reason)` for *guard* under the given environment.

    `reason` is `None` whenever `should_run` is `True`. `github_actions=False`
    (the local / CI-local-parity case) always returns `(True, None)` -- this
    table only ever narrows CI-runner behavior, never local behavior, so a
    developer or `make pr-preflight` never sees a guard silently disappear.
    """
    if not github_actions:
        return True, None
    reason = RUNNER_INAPPLICABLE_GUARDS.get(guard)
    if reason is None:
        return True, None
    return False, reason


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("guard", help="ci-lint guard slug, e.g. 'agent-identity' or 'skill-sync-check'")
    args = parser.parse_args(argv)

    github_actions = os.environ.get("GITHUB_ACTIONS", "") == "true"
    should_run, reason = runs_on_runner(args.guard, github_actions=github_actions)
    if should_run:
        return 0
    print(f"SKIP {args.guard}: environment-inapplicable on a CI runner -- {reason}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
