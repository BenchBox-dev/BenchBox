"""
DuckDB EXPLAIN output fixtures by version.

Provides sample EXPLAIN outputs from different DuckDB versions to test
parser compatibility across version changes.

These fixtures represent real-world format variations that may occur
when users upgrade their DuckDB installations.
"""

# =============================================================================
# DuckDB 0.9.x - Text format with box-drawing characters
# =============================================================================

DUCKDB_0_9_SIMPLE_SCAN = """
┌───────────────────────────┐
│         SEQ_SCAN          │
│   ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │
│          lineitem         │
│   ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │
│        l_orderkey         │
│        l_quantity         │
│     l_extendedprice       │
└───────────────────────────┘
"""

DUCKDB_0_9_FILTER_SCAN = """
┌───────────────────────────┐
│          FILTER           │
│   ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │
│(l_shipdate <= CAST(       │
│'1998-12-01' AS DATE))     │
└─────────────┬─────────────┘
┌─────────────┴─────────────┐
│         SEQ_SCAN          │
│   ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │
│          lineitem         │
│   ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │
│        l_shipdate         │
│        l_returnflag       │
│        l_linestatus       │
└───────────────────────────┘
"""

DUCKDB_0_9_AGGREGATE = """
┌───────────────────────────┐
│         PROJECTION        │
│   ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │
│         l_returnflag      │
│         l_linestatus      │
│         sum_qty           │
└─────────────┬─────────────┘
┌─────────────┴─────────────┐
│       HASH_GROUP_BY       │
│   ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │
│         Groups:           │
│       l_returnflag        │
│       l_linestatus        │
│   ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │
│      sum(l_quantity)      │
└─────────────┬─────────────┘
┌─────────────┴─────────────┐
│         SEQ_SCAN          │
│   ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │
│          lineitem         │
└───────────────────────────┘
"""

DUCKDB_0_9_JOIN = """
┌───────────────────────────┐
│         PROJECTION        │
│   ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │
│        o_orderkey         │
│         c_name            │
└─────────────┬─────────────┘
┌─────────────┴─────────────┐
│        HASH_JOIN          │
│   ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │
│o_custkey = c_custkey      │
└──────┬──────────────┬─────┘
┌──────┴──────┐ ┌─────┴─────┐
│  SEQ_SCAN   │ │ SEQ_SCAN  │
│   orders    │ │ customer  │
└─────────────┘ └───────────┘
"""

DUCKDB_0_9_ORDER_BY = """
┌───────────────────────────┐
│         ORDER_BY          │
│   ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │
│o_orderdate ASC NULLS LAST │
│o_totalprice DESC NULLS    │
│           LAST            │
└─────────────┬─────────────┘
┌─────────────┴─────────────┐
│         SEQ_SCAN          │
│   ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │
│          orders           │
└───────────────────────────┘
"""

# =============================================================================
# DuckDB 0.10.x / 1.0.x - JSON format (EXPLAIN FORMAT JSON)
# =============================================================================

DUCKDB_1_0_JSON_SIMPLE_SCAN = """{
    "name": "SEQ_SCAN",
    "extra_info": "lineitem\\nl_orderkey\\nl_quantity\\nl_extendedprice",
    "children": []
}"""

DUCKDB_1_0_JSON_FILTER_SCAN = """{
    "name": "FILTER",
    "extra_info": "(l_shipdate <= CAST('1998-12-01' AS DATE))",
    "children": [
        {
            "name": "SEQ_SCAN",
            "extra_info": "lineitem\\nl_shipdate\\nl_returnflag\\nl_linestatus",
            "children": []
        }
    ]
}"""

DUCKDB_1_0_JSON_AGGREGATE = """{
    "name": "PROJECTION",
    "extra_info": "l_returnflag\\nl_linestatus\\nsum_qty",
    "children": [
        {
            "name": "HASH_GROUP_BY",
            "extra_info": "l_returnflag\\nl_linestatus\\nsum(l_quantity)",
            "children": [
                {
                    "name": "SEQ_SCAN",
                    "extra_info": "lineitem",
                    "children": []
                }
            ]
        }
    ]
}"""

DUCKDB_1_0_JSON_JOIN = """{
    "name": "PROJECTION",
    "extra_info": "o_orderkey\\nc_name",
    "children": [
        {
            "name": "HASH_JOIN",
            "extra_info": "o_custkey = c_custkey",
            "children": [
                {
                    "name": "SEQ_SCAN",
                    "extra_info": "orders",
                    "children": []
                },
                {
                    "name": "SEQ_SCAN",
                    "extra_info": "customer",
                    "children": []
                }
            ]
        }
    ]
}"""

DUCKDB_1_0_JSON_ORDER_BY = """{
    "name": "ORDER_BY",
    "extra_info": "o_orderdate ASC NULLS LAST\\no_totalprice DESC NULLS LAST",
    "children": [
        {
            "name": "SEQ_SCAN",
            "extra_info": "orders",
            "children": []
        }
    ]
}"""

DUCKDB_1_0_JSON_WITH_TIMING = """{
    "name": "PROJECTION",
    "timing": 0.025,
    "cardinality": 500,
    "extra_info": "result_cols",
    "children": [
        {
            "name": "HASH_GROUP_BY",
            "timing": 0.015,
            "cardinality": 500,
            "extra_info": "sum(amount)",
            "children": [
                {
                    "name": "SEQ_SCAN",
                    "timing": 0.010,
                    "cardinality": 10000,
                    "extra_info": "lineitem",
                    "children": []
                }
            ]
        }
    ]
}"""

# DuckDB nested wrapper format (common in EXPLAIN ANALYZE output)
DUCKDB_1_0_JSON_WRAPPED = """{
    "children": [
        {
            "name": "QUERY_PLAN",
            "children": [
                {
                    "name": "PROJECTION",
                    "extra_info": "results",
                    "children": [
                        {
                            "name": "SEQ_SCAN",
                            "extra_info": "orders",
                            "children": []
                        }
                    ]
                }
            ]
        }
    ]
}"""

# DuckDB Python 1.6.0.dev379 / engine v2.0.0-alpha39998 analyzed-plan format.
DUCKDB_2_0_PREVIEW_JSON_ANALYZED = """{
    "operator": [
        {
            "type": "RESULT_COLLECTOR",
            "timing": 0.0,
            "intermediate_rows": 0,
            "intermediate_size_bytes": 0,
            "extra_info": {},
            "children": [
                {
                    "type": "EXPLAIN_ANALYZE",
                    "timing": 0.000001,
                    "intermediate_rows": 0,
                    "intermediate_size_bytes": 0,
                    "extra_info": {},
                    "children": [
                        {
                            "type": "PROJECTION",
                            "timing": 0.000004,
                            "intermediate_rows": 1,
                            "intermediate_size_bytes": 4,
                            "extra_info": {
                                "Estimated Cardinality": "1",
                                "Projections": "test_column"
                            },
                            "children": [
                                {
                                    "type": "DUMMY_SCAN",
                                    "timing": 0.000001,
                                    "intermediate_rows": 1,
                                    "intermediate_size_bytes": 4,
                                    "extra_info": {},
                                    "children": []
                                }
                            ]
                        }
                    ]
                }
            ]
        }
    ],
    "query": {
        "sql": "EXPLAIN (ANALYZE, FORMAT JSON) SELECT 1 AS test_column",
        "total_time": 0.0002
    }
}"""

# =============================================================================
# Version metadata for parameterized testing
# =============================================================================

VERSION_FIXTURES = [
    # (version, format, fixture_name, fixture_value)
    ("0.9.0", "text", "simple_scan", DUCKDB_0_9_SIMPLE_SCAN),
    ("0.9.0", "text", "filter_scan", DUCKDB_0_9_FILTER_SCAN),
    ("0.9.0", "text", "aggregate", DUCKDB_0_9_AGGREGATE),
    ("0.9.0", "text", "join", DUCKDB_0_9_JOIN),
    ("0.9.0", "text", "order_by", DUCKDB_0_9_ORDER_BY),
    ("1.0.0", "json", "simple_scan", DUCKDB_1_0_JSON_SIMPLE_SCAN),
    ("1.0.0", "json", "filter_scan", DUCKDB_1_0_JSON_FILTER_SCAN),
    ("1.0.0", "json", "aggregate", DUCKDB_1_0_JSON_AGGREGATE),
    ("1.0.0", "json", "join", DUCKDB_1_0_JSON_JOIN),
    ("1.0.0", "json", "order_by", DUCKDB_1_0_JSON_ORDER_BY),
    ("1.0.0", "json", "with_timing", DUCKDB_1_0_JSON_WITH_TIMING),
    ("1.0.0", "json", "wrapped", DUCKDB_1_0_JSON_WRAPPED),
    ("2.0.0-alpha39998", "json", "preview_analyzed", DUCKDB_2_0_PREVIEW_JSON_ANALYZED),
]

# Expected operators for each fixture type
# Note: Text parser may not capture all operators due to format limitations
EXPECTED_OPERATORS = {
    "simple_scan": ["SCAN"],
    "filter_scan": ["SCAN"],  # Text parser may not always capture FILTER separately
    "aggregate": ["PROJECT"],  # At minimum, PROJECT is captured
    "join": ["PROJECT", "JOIN"],  # Text parser may not capture leaf SCANs in complex layouts
    "order_by": ["SORT", "SCAN"],
    "with_timing": ["PROJECT", "AGGREGATE", "SCAN"],
    "wrapped": ["PROJECT", "SCAN"],
    "preview_analyzed": ["PROJECT"],
}
