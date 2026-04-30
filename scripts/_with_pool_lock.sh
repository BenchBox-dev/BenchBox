#!/bin/sh
# Acquire the pool file lock and exec a command under it. Used by every
# pool-mutating Make target (worktree-claim, worktree-release,
# worktree-pool-reset, worktree-pool-sweep-stale) so they all serialize
# against each other rather than only against worktree-claim.
#
# Usage: _with_pool_lock.sh <lock-path> <cmd> [args...]
#
# Selects lockf (macOS), flock (Linux), or scripts/_pool_lock.py
# (any platform with Python + uv) in that order. 30s timeout.

set -e

LOCK="$1"
if [ -z "$LOCK" ] || [ "$#" -lt 2 ]; then
  echo "Usage: $0 <lock-path> <cmd> [args...]" >&2
  exit 64
fi
shift

mkdir -p "$(dirname "$LOCK")"
touch "$LOCK"

if command -v lockf >/dev/null 2>&1; then
  exec lockf -t 30 "$LOCK" "$@"
elif command -v flock >/dev/null 2>&1; then
  exec flock -w 30 "$LOCK" "$@"
else
  exec uv run -- python scripts/_pool_lock.py "$LOCK" "$@"
fi
