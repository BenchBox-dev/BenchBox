.PHONY: blind-spots-list
blind-spots-list:
	@uv run --project _project/scripts -- python _project/scripts/sweep_blind_spots.py list

.PHONY: blind-spots-report
blind-spots-report:
	@uv run --project _project/scripts -- python _project/scripts/sweep_blind_spots.py report

.PHONY: blind-spots-sweep
blind-spots-sweep: blind-spots-report

.PHONY: soundness-drain-report
soundness-drain-report:
	@uv run -- python _project/scripts/soundness_drain_report.py

.PHONY: soundness-drain-self-test
soundness-drain-self-test:
	@uv run -- python _project/scripts/soundness_drain_report.py --self-test

.PHONY: worktree-audit
worktree-audit:
	@uv run -- python _project/scripts/worktree_audit.py $(if $(FORMAT),--format $(FORMAT),)
