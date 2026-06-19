"""Cross-engine plan-DAG conformance corpus and comparable-subset projection.

The raw ``plan_fingerprint`` is a PER-ENGINE within-version key and is NOT
comparable across engines (see the decision in
``benchbox/core/results/query_plan_models.py``). Cross-engine STRUCTURAL
comparison is instead provided by the wrapper-stripped *comparable subset*
projection in ``comparison.py``.

This module:

1. ``TestComparableSubsetProjection`` — unit-tests the projection
   (``structural_backbone_counts`` / ``comparable_subset_signature`` /
   ``structural_backbones_match``): wrapper nodes are dropped and consecutive
   runs of a multi-stage operator (aggregate/sort) collapse to one, while joins
   and scans are always counted per node.
2. ``TestCrossEngineConformanceCorpus`` — a golden corpus of recorded EXPLAIN
   fixtures (no live engines). For each canonical query it asserts every engine's
   harmonized DAG meets the declared backbone invariant (e.g. exactly 2 base
   scans, 1 join, 1 aggregate), that the comparable-subset signature is IDENTICAL
   across engines, and that the raw per-engine fingerprints remain DISTINCT.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from benchbox.core.query_plans.comparison import (
    comparable_subset_signature,
    structural_backbone_counts,
    structural_backbones_match,
)
from benchbox.core.query_plans.parsers.registry import get_parser_for_platform
from benchbox.core.results.query_plan_models import (
    LogicalOperator,
    LogicalOperatorType,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "query_plans"


def _load(name: str) -> str:
    return (_FIXTURES / name).read_text()


def _op(op_type: LogicalOperatorType, children=None) -> LogicalOperator:
    return LogicalOperator(
        operator_type=op_type,
        operator_id=f"{op_type.value.lower()}_{id(children)}",
        children=children or [],
    )


# ---------------------------------------------------------------------------
# Cross-engine conformance corpus.
#
# Each canonical query maps to (declared backbone invariant, {engine: fixture}).
# The fixtures are the recorded EXPLAIN samples shared by the query-plan-capture
# family; they all render the same canonical shape: an aggregate over a join of two
# base tables. Engines differ in wrapper/exchange nodes, partial+final aggregates
# and multi-stage sorts — the comparable-subset projection normalizes those away.
# ---------------------------------------------------------------------------

_CORPUS: dict[str, dict] = {
    "tpch_join_aggregate": {
        # Relational backbone every engine must agree on for this canonical shape.
        "invariant": {
            LogicalOperatorType.SCAN.value: 2,
            LogicalOperatorType.JOIN.value: 1,
            LogicalOperatorType.AGGREGATE.value: 1,
        },
        "fixtures": {
            "clickhouse": "clickhouse_explain_plan_sample.txt",
            "trino": "trino_explain_sample.json",
            "presto": "presto_explain_sample.json",
            "spark": "spark_explain_sample.txt",
            "snowflake": "snowflake_explain_sample.json",
            "databend": "databend_explain_sample.txt",
            "doris": "doris_shape_plan_sample.txt",
            "singlestore": "singlestore_explain_sample.txt",
            "firebolt": "firebolt_explain_sample.txt",
            "duckdb": "motherduck_duckdb_explain_sample.json",
        },
    },
}


def _corpus_cases():
    cases = []
    for query_id, spec in _CORPUS.items():
        for engine, fixture in spec["fixtures"].items():
            cases.append(pytest.param(query_id, engine, fixture, id=f"{query_id}-{engine}"))
    return cases


class TestComparableSubsetProjection:
    """Unit contract for the wrapper-stripped, collapsing backbone projection."""

    def test_drops_wrapper_nodes(self):
        # Project/Filter/Other wrappers must not appear in the backbone counts.
        tree = _op(
            LogicalOperatorType.PROJECT,
            [
                _op(
                    LogicalOperatorType.FILTER,
                    [
                        _op(
                            LogicalOperatorType.OTHER,
                            [_op(LogicalOperatorType.SCAN)],
                        )
                    ],
                )
            ],
        )
        assert structural_backbone_counts(tree) == {LogicalOperatorType.SCAN.value: 1}

    def test_collapses_consecutive_same_type(self):
        # A partial+final aggregate (parent->child Aggregate run) counts once.
        tree = _op(
            LogicalOperatorType.AGGREGATE,
            [_op(LogicalOperatorType.AGGREGATE, [_op(LogicalOperatorType.SCAN)])],
        )
        assert structural_backbone_counts(tree) == {
            LogicalOperatorType.AGGREGATE.value: 1,
            LogicalOperatorType.SCAN.value: 1,
        }

    def test_collapse_looks_through_wrappers(self):
        # Aggregate -> Other(exchange) -> Aggregate still collapses to one aggregate.
        tree = _op(
            LogicalOperatorType.AGGREGATE,
            [
                _op(
                    LogicalOperatorType.OTHER,
                    [_op(LogicalOperatorType.AGGREGATE, [_op(LogicalOperatorType.SCAN)])],
                )
            ],
        )
        assert structural_backbone_counts(tree)[LogicalOperatorType.AGGREGATE.value] == 1

    def test_stacked_joins_are_not_collapsed(self):
        # A left-deep 3-table join (Join over Join over scans) is TWO distinct joins;
        # joins are not collapsible, so they must both be counted.
        tree = _op(
            LogicalOperatorType.JOIN,
            [
                _op(
                    LogicalOperatorType.JOIN,
                    [_op(LogicalOperatorType.SCAN), _op(LogicalOperatorType.SCAN)],
                ),
                _op(LogicalOperatorType.SCAN),
            ],
        )
        counts = structural_backbone_counts(tree)
        assert counts[LogicalOperatorType.JOIN.value] == 2
        assert counts[LogicalOperatorType.SCAN.value] == 3

    def test_stacked_scans_are_not_collapsed(self):
        # A scan over a scan (e.g. a scan of a materialized CTE) is two base scans.
        tree = _op(LogicalOperatorType.SCAN, [_op(LogicalOperatorType.SCAN)])
        assert structural_backbone_counts(tree)[LogicalOperatorType.SCAN.value] == 2

    def test_unrelated_aggregates_separated_by_join_both_count(self):
        # Two aggregates that are NOT a parent->child run (separated by a join) are
        # distinct logical aggregations and must both count.
        tree = _op(
            LogicalOperatorType.AGGREGATE,
            [
                _op(
                    LogicalOperatorType.JOIN,
                    [
                        _op(LogicalOperatorType.AGGREGATE, [_op(LogicalOperatorType.SCAN)]),
                        _op(LogicalOperatorType.SCAN),
                    ],
                )
            ],
        )
        assert structural_backbone_counts(tree)[LogicalOperatorType.AGGREGATE.value] == 2

    def test_empty_only_is_rejected(self):
        tree = _op(LogicalOperatorType.SCAN)
        with pytest.raises(ValueError):
            structural_backbone_counts(tree, only=set())

    def test_sibling_scans_counted_separately(self):
        # A join over two scans must count both scans (siblings, not a collapsed run).
        tree = _op(
            LogicalOperatorType.JOIN,
            [_op(LogicalOperatorType.SCAN), _op(LogicalOperatorType.SCAN)],
        )
        counts = structural_backbone_counts(tree)
        assert counts[LogicalOperatorType.SCAN.value] == 2
        assert counts[LogicalOperatorType.JOIN.value] == 1

    def test_only_restriction_reports_missing_as_zero(self):
        tree = _op(LogicalOperatorType.SCAN)
        counts = structural_backbone_counts(tree, only={LogicalOperatorType.SCAN.value, LogicalOperatorType.JOIN.value})
        assert counts == {LogicalOperatorType.SCAN.value: 1, LogicalOperatorType.JOIN.value: 0}

    def test_signature_is_deterministic_and_sorted(self):
        tree = _op(
            LogicalOperatorType.JOIN,
            [_op(LogicalOperatorType.SCAN), _op(LogicalOperatorType.SCAN)],
        )
        assert comparable_subset_signature(tree) == "Join:1|Scan:2"

    def test_backbones_match_ignores_wrappers(self):
        bare = _op(
            LogicalOperatorType.JOIN,
            [_op(LogicalOperatorType.SCAN), _op(LogicalOperatorType.SCAN)],
        )
        wrapped = _op(
            LogicalOperatorType.PROJECT,
            [
                _op(
                    LogicalOperatorType.JOIN,
                    [
                        _op(LogicalOperatorType.OTHER, [_op(LogicalOperatorType.SCAN)]),
                        _op(LogicalOperatorType.SCAN),
                    ],
                )
            ],
        )
        assert structural_backbones_match(bare, wrapped) is True


class TestCrossEngineConformanceCorpus:
    """Canonical queries must meet the declared backbone invariants on every engine."""

    @pytest.mark.parametrize("query_id, engine, fixture", _corpus_cases())
    def test_engine_meets_backbone_invariant(self, query_id, engine, fixture):
        invariant = _CORPUS[query_id]["invariant"]
        dag = get_parser_for_platform(engine).parse_explain_output(query_id, _load(fixture))
        assert dag is not None, f"{engine} fixture {fixture} failed to parse"

        counts = structural_backbone_counts(dag.logical_root, only=set(invariant))
        assert counts == invariant, (
            f"{engine} backbone {counts} does not meet the {query_id} invariant {invariant}. "
            "A parser's operator harmonization changed; justify it or fix the mapping."
        )

    @pytest.mark.parametrize("query_id", sorted(_CORPUS))
    def test_comparable_subset_is_identical_across_engines(self, query_id):
        # Compares the reliably-cross-engine relational core (the declared invariant
        # keys: scans/joins/aggregates). Presentation operators (Sort/Limit/Window) are
        # deliberately excluded because engines surface them inconsistently in EXPLAIN
        # (e.g. Trino's fixture has a Limit, Presto/Spark have neither, others a Sort),
        # so they are not part of the cross-engine comparable subset by design.
        invariant = _CORPUS[query_id]["invariant"]
        signatures = {}
        for engine, fixture in _CORPUS[query_id]["fixtures"].items():
            dag = get_parser_for_platform(engine).parse_explain_output(query_id, _load(fixture))
            signatures[engine] = comparable_subset_signature(dag.logical_root, only=set(invariant))

        distinct = set(signatures.values())
        assert len(distinct) == 1, (
            f"Comparable-subset signatures diverged across engines for {query_id}: {signatures}. "
            "The wrapper-stripped backbone must be identical across engines for the same query."
        )

    @pytest.mark.parametrize("query_id", sorted(_CORPUS))
    def test_raw_fingerprints_remain_per_engine_distinct(self, query_id):
        # The comparable subset matches across engines, but the RAW fingerprint must
        # stay per-engine (distinct), documenting that it is not a cross-engine key.
        fingerprints = {}
        for engine, fixture in _CORPUS[query_id]["fixtures"].items():
            dag = get_parser_for_platform(engine).parse_explain_output(query_id, _load(fixture))
            fingerprints[engine] = dag.plan_fingerprint

        # Engines harmonize wrappers differently, so raw fingerprints are distinct.
        assert len(set(fingerprints.values())) == len(fingerprints), (
            "Raw per-engine fingerprints unexpectedly collided across engines; "
            "the raw fingerprint is documented as NOT cross-engine comparable."
        )
