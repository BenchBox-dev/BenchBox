#!/usr/bin/env python3
"""Label every TPC-DS DataFrame-versus-SQL divergence by its likely cause.

This is a report, not a gate. It runs the same per-query comparison as the staged cross-surface
gate (``benchbox.core.equivalence.cross_surface``) at one or more scale factors, and for every
cell (query, DataFrame family) that diverges it records the cause and the full divergence
text as evidence. It does not change a verdict, the comparator, or any gate.

Causes:

``parameter drift``
    The cell matches when the implementation runs on the values dsqgen put in the SQL (the adapter
    binding) but diverges on the defaults file. The gate already applies the binding for the queries
    that have an adapter, so this shows up as a cell that the adapter fixed.
``unbound (no adapter)``
    The query has no adapter, so the DataFrame side runs on the defaults file while the SQL carries
    dsqgen's values. A value or row-count difference cannot be told apart from drift until the query
    has an adapter. The detail-based label is kept as the secondary cause. NULL, dtype and ordering labels
    are evidence on their own and are not replaced by this one.
``null order``
    The same rows come back but a NULL sits at a different position in the ORDER BY. Needs the rows;
    from the detail text alone, an ORDER BY key that is NULL on one side and a value on the other.
``null value``
    A NULL against a value (a number, say) in a result cell. That is a NULL-handling difference in the
    value, not ORDER BY placement.
``null vs nan``
    A NULL against NaN. The DataFrame side represents a missing value as NaN where SQL has NULL.
``int vs float``
    The same number as an integer on one side and a float on the other (``31`` against ``31.0``). A
    dtype difference, not a value difference.
``decimal/float``
    A value or an ORDER BY key that differs only by float noise (relative difference under 1e-6).
``order``
    The same rows (compared as a multiset, with integers and floats of equal value treated as equal)
    come back in a different order. Needs the rows, which the detail text does not carry.

``row count/logic``
    A different number of rows or columns, or a value that differs by more than noise, or an ORDER
    BY mismatch where the rows themselves differ (so it is not only an ordering difference).
``flaky``
    With ``--repeat N``, the cell did not give the same outcome on every run.
``error``
    The comparison raised. A Polars ``PanicException`` is a ``BaseException`` and is recorded here too.
``unclassified``
    The detail text fits none of the above.

A tie between rows is never labelled: the comparator already reshuffles tie groups, so a reported ORDER BY
key mismatch is a mismatch between keys that are not equal. A tie that comes and goes between runs shows up
as ``flaky`` with ``--repeat``. Tie canonicalization belongs to the comparator and only for causes shown to
be ties.

Usage::

    uv run python scripts/tpcds_divergence_report.py --scale 0.03 --scale 0.1 --out report.md --json report.json
    uv run python scripts/tpcds_divergence_report.py --scale 0.03 --repeat 5 --query 36

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark(TM) DS (TPC-DS) - Copyright (c) Transaction Processing Performance Council

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import json
import re
import sys
import tempfile
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

PARAMETER_DRIFT = "parameter drift"
UNBOUND = "unbound (no adapter)"
NULL_ORDER = "null order"
NULL_VALUE = "null value"
NULL_VS_NAN = "null vs nan"
INT_VS_FLOAT = "int vs float"
ORDER = "order"
DECIMAL_FLOAT = "decimal/float"
ROW_COUNT_LOGIC = "row count/logic"
FLAKY = "flaky"
ERROR = "error"
UNCLASSIFIED = "unclassified"

FLOAT_NOISE = 1e-6

_ORDER_KEY = re.compile(
    r"ORDER BY key mismatch at position (\d+)\. Original key: (.*?), Variant key: (.*?) \(order-key", re.S
)
_VALUE = re.compile(
    r"Value mismatch at row (\d+), column (\d+)\. Original: (.*?), Variant: (.*?)(?:, Tolerance:|; also columns|$)",
    re.S,
)
_ROW_COUNT = re.compile(r"Row count mismatch\. Original: (\d+), Variant: (\d+)")
_COLUMN_COUNT = re.compile(r"Column count mismatch")
_HARNESS_FAILURES = ("error:", "reference query failed:")
_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?$")
_INTEGER = re.compile(r"^-?\d+$")


def _number(text: str) -> float | None:
    text = text.strip().strip("'\"")
    return float(text) if _NUMBER.match(text) else None


def _close(left: float, right: float) -> bool:
    scale = max(abs(left), abs(right))
    return scale == 0 or abs(left - right) / scale < FLOAT_NOISE or abs(left - right) < 1e-10


def _key_cells(text: str) -> list[str]:
    """Split a printed key tuple such as ``(None, 7008009)`` into its cell texts."""
    inner = text.strip()
    if inner.startswith("(") and inner.endswith(")"):
        inner = inner[1:-1]
    return [part.strip() for part in re.split(r",\s*(?=(?:[^']*'[^']*')*[^']*$)", inner)]


def _text(cell: str) -> str:
    return cell.strip().strip("'\"")


def _canonical(value: Any) -> Any:
    """A hashable form of one cell in which an integer and a float of equal value are the same."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return "nan" if value != value else float(f"{value:.9g}")
    return value


def _same_rows(rows: tuple[Sequence[tuple], Sequence[tuple]] | None) -> bool | None:
    """Whether the reference and the DataFrame result hold the same rows, ignoring their order.

    ``None`` when the rows were not captured, so the question cannot be answered.
    """
    if rows is None:
        return None
    reference, candidate = rows
    return Counter(tuple(_canonical(v) for v in row) for row in reference) == Counter(
        tuple(_canonical(v) for v in row) for row in candidate
    )


def _null_difference(a: str, b: str) -> str | None:
    """``NULL_VS_NAN`` or ``NULL_VALUE`` when exactly one of two printed cells is NULL, else ``None``."""
    if (a == "None") == (b == "None"):
        return None
    other = _text(b if a == "None" else a)
    return NULL_VS_NAN if other.lower() == "nan" else NULL_VALUE


def _number_difference(a: str, b: str, what: str) -> tuple[str, str] | None:
    """Label two printed cells that are numbers equal within float noise, else ``None``."""
    left, right = _number(a), _number(b)
    if left is None or right is None or not _close(left, right):
        return None
    if left == right and bool(_INTEGER.match(_text(a))) != bool(_INTEGER.match(_text(b))):
        return INT_VS_FLOAT, f"{what} is an integer on one side and a float on the other ({a} against {b})"
    return DECIMAL_FLOAT, f"{what} differs by float noise ({a} against {b})"


def label_detail(detail: str, rows: tuple[Sequence[tuple], Sequence[tuple]] | None = None) -> tuple[str, str]:
    """Return ``(cause, why)`` for one full divergence detail string.

    ``rows`` is the ``(reference, candidate)`` result pair when it was captured. The detail text alone
    cannot show that the same rows came back in a different order, so ``order`` needs it.
    """
    if _COLUMN_COUNT.search(detail):
        return ROW_COUNT_LOGIC, "different number of columns"
    match = _ROW_COUNT.search(detail)
    if match:
        return ROW_COUNT_LOGIC, f"{match.group(1)} rows against {match.group(2)}"
    match = _ORDER_KEY.search(detail)
    if match:
        original, variant = _key_cells(match.group(2)), _key_cells(match.group(3))
        pairs = [(a, b) for a, b in zip(original, variant) if a != b]
        same_rows = _same_rows(rows)
        if pairs:
            a, b = pairs[0]
            null = _null_difference(a, b)
            if null == NULL_VS_NAN:
                return (
                    NULL_VS_NAN,
                    f"first differing key cell is NULL on one side and NaN on the other ({a} against {b})",
                )
            if null and same_rows is not False:
                return NULL_ORDER, f"first differing key cell is NULL on one side ({a} against {b})"
            if null:
                return NULL_VALUE, f"first differing key cell is NULL on one side and the rows differ ({a} against {b})"
            number = _number_difference(a, b, "order key")
            if number:
                return number
        if same_rows:
            return ORDER, "the same rows in a different order"
        if same_rows is False:
            return ROW_COUNT_LOGIC, "the rows differ, not only their order"
        return UNCLASSIFIED, "order key differs and the keys do not show NULL placement or float noise"
    match = _VALUE.search(detail)
    if match:
        a, b = match.group(3).strip(), match.group(4).strip()
        null = _null_difference(a, b)
        if null:
            return null, f"value is NULL on one side ({a} against {b})"
        number = _number_difference(a, b, "value")
        if number:
            return number
        if _number(a) is not None and _number(b) is not None:
            return ROW_COUNT_LOGIC, f"values differ by more than noise ({a} against {b})"
        return UNCLASSIFIED, f"non-numeric values differ ({a} against {b})"
    return UNCLASSIFIED, "detail text not recognised"


def classify_cell(
    detail: str,
    *,
    adapted: bool,
    drift_fixed: bool = False,
    outcomes: Sequence[str] | None = None,
    error: str | None = None,
    rows: tuple[Sequence[tuple], Sequence[tuple]] | None = None,
) -> dict[str, str]:
    """Cause record for one divergent cell.

    ``adapted`` says the query has a parameter adapter. ``outcomes`` are the per-run detail strings
    when the cell was repeated; a cell whose runs differ is flaky whatever the detail says. ``rows`` is
    the captured ``(reference, candidate)`` result pair, when there is one.
    """
    if outcomes is not None and len(set(outcomes)) > 1:
        return {
            "cause": FLAKY,
            "why": f"{len(set(outcomes))} different outcomes in {len(outcomes)} runs",
            "secondary": "",
        }
    if error:
        return {"cause": ERROR, "why": error, "secondary": ""}
    if drift_fixed:
        return {
            "cause": PARAMETER_DRIFT,
            "why": "diverges on the defaults, matches on dsqgen's values",
            "secondary": "",
        }
    cause, why = label_detail(detail, rows)
    if not adapted and cause in {ROW_COUNT_LOGIC, UNCLASSIFIED, DECIMAL_FLOAT}:
        # NULL handling, dtype and ordering differences are evidence on their own; anything else may just be
        # different parameters.
        return {"cause": UNBOUND, "why": f"no adapter, so parameters are not bound ({why})", "secondary": cause}
    return {"cause": cause, "why": why, "secondary": ""}


@dataclasses.dataclass
class Cell:
    scale: float
    backend: str
    query: str
    status: str
    cause: str = ""
    why: str = ""
    secondary: str = ""
    evidence: str = ""
    adapted: bool = False
    runs: int = 1


class _RowCapture:
    """The reference rows and the DataFrame rows of one comparison, kept to tell an ordering difference from a value one."""

    def __init__(self) -> None:
        self.reference: list[tuple] | None = None
        self.candidate: list[tuple] | None = None

    @property
    def rows(self) -> tuple[list[tuple], list[tuple]] | None:
        if self.reference is None or self.candidate is None:
            return None
        return self.reference, self.candidate


@contextlib.contextmanager
def _capturing(xs: Any, capture: _RowCapture | None) -> Iterator[None]:
    """Record the rows ``xs`` fetches and materializes during one comparison, without changing them."""
    fetch = getattr(xs, "fetch_reference_rows", None)
    materialize = getattr(xs, "materialize_rows", None)
    if capture is None or fetch is None or materialize is None:
        yield
        return

    def fetch_recorded(*args: Any, **kwargs: Any) -> Any:
        rows = fetch(*args, **kwargs)
        if capture.reference is None:  # the first fetch is the reference; later ones are the harness's probes
            capture.reference = rows
        return rows

    def materialize_recorded(*args: Any, **kwargs: Any) -> Any:
        capture.candidate = rows = materialize(*args, **kwargs)
        return rows

    xs.fetch_reference_rows, xs.materialize_rows = fetch_recorded, materialize_recorded
    try:
        yield
    finally:
        xs.fetch_reference_rows, xs.materialize_rows = fetch, materialize


def _run_cell(
    xs: Any,
    gate: Any,
    data: Any,
    contexts: Any,
    query: str,
    backend: str,
    dataframe_query: Callable,
    capture: _RowCapture | None = None,
) -> tuple[str, str]:
    """One comparison. Returns ``(status, text)`` where text is the full detail or the error.

    ``capture``, when given, is filled with the reference and DataFrame rows.
    """
    try:
        with _capturing(xs, capture):
            divergences = xs.find_cross_surface_divergences(
                data.connection,
                query_ids=[query],
                reference_sql=data.reference_sql,
                dataframe_query=dataframe_query,
                contexts=contexts,
                validator=gate.build_validator(),
                backends=(backend,),
            )
    except Exception as exc:  # noqa: BLE001 - a comparison that raises is a result, not a crash
        return "error", f"{type(exc).__name__}: {exc}"
    except BaseException as exc:
        # A Polars panic (for example "os error 22") derives from BaseException, so the clause above misses
        # it. Record it for this cell; KeyboardInterrupt, SystemExit and any other BaseException still stop the run.
        if type(exc).__name__ != "PanicException":
            raise
        return "error", f"{type(exc).__name__}: {exc}"
    if divergences:
        detail = divergences[0].detail
        # The harness catches execution failures itself and reports them as divergences with these prefixes.
        if detail.startswith(_HARNESS_FAILURES):
            return "error", detail
        return "divergent", detail
    return "match", ""


def collect(scale: float, *, queries: Sequence[str] | None = None, repeat: int = 1) -> list[Cell]:
    """Compare every query at ``scale`` and return a record for each divergent or drift-fixed cell."""
    from benchbox.core.equivalence import cross_surface as xs
    from benchbox.core.tpcds.dataframe_queries import TPCDS_DATAFRAME_QUERIES
    from benchbox.core.tpcds.dataframe_queries.parameter_adapters import adapter_query_ids

    adapted_ids = {str(query_id) for query_id in adapter_query_ids()}
    gate = dataclasses.replace(xs.STAGED_GATES["tpcds"], scale_factor=scale)

    def unbound(query_id: str) -> Any:
        return TPCDS_DATAFRAME_QUERIES.get_or_raise(f"Q{query_id}")

    cells: list[Cell] = []
    with tempfile.TemporaryDirectory() as tmp:
        data = gate.build(scale, Path(tmp))
        try:
            wanted = [str(q) for q in data.query_ids if queries is None or str(q) in queries]
            for backend in gate.backends:
                contexts = xs.build_production_contexts(
                    data.benchmark, data.data_dir, backends=(backend,), scale_factor=scale
                )
                for query in wanted:
                    captures = [_RowCapture() for _ in range(max(1, repeat))]
                    runs = [
                        _run_cell(xs, gate, data, contexts, query, backend, data.dataframe_query, capture)
                        for capture in captures
                    ]
                    status, text = runs[0]
                    texts = [run[1] for run in runs]
                    is_adapted = query in adapted_ids
                    flaky = len({run[:2] for run in runs}) > 1
                    drift_fixed = False
                    if status == "match" and not flaky and is_adapted:
                        raw_status, raw_text = _run_cell(xs, gate, data, contexts, query, backend, unbound)
                        drift_fixed = raw_status == "divergent"
                        if drift_fixed:
                            text = f"on the defaults file: {raw_text}"
                    if status == "match" and not flaky and not drift_fixed:
                        continue
                    record = classify_cell(
                        "" if drift_fixed else text,
                        adapted=is_adapted,
                        drift_fixed=drift_fixed,
                        outcomes=texts if flaky else None,
                        error=text if status == "error" and not drift_fixed else None,
                        rows=captures[0].rows if status == "divergent" and not drift_fixed else None,
                    )
                    cells.append(
                        Cell(
                            scale=scale,
                            backend=backend,
                            query=query,
                            status="drift fixed by adapter" if drift_fixed else ("flaky" if flaky else status),
                            cause=record["cause"],
                            why=record["why"],
                            secondary=record["secondary"],
                            evidence=text if text else "; ".join(sorted(set(texts))),
                            adapted=is_adapted,
                            runs=len(runs),
                        )
                    )
                del contexts
        finally:
            data.connection.close()
    return cells


def render_markdown(cells: Sequence[Cell], scales: Sequence[float] = ()) -> str:
    lines = ["# TPC-DS divergence report", ""]
    for scale in sorted({cell.scale for cell in cells} | set(scales)):
        subset = [cell for cell in cells if cell.scale == scale]
        counts = Counter(cell.cause for cell in subset)
        lines += [
            f"## Scale factor {scale}",
            "",
            ", ".join(f"{cause}: {count}" for cause, count in sorted(counts.items())) or "no divergent cells",
            "",
        ]
        lines += ["| Query | Family | Status | Cause | Why | Evidence |", "|---|---|---|---|---|---|"]
        for cell in sorted(subset, key=lambda c: (int(c.query), c.backend)):
            evidence = cell.evidence.replace("|", "\\|").replace("\n", " ")
            cause = cell.cause + (f" ({cell.secondary})" if cell.secondary else "")
            lines.append(f"| Q{cell.query} | {cell.backend} | {cell.status} | {cause} | {cell.why} | {evidence} |")
        lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--scale", type=float, action="append", help="scale factor (repeatable; default 0.03 and 0.1)")
    parser.add_argument("--query", action="append", help="limit to a query number (repeatable)")
    parser.add_argument("--repeat", type=int, default=1, help="runs per cell; a cell that differs across runs is flaky")
    parser.add_argument("--out", type=Path, help="write the markdown report here")
    parser.add_argument("--json", type=Path, help="write the JSON report here")
    args = parser.parse_args(argv)

    scales = args.scale or [0.03, 0.1]
    cells: list[Cell] = []
    for scale in scales:
        cells.extend(collect(scale, queries=args.query, repeat=args.repeat))
    markdown = render_markdown(cells, scales)
    if args.out:
        args.out.write_text(markdown + "\n", encoding="utf-8")
    else:
        print(markdown)
    if args.json:
        args.json.write_text(
            json.dumps([dataclasses.asdict(cell) for cell in cells], indent=1) + "\n", encoding="utf-8"
        )
    print(f"{len(cells)} cell(s) reported", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
