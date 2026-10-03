blind-spots-list:
	@uv run --project _project/scripts -- python _project/scripts/sweep_blind_spots.py list

blind-spots-report:
	@uv run --project _project/scripts -- python _project/scripts/sweep_blind_spots.py report

blind-spots-sweep: blind-spots-report

soundness-drain-report:
	@uv run -- python _project/scripts/soundness_drain_report.py

soundness-drain-self-test:
	@uv run -- python _project/scripts/soundness_drain_report.py --self-test

.PHONY: worktree-audit
worktree-audit:
	@uv run -- python _project/scripts/worktree_audit.py $(if $(FORMAT),--format $(FORMAT),)
