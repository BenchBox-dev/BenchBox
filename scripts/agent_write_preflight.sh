#!/bin/sh
set -eu

# BenchBox-local guard for agent write sessions. It intentionally does not
# encode a global preference: it only protects this repository's primary clone.

top=$(git rev-parse --show-toplevel)
common_dir=$(git rev-parse --git-common-dir)

case "$common_dir" in
  /*) common_abs=$(realpath "$common_dir") ;;
  *) common_abs=$(cd "$top" && realpath "$common_dir") ;;
esac

primary_clone=${BENCHBOX_AGENT_PRIMARY_CLONE:-$(dirname "$common_abs")}
top_abs=$(realpath "$top")
primary_abs=$(realpath "$primary_clone")

allow_main=${BENCHBOX_ALLOW_MAIN_CLONE_WRITE:-${ALLOW_MAIN_CLONE_WRITE:-}}

if [ "$top_abs" = "$primary_abs" ] && [ "$allow_main" != "1" ]; then
  cat >&2 <<EOF
Refusing BenchBox write preflight in the primary clone:
  $top_abs

Claim a pool worktree before write work:
  make worktree-claim BRANCH=fix/descriptive-slug
  cd <WORKTREE_PATH>

Read-only review/research may stay in the primary clone. Emergency main-clone
hotfix work requires explicit user authorization and:
  BENCHBOX_ALLOW_MAIN_CLONE_WRITE=1 make agent-write-preflight
EOF
  exit 1
fi

printf 'BenchBox write preflight OK: %s\n' "$top_abs"
