"""Internal CLI entry points for the `make uat-*` operator targets.

These are intentionally thin: argparse → call into framework module →
print structured output. Not exposed as a `benchbox` subcommand (UAT
is a project-developer concern; benchbox is a project-user concern;
see _project/specs/uat-framework.md Section 1.4).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path


def cell_main(argv: list[str] | None = None) -> int:
    """Implements `make uat-cell PLATFORM=X BENCHMARK=Y SCALE=Z`."""
    from tests.uat import docker_assets
    from tests.uat.runner import run_cell

    parser = argparse.ArgumentParser(prog="uat-cell")
    parser.add_argument("--platform", required=True)
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--scale", required=True, type=float)
    parser.add_argument("--timeout-s", type=int, default=600)
    parser.add_argument("--phases", default="load,power")
    parser.add_argument("--compression", default=None)
    parser.add_argument("--log-dir", default=None)
    args = parser.parse_args(argv)

    result = run_cell(
        platform=args.platform,
        benchmark=args.benchmark,
        scale=args.scale,
        timeout_s=args.timeout_s,
        phases=args.phases,
        compression=args.compression,
        log_dir=Path(args.log_dir) if args.log_dir else None,
        local_managed_platform=docker_assets.is_docker_platform(args.platform),
    )
    print(
        json.dumps(
            {
                "platform": result.platform,
                "benchmark": result.benchmark,
                "scale": result.scale,
                "status": result.status,
                "exit_code": result.exit_code,
                "elapsed_s": round(result.elapsed_s, 2),
                "log_path": str(result.log_path),
                "result_path": str(result.result_path) if result.result_path else None,
                "submit_terminal_state": result.submit_terminal_state,
            },
            indent=2,
        )
    )
    return 0 if result.status == "passed" else 1


def sweep_main(argv: list[str] | None = None) -> int:
    """Implements `make uat-sweep CONFIG=<path>`."""
    from tests.uat.orchestrator import run_sweep_from_path

    parser = argparse.ArgumentParser(prog="uat-sweep")
    parser.add_argument("--config", required=True)
    parser.add_argument("--dry-run", action="store_true", help="Override the YAML config and skip workload phases")
    parser.add_argument("--resume", default=None, help="Path to a prior sweep resume.json manifest")
    args = parser.parse_args(argv)

    sweep_kwargs = {"dry_run_override": True if args.dry_run else None}
    if args.resume:
        sweep_kwargs["resume_manifest"] = Path(args.resume)
    result = run_sweep_from_path(Path(args.config), **sweep_kwargs)
    print(
        json.dumps(
            {
                "name": result.name,
                "log_dir": str(result.log_dir),
                "aborted_phase": result.aborted_phase,
                "abort_reason": result.abort_reason,
                "phase_exit_codes": result.phase_exit_codes,
            },
            indent=2,
        )
    )
    return result.exit_code()


def stress_main(argv: list[str] | None = None) -> int:
    """Implements `make uat-stress [PLATFORM=] [BENCHMARK=] [SCALE=]`."""
    from dataclasses import replace

    from tests.uat.config import load_config
    from tests.uat.orchestrator import run_sweep

    parser = argparse.ArgumentParser(prog="uat-stress")
    parser.add_argument("--config", default=None, help="Defaults to tests/uat/configs/stress-default.yaml")
    parser.add_argument("--platform", default=None)
    parser.add_argument("--benchmark", default=None)
    parser.add_argument("--scale", type=float, default=None)
    args = parser.parse_args(argv)

    if args.config is None:
        config_path = Path(__file__).resolve().parent / "configs" / "stress-default.yaml"
    else:
        config_path = Path(args.config)
    config = load_config(config_path)
    if args.platform is not None:
        config = replace(config, platforms=replace(config.platforms, groups=(), include=(args.platform,)))
    if args.benchmark is not None:
        config = replace(config, benchmarks=replace(config.benchmarks, groups=(), include=(args.benchmark,)))
    if args.scale is not None:
        config = replace(config, scales=replace(config.scales, override=args.scale))
    result = run_sweep(config)
    print(
        json.dumps(
            {
                "name": result.name,
                "log_dir": str(result.log_dir),
                "aborted_phase": result.aborted_phase,
                "phase_exit_codes": result.phase_exit_codes,
            },
            indent=2,
        )
    )
    return result.exit_code()


def preflight_main(argv: list[str] | None = None) -> int:
    """Print the advisory disk budget and current preflight status for a config."""
    from tests.uat.config import load_config
    from tests.uat.phases.execute import default_benchmark_runs_dir
    from tests.uat.phases.preflight import requested_platforms_from_config, run_preflight

    parser = argparse.ArgumentParser(prog="uat-preflight")
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)

    config = load_config(args.config)
    benchmark_runs_dir = default_benchmark_runs_dir(config)
    result = run_preflight(
        free_space_path=config.preflight.free_space_path or str(benchmark_runs_dir),
        free_space_min_gib=config.preflight.free_space_min_gib,
        docker_required=config.preflight.docker_required or config.cleanup.docker_manage_platforms,
        noisy_neighbor_warn_load=config.preflight.noisy_neighbor_warn_load,
        local_platforms_check=config.preflight.local_platforms_check,
        requested_platforms=requested_platforms_from_config(config),
        benchmark_runs_dir=benchmark_runs_dir,
        disk_budget_config=config,
    )
    if result.disk_budget_summary:
        print(result.disk_budget_summary)
    for warning in result.warnings:
        print(f"[preflight warn] {warning}", file=sys.stderr)
    if result.aborted:
        print(f"[preflight] ABORT: {result.abort_reason}", file=sys.stderr)
        return 2
    return 0


def report_main(argv: list[str] | None = None) -> int:
    """Implements `make uat-report`. Reads cells from a JSON-lines stream."""
    import json as _json

    from tests.uat.phases.report import write_report
    from tests.uat.runner import CellResult

    parser = argparse.ArgumentParser(prog="uat-report")
    parser.add_argument("--cells-jsonl", required=True)
    parser.add_argument("--output-tsv", required=True)
    parser.add_argument(
        "--rungs",
        default=None,
        help="Comma-separated rung scales for cross-scale coverage",
    )
    parser.add_argument("--cross-scale-floor", type=int, default=None)
    args = parser.parse_args(argv)

    cells = []
    with open(args.cells_jsonl, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            payload = _json.loads(line)
            cells.append(
                CellResult(
                    platform=payload["platform"],
                    benchmark=payload["benchmark"],
                    scale=float(payload["scale"]),
                    status=payload["status"],
                    exit_code=int(payload.get("exit_code", 0)),
                    elapsed_s=float(payload.get("elapsed_s", 0.0)),
                    log_path=Path(payload.get("log_path", "")),
                    result_path=(Path(payload["result_path"]) if payload.get("result_path") else None),
                    submit_terminal_state=payload.get("submit_terminal_state", "submittable"),
                )
            )
    rungs = [float(s) for s in args.rungs.split(",")] if args.rungs else None
    summary = write_report(
        cells,
        output_path=Path(args.output_tsv),
        rungs=rungs,
        cross_scale_floor=args.cross_scale_floor,
    )
    print(
        json.dumps(
            {
                "tsv": str(summary.tsv_path),
                "rows": summary.rows,
                "passed": summary.pass_count,
                "failed": summary.fail_count,
                "timed_out": summary.timeout_count,
                "cross_scale_clean_pairs": summary.cross_scale_clean_pairs,
                "cross_scale_floor": summary.cross_scale_floor,
                "cross_scale_floor_breached": summary.cross_scale_floor_breached,
            },
            indent=2,
        )
    )
    return summary.exit_code()


def explorer_smoke_main(argv: list[str] | None = None) -> int:
    """Implements `make uat-explorer-smoke`."""
    from tests.uat.phases.explorer_smoke import run_explorer_smoke

    parser = argparse.ArgumentParser(prog="uat-explorer-smoke")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--log-dir", required=True)
    parser.add_argument("--browsers", default="chromium")
    args = parser.parse_args(argv)

    result = run_explorer_smoke(
        bundles_dir=Path(args.data_dir),
        output_dir=Path(args.output_dir),
        log_dir=Path(args.log_dir),
        playwright_browsers=tuple(args.browsers.split(",")),
    )
    print(
        json.dumps(
            {
                "skipped": result.skipped,
                "skip_reason": result.skip_reason,
                "build_returncode": result.build_returncode,
                "smoke_returncode": result.smoke_returncode,
                "build_log": str(result.build_log) if result.build_log else None,
                "smoke_log": str(result.smoke_log) if result.smoke_log else None,
            },
            indent=2,
        )
    )
    return result.exit_code()


def replay_classify_main(argv: list[str] | None = None) -> int:
    """Replay a coverage TSV's passed result paths through the submit classifier."""
    from tests.uat.runner import SubmitTerminalState, classify_for_submit

    parser = argparse.ArgumentParser(prog="uat-replay-classify")
    parser.add_argument("--coverage-cells", required=True)
    parser.add_argument("--results-root", required=True)
    args = parser.parse_args(argv)

    coverage_cells = Path(args.coverage_cells).expanduser()
    results_root = Path(args.results_root).expanduser()
    counts: Counter[str] = Counter()
    total = 0
    with coverage_cells.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            if row.get("status") != "passed" or not row.get("result_path"):
                continue
            total += 1
            result_path = Path(row["result_path"])
            if not result_path.exists():
                result_path = results_root / result_path.name
            counts[classify_for_submit(result_path).value] += 1

    submittable = counts[SubmitTerminalState.submittable.value]
    non_submittable = total - submittable
    split = ", ".join(
        f"{state.value}={counts[state.value]}"
        for state in SubmitTerminalState
        if state is not SubmitTerminalState.submittable
    )
    print(
        f"{total} passed-result paths; {submittable} submittable; "
        f"{non_submittable} non-submittable split by classifier: {split}"
    )
    return 0


def package_main(argv: list[str] | None = None) -> int:
    """Implements `make uat-package CONFIG=<path> RESULTS=glob...`."""
    from tests.uat.config import load_config
    from tests.uat.phases.package import run_package

    parser = argparse.ArgumentParser(prog="uat-package")
    parser.add_argument("--config", required=True)
    parser.add_argument("--submissions-dir", required=True)
    parser.add_argument(
        "--result",
        action="append",
        required=True,
        help="Result JSON path; repeat for multiple",
    )
    args = parser.parse_args(argv)

    config = load_config(args.config)
    result = run_package(
        config,
        result_paths=[Path(p) for p in args.result],
        submissions_dir=Path(args.submissions_dir),
    )
    print(
        json.dumps(
            {
                "terminal_state": result.terminal_state,
                "submissions_dir": str(result.submissions_dir),
                "success": result.success_count,
                "failure": result.failure_count,
            },
            indent=2,
        )
    )
    return result.exit_code()


def validate_main(argv: list[str] | None = None) -> int:
    """Implements `make uat-validate RESULTS_DIR=<dir>`."""
    from tests.uat.phases.validate import run_validate

    parser = argparse.ArgumentParser(prog="uat-validate")
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--output-tsv", required=True)
    parser.add_argument("--floor", type=float, default=0.80)
    args = parser.parse_args(argv)

    result = run_validate(
        Path(args.results_dir),
        output_tsv=Path(args.output_tsv),
        floor=args.floor,
    )
    print(
        json.dumps(
            {
                "rollup_tsv": str(result.rollup_tsv_path),
                "clean": result.clean_count,
                "warning_only": result.warning_count,
                "error": result.error_count,
                "refused_by_cli": result.refused_count,
                "clean_rate": round(result.clean_rate, 4),
                "floor": result.floor,
                "floor_breached": result.floor_breached,
            },
            indent=2,
        )
    )
    return result.exit_code()


def verify_tuning_matrix_main(argv: list[str] | None = None) -> int:
    """Verify checked-in tuned-template coverage against observed UAT logs."""
    from benchbox.core.tuning.coverage import (
        parse_runtime_tuning_logs,
        read_tuning_coverage_tsv,
        runtime_mismatches,
    )
    from tests.uat.matrix import PLATFORM_GROUPS, load_benchmarks, resolve_benchmarks

    parser = argparse.ArgumentParser(prog="verify-tuning-matrix")
    parser.add_argument("--logs", required=True, help="Directory containing per-cell UAT command logs")
    parser.add_argument(
        "--matrix",
        default=str(Path(__file__).resolve().parent / "data" / "tuning_coverage.tsv"),
        help="Checked-in tuning coverage TSV",
    )
    args = parser.parse_args(argv)

    benchmarks = load_benchmarks()
    logs_dir = Path(args.logs).expanduser()
    observations = parse_runtime_tuning_logs(
        logs_dir,
        platforms=PLATFORM_GROUPS["all"],
        benchmarks=resolve_benchmarks(groups=["all"], benchmarks=benchmarks),
    )
    if not observations:
        print(f"No tuning observations parsed from UAT logs under {logs_dir}", file=sys.stderr)
        return 1
    matrix_rows = read_tuning_coverage_tsv(Path(args.matrix))
    mismatches = runtime_mismatches(matrix_rows, observations)
    if mismatches:
        print("Tuning matrix mismatches:", file=sys.stderr)
        for mismatch in mismatches:
            print(f"  - {mismatch}", file=sys.stderr)
        return 1
    print(json.dumps({"observations": len(observations), "mismatches": 0}, indent=2))
    return 0


def execute_main(argv: list[str] | None = None) -> int:
    """Implements `make uat-execute CONFIG=path/to/uat.yaml`."""
    from tests.uat.config import load_config
    from tests.uat.phases.execute import default_benchmark_runs_dir, default_log_dir, run_execute
    from tests.uat.phases.preflight import requested_platforms_from_config, run_preflight

    parser = argparse.ArgumentParser(prog="uat-execute")
    parser.add_argument("--config", required=True)
    parser.add_argument(
        "--databases-root",
        default=None,
        help="Optional override for ~/Developer/benchmark_runs/databases",
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Disable reuse-aware database cleanup",
    )
    parser.add_argument("--resume", default=None, help="Path to a prior execute/sweep resume.json manifest")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    benchmark_runs_dir = default_benchmark_runs_dir(config)
    if "preflight" in config.phases:
        preflight = run_preflight(
            free_space_path=config.preflight.free_space_path or str(benchmark_runs_dir),
            free_space_min_gib=config.preflight.free_space_min_gib,
            docker_required=config.preflight.docker_required or config.cleanup.docker_manage_platforms,
            noisy_neighbor_warn_load=config.preflight.noisy_neighbor_warn_load,
            local_platforms_check=config.preflight.local_platforms_check,
            requested_platforms=requested_platforms_from_config(config),
            benchmark_runs_dir=benchmark_runs_dir,
            disk_budget_config=config,
        )
        if preflight.disk_budget_summary:
            print(preflight.disk_budget_summary, file=sys.stderr)
        for warning in preflight.warnings:
            print(f"[preflight warn] {warning}", file=sys.stderr)
        if preflight.aborted:
            print(f"[preflight] ABORT: {preflight.abort_reason}", file=sys.stderr)
            return 2

    databases_root = Path(args.databases_root).expanduser() if args.databases_root else benchmark_runs_dir / "databases"
    log_dir = default_log_dir(config)
    runner = None
    if args.resume:
        from tests.uat.orchestrator import build_resume_runner, load_resume_attempts
        from tests.uat.phases.execute import run_cell

        runner = build_resume_runner(load_resume_attempts(Path(args.resume)), run_cell, log_dir=log_dir)
    execute_kwargs: dict = {
        "log_dir": log_dir,
        "benchmark_runs_dir": benchmark_runs_dir,
        "databases_root": databases_root,
        "cleanup_enabled": not args.no_cleanup and config.cleanup.prune_databases,
        "free_space_checks_enabled": "preflight" in config.phases,
    }
    if runner is not None:
        execute_kwargs["runner"] = runner
    outcome = run_execute(config, **execute_kwargs)

    summary = {
        "name": config.name,
        "log_dir": str(log_dir),
        "passed": sum(1 for r in outcome.results if r.status == "passed"),
        "failed": sum(1 for r in outcome.results if r.status == "failed"),
        "timed_out": sum(1 for r in outcome.results if r.status == "timed-out"),
        "pruned": len(outcome.pruned),
        "compatibility_pruned": len(getattr(outcome, "compatibility_pruned", ())),
        "skipped_unreachable": len(outcome.skipped_unreachable),
        "docker_events": len(outcome.docker_events),
        "aborted": outcome.aborted,
        "abort_reason": outcome.abort_reason,
    }
    print(json.dumps(summary, indent=2))
    if outcome.aborted:
        print(f"[execute] ABORT: {outcome.abort_reason}", file=sys.stderr)
        return 2
    return 0 if summary["failed"] == 0 and summary["timed_out"] == 0 else 1


def docker_cleanup_main(argv: list[str] | None = None) -> int:
    """Implements `make uat-docker-cleanup [APPLY=1]`."""
    from tests.uat import docker_cleanup

    parser = argparse.ArgumentParser(prog="uat-docker-cleanup")
    parser.add_argument(
        "--prefix",
        default=docker_cleanup.DEFAULT_UAT_PROJECT_PREFIX,
        help="Docker compose project prefix that marks UAT-owned resources",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Remove UAT-owned resources. Without this flag the command only reports the plan.",
    )
    args = parser.parse_args(argv)

    try:
        report = docker_cleanup.recover_abandoned_uat_docker_usage(
            project_prefix=args.prefix,
            apply=args.apply,
        )
    except docker_cleanup.DockerCleanupError as exc:
        print(f"[uat-docker-cleanup] ERROR: {exc}", file=sys.stderr)
        return 2
    print(docker_cleanup.format_cleanup_report(report))
    return 0


SUBCOMMANDS = {
    "cell": cell_main,
    "docker-cleanup": docker_cleanup_main,
    "execute": execute_main,
    "validate": validate_main,
    "package": package_main,
    "explorer-smoke": explorer_smoke_main,
    "report": report_main,
    "sweep": sweep_main,
    "stress": stress_main,
    "verify-tuning-matrix": verify_tuning_matrix_main,
}


def _help_text() -> str:
    cmds = ", ".join(sorted(SUBCOMMANDS))
    return (
        f"usage: python -m tests.uat._cli <subcommand> [options]\n"
        f"  subcommands: {cmds}\n"
        "  with no subcommand, --platform/--benchmark/--scale invoke the "
        "single-cell runner."
    )


def main(argv: list[str] | None = None) -> int:
    """Dispatch to the right subcommand. Bare flags route to cell_main for `make uat-cell`."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        return cell_main([])
    head = argv[0]
    if head in SUBCOMMANDS:
        return SUBCOMMANDS[head](argv[1:])
    if head == "replay-classify":
        return replay_classify_main(argv[1:])
    if head == "preflight":
        # Not a make target yet, so keep it out of SUBCOMMANDS' make-target
        # parity test while still exposing the advisory estimator CLI.
        return preflight_main(argv[1:])
    if head in {"-h", "--help"}:
        print(_help_text())
        return 0
    if head.startswith("-"):
        # Backward compat: `python -m tests.uat._cli --platform=... --benchmark=... --scale=...`
        return cell_main(argv)
    print(f"unknown subcommand: {head!r}", file=sys.stderr)
    print(_help_text(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
