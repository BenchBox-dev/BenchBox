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
from collections.abc import Callable
from pathlib import Path

Handler = Callable[[argparse.Namespace], int]

MAKE_TARGET_SUBCOMMANDS = (
    "cell",
    "docker-cleanup",
    "execute",
    "validate",
    "package",
    "explorer-smoke",
    "report",
    "sweep",
    "stress",
    "verify-tuning-matrix",
)


def _split_csv(value: str | None) -> list[float] | None:
    return [float(part) for part in value.split(",")] if value else None


def _handle_cell(args: argparse.Namespace) -> int:
    """Implements `make uat-cell PLATFORM=X BENCHMARK=Y SCALE=Z`."""
    from tests.uat import docker_assets
    from tests.uat.runner import run_cell

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


def _handle_sweep(args: argparse.Namespace) -> int:
    """Implements `make uat-sweep CONFIG=<path>`."""
    from tests.uat.orchestrator import run_sweep_from_path

    sweep_kwargs = {"dry_run_override": True if args.dry_run else None}
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


def _handle_stress(args: argparse.Namespace) -> int:
    """Implements `make uat-stress [PLATFORM=] [BENCHMARK=] [SCALE=]`."""
    from tests.uat.orchestrator import run_sweep_from_path

    if args.config is None:
        config_path = Path(__file__).resolve().parent / "configs" / "stress-default.yaml"
    else:
        config_path = Path(args.config)
    # Same closed override set `run_sweep_from_path` already implements for
    # `make uat-sweep`'s dry-run path (spec Section 4 override contract) --
    # this used to be a second, hand-duplicated copy of the platform/
    # benchmark/scale override logic. Reuse instead of re-implementing.
    stress_overrides = {
        "platform": args.platform,
        "benchmark": args.benchmark,
        "scale": args.scale,
    }
    result = run_sweep_from_path(config_path, stress_overrides=stress_overrides)
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


def _handle_preflight(args: argparse.Namespace) -> int:
    """Print the advisory disk budget and current preflight status for a config."""
    from tests.uat.config import load_config
    from tests.uat.phases.execute import default_benchmark_runs_dir
    from tests.uat.phases.preflight import preflight_kwargs_from_config, run_preflight

    config = load_config(args.config)
    benchmark_runs_dir = default_benchmark_runs_dir(config)
    result = run_preflight(**preflight_kwargs_from_config(config, benchmark_runs_dir=benchmark_runs_dir))
    if result.disk_budget_summary:
        print(result.disk_budget_summary)
    for line in getattr(result, "free_space_report", ()):
        print(line)
    for warning in result.warnings:
        print(f"[preflight warn] {warning}", file=sys.stderr)
    if result.aborted:
        print(f"[preflight] ABORT: {result.abort_reason}", file=sys.stderr)
        return 2
    return 0


def _handle_report(args: argparse.Namespace) -> int:
    """Implements `make uat-report`. Reads cells from a JSON-lines stream."""
    from tests.uat.cells_io import read_cells_jsonl, read_skipped_unreachable_sidecar
    from tests.uat.phases.report import write_report

    cells = read_cells_jsonl(Path(args.cells_jsonl))
    # Skipped-unreachable cells are not JSONL rows; the durable sweep writes
    # their count to a sidecar next to cells.jsonl. Read it back so a
    # regenerated report keeps `total_defined` faithful instead of printing
    # `unreachable: 0` for an incomplete sweep. When the sidecar is missing
    # (older artifacts), the count defaults to 0 but is not confirmed -
    # `unreachable_count_is_estimated` makes that distinction visible instead
    # of silently looking identical to a confirmed clean run.
    skipped_unreachable_count, sidecar_present = read_skipped_unreachable_sidecar(Path(args.cells_jsonl))
    rungs = _split_csv(args.rungs)
    summary = write_report(
        cells,
        output_path=Path(args.output_tsv),
        rungs=rungs,
        cross_scale_floor=args.cross_scale_floor,
        skipped_unreachable_count=skipped_unreachable_count,
        unreachable_count_is_estimated=not sidecar_present,
    )
    print(
        json.dumps(
            {
                "tsv": str(summary.tsv_path),
                "rows": summary.rows,
                "candidates": summary.candidate_count,
                "attempted": summary.attempted_count,
                "skipped": summary.skipped_count,
                "unreachable": summary.unreachable_count,
                "unreachable_is_estimated": summary.unreachable_count_is_estimated,
                "total_defined": summary.total_defined_count,
                "registry_pruned": summary.registry_pruned_count,
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


def _handle_explorer_smoke(args: argparse.Namespace) -> int:
    """Implements `make uat-explorer-smoke`."""
    from tests.uat.phases.explorer_smoke import run_explorer_smoke

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


def _handle_replay_classify(args: argparse.Namespace) -> int:
    """Replay a coverage TSV's passed result paths through the submit classifier."""
    from tests.uat.runner import SubmitTerminalState, classify_for_submit

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


def _handle_package(args: argparse.Namespace) -> int:
    """Implements `make uat-package CONFIG=<path> RESULTS=glob...`."""
    from tests.uat.config import load_config
    from tests.uat.phases.package import run_package

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


def _handle_validate(args: argparse.Namespace) -> int:
    """Implements `make uat-validate RESULTS_DIR=<dir>`."""
    from tests.uat.phases.validate import run_validate

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


def _handle_verify_tuning_matrix(args: argparse.Namespace) -> int:
    """Verify checked-in tuned-template coverage against observed UAT logs."""
    from benchbox.core.tuning.coverage import (
        parse_runtime_tuning_logs,
        read_tuning_coverage_tsv,
        runtime_mismatches,
    )
    from tests.uat.matrix import PLATFORM_GROUPS, load_benchmarks, resolve_benchmarks

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


def _handle_execute(args: argparse.Namespace) -> int:
    """Implements `make uat-execute CONFIG=path/to/uat.yaml`.

    Routes through the orchestrator's canonical phase loop (`run_sweep`,
    scoped to `[preflight?, execute]`) instead of a hand-rolled
    preflight+execute duplicate, so `make uat-execute` gets the same
    per-cell disk-floor watch and durable cells.jsonl + accounting sidecar a
    sweep gets -- see uat-execute-path-unification w2. One behavior
    improvement over the prior standalone implementation: a mid-execute
    disk-floor abort now also emits the abort-safe cells.jsonl/partial-report
    artifacts (previously `make uat-execute` had none).
    """
    from dataclasses import replace

    from tests.uat.config import load_config
    from tests.uat.orchestrator import run_sweep
    from tests.uat.phases.execute import default_benchmark_runs_dir

    config = load_config(args.config)
    benchmark_runs_dir = default_benchmark_runs_dir(config)
    databases_root = Path(args.databases_root).expanduser() if args.databases_root else benchmark_runs_dir / "databases"

    # `make uat-execute` runs preflight only when the config's own `phases:`
    # list requests it (matching the prior standalone implementation' gating
    # on `"preflight" in config.phases`), plus execute -- never
    # validate/package/report/explorer_smoke, which stay `make uat-sweep`'s
    # job.
    phases = tuple(phase for phase in ("preflight", "execute") if phase in config.phases)
    if "execute" not in phases:
        phases = (*phases, "execute")
    cleanup_enabled = not args.no_cleanup and config.cleanup.prune_databases
    scoped_config = replace(
        config,
        phases=phases,
        cleanup=replace(config.cleanup, prune_databases=cleanup_enabled),
    )

    result = run_sweep(scoped_config, databases_root=databases_root)

    if result.aborted_phase == "preflight":
        print(f"[preflight] ABORT: {result.abort_reason}", file=sys.stderr)
        return 2

    outcome = result.execute_outcome
    if outcome is None:
        # Reachable only when the execute phase never actually ran -- e.g. a
        # `dry_run: true` config, where run_sweep records exit 0 per phase
        # without invoking run_execute. (A mid-execute disk-floor abort does
        # NOT land here: run_sweep synthesizes an ExecuteOutcome from the
        # attempted cells for that case, so it flows through the normal
        # summary path below.) There are no per-cell counts to report.
        summary = {
            "name": config.name,
            "log_dir": str(result.log_dir),
            "passed": 0,
            "failed": 0,
            "timed_out": 0,
            "pruned": 0,
            "compatibility_pruned": 0,
            "skipped_unreachable": 0,
            "docker_events": 0,
            "aborted": True,
            "abort_reason": result.abort_reason,
        }
        print(json.dumps(summary, indent=2))
        print(f"[execute] ABORT: {result.abort_reason}", file=sys.stderr)
        return 2

    summary = {
        "name": config.name,
        "log_dir": str(result.log_dir),
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
    return outcome.exit_code()


def _handle_docker_cleanup(args: argparse.Namespace) -> int:
    """Implements `make uat-docker-cleanup [ENGINE=] [MODE=] [APPLY=1]`."""
    if args.engine == "container":
        return _handle_container_cleanup(args)

    from tests.uat import docker_cleanup

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


def _handle_container_cleanup(args: argparse.Namespace) -> int:
    """Apple `container` mode of `make uat-docker-cleanup ENGINE=container`."""
    from tests.uat import container_cleanup

    try:
        report = container_cleanup.reclaim_container_usage(
            project_prefix=args.prefix,
            mode=args.mode,
            apply=args.apply,
        )
    except container_cleanup.ContainerCleanupError as exc:
        print(f"[uat-docker-cleanup] ERROR: {exc}", file=sys.stderr)
        return 2
    print(container_cleanup.format_container_cleanup_report(report))
    return 0


def _set_handler(parser: argparse.ArgumentParser, handler: Handler) -> None:
    parser.set_defaults(handler=handler)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tests.uat._cli",
        description="Developer-only UAT framework entrypoints.",
    )
    subparsers = parser.add_subparsers(dest="cmd", required=False)

    cell = subparsers.add_parser("cell", help="run one UAT matrix cell")
    cell.add_argument("--platform", required=True)
    cell.add_argument("--benchmark", required=True)
    cell.add_argument("--scale", required=True, type=float)
    cell.add_argument("--timeout-s", type=int, default=600)
    cell.add_argument("--phases", default="load,power")
    cell.add_argument("--compression", default=None)
    cell.add_argument("--log-dir", default=None)
    _set_handler(cell, _handle_cell)

    sweep = subparsers.add_parser("sweep", help="run a multi-phase UAT sweep from YAML")
    sweep.add_argument("--config", required=True)
    sweep.add_argument("--dry-run", action="store_true", help="Override the YAML config and skip workload phases")
    _set_handler(sweep, _handle_sweep)

    stress = subparsers.add_parser("stress", help="run the canned stress preset")
    stress.add_argument("--config", default=None, help="Defaults to tests/uat/configs/stress-default.yaml")
    stress.add_argument("--platform", default=None)
    stress.add_argument("--benchmark", default=None)
    stress.add_argument("--scale", type=float, default=None)
    _set_handler(stress, _handle_stress)

    preflight = subparsers.add_parser("preflight", help="print advisory disk and platform preflight status")
    preflight.add_argument("--config", required=True)
    _set_handler(preflight, _handle_preflight)

    report = subparsers.add_parser("report", help="write a TSV report from a cells JSONL")
    report.add_argument("--cells-jsonl", required=True)
    report.add_argument("--output-tsv", required=True)
    report.add_argument("--rungs", default=None, help="Comma-separated rung scales for cross-scale coverage")
    report.add_argument("--cross-scale-floor", type=int, default=None)
    _set_handler(report, _handle_report)

    explorer = subparsers.add_parser("explorer-smoke", help="build and smoke-test the results explorer")
    explorer.add_argument("--data-dir", required=True)
    explorer.add_argument("--output-dir", required=True)
    explorer.add_argument("--log-dir", required=True)
    explorer.add_argument("--browsers", default="chromium")
    _set_handler(explorer, _handle_explorer_smoke)

    replay = subparsers.add_parser("replay-classify", help="classify passed coverage cells for submission readiness")
    replay.add_argument("--coverage-cells", required=True)
    replay.add_argument("--results-root", required=True)
    _set_handler(replay, _handle_replay_classify)

    package = subparsers.add_parser("package", help="package UAT result bundles")
    package.add_argument("--config", required=True)
    package.add_argument("--submissions-dir", required=True)
    package.add_argument("--result", action="append", required=True, help="Result JSON path; repeat for multiple")
    _set_handler(package, _handle_package)

    validate = subparsers.add_parser("validate", help="validate published result bundles")
    validate.add_argument("--results-dir", required=True)
    validate.add_argument("--output-tsv", required=True)
    validate.add_argument("--floor", type=float, default=0.80)
    _set_handler(validate, _handle_validate)

    tuning = subparsers.add_parser("verify-tuning-matrix", help="compare tuned-template coverage to observed logs")
    tuning.add_argument("--logs", required=True, help="Directory containing per-cell UAT command logs")
    tuning.add_argument(
        "--matrix",
        default=str(Path(__file__).resolve().parent / "data" / "tuning_coverage.tsv"),
        help="Checked-in tuning coverage TSV",
    )
    _set_handler(tuning, _handle_verify_tuning_matrix)

    execute = subparsers.add_parser("execute", help="run the UAT execute phase")
    execute.add_argument("--config", required=True)
    execute.add_argument(
        "--databases-root",
        default=None,
        help="Optional override for ~/Developer/benchmark_runs/databases",
    )
    execute.add_argument("--no-cleanup", action="store_true", help="Disable reuse-aware database cleanup")
    _set_handler(execute, _handle_execute)

    docker = subparsers.add_parser(
        "docker-cleanup", help="report or remove abandoned UAT-owned Docker / Apple container resources"
    )
    from tests.uat import container_cleanup, docker_cleanup

    docker.add_argument(
        "--engine",
        choices=("docker", "container"),
        default="docker",
        help="Cleanup engine: 'docker' (default) or 'container' (Apple container store).",
    )
    docker.add_argument(
        "--mode",
        choices=container_cleanup.CONTAINER_CLEANUP_MODES,
        default="owned",
        help="Apple-container breadth ladder: owned (default) < images < max. Ignored for --engine docker.",
    )
    docker.add_argument(
        "--prefix",
        default=docker_cleanup.DEFAULT_UAT_PROJECT_PREFIX,
        help="Compose project prefix that marks UAT-owned resources",
    )
    docker.add_argument(
        "--apply",
        action="store_true",
        help="Remove owned resources. Without this flag the command only reports the plan.",
    )
    _set_handler(docker, _handle_docker_cleanup)

    return parser


def _argv_with_default_cell(argv: list[str]) -> list[str]:
    if argv and argv[0] in {"-h", "--help"}:
        return argv
    if not argv or argv[0].startswith("-"):
        return ["cell", *argv]
    return argv


def _exit_code_from_system_exit(exc: SystemExit) -> int:
    if exc.code is None:
        return 0
    if isinstance(exc.code, int):
        return exc.code
    print(exc.code, file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    """Dispatch to the right subcommand. Bare flags route to `cell` for `make uat-cell`."""
    parser = _build_parser()
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    try:
        args = parser.parse_args(_argv_with_default_cell(raw_argv))
    except SystemExit as exc:
        return _exit_code_from_system_exit(exc)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
