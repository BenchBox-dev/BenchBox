# Disposable linked worktree lifecycle.
#
# Worktree paths are caller-owned. There is no retained slot allocator,
# reset/reuse path, global lock, or automatic branch cleanup. User-provided
# values are exported to the helper instead of interpolated into a shell
# recipe.

# Freeze raw command-line values into simply-expanded variables before GNU
# Make exports command-line overrides to recipes. The `value` function prevents
# Make expressions in user input from running; `override` changes their flavor
# from recursive to simple so later environment construction cannot re-expand
# the raw text.
override BRANCH := $(value BRANCH)
override WORKTREE_PATH := $(value WORKTREE_PATH)

worktree-create: export BRANCH := $(BRANCH)
worktree-create: export WORKTREE_PATH := $(WORKTREE_PATH)
worktree-create:
	@$(BENCHBOX_MAKEFILE_ROOT)scripts/worktree_lifecycle.sh create

worktree-remove: export WORKTREE_PATH := $(WORKTREE_PATH)
worktree-remove:
	@$(BENCHBOX_MAKEFILE_ROOT)scripts/worktree_lifecycle.sh remove

worktree-list:
	@git worktree list --porcelain
