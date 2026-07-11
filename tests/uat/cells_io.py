"""cells.jsonl + accounting-sidecar codec: single schema definition.

Before this module existed, the writer lived in
`tests.uat.orchestrator._write_cells_jsonl` and the reader lived in
`tests.uat._cli` (`_read_skipped_unreachable_sidecar` plus inline JSONL
parsing in `_handle_report`), with no shared schema definition between the
two -- see uat-execute-path-unification w1. This module is now the single
owner: the durable sweep (`tests.uat.orchestrator`) and `make uat-execute`
(`tests.uat._cli`) both write through it, and `make uat-report`
(`tests.uat._cli`) reads through it.

Sidecar rationale: skipped-unreachable cells are `Cell` records (a
compatibility/reachability decision made before a cell ever runs), not
`CellResult` rows, and so cannot appear in the `cells.jsonl` stream. Their
count -- and the `disk_gate_disabled` flag recorded by
uat-disk-gate-always-on w2 -- are persisted in a sidecar
(`<cells.jsonl>.accounting.json`) next to the stream instead.

Write ordering: `cells.jsonl` is written before its accounting sidecar. If a
crash lands between the two writes, a reader sees either no `cells.jsonl`
yet (nothing to combine) or a `cells.jsonl` without a sidecar yet
(`read_skipped_unreachable_sidecar` treats a missing sidecar as an
*estimated* `skipped_unreachable_count=0`, not a confirmed one). The reverse
order could leave a fresh sidecar beside a stale cell stream, which
`make uat-report` would silently combine as if consistent. See
uat-resume-retirement-artifact-durability w4.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from tests.uat.phases.report import atomic_write_text, terminal_state
from tests.uat.runner import CellResult

FAILURE_TAIL_LINES = 50
FAILURE_TAIL_CHARS = 12_000


class SourceInfo(Protocol):
    commit_sha: str
    commit_short_sha: str
    dirty: bool


def cells_accounting_path(cells_jsonl: Path) -> Path:
    """Sidecar path for a given cells.jsonl -- the one filename convention both writer and reader share."""
    return cells_jsonl.with_name(cells_jsonl.name + ".accounting.json")


def write_cells_jsonl(
    path: Path,
    cells: Iterable[CellResult],
    *,
    source_info: SourceInfo,
    skipped_unreachable_count: int = 0,
    disk_gate_disabled: bool = False,
) -> None:
    """Write the durable per-cell result stream plus its accounting sidecar."""
    lines: list[str] = []
    for cell in cells:
        cell_terminal_state = terminal_state(cell)
        failure_tail = _persist_cell_failure_context(cell, terminal_state=cell_terminal_state)
        lines.append(
            json.dumps(
                {
                    "platform": cell.platform,
                    "benchmark": cell.benchmark,
                    "scale": cell.scale,
                    "status": cell.status,
                    "terminal_state": cell_terminal_state,
                    "submit_terminal_state": cell.submit_terminal_state,
                    "timed_out": cell.status == "timed-out",
                    "exit_code": cell.exit_code,
                    "elapsed_s": cell.elapsed_s,
                    "log_path": str(cell.log_path),
                    "result_path": (str(cell.result_path) if cell.result_path else None),
                    "throughput_check": cell.throughput_check,
                    "failure_tail": failure_tail,
                    "source_commit_sha": source_info.commit_sha,
                    "source_commit_short_sha": source_info.commit_short_sha,
                    "source_dirty": source_info.dirty,
                }
            )
            + "\n"
        )
    # cells.jsonl before its sidecar -- see module docstring "Write ordering".
    atomic_write_text(path, "".join(lines))

    accounting_path = cells_accounting_path(path)
    accounting_text = (
        json.dumps(
            {
                "skipped_unreachable_count": int(skipped_unreachable_count),
                "disk_gate_disabled": bool(disk_gate_disabled),
            }
        )
        + "\n"
    )
    atomic_write_text(accounting_path, accounting_text)


def read_cells_jsonl(path: Path) -> list[CellResult]:
    """Read a durable cells.jsonl stream back into `CellResult` rows.

    Reconstructs only the fields `CellResult` carries; the artifact-only
    annotations written by `write_cells_jsonl` (terminal_state, timed_out,
    failure_tail, source_*) are durable-record metadata, not part of the
    `CellResult` contract, and are intentionally not round-tripped here --
    matches the parsing `make uat-report` (`_handle_report`) has always done.
    """
    cells: list[CellResult] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            payload = json.loads(line)
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
                    throughput_check=payload.get("throughput_check"),
                )
            )
    return cells


def read_skipped_unreachable_sidecar(cells_jsonl: Path) -> tuple[int, bool]:
    """Read the skipped-unreachable count persisted alongside ``cells.jsonl``.

    Returns ``(count, sidecar_present)``: ``(0, False)`` when the sidecar is
    absent or unreadable (older artifacts predate it -- the count is
    *assumed* 0, not confirmed), and ``(count, True)`` when a sidecar was
    read successfully. Callers thread ``sidecar_present`` into
    ``write_report(unreachable_count_is_estimated=...)`` so a regenerated
    report can distinguish "confirmed unreachable=0" from "sidecar missing,
    unreachable assumed 0."
    """
    sidecar = cells_accounting_path(cells_jsonl)
    if not sidecar.exists():
        return 0, False
    try:
        with sidecar.open(encoding="utf-8") as fh:
            payload = json.load(fh)
        return int(payload.get("skipped_unreachable_count", 0)), True
    except (OSError, ValueError, TypeError):
        return 0, False


def _persist_cell_failure_context(cell: CellResult, *, terminal_state: str) -> str:
    if cell.status == "passed" and cell.result_path is not None:
        return ""
    log_path = Path(cell.log_path)
    tail = _cell_log_tail(log_path)
    if log_path.exists():
        if not _cell_log_has_marker(log_path):
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(
                    f"# UAT_TERMINAL_STATE terminal_state={terminal_state} "
                    f"status={cell.status} exit_code={cell.exit_code} "
                    f"result_path={cell.result_path or ''}\n"
                )
                fh.write(f"# UAT_FAILURE_TAIL_START max_lines={FAILURE_TAIL_LINES}\n")
                fh.write((tail or "(no subprocess output captured)") + "\n")
                fh.write("# UAT_FAILURE_TAIL_END\n")
    return tail


def _cell_log_tail(log_path: Path) -> str:
    if not log_path.exists():
        return ""
    lines: deque[str] = deque(maxlen=FAILURE_TAIL_LINES)
    with log_path.open(encoding="utf-8", errors="replace") as fh:
        for raw_line in fh:
            line = raw_line.rstrip("\n")
            if line.startswith("# UAT_"):
                break
            if line.startswith("# "):
                continue
            if line.strip():
                lines.append(line)
    tail = "\n".join(lines)
    if len(tail) > FAILURE_TAIL_CHARS:
        return tail[-FAILURE_TAIL_CHARS:]
    return tail


def _cell_log_has_marker(log_path: Path) -> bool:
    with log_path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("# UAT_TERMINAL_STATE "):
                return True
    return False
