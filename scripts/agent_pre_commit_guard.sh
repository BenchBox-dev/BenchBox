#!/bin/sh
set -eu

# The linked-worktree guard is an agent-session safeguard. Git hooks cannot
# reliably distinguish an agent using a human Git identity from a human
# contributor, so an unmarked primary-clone commit must fail closed. Humans
# who have explicitly authorized a primary-clone commit may use the same
# declaration accepted by agent_write_preflight.sh; linked worktrees need no
# declaration.
configured=$(git config --bool --get benchbox.agent-write-preflight 2>/dev/null || true)
if [ "$configured" = "true" ] || [ "${BENCHBOX_AGENT_SESSION:-}" = "1" ]; then
  exec sh scripts/agent_write_preflight.sh
fi

allow_main=${BENCHBOX_ALLOW_MAIN_CLONE_WRITE:-${ALLOW_MAIN_CLONE_WRITE:-}}
if [ "$allow_main" = "1" ] || [ "${BENCHBOX_EPHEMERAL_CLONE:-}" = "1" ]; then
  exit 0
fi

exec sh scripts/agent_write_preflight.sh
