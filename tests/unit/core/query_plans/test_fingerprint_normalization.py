# Copyright 2026 Joe Harris / BenchBox Project
#
# Licensed under the MIT License. See LICENSE file in the project root for details.

"""Unit tests for opt-in literal normalization in plan fingerprints.

The default ``plan_fingerprint`` embeds filter/join/projection literals verbatim,
so two runs with different benchmark seeds produce different fingerprints for
structurally identical plans (a false-positive "plan changed" signal). The
opt-in ``normalize_literals`` path masks numeric/string literals to
``<NUM>``/``<STR>`` so seed-varied plans share a fingerprint, while leaving the
default behaviour and all identifier fields untouched.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from benchbox.core.manifest.models import PLAN_FINGERPRINT_SCHEME_NORMALIZED, PlanMetadata
from benchbox.core.manifest.plan_metadata_utils import (
    PlanFingerprintSchemeMismatchError,
    create_plan_metadata_from_results,
    merge_plan_metadata,
    update_plan_versions,
)
from benchbox.core.results.query_plan_models import (
    LogicalOperator,
    LogicalOperatorType,
    QueryPlanDAG,
    compute_plan_fingerprint,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _scan(filter_expr: str | None = None, **kwargs) -> LogicalOperator:
    """A SCAN operator over ``lineitem`` with an optional filter predicate."""
    return LogicalOperator(
        operator_type=LogicalOperatorType.SCAN,
        operator_id="scan_1",
        table_name="lineitem",
        filter_expressions=[filter_expr] if filter_expr is not None else None,
        **kwargs,
    )


def _dag(root: LogicalOperator, query_id: str = "q1") -> QueryPlanDAG:
    return QueryPlanDAG(query_id=query_id, platform="duckdb", logical_root=root)


class TestStructuralSignatureNormalization:
    def test_numeric_literal_difference_collapses_when_normalized(self):
        """Filters differing only by a numeric literal share a normalized signature."""
        a = _scan("l_quantity < 1234.56")
        b = _scan("l_quantity < 2345.67")

        # Default (literal-sensitive) signatures differ...
        assert a.get_structural_signature() != b.get_structural_signature()
        # ...but normalized signatures are identical.
        assert a.get_structural_signature(normalize_literals=True) == b.get_structural_signature(
            normalize_literals=True
        )
        assert "<NUM>" in a.get_structural_signature(normalize_literals=True)

    def test_string_literal_difference_collapses_when_normalized(self):
        """Filters differing only by a quoted string literal normalize equal."""
        a = _scan("l_shipmode = 'AIR'")
        b = _scan("l_shipmode = 'RAIL'")

        assert a.get_structural_signature() != b.get_structural_signature()
        assert a.get_structural_signature(normalize_literals=True) == b.get_structural_signature(
            normalize_literals=True
        )
        assert "<STR>" in a.get_structural_signature(normalize_literals=True)

    def test_default_signature_unchanged_by_new_parameter(self):
        """normalize_literals=False (default) is byte-identical to the legacy call."""
        op = _scan("l_quantity < 1234.56")
        assert op.get_structural_signature() == op.get_structural_signature(normalize_literals=False)
        # The literal is preserved verbatim in the default signature.
        assert "1234.56" in op.get_structural_signature()
        assert "<NUM>" not in op.get_structural_signature()

    def test_projection_columns_are_not_altered(self):
        """Projection identifiers (no literals) are unchanged by normalization."""
        op = LogicalOperator(
            operator_type=LogicalOperatorType.PROJECT,
            operator_id="proj_1",
            projection_expressions=["l_orderkey", "l_extendedprice"],
        )
        assert op.get_structural_signature(normalize_literals=True) == op.get_structural_signature()

    def test_projection_literal_is_masked_but_column_kept(self):
        """A computed-constant projection masks the literal yet keeps the column name."""
        op = LogicalOperator(
            operator_type=LogicalOperatorType.PROJECT,
            operator_id="proj_1",
            projection_expressions=["l_extendedprice * 0.05 AS tax"],
        )
        normalized = op.get_structural_signature(normalize_literals=True)
        assert "l_extendedprice" in normalized
        assert "<NUM>" in normalized
        assert "0.05" not in normalized

    def test_identifiers_with_trailing_digits_not_masked(self):
        """Column/alias identifiers ending in digits keep their digits."""
        op = _scan("t1.l_orderkey1 > 5")
        normalized = op.get_structural_signature(normalize_literals=True)
        assert "t1.l_orderkey1" in normalized, normalized
        # The standalone literal 5 IS masked.
        assert "> <NUM>" in normalized

    def test_table_and_grouping_identifiers_not_normalized(self):
        """table_name / group_by_keys are identifiers and must survive normalization."""
        op = LogicalOperator(
            operator_type=LogicalOperatorType.AGGREGATE,
            operator_id="agg_1",
            table_name="orders",
            group_by_keys=["o_orderstatus"],
            children=[_scan("o_totalprice > 1000")],
        )
        normalized = op.get_structural_signature(normalize_literals=True)
        assert "table:orders" in normalized
        assert "group:o_orderstatus" in normalized

    def test_aggregation_hex_literal_collapses_when_normalized(self):
        """aggregation_functions/group_by_keys/sort_keys go through _normalize_literal_text,
        a separate normalizer from _mask_literals (used by filter/join/projection). It must
        share the same hardened numeric grammar - otherwise a hex/underscore/dotted literal
        buried in an aggregate call masks in filter expressions but not here, and two
        seed-varied hex constants still produce different normalized signatures."""
        a = LogicalOperator(
            operator_type=LogicalOperatorType.AGGREGATE,
            operator_id="agg_1",
            aggregation_functions=["sum(x + 0xFF)"],
        )
        b = LogicalOperator(
            operator_type=LogicalOperatorType.AGGREGATE,
            operator_id="agg_1",
            aggregation_functions=["sum(x + 0x1A)"],
        )
        assert a.get_structural_signature() != b.get_structural_signature()
        assert a.get_structural_signature(normalize_literals=True) == b.get_structural_signature(
            normalize_literals=True
        )

    def test_ordinal_column_references_survive_normalization_in_group_by(self):
        """DuckDB ordinal refs (#0/#1) in group_by_keys must not be masked - they point at
        a specific (possibly differently-numbered) column, a genuine structural difference,
        not a literal constant. (sort_keys wraps each entry in a Python dict repr before
        normalizing, which quotes - and so fully masks - every field including ordinals;
        that's a separate, pre-existing quirk unrelated to this hardening pass.)"""
        op = LogicalOperator(
            operator_type=LogicalOperatorType.AGGREGATE,
            operator_id="agg_1",
            group_by_keys=["#0", "#1"],
        )
        normalized = op.get_structural_signature(normalize_literals=True)
        assert "#0" in normalized
        assert "#1" in normalized

    def test_escaped_apostrophe_string_literal_masks_as_one_token(self):
        """A doubled single quote is an escaped apostrophe INSIDE the literal, not the
        end of the string. Without treating '' as an escape, 'O''Brien' would split
        into two adjacent string literals ('O' + 'Brien'), leaving <STR><STR> - the
        split itself residual value-dependent syntax - in the "normalized" signature,
        so two seed-varied names could still normalize to different signatures."""
        op = _scan("c_name = 'O''Brien'")
        normalized = op.get_structural_signature(normalize_literals=True)
        assert normalized.count("<STR>") == 1, normalized
        assert "<STR><STR>" not in normalized

    def test_signed_numeric_literal_collapses_regardless_of_sign(self):
        """A threshold that crosses zero across seeds (e.g. -5 vs 5) must still
        normalize to the SAME signature. Masking only the digit run (leaving a bare
        sign character outside the placeholder) would leave -<NUM> and <NUM> as
        distinct tokens - literal-sensitive residue defeating the whole point of
        cross-seed normalization."""
        negative = _scan("l_tax_credit > -5")
        positive = _scan("l_tax_credit > 5")

        assert negative.get_structural_signature() != positive.get_structural_signature()
        assert negative.get_structural_signature(normalize_literals=True) == positive.get_structural_signature(
            normalize_literals=True
        )

    def test_spaced_minus_operator_is_not_absorbed_as_a_sign(self):
        """A '-' separated from its operand by whitespace is a binary operator, not a
        literal's sign, and must stay OUTSIDE the masked token (only the two numeric
        operands are masked)."""
        op = _scan("l_discount = 0.05 - 0.01")
        normalized = op.get_structural_signature(normalize_literals=True)
        assert normalized.endswith("<NUM> - <NUM>"), normalized

    @pytest.mark.parametrize(
        ("literal_a", "literal_b"),
        [
            pytest.param("l_quantity < 1e5", "l_quantity < 2e5", id="scientific-lower-e"),
            pytest.param("l_quantity < 1E5", "l_quantity < 2E5", id="scientific-upper-e"),
            pytest.param("l_quantity < 1.2E-3", "l_quantity < 3.4E-3", id="scientific-negative-exponent"),
            pytest.param("l_flag = 0xFF", "l_flag = 0x1A", id="hex-literal"),
            pytest.param("l_quantity < 1_000", "l_quantity < 2_000", id="underscore-grouped"),
            pytest.param("l_discount < .5", "l_discount < .75", id="leading-dot"),
            pytest.param("l_quantity < 5.", "l_quantity < 9.", id="trailing-dot"),
        ],
    )
    def test_adversarial_numeric_literal_forms_collapse_when_normalized(self, literal_a, literal_b):
        """Scientific/hex/underscore/dotted numeric literals mask atomically.

        These forms previously escaped ``\\b\\d+(?:\\.\\d+)?\\b`` entirely (hex,
        underscore, leading/trailing dot) or were corrupted mid-token (scientific,
        e.g. ``1.2E-3`` -> ``<NUM>.2E-<NUM>``), leaving residual literal-dependent
        text in the "normalized" signature.
        """
        a = _scan(literal_a)
        b = _scan(literal_b)
        assert a.get_structural_signature() != b.get_structural_signature()
        normalized_a = a.get_structural_signature(normalize_literals=True)
        normalized_b = b.get_structural_signature(normalize_literals=True)
        assert normalized_a == normalized_b
        assert normalized_a.count("<NUM>") == 1, normalized_a

    def test_scientific_literal_masked_as_single_atomic_token(self):
        """1.2E-3 must mask as ONE <NUM> token, not corrupt into <NUM>.2E-<NUM>."""
        op = _scan("l_tax = 1.2E-3")
        normalized = op.get_structural_signature(normalize_literals=True)
        assert normalized.count("<NUM>") == 1, normalized
        assert "1.2E-3" not in normalized
        assert ".2E-" not in normalized

    def test_normalization_recurses_into_children(self):
        """Child operator literals are masked too (signature is recursive)."""
        a = LogicalOperator(
            operator_type=LogicalOperatorType.LIMIT,
            operator_id="limit_1",
            limit_count=10,
            children=[_scan("l_quantity < 100")],
        )
        b = LogicalOperator(
            operator_type=LogicalOperatorType.LIMIT,
            operator_id="limit_1",
            limit_count=10,
            children=[_scan("l_quantity < 999")],
        )
        assert a.get_structural_signature() != b.get_structural_signature()
        assert a.get_structural_signature(normalize_literals=True) == b.get_structural_signature(
            normalize_literals=True
        )


class TestComputePlanFingerprint:
    def test_dag_fingerprint_normalized_matches_across_literals(self):
        """QueryPlanDAG.compute_plan_fingerprint(normalize_literals=True) is seed-stable."""
        a = _dag(_scan("l_quantity < 1234.56"))
        b = _dag(_scan("l_quantity < 2345.67"))

        assert a.compute_plan_fingerprint() != b.compute_plan_fingerprint()
        assert a.compute_plan_fingerprint(normalize_literals=True) == b.compute_plan_fingerprint(
            normalize_literals=True
        )

    def test_default_plan_fingerprint_unchanged(self):
        """The stored plan_fingerprint equals the explicit non-normalized computation."""
        dag = _dag(_scan("l_quantity < 1234.56"))
        assert dag.plan_fingerprint == dag.compute_plan_fingerprint(normalize_literals=False)

    def test_normalized_fingerprint_property_cached_and_matches_method(self):
        """normalized_fingerprint matches the method and returns a cached object.

        Asserts the public contract only: SHA256 hexdigests are not interned, so an
        ``is`` identity check across two accesses proves the value is cached rather
        than recomputed each time.
        """
        dag = _dag(_scan("l_quantity < 1234.56"))
        first = dag.normalized_fingerprint
        assert first == dag.compute_plan_fingerprint(normalize_literals=True)
        assert dag.normalized_fingerprint is first  # cached (not recomputed)

    def test_normalized_fingerprint_stable_across_seeds(self):
        """Two seed-varied DAGs share normalized_fingerprint but differ by default."""
        a = _dag(_scan("l_shipmode = 'AIR'"))
        b = _dag(_scan("l_shipmode = 'RAIL'"))
        assert a.plan_fingerprint != b.plan_fingerprint
        assert a.normalized_fingerprint == b.normalized_fingerprint

    def test_refresh_fingerprint_invalidates_normalized_cache(self):
        """After a tree mutation + refresh, normalized_fingerprint tracks the new tree."""
        dag = _dag(_scan("l_quantity < 100"))
        before = dag.normalized_fingerprint  # populate cache against the original tree
        dag.logical_root.table_name = "orders"  # a structural change the mask cannot hide
        dag.refresh_fingerprint()
        after = dag.normalized_fingerprint
        # The cache was invalidated: the property reflects the mutated tree, not the
        # stale pre-refresh value, and still equals a fresh masked computation.
        assert after != before
        assert after == dag.compute_plan_fingerprint(normalize_literals=True)

    def test_module_level_compute_honors_normalize_literals(self):
        """The standalone compute_plan_fingerprint() honors the flag too."""
        a = _scan("l_quantity < 1234.56")
        b = _scan("l_quantity < 2345.67")
        assert compute_plan_fingerprint(a) != compute_plan_fingerprint(b)
        assert compute_plan_fingerprint(a, normalize_literals=True) == compute_plan_fingerprint(
            b, normalize_literals=True
        )


class TestPlanMetadataNormalization:
    @staticmethod
    def _results(query_plan: QueryPlanDAG) -> SimpleNamespace:
        query_result = {"query_id": query_plan.query_id, "query_plan": query_plan}
        return SimpleNamespace(platform="duckdb", platform_version="1.0", query_results=[query_result])

    def test_metadata_default_uses_literal_sensitive_fingerprint(self):
        """Without the flag, two seeds record different fingerprints (the bug)."""
        meta_a = create_plan_metadata_from_results(self._results(_dag(_scan("l_quantity < 1234.56"))))
        meta_b = create_plan_metadata_from_results(self._results(_dag(_scan("l_quantity < 2345.67"))))
        assert meta_a.plan_fingerprints["q1"] != meta_b.plan_fingerprints["q1"]

    def test_metadata_normalized_is_seed_stable(self):
        """With normalize_literals=True, the recorded fingerprints match across seeds."""
        meta_a = create_plan_metadata_from_results(
            self._results(_dag(_scan("l_quantity < 1234.56"))), normalize_literals=True
        )
        meta_b = create_plan_metadata_from_results(
            self._results(_dag(_scan("l_quantity < 2345.67"))), normalize_literals=True
        )
        assert meta_a.plan_fingerprints["q1"] == meta_b.plan_fingerprints["q1"]

    def test_metadata_normalized_differs_from_default(self):
        """The normalized fingerprint is genuinely a different value from the default."""
        plan = _dag(_scan("l_quantity < 1234.56"))
        default_meta = create_plan_metadata_from_results(self._results(plan))
        normalized_meta = create_plan_metadata_from_results(self._results(plan), normalize_literals=True)
        assert default_meta.plan_fingerprints["q1"] != normalized_meta.plan_fingerprints["q1"]

    def test_metadata_records_its_normalization_scheme(self):
        """PlanMetadata.normalization_scheme records which mode produced its fingerprints."""
        plan = _dag(_scan("l_quantity < 1234.56"))
        default_meta = create_plan_metadata_from_results(self._results(plan))
        normalized_meta = create_plan_metadata_from_results(self._results(plan), normalize_literals=True)
        assert default_meta.normalization_scheme == "literal"
        assert normalized_meta.normalization_scheme == PLAN_FINGERPRINT_SCHEME_NORMALIZED


class TestCrossModeMixingRegression:
    """update_plan_versions/merge_plan_metadata must refuse to compare fingerprints
    recorded under different normalization_scheme values - a literal-sensitive
    fingerprint and a literal-normalized one for the SAME plan are different
    values, so naively diffing them reports every query as "changed"
    (update_plan_versions) or silently keeps whichever side wrote last
    (merge_plan_metadata), neither of which is a real signal."""

    @staticmethod
    def _results(query_plan: QueryPlanDAG) -> SimpleNamespace:
        query_result = {"query_id": query_plan.query_id, "query_plan": query_plan}
        return SimpleNamespace(platform="duckdb", platform_version="1.0", query_results=[query_result])

    def test_update_plan_versions_rejects_cross_scheme_comparison(self):
        """Same plan, recorded once literal and once normalized -> mismatch error, not a false version bump."""
        plan = _dag(_scan("l_quantity < 1234.56"))
        literal_meta = create_plan_metadata_from_results(self._results(plan))
        normalized_meta = create_plan_metadata_from_results(self._results(plan), normalize_literals=True)

        with pytest.raises(PlanFingerprintSchemeMismatchError):
            update_plan_versions(literal_meta, normalized_meta)

    def test_merge_plan_metadata_rejects_cross_scheme_comparison(self):
        """Merging a literal-scheme base with a normalized-scheme overlay must raise, not silently mix."""
        plan = _dag(_scan("l_quantity < 1234.56"))
        literal_meta = create_plan_metadata_from_results(self._results(plan))
        normalized_meta = create_plan_metadata_from_results(self._results(plan), normalize_literals=True)

        with pytest.raises(PlanFingerprintSchemeMismatchError):
            merge_plan_metadata(literal_meta, normalized_meta)

    def test_update_plan_versions_same_scheme_still_works(self):
        """The mismatch guard doesn't block the common same-scheme case."""
        prev = create_plan_metadata_from_results(self._results(_dag(_scan("l_quantity < 100"))))
        current = create_plan_metadata_from_results(self._results(_dag(_scan("l_quantity < 999"))))
        update_plan_versions(prev, current)
        assert current.plan_versions["q1"] == 2

    def test_merge_plan_metadata_same_scheme_still_works(self):
        """The mismatch guard doesn't block merging two normalized-scheme metadata instances."""
        base = create_plan_metadata_from_results(
            self._results(_dag(_scan("l_quantity < 100"), query_id="q1")), normalize_literals=True
        )
        overlay = create_plan_metadata_from_results(
            self._results(_dag(_scan("l_quantity < 999"), query_id="q2")), normalize_literals=True
        )
        merged = merge_plan_metadata(base, overlay)
        assert merged.normalization_scheme == PLAN_FINGERPRINT_SCHEME_NORMALIZED
        assert set(merged.plan_fingerprints) == {"q1", "q2"}

    def test_mismatch_guard_skips_when_either_side_has_no_fingerprints(self):
        """A fresh/empty accumulator's default scheme must not block combining with real data."""
        empty = PlanMetadata()
        real = create_plan_metadata_from_results(
            self._results(_dag(_scan("l_quantity < 100"))), normalize_literals=True
        )

        update_plan_versions(empty, real)  # must not raise
        merged = merge_plan_metadata(empty, real)  # must not raise
        assert merged.plan_fingerprints == real.plan_fingerprints
