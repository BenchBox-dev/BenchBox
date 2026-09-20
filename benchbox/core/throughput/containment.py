"""Phase-boundary containment for throughput outstanding work.

A combined benchmark runner (the shared power -> throughput -> maintenance
sequencer, the TPC-DS official benchmark) must not start maintenance or
another measured phase -- nor reuse the shared resources for measured work --
while a prior throughput phase still has outstanding (leaked, still-running)
streams. This module owns that gate plus the bounded termination observation
that lifts it.

Ownership recap (see runner.py): each stream's own ``stream_fn`` owns its
database connection and closes it in its own ``finally`` whenever the worker
thread eventually ends. ``StreamRunner`` never touches stream connections; it
owns only the worker futures, whose handles ride on the result as the private
``_outstanding_futures`` attribute (in-process only, never serialized --
bundle builders pick explicit fields). Cleanup state on the result is plain
data: ``outstanding_stream_ids``, ``cancelled_stream_ids``,
``outstanding_notes``, ``cleanup_state``.
"""

from __future__ import annotations

import concurrent.futures
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PhaseBoundaryDecision:
    """Whether the next phase may start after a throughput phase."""

    proceed: bool
    reason: str
    outstanding_stream_ids: list[int] = field(default_factory=list)


def check_phase_boundary(throughput_result: Any | None) -> PhaseBoundaryDecision:
    """Decide whether a later phase may start after a throughput phase.

    Proceeds unless the result carries explicit outstanding-work evidence
    (a list/tuple of outstanding stream ids). Results without that evidence
    -- None (phase never ran), legacy dicts, or healthy results -- proceed:
    only explicit evidence contains, never a missing attribute.

    Args:
        throughput_result: The throughput phase result, if any.

    Returns:
        PhaseBoundaryDecision naming the outstanding streams when contained.
    """
    outstanding = getattr(throughput_result, "outstanding_stream_ids", None)
    if not isinstance(outstanding, (list, tuple)) or not outstanding:
        return PhaseBoundaryDecision(
            proceed=True,
            reason="No outstanding throughput work; phase boundary clear.",
        )
    outstanding_ids = [int(stream_id) for stream_id in outstanding]
    return PhaseBoundaryDecision(
        proceed=False,
        reason=(
            f"Throughput phase has outstanding work on streams {outstanding_ids}: "
            f"those workers may still be executing queries and holding resources. "
            f"Refusing the next phase until termination is observed."
        ),
        outstanding_stream_ids=outstanding_ids,
    )


def await_quiescence(throughput_result: Any, timeout: float) -> bool:
    """Wait (bounded) until outstanding streams terminate, then release the boundary.

    Observes the worker futures retained by ``StreamRunner.execute()``. When
    every outstanding stream has terminated, the result's outstanding state is
    cleared, ``cleanup_state`` becomes ``"quiesced"``, and True is returned so
    a later ``check_phase_boundary`` proceeds. On timeout the outstanding
    state is pruned to the still-running remainder and False is returned --
    the boundary stays contained.

    Args:
        throughput_result: The throughput phase result carrying outstanding work.
        timeout: Maximum seconds to wait. Always bounded; never omit it to
            join unconditionally.

    Returns:
        True when no outstanding work remains, False otherwise (including
        when there are no observable worker handles -- termination then
        cannot be proven, so containment holds).
    """
    handles: dict[int, concurrent.futures.Future] = dict(getattr(throughput_result, "_outstanding_futures", None) or {})
    if not handles:
        return not bool(getattr(throughput_result, "outstanding_stream_ids", None) or [])

    done, not_done = concurrent.futures.wait(handles.values(), timeout=timeout)
    done_ids = {stream_id for stream_id, future in handles.items() if future in done}
    remaining = {stream_id: future for stream_id, future in handles.items() if future in not_done}

    outstanding = getattr(throughput_result, "outstanding_stream_ids", None)
    if isinstance(outstanding, list):
        remaining_ids = [stream_id for stream_id in outstanding if stream_id in remaining]
        outstanding[:] = remaining_ids

    resources = getattr(throughput_result, "outstanding_notes", None)
    if isinstance(resources, list) and done_ids:
        resources.append(f"Termination observed for streams {sorted(done_ids)}.")

    throughput_result._outstanding_futures = remaining  # type: ignore[attr-defined]

    if remaining:
        return False

    if isinstance(getattr(throughput_result, "cleanup_state", None), str):
        throughput_result.cleanup_state = "quiesced"
    logger.debug("Throughput outstanding work quiesced; phase boundary released.")
    return True
