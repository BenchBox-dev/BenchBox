"""Static detector for correlated-subquery self-binding in benchmark SQL.

PR #756 fixed three TPC-Havoc SQL variants where a correlated subquery's
UNQUALIFIED correlation column silently bound to the INNER relation instead of
the intended outer table, degenerating a per-row correlation into an
uncorrelated scan (wrong results, but execution stays "green"). Example::

    -- intended: correlate inner ps2 to the OUTER partsupp row
    where ps2.ps_partkey = ps_partkey      -- BUG: ps_partkey binds to inner ps2
    where ps2.ps_partkey = partsupp.ps_partkey   -- FIX: qualified to the outer

This module is a conservative, catalog-aware lint that surfaces such cases as
*candidates for human review* (it is advisory, not a hard gate - see
``_project/TODO/main/planning/correlated-subquery-self-binding-cross-surface-audit.yaml``).

Heuristic
---------
Inside a subquery, an unqualified column in a comparison predicate is flagged
when ALL of the following hold:

* the predicate's *other* operand is a column qualified by one of the subquery's
  own (inner) source aliases - i.e. the predicate is correlation-shaped, pairing
  an inner column with a bare column (a bare-column-vs-literal filter is ignored);
* the bare column is provided by an inner source (so it silently binds inner);
* the bare column is also provided by an enclosing (outer) source (so the author
  plausibly meant the outer relation - the binding is *ambiguous*, which is what
  makes the defect silent rather than an error).

Inner/outer "provided" columns include base-table columns (from the benchmark's
own DDL) AND the output columns of derived-table / CTE sources, so a correlation
target that is a CTE (as in the #756 Q17 fix) is covered. Plain filters,
fully-qualified correlations, and unambiguous (inner-only or outer-only) columns
are not flagged, which keeps false positives low.

The column->tables index is built by parsing the benchmark's own
``CREATE TABLE`` DDL, so the detector is benchmark-agnostic: hand it any DDL and
any SQL.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import Scope, build_scope


@dataclass(frozen=True)
class SelfBindingCandidate:
    """A predicate whose unqualified column may silently bind to the inner relation."""

    column: str
    predicate: str
    inner_tables: tuple[str, ...]
    ambiguous_tables: tuple[str, ...]

    def describe(self) -> str:
        """One-line human-readable description."""
        return (
            f"unqualified `{self.column}` in `{self.predicate}` silently binds to an "
            f"inner source {list(self.inner_tables)} though `{self.column}` is also "
            f"provided by an outer relation (defined in {list(self.ambiguous_tables)}) "
            f"- qualify it to the intended table"
        )


def build_column_table_index(create_table_sql: str, *, dialect: str = "duckdb") -> dict[str, set[str]]:
    """Map each column name to the set of tables that define it, from CREATE TABLE DDL."""
    index: dict[str, set[str]] = defaultdict(set)
    for statement in sqlglot.parse(create_table_sql, read=dialect):
        if not isinstance(statement, exp.Create):
            continue
        table = statement.find(exp.Table)
        schema = statement.find(exp.Schema)
        if table is None or schema is None:
            continue
        table_name = table.name.lower()
        for column_def in schema.find_all(exp.ColumnDef):
            index[column_def.name.lower()].add(table_name)
    return dict(index)


def _provided_columns(scope: Scope, column_index: dict[str, set[str]]) -> set[str]:
    """Lower-cased column names this scope's own sources expose.

    Base tables contribute their DDL columns; derived-table / CTE sources
    contribute the output names of their SELECT (so CTE correlation targets,
    as in the #756 Q17 fix, are recognized).
    """
    provided: set[str] = set()
    for source in scope.sources.values():
        if isinstance(source, exp.Table):
            table = source.name.lower()
            provided |= {col for col, tables in column_index.items() if table in tables}
        elif isinstance(source, Scope) and isinstance(source.expression, exp.Select):
            provided |= {select.alias_or_name.lower() for select in source.expression.selects if select.alias_or_name}
    return provided


def _inner_alias_qualified(operand: exp.Expression | None, inner_aliases: set[str]) -> bool:
    """True if operand is a column qualified by one of this subquery's own source aliases."""
    return isinstance(operand, exp.Column) and bool(operand.table) and operand.table.lower() in inner_aliases


def _comparison_predicates(scope: Scope) -> Iterable[exp.Binary]:
    """Comparison predicates in WHERE/HAVING/JOIN-ON of this scope's own SELECT."""
    select = scope.expression
    if not isinstance(select, exp.Select):
        return []
    roots: list[exp.Expression] = []
    for clause in (select.args.get("where"), select.args.get("having")):
        if clause is not None:
            roots.append(clause)
    for join in select.args.get("joins") or []:
        on = join.args.get("on")
        if on is not None:
            roots.append(on)
    predicates: list[exp.Binary] = []
    comparisons = (exp.EQ, exp.NEQ, exp.LT, exp.LTE, exp.GT, exp.GTE)
    for root in roots:
        predicates.extend(root.find_all(*comparisons))
    return predicates


def find_self_binding_candidates(
    sql: str, column_index: dict[str, set[str]], *, dialect: str = "duckdb"
) -> list[SelfBindingCandidate]:
    """Flag unqualified subquery columns that may self-bind to the inner relation.

    Args:
        sql: The query to analyze.
        column_index: column name -> defining tables, e.g. from build_column_table_index.
        dialect: SQL dialect for parsing.

    Returns:
        Candidates ordered by appearance. Conservative: only a bare column compared
        against an inner-alias-qualified column, where the bare column is provided by
        BOTH an inner and an outer source, is flagged.
    """
    tree = sqlglot.parse_one(sql, read=dialect)
    root = build_scope(tree)
    if root is None:
        return []

    candidates: list[SelfBindingCandidate] = []
    seen: set[tuple[str, str]] = set()
    for scope in root.traverse():
        if scope.parent is None:
            continue  # top-level scope cannot self-bind to an outer relation
        inner_aliases = {alias.lower() for alias in scope.sources}
        inner_provided = _provided_columns(scope, column_index)
        if not inner_provided:
            continue
        outer_provided: set[str] = set()
        ancestor = scope.parent
        while ancestor is not None:
            outer_provided |= _provided_columns(ancestor, column_index)
            ancestor = ancestor.parent

        for predicate in _comparison_predicates(scope):
            left, right = predicate.left, predicate.right
            for bare, other in ((left, right), (right, left)):
                if not isinstance(bare, exp.Column) or bare.table:
                    continue  # need an UNqualified column on this side
                name = bare.name.lower()
                if name not in inner_provided or name not in outer_provided:
                    continue  # unambiguous (inner-only or outer-only): not a self-bind
                if not _inner_alias_qualified(other, inner_aliases):
                    continue  # other side must be an inner-qualified column (correlation shape)
                text = predicate.sql(dialect=dialect)
                key = (name, text)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(
                    SelfBindingCandidate(
                        column=bare.name,
                        predicate=text,
                        inner_tables=tuple(sorted(inner_aliases)),
                        ambiguous_tables=tuple(sorted(column_index.get(name, set()))),
                    )
                )
    return candidates


def _scan_tpchavoc() -> int:
    """Scan all TPC-Havoc SQL variants and print self-binding candidates.

    Returns the number of variants flagged (advisory; the CLI always exits 0).
    """
    from benchbox.core.tpchavoc.benchmark import TPCHavocBenchmark

    benchmark = TPCHavocBenchmark(scale_factor=1.0)
    index = build_column_table_index(benchmark.get_create_tables_sql(dialect="duckdb"))

    flagged = 0
    for query_id in benchmark.get_implemented_queries():
        for variant_id in range(1, 11):
            key = f"{query_id}_v{variant_id}"
            try:
                sql = benchmark.get_query(key)
                found = find_self_binding_candidates(sql, index)
            except Exception as exc:  # noqa: BLE001 - advisory tool must not crash on one query
                print(f"  {key}: SKIP ({type(exc).__name__}: {exc})")
                continue
            if found:
                flagged += 1
                print(f"  {key}:")
                for candidate in found:
                    print(f"    - {candidate.describe()}")
    print(f"\nTPC-Havoc SQL variants flagged: {flagged}")
    return flagged


def main() -> int:
    """CLI: scan a benchmark's SQL for self-binding candidates (advisory, always exits 0)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", default="tpchavoc", choices=["tpchavoc"], help="benchmark to scan")
    parser.parse_args()
    _scan_tpchavoc()
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
