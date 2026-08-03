#!/bin/sh
set -eu

# [COMMIT-IDENTITY-001] commit-msg gate: reject agent/service attribution
# trailers.
#
# This rejects rather than rewrites. CLAUDE.md requires that project hooks not
# silently mutate files, and a hook that quietly edited the commit message would
# also hide the fact that something upstream keeps adding the trailer. Failing
# loudly keeps the cause visible.
#
# Agent harnesses commonly append these trailers by default, so the offending
# text is usually a message convention rather than a deliberate act. AGENTS.md
# allows the trailer only when the current task explicitly requested that exact
# trailer; that case declares itself with BENCHBOX_ALLOW_AGENT_COAUTHOR=1.

message_file=${1:-}
if [ -z "$message_file" ] || [ ! -f "$message_file" ]; then
  echo "check_agent_trailers: expected a commit message file argument" >&2
  exit 2
fi

if [ "${BENCHBOX_ALLOW_AGENT_COAUTHOR:-}" = "1" ]; then
  exit 0
fi

# Comment lines never survive into the stored message, so ignore them; a commit
# template mentioning the trailer must not fail the commit.
body=$(grep -v '^[ \t]*#' "$message_file" || true)

coauthor=$(printf '%s\n' "$body" |
  grep -inE '^[ \t]*co-authored-by:.*(noreply@anthropic\.com|noreply@openai\.com)' || true)
session=$(printf '%s\n' "$body" |
  grep -inE '^[ \t]*(claude|codex|gemini|chatgpt)-session:' || true)

if [ -z "$coauthor" ] && [ -z "$session" ]; then
  exit 0
fi

{
  echo "Refusing commit: message carries agent/service attribution."
  echo
  [ -n "$coauthor" ] && printf '%s\n' "$coauthor" | sed 's/^/  /'
  [ -n "$session" ] && printf '%s\n' "$session" | sed 's/^/  /'
  echo
  echo "[COMMIT-IDENTITY-001] forbids an agent Co-Authored-By trailer, or any"
  echo "equivalent attribution, unless the current task explicitly requested that"
  echo "exact trailer. A tool convention is not authorization."
  echo
  echo "Remove the trailer, or -- if the task did request it -- declare that:"
  echo "  BENCHBOX_ALLOW_AGENT_COAUTHOR=1 git commit ..."
} >&2

exit 1
