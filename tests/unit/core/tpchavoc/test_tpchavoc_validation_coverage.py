"""Coverage-focused tests for TPC-Havoc validation utilities."""

from __future__ import annotations

import pytest

from benchbox.core.tpchavoc.validation import ResultValidator, ValidationError, ValidationReport

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

    assert validator._values_equal("  abc ", "abc")
    assert validator._values_equal(1.0000001, 1.0000002)
    assert validator._values_equal(None, None)
    assert not validator._values_equal(None, 1)
    assert not validator._values_equal("x", "y")


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
