#!/bin/sh
# Untracked skill-mirror drift guard (cloud parity).
#
# The codex/gemini/antigravity mirrors and the curated-out `blog` skill are
# deliberately untracked: cloud is Claude-only and `blog` is published
# separately. `skill-sync verify` only inspects the tracked `claude` target
# (it skips untracked targets and `ignore`d paths), so it cannot catch these
# being force-added. Fail the build if any become git-tracked.
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
# Run locally:
#   scripts/check_untracked_skill_mirrors.sh
set -eu

tracked=$(git ls-files -- \
  '.codex/skills' '.codex/shared-skills' '.codex/shared-skills.lock.json' \
  '.gemini/skills' '.antigravity/skills' \
  '.claude/skills/blog')
if [ -n "$tracked" ]; then
  echo "ERROR: deliberately-untracked skill mirrors are now git-tracked:" >&2
  echo "$tracked" >&2
  echo "Untrack them with 'git rm --cached -r <path>' (regenerate locally via 'make skill-sync')." >&2
  exit 1
fi
