#!/bin/sh
# Select an exact develop commit for a new cut, or resume its uncommitted branch.
set -eu

version=${1:?Usage: release_cut_start.sh X.Y.Z}
if ! printf '%s\n' "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.+-]+)?$'; then
  echo "Error: VERSION must be X.Y.Z with an optional release suffix." >&2
  exit 1
fi
branch="v$version"
current=$(git symbolic-ref --quiet --short HEAD) || {
  echo "Error: release-cut requires a named branch." >&2
  exit 1
}

git_dir=$(git rev-parse --absolute-git-dir)
common_dir=$(git rev-parse --git-common-dir)
if [ "$git_dir" -ef "$common_dir" ]; then
  echo "Error: release-cut requires a linked worktree, not the primary clone." >&2
  exit 1
fi

# Fetch before comparing heads. This also refreshes origin/release for the
# changelog and alignment merge later in release-cut.
git fetch origin
remote_branch=$(git ls-remote --heads origin "refs/heads/$branch")
remote_tag=$(git ls-remote --tags origin "refs/tags/$branch")

if [ "$current" = "$branch" ]; then
  if git log --first-parent --format=%s origin/develop..HEAD | grep -Fxq "Release $branch"; then
    echo "Error: $branch already carries its release commit; nothing left to resume." >&2
    exit 1
  fi
  if ! git merge-base --is-ancestor HEAD origin/develop; then
    echo "Error: $branch has commits outside fetched origin/develop; inspect it before resuming." >&2
    exit 1
  fi
  if [ -n "$remote_branch" ] || [ -n "$remote_tag" ]; then
    echo "Error: $branch already exists on origin; inspect the pushed cut before resuming." >&2
    exit 1
  fi
  echo "==> Resuming interrupted cut on $branch"
  exit 0
fi

case "$current" in
  v*) echo "Error: another release branch is checked out: $current" >&2; exit 1 ;;
esac

if [ -n "$(git status --porcelain)" ]; then
  echo "Error: working tree must be clean before a new release cut." >&2
  exit 1
fi

head=$(git rev-parse HEAD)
develop=$(git rev-parse 'origin/develop^{commit}')
if [ "$head" != "$develop" ]; then
  echo "Error: HEAD $head differs from fetched origin/develop $develop." >&2
  exit 1
fi

if git show-ref --verify --quiet "refs/heads/$branch"; then
  echo "Error: local branch $branch already exists; inspect it before retrying." >&2
  exit 1
fi
if git show-ref --verify --quiet "refs/tags/$branch"; then
  echo "Error: local tag $branch already exists; inspect it before retrying." >&2
  exit 1
fi
if [ -n "$remote_branch" ] || [ -n "$remote_tag" ]; then
  echo "Error: $branch already exists on origin as a branch or tag; decide its disposition before cutting." >&2
  exit 1
fi

git switch -c "$branch" "$develop"
