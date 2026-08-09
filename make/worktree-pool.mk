## worktree-pool-status: report pool slot state + venv health + disk usage.
##
## Columns:
##   pool, path, branch, state, claim_age, venv, size
##
## State semantics:
##   free     — detached HEAD, working tree clean
##   claimed  — on a feature branch, no PR or PR is open
##   stale    — on a feature branch, PR is MERGED (release/sweep candidate)
##   dirty    — uncommitted changes (filtered against .benchbox/ scratch
##              dir which is the only expected non-ignored untracked path;
##              .venv/ is .gitignored, so it does not appear in --untracked-files=normal)
##   aborted  — `.benchbox/claim_in_progress` marker survived from a
##              previous claim that was SIGKILL'd or otherwise died
##              before its trap could clean up. Run pool-reset to recover.
##   unknown  — gh pr view/list lookup failed (auth / network / rate limit)
##              — distinguished from claimed-no-PR-yet
##   missing  — pool slot directory absent
##
## Venv health:
##   ok           — .venv/pyvenv.cfg exists and is at least as new as uv.lock + pyproject.toml
##   stale        — .venv exists but uv.lock or pyproject.toml is newer (next claim will re-sync)
##   missing      — .venv absent (claim will recreate; expected for free
##                  slots, since release/sweep clears `.venv/`)
##
## PR-state lookup is batched: a single `gh pr list --state all` runs up
## front and an associative awk lookup per slot replaces N per-slot
## `gh pr view` calls. The bulk window is bumped to 1000 (gh's
## effective max for one page); for any pool branch whose PR falls
## outside the window, a per-branch `gh pr view` fallback fills in the
## state so long-lived stale slots don't get misclassified as `claimed`.
worktree-pool-status:
	@POOL_REPO=$$($(POOL_REPO_CMD)); \
	pr_table=$$(gh pr list --state all --base develop --limit 1000 \
		--json headRefName,state \
		--template '{{range .}}{{.headRefName}}{{"\t"}}{{.state}}{{"\n"}}{{end}}' 2>/dev/null); \
	pr_lookup_failed=0; \
	if [ -z "$$pr_table" ]; then pr_lookup_failed=1; fi; \
	printf '%-8s | %-58s | %-28s | %-8s | %-13s | %-7s | %s\n' "pool" "path" "branch" "state" "claim_age" "venv" "size"; \
	i=1; \
	while [ "$$i" -le "$(POOL_SIZE)" ]; do \
		pool=$$(printf 'pool-%02d' "$$i"); \
		wt="$(WORKTREE_POOL_PARENT)/$$POOL_REPO.$$pool"; \
		branch="-"; state="missing"; age="-"; venv="-"; size="-"; \
		if git -C "$$wt" rev-parse --is-inside-work-tree >/dev/null 2>&1; then \
			current=$$(git -C "$$wt" symbolic-ref -q --short HEAD 2>/dev/null || true); \
			dirty=$$(git -C "$$wt" status --porcelain --untracked-files=normal | grep -vE '^\?\? \.benchbox(/|$$)' || true); \
			aborted=0; \
			[ -f "$$wt/.benchbox/claim_in_progress" ] && aborted=1; \
			if [ ! -f "$$wt/.venv/pyvenv.cfg" ]; then \
				venv="missing"; \
			elif [ -n "$$(find "$$wt/uv.lock" "$$wt/pyproject.toml" -newer "$$wt/.venv/pyvenv.cfg" 2>/dev/null | head -n 1)" ]; then \
				venv="stale"; \
			else \
				venv="ok"; \
			fi; \
			size=$$(du -sh "$$wt" 2>/dev/null | awk '{print $$1}'); \
			[ -n "$$size" ] || size="-"; \
			if [ "$$aborted" = "1" ]; then \
				state="aborted"; \
				[ -n "$$current" ] && branch="$$current" || branch="(detached)"; \
				age=$$(git -C "$$wt" log -1 --format=%ar 2>/dev/null || echo "-"); \
			elif [ -z "$$current" ]; then \
				branch="(detached)"; \
				if [ -z "$$dirty" ]; then state="free"; else state="dirty"; fi; \
			else \
				branch="$$current"; \
				age=$$(git -C "$$wt" log -1 --format=%ar 2>/dev/null || echo "-"); \
				if [ -n "$$dirty" ]; then \
					state="dirty"; \
				else \
					pr_state=$$(printf '%s\n' "$$pr_table" | awk -F'\t' -v b="$$current" '$$1 == b {print $$2; exit}'); \
					if [ -z "$$pr_state" ] && [ "$$pr_lookup_failed" = "0" ]; then \
						pr_state=$$(gh pr view "$$current" --json state --jq .state 2>/dev/null || true); \
					fi; \
					if [ "$$pr_lookup_failed" = "1" ]; then \
						state="unknown"; \
					elif [ "$$pr_state" = "MERGED" ]; then \
						state="stale"; \
					else \
						state="claimed"; \
					fi; \
				fi; \
			fi; \
		fi; \
		printf '%-8s | %-58s | %-28s | %-8s | %-13s | %-7s | %s\n' "$$pool" "$$wt" "$$branch" "$$state" "$$age" "$$venv" "$$size"; \
		i=$$((i + 1)); \
	done; \
	if [ "$$pr_lookup_failed" = "1" ]; then \
		printf '\nNote: state=unknown — \`gh pr list\` returned no data.\n'; \
		printf '  Check \`gh auth status\` and \`gh api rate_limit\` to recover.\n'; \
	fi

## worktree-pool-check: assert pool invariants and exit non-zero on drift.
##
## Fails if:
##   - any slot directory is missing (count < POOL_SIZE)
##   - extra `pool-NN` directories exist beyond POOL_SIZE in WORKTREE_POOL_PARENT
##   - any slot is in `aborted` state (.benchbox/claim_in_progress survived)
##
## NOT a PR-CI gate. Intended use:
##   - pre-release sanity check (catch drift before cutting a release)
##   - periodic local cron / agent-loop hook
##
## Performance: avoids the gh PR lookup that worktree-pool-status uses, so
## it is fast and safe to run frequently. Runs read-only — never mutates.
##
## See `_project/blind-spots/2026-04-30-214358-pool-size-not-codified-as-contract.md`.
worktree-pool-check:
	@POOL_REPO=$$($(POOL_REPO_CMD)); \
	violations=""; \
	missing_count=0; \
	aborted_count=0; \
	i=1; \
	now_epoch=$$(date +%s); \
	while [ "$$i" -le "$(POOL_SIZE)" ]; do \
		pool=$$(printf 'pool-%02d' "$$i"); \
		wt="$(WORKTREE_POOL_PARENT)/$$POOL_REPO.$$pool"; \
		if ! git -C "$$wt" rev-parse --is-inside-work-tree >/dev/null 2>&1; then \
			violations="$$violations  - $$pool: missing ($$wt is not a git worktree)\n"; \
			missing_count=$$((missing_count + 1)); \
		elif [ -f "$$wt/.benchbox/claim_in_progress" ]; then \
			marker_mtime_epoch=$$(stat -c %Y "$$wt/.benchbox/claim_in_progress" 2>/dev/null || stat -f %m "$$wt/.benchbox/claim_in_progress" 2>/dev/null || echo 0); \
			case "$$marker_mtime_epoch" in ''|*[!0-9]*) marker_mtime_epoch=0 ;; esac; \
			marker_age_seconds=$$((now_epoch - marker_mtime_epoch)); \
			marker_age=$$(date -u -r "$$wt/.benchbox/claim_in_progress" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo "?"); \
			if [ "$$marker_age_seconds" -ge "$(POOL_CLAIM_MARKER_STALE_SECONDS)" ]; then \
				violations="$$violations  - $$pool: aborted (claim_in_progress marker present, mtime $$marker_age, age $${marker_age_seconds}s >= $(POOL_CLAIM_MARKER_STALE_SECONDS)s)\n"; \
				aborted_count=$$((aborted_count + 1)); \
			fi; \
		fi; \
		i=$$((i + 1)); \
	done; \
	extras=""; \
	for wt in "$(WORKTREE_POOL_PARENT)/$$POOL_REPO."pool-*; do \
		[ -d "$$wt" ] || continue; \
		base=$$(basename "$$wt"); \
		num=$${base##*pool-}; \
		case "$$num" in [0-9][0-9]) ;; *) continue ;; esac; \
		num_dec=$$(expr "$$num" + 0); \
		if [ "$$num_dec" -gt "$(POOL_SIZE)" ]; then \
			extras="$$extras  - $$base (number > POOL_SIZE=$(POOL_SIZE))\n"; \
		fi; \
	done; \
	if [ -n "$$extras" ]; then \
		violations="$$violations  Extra pool slots beyond POOL_SIZE:\n$$extras"; \
	fi; \
	if [ -n "$$violations" ]; then \
		printf 'Pool invariant check FAILED (POOL_SIZE=%s):\n' "$(POOL_SIZE)" >&2; \
		printf '%b' "$$violations" >&2; \
		printf 'Recover with `make worktree-pool-status` to inspect, then\n' >&2; \
		printf '`make worktree-pool-reset POOL=NN` (last resort) or\n' >&2; \
		printf '`make worktree-pool-init` to recreate missing slots.\n' >&2; \
		exit 1; \
	fi; \
	printf 'Pool invariant check OK: %d slot(s), no aborted markers.\n' "$(POOL_SIZE)"

## worktree-pool-reset POOL=NN [FORCE=1]: hard-reset a stuck pool slot to
## origin/develop. Without FORCE=1, refuses if the slot has uncommitted
## tracked changes. With FORCE=1, prompts for "RESET" then discards
## tracked changes AND scrubs untracked + ignored content (including
## `.venv/`, `benchmark_runs/`, build outputs) so the slot is reclaimed
## clean. The `.benchbox/` cache directory is preserved across reset.
## Use as an escape hatch when worktree-pool-sweep-stale won't release a
## slot (e.g., dirty working tree, no merged PR), or to reclaim disk
## from orphan benchmark output left by previous claims.
worktree-pool-reset:
	@test -n "$(POOL)" || { echo "Usage: make worktree-pool-reset POOL=NN"; exit 1; }
	@case "$(POOL)" in [0-9][0-9]) ;; *) echo "POOL must be two digits, e.g. POOL=03"; exit 1 ;; esac
	@LOCK="$$(realpath "$$(git rev-parse --git-common-dir)")/pool.lock"; \
	scripts/_with_pool_lock.sh "$$LOCK" $(MAKE) -s worktree-pool-reset-locked POOL="$(POOL)" FORCE="$(FORCE)" POOL_SIZE="$(POOL_SIZE)" WORKTREE_POOL_PARENT="$(WORKTREE_POOL_PARENT)"
