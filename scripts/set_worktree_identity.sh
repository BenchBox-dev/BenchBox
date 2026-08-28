#!/bin/sh
set -eu

# [COMMIT-IDENTITY-001] Claim-time PREVENTION for shared-clone identity drift.
#
# `make agent-write-preflight` detects a contaminated identity, and
# `agent_instruction_audit.py` warns about one. Both act after the fact. This
# acts before: it pins the human identity to the new linked worktree so a later
# write to the shared config cannot reauthor work done here.
#
# Why worktree scope is the fix. Linked worktrees share the primary clone's
# config, and from inside one of them `git config user.email X` (no --global)
# writes to that COMMON config -- which is exactly the defect this repairs: one
# such write reauthors the primary clone and every linked worktree at once.
# Git's precedence is worktree > local > global, so a value written with
# `--worktree` keeps resolving here no matter what later lands in the common
# config. Measured: with a worktree override in place, re-contaminating the
# common config leaves this worktree resolving the human identity, while a
# sibling worktree without the override goes agent. That is why this must run
# per worktree, at creation time.
#
# This never writes user.* to the common config. `extensions.worktreeConfig` is
# the one common-config key it sets, because `--worktree` is inert without it;
# it is not an identity value and carries no authorship.

worktree=${1:-$(pwd)}

git_wt() {
  git -C "$worktree" "$@"
}

# Read the identity the human actually owns. Global/system scope only: reading
# the resolved value would happily echo back a contaminated common config and
# pin the contamination into worktree scope, which is the one outcome worse
# than doing nothing.
name=$(git_wt config --global --includes --get user.name 2>/dev/null || true)
email=$(git_wt config --global --includes --get user.email 2>/dev/null || true)

if [ -z "$name" ] || [ -z "$email" ]; then
  cat >&2 <<EOF
Refusing to set worktree identity: no global Git identity to pin.

  user.name:  ${name:-<unset>}
  user.email: ${email:-<unset>}

Set the human identity globally first, so every worktree inherits it:
  git config --global user.name "Your Name"
  git config --global user.email "you@example.com"
EOF
  exit 1
fi

# Keep these lists in sync with AGENT_NAMES / AGENT_EMAILS in
# _project/scripts/agent_instruction_audit.py and the same case arms in
# scripts/agent_write_preflight.sh.
lower_name=$(printf '%s' "$name" | tr 'A-Z' 'a-z')
lower_email=$(printf '%s' "$email" | tr 'A-Z' 'a-z')

agent_identity=no
case "$lower_email" in
  noreply@anthropic.com | noreply@openai.com) agent_identity=yes ;;
esac
case "$lower_name" in
  chatgpt | claude | codex | gemini | openai) agent_identity=yes ;;
esac

if [ "$agent_identity" = yes ]; then
  cat >&2 <<EOF
Refusing to set worktree identity: the global Git identity is a known
agent/service identity.

  $name <$email>

Pinning it into worktree scope would make the misattribution durable and
survive repair of the shared config -- the opposite of this guard's purpose.
Restore the human global identity, then re-run:
  make worktree-create BRANCH=fix/descriptive-slug WORKTREE_PATH=../BenchBox.wt-fix-descriptive-slug

For a single commit that an authorized task explicitly wants attributed
elsewhere, pass the identity per command instead:
  git -c user.name=... -c user.email=... commit
EOF
  exit 1
fi

# `--worktree` is inert unless the extension is enabled in the common config.
# Idempotent, and not an identity value.
if [ "$(git_wt config --get extensions.worktreeConfig 2>/dev/null || true)" != "true" ]; then
  git_wt config extensions.worktreeConfig true
fi

# Mark worktrees created through the agent-safe lifecycle so the pre-commit
# hook applies the location guard there while leaving normal human commits in
# the primary clone alone.
git_wt config --worktree benchbox.agent-write-preflight true

# Enabling the extension moves any pre-existing common-config [user] block out
# of this worktree's precedence path only if we write our own. Write both keys
# unconditionally-but-idempotently so a partially-set worktree converges.
current_name=$(git_wt config --worktree --get user.name 2>/dev/null || true)
current_email=$(git_wt config --worktree --get user.email 2>/dev/null || true)

changed=no
if [ "$current_name" != "$name" ]; then
  git_wt config --worktree user.name "$name"
  changed=yes
fi
if [ "$current_email" != "$email" ]; then
  git_wt config --worktree user.email "$email"
  changed=yes
fi

if [ "$changed" = yes ]; then
  printf 'Pinned worktree Git identity: %s <%s>\n' "$name" "$email"
else
  printf 'Worktree Git identity already pinned: %s <%s>\n' "$name" "$email"
fi
