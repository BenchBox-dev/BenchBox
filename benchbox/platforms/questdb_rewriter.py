"""QuestDB SQL dialect rewriter - post-translation fixups for QuestDB 9.3.4 compatibility.

## Rewriter Architecture

### Position in the execution chain

    qgen template
        → _clean_sql() in benchbox/core/tpch/queries.py
        → translate_sql_query() (SQLGlot, netezza → postgres dialect)
        → questdb_rewrite(query)           ← this module
        → QuestDBAdapter.execute_query()
        → execute_sql_query() in base/sql_execution.py

The rewriter runs after SQLGlot normalisation, which handles obvious syntax
differences between Netezza and PostgreSQL.  It applies QuestDB-specific fixes
that the generic SQLGlot translation does not cover.

### Design constraints

1. **Non-destructive** - every rule must be testable with a before/after SQL
   fixture.  If semantics change, that is a bug, not a feature.
2. **Idempotent** - calling rewrite() twice on the same SQL must return the
   same result as calling it once.
3. **Scoped** - this module touches only QuestDB.  The function is called only
   from QuestDBAdapter.execute_query(); no other platform ever imports it.
5. **Import discipline** - QuestDB adapter imports ``rewrite`` by name
   (``from benchbox.platforms.questdb_rewriter import rewrite as _rewriter_rewrite``).
   Unit tests MUST patch the imported name in the adapter module
   (``benchbox.platforms.questdb._rewriter_rewrite``), NOT the name on this module
   (``benchbox.platforms.questdb_rewriter.rewrite``).  Patching the source module
   silently no-ops because the adapter's local reference is already bound.
4. **SQLGlot-first for structural rewrites** - regex over SQL text is fragile
   for multi-table, aliased, or nested queries.  Use SQLGlot AST traversal for
   comma-JOIN expansion (w8/w9).  Reserve regex for simple lexical substitutions
   (INTERVAL arithmetic, SUBSTRING FROM/FOR, CTE column list).

### Rewrite rules (in order of query-coverage impact)

──────────────────────────────────────────────────────────────────────────────
RULE 1 - Comma JOIN → explicit INNER JOIN  [implemented in w8/w9]
──────────────────────────────────────────────────────────────────────────────
Blocks: TPC-H (all 22), TPC-DS (all 99), SSB (all 13), tpchavoc, tpch_skew.
QuestDB 9.3.4 does NOT support implicit comma-JOIN syntax despite documentation
claims.  Every query with `FROM a, b WHERE a.x = b.x` fails.

Before:
    SELECT l.l_orderkey, o.o_orderdate
    FROM   lineitem l, orders o
    WHERE  l.l_orderkey = o.o_orderkey
      AND  l.l_shipdate > DATE '1995-01-01'

After:
    SELECT l.l_orderkey, o.o_orderdate
    FROM   lineitem AS l
    JOIN   orders AS o ON l.l_orderkey = o.o_orderkey
    WHERE  l.l_shipdate > DATE '1995-01-01'

Implementation (AST-based via sqlglot):
  1. Parse with sqlglot.parse_one(query, dialect="postgres")
  2. Detect comma-joins: Join nodes where on=None AND using=None
     (sqlglot represents "FROM a, b" as Join(table=b, on=None, using=None))
  3. Split WHERE predicates into:
     - Join predicates: EQ nodes whose both sides reference different tables
     - Filter predicates: remaining conditions
  4. For each comma-join table, find the connecting join predicate via a
     greedy algorithm seeded from the primary FROM table, and move it to
     the Join node's ON slot
  5. Reassemble WHERE with only the filter predicates remaining
  6. Re-serialise with tree.sql(dialect="postgres")

Handled cases:
  - Multi-table comma JOINs (TPC-H Q5 has 5 tables, Q9 has 6)
  - Aliased tables: FROM lineitem l, orders o (alias preserved)
  - Mixed explicit + implicit: FROM a JOIN b ON ..., c WHERE c.x = b.y
  - Subqueries in WHERE (e.g. IN (SELECT ...)): recursed via find_all(Subquery)
  - Nested subqueries: outer and inner comma JOINs both rewritten
  - CTE bodies: recursed via find_all(CTE) - TPC-DS uses CTEs throughout
  - EXISTS predicates: recursed via find_all(Exists) - Q10-style correlated EXISTS
  - Unqualified column join predicates: col=col without table qualifiers (TPC-DS)
  - Mixed qualified+unqualified: one qualified (in joined set), one bare column

Regex is not used for this rule - TPC-DS has deeply nested and aliased
subqueries where regex produces structurally incorrect SQL.

──────────────────────────────────────────────────────────────────────────────
RULE 2 - INTERVAL arithmetic → dateadd()  [implemented in w10]
──────────────────────────────────────────────────────────────────────────────
Blocks: TPC-H Q1, Q4, Q6, Q17 (at minimum).
QuestDB does not support standard SQL INTERVAL expressions for date arithmetic.
Use dateadd('d', N, expr) instead.

Before:
    CAST('1998-12-01' AS DATE) - INTERVAL '90' DAY

After:
    dateadd('d', -90, CAST('1998-12-01' AS DATE))

Pattern (regex-safe, lexically consistent):
    Input:  <date_expr> [+-] INTERVAL '<N>' (DAY|MONTH|YEAR)
    Output: dateadd('<unit>', [+-]N, <date_expr>)
    Units:  DAY → 'd', MONTH → 'M', YEAR → 'y'

Affected TPC-H queries: Q1, Q4, Q6, Q17 (at minimum).

──────────────────────────────────────────────────────────────────────────────
RULE 3 - SUBSTRING FROM/FOR → substring(str, pos, len)  [implemented in w10]
──────────────────────────────────────────────────────────────────────────────
Blocks: TPC-H Q22, some TPC-DS queries.
QuestDB does not support the SQL:1999 SUBSTRING FROM/FOR syntax.

Before:
    SUBSTRING(c_phone FROM 1 FOR 2)

After:
    substring(c_phone, 1, 2)

Two forms:
    SUBSTRING(expr FROM start FOR length) → substring(expr, start, length)
    SUBSTRING(expr FROM start)            → substring(expr, start)

Pattern is lexically fixed; regex is appropriate here.

──────────────────────────────────────────────────────────────────────────────
RULE 4 - CTE column list removal  [implemented in w10]
──────────────────────────────────────────────────────────────────────────────
Blocks: TPC-H Q15 (when using the non-15a.sql variant).
QuestDB does not support the optional column-alias list in WITH clauses.

Before:
    WITH revenue (supplier_no, total_revenue) AS (...)

After:
    WITH revenue AS (...)

Pattern: `WITH name (col1, col2, ...) AS (` → `WITH name AS (`
Regex-safe since it is a fixed lexical pattern at the top of the query.
"""

from __future__ import annotations

import re

import sqlglot
from sqlglot import exp


def rewrite(query: str) -> str:
    """Apply all QuestDB dialect fixups to a SQL query.

    Rewrites are applied in order:
      1. Comma JOIN → explicit INNER JOIN  (AST-based, w8/w9)
      2. INTERVAL arithmetic → dateadd()  (regex, w10)
      3. SUBSTRING FROM/FOR               (regex, w10)
      4. CTE column list removal          (regex, w10)

    Args:
        query: SQL string, post-SQLGlot normalisation (postgres dialect)

    Returns:
        Query with QuestDB-specific fixups applied.  If no rewrite is needed,
        returns the input unchanged (no AST round-trip penalty).
    """
    query = _rewrite_comma_joins(query)
    query = _rewrite_interval_arithmetic(query)
    query = _rewrite_substring_from_for(query)
    query = _rewrite_cte_column_list(query)
    return query


# ──────────────────────────────────────────────────────────────────────────────
# Rule 1 - Comma JOIN → explicit INNER JOIN
# ──────────────────────────────────────────────────────────────────────────────


def _rewrite_comma_joins(query: str) -> str:
    """Convert implicit comma-JOIN syntax to explicit INNER JOIN … ON.

    Returns the input unchanged if no comma joins are detected, avoiding the
    SQLGlot parse/generate round-trip cost for queries that don't need it.

    Handles:
      - 2-table case (w8): FROM a, b WHERE a.x = b.x AND filter
      - Multi-table (w9): FROM a, b, c with chained equalities
      - Aliased tables: FROM lineitem l, orders o
      - Mixed explicit + implicit: FROM a JOIN b ON …, c WHERE c.x = b.y
      - Subqueries with comma JOINs (recursed via SQLGlot walk)
    """
    if not _has_comma_join(query):
        return query

    try:
        tree = sqlglot.parse_one(query, dialect="postgres")
    except Exception:
        return query

    changed = _rewrite_comma_joins_in_select(tree)
    if not changed:
        return query

    return tree.sql(dialect="postgres")


def _rewrite_nested_selects(root: exp.Expression) -> bool:
    """Recurse into all nested Select bodies (subqueries, EXISTS, CTEs) bottom-up.

    Returns True if any rewrite was applied in a nested scope.
    exp.Subquery covers scalar / IN / FROM-clause subqueries.
    exp.Exists bodies are bare Select nodes (not Subquery-wrapped).
    exp.CTE bodies are bare Select nodes (not Subquery-wrapped).

    Mutual recursion note: this calls _rewrite_comma_joins_in_select, which
    calls back into _rewrite_nested_selects on each inner Select.  find_all()
    does a deep tree walk, so a node at depth d is visited d times (once by
    each ancestor's _rewrite_nested_selects call).  Rewrites are idempotent -
    a join already rewritten to explicit JOIN syntax is never re-matched -
    so duplicate visits are harmless.  At real-world SQL depths (TPC-DS: 2-4
    levels) the overhead is negligible.
    """
    changed = False
    for subquery in root.find_all(exp.Subquery):
        if subquery is not root:
            inner = subquery.this
            if isinstance(inner, exp.Select) and _rewrite_comma_joins_in_select(inner):
                changed = True
    for node in root.find_all(exp.Exists):
        if isinstance(node.this, exp.Select) and _rewrite_comma_joins_in_select(node.this):
            changed = True
    for cte in root.find_all(exp.CTE):
        if isinstance(cte.this, exp.Select) and _rewrite_comma_joins_in_select(cte.this):
            changed = True
    return changed


def _rewrite_comma_joins_in_select(select: exp.Expression) -> bool:
    """Rewrite comma joins inside a single SELECT node, in-place.

    Returns True if any rewrite was applied.
    """
    changed = _rewrite_nested_selects(select)

    joins = select.args.get("joins") or []
    comma_joins = [j for j in joins if j.args.get("on") is None and j.args.get("using") is None]
    if not comma_joins:
        return changed

    where = select.args.get("where")
    if where is None:
        # No WHERE clause - raw comma syntax is still unsupported by QuestDB,
        # so convert every comma join into an explicit CROSS JOIN.
        for join in comma_joins:
            join.set("kind", "CROSS")
        return True

    predicates = _flatten_and(where.this)
    remaining = list(predicates)

    # Build the set of table references already in the join chain.
    # Start with the primary table from the FROM clause.
    from_clause = select.args.get("from_")
    joined_refs: set[str] = set()
    if from_clause:
        joined_refs.add(_table_ref(from_clause.this))

    # Also include tables from any existing explicit JOINs
    for j in joins:
        if j not in comma_joins:
            joined_refs.add(_table_ref(j.this))

    for join in comma_joins:
        cj_ref = _table_ref(join.this)
        joined_refs_snapshot = set(joined_refs)

        join_pred = None
        for pred in remaining:
            if _is_join_pred_between(pred, cj_ref, joined_refs_snapshot):
                join_pred = pred
                break

        if join_pred is not None:
            join.set("on", join_pred.copy())
            remaining.remove(join_pred)
            changed = True
        else:
            # No connecting equality found for this comma join. Preserve the
            # cross-product semantics explicitly so the rewritten query no
            # longer relies on unsupported comma syntax.
            join.set("kind", "CROSS")
            changed = True

        joined_refs.add(cj_ref)

    # Rebuild WHERE from the remaining filter predicates
    new_cond = _build_and(remaining)
    if new_cond is None:
        select.set("where", None)
    else:
        select.set("where", exp.Where(this=new_cond))

    return changed


def _table_ref(node: exp.Expression) -> str:
    """Return the canonical reference string for a table node (alias or name)."""
    alias = node.alias if hasattr(node, "alias") else ""
    if alias:
        return alias.lower()
    name = node.name if hasattr(node, "name") else str(node)
    return name.lower()


def _column_table_ref(col: exp.Column) -> str:
    """Return the table qualifier of a Column node (alias or name, lowercased)."""
    table = col.args.get("table")
    if table is None:
        return ""
    return str(table).lower()


def _collect_table_refs(node: exp.Expression) -> set[str]:
    """Return all table qualifiers referenced in an expression's columns."""
    refs: set[str] = set()
    for col in node.find_all(exp.Column):
        ref = _column_table_ref(col)
        if ref:
            refs.add(ref)
    return refs


def _is_join_pred_between(pred: exp.Expression, cj_ref: str, joined_refs: set[str]) -> bool:
    """True if pred is an equality that connects cj_ref to a table in joined_refs.

    Handles three forms:
    - Fully qualified: ``t1.col = t2.col`` - table refs extracted and matched exactly.
    - Fully unqualified: ``col_a = col_b`` - treated as a join predicate when both
      sides are bare columns with no table qualifier.  Scalar comparisons like
      ``d_year = 2000`` have only one column, so they are correctly excluded.
    - Mixed: one side is qualified (table in joined_refs), the other is unqualified.
      TPC-DS uses this pattern frequently (e.g. ``s_store_sk = ctr1.ctr_store_sk``
      where ``s_store_sk`` is unqualified but belongs to the comma-joined ``store``
      table).  The qualified side anchors the predicate to the already-joined set;
      the unqualified column is assumed to belong to the current comma-join table.
      This heuristic is correct when predicates are listed in join order (standard
      for TPC-H and TPC-DS generated SQL).
    """
    if not isinstance(pred, exp.EQ):
        return False
    cols = list(pred.find_all(exp.Column))
    if len(cols) != 2:
        # Scalar comparison (col = literal) - keep in WHERE
        return False
    refs = _collect_table_refs(pred)
    if refs:
        if cj_ref in refs and bool(refs & joined_refs):
            return True  # fully qualified: both tables explicitly named
        # Mixed: one qualified side (in joined_refs), one unqualified side.
        # The qualified column anchors to an already-joined table; the unqualified
        # column is assumed to belong to the current comma-join table (cj_ref).
        # Assumption: TPC-DS/TPC-H generate predicates in join order, so the
        # unqualified column belongs to the table currently being promoted.
        # A predicate like `other_joined.col = bare_col` where bare_col actually
        # belongs to a *different* table would be misassigned, but this pattern
        # does not appear in TPC-H or TPC-DS generated SQL.
        if bool(refs & joined_refs) and any(_column_table_ref(c) == "" for c in cols):
            return True
        return False
    # Fully unqualified: both columns bare - treat as a join predicate.
    return all(_column_table_ref(c) == "" for c in cols)


def _flatten_and(node: exp.Expression) -> list[exp.Expression]:
    """Flatten a nested AND tree into a flat list of predicates."""
    if isinstance(node, exp.And):
        return _flatten_and(node.left) + _flatten_and(node.right)
    return [node]


def _build_and(predicates: list[exp.Expression]) -> exp.Expression | None:
    """Rebuild a nested AND tree from a flat predicate list."""
    if not predicates:
        return None
    result = predicates[0]
    for pred in predicates[1:]:
        result = exp.And(this=result, expression=pred)
    return result


def _has_comma_join(query: str) -> bool:
    """Heuristic: return True if the query might contain a comma JOIN.

    False positives are acceptable (they trigger the full AST parse);
    false negatives would silently skip rewrites.
    """
    stripped = re.sub(r"'[^']*'", "'?'", query)
    return bool(re.search(r"\b\w[\w.]*\s*,\s*\w", stripped, re.IGNORECASE))


# ──────────────────────────────────────────────────────────────────────────────
# Rule 2 - INTERVAL arithmetic → dateadd()
# ──────────────────────────────────────────────────────────────────────────────

# Matches: <expr> +/- INTERVAL '<N>' DAY|MONTH|YEAR
# Capturing groups: (1) date expression, (2) sign, (3) number, (4) unit
_INTERVAL_RE = re.compile(
    # group 1: date expr - either CAST(... AS DATE) or a bare identifier/column
    r"(CAST\s*\([^)]+\)|[\w.]+)"
    r"\s*([+-])\s*"
    r"INTERVAL\s+'(\d+)'\s+(DAY|MONTH|YEAR)",
    re.IGNORECASE,
)

_INTERVAL_UNIT_MAP = {"DAY": "d", "MONTH": "M", "YEAR": "y"}


def _rewrite_interval_arithmetic(query: str) -> str:
    """Replace INTERVAL arithmetic with QuestDB's dateadd() function."""

    def _replace(m: re.Match) -> str:
        date_expr = m.group(1).strip()
        sign = m.group(2)
        n = int(m.group(3))
        unit = _INTERVAL_UNIT_MAP[m.group(4).upper()]
        offset = -n if sign == "-" else n
        return f"dateadd('{unit}', {offset}, {date_expr})"

    return _INTERVAL_RE.sub(_replace, query)


# ──────────────────────────────────────────────────────────────────────────────
# Rule 3 - SUBSTRING FROM/FOR → substring(str, pos, len)
# ──────────────────────────────────────────────────────────────────────────────

# SUBSTRING(expr FROM start FOR length) - both FROM and FOR present
_SUBSTRING_FROM_FOR_RE = re.compile(
    r"SUBSTRING\s*\(\s*(.*?)\s+FROM\s+(\d+)\s+FOR\s+(\d+)\s*\)",
    re.IGNORECASE,
)

# SUBSTRING(expr FROM start) - only FROM (no FOR clause)
_SUBSTRING_FROM_RE = re.compile(
    r"SUBSTRING\s*\(\s*(.*?)\s+FROM\s+(\d+)\s*\)",
    re.IGNORECASE,
)


def _rewrite_substring_from_for(query: str) -> str:
    """Rewrite SUBSTRING FROM/FOR to positional substring() call."""
    query = _SUBSTRING_FROM_FOR_RE.sub(r"substring(\1, \2, \3)", query)
    query = _SUBSTRING_FROM_RE.sub(r"substring(\1, \2)", query)
    return query


# ──────────────────────────────────────────────────────────────────────────────
# Rule 4 - CTE column list removal
# ──────────────────────────────────────────────────────────────────────────────

# Matches: WITH name (col1, col2, ...) AS (
_CTE_COLUMN_LIST_RE = re.compile(
    r"\bWITH\s+(\w+)\s*\([^)]+\)\s+AS\s*\(",
    re.IGNORECASE,
)


def _rewrite_cte_column_list(query: str) -> str:
    """Remove column alias list from CTE definitions."""
    return _CTE_COLUMN_LIST_RE.sub(r"WITH \1 AS (", query)
