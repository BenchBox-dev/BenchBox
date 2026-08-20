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

import datetime as _dt
import json
import os
from collections import deque
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from tests.uat.phases.report import atomic_write_text, terminal_state
from tests.uat.runner import CellResult

FAILURE_TAIL_LINES = 50
FAILURE_TAIL_CHARS = 12_000

# Sweep lifecycle markers (uat-sweep-durability-and-signal-teardown w1).
#
# Both are *separate* sentinel artifacts beside cells.jsonl -- deliberately not
# trailing rows inside cells.jsonl, so the row schema report/gate consumers
# parse stays byte-for-byte unchanged.
#
# The durable sweep writes the ``.inprogress`` marker the moment it starts
# streaming rows, and a complete ``write_cells_jsonl`` clears it and writes the
# ``.finalized`` marker at orderly end. The two together let a reader tell
# three cases apart WITHOUT changing how a marker-less legacy artifact reads:
#   * finalized present            -> sweep completed (positive signal).
#   * inprogress present, no final -> sweep was KILLED mid-run: its streamed
#                                     rows are durable but partial, so report
#                                     must reject it as green.
#   * neither marker               -> a legacy/hand-written artifact predating
#                                     the markers -- treated exactly as before
#                                     (the pinned "regenerate old artifacts"
#                                     contract, test_report_cli_without_sidecar_*).
CELLS_FINALIZED_SUFFIX = ".finalized"
CELLS_INPROGRESS_SUFFIX = ".inprogress"


class SourceInfo(Protocol):
    commit_sha: str
    commit_short_sha: str
    dirty: bool


def cells_accounting_path(cells_jsonl: Path) -> Path:
    """Sidecar path for a given cells.jsonl -- the one filename convention both writer and reader share."""
    return cells_jsonl.with_name(cells_jsonl.name + ".accounting.json")


def cells_finalized_path(cells_jsonl: Path) -> Path:
    """Path of the finalize-marker sentinel beside a given cells.jsonl (w1)."""
    return cells_jsonl.with_name(cells_jsonl.name + CELLS_FINALIZED_SUFFIX)


def cells_inprogress_path(cells_jsonl: Path) -> Path:
    """Path of the in-progress marker sentinel beside a given cells.jsonl (w1)."""
    return cells_jsonl.with_name(cells_jsonl.name + CELLS_INPROGRESS_SUFFIX)


def _render_cell_row(cell: CellResult, *, source_info: SourceInfo) -> str:
    """Render one cells.jsonl row (with trailing newline) and persist its log failure context.

    The single owner of the cells.jsonl row schema, shared by the complete
    `write_cells_jsonl` writer and the incremental `CellStreamWriter` so a
    streamed row and a batch-written row are byte-for-byte identical -- the
    final atomic `write_cells_jsonl` at orderly sweep end can then replace the
    incrementally-appended file without changing a single row's bytes.
    `_persist_cell_failure_context` is idempotent per cell log (guarded by
    `_cell_log_has_marker`), so calling it once while streaming and again at
    the batch write does not double-append the failure tail.
    """
    cell_terminal_state = terminal_state(cell)
    failure_tail = _persist_cell_failure_context(cell, terminal_state=cell_terminal_state)
    return (
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
                "load_failure_path": (str(cell.load_failure_path) if cell.load_failure_path else None),
                "throughput_check": cell.throughput_check,
                "failure_tail": failure_tail,
                "source_commit_sha": source_info.commit_sha,
                "source_commit_short_sha": source_info.commit_short_sha,
                "source_dirty": source_info.dirty,
            }
        )
        + "\n"
    )


class CellStreamWriter:
    """Incrementally append cells.jsonl rows, flushing + fsync'ing each row.

    Durability contract (uat-sweep-durability-and-signal-teardown w1): a sweep
    killed mid-run keeps every *completed* cell's row on disk, because each row
    is flushed and fsync'd at cell completion instead of being buffered in
    memory until the sweep's end (the pre-existing failure mode -- the whole
    result set was written in one batch after the last cell, so a mid-sweep
    process death lost every row). It reopens the file per append rather than
    holding a handle across the sweep: cells complete seconds-to-minutes apart
    in a serial sweep, so the open cost is negligible, and no open handle has
    to be reasoned about across the SIGTERM teardown path (w2).

    It deliberately does NOT write the finalize marker -- only a complete
    `write_cells_jsonl` does. On construction it drops the ``.inprogress``
    marker, the positive signal that a durable stream began; if the sweep is
    killed before `write_cells_jsonl` clears it, that lingering marker is how
    report tells this partial run apart from a marker-less legacy artifact.
    """

    def __init__(self, path: Path, *, source_info: SourceInfo) -> None:
        self._path = path
        self._source_info = source_info
        self.count = 0
        # A reused log directory (stable/date-only logs_dir_template or
        # log_dir_override) can still hold a previous *completed* run's stream
        # plus its `.finalized` marker. If this new run is then killed before
        # the final `write_cells_jsonl` rewrite, `cells_run_incomplete()` would
        # see the stale `.finalized` and treat the killed rerun as clean, so
        # `make uat-report` could pass a partial rerun as green. Start from an
        # empty stream and clear any old finalize marker before marking this run
        # in progress, so a partial rerun can never inherit the prior run's
        # finalized signal or its stale rows.
        path.unlink(missing_ok=True)
        cells_finalized_path(path).unlink(missing_ok=True)
        write_cells_inprogress_marker(path)

    def append(self, cell: CellResult) -> None:
        line = _render_cell_row(cell, source_info=self._source_info)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
        self.count += 1


def write_cells_inprogress_marker(cells_jsonl: Path) -> Path:
    """Write the atomic in-progress marker when a durable stream begins (w1)."""
    marker = cells_inprogress_path(cells_jsonl)
    atomic_write_text(
        marker,
        json.dumps({"started_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds")}) + "\n",
    )
    return marker


def write_cells_finalized_marker(cells_jsonl: Path, *, row_count: int) -> Path:
    """Write the atomic finalize marker for a completed cells.jsonl and clear the in-progress one (w1).

    Called from a complete `write_cells_jsonl` (and directly by tests modeling
    a finished sweep). Records the row count and an offset-aware completion
    timestamp, then removes any `.inprogress` marker so an orderly-completed run
    is never mistaken for a killed one.
    """
    marker = cells_finalized_path(cells_jsonl)
    atomic_write_text(
        marker,
        json.dumps(
            {
                "finalized_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                "row_count": int(row_count),
            }
        )
        + "\n",
    )
    cells_inprogress_path(cells_jsonl).unlink(missing_ok=True)
    return marker


def cells_are_finalized(cells_jsonl: Path) -> bool:
    """True when the finalize marker beside `cells_jsonl` exists (positive completion signal)."""
    return cells_finalized_path(cells_jsonl).exists()


def cells_run_incomplete(cells_jsonl: Path) -> bool:
    """True when a durable sweep began (`.inprogress`) but never finalized -- i.e. it was killed mid-run.

    False for a legacy/hand-written artifact that carries neither marker, so
    `make uat-report` keeps regenerating old artifacts exactly as before
    (test_report_cli_without_sidecar_defaults_unreachable_zero) -- only a
    genuinely interrupted durable run is flagged.
    """
    return cells_inprogress_path(cells_jsonl).exists() and not cells_finalized_path(cells_jsonl).exists()


def read_cells_finalized_marker(cells_jsonl: Path) -> dict[str, object] | None:
    """Return the finalize marker payload, or None when absent/unreadable."""
    marker = cells_finalized_path(cells_jsonl)
    if not marker.exists():
        return None
    try:
        with marker.open(encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def write_cells_jsonl(
    path: Path,
    cells: Iterable[CellResult],
    *,
    source_info: SourceInfo,
    skipped_unreachable_count: int = 0,
    startup_failed_count: int = 0,
    died_mid_platform_count: int = 0,
    compatibility_pruned_count: int = 0,
    early_stop_pruned_count: int = 0,
    registry_pruned_count: int = 0,
    disk_gate_disabled: bool = False,
    memory_gate_disabled: bool = False,
    container_engine: str | None = None,
    finalize: bool = True,
) -> None:
    """Write the durable per-cell result stream plus its accounting sidecar.

    This is the *complete* writer: it is called with the full result set at an
    orderly sweep end (or by a test modeling a finished sweep), so by default
    it also writes the finalize marker (`finalize=True`) that report/gate use
    to tell a finished sweep from a killed one. During a live sweep the
    orchestrator streams rows via `CellStreamWriter` first, then calls this to
    atomically replace the incrementally-written file with the identical
    authoritative content and drop the marker. Pass `finalize=False` only to
    model an unfinalized/partial run in a test.
    """
    lines = [_render_cell_row(cell, source_info=source_info) for cell in cells]
    # cells.jsonl before its sidecar -- see module docstring "Write ordering".
    atomic_write_text(path, "".join(lines))

    accounting_path = cells_accounting_path(path)
    accounting_text = (
        json.dumps(
            {
                "skipped_unreachable_count": int(skipped_unreachable_count),
                # Distinct from skipped_unreachable_count: a stack that never
                # started (managed compose-up failure) vs. a reachability
                # probe that found nothing listening. Additive field -- see
                # uat-fail-advance-consistency w3.
                "startup_failed_count": int(startup_failed_count),
                # Disjoint from both of the above: the stack started AND was
                # reachable, then stopped being reachable partway through
                # this platform's cells, so its remaining cells never ran.
                # Recorded separately so a mid-sweep stack death is not
                # laundered into either "never started" or "cell failures"
                # (uat-container-readiness-and-memory-headroom-gate).
                "died_mid_platform_count": int(died_mid_platform_count),
                # Prune counts persisted so `make uat-report` regeneration
                # reconstructs the same total_defined the live report had,
                # instead of defaulting these to 0 (which made a regenerated
                # report under-count) -- uat-report-regen-prune-accounting w1.
                # registry_pruned_count is disjoint from compatibility_pruned_count:
                # a registry/ladder drop (pruned-registry) vs a platform/benchmark
                # compatibility-RULE drop (w2).
                "compatibility_pruned_count": int(compatibility_pruned_count),
                "early_stop_pruned_count": int(early_stop_pruned_count),
                "registry_pruned_count": int(registry_pruned_count),
                "disk_gate_disabled": bool(disk_gate_disabled),
                # Companion to disk_gate_disabled: records that
                # `preflight.free_memory_min_gib: 0` turned the free-memory
                # headroom gate OFF for this sweep, so a reader can tell
                # "the gate ran and passed" from "the gate never ran"
                # instead of reading a clean sweep as evidence of headroom.
                # Additive field -- see
                # uat-container-readiness-and-memory-headroom-gate w2.
                "memory_gate_disabled": bool(memory_gate_disabled),
                # Resolved engine binary (docker/mocker/...) at sweep start --
                # additive field, None on older artifacts and on sweeps whose
                # engine resolution failed. See uat-container-engine-routing
                # w2.
                "container_engine": container_engine,
            }
        )
        + "\n"
    )
    atomic_write_text(accounting_path, accounting_text)

    # Finalize marker last: rows and sidecar are on disk before the sweep is
    # declared complete, so a reader that sees the marker is guaranteed the
    # full stream + sidecar preceded it (uat-sweep-durability-and-signal-teardown w1).
    if finalize:
        write_cells_finalized_marker(path, row_count=len(lines))


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
                    load_failure_path=(
                        Path(payload["load_failure_path"]) if payload.get("load_failure_path") else None
                    ),
                )
            )
    return cells


def read_accounting_sidecar(cells_jsonl: Path) -> tuple[dict[str, object], bool]:
    """Read the accounting sidecar's raw JSON payload, if present and parseable.

    Returns ``(payload, sidecar_present)``: ``({}, False)`` when the sidecar
    is absent or unreadable (older artifacts predate it -- every count is
    then *assumed* 0, not confirmed), and ``(payload, True)`` when it was
    read successfully. This is the single read shared by every consumer
    that needs more than one field (e.g. `make uat-report` reads
    skipped_unreachable_count and startup_failed_count from one call), so
    all consumers agree on what "sidecar present" means (exists AND parses
    as JSON) and a multi-count caller does not re-read the file per count.
    """
    sidecar = cells_accounting_path(cells_jsonl)
    if not sidecar.exists():
        return {}, False
    try:
        with sidecar.open(encoding="utf-8") as fh:
            payload = json.load(fh)
        if not isinstance(payload, dict):
            # Parses as JSON but isn't a mapping (e.g. an array) -- not a
            # sidecar this schema can have written. Treat like a missing
            # sidecar rather than handing callers a payload whose .get()
            # would raise.
            return {}, False
        return payload, True
    except (OSError, ValueError, TypeError):
        return {}, False


def coerce_accounting_count(value: object, default: int = 0) -> int:
    """Best-effort ``int`` coercion for a sidecar count field.

    A sidecar can parse as a JSON mapping yet still carry a malformed count
    (``null``, a non-numeric string, a nested object) -- from manual editing,
    a future schema change, or a truncated write. That must not crash
    `make uat-report`; it falls back to ``default`` like an absent sidecar
    would, rather than propagating ``int()``'s ``TypeError``/``ValueError``.
    """
    return coerce_accounting_count_with_validity(value, default)[0]


def coerce_accounting_count_with_validity(value: object, default: int = 0) -> tuple[int, bool]:
    """Return a coerced count and whether the source value was valid."""
    try:
        return int(value), True  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default, False


def read_skipped_unreachable_sidecar(cells_jsonl: Path) -> tuple[int, bool]:
    """Read the skipped-unreachable count persisted alongside ``cells.jsonl``.

    Returns ``(count, sidecar_present)``: ``(0, False)`` when the sidecar is
    absent or unreadable (older artifacts predate it -- the count is
    *assumed* 0, not confirmed), and ``(count, True)`` when a sidecar was
    read successfully. Callers thread ``sidecar_present`` into
    ``write_report(unreachable_count_is_estimated=...)`` so a regenerated
    report can distinguish "confirmed unreachable=0" from "sidecar missing,
    unreachable assumed 0." Single-count convenience over
    ``read_accounting_sidecar``; callers needing several counts should call
    that directly instead of stacking one read per count.
    """
    payload, present = read_accounting_sidecar(cells_jsonl)
    return coerce_accounting_count(payload.get("skipped_unreachable_count", 0)), present


def update_accounting_sidecar(cells_jsonl: Path, **fields: object) -> bool:
    """Merge additional keys into an already-written accounting sidecar.

    Returns ``True`` when a sidecar existed and was patched in place,
    ``False`` when there was nothing to patch (no sidecar written yet for
    this ``cells.jsonl``). The false case is reachable when a phase that
    wants to record accounting (e.g. explorer_smoke's node-missing skip --
    see uat-fail-advance-consistency w2) runs in a sweep whose `phases:`
    list never ran `execute`, so no sidecar was ever created. Callers should
    not fabricate a sidecar from scratch here: a sidecar's presence is the
    signal that its counts are confirmed (see
    ``read_skipped_unreachable_sidecar``), and a sidecar containing only a
    caller's opportunistic fields (with the execute-derived counts
    defaulted to 0) would misrepresent an unconfirmed 0 as a real one.
    """
    payload, present = read_accounting_sidecar(cells_jsonl)
    if not present:
        return False
    payload.update(fields)
    accounting_path = cells_accounting_path(cells_jsonl)
    atomic_write_text(accounting_path, json.dumps(payload) + "\n")
    return True


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
