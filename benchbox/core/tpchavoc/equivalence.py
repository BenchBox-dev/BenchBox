"""Result-equivalence oracle for TPC-Havoc SQL variants.

TPC-Havoc's premise is that the ten SQL variants of each TPC-H query are
structurally diverse but *semantically equivalent* to the canonical TPC-H
query. benchbox ships :meth:`TPCHavocBenchmark.validate_variant_equivalence`,
but nothing in the default run or in CI ever calls it for a real variant, so
divergences are silent (see ``_project/TODO/main/planning/
tpchavoc-variant-equivalence-gate.yaml``).

This module wires that existing validator over a real, small-scale DuckDB
dataset and reports every variant that diverges from canonical TPC-H. It is a
**diagnostic**: ``python -m benchbox.core.tpchavoc.equivalence`` (or
``make tpchavoc-equivalence-report``) prints a categorized report and always
exits ``0``. A hard CI gate is deliberately deferred until the judgment-call
divergence classes recorded in :data:`KNOWN_DIVERGENCES` are triaged.

Comparison is order-insensitive with float tolerance (the validator sorts both
sides). Because canonical TPC-H queries carry a presentational ``ORDER BY ...
LIMIT n`` top-N cut that the variant families treat inconsistently, the trailing
``LIMIT`` is stripped from both sides before comparison; the one variant that
relies on ``LIMIT`` for computation rather than presentation (``14_v9``) is
recorded as a known divergence.

Known divergences observed at SF=0.1 on DuckDB fall into four classes:

* ``scale-threshold`` - the Q11 variants hardcode the ``0.0001`` value
  threshold while canonical TPC-H scales it by ``1 / SF``; they are equivalent
  only at SF=1.
* ``extra-column`` - the "window function" variants add a ranking/helper
  column, changing the output schema (an intended structural difference).
* ``limit-semantics`` - ``14_v9`` uses ``LIMIT 1`` to collapse a window result
  to a single row; the top-N normalization here removes it.
* ``suspected-defect`` - value/ordering mismatches that need triage and may be
  genuine variant bugs (``1_v8``, ``7_v5``, ``9_v10``).

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark(TM) H (TPC-H) - Copyright (C) Transaction Processing Performance Council.
This implementation is derived from TPC-H.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from benchbox.core.tpchavoc.benchmark import TPCHavocBenchmark
from benchbox.core.tpchavoc.validation import ValidationError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from benchbox import TPCH

# Smallest scale that is discriminating for the known defect classes: at SF=0.01
# the Q2/Q10 projection bugs do not surface (no negative balances in the result)
# and Q17 is NULL, so a gate there would be vacuous. SF=0.1 catches them while
# staying ~10x cheaper than SF=1.
EQUIVALENCE_SCALE = 0.1

# Variants known to diverge from canonical TPC-H at EQUIVALENCE_SCALE, with the
# reason class. This is the burndown input for the deferred hard gate, not an
# allow-list the diagnostic enforces. Keyed by "<query>_v<variant>".
KNOWN_DIVERGENCES: dict[str, str] = {
    "1_v8": "suspected-defect",
    "5_v9": "extra-column",
    "7_v5": "suspected-defect",
    "7_v9": "extra-column",
    "8_v9": "extra-column",
    "9_v9": "extra-column",
    "9_v10": "suspected-defect",
    "10_v9": "extra-column",
    **{f"11_v{variant}": "scale-threshold" for variant in range(1, 11)},
    "12_v9": "extra-column",
    "13_v9": "extra-column",
    "14_v9": "limit-semantics",
    "15_v4": "extra-column",
}

_TRAILING_LIMIT = re.compile(r"(?is)\s+limit\s+\d+\s*;?\s*$")


@dataclass(frozen=True)
class Divergence:
    """A single variant whose result differs from the canonical TPC-H query."""

    query_id: int
    variant_id: int
    detail: str

    @property
    def key(self) -> str:
        """Stable ``<query>_v<variant>`` identifier."""
        return f"{self.query_id}_v{self.variant_id}"


def strip_top_n(sql: str) -> str:
    """Remove a trailing line comment, statement terminator, and ``LIMIT n``.

    Canonical TPC-H queries truncate to a top-N for display; the TPC-Havoc
    variant families do not do this consistently, and some variant files end the
    statement with a ``-- Variant N`` comment. The trailing comment, terminator,
    and ``LIMIT`` are normalized away on both sides before comparing the
    underlying result sets, so a variant that keeps ``LIMIT`` (e.g. ``21_v*``,
    which end ``limit 100 -- Variant N``) is compared on the same footing as one
    that drops it.
    """
    normalized = re.sub(r"\s*--[^\n]*$", "", sql.strip())
    normalized = normalized.rstrip().rstrip(";")
    return _TRAILING_LIMIT.sub("", normalized)


def find_divergences(
    connection: Any,
    benchmark: TPCHavocBenchmark,
    canonical_query: Callable[[int], str],
    *,
    query_ids: list[int] | None = None,
) -> list[Divergence]:
    """Compare every variant of each query to canonical TPC-H on ``connection``.

    Args:
        connection: A DBAPI/DuckDB connection already populated with TPC-H data.
        benchmark: The TPC-Havoc benchmark providing variants and the validator.
        canonical_query: Callable returning the canonical TPC-H SQL for a query id.
        query_ids: Subset of query ids to check; defaults to all implemented.

    Returns:
        One :class:`Divergence` per variant whose result is not equivalent to
        canonical TPC-H. Reuses :meth:`TPCHavocBenchmark.validate_variant_equivalence`.
    """
    ids = query_ids if query_ids is not None else benchmark.get_implemented_queries()
    divergences: list[Divergence] = []
    for query_id in ids:
        try:
            original = connection.execute(strip_top_n(canonical_query(query_id))).fetchall()
        except Exception as exc:  # noqa: BLE001 - a diagnostic must report, not crash, on a bad query
            divergences.append(Divergence(query_id, 0, f"canonical query failed: {exc}"))
            continue
        for variant_id in range(1, 11):
            try:
                variant_sql = strip_top_n(benchmark.get_query(f"{query_id}_v{variant_id}"))
                variant_rows = connection.execute(variant_sql).fetchall()
                benchmark.validate_variant_equivalence(query_id, variant_id, original, variant_rows)
            except ValidationError as exc:
                divergences.append(Divergence(query_id, variant_id, str(exc)))
            except Exception as exc:  # noqa: BLE001 - surface execution/sort errors as divergences
                divergences.append(Divergence(query_id, variant_id, f"error: {exc}"))
    return divergences


def build_duckdb_with_tpch(scale_factor: float, output_dir: str | Path) -> tuple[Any, TPCHavocBenchmark, TPCH]:
    """Generate TPC-H data and return a populated in-memory DuckDB connection.

    Platform/generator imports are deferred so importing this module does not
    pull DuckDB or the data generator into the core import graph.

    Returns:
        ``(connection, tpchavoc_benchmark, tpch_benchmark)``.
    """
    import duckdb

    from benchbox import TPCH
    from benchbox.core.tpch.generator import TPCHDataGenerator
    from benchbox.platforms.duckdb import DuckDBAdapter

    output_dir = Path(output_dir)
    generated = TPCHDataGenerator(scale_factor=scale_factor, output_dir=output_dir).generate()
    data_dir = next(Path(paths[0] if isinstance(paths, list) else paths).parent for paths in generated.values())

    tpchavoc = TPCHavocBenchmark(scale_factor=scale_factor, output_dir=output_dir)
    tpch = TPCH(scale_factor=scale_factor, output_dir=output_dir)

    connection = duckdb.connect(":memory:")
    for statement in tpchavoc.get_create_tables_sql(dialect="duckdb").strip().split(";"):
        if statement.strip():
            connection.execute(statement.strip())
    DuckDBAdapter(database=":memory:").load_data(tpchavoc, connection, data_dir)
    return connection, tpchavoc, tpch


def main() -> int:
    """Generate data, run the oracle, and print a categorized report.

    Always returns ``0`` - this is a diagnostic, not a gate.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        connection, tpchavoc, tpch = build_duckdb_with_tpch(EQUIVALENCE_SCALE, tmp)
        try:
            divergences = find_divergences(connection, tpchavoc, lambda q: tpch.get_query(q))
        finally:
            connection.close()

    total = len(tpchavoc.get_implemented_queries()) * 10
    found = {d.key for d in divergences}
    new = sorted(found - set(KNOWN_DIVERGENCES), key=_sort_key)
    resolved = sorted(set(KNOWN_DIVERGENCES) - found, key=_sort_key)

    print(f"TPC-Havoc variant equivalence vs canonical TPC-H @ SF={EQUIVALENCE_SCALE} (DuckDB)")
    print(f"  checked {total} variants - {len(divergences)} divergent, {total - len(divergences)} equivalent\n")

    by_class: dict[str, list[Divergence]] = {}
    for divergence in sorted(divergences, key=lambda d: _sort_key(d.key)):
        klass = KNOWN_DIVERGENCES.get(divergence.key, "UNCLASSIFIED")
        by_class.setdefault(klass, []).append(divergence)
    for klass in sorted(by_class):
        print(f"  [{klass}]")
        for divergence in by_class[klass]:
            print(f"    {divergence.key}: {divergence.detail}")
        print()

    if new:
        print(f"NEW (unclassified) divergences - triage needed: {new}")
    if resolved:
        print(f"Previously-known divergences now equivalent - update KNOWN_DIVERGENCES: {resolved}")
    if not new and not resolved:
        print("Divergence set matches KNOWN_DIVERGENCES.")
    return 0


def _sort_key(key: str) -> tuple[int, int]:
    """Sort ``<query>_v<variant>`` keys numerically."""
    query, variant = key.split("_v")
    return int(query), int(variant)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
