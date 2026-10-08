from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path

from .verdict import Finding, Verdict

INLINE = "inline"
_LINE_SUFFIX = re.compile(r":\d+(?:-\d+)?$")


TRACED = ("claude", "codex")
CLAUDE_READERS = ("Read", "Grep")
CITATION_PREFIX = "Citation not found in the head commit"


@dataclass(frozen=True)
class Trace:
    reads: tuple[str, ...] = ()


def json_lines(stdout: str) -> list[dict]:
    events = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


codex_events = json_lines


def codex_errors(stdout: str) -> str:
    lines = []
    for event in codex_events(stdout):
        error = event.get("error") if isinstance(event.get("error"), dict) else event
        if event.get("type") in ("error", "turn.failed") and isinstance(error.get("message"), str):
            lines.append(f"ERROR: {error['message']}")
    return "\n".join(lines)


def _claude_reads(stdout: str) -> tuple[str, ...]:
    uses: dict[str, str] = {}
    succeeded: set[str] = set()
    for event in json_lines(stdout):
        content = (event.get("message") or {}).get("content")
        for block in content if isinstance(content, list) else ():
            if not isinstance(block, dict):
                continue
            if event.get("type") == "assistant" and block.get("type") == "tool_use":
                if block.get("name") in CLAUDE_READERS and isinstance(block.get("input"), dict):
                    target = block["input"].get("file_path") or block["input"].get("path") or ""
                    uses[str(block.get("id"))] = str(target)
            elif event.get("type") == "user" and block.get("type") == "tool_result" and not block.get("is_error"):
                succeeded.add(str(block.get("tool_use_id")))
    return tuple(target for use, target in uses.items() if use in succeeded and target)


def trace(harness: str, stdout: str) -> Trace:
    if harness == "codex":
        reads = []
        for event in json_lines(stdout):
            item = event.get("item")
            if (
                event.get("type") == "item.completed"
                and isinstance(item, dict)
                and item.get("type") == "command_execution"
                and str(item.get("exit_code")) == "0"
            ):
                reads.append(str(item.get("command") or ""))
        return Trace(tuple(reads))
    if harness == "claude":
        return Trace(_claude_reads(stdout))
    return Trace()


def _names(command: str, path: str, workspace: Path) -> bool:
    root = re.escape(os.path.realpath(workspace) + os.sep)
    pattern = rf"(?:(?<![\w./-])(?:\./)?|{root}){re.escape(path)}(?![\w./-])"
    return re.search(pattern, command) is not None


def unread(harness: str, required: Iterable[str], run: Trace, workspace: Path) -> list[str]:
    if harness == "claude":
        read = {relative(target, workspace) for target in run.reads}
        return [path for path in required if path not in read]
    if harness == "codex":
        return [path for path in required if not any(_names(command, path, workspace) for command in run.reads)]
    return []


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
        return f"{finding.file} is not a file in the head commit"
    last = finding.end_line or finding.line
    if last > count:
        return f"{finding.file} has {count} lines, so line {last} does not exist"
    return None


def mark_citations(verdict: Verdict, workspace: Path) -> Verdict:
    marked = []
    for finding in verdict.defects:
        error = _citation_error(finding, workspace)
        detail = f"{CITATION_PREFIX}: {error}. {finding.detail}".rstrip() if error else finding.detail
        marked.append(replace(finding, detail=detail))
    return replace(verdict, defects=tuple(marked))


def _shown(paths: list[str]) -> str:
    return ", ".join(paths[:5]) + (f" and {len(paths) - 5} more" if len(paths) > 5 else "")


def check(
    verdict: Verdict,
    *,
    harness: str,
    brief_mode: str,
    workspace: Path,
    required: Iterable[str],
    run: Trace,
) -> str | None:
    if brief_mode == INLINE or verdict.defects:
        return None
    needed = sorted(set(required))
    if harness in TRACED:
        if not run.reads:
            return "the reviewer found no defects but its trace shows no successful file read"
        missing = unread(harness, needed, run, workspace)
        if missing:
            return f"the reviewer found no defects but its trace shows no read of {_shown(missing)}"
    examined = {relative(path, workspace) for path in verdict.files_examined}
    missing = [path for path in needed if path not in examined]
    if missing:
        return f"the reviewer found no defects but did not examine {_shown(missing)}"
    return None
