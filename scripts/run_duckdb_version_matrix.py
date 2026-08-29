#!/usr/bin/env python3
"""Run the reproducible DuckDB version matrix used by Results Explorer.

The matrix is intentionally operator-run: it creates four SF10 synthetic
datasets once, then loads and measures each dataset with seven DuckDB package
versions. Each power cell is a separate BenchBox invocation, repeated three times. Generated
artifacts stay outside the checkout and are recorded in ``matrix-manifest.json``.

Run from the BenchBox checkout with:

    uv run --no-sync -- python scripts/run_duckdb_version_matrix.py \
      --output-dir /Users/joe/Developer/benchmark_runs/duckdb-version-matrix-20260829

``--no-sync`` is required because the runner changes the active DuckDB wheel
between subprocesses while the BenchBox project lock intentionally remains
unchanged.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSIONS = ("1.0.0", "1.1.3", "1.2.2", "1.3.2", "1.4.4", "1.5.5", "1.6.0.dev365")
BENCHMARKS = (("tpch", 10.0), ("tpcds", 10.0), ("clickbench", 10.0), ("ssb", 10.0))
REPETITIONS = 3
COMPRESSION = "zstd:3"
PRERELEASE_RE = re.compile(r"\.(?:dev\d+|rc\d+|a\d+|b\d+)$", re.IGNORECASE)


def _scale_token(scale: float) -> str:
    return str(int(scale)) if scale == int(scale) else str(scale).replace(".", "")


def _is_prerelease(version: str) -> bool:
    return bool(PRERELEASE_RE.search(version))


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
    """Run one command, logging its output and using monotonic elapsed time."""
    if dry_run:
        print(f"$ {_command_text(command)}")
        return 0, "", 0.0

    _append_log(log_path, f"$ {_command_text(command)}\n")
    started = time.monotonic()
    completed = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, check=False)
    elapsed = time.monotonic() - started
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


def _install_driver(version: str, *, cwd: Path, env: dict[str, str], log_path: Path, dry_run: bool) -> None:
    command = [
        "uv",
        "pip",
        "install",
        "--prerelease=allow",
        "--python",
        sys.executable,
        f"duckdb=={version}",
    ]
    status, output, _ = _run_command(command, cwd=cwd, env=env, log_path=log_path, dry_run=dry_run)
    if status:
        raise RuntimeError(f"Could not install DuckDB {version}; see {log_path}\n{output[-2000:]}")


def _clear_database(output_dir: Path, benchmark: str, scale: float) -> None:
    """Remove only the exact DuckDB database artifacts for one matrix cell."""
    database_dir = output_dir / "databases" / f"{benchmark}_sf{_scale_token(scale)}"
    if not database_dir.exists():
        return
    for suffix in (".duckdb", ".wal"):
        for path in database_dir.glob(f"*{suffix}"):
            if path.is_file() or path.is_symlink():
                path.unlink()


def _benchbox_command(
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
        COMPRESSION,
        "--phases",
        phase,
        "--benchmark",
        benchmark,
        "--scale",
        str(int(scale) if scale == int(scale) else scale),
    ]
    if phase != "generate":
        command[7:7] = ["--platform", "duckdb"]
    if version is not None and not _is_prerelease(version):
        command.extend(["--platform-option", f"driver_version={version}"])
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


def run_matrix(*, output_dir: Path, repo_root: Path, dry_run: bool) -> dict[str, Any]:
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

    def execute(phase: str, benchmark: str, scale: float, version: str | None, repetition: int | None) -> None:
        command = _benchbox_command(phase=phase, benchmark=benchmark, scale=scale, version=version)
        status, output, elapsed_s = _run_command(
            command,
            cwd=repo_root,
            env=env,
            log_path=log_path,
            dry_run=dry_run,
        )
        if status:
            raise RuntimeError(f"BenchBox {phase} failed for {benchmark} v{version or '-'}; see {log_path}")
        if dry_run:
            return
        result_path = _find_result_path(output, cwd=repo_root)
        records.append(
            _record(
                output_dir=output_dir,
                result_path=result_path,
                phase=phase,
                benchmark=benchmark,
                scale=scale,
                requested_version=version,
                repetition=repetition,
                elapsed_s=elapsed_s,
            )
        )
        records_path = output_dir / "matrix-records.jsonl"
        with records_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(records[-1], sort_keys=True) + "\n")

    for benchmark, scale in BENCHMARKS:
        execute("generate", benchmark, scale, None, None)

    for version in VERSIONS:
        _install_driver(version, cwd=repo_root, env=env, log_path=log_path, dry_run=dry_run)
        for benchmark, scale in BENCHMARKS:
            if not dry_run:
                _clear_database(output_dir, benchmark, scale)
            execute("load", benchmark, scale, version, None)
            for repetition in range(1, REPETITIONS + 1):
                execute("power", benchmark, scale, version, repetition)

    manifest = {
        "schema_version": "1",
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "versions": list(VERSIONS),
        "benchmarks": [{"id": name, "scale": scale} for name, scale in BENCHMARKS],
        "repetitions": REPETITIONS,
        "compression": COMPRESSION,
        "expected_runs": 4 + len(VERSIONS) * len(BENCHMARKS) * (1 + REPETITIONS),
        "records": records,
    }
    if not dry_run:
        _write_json(output_dir / "matrix-manifest.json", manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True, help="New output root outside the checkout")
    parser.add_argument("--dry-run", action="store_true", help="Print the 116-command matrix without running it")
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    try:
        manifest = run_matrix(
            output_dir=args.output_dir.expanduser().resolve(), repo_root=repo_root, dry_run=args.dry_run
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        f"DuckDB matrix {'planned' if args.dry_run else 'complete'}: "
        f"{len(manifest['records']) if not args.dry_run else manifest['expected_runs']} runs"
    )
    if not args.dry_run:
        print(f"Manifest: {args.output_dir.expanduser().resolve() / 'matrix-manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
