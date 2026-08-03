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

if [ "$top_abs" -ef "$primary_abs" ] && [ "$allow_main" != "1" ] && [ "$ephemeral" != "yes" ]; then
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

# [COMMIT-IDENTITY-001] Claim-time identity assertion.
#
# Linked worktrees share the primary clone's config, so a single stray [user]
# block there silently reauthors every pool worktree at once. Catching it at
# claim time -- the moment a session acquires write rights -- is the only point
# where one check covers every worktree before any commit exists. Keep the agent
# name/address lists in sync with AGENT_NAMES / AGENT_EMAILS and
# SIGNING_SERVICE_EMAILS in _project/scripts/agent_instruction_audit.py.
if [ "${BENCHBOX_ALLOW_AGENT_GIT_IDENTITY:-}" != "1" ]; then
  author_ident=$(git -C "$top_abs" var GIT_AUTHOR_IDENT 2>/dev/null || true)
  author_email=$(printf '%s' "$author_ident" | sed -n 's/^.*<\([^>]*\)>.*$/\1/p' | tr 'A-Z' 'a-z')
  author_name=$(printf '%s' "$author_ident" | sed -n 's/^\(.*\) <[^>]*>.*$/\1/p' | tr 'A-Z' 'a-z')

  agent_identity=no
  case "$author_email" in
    noreply@anthropic.com | noreply@openai.com) agent_identity=yes ;;
  esac
  case "$author_name" in
    chatgpt | claude | codex | gemini | openai) agent_identity=yes ;;
  esac

  if [ "$agent_identity" = yes ]; then
    origins=$(git -C "$top_abs" config --show-origin --get-regexp '^user\.(name|email)$' 2>/dev/null || true)
    cat >&2 <<EOF
Refusing BenchBox write preflight: Git author identity resolves to a known
agent/service identity.

  author:  $author_ident
  origins:
$(printf '%s\n' "${origins:-  <none>}" | sed 's/^/    /')

A repository-local value overrides the global identity but is not automatically
intentional, and every linked worktree inherits it. Set the human identity, or
-- if this task explicitly authorized the agent identity -- declare it:
  BENCHBOX_ALLOW_AGENT_GIT_IDENTITY=1 make agent-write-preflight

A commit-signing service may still hold the committer slot behind a human
author; only authorship is refused here.
EOF
    exit 1
  fi
fi

# An ephemeral clone never runs worktree-claim, which is where pool worktrees
# get their hooks, so the repo's commit-time gates would silently never fire
# here. Installing is best-effort: CI re-runs the same guards, so a failure to
# install is a warning rather than a refusal.
if [ "$ephemeral" = "yes" ] && [ ! -e "$common_abs/hooks/pre-commit" ]; then
  if (cd "$top_abs" && uv run -- pre-commit install --hook-type pre-commit --hook-type commit-msg >/dev/null 2>&1); then
    printf 'Installed pre-commit hooks (ephemeral clone had none).\n'
  else
    echo "note: pre-commit install failed/unavailable; commit-time guards will not run here (CI still enforces them)" >&2
  fi
fi

if [ "$ephemeral" = "yes" ]; then
  printf 'BenchBox write preflight OK (ephemeral clone, no worktree pool present): %s\n' "$top_abs"
else
  printf 'BenchBox write preflight OK: %s\n' "$top_abs"
fi
