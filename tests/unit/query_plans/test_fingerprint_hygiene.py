"""Cross-parser signature-hygiene invariant.

The plan fingerprint is a LOGICAL, stats-independent structural hash (see the
stability contract in ``benchbox/core/results/query_plan_models.py``). A parser
that folds an operator's raw EXPLAIN detail into a signature-bearing logical
field leaks any cost/cardinality estimate carried in that text into the hash, so
a stats refresh (VACUUM/ANALYZE) or a different table size silently changes the
fingerprint. That is a bug, and historically the DuckDB parser had it (its
FORMAT JSON ``extra_info`` dict carries ``Estimated Cardinality``).

This module enforces the rule for every registered parser:

1. ``test_no_parser_leaks_estimate_tokens_into_signature`` parses a recorded
   fixture per platform and asserts the structural signature contains no
   cost/cardinality/estimate token. Driven by recorded fixtures under
   ``tests/fixtures/query_plans/`` (plus inline samples for the parsers that
   ship no file fixture) so it runs with no live service.
2. ``test_registry_is_fully_covered`` asserts every registered platform has a
   hygiene fixture, so a newly added parser cannot silently skip the invariant.
3. ``test_estimate_only_changes_do_not_change_fingerprint`` parses two fixtures
   that differ ONLY in estimate values and asserts an identical fingerprint.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from benchbox.core.query_plans.parsers.base import strip_estimate_keys, strip_estimates
from benchbox.core.query_plans.parsers.registry import (
    get_parser_for_platform,
    get_parser_registry,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "query_plans"


def _load(name: str) -> str:
    return (_FIXTURES / name).read_text()


# Tokens that must never appear in a structural signature: digit-bearing
# cost/cardinality/estimate text, plus the DataFusion ``metrics=[...]`` block.
# Kept aligned with the estimate vocabulary stripped in base.py: this tripwire
# flags the unambiguous estimate forms (so it never false-positives on a genuine
# predicate column named ``cost``/``rows``) while covering every standalone
# estimate token the stripper knows about (selectivity, num_rows, ...).
_ESTIMATE_TOKEN_RE = re.compile(
    r"""
    estimated\s+cardinality
    | estimated\s+cost
    | estimated\s+rows
    | cardinality\s*[:=]\s*\d
    | \bEC:\s*\d
    | output_rows\s*[:=]\s*\d
    | plan_rows\s*[:=]\s*\d
    | num_rows\s*[:=]\s*\d
    | row_count\s*[:=]\s*\d
    | selectivity\s*[:=]\s*\d
    | metrics\s*=\s*\[
    | \(\s*cost=[\d.]+\.\.
    """,
    re.IGNORECASE | re.VERBOSE,
)


# ---------------------------------------------------------------------------
# Inline fixtures for parsers that ship no recorded file fixture. Each carries a
# cost/cardinality estimate in the raw EXPLAIN so the leak path is exercised.
# ---------------------------------------------------------------------------


def _postgresql_explain(plan_rows: int, total_cost: float) -> str:
    """PostgreSQL EXPLAIN (FORMAT JSON): estimates live in dedicated keys."""
    return json.dumps(
        [
            {
                "Plan": {
                    "Node Type": "Aggregate",
                    "Strategy": "Hashed",
                    "Total Cost": total_cost,
                    "Plan Rows": plan_rows,
                    "Group Key": ["o_orderpriority"],
                    "Plans": [
                        {
                            "Node Type": "Seq Scan",
                            "Relation Name": "orders",
                            "Total Cost": total_cost,
                            "Plan Rows": plan_rows * 10,
                            "Filter": "(o_totalprice > 10)",
                        }
                    ],
                }
            }
        ]
    )


def _redshift_explain(rows: int, total_cost: str) -> str:
    """Redshift text EXPLAIN: estimates in ``(cost=.. rows=.. width=..)``."""
    return (
        f"XN HashAggregate  (cost=50.00..{total_cost} rows={rows} width=40)\n"
        f"  ->  XN Seq Scan on lineitem  (cost=0.00..25.00 rows={rows * 10} width=40)\n"
        f"        Filter: (l_quantity > 5)"
    )


def _datafusion_explain(output_rows: int) -> str:
    """DataFusion EXPLAIN ANALYZE physical plan: estimates in ``metrics=[...]``."""
    return (
        f"physical_plan | FilterExec: id@0 > 1, "
        f"metrics=[output_rows={output_rows}, elapsed_compute=9us, "
        f"selectivity=98% ({output_rows}/{output_rows + 1})]\n"
        f"              |   DataSourceExec: partitions=1, partition_sizes=[1], metrics=[]"
    )


def _duckdb_explain(cardinality: int) -> str:
    """DuckDB EXPLAIN (FORMAT JSON): ``extra_info`` dict carries Estimated Cardinality."""
    return json.dumps(
        [
            {
                "name": "PERFECT_HASH_GROUP_BY",
                "extra_info": {
                    "Groups": "#0",
                    "Aggregates": "sum(#1)",
                    "Estimated Cardinality": str(cardinality),
                },
                "children": [
                    {
                        "name": "SEQ_SCAN",
                        "extra_info": {
                            "Table": "orders",
                            "Filters": "id>1",
                            "Estimated Cardinality": str(cardinality * 20),
                        },
                        "children": [],
                    }
                ],
            }
        ]
    )


def _sqlite_explain() -> str:
    return "QUERY PLAN\n`--SEARCH orders USING INDEX idx_orders (id=?)"


# ---------------------------------------------------------------------------
# Per-platform hygiene fixtures. Every registered platform must resolve here.
# File-backed entries reuse the recorded EXPLAIN fixtures; inline entries cover
# the parsers that ship no file fixture.
# ---------------------------------------------------------------------------

_FILE_FIXTURES: dict[str, str] = {
    "duckdb": "motherduck_duckdb_explain_sample.json",
    "motherduck": "motherduck_duckdb_explain_sample.json",
    "clickhouse": "clickhouse_explain_plan_sample.txt",
    "presto": "presto_explain_sample.json",
    "athena": "athena_explain_sample.json",
    "trino": "trino_explain_sample.json",
    "starburst": "trino_explain_sample.json",
    "spark": "spark_explain_sample.txt",
    "databricks": "spark_explain_sample.txt",
    "lakesail": "spark_explain_sample.txt",
    "velox": "velox_explain_extended_sample.txt",
    "databend": "databend_explain_sample.txt",
    "questdb": "questdb_explain_sample.txt",
    "doris": "doris_shape_plan_sample.txt",
    "singlestore": "singlestore_explain_sample.txt",
    "snowflake": "snowflake_explain_sample.json",
    "firebolt": "firebolt_explain_sample.txt",
    "azure_synapse": "azure_synapse_explain_sample.xml",
    "fabric_warehouse": "fabric_warehouse_showplan_sample.txt",
    "bigquery": "bigquery_query_plan_sample.json",
}

_INLINE_FIXTURES: dict[str, str] = {
    "postgresql": _postgresql_explain(5, 125.5),
    "postgres": _postgresql_explain(5, 125.5),
    "redshift": _redshift_explain(100, "55.00"),
    "datafusion": _datafusion_explain(48),
    "sqlite": _sqlite_explain(),
}


def _signature_fixture(platform: str) -> str:
    if platform in _FILE_FIXTURES:
        return _load(_FILE_FIXTURES[platform])
    return _INLINE_FIXTURES[platform]


# Estimate-only pairs: two EXPLAIN renderings of the same plan that differ ONLY
# in cost/cardinality values. The fingerprint must be identical.
#
# duckdb and datafusion exercise the strip helpers directly (their estimates sit
# in a signature-bearing field before stripping). postgresql and redshift route
# estimates into non-hashed `properties`; their pairs assert the complementary
# guarantee that those parsers keep estimates out of the signature entirely.
_ESTIMATE_PAIRS: dict[str, tuple[str, str]] = {
    "duckdb": (_duckdb_explain(5), _duckdb_explain(90_000)),
    "datafusion": (_datafusion_explain(48), _datafusion_explain(90_000)),
    "postgresql": (_postgresql_explain(5, 125.5), _postgresql_explain(70_000, 9_000_000.0)),
    "redshift": (_redshift_explain(100, "55.00"), _redshift_explain(99_000, "990000.00")),
}


def _registered_platforms() -> list[str]:
    return sorted(get_parser_registry().get_all_platforms())


class TestRegistryCoverage:
    def test_registry_is_fully_covered(self):
        """Every registered parser must have a hygiene fixture (future-proofing)."""
        registered = set(_registered_platforms())
        covered = set(_FILE_FIXTURES) | set(_INLINE_FIXTURES)
        missing = registered - covered
        assert not missing, (
            f"Parsers {sorted(missing)} are registered but have no signature-hygiene "
            "fixture. Add one to tests/unit/query_plans/test_fingerprint_hygiene.py "
            "so the no-estimate-leak invariant covers them."
        )


class TestSignatureHygiene:
    @pytest.mark.parametrize("platform", _registered_platforms())
    def test_no_parser_leaks_estimate_tokens_into_signature(self, platform):
        """No registered parser may fold cost/cardinality text into the signature."""
        parser = get_parser_for_platform(platform)
        assert parser is not None, f"No parser registered for {platform}"

        dag = parser.parse_explain_output("hygiene", _signature_fixture(platform))
        assert dag is not None, f"{platform} fixture failed to parse"
        assert dag.logical_root is not None

        signature = dag.logical_root.get_structural_signature()
        leak = _ESTIMATE_TOKEN_RE.search(signature)
        assert leak is None, (
            f"{platform} parser leaked an estimate token {leak.group(0)!r} into the "
            f"structural signature:\n{signature}\n"
            "Strip cost/cardinality via strip_estimates()/strip_estimate_keys() before "
            "storing detail into a signature-bearing field."
        )

    @pytest.mark.parametrize("platform", sorted(_ESTIMATE_PAIRS))
    def test_estimate_only_changes_do_not_change_fingerprint(self, platform):
        """Two plans that differ only in estimates must share a fingerprint."""
        low_text, high_text = _ESTIMATE_PAIRS[platform]
        parser = get_parser_for_platform(platform)

        low = parser.parse_explain_output("low", low_text)
        high = parser.parse_explain_output("high", high_text)
        assert low is not None and high is not None

        assert low.plan_fingerprint == high.plan_fingerprint, (
            f"{platform} fingerprint changed when only the cost/cardinality estimate "
            "changed; the fingerprint must be stats-independent.\n"
            f"low : {low.logical_root.get_structural_signature()}\n"
            f"high: {high.logical_root.get_structural_signature()}"
        )


class TestStripHelpers:
    """Direct contract tests for the shared strip helpers."""

    def test_strip_estimate_keys_drops_estimate_fields_only(self):
        extra = {
            "Groups": "#0",
            "Aggregates": "sum(#1)",
            "Estimated Cardinality": "12345",
        }
        cleaned = strip_estimate_keys(extra)
        assert cleaned == {"Groups": "#0", "Aggregates": "sum(#1)"}
        # Input is not mutated.
        assert "Estimated Cardinality" in extra

    @pytest.mark.parametrize(
        "key",
        ["Estimated Cardinality", "Estimated Cost", "Cardinality", "rows", "EC", "Selectivity"],
    )
    def test_strip_estimate_keys_recognises_estimate_keys(self, key):
        assert strip_estimate_keys({key: "1", "Conditions": "a=b"}) == {"Conditions": "a=b"}

    @pytest.mark.parametrize(
        "structural_key",
        ["Projections", "Conditions", "Groups", "Aggregates", "Order By", "Table", "Filters"],
    )
    def test_strip_estimate_keys_keeps_structural_keys(self, structural_key):
        # "Projections" contains the substring "ec"; it must NOT be treated as an estimate.
        result = strip_estimate_keys({structural_key: "value"})
        assert result == {structural_key: "value"}

    def test_strip_estimates_removes_metrics_block(self):
        out = strip_estimates("id@0 > 1, metrics=[output_rows=48, selectivity=98% (48/49)]")
        assert out == "id@0 > 1"

    def test_strip_estimates_removes_cost_parenthetical(self):
        out = strip_estimates("Seq Scan on orders (cost=0.00..15.50 rows=500 width=48)")
        assert "cost=" not in out
        assert "rows=" not in out
        assert out.startswith("Seq Scan on orders")

    def test_strip_estimates_removes_inline_estimated_cardinality(self):
        out = strip_estimates("Filters: id>1 Estimated Cardinality: 119")
        assert "119" not in out
        assert "id>1" in out

    def test_strip_estimates_preserves_predicate_with_estimate_like_column(self):
        # A genuine predicate on a column literally named 'cost' must survive: removal
        # is anchored to explicit estimate wording, not bare cost=/rows=.
        out = strip_estimates("(cost_center = 5 AND rows_flag = 1)")
        assert out == "(cost_center = 5 AND rows_flag = 1)"

    @pytest.mark.parametrize(
        "predicate",
        [
            "(cost=5 AND x=1)",  # column named 'cost', not a (cost=N..N) estimate paren
            "WHERE num_rows = 5",  # column named 'num_rows'
            "amount > 100 AND ec = 7",  # column named 'ec' with '=', not the 'EC:' estimate token
            "(rows = 5 OR cardinality = 7)",  # columns named 'rows'/'cardinality'
        ],
    )
    def test_strip_estimates_does_not_corrupt_genuine_predicates(self, predicate):
        # Regression: the cost parenthetical and inline-token removals must be anchored
        # to estimate wording so they never delete a real predicate whose column name
        # collides with an estimate keyword.
        assert strip_estimates(predicate) == predicate

    def test_strip_estimates_removes_metrics_block_with_nested_brackets(self):
        # Regression: the metrics block can embed bracketed values (partitioning), so the
        # removal must reach the final ']' instead of stopping at the first inner one.
        out = strip_estimates("expr=[a@0 ASC], metrics=[output_rows=5, partitioning=[Hash([a],4)]]")
        assert out == "expr=[a@0 ASC]"
        assert "output_rows" not in out and "metrics=" not in out

    def test_strip_estimates_handles_empty(self):
        assert strip_estimates("") == ""

    @pytest.mark.parametrize(
        "predicate",
        [
            "arr = []",
            "col IN []",
            "list_filter(tags, x -> x IN [])",
        ],
    )
    def test_strip_estimates_preserves_genuine_empty_list(self, predicate):
        # Regression: a real empty-list literal must survive when no estimate token was
        # stripped — the empty-bracket tidy-up only runs after an actual removal, so it no
        # longer corrupts predicates such as ``arr = []`` (DuckDB/DataFusion signatures).
        assert strip_estimates(predicate) == predicate

    def test_strip_estimates_still_tidies_emptied_brackets_after_removal(self):
        # When an estimate token vacated its enclosing brackets, the now-empty ``[]`` is
        # still tidied — the guard only skips tidy-up when nothing was removed.
        out = strip_estimates("part=[Estimated Cardinality: 5], key=a")
        assert "[]" not in out
        assert "5" not in out and "key=a" in out

    def test_strip_estimates_preserves_empty_list_alongside_stripped_estimate(self):
        # Regression: a genuine empty-list predicate must survive even when the SAME line
        # also carries an estimate that gets stripped. Previously the global ``[]`` tidy-up
        # ran on any removal and corrupted ``arr = []`` -> ``arr =``, changing the
        # signature/fingerprint. Only estimate-vacated brackets should be removed.
        out = strip_estimates("FilterExec: arr = [], metrics=[output_rows=5]")
        assert "arr = []" in out
        assert "output_rows" not in out and "metrics=" not in out
