#!/bin/sh
set -eu

message_file=${1:-}
if [ -z "$message_file" ] || [ ! -f "$message_file" ]; then
  echo "check_agent_trailers: expected a commit message file argument" >&2
  exit 2
fi

if [ "${BENCHBOX_ALLOW_AGENT_COAUTHOR:-}" = "1" ]; then
  exit 0
fi

body=$(grep -v '^[ \t]*#' "$message_file" || true)

coauthor=$(printf '%s\n' "$body" |
  grep -inE '^[ \t]*co-authored-by:(.*(noreply@anthropic\.com|noreply@openai\.com)|[ \t]*(chatgpt|claude|codex|gemini|openai)[ \t]*<)' || true)
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
