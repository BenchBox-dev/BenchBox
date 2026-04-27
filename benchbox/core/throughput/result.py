"""Shared result model for TPC throughput tests.

``ThroughputStreamResult`` is the unified single-stream result type - both
``TPCHThroughputStreamResult`` and ``TPCDSThroughputStreamResult`` were
identical dataclasses; this replaces them.  Callers in each spec module
define a backward-compatibility alias so existing import paths are unchanged.

``ThroughputResult`` is the shared base for the per-test result.  It holds
every field that TPC-H and TPC-DS share; the spec-specific ``config`` field
lives on the subclasses in each spec's module, added via ``kw_only=True`` so
the all-keyword callers are unaffected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ThroughputStreamResult:
    """Result of a single concurrent throughput test stream.

    Shared by TPC-H and TPC-DS.  Each spec module exports a
    backward-compat alias (``TPCHThroughputStreamResult``,
    ``TPCDSThroughputStreamResult``).
    """

    stream_id: int
    start_time: float
    end_time: float
    duration: float
    queries_executed: int
    queries_successful: int
    queries_failed: int
    query_results: list[dict[str, Any]] = field(default_factory=list)
    success: bool = True
    error: Optional[str] = None


@dataclass
class ThroughputResult:
    """Base result dataclass for TPC throughput tests.

    Contains every field shared between TPC-H and TPC-DS.  Spec-specific
    subclasses add ``config`` as a ``kw_only=True`` field so all-keyword
    construction still works:

    .. code-block:: python

        @dataclass
        class TPCHThroughputTestResult(ThroughputResult):
            config: TPCHThroughputTestConfig = field(kw_only=True)

            @property
            def scale_factor(self) -> float:
                return self.config.scale_factor

    All existing field names on ``TPCHThroughputTestResult`` and
    ``TPCDSThroughputTestResult`` are preserved; no public API changes.
    """

    start_time: str
    end_time: str
    total_time: float
    throughput_at_size: float
    streams_executed: int
    streams_successful: int
    stream_results: list[ThroughputStreamResult] = field(default_factory=list)
    query_throughput: float = 0.0
    success: bool = True
    errors: list[str] = field(default_factory=list)
