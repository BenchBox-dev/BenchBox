from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .verdict import Finding, Verdict

INLINE = "inline"
_LINE_SUFFIX = re.compile(r":\d+(?:-\d+)?$")


@dataclass(frozen=True)
class Trace:
    turns: int | None = None
    reads: tuple[str, ...] = ()


def codex_events(stdout: str) -> list[dict]:
    events = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def codex_errors(stdout: str) -> str:
    lines = []
    for event in codex_events(stdout):
        error = event.get("error") if isinstance(event.get("error"), dict) else event
        if event.get("type") in ("error", "turn.failed") and isinstance(error.get("message"), str):
            lines.append(f"ERROR: {error['message']}")
    return "\n".join(lines)


def trace(harness: str, stdout: str) -> Trace:
    if harness == "codex":
        reads = []
        for event in codex_events(stdout):
            item = event.get("item")
            if (
                event.get("type") == "item.completed"
                and isinstance(item, dict)
                and item.get("type") == "command_execution"
                and str(item.get("exit_code")) == "0"
            ):
                reads.append(f"{item.get('command') or ''}\n{item.get('aggregated_output') or ''}")
        return Trace(reads=tuple(reads))
    if harness == "claude":
        try:
            envelope = json.loads(stdout)
        except json.JSONDecodeError:
            return Trace()
        turns = envelope.get("num_turns") if isinstance(envelope, dict) else None
        return Trace(turns=turns if isinstance(turns, int) and not isinstance(turns, bool) else None)
    return Trace()


def relative(path: str, workspace: Path) -> str:
    path = _LINE_SUFFIX.sub("", path)
    root = os.path.realpath(workspace)
    candidate = os.path.normpath(path if os.path.isabs(path) else os.path.join(root, path))
    if candidate.startswith(root + os.sep):
        candidate = candidate[len(root) + 1 :]
    elif os.path.realpath(candidate).startswith(root + os.sep):
        candidate = os.path.realpath(candidate)[len(root) + 1 :]
    return candidate.removeprefix("./")


def _line_count(workspace: Path, path: str) -> int | None:
    root = os.path.realpath(workspace)
    target = os.path.realpath(os.path.join(root, path))
    if not target.startswith(root + os.sep) or not os.path.isfile(target):
        return None
    with open(target, "rb") as handle:
        data = handle.read()
    return max(1, data.count(b"\n") + (0 if data.endswith(b"\n") or not data else 1))


def _citation_error(finding: Finding, workspace: Path) -> str | None:
    count = _line_count(workspace, finding.file)
    if count is None:
        return f"a defect cites {finding.file}, which is not a file in the head commit"
    last = finding.end_line or finding.line
    if last > count:
        return f"a defect cites {finding.file}:{last}, past its last line ({count})"
    return None


def check(
    verdict: Verdict,
    *,
    harness: str,
    brief_mode: str,
    workspace: Path,
    required: Iterable[str],
    run: Trace,
) -> str | None:
    for finding in verdict.defects:
        error = _citation_error(finding, workspace)
        if error is not None:
            return error
    if brief_mode == INLINE:
        return None
    if harness == "claude" and (run.turns is None or run.turns <= 1):
        return "the reviewer read no files: it answered a file-list brief in a single turn"
    needed = sorted(set(required))
    if harness == "codex" and not any(any(path in text for path in needed) if needed else True for text in run.reads):
        return "the reviewer read no files: its command trace shows no successful read of the changed files"
    if verdict.defects:
        return None
    examined = {relative(path, workspace) for path in verdict.files_examined}
    missing = [path for path in needed if path not in examined]
    if missing:
        shown = ", ".join(missing[:5]) + (f" and {len(missing) - 5} more" if len(missing) > 5 else "")
        return f"the reviewer found no defects but did not examine {shown}"
    return None
