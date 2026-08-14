#!/bin/sh
set -eu

# The linked-worktree guard is an agent-session safeguard. A human contributor
# may intentionally commit from the primary clone, so the pre-commit hook must
# not apply the agent-only location policy unconditionally.
configured=$(git config --bool --get benchbox.agent-write-preflight 2>/dev/null || true)
if [ "$configured" = "true" ] || [ "${BENCHBOX_AGENT_SESSION:-}" = "1" ]; then
  exec sh scripts/agent_write_preflight.sh
fi

exit 0
