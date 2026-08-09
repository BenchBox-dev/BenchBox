# Initialize retained pool worktrees. Existing pool-NN paths are left untouched.
worktree-pool-init:
	@git fetch origin develop --quiet
	@set -e; \
	POOL_REPO=$$($(POOL_REPO_CMD)); \
	i=1; \
	while [ "$$i" -le "$(POOL_SIZE)" ]; do \
		pool=$$(printf 'pool-%02d' "$$i"); \
		wt="$(WORKTREE_POOL_PARENT)/$$POOL_REPO.$$pool"; \
		if [ -e "$$wt" ]; then \
			git -C "$$wt" rev-parse --is-inside-work-tree >/dev/null 2>&1 || { \
				echo "Path exists but is not a git worktree: $$wt" >&2; \
				exit 1; \
			}; \
			echo "$$pool exists: $$wt"; \
		else \
			echo "$$pool create: $$wt"; \
			git worktree add --detach "$$wt" origin/develop; \
			( cd "$$wt" && uv sync --group dev && uv run -- pre-commit install ); \
		fi; \
		i=$$((i + 1)); \
	done
	@POOL_REPO=$$($(POOL_REPO_CMD)); \
	printf '%-8s | %-60s | %s\n' "pool" "path" "branch"; \
	i=1; \
	while [ "$$i" -le "$(POOL_SIZE)" ]; do \
		pool=$$(printf 'pool-%02d' "$$i"); \
		wt="$(WORKTREE_POOL_PARENT)/$$POOL_REPO.$$pool"; \
		if [ -d "$$wt/.git" ] || git -C "$$wt" rev-parse --is-inside-work-tree >/dev/null 2>&1; then \
			branch=$$(git -C "$$wt" branch --show-current 2>/dev/null); \
			[ -n "$$branch" ] || branch="(detached)"; \
		else \
			branch="(missing)"; \
		fi; \
		printf '%-8s | %-60s | %s\n' "$$pool" "$$wt" "$$branch"; \
		i=$$((i + 1)); \
	done

# Claim the first free pool worktree for a feature branch.
#
# Concurrency: every pool-mutating target (claim, release, pool-reset,
# pool-sweep-stale) acquires the same `.git/pool.lock` via
# scripts/_with_pool_lock.sh. They serialize against each other so
# concurrent operations cannot leave a slot in a torn state. The lock
# does NOT cover read-only inspection (worktree-pool-status), which is
# safe to run anytime.
worktree-claim:
	@test -n "$(BRANCH)" || { echo "Usage: make worktree-claim BRANCH=<branch-name>"; exit 1; }
	@case "$(BRANCH)" in chore/?*|fix/?*|feat/?*|docs/?*) ;; *) echo "BRANCH must match ^(chore|fix|feat|docs)/.+"; exit 1 ;; esac
	@git check-ref-format --branch "$(BRANCH)" >/dev/null || { echo "Invalid git branch name: $(BRANCH)"; exit 1; }
	@if [ "$(POOL_MIN_FREE_KB)" -gt 0 ]; then \
		FREE_KB=$$(df -k "$(WORKTREE_POOL_PARENT)" 2>/dev/null | awk 'NR==2 {print $$4}'); \
		if [ -n "$$FREE_KB" ] && [ "$$FREE_KB" -lt "$(POOL_MIN_FREE_KB)" ]; then \
			echo "Refusing to claim: $$FREE_KB KB free on $(WORKTREE_POOL_PARENT) < $(POOL_MIN_FREE_KB) KB required." >&2; \
			echo "Hint: run \`make worktree-pool-disk-clean\` to drop pytest/coverage caches," >&2; \
			echo "      or override with \`POOL_MIN_FREE_KB=0 make worktree-claim BRANCH=...\`." >&2; \
			exit 1; \
		fi; \
	fi
	@git fetch origin develop --quiet
	@LOCK="$$(realpath "$$(git rev-parse --git-common-dir)")/pool.lock"; \
	scripts/_with_pool_lock.sh "$$LOCK" $(MAKE) -s worktree-claim-locked BRANCH="$(BRANCH)" POOL_SIZE="$(POOL_SIZE)" WORKTREE_POOL_PARENT="$(WORKTREE_POOL_PARENT)"

# Orchestrator: try once, then auto-sweep stale slots, then try again.
# The auto-sweep means routine pool exhaustion (forgotten releases) is
# self-healing without operator intervention.
#
# The whole recipe runs in ONE shell (line continuations + a single `@`).
# Each `@`-prefixed make recipe line otherwise spawns its own subshell, so
# `if ... ; then exit 0; fi` would only exit that line's subshell — make
# would happily continue to the auto-sweep retry path even after a
# successful first attempt, falsely reporting failure to the caller.
worktree-claim-locked:
	@if $(MAKE) -s worktree-claim-attempt BRANCH="$(BRANCH)" POOL_SIZE="$(POOL_SIZE)" WORKTREE_POOL_PARENT="$(WORKTREE_POOL_PARENT)"; then \
		exit 0; \
	fi; \
	echo "No free pool worktree on first pass — auto-sweeping stale slots..." >&2; \
	$(MAKE) -s worktree-pool-sweep-stale-locked POOL_SIZE="$(POOL_SIZE)" WORKTREE_POOL_PARENT="$(WORKTREE_POOL_PARENT)" >&2 || true; \
	if $(MAKE) -s worktree-claim-attempt BRANCH="$(BRANCH)" POOL_SIZE="$(POOL_SIZE)" WORKTREE_POOL_PARENT="$(WORKTREE_POOL_PARENT)"; then \
		exit 0; \
	fi; \
	echo "Still no free pool worktree available after auto-sweep." >&2; \
	echo "Hint: dirty or claim-aborted slots are not auto-recovered (they may have valuable state)." >&2; \
	echo "      Run \`make worktree-pool-status\` to inspect, then \`make worktree-pool-reset POOL=NN\`" >&2; \
	echo "      as a last-resort manual escape hatch after reviewing what will be discarded." >&2; \
	exit 1

# Single-pass claim attempt. Iterates the pool once; on the first
# detached, clean, non-claim-aborted slot, hard-resets it to
# origin/develop (scrubbing any residual INDEX/working-tree skew from
# an interrupted release or manual `git checkout`) and mutates it to
# the requested branch under an EXIT trap that rolls back on any failure
# (including SIGINT/SIGTERM). EXIT is POSIX (works in dash/sh/bash); ERR
# is not.
# A `.benchbox/claim_in_progress` marker is written before mutation and
# removed on success or rollback; if the process is SIGKILL'd between
# write and removal, the marker survives and `worktree-pool-status`
# reports the slot as `aborted` so the operator knows it needs reset.
#
# The `reset --hard` immediately before the final emptiness check is the
# hardening for a subtle prior bug: `git status --porcelain` could return
# empty on a slot whose INDEX still had stale staged entries from a
# previous tenant (when the stale blob coincidentally matched HEAD's blob
# for that path). The gate accepted the slot as "clean detached", but
# the resulting worktree carried the previous tenant's INDEX into the new
# branch. Resetting before the final emptiness check normalizes the slot.
#
# Ordering: a normal porcelain gate runs before mutation so dirty
# detached slots are preserved for manual recovery. The marker is then
# written BEFORE `reset --hard` so the EXIT trap can roll back a slot
# whose reset is interrupted mid-flight (SIGINT/SIGTERM during the reset
# would otherwise leave the slot in a partial state with no
# aborted-marker signal). Slots skipped by the post-reset porcelain
# check or a transient reset failure remove the marker before `continue`
# so the trap's cleanup does not target the wrong slot on a later
# iteration. The cleanup function itself runs an extra `reset --hard` so
# an interrupted reset is fully normalized.
worktree-claim-attempt:
	@set -e; \
	marker=""; wt=""; pool=""; claim_ok=0; \
	cleanup() { \
		trap '' INT TERM; \
		if [ "$$claim_ok" != "1" ] && [ -n "$$marker" ]; then \
			cleanup_marker="$$marker"; cleanup_wt="$$wt"; cleanup_pool="$$pool"; \
			marker=""; \
			rm -f "$$cleanup_marker"; \
			git -C "$$cleanup_wt" checkout --detach origin/develop >/dev/null 2>&1 || true; \
			git -C "$$cleanup_wt" reset --hard origin/develop >/dev/null 2>&1 || true; \
			git -C "$$cleanup_wt" branch -D "$(BRANCH)" >/dev/null 2>&1 || true; \
			echo "claim of $$cleanup_pool failed; slot returned to detached origin/develop" >&2; \
		fi; \
	}; \
	on_int() { cleanup; exit 130; }; \
	on_term() { cleanup; exit 143; }; \
	trap cleanup EXIT; \
	trap on_int INT; \
	trap on_term TERM; \
	POOL_REPO=$$($(POOL_REPO_CMD)); \
	i=1; \
	while [ "$$i" -le "$(POOL_SIZE)" ]; do \
		pool=$$(printf 'pool-%02d' "$$i"); \
		wt="$(WORKTREE_POOL_PARENT)/$$POOL_REPO.$$pool"; \
		i=$$((i + 1)); \
		git -C "$$wt" rev-parse --is-inside-work-tree >/dev/null 2>&1 || continue; \
		[ -f "$$wt/.benchbox/claim_in_progress" ] && continue; \
		branch=$$(git -C "$$wt" symbolic-ref -q --short HEAD 2>/dev/null || true); \
		[ -z "$$branch" ] || continue; \
		pre_status=$$(git -C "$$wt" status --porcelain --untracked-files=normal | grep -vE '^\?\? \.benchbox(/|$$)' || true); \
		if [ -n "$$pre_status" ]; then \
			echo "claim skip $$pool: porcelain non-empty before reset" >&2; \
			continue; \
		fi; \
		marker="$$wt/.benchbox/claim_in_progress"; \
		mkdir -p "$$wt/.benchbox"; \
		printf 'pid=%s started=%s branch=%s\n' "$$$$" "$$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(BRANCH)" > "$$marker"; \
		if ! git -C "$$wt" reset --hard origin/develop >/dev/null 2>&1; then \
			rm -f "$$marker"; marker=""; \
			echo "claim skip $$pool: reset --hard origin/develop failed" >&2; \
			continue; \
		fi; \
		status=$$(git -C "$$wt" status --porcelain --untracked-files=normal | grep -vE '^\?\? \.benchbox(/|$$)' || true); \
		if [ -n "$$status" ]; then \
			rm -f "$$marker"; marker=""; \
			echo "claim skip $$pool: post-reset porcelain non-empty (untracked residue)" >&2; \
			continue; \
		fi; \
		git -C "$$wt" checkout -b "$(BRANCH)" >/dev/null; \
		if [ ! -f "$$wt/.venv/pyvenv.cfg" ] \
			|| [ -n "$$(find "$$wt/uv.lock" "$$wt/pyproject.toml" -newer "$$wt/.venv/pyvenv.cfg" 2>/dev/null | head -n 1)" ]; then \
			( cd "$$wt" && uv sync --group dev >/dev/null ); \
		fi; \
		if [ -f "$$wt/.pre-commit-config.yaml" ]; then \
			( cd "$$wt" && uv run -- pre-commit install >/dev/null 2>&1 ) \
				|| echo "note: pre-commit install failed/unavailable in $$wt; codespell etc. won't run at commit time (run \`uv run -- pre-commit install\` manually)" >&2; \
		fi; \
		scripts/set_worktree_identity.sh "$$wt" >&2 \
			|| echo "note: could not pin worktree Git identity in $$wt; commits there resolve identity from the shared config (make agent-write-preflight still refuses an agent author)" >&2; \
		rm -f "$$marker"; \
		marker=""; \
		claim_ok=1; \
		printf 'WORKTREE_PATH=%s\n' "$$(cd "$$wt" && pwd -P)"; \
		exit 0; \
	done; \
	exit 1

worktree-release:
	@top=$$(git rev-parse --show-toplevel); \
	case "$$top" in *.pool-[0-9][0-9]) ;; *) echo "Refusing: worktree-release must run inside a pool-NN worktree."; exit 1 ;; esac; \
	LOCK="$$(realpath "$$(git rev-parse --git-common-dir)")/pool.lock"; \
	scripts/_with_pool_lock.sh "$$LOCK" $(MAKE) -s worktree-release-locked FORCE="$(FORCE)"
