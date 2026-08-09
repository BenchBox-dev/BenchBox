## worktree-pool-sweep-stale: auto-release pool slots whose branch's PR
## is MERGED on origin and whose working tree is clean. Idempotent;
## refuses to touch slots that are dirty, claimed-no-PR, claimed-with-open-PR,
## or where the gh API lookup failed (state=unknown). Run after a busy day
## to recover slots that died between work and `make worktree-release`.
##
## Also drops `.venv/` from each released slot to free disk on inactive
## pool worktrees; the next `worktree-claim` re-syncs from `~/.cache/uv/`.
##
## Acquires the pool lock for the duration of the sweep so concurrent
## claims/releases cannot race with the per-slot reset operations.
worktree-pool-sweep-stale:
	@LOCK="$$(realpath "$$(git rev-parse --git-common-dir)")/pool.lock"; \
	scripts/_with_pool_lock.sh "$$LOCK" $(MAKE) -s worktree-pool-sweep-stale-locked POOL_SIZE="$(POOL_SIZE)" WORKTREE_POOL_PARENT="$(WORKTREE_POOL_PARENT)"

worktree-pool-sweep-stale-locked:
	@set -e; \
	POOL_REPO=$$($(POOL_REPO_CMD)); \
	pr_table=$$(gh pr list --state all --base develop --limit 1000 \
		--json headRefName,state \
		--template '{{range .}}{{.headRefName}}{{"\t"}}{{.state}}{{"\n"}}{{end}}' 2>/dev/null); \
	if [ -z "$$pr_table" ]; then \
		echo "gh pr list returned no data; refusing to sweep without PR-state visibility" >&2; \
		exit 1; \
	fi; \
	swept=0; \
	i=1; \
	while [ "$$i" -le "$(POOL_SIZE)" ]; do \
		pool=$$(printf 'pool-%02d' "$$i"); \
		wt="$(WORKTREE_POOL_PARENT)/$$POOL_REPO.$$pool"; \
		i=$$((i + 1)); \
		git -C "$$wt" rev-parse --is-inside-work-tree >/dev/null 2>&1 || continue; \
		current=$$(git -C "$$wt" symbolic-ref -q --short HEAD 2>/dev/null || true); \
		[ -n "$$current" ] || continue; \
		dirty=$$(git -C "$$wt" status --porcelain --untracked-files=normal | grep -vE '^\?\? \.benchbox(/|$$)' || true); \
		if [ -n "$$dirty" ]; then \
			echo "skip $$pool: dirty (branch=$$current)"; \
			continue; \
		fi; \
		pr_state=$$(printf '%s\n' "$$pr_table" | awk -F'\t' -v b="$$current" '$$1 == b {print $$2; exit}'); \
		if [ -z "$$pr_state" ]; then \
			pr_state=$$(gh pr view "$$current" --json state --jq .state 2>/dev/null || true); \
		fi; \
		if [ "$$pr_state" != "MERGED" ]; then \
			echo "skip $$pool: PR not merged (state=$${pr_state:-none})"; \
			continue; \
		fi; \
		echo "sweep $$pool: releasing $$current (PR MERGED)"; \
		git -C "$$wt" fetch origin develop --quiet; \
		git -C "$$wt" checkout --detach origin/develop >/dev/null; \
		git -C "$$wt" reset --hard origin/develop >/dev/null; \
		git -C "$$wt" branch -D "$$current" >/dev/null 2>&1 || true; \
		git -C "$$wt" remote prune origin >/dev/null 2>&1 || true; \
		rm -rf "$$wt/.venv"; \
		swept=$$((swept + 1)); \
	done; \
	echo "Swept $$swept pool slot(s)."

## worktree-pool-disk-clean: drop pytest, mypy, ruff, coverage caches
## from every pool slot without touching `.venv/` or git state. Useful
## when the pre-claim free-space check refuses or `worktree-pool-status`
## shows slots ballooning past their typical ~2 GB footprint.
##
## Lock-free by design: it only removes ignored cache directories, so
## it cannot corrupt git state or interfere with concurrent claim/release.
worktree-pool-disk-clean:
	@set -e; \
	POOL_REPO=$$($(POOL_REPO_CMD)); \
	freed_total=0; \
	cleaned=0; \
	i=1; \
	while [ "$$i" -le "$(POOL_SIZE)" ]; do \
		pool=$$(printf 'pool-%02d' "$$i"); \
		wt="$(WORKTREE_POOL_PARENT)/$$POOL_REPO.$$pool"; \
		i=$$((i + 1)); \
		[ -d "$$wt" ] || continue; \
		before=$$(du -sk "$$wt" 2>/dev/null | awk '{print $$1}'); \
		find "$$wt" -type d \( -name '__pycache__' -o -name '.pytest_cache' -o -name '.ruff_cache' -o -name '.mypy_cache' \) -prune -exec rm -rf {} + 2>/dev/null || true; \
		find "$$wt" -maxdepth 4 -type f \( -name '.coverage' -o -name '.coverage.*' \) -exec rm -f {} + 2>/dev/null || true; \
		[ -d "$$wt/.benchbox/cache" ] && rm -rf "$$wt/.benchbox/cache" || true; \
		after=$$(du -sk "$$wt" 2>/dev/null | awk '{print $$1}'); \
		delta=$$((before - after)); \
		if [ "$$delta" -gt 0 ]; then \
			echo "$$pool: freed $${delta}K (was $${before}K, now $${after}K)"; \
			freed_total=$$((freed_total + delta)); \
			cleaned=$$((cleaned + 1)); \
		fi; \
	done; \
	echo "Cleaned $$cleaned slot(s); freed $${freed_total}K total."

worktree-list:
	@git worktree list


# Remove worktrees whose branches are gone on origin (already merged).
# Legacy cleanup only. Pool worktrees are retained and released instead.
worktree-prune:
	@git fetch --prune --quiet
	@MAIN_CLONE=$$(dirname "$$(realpath "$$(git rev-parse --git-common-dir)")"); \
	git worktree list --porcelain | awk 'function emit(){if (wt != "") print wt "|" br} /^worktree /{emit(); wt=$$2; br=""} /^branch /{br=$$2} END{emit()}' | \
		while IFS='|' read -r wt br; do \
			[ "$$wt" = "$$MAIN_CLONE" ] && continue; \
			base=$$(basename "$$wt"); \
			case "$$base" in *.pool-[0-9][0-9]) pool=$${base##*.}; echo "Skipping pool worktree $$pool (retained)"; continue ;; esac; \
			[ -n "$$br" ] || continue; \
			short=$${br#refs/heads/}; \
			if ! git ls-remote --exit-code --heads origin "$$short" >/dev/null 2>&1; then \
				echo "Removing worktree (branch gone on origin): $$wt [$$short]"; \
				git worktree remove "$$wt" 2>/dev/null || git worktree remove --force "$$wt"; \
				git branch -D "$$short" 2>/dev/null || true; \
			fi; \
		done
	@git worktree prune

# Blind-spot finding triage (file-first capture; see _project/blind-spots/README.md).
blind-spots-list:
	@uv run --project _project/scripts -- python _project/scripts/sweep_blind_spots.py list

blind-spots-report:
	@uv run --project _project/scripts -- python _project/scripts/sweep_blind_spots.py report

# Alias: 'sweep' as the verb users will reach for; report is the v1 sweep view.
blind-spots-sweep: blind-spots-report

# Soundness-PR drain digest (read-only local run; the scheduled workflow
# runs the same script with --apply). See docs/operations/soundness-drain.md.
soundness-drain-report:
	@uv run -- python _project/scripts/soundness_drain_report.py

soundness-drain-self-test:
	@uv run -- python _project/scripts/soundness_drain_report.py --self-test
