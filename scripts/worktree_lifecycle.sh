#!/bin/sh
set -eu

# Keep user-controlled branch and path values in environment variables. This
# helper is called by Make without interpolating those values into a shell
# recipe, so punctuation in either value cannot become shell syntax.

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
operation=${1:-}

usage() {
  echo "Usage: $0 create|remove" >&2
  exit 1
}

die() {
  echo "$1" >&2
  exit 1
}

canonical_path() {
  input=$1
  case "$input" in
    /*) candidate=$input ;;
    *) candidate=$(pwd -P)/$input ;;
  esac

  if [ -e "$candidate" ] || [ -L "$candidate" ]; then
    realpath "$candidate"
    return
  fi

  case "$candidate" in
    */*) parent=${candidate%/*}; leaf=${candidate##*/} ;;
    *) parent=.; leaf=$candidate ;;
  esac
  [ -n "$leaf" ] && [ "$leaf" != "." ] && [ "$leaf" != ".." ] || die "Invalid worktree path: $input"
  [ -n "$parent" ] || parent=/
  parent=$(CDPATH= cd -- "$parent" 2>/dev/null && pwd -P) || die "Invalid worktree path: $input"
  printf '%s/%s\n' "$parent" "$leaf"
}

git_common_dir() {
  common_dir=$(git rev-parse --git-common-dir) || die "Not inside a Git repository"
  case "$common_dir" in
    /*) realpath "$common_dir" ;;
    *) realpath "$(git rev-parse --show-toplevel)/$common_dir" ;;
  esac
}

worktree_has_branch() {
  target=$1
  target_ref=refs/heads/$2
  git -C "$primary_clone" worktree list --porcelain | awk -v target="$target" -v target_ref="$target_ref" '
    function finish_block() {
      if (current == target && current_ref == target_ref) found = 1
    }
    /^worktree / {
      finish_block()
      current = substr($0, 10)
      current_ref = ""
      next
    }
    /^branch / { current_ref = substr($0, 8) }
    END {
      finish_block()
      exit(found ? 0 : 1)
    }
  '
}

rollback_started_creation() {
  [ "${creation_started:-no}" = yes ] || return 0
  worktree_has_branch "$worktree_path" "$branch" || return 0

  if git -C "$primary_clone" worktree remove --force "$worktree_path" >/dev/null 2>&1; then
    git -C "$primary_clone" branch -D "$branch" >/dev/null 2>&1 ||
      echo "Rollback warning: removed worktree but could not delete branch: $branch" >&2
  else
    echo "Rollback warning: could not remove created worktree: $worktree_path" >&2
  fi
}

on_exit() {
  status=$?
  trap - EXIT HUP INT TERM
  if [ "$status" -ne 0 ]; then
    rollback_started_creation
  fi
  exit "$status"
}

on_signal() {
  status=$1
  trap - EXIT HUP INT TERM
  rollback_started_creation
  exit "$status"
}

create_worktree() {
  branch=${BRANCH:-}
  worktree_input=${WORKTREE_PATH:-}
  [ -n "$branch" ] || die "Usage: make worktree-create BRANCH=<branch> WORKTREE_PATH=<path>"
  [ -n "$worktree_input" ] || die "Usage: make worktree-create BRANCH=<branch> WORKTREE_PATH=<path>"

  case "$branch" in
    develop|main|release) die "Refusing to create a worktree for protected branch: $branch" ;;
    chore/*|fix/*|feat/*|docs/*) ;;
    *) die "BRANCH must match ^(chore|fix|feat|docs)/.+" ;;
  esac
  git check-ref-format --branch "$branch" >/dev/null || die "Invalid git branch name: $branch"

  primary_clone=$(dirname "$(git_common_dir)")
  worktree_path=$(canonical_path "$worktree_input")

  if git show-ref --verify --quiet "refs/heads/$branch"; then
    die "Local branch already exists: $branch"
  fi
  remote_ref=$(git ls-remote --heads origin "$branch") || die "Could not verify remote branch: $branch"
  [ -z "$remote_ref" ] || die "Remote branch already exists: $branch"
  [ ! -e "$worktree_path" ] && [ ! -L "$worktree_path" ] || die "Worktree path already exists: $worktree_path"

  git fetch origin develop --quiet
  creation_started=yes
  trap on_exit EXIT
  trap 'on_signal 129' HUP
  trap 'on_signal 130' INT
  trap 'on_signal 143' TERM
  git worktree add -b "$branch" "$worktree_path" origin/develop
  "$script_dir/set_worktree_identity.sh" "$worktree_path"
  creation_started=no
  trap - EXIT HUP INT TERM
  printf 'WORKTREE_PATH=%s\n' "$(cd "$worktree_path" && pwd -P)"
}

worktree_state() {
  target=$1
  git worktree list --porcelain | awk -v target="$target" '
    function finish_block() {
      if (current == target && locked) target_locked = 1
    }
    /^worktree / {
      finish_block()
      current = substr($0, 10)
      locked = 0
      if (current == target) target_found = 1
      next
    }
    current == target && /^locked( |$)/ { locked = 1 }
    END {
      finish_block()
      if (!target_found) print "missing"
      else if (target_locked) print "locked"
      else print "registered"
    }
  '
}

remove_worktree() {
  worktree_input=${WORKTREE_PATH:-}
  [ -n "$worktree_input" ] || die "Usage: make worktree-remove WORKTREE_PATH=<path>"

  primary_clone=$(dirname "$(git_common_dir)")
  target=$(canonical_path "$worktree_input")
  primary_path=$(realpath "$primary_clone")
  [ "$target" != "$primary_path" ] || die "Refusing to remove the primary clone: $target"

  state=$(worktree_state "$target")
  case "$state" in
    missing) die "Refusing: path is not an exact registered worktree: $target" ;;
    locked) die "Refusing: worktree is locked; confirm the mount is inactive, then unlock it separately: $target" ;;
  esac
  [ -d "$target" ] || die "Refusing: registered worktree directory is missing: $target"
  git -C "$target" rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "Refusing: not a usable worktree: $target"
  git -C "$target" symbolic-ref -q HEAD >/dev/null 2>&1 || die "Refusing: worktree is detached: $target"

  dirty=$(git -C "$target" status --porcelain --untracked-files=all)
  if [ -n "$dirty" ]; then
    echo "Refusing to remove dirty worktree $target:" >&2
    echo "$dirty" >&2
    exit 1
  fi

  git -C "$primary_clone" worktree remove "$target"
  echo "Removed worktree: $target"
}

case "$operation" in
  create) create_worktree ;;
  remove) remove_worktree ;;
  *) usage ;;
esac
