#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchbox.utils.clock import elapsed_seconds, mono_time
from scripts.version_matrix_specs import SPECS, MatrixSpec, scale_argument, scale_token

CLI_DESCRIPTION = (
    "Run a reproducible engine version matrix.\n"
    "\n"
    "The matrix is operator-run: it generates each benchmark dataset once, then\n"
    "loads and measures it with every package version in the selected engine spec.\n"
    "Each power cell is a separate BenchBox invocation, repeated per the spec.\n"
    "Artifacts stay outside the checkout and are recorded in ``matrix-manifest.json``;\n"
    "analyze them with ``scripts/analyze_version_matrix.py``.\n"
    "\n"
    "Run from the BenchBox checkout with ``uv run --no-sync`` because the runner\n"
    "changes the installed engine package between subprocesses while the project\n"
    "lock stays unchanged.\n"
)


@dataclass(frozen=True)
class Step:
    kind: str
    benchmark: str | None = None
    scale: float | None = None
    version: str | None = None
    repetition: int | None = None


def plan_steps(spec: MatrixSpec) -> list[Step]:
    steps = [Step("generate", benchmark, scale) for benchmark, scale in spec.benchmarks]
    for version in spec.versions:
        steps.append(Step("install", version=version))
        for benchmark, scale in spec.benchmarks:
            steps.append(Step("load", benchmark, scale, version))
            steps.extend(
                Step("power", benchmark, scale, version, repetition) for repetition in range(1, spec.repetitions + 1)
            )
    return steps


def _command_text(command: list[str]) -> str:
    return shlex.join(command)


def _append_log(log_path: Path, text: str) -> None:
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(text)
        if not text.endswith("\n"):
            handle.write("\n")


def _run_command(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    log_path: Path,
    dry_run: bool,
) -> tuple[int, str, float]:
    if dry_run:
        print(f"$ {_command_text(command)}")
        return 0, "", 0.0

    _append_log(log_path, f"$ {_command_text(command)}\n")
    started = mono_time()
    completed = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, check=False)
    elapsed = elapsed_seconds(started)
    output = (completed.stdout or "") + (completed.stderr or "")
    _append_log(log_path, output)
    _append_log(log_path, f"[exit={completed.returncode} elapsed_s={elapsed:.3f}]\n")
    return completed.returncode, output, elapsed


def _find_result_path(output: str, *, cwd: Path) -> Path:
    for line in reversed(output.splitlines()):
        candidate = Path(line.strip())
        if not candidate.is_absolute():
            candidate = cwd / candidate
        if candidate.is_file() and candidate.suffix == ".json":
            return candidate.resolve()
    raise RuntimeError("BenchBox completed without emitting an existing result JSON path")


def install_command(spec: MatrixSpec, version: str) -> list[str]:
    return [
        "uv",
        "pip",
        "install",
        "--prerelease=allow",
        "--python",
        sys.executable,
        f"{spec.driver_package}=={version}",
    ]


def _clear_databases(spec: MatrixSpec, output_dir: Path, benchmark: str, scale: float) -> None:
    database_dir = output_dir / "databases" / f"{benchmark}_sf{scale_token(scale)}"
    if not database_dir.exists():
        return
    for suffix in spec.cleared_database_suffixes:
        for path in database_dir.glob(f"*{suffix}"):
            if path.is_file() or path.is_symlink():
                path.unlink()


def benchbox_command(
    spec: MatrixSpec,
    *,
    phase: str,
    benchmark: str,
    scale: float,
    version: str | None = None,
) -> list[str]:
    command = [
        "uv",
        "run",
        "--no-sync",
        "--",
        "benchbox",
        "run",
        "--non-interactive",
        "--quiet",
        "--compression",
        spec.compression,
        "--phases",
        phase,
        "--benchmark",
        benchmark,
        "--scale",
        scale_argument(scale),
    ]
    if phase != "generate":
        command[7:7] = ["--platform", spec.platform]
    command.extend(spec.driver_platform_options(version))
    return command


def _load_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Result bundle is not an object: {path}")
    return payload


def _record(
    *,
    output_dir: Path,
    result_path: Path,
    phase: str,
    benchmark: str,
    scale: float,
    requested_version: str | None,
    repetition: int | None,
    elapsed_s: float,
) -> dict[str, Any]:
    payload = _load_payload(result_path)
    platform = payload.get("platform") if isinstance(payload.get("platform"), dict) else {}
    execution = payload.get("execution") if isinstance(payload.get("execution"), dict) else {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    queries = summary.get("queries") if isinstance(summary.get("queries"), dict) else {}
    return {
        "path": result_path.relative_to(output_dir).as_posix(),
        "phase": phase,
        "benchmark": benchmark,
        "scale": scale,
        "requested_version": requested_version,
        "repetition": repetition,
        "elapsed_s": round(elapsed_s, 3),
        "platform_version": (
            execution.get("driver_version_resolved")
            or execution.get("driver_resolved_version")
            or platform.get("client_version")
            or platform.get("version")
        ),
        "client_version": platform.get("client_version"),
        "driver_resolved_version": execution.get("driver_version_resolved") or execution.get("driver_resolved_version"),
        "driver_actual_version": execution.get("driver_version_actual") or execution.get("driver_actual_version"),
        "validation": summary.get("validation"),
        "query_total": queries.get("total"),
        "query_failed": queries.get("failed"),
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_matrix(spec: MatrixSpec, *, output_dir: Path, repo_root: Path, dry_run: bool) -> dict[str, Any]:
    if output_dir == repo_root or repo_root in output_dir.parents:
        raise ValueError(f"output directory must be outside the checkout: {output_dir}")
    if not dry_run:
        if output_dir.exists() and any(output_dir.iterdir()):
            raise ValueError(f"output directory must be new or empty: {output_dir}")
        output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "matrix.log"
    env = os.environ.copy()
    env["BENCHBOX_OUTPUT_DIR"] = str(output_dir)
    env["PYTHONUNBUFFERED"] = "1"
    records: list[dict[str, Any]] = []

    for step in plan_steps(spec):
        if step.kind == "install":
            assert step.version is not None
            status, output, _ = _run_command(
                install_command(spec, step.version), cwd=repo_root, env=env, log_path=log_path, dry_run=dry_run
            )
            if status:
                raise RuntimeError(
                    f"Could not install {spec.display_name} {step.version}; see {log_path}\n{output[-2000:]}"
                )
            continue
        assert step.benchmark is not None and step.scale is not None
        if step.kind == "load" and not dry_run:
            _clear_databases(spec, output_dir, step.benchmark, step.scale)
        command = benchbox_command(
            spec, phase=step.kind, benchmark=step.benchmark, scale=step.scale, version=step.version
        )
        status, output, elapsed_s = _run_command(command, cwd=repo_root, env=env, log_path=log_path, dry_run=dry_run)
        if status:
            raise RuntimeError(
                f"BenchBox {step.kind} failed for {step.benchmark} v{step.version or '-'}; see {log_path}"
            )
        if dry_run:
            continue
        records.append(
            _record(
                output_dir=output_dir,
                result_path=_find_result_path(output, cwd=repo_root),
                phase=step.kind,
                benchmark=step.benchmark,
                scale=step.scale,
                requested_version=step.version,
                repetition=step.repetition,
                elapsed_s=elapsed_s,
            )
        )
        with (output_dir / "matrix-records.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(records[-1], sort_keys=True) + "\n")

    manifest = {
        "schema_version": "1",
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "versions": list(spec.versions),
        "benchmarks": [{"id": name, "scale": scale} for name, scale in spec.benchmarks],
        "repetitions": spec.repetitions,
        "compression": spec.compression,
        "expected_runs": spec.expected_benchmark_runs,
        "records": records,
    }
    if not dry_run:
        _write_json(output_dir / "matrix-manifest.json", manifest)
    return manifest


def main(argv: list[str] | None = None, *, spec: MatrixSpec | None = None, description: str = CLI_DESCRIPTION) -> int:
    parser = argparse.ArgumentParser(description=description)
    if spec is None:
        parser.add_argument("--engine", choices=sorted(SPECS), required=True, help="Engine spec to run")
    parser.add_argument("--output-dir", type=Path, required=True, help="New output root outside the checkout")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned commands without running them")
    args = parser.parse_args(argv)
    selected = spec or SPECS[args.engine]
    repo_root = REPO_ROOT
    output_dir = args.output_dir.expanduser().resolve()
    try:
        manifest = run_matrix(selected, output_dir=output_dir, repo_root=repo_root, dry_run=args.dry_run)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        f"{selected.display_name} matrix {'planned' if args.dry_run else 'complete'}: "
        f"{len(manifest['records']) if not args.dry_run else manifest['expected_runs']} runs"
    )
    if not args.dry_run:
        print(f"Manifest: {output_dir / 'matrix-manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
