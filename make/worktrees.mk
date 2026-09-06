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
override CONTROLLER_KIND := $(value CONTROLLER_KIND)
override CONTROLLER_ID := $(value CONTROLLER_ID)
override EXPECTED_HEAD_OID := $(value EXPECTED_HEAD_OID)
override FORMAT := $(value FORMAT)

worktree-create: export BRANCH := $(BRANCH)
worktree-create: export WORKTREE_PATH := $(WORKTREE_PATH)
worktree-create: export CONTROLLER_KIND := $(CONTROLLER_KIND)
worktree-create: export CONTROLLER_ID := $(CONTROLLER_ID)
worktree-create:
	@$(BENCHBOX_MAKEFILE_ROOT)scripts/worktree_lifecycle.sh create

worktree-remove: export WORKTREE_PATH := $(WORKTREE_PATH)
worktree-remove:
	@$(BENCHBOX_MAKEFILE_ROOT)scripts/worktree_lifecycle.sh remove

worktree-release: export WORKTREE_PATH := $(WORKTREE_PATH)
worktree-release:
	@$(BENCHBOX_MAKEFILE_ROOT)scripts/worktree_lifecycle.sh release

worktree-finish: export WORKTREE_PATH := $(WORKTREE_PATH)
worktree-finish: export EXPECTED_HEAD_OID := $(EXPECTED_HEAD_OID)
worktree-finish: export FORMAT := $(FORMAT)
worktree-finish:
	@$(BENCHBOX_MAKEFILE_ROOT)scripts/worktree_lifecycle.sh finish

worktree-list:
	@git worktree list --porcelain
