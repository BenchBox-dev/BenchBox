---
sqlglot_version: 30.6.0
status: drafted
type: feature-request
target_dialect: questdb
benchbox_workaround: benchbox/platforms/questdb_rewriter.py
filed: false
---

# Title

Feature request: QuestDB dialect

# Body

## Background

QuestDB (https://questdb.io/) is an open-source time-series + analytical engine with a SQL surface that is broadly Postgres-shaped but with several material divergences. As of `sqlglot==30.6.0` there is no `questdb` entry in `Dialects`. Targeting QuestDB by transpiling to `postgres` produces SQL that fails to parse on QuestDB 9.3.4 across every TPC-H, TPC-DS, and SSB query we run.

```python
from sqlglot.dialects.dialect import Dialect

Dialect.get_or_raise("questdb")
# ValueError: Unknown dialect 'questdb'
```

## Coverage gaps observed against QuestDB 9.3.4

These are the four cases that BenchBox currently rewrites in
`benchbox/platforms/questdb_rewriter.py` after a `postgres`-targeted transpile:

### 1. Implicit comma joins → explicit `INNER JOIN ... ON`

QuestDB does not accept implicit comma joins (`FROM a, b WHERE a.x = b.x`), despite documentation suggestions otherwise. Affects all 22 TPC-H queries, all 99 TPC-DS queries, all 13 SSB queries.

```sql
-- input
SELECT l.l_orderkey, o.o_orderdate
FROM lineitem l, orders o
WHERE l.l_orderkey = o.o_orderkey
  AND l.l_shipdate > DATE '1995-01-01'

-- needs to become
SELECT l.l_orderkey, o.o_orderdate
FROM lineitem AS l
INNER JOIN orders AS o ON l.l_orderkey = o.o_orderkey
WHERE l.l_shipdate > DATE '1995-01-01'
```

### 2. `INTERVAL` arithmetic → `dateadd('d', n, expr)`

QuestDB has no SQL standard `INTERVAL` expression. The native form is `dateadd('<unit>', <signed_n>, <expr>)`.

```sql
-- input
CAST('1998-12-01' AS DATE) - INTERVAL '90' DAY

-- needs to become
dateadd('d', -90, CAST('1998-12-01' AS DATE))
```

### 3. `SUBSTRING(s FROM p FOR l)` → 3-argument form

QuestDB accepts only the function-style 3-argument `substring(s, p, l)`.

```sql
-- input
SUBSTRING(name FROM 1 FOR 3)

-- needs to become
substring(name, 1, 3)
```

### 4. CTE column-alias lists rejected

QuestDB does not accept `WITH cte (col1, col2) AS (SELECT ...)`; the column list must be omitted.

```sql
-- input
WITH x (a, b) AS (SELECT 1, 2) SELECT * FROM x

-- needs to become
WITH x AS (SELECT 1, 2) SELECT * FROM x
```

## Offer

We have a working post-AST rewriter in `benchbox/platforms/questdb_rewriter.py` (about 21 KB) that handles these cases plus a bank of fixtures across TPC-H, TPC-DS, SSB, tpchavoc, and tpch_skew. We are happy to:

- Contribute a `QuestDB` dialect class derived from `Postgres`, lifting the four transformations into the dialect's parser/generator.
- Contribute the BenchBox query corpus as test fixtures.

If the maintainers prefer to scope a first pass narrowly, items (1) and (2) cover the largest fraction of failures we see on real workloads.

## Version

- `sqlglot==30.6.0`
- Python 3.12
- QuestDB 9.3.4
- Confirmed missing dialect via the harness at https://github.com/joeharris76/BenchBox/blob/develop/_project/sqlglot-upstream/repros/repro_all.py
