#!/bin/sh
set -eu

worktree=${1:-$(pwd)}

git_wt() {
  git -C "$worktree" "$@"
}

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

if [ "$(git_wt config --get extensions.worktreeConfig 2>/dev/null || true)" != "true" ]; then
  git_wt config extensions.worktreeConfig true
fi

git_wt config --worktree benchbox.agent-write-preflight true

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
