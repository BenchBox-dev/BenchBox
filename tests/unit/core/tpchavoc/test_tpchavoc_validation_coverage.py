"""Coverage-focused tests for TPC-Havoc validation utilities."""

from __future__ import annotations

import math

import pytest

from benchbox.core.tpchavoc.validation import (
    ResultValidator,
    ValidationError,
    ValidationReport,
    calculate_checksum,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def test_validate_results_exact_accepts_reordered_rows() -> None:
    validator = ResultValidator()

    original = [("A", 1.0), ("B", 2.0)]
    variant = [("B", 2.0), ("A", 1.0)]

    assert validator.validate_results_exact(original, variant, query_id=3, variant_id=2)


# --- tie_aware top-N boundary handling (cross-surface gate) -------------------
# The reference (``original``) is in ORDER BY order; the order key is the last
# column, DESC, so the worst-kept value (the boundary) is the minimum. Rows tied
# at that boundary value may be an ambiguous selection across the LIMIT cutoff.


def test_tie_aware_accepts_boundary_tie_swap() -> None:
    """A swap confined to rows tied at the boundary order-key value is accepted."""
    validator = ResultValidator()
    original = [(10, 5), (11, 5), (12, 3), (13, 2), (14, 2)]
    # row (13,2) -> (99,2): a different but equally-valid boundary-tie member
    variant = [(10, 5), (11, 5), (12, 3), (99, 2), (14, 2)]

    assert validator.validate_results_exact(original, variant, 1, 0, tie_aware=True)


def test_tie_aware_off_by_default_still_strict() -> None:
    """Without tie_aware the same boundary-tie swap is a hard failure (unchanged)."""
    validator = ResultValidator()
    original = [(10, 5), (11, 5), (12, 3), (13, 2), (14, 2)]
    variant = [(10, 5), (11, 5), (12, 3), (99, 2), (14, 2)]

    with pytest.raises(ValidationError, match="Value mismatch"):
        validator.validate_results_exact(original, variant, 1, 0)


def test_tie_aware_rejects_non_boundary_value_bug() -> None:
    """A wrong order-key value on a fully-included (non-boundary) row still fails."""
    validator = ResultValidator()
    original = [(10, 5), (11, 5), (12, 3), (13, 2), (14, 2)]
    # top row's order key 5 -> 4: a real value bug, not a boundary tie
    variant = [(10, 4), (11, 5), (12, 3), (13, 2), (14, 2)]

    with pytest.raises(ValidationError):
        validator.validate_results_exact(original, variant, 1, 0, tie_aware=True)


def test_tie_aware_rejects_non_key_bug_on_determined_row() -> None:
    """A wrong non-key value on a non-boundary row is not masked by tie tolerance."""
    validator = ResultValidator()
    original = [(1, "A", 5), (2, "B", 5), (3, "C", 3), (4, "D", 2), (5, "E", 2)]
    # (2,'B',5) -> (2,'X',5): wrong dimension at the TOP (count 5), not the boundary
    variant = [(1, "A", 5), (2, "X", 5), (3, "C", 3), (4, "D", 2), (5, "E", 2)]

    with pytest.raises(ValidationError):
        validator.validate_results_exact(original, variant, 1, 0, tie_aware=True)


def test_tie_aware_rejects_unique_last_row_change() -> None:
    """A unique (untied) boundary row is deterministic and must still match."""
    validator = ResultValidator()
    original = [(10, 5), (11, 4), (12, 3), (13, 2), (14, 1)]
    # last row's non-key value changed; the boundary value 1 is unique (no tie)
    variant = [(10, 5), (11, 4), (12, 3), (13, 2), (99, 1)]

    with pytest.raises(ValidationError):
        validator.validate_results_exact(original, variant, 1, 0, tie_aware=True)


# --- calculate_checksum on NULL-bearing / mixed-type rows ---------------------
# (correctness-gate-value-digest-fidelity-followups w6)
#
# The bounded gate's 18 SF=1 result sets are NULL-free and single-typed per column,
# so calculate_checksum's None-safe / type-safe ``_row_sort_key`` branch is NEVER
# exercised by the gate. A bare ``sorted(rows)`` would raise ``TypeError`` on a
# NULL-bearing column (``None < 1`` unorderable) or a mixed-type column, which the
# gate would mislabel as an execution "error:" rather than a clean digest. These
# tests exercise that path directly so a latent ordering bug in None handling cannot
# hide behind the gate's NULL-free inputs. They FAIL if the None-safe surrogate is
# removed (a bare sort would raise here).


def test_calculate_checksum_null_bearing_rows_are_deterministic() -> None:
    """A column mixing NULL with values hashes deterministically and never raises."""
    rows = [(1, None), (2, "x"), (3, None), (4, "y")]

    first = calculate_checksum(rows)
    second = calculate_checksum(rows)
    assert first == second, "checksum must be deterministic for identical NULL-bearing input"
    # Order-normalized: a permutation of the same rows hashes identically.
    assert calculate_checksum(list(reversed(rows))) == first


def test_calculate_checksum_mixed_type_column_does_not_raise() -> None:
    """A single column mixing int / str / None / float sorts via the surrogate, no TypeError.

    A bare ``sorted`` would raise ``TypeError`` comparing ``int`` with ``str`` (or
    ``None`` with anything); the None-safe ``_row_sort_key`` groups by a stable type
    name so ordering is total. The digest is stable across input permutations.
    """
    rows = [(1,), ("a",), (None,), (2.5,), ("b",), (None,)]

    digest = calculate_checksum(rows)  # must not raise
    assert isinstance(digest, str) and len(digest) == 32  # md5 hex
    # Permutation-invariant (order-normalized) despite the mixed types + NULLs.
    import random

    shuffled = rows[:]
    random.Random(17).shuffle(shuffled)
    assert calculate_checksum(shuffled) == digest


def test_calculate_checksum_collides_null_with_string_null() -> None:
    """A real NULL (None -> 'NULL') and the literal string 'NULL' hash to the same cell text.

    Documents the one ambiguity of the str-rendering primitive: a ``None`` cell and a
    literal ``"NULL"`` string render to the same token. This is an accepted property of
    the shared digest (the gate's reference is DuckDB-pinned and NULL-free), pinned so a
    future change is a conscious one.
    """
    assert calculate_checksum([(None,)]) == calculate_checksum([("NULL",)])


def test_calculate_checksum_collides_across_cell_separator() -> None:
    """A ``"|"`` cell-separator character embedded in a value can alias across row shapes.

    ``calculate_checksum`` joins cells with ``"|"`` with no escaping, so a 2-column row
    whose first cell contains a literal ``"|"`` renders to the SAME row string as a
    genuinely different 2-column row: ``[("a|b", "c")]`` -> ``"a|b|c"`` and
    ``[("a", "b|c")]`` -> ``"a|b|c"``. Accepted as a documented property of this
    digest (see value-digest-collision-pinning.yaml): fixing it would require
    escaping/tagging the render and regenerating the committed reference digest
    (``benchbox/core/expected_results/reference_digests/tpch_value_digests_sf1.json``),
    which is out of scope for pinning alone. Pinned so a future change is conscious,
    following the same discipline as the NULL-vs-"NULL" pin above.
    """
    assert calculate_checksum([("a|b", "c")]) == calculate_checksum([("a", "b|c")])


def test_calculate_checksum_collides_across_row_separator() -> None:
    """A ``"\\n"`` row-separator character embedded in a value can alias across row counts.

    ``calculate_checksum`` joins rows with ``"\\n"`` with no escaping, so a single-row
    result whose one cell contains a literal newline renders identically to a
    genuinely different two-row result: ``[("a\\nb",)]`` and ``[("a",), ("b",)]``
    both render to ``"a\\nb\\n"``. Accepted as a documented property of this digest
    (see value-digest-collision-pinning.yaml) for the same reason as the cell-separator
    pin above - fixing it requires a reference-digest regeneration out of scope here.
    """
    assert calculate_checksum([("a\nb",)]) == calculate_checksum([("a",), ("b",)])


def test_calculate_checksum_collides_str_and_int_dtype() -> None:
    """A string cell and an int cell of the same textual value hash identically.

    ``calculate_checksum`` renders every non-None cell via ``str(val)``, so the string
    ``"1"`` and the int ``1`` both render to the token ``"1"`` and the digest cannot
    distinguish a genuine dtype regression (e.g. an INTEGER column silently becoming
    VARCHAR) from an unchanged value. Audited per value-digest-collision-pinning.yaml
    w1: no other check on the paths this digest guards (TPC-Havoc's
    ``validate_results_checksum`` or the correctness gate's value-digest oracle in
    ``benchbox.core.results.result_digest``) independently verifies cell dtype -
    ``result_digest._normalize_cell`` already documents (and pins in
    ``tests/unit/test_correctness_gate_value_oracle.py::test_digest_couples_value_with_numeric_type``)
    an analogous accepted int-vs-float/Decimal rendering asymmetry for the SAME
    DuckDB-pinned-oracle reason: fixing this collision would change the rendered form
    of every cell and require regenerating the committed reference digest
    (``tpch_value_digests_sf1.json``), which is out of safe scope for this pin-only
    change. Pinned as an accepted property, consistent with the NULL-vs-"NULL" and
    separator pins above.
    """
    assert calculate_checksum([("1",)]) == calculate_checksum([(1,)])


def test_tie_aware_constant_column_is_not_a_boundary_key() -> None:
    """A constant/literal column must not qualify as the tie-boundary key.

    Mirrors ClickBench Q35 (``SELECT 1, URL, COUNT(*) AS c ... ORDER BY c DESC
    LIMIT N``): column 0 is the literal ``1``. A real count bug on a non-boundary
    row (top ``c`` 5 -> 4) shares that constant 1, so treating column 0 as a
    monotonic boundary key would wrongly accept the swap. The actual order key
    (column 2) puts the change off the boundary value, so it must still fail.
    """
    validator = ResultValidator()
    original = [(1, "a", 5), (1, "b", 5), (1, "c", 3), (1, "d", 2), (1, "e", 2)]
    variant = [(1, "a", 4), (1, "b", 5), (1, "c", 3), (1, "d", 2), (1, "e", 2)]

    with pytest.raises(ValidationError):
        validator.validate_results_exact(original, variant, 1, 0, tie_aware=True)


@pytest.mark.parametrize(
    ("original", "variant", "message"),
    [
        ([(1,)], [(1,), (2,)], "Row count mismatch"),
        ([(1, 2)], [(1,)], "Column count mismatch"),
        ([(1, "x")], [(2, "x")], "Value mismatch"),
    ],
)
def test_validate_results_exact_failure_modes(
    original: list[tuple[object, ...]],
    variant: list[tuple[object, ...]],
    message: str,
) -> None:
    validator = ResultValidator()

    with pytest.raises(ValidationError, match=message):
        validator.validate_results_exact(original, variant, query_id=4, variant_id=1)


def test_numeric_and_string_value_comparison_behavior() -> None:
    validator = ResultValidator(tolerance=1e-6)

    assert not validator._values_equal("  abc ", "abc")
    assert validator._values_equal(1.0000001, 1.0000002)
    assert validator._values_equal(None, None)
    assert not validator._values_equal(None, 1)
    assert not validator._values_equal("x", "y")


def test_value_widening_is_strict_by_default_and_explicitly_opted_in() -> None:
    strict = ResultValidator()
    widened = ResultValidator(treat_nan_as_null=True, strip_strings=True)

    assert not strict._values_equal(None, float("nan"))
    assert not strict._values_equal(float("nan"), None)
    assert not strict._values_equal(float("nan"), float("nan"))
    assert not strict._values_equal("foo ", "foo")

    assert widened._values_equal(None, float("nan"))
    assert widened._values_equal(float("nan"), None)
    assert widened._values_equal(float("nan"), float("nan"))
    assert widened._values_equal("foo ", "foo")


def test_validate_results_exact_reports_nan_null_and_whitespace_divergences() -> None:
    strict = ResultValidator()

    with pytest.raises(ValidationError, match="Value mismatch"):
        strict.validate_results_exact([(None,)], [(float("nan"),)], query_id=6, variant_id=1)

    with pytest.raises(ValidationError, match="Value mismatch"):
        strict.validate_results_exact([("foo",)], [("foo ",)], query_id=6, variant_id=2)

    widened = ResultValidator(treat_nan_as_null=True, strip_strings=True)
    assert widened.validate_results_exact([(None,), ("foo",)], [(float("nan"),), ("foo ",)], 6, 3)


def test_treat_nan_as_null_sorts_nan_into_null_bucket_so_rows_pair() -> None:
    """The positional comparator sorts both sides before pairing rows. The NaN-as-NULL
    widening only helps if the sort agrees: a reference NULL row and a candidate NaN
    row must land in the SAME ordinal position. Without normalizing the sort key, NaN
    sorts in the numeric bucket while NULL sorts first, so the rows below pair NULL vs
    a numeric value and raise a spurious mismatch despite the flag."""
    widened = ResultValidator(treat_nan_as_null=True)

    reference = [(None, "a"), (2, "b")]
    candidate = [(2, "b"), (float("nan"), "a")]

    # The sort surrogate maps NaN to the None bucket so both lists order identically.
    assert widened._row_sort_key((float("nan"), "a")) == widened._row_sort_key((None, "a"))
    assert widened.validate_results_exact(reference, candidate, query_id=7, variant_id=1)

    # Strict mode leaves NaN in the numeric bucket (distinct from the None bucket).
    strict = ResultValidator()
    assert strict._row_sort_key((float("nan"), "a")) != strict._row_sort_key((None, "a"))


def test_container_values_compared_elementwise_with_tolerance() -> None:
    """List/struct/map cells recurse so float tolerance + Decimal coercion apply
    INSIDE containers (a DECIMAL array from DuckDB vs the same array as float64
    from a DataFrame surface), while staying order-sensitive for lists."""
    from decimal import Decimal

    validator = ResultValidator(tolerance=1e-6)

    # Nested Decimal-vs-float and nested float precision are tolerated.
    assert validator._values_equal([Decimal("322261.46"), Decimal("1.5")], [322261.46, 1.5])
    assert validator._values_equal([1100.011], [1100.0110000000001])
    assert validator._values_equal({"125": Decimal("806.66")}, {"125": 806.66})
    assert validator._values_equal(Decimal("77.87"), 77.87)

    # Lists stay order-sensitive; length / key / real-value differences still fail.
    assert not validator._values_equal([1, 2, 3], [1, 3, 2])
    assert not validator._values_equal([1, 2], [1, 2, 3])
    assert not validator._values_equal({"a": 1}, {"b": 1})
    assert not validator._values_equal([1.0, 2.0], [1.0, 2.5])
    assert not validator._values_equal([math.nan], [math.nan])


def test_validate_results_checksum_mismatch_raises() -> None:
    validator = ResultValidator()

    with pytest.raises(ValidationError, match="Checksum mismatch"):
        validator.validate_results_checksum([(1, "a")], [(2, "b")], query_id=10, variant_id=9)


def test_validate_aggregation_results_uses_tolerance_for_numeric_columns() -> None:
    validator = ResultValidator(tolerance=1e-3)

    original = [("x", 100.0, 2)]
    variant = [("x", 100.00005, 2)]

    assert validator.validate_aggregation_results(
        original,
        variant,
        query_id=1,
        variant_id=3,
        aggregation_columns=[1],
    )


def test_validate_query1_results_delegates_aggregation_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    validator = ResultValidator()
    captured: dict[str, object] = {}

    def fake_validate(
        original_results: list[tuple[object, ...]],
        variant_results: list[tuple[object, ...]],
        query_id: int,
        variant_id: int,
        aggregation_columns: list[int] | None = None,
    ) -> bool:
        captured["query_id"] = query_id
        captured["variant_id"] = variant_id
        captured["aggregation_columns"] = aggregation_columns
        return True

    monkeypatch.setattr(validator, "validate_aggregation_results", fake_validate)

    assert validator.validate_query1_results([("R", "F", 1.0)], [("R", "F", 1.0)], variant_id=4)
    assert captured == {
        "query_id": 1,
        "variant_id": 4,
        "aggregation_columns": [2, 3, 4, 5, 6, 7, 8],
    }


def test_calculate_checksum_represents_null_values() -> None:
    validator = ResultValidator()

    checksum1 = validator._calculate_checksum([(1, None), (2, "x")])
    checksum2 = validator._calculate_checksum([(2, "x"), (1, None)])

    assert checksum1 == checksum2


def test_validation_report_summaries_and_text_report() -> None:
    report = ValidationReport()
    report.add_validation_result(1, 1, success=True, execution_time_original=10.0, execution_time_variant=9.0)
    report.add_validation_result(2, 1, success=False, error_message="mismatch")

    summary = report.get_summary()
    perf = report.get_performance_summary()
    text = report.generate_report()

    assert summary["total_tests"] == 2
    assert summary["successful_tests"] == 1
    assert summary["failed_queries"] == ["Q2.1"]
    assert perf["variants_faster"] == 1
    assert "TPC-Havoc Validation Report" in text
    assert "Q2.1" in text


def test_validation_report_no_performance_data_message() -> None:
    report = ValidationReport()
    report.add_validation_result(3, 1, success=True)

    assert report.get_performance_summary() == {"message": "No performance data available"}


# ---------------------------------------------------------------------------
# TPCHavocBenchmark delegation to TPCHavocQueryManager
# ---------------------------------------------------------------------------


def _make_benchmark(tmp_path, monkeypatch):
    """Create a TPCHavocBenchmark with a mocked query manager."""
    from unittest.mock import MagicMock

    from benchbox.core.tpchavoc.benchmark import TPCHavocBenchmark

    bench = TPCHavocBenchmark(scale_factor=0.01, output_dir=tmp_path)
    mock_qm = MagicMock()
    bench.query_manager = mock_qm
    return bench, mock_qm


def test_get_query_delegates_to_query_manager(tmp_path, monkeypatch) -> None:
    bench, mock_qm = _make_benchmark(tmp_path, monkeypatch)
    mock_qm.get_query.return_value = "SELECT 1"

    result = bench.get_query(1)

    mock_qm.get_query.assert_called_once_with(1, seed=None, scale_factor=pytest.approx(0.01))
    assert result == "SELECT 1"


def test_get_query_variant_delegates(tmp_path, monkeypatch) -> None:
    bench, mock_qm = _make_benchmark(tmp_path, monkeypatch)
    mock_qm.get_query_variant.return_value = "SELECT variant"

    result = bench.get_query_variant(2, 3)

    mock_qm.get_query_variant.assert_called_once_with(2, 3, None, scale_factor=bench.scale_factor)
    assert result == "SELECT variant"


def test_get_all_variants_delegates(tmp_path, monkeypatch) -> None:
    bench, mock_qm = _make_benchmark(tmp_path, monkeypatch)
    mock_qm.get_all_variants.return_value = {1: "SELECT a", 2: "SELECT b"}

    result = bench.get_all_variants(1)

    assert result == {1: "SELECT a", 2: "SELECT b"}
    mock_qm.get_all_variants.assert_called_once_with(1, scale_factor=bench.scale_factor)


def test_get_variant_description_delegates(tmp_path, monkeypatch) -> None:
    bench, mock_qm = _make_benchmark(tmp_path, monkeypatch)
    mock_qm.get_variant_description.return_value = "Uses window function"

    result = bench.get_variant_description(5, 2)

    assert result == "Uses window function"


def test_get_implemented_queries_delegates(tmp_path, monkeypatch) -> None:
    bench, mock_qm = _make_benchmark(tmp_path, monkeypatch)
    mock_qm.get_implemented_queries.return_value = [1, 2, 3]

    result = bench.get_implemented_queries()

    assert result == [1, 2, 3]


def test_get_all_variants_info_delegates(tmp_path, monkeypatch) -> None:
    bench, mock_qm = _make_benchmark(tmp_path, monkeypatch)
    mock_qm.get_all_variants_info.return_value = {1: {"sql": "..."}, 2: {"sql": "..."}}

    result = bench.get_all_variants_info(3)

    mock_qm.get_all_variants_info.assert_called_once_with(3)
    assert 1 in result


def test_validate_variant_equivalence_exact_path(tmp_path, monkeypatch) -> None:
    bench, _ = _make_benchmark(tmp_path, monkeypatch)

    from unittest.mock import MagicMock

    mock_validator = MagicMock()
    mock_validator.validate_results_exact.return_value = True
    bench.validator = mock_validator

    result = bench.validate_variant_equivalence(
        query_id=5,
        variant_id=1,
        original_results=[(1,)],
        variant_results=[(1,)],
    )

    assert result is True
    mock_validator.validate_results_exact.assert_called_once()


def test_validate_variant_equivalence_query1_path(tmp_path, monkeypatch) -> None:
    bench, _ = _make_benchmark(tmp_path, monkeypatch)

    from unittest.mock import MagicMock

    mock_validator = MagicMock()
    mock_validator.validate_query1_results.return_value = True
    bench.validator = mock_validator

    result = bench.validate_variant_equivalence(
        query_id=1,
        variant_id=2,
        original_results=[(1,)],
        variant_results=[(1,)],
    )

    assert result is True
    mock_validator.validate_query1_results.assert_called_once()


def test_validate_variant_equivalence_checksum_path(tmp_path, monkeypatch) -> None:
    bench, _ = _make_benchmark(tmp_path, monkeypatch)

    from unittest.mock import MagicMock

    mock_validator = MagicMock()
    mock_validator.validate_results_checksum.return_value = True
    bench.validator = mock_validator

    result = bench.validate_variant_equivalence(
        query_id=3,
        variant_id=1,
        original_results=[(1,)],
        variant_results=[(1,)],
        use_checksum=True,
    )

    assert result is True
    mock_validator.validate_results_checksum.assert_called_once()


def test_get_benchmark_info_structure(tmp_path, monkeypatch) -> None:
    bench, mock_qm = _make_benchmark(tmp_path, monkeypatch)
    mock_qm.get_implemented_queries.return_value = [1, 6]
    mock_qm.get_all_variants_info.return_value = {1: {"sql": "..."}}

    info = bench.get_benchmark_info()

    assert info["benchmark_name"] == "TPC-Havoc"
    assert info["scale_factor"] == pytest.approx(0.01)
    assert info["total_queries_with_variants"] == 2
    assert info["variants_per_query"] == 10


def test_export_variant_queries_creates_sql_files(tmp_path, monkeypatch) -> None:
    bench, mock_qm = _make_benchmark(tmp_path, monkeypatch)
    mock_qm.get_implemented_queries.return_value = [1]
    mock_qm.get_all_variants.return_value = {1: "SELECT 1", 2: "SELECT 2"}
    mock_qm.get_variant_description.return_value = "Uses CTE"

    output_dir = tmp_path / "queries"
    exported = bench.export_variant_queries(output_dir=output_dir, format="sql")

    assert len(exported) == 2
    assert (output_dir / "q1_variant_1.sql").exists()
    assert (output_dir / "q1_variant_2.sql").exists()
    content = (output_dir / "q1_variant_1.sql").read_text()
    assert "TPC-Havoc Query 1 Variant 1" in content


def test_export_variant_queries_invalid_format(tmp_path, monkeypatch) -> None:
    bench, _ = _make_benchmark(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="Unsupported"):
        bench.export_variant_queries(output_dir=tmp_path, format="xml")
