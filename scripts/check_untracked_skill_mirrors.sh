#!/bin/sh
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
