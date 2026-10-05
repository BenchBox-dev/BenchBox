# Blind-spot finding triage (file-first capture; see _project/blind-spots/README.md).
.PHONY: blind-spots-list
blind-spots-list:
	@uv run --project _project/scripts -- python _project/scripts/sweep_blind_spots.py list

.PHONY: blind-spots-report
blind-spots-report:
	@uv run --project _project/scripts -- python _project/scripts/sweep_blind_spots.py report

# Alias: 'sweep' as the verb users will reach for; report is the v1 sweep view.
.PHONY: blind-spots-sweep
blind-spots-sweep: blind-spots-report

# Soundness-PR drain digest (read-only local run; the scheduled workflow
# runs the same script with --apply). See docs/operations/soundness-drain.md.
.PHONY: soundness-drain-report
soundness-drain-report:
	@uv run -- python _project/scripts/soundness_drain_report.py

.PHONY: soundness-drain-self-test
soundness-drain-self-test:
	@uv run -- python _project/scripts/soundness_drain_report.py --self-test

# Bounded read-only inventory and lifecycle audit of registered worktrees and local branches.
# Emits human-readable text by default, or schema-versioned JSON with FORMAT=json.
.PHONY: worktree-audit
worktree-audit:
	@uv run -- python _project/scripts/worktree_audit.py $(if $(FORMAT),--format $(FORMAT),)
