"""Internal CLI entry points for the `make uat-*` operator targets.

These are intentionally thin: argparse → call into framework module →
print structured output. Not exposed as a `benchbox` subcommand (UAT
is a project-developer concern; benchbox is a project-user concern;
see _project/specs/uat-framework.md Section 1.4).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def cell_main(argv: list[str] | None = None) -> int:
    """Implements `make uat-cell PLATFORM=X BENCHMARK=Y SCALE=Z`."""
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
    args = parser.parse_args(argv)

    result = run_sweep_from_path(Path(args.config))
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
    from tests.uat.orchestrator import run_sweep_from_path

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
    overrides: dict[str, str | float | None] = {
        "platform": args.platform,
        "benchmark": args.benchmark,
        "scale": args.scale,
    }
    result = run_sweep_from_path(config_path, stress_overrides=overrides)
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
    parser.add_argument("--bundles-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--log-dir", required=True)
    parser.add_argument("--browsers", default="chromium")
    args = parser.parse_args(argv)

    result = run_explorer_smoke(
        bundles_dir=Path(args.bundles_dir),
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


def execute_main(argv: list[str] | None = None) -> int:
    """Implements `make uat-execute CONFIG=path/to/uat.yaml`."""
    from tests.uat.config import load_config
    from tests.uat.phases.execute import default_log_dir, run_execute
    from tests.uat.phases.preflight import run_preflight

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
    args = parser.parse_args(argv)

    config = load_config(args.config)
    if "preflight" in config.phases:
        preflight = run_preflight(
            free_space_path=(config.raw.get("preflight") or {}).get("free_space_path", "~/Developer/benchmark_runs"),
            free_space_min_gib=(config.raw.get("preflight") or {}).get("free_space_min_gib", 5.0),
            docker_required=(config.raw.get("preflight") or {}).get("docker_required", False),
        )
        for warning in preflight.warnings:
            print(f"[preflight warn] {warning}", file=sys.stderr)
        if preflight.aborted:
            print(f"[preflight] ABORT: {preflight.abort_reason}", file=sys.stderr)
            return 2

    databases_root = (
        Path(args.databases_root) if args.databases_root else Path.home() / "Developer" / "benchmark_runs" / "databases"
    )
    log_dir = default_log_dir(config)
    outcome = run_execute(
        config,
        log_dir=log_dir,
        databases_root=databases_root,
        cleanup_enabled=not args.no_cleanup,
    )

    summary = {
        "name": config.name,
        "log_dir": str(log_dir),
        "passed": sum(1 for r in outcome.results if r.status == "passed"),
        "failed": sum(1 for r in outcome.results if r.status == "failed"),
        "timed_out": sum(1 for r in outcome.results if r.status == "timed-out"),
        "pruned": len(outcome.pruned),
        "skipped_unreachable": len(outcome.skipped_unreachable),
    }
    print(json.dumps(summary, indent=2))
    return 0 if summary["failed"] == 0 and summary["timed_out"] == 0 else 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "execute":
        sys.exit(execute_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "validate":
        sys.exit(validate_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "package":
        sys.exit(package_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "explorer-smoke":
        sys.exit(explorer_smoke_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        sys.exit(report_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "sweep":
        sys.exit(sweep_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "stress":
        sys.exit(stress_main(sys.argv[2:]))
    sys.exit(cell_main())
