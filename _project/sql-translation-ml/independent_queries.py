"""Queries authored independently from the TPC-H schema without access to generator templates or outcomes."""

QUERIES = [
    {
        "id": "q01_integer_date_filter",
        "feature_tags": ["projection", "integer-predicate", "date-text-literal", "multiline"],
        "sql": """SELECT
    o.o_orderkey,
    o.o_custkey,
    o.o_orderdate,
    o.o_shippriority
FROM orders AS o
WHERE o.o_orderkey >= 1
  AND o.o_orderdate >= '1994-01-01'
  AND o.o_orderdate < '1996-01-01'
ORDER BY o.o_orderkey;""",
        "notes": "Uses ISO date text literals, portable to DuckDB and SQLite.",
    },
    {
        "id": "q02_left_join_null_comment",
        "feature_tags": ["left-outer-join", "null", "case", "text"],
        "sql": """SELECT
    r.r_regionkey,
    r.r_name,
    n.n_nationkey,
    n.n_name,
    CASE
        WHEN n.n_nationkey IS NULL THEN 'no nation'
        WHEN n.n_comment IS NULL THEN 'missing comment'
        ELSE 'comment present'
    END AS nation_comment_state
FROM region AS r
LEFT JOIN nation AS n
    ON n.n_regionkey = r.r_regionkey
ORDER BY r.r_regionkey, n.n_nationkey;""",
        "notes": "Retains regions with no nations and distinguishes NULL nation comments.",
    },
    {
        "id": "q03_union_all_duplicate_preservation",
        "feature_tags": ["cte", "union-all", "duplicates", "integer"],
        "sql": """WITH customer_keys AS (
    SELECT c.c_custkey
    FROM customer AS c
    WHERE c.c_custkey >= 1
),
order_customer_keys AS (
    SELECT o.o_custkey
    FROM orders AS o
    WHERE o.o_custkey >= 1
)
SELECT c_custkey, 'customer' AS source_name
FROM customer_keys
UNION ALL
SELECT o_custkey, 'order' AS source_name
FROM order_customer_keys
ORDER BY c_custkey, source_name;""",
        "notes": "UNION ALL intentionally preserves repeated customer keys across and within inputs.",
    },
    {
        "id": "q04_distinct_part_supplier_pairs",
        "feature_tags": ["distinct", "inner-join", "integer", "text"],
        "sql": """SELECT DISTINCT
    p.p_partkey,
    p.p_name,
    s.s_suppkey,
    s.s_name
FROM part AS p
JOIN partsupp AS ps
    ON ps.ps_partkey = p.p_partkey
JOIN supplier AS s
    ON s.s_suppkey = ps.ps_suppkey
WHERE p.p_size >= 1
  AND ps.ps_availqty >= 0
ORDER BY p.p_partkey, s.s_suppkey;""",
        "notes": "Exercises duplicate elimination after a many-to-many-style join.",
    },
    {
        "id": "q05_grouped_line_counts",
        "feature_tags": ["group-by", "count", "having", "integer"],
        "sql": """SELECT
    l.l_orderkey,
    COUNT(*) AS line_count,
    COUNT(DISTINCT l.l_partkey) AS distinct_part_count
FROM lineitem AS l
WHERE l.l_linenumber >= 1
GROUP BY l.l_orderkey
HAVING COUNT(*) >= 1
ORDER BY l.l_orderkey;""",
        "notes": "All aggregates produce integers; no DECIMAL source or output is used.",
    },
    {
        "id": "q06_cte_left_join_empty_orders",
        "feature_tags": ["cte", "left-outer-join", "count", "null", "case"],
        "sql": """WITH line_counts AS (
    SELECT
        l.l_orderkey,
        COUNT(*) AS line_count
    FROM lineitem AS l
    GROUP BY l.l_orderkey
)
SELECT
    o.o_orderkey,
    o.o_orderdate,
    CASE
        WHEN lc.line_count IS NULL THEN 0
        ELSE lc.line_count
    END AS line_count
FROM orders AS o
LEFT JOIN line_counts AS lc
    ON lc.l_orderkey = o.o_orderkey
WHERE o.o_orderkey >= 1
ORDER BY o.o_orderkey;""",
        "notes": "Tests CTE materialization shape and NULL handling for orders without lineitems.",
    },
    {
        "id": "q07_window_row_number",
        "feature_tags": ["window", "row-number", "partition-by", "integer", "date"],
        "sql": """SELECT
    l.l_orderkey,
    l.l_linenumber,
    l.l_shipdate,
    ROW_NUMBER() OVER (
        PARTITION BY l.l_orderkey
        ORDER BY l.l_linenumber, l.l_partkey, l.l_suppkey
    ) AS line_position
FROM lineitem AS l
WHERE l.l_shipdate >= '1992-01-01'
ORDER BY l.l_orderkey, line_position;""",
        "notes": "The window ordering has stable integer tie-breakers.",
    },
    {
        "id": "q08_correlated_exists_partsupp",
        "feature_tags": ["correlated-subquery", "exists", "integer", "text"],
        "sql": """SELECT
    p.p_partkey,
    p.p_name,
    p.p_size
FROM part AS p
WHERE p.p_size >= 1
  AND EXISTS (
      SELECT 1
      FROM partsupp AS ps
      WHERE ps.ps_partkey = p.p_partkey
        AND ps.ps_availqty >= p.p_size
  )
ORDER BY p.p_partkey;""",
        "notes": "Correlated predicate compares only INTEGER columns.",
    },
    {
        "id": "q09_correlated_count",
        "feature_tags": ["correlated-subquery", "scalar-subquery", "count", "integer"],
        "sql": """SELECT
    s.s_suppkey,
    s.s_name,
    (
        SELECT COUNT(*)
        FROM partsupp AS ps
        WHERE ps.ps_suppkey = s.s_suppkey
          AND ps.ps_availqty >= 1
    ) AS available_part_count
FROM supplier AS s
WHERE s.s_suppkey >= 1
ORDER BY s.s_suppkey;""",
        "notes": "Scalar correlated COUNT is defined even when a supplier has no partsupp rows.",
    },
    {
        "id": "q10_intersect_customer_orders",
        "feature_tags": ["set-operation", "intersect", "cte", "integer"],
        "sql": """WITH active_customers AS (
    SELECT c.c_custkey
    FROM customer AS c
    WHERE c.c_custkey >= 1
),
ordered_customers AS (
    SELECT o.o_custkey
    FROM orders AS o
    WHERE o.o_orderkey >= 1
)
SELECT c_custkey
FROM active_customers
INTERSECT
SELECT o_custkey
FROM ordered_customers
ORDER BY c_custkey;""",
        "notes": "INTERSECT supplies set semantics distinct from q03's duplicate-preserving UNION ALL.",
    },
    {
        "id": "q11_case_date_buckets",
        "feature_tags": ["case", "group-by", "date", "text", "count"],
        "sql": """SELECT
    CASE
        WHEN o.o_orderdate < '1994-01-01' THEN 'before-1994'
        WHEN o.o_orderdate < '1995-01-01' THEN 'year-1994'
        ELSE '1995-or-later'
    END AS order_date_bucket,
    CASE
        WHEN o.o_orderstatus = 'F' THEN 'final'
        WHEN o.o_orderstatus = 'O' THEN 'open'
        ELSE 'other'
    END AS order_status_bucket,
    COUNT(*) AS order_count
FROM orders AS o
GROUP BY
    CASE
        WHEN o.o_orderdate < '1994-01-01' THEN 'before-1994'
        WHEN o.o_orderdate < '1995-01-01' THEN 'year-1994'
        ELSE '1995-or-later'
    END,
    CASE
        WHEN o.o_orderstatus = 'F' THEN 'final'
        WHEN o.o_orderstatus = 'O' THEN 'open'
        ELSE 'other'
    END
ORDER BY order_date_bucket, order_status_bucket;""",
        "notes": "Repeats CASE expressions in GROUP BY for conservative cross-dialect portability.",
    },
    {
        "id": "q12_nested_regional_customer_activity",
        "feature_tags": [
            "long-query",
            "nested-cte",
            "left-outer-join",
            "window",
            "correlated-exists",
            "set-operation",
            "case",
            "null",
            "count",
            "date",
        ],
        "sql": """WITH
line_summary AS (
    SELECT
        l.l_orderkey,
        COUNT(*) AS line_count,
        COUNT(DISTINCT l.l_partkey) AS part_count,
        MIN(l.l_shipdate) AS first_shipdate,
        MAX(l.l_receiptdate) AS last_receiptdate
    FROM lineitem AS l
    WHERE l.l_linenumber >= 1
      AND l.l_shipdate >= '1992-01-01'
    GROUP BY l.l_orderkey
),
order_activity AS (
    SELECT
        o.o_orderkey,
        o.o_custkey,
        o.o_orderdate,
        o.o_orderstatus,
        ls.line_count,
        ls.part_count,
        ls.first_shipdate,
        ls.last_receiptdate,
        CASE
            WHEN ls.line_count IS NULL THEN 'no-lines'
            WHEN ls.first_shipdate > ls.last_receiptdate THEN 'date-anomaly'
            ELSE 'has-lines'
        END AS line_state
    FROM orders AS o
    LEFT JOIN line_summary AS ls
        ON ls.l_orderkey = o.o_orderkey
    WHERE o.o_orderkey >= 1
),
customer_activity AS (
    SELECT
        c.c_custkey,
        c.c_nationkey,
        c.c_name,
        COUNT(oa.o_orderkey) AS order_count,
        COUNT(CASE WHEN oa.line_state = 'has-lines' THEN 1 END) AS complete_order_count,
        COUNT(CASE WHEN oa.o_orderdate >= '1994-01-01' THEN 1 END) AS recent_order_count
    FROM customer AS c
    LEFT JOIN order_activity AS oa
        ON oa.o_custkey = c.c_custkey
    GROUP BY c.c_custkey, c.c_nationkey, c.c_name
),
nation_activity AS (
    SELECT
        n.n_nationkey,
        n.n_regionkey,
        n.n_name,
        COUNT(ca.c_custkey) AS customer_count,
        COUNT(CASE WHEN ca.order_count >= 1 THEN 1 END) AS ordering_customer_count,
        COUNT(CASE WHEN ca.complete_order_count >= 1 THEN 1 END) AS complete_customer_count
    FROM nation AS n
    LEFT JOIN customer_activity AS ca
        ON ca.c_nationkey = n.n_nationkey
    GROUP BY n.n_nationkey, n.n_regionkey, n.n_name
),
ranked_nations AS (
    SELECT
        na.n_nationkey,
        na.n_regionkey,
        na.n_name,
        na.customer_count,
        na.ordering_customer_count,
        na.complete_customer_count,
        ROW_NUMBER() OVER (
            PARTITION BY na.n_regionkey
            ORDER BY na.ordering_customer_count DESC,
                     na.complete_customer_count DESC,
                     na.n_nationkey
        ) AS regional_position
    FROM nation_activity AS na
),
participating_nations AS (
    SELECT n.n_nationkey
    FROM nation AS n
    JOIN customer AS c
        ON c.c_nationkey = n.n_nationkey
    INTERSECT
    SELECT n.n_nationkey
    FROM nation AS n
    JOIN supplier AS s
        ON s.s_nationkey = n.n_nationkey
)
SELECT
    r.r_regionkey,
    r.r_name,
    rn.n_nationkey,
    rn.n_name,
    rn.customer_count,
    rn.ordering_customer_count,
    rn.complete_customer_count,
    rn.regional_position,
    CASE
        WHEN rn.n_nationkey IS NULL THEN 'no-nation'
        WHEN EXISTS (
            SELECT 1
            FROM participating_nations AS pn
            WHERE pn.n_nationkey = rn.n_nationkey
        ) THEN 'customer-and-supplier'
        ELSE 'single-sided-or-empty'
    END AS participation_state
FROM region AS r
LEFT JOIN ranked_nations AS rn
    ON rn.n_regionkey = r.r_regionkey
WHERE r.r_regionkey >= 0
ORDER BY r.r_regionkey, rn.regional_position, rn.n_nationkey;""",
        "notes": (
            "Genuinely nested, over-256-token portable query. It exercises CTE dependency chains, two outer joins, "
            "NULL paths, date comparisons, integer-only aggregates, window ranking, INTERSECT, and a correlated "
            "EXISTS predicate."
        ),
    },
]
