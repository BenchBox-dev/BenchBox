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
