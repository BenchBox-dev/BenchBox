#!/bin/sh
set -eu

# BenchBox-local guard for agent write sessions. It intentionally does not
# encode a global preference: it only protects this repository's primary clone.

top=$(git rev-parse --show-toplevel)
common_dir=$(git rev-parse --git-common-dir)
git_dir_abs=$(git rev-parse --absolute-git-dir)

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
# session has to say so. Keep that declaration explicit and reserve it for
# disposable remote/CI clones; normal local agents use linked worktrees.
registered_worktrees=$(git worktree list 2>/dev/null | wc -l | tr -d ' ')

ephemeral=no
if [ "${BENCHBOX_EPHEMERAL_CLONE:-}" = "1" ] && [ "$registered_worktrees" -eq 1 ]; then
  ephemeral=yes
fi

if [ "$top_abs" -ef "$primary_abs" ] && [ "$allow_main" != "1" ] && [ "$ephemeral" != "yes" ]; then
  cat >&2 <<EOF
Refusing BenchBox write preflight in the primary clone:
  $top_abs

Create a disposable worktree before write work:
  make worktree-create BRANCH=fix/descriptive-slug WORKTREE_PATH=../BenchBox.wt-fix-descriptive-slug
  cd <WORKTREE_PATH>

If this is instead a disposable, ephemeral clone with no canonical clone to
protect -- a remote agent session or a CI runner -- declare that:
  BENCHBOX_EPHEMERAL_CLONE=1 make agent-write-preflight
Normal local agent sessions must use a linked worktree.

Read-only review/research may stay in the primary clone. Emergency main-clone
hotfix work requires explicit user authorization and:
  BENCHBOX_ALLOW_MAIN_CLONE_WRITE=1 make agent-write-preflight
EOF
  exit 1
fi

if [ "$allow_main" != "1" ] && [ "$ephemeral" != "yes" ] && [ "$git_dir_abs" -ef "$common_abs" ]; then
  cat >&2 <<EOF
Refusing BenchBox write preflight: this is a plain clone, not a registered
linked worktree.

Create a disposable worktree before write work:
  make worktree-create BRANCH=fix/descriptive-slug WORKTREE_PATH=../BenchBox.wt-fix-descriptive-slug
  cd <WORKTREE_PATH>
EOF
  exit 1
fi

# [COMMIT-IDENTITY-001] Claim-time identity assertion.
#
# Linked worktrees share the primary clone's config, so a single stray [user]
# block there silently reauthors every linked worktree at once. Catching it at
# preflight time -- before a session acquires write rights -- is the only point
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

# Commit-time hooks live in the common Git directory, so every linked worktree
# shares one set. `pre-commit install` records the absolute path of whichever
# interpreter ran it, so installing from a worktree pins the shared hooks to a
# directory that is later deleted -- and commits then fail in every worktree at
# once. Presence is therefore not health: check that the recorded interpreter
# still resolves, and always repair from the primary clone, never from the
# caller's worktree. Repair is best-effort: CI re-runs the same guards, so a
# failure to install is a warning rather than a refusal.
hook_path="$common_abs/hooks/pre-commit"

hooks_usable=no
hook_reason="no pre-commit hook is installed"
if [ -e "$hook_path" ]; then
  # A hook pre-commit did not generate has no INSTALL_PYTHON line; leave it be.
  hook_interpreter=$(sed -n 's/^INSTALL_PYTHON=//p' "$hook_path" | head -n 1)
  if [ -z "$hook_interpreter" ] || [ -x "$hook_interpreter" ]; then
    hooks_usable=yes
  else
    hook_reason="its recorded interpreter is gone ($hook_interpreter)"
  fi
fi

if [ "$hooks_usable" != yes ]; then
  # Hook types come from default_install_hook_types in .pre-commit-config.yaml,
  # so all configured stages stay in sync.
  if (cd "$primary_abs" && uv run -- pre-commit install >/dev/null 2>&1); then
    printf 'Repaired commit-time hooks from %s (%s).\n' "$primary_abs" "$hook_reason"
  else
    echo "note: pre-commit install failed/unavailable; commit-time guards will not run here (CI still enforces them)" >&2
  fi
fi

if [ "$ephemeral" = "yes" ]; then
  printf 'BenchBox write preflight OK (ephemeral clone): %s\n' "$top_abs"
else
  printf 'BenchBox write preflight OK: %s\n' "$top_abs"
fi
