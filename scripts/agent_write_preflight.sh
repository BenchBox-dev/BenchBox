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

# A disposable clone -- a remote agent session, a CI runner -- is structurally
# identical to the maintainer's primary clone: both are plain clones, neither is
# a linked worktree. Nothing in the filesystem distinguishes them, so the
# session has to say so. What keeps that declaration from becoming another
# blanket override is that it is honored ONLY where the worktree pool this
# guard exists to protect is absent. On a machine running the pool,
# BENCHBOX_EPHEMERAL_CLONE cannot switch the guard off, so a session that
# declares it wrongly there still refuses.
pool_worktrees=$(git worktree list 2>/dev/null | wc -l | tr -d ' ')
pool_siblings=$(find "$(dirname "$top_abs")" -maxdepth 1 -name '*.pool-*' 2>/dev/null | wc -l | tr -d ' ')

ephemeral=no
if [ "${BENCHBOX_EPHEMERAL_CLONE:-}" = "1" ] &&
  [ "$pool_worktrees" -eq 1 ] &&
  [ "$pool_siblings" -eq 0 ]; then
  ephemeral=yes
fi

if [ "$top_abs" = "$primary_abs" ] && [ "$allow_main" != "1" ] && [ "$ephemeral" != "yes" ]; then
  cat >&2 <<EOF
Refusing BenchBox write preflight in the primary clone:
  $top_abs

Claim a pool worktree before write work:
  make worktree-claim BRANCH=fix/descriptive-slug
  cd <WORKTREE_PATH>

If this is instead a disposable, ephemeral clone with no canonical clone to
protect -- a remote agent session or a CI runner -- declare that:
  BENCHBOX_EPHEMERAL_CLONE=1 make agent-write-preflight
It is ignored wherever a worktree pool is present, so it cannot disable this
guard on a machine that uses one.

Read-only review/research may stay in the primary clone. Emergency main-clone
hotfix work requires explicit user authorization and:
  BENCHBOX_ALLOW_MAIN_CLONE_WRITE=1 make agent-write-preflight
EOF
  exit 1
fi

if [ "$ephemeral" = "yes" ]; then
  printf 'BenchBox write preflight OK (ephemeral clone, no worktree pool present): %s\n' "$top_abs"
else
  printf 'BenchBox write preflight OK: %s\n' "$top_abs"
fi
