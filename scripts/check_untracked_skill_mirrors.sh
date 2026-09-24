#!/bin/sh
# Untracked skill-mirror drift guard (cloud parity).
#
# The shared agents mirror and the curated-out `blog` skill are deliberately
# untracked: cloud is Claude-only and `blog` is published
# separately. `skill-sync verify` checks every selected skill's bytes against
# its target manifest, but it cannot tell a force-added (git-tracked) mirror
# from a legitimate local one — Git tracking state is outside what the
# manifest records. Fail the build if any deliberately-untracked path becomes
# git-tracked.
#
# Rationale: _project/decisions/claude-settings-cloud-ownership-2026-06-29.md
#
# Extracted verbatim (logic byte-equivalent) from the "Untracked skill-mirror
# drift guard (cloud parity)" step in the `code-lint` (pr.yml `lint` job) job
# so the same guard runs both in CI and locally via `make ci-lint` /
# `make pr-preflight` without drifting out of sync. See
# docs/operations/ci-local-parity.md for the parity invariant this guard is
# part of.
#
# The consolidated `.agents/skills` path is checked explicitly even though the
# broader `.agents/` rule also ignores it, so a force-added mirror is visible
# to this guard rather than hidden by the parent rule. The retired
# `.codex`/`.gemini` mirror paths are kept in the list so resurrecting one
# fails closed instead of silently reviving an unguarded surface.
#
# Run locally:
#   scripts/check_untracked_skill_mirrors.sh
set -eu

tracked=$(git ls-files -- \
  '.agents/skills' \
  '.codex/skills' '.codex/shared-skills' '.codex/shared-skills.lock.json' \
  '.gemini/skills' '.antigravity/skills' \
  '.claude/skills/blog')
if [ -n "$tracked" ]; then
  echo "ERROR: deliberately-untracked skill mirrors are now git-tracked:" >&2
  echo "$tracked" >&2
  echo "Untrack them with 'git rm --cached -r <path>' (regenerate locally via 'make skill-sync')." >&2
  exit 1
fi
