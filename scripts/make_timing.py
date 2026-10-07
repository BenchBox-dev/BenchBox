#!/usr/bin/env python3

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import signal
import socket
import statistics
import subprocess
import sys
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA = "make_timing_v1"
FILE_ENV = "BENCHBOX_MAKE_TIMINGS_FILE"
SWITCH_ENV = "BENCHBOX_MAKE_TIMINGS"
TARGET_ENV = "BENCHBOX_MAKE_TIMING_TARGET"
GOALS_ENV = "BENCHBOX_MAKE_TIMING_GOALS"
DISABLED_VALUES = frozenset({"0", "off", "false", "no"})
UNNAMED_TARGET = "unnamed"
GIT_TIMEOUT_SECONDS = 5
FORWARDED_SIGNALS = tuple(getattr(signal, name) for name in ("SIGTERM", "SIGHUP") if hasattr(signal, name))
TERMINAL_SIGNALS = tuple(getattr(signal, name) for name in ("SIGINT", "SIGQUIT") if hasattr(signal, name))
EXIT_COMMAND_NOT_FOUND = 127
EXIT_COMMAND_NOT_EXECUTABLE = 126
SIGNAL_EXIT_OFFSET = 128


def recording_disabled(environ: dict[str, str] | None = None) -> bool:
    environment = os.environ if environ is None else environ
    return environment.get(SWITCH_ENV, "").strip().lower() in DISABLED_VALUES


def timings_path(environ: dict[str, str] | None = None) -> Path:
    environment = os.environ if environ is None else environ
    override = environment.get(FILE_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".benchbox" / "make-timings.jsonl"


def _warn(message: str) -> None:
    print(f"[make-timing] {message}", file=sys.stderr)


def _load_clock() -> Any:
    path = Path(__file__).resolve().parents[1] / "benchbox" / "utils" / "clock.py"
    spec = importlib.util.spec_from_file_location("benchbox_utils_clock", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git_output(*arguments: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip()
    return value if completed.returncode == 0 and value else None


def _iso_utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_iso_utc(text: str) -> datetime:
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _make_goals(environ: dict[str, str]) -> list[str]:
    return environ.get(GOALS_ENV, "").split()


def build_record(
    *,
    target: str,
    started_at: datetime,
    ended_at: datetime,
    duration_seconds: float,
    exit_code: int,
    cwd: str,
    branch: str | None,
    head: str | None,
    host: str,
    make_goals: Sequence[str],
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "target": target,
        "started_at": _iso_utc(started_at),
        "ended_at": _iso_utc(ended_at),
        "duration_seconds": round(duration_seconds, 3),
        "exit_code": exit_code,
        "cwd": cwd,
        "branch": branch,
        "head": head,
        "host": host,
        "make_goals": list(make_goals),
    }


def append_record(path: Path, record: dict[str, Any]) -> None:
    line = (json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        written = os.write(descriptor, line)
    finally:
        os.close(descriptor)
    if written != len(line):
        raise OSError(f"short write to {path}: {written} of {len(line)} bytes")


def _run_child(argv: Sequence[str]) -> int:
    saved: dict[int, Any] = {}
    try:
        for number in TERMINAL_SIGNALS:
            saved[number] = signal.signal(number, lambda *_: None)
        try:
            child = subprocess.Popen(list(argv), close_fds=False)
        except FileNotFoundError:
            print(f"make_timing: command not found: {argv[0]}", file=sys.stderr)
            return EXIT_COMMAND_NOT_FOUND
        except OSError as error:
            print(f"make_timing: cannot execute {argv[0]}: {error}", file=sys.stderr)
            return EXIT_COMMAND_NOT_EXECUTABLE
        for number in FORWARDED_SIGNALS:
            saved[number] = signal.signal(number, lambda received, _frame: child.send_signal(received))
        return child.wait()
    finally:
        for number, handler in saved.items():
            signal.signal(number, handler)


def run_and_record(
    argv: Sequence[str],
    *,
    target: str,
    environ: dict[str, str] | None = None,
) -> int:
    environment = dict(os.environ if environ is None else environ)
    path: Path | None = None
    stopwatch: Any = None
    context: dict[str, Any] = {}
    if not recording_disabled(environment):
        try:
            path = timings_path(environment)
            clock = _load_clock()
            context = {
                "cwd": os.getcwd(),
                "branch": _git_output("branch", "--show-current"),
                "head": _git_output("rev-parse", "--short", "HEAD"),
                "host": socket.gethostname(),
                "make_goals": _make_goals(environment),
            }
            stopwatch = clock.Stopwatch.start()
        except Exception as error:
            _warn(f"timing disabled for this run: {error}")
            stopwatch = None

    returncode = _run_child(argv)

    if stopwatch is not None and path is not None:
        exit_code = returncode if returncode >= 0 else SIGNAL_EXIT_OFFSET - returncode
        try:
            ended_at, duration = stopwatch.finish()
            record = build_record(
                target=target,
                started_at=stopwatch.start_utc,
                ended_at=ended_at,
                duration_seconds=duration,
                exit_code=exit_code,
                **context,
            )
            append_record(path, record)
        except Exception as error:
            _warn(f"could not record timing in {path}: {error}")

    if returncode < 0:
        signal.signal(-returncode, signal.SIG_DFL)
        os.kill(os.getpid(), -returncode)
    return returncode


def read_records(path: Path) -> tuple[list[dict[str, Any]], int]:
    records: list[dict[str, Any]] = []
    skipped = 0
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return records, skipped
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            _parse_iso_utc(record["started_at"])
            float(record["duration_seconds"])
            str(record["target"])
        except (ValueError, KeyError, TypeError):
            skipped += 1
            continue
        if record.get("schema") != SCHEMA:
            skipped += 1
            continue
        records.append(record)
    return records, skipped


def percentile(sorted_values: Sequence[float], fraction: float) -> float:
    rank = max(1, math.ceil(fraction * len(sorted_values)))
    return sorted_values[rank - 1]


def _format_seconds(seconds: float) -> str:
    if seconds >= 3600:
        return f"{seconds / 3600:.2f}h"
    if seconds >= 60:
        return f"{seconds / 60:.1f}m"
    return f"{seconds:.1f}s"


def render_report(
    records: Sequence[dict[str, Any]],
    *,
    now: datetime,
    days: int,
    slowest: int,
    skipped: int = 0,
    source: Path | None = None,
) -> str:
    cutoff = now - timedelta(days=days)
    recent = [record for record in records if _parse_iso_utc(record["started_at"]) >= cutoff]
    lines = [f"Make target timings, last {days} days" + (f" ({source})" if source else "")]
    if not recent:
        lines.append("No timing records in this window.")
    else:
        by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in recent:
            by_target[record["target"]].append(record)
        width = max(len("target"), max(len(name) for name in by_target))
        lines.append(f"{'target':<{width}}  {'runs':>5}  {'failed':>6}  {'median':>8}  {'p90':>8}  {'max':>8}")
        for name in sorted(by_target):
            runs = by_target[name]
            durations = sorted(float(run["duration_seconds"]) for run in runs)
            failed = sum(1 for run in runs if run.get("exit_code") != 0)
            lines.append(
                f"{name:<{width}}  {len(runs):>5}  {failed:>6}  "
                f"{_format_seconds(statistics.median(durations)):>8}  "
                f"{_format_seconds(percentile(durations, 0.9)):>8}  "
                f"{_format_seconds(durations[-1]):>8}"
            )
        if slowest > 0:
            lines.append("")
            lines.append(f"Slowest {min(slowest, len(recent))} recent runs")
            ranked = sorted(recent, key=lambda run: float(run["duration_seconds"]), reverse=True)[:slowest]
            for run in ranked:
                lines.append(
                    f"  {_format_seconds(float(run['duration_seconds'])):>8}  {run['started_at']}  "
                    f"{run['target']}  exit={run.get('exit_code')}  {run.get('branch') or '-'}@{run.get('head') or '-'}"
                )
    if skipped:
        lines.append("")
        lines.append(f"Skipped {skipped} unreadable or unrecognised line(s).")
    return "\n".join(lines)


def _command_run(arguments: argparse.Namespace) -> int:
    command = list(arguments.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print("make_timing run: a command is required after --", file=sys.stderr)
        return 2
    target = arguments.target or os.environ.get(TARGET_ENV) or UNNAMED_TARGET
    return run_and_record(command, target=target)


def _command_report(arguments: argparse.Namespace) -> int:
    path = Path(arguments.file).expanduser() if arguments.file else timings_path()
    records, skipped = read_records(path)
    now = datetime.now(timezone.utc)
    print(render_report(records, now=now, days=arguments.days, slowest=arguments.slowest, skipped=skipped, source=path))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record and report wall-clock time of make targets.")
    subcommands = parser.add_subparsers(dest="subcommand", required=True)

    run = subcommands.add_parser("run", help="Run a command, append one timing record, and exit with its status.")
    run.add_argument("--target", help=f"Target name to record (default: ${TARGET_ENV}).")
    run.add_argument("command", nargs=argparse.REMAINDER)
    run.set_defaults(handler=_command_run)

    report = subcommands.add_parser("report", help="Print per-target count, median, p90 and max.")
    report.add_argument("--days", type=int, default=30)
    report.add_argument("--slowest", type=int, default=5)
    report.add_argument("--file", help=f"Timings file (default: ${FILE_ENV} or ~/.benchbox/make-timings.jsonl).")
    report.set_defaults(handler=_command_report)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    return arguments.handler(arguments)


if __name__ == "__main__":
    sys.exit(main())
