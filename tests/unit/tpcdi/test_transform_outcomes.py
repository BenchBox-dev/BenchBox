from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("pandas")

from benchbox.core.tpcdi.benchmark import TPCDIBenchmark, TPCDITransformationError
from benchbox.core.tpcdi.config import TPCDIConfig

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _benchmark(tmp_path, enable_parallel):
    config = TPCDIConfig(scale_factor=0.01, output_dir=tmp_path, enable_parallel=enable_parallel, max_workers=2)
    return TPCDIBenchmark(config=config)


def _write_customers(path, ids):
    path.write_text("CustomerID,FirstName\n" + "".join(f"{i},Name{i}\n" for i in ids), encoding="utf-8")
    return str(path)


def _source_files(tmp_path):
    good = _write_customers(tmp_path / "customer_good.csv", [1, 2])
    bad = _write_customers(tmp_path / "customer_bad.csv", [3, 4])
    return {"csv": [good, bad]}, bad


def _failing_on(bad_file):
    def transform(file_path, batch_type):
        if file_path == bad_file:
            raise ValueError("unreadable source")
        return {"records_processed": 2, "transformations": ["stub"]}

    return transform


@pytest.mark.parametrize("enable_parallel", [False, True])
def test_failed_file_transform_raises_and_names_file(tmp_path, enable_parallel):
    benchmark = _benchmark(tmp_path, enable_parallel)
    source_files, bad = _source_files(tmp_path)
    transform = benchmark._transform_source_data_parallel if enable_parallel else benchmark._transform_source_data

    with patch.object(benchmark, "_transform_csv_file", _failing_on(bad)):
        with pytest.raises(TPCDITransformationError) as raised:
            transform(source_files, "historical")

    assert raised.value.failed_files == [bad]
    assert bad in str(raised.value)


@pytest.mark.parametrize("enable_parallel", [False, True])
def test_etl_pipeline_fails_when_a_file_transform_fails(tmp_path, enable_parallel):
    benchmark = _benchmark(tmp_path, enable_parallel)
    source_files, bad = _source_files(tmp_path)
    backend = MagicMock()

    with (
        patch.object(benchmark, "generate_source_data", return_value=source_files),
        patch.object(benchmark, "_transform_csv_file", _failing_on(bad)),
    ):
        with pytest.raises(TPCDITransformationError):
            benchmark.run_etl_pipeline(backend=backend, batch_type="historical", validate_data=False)

    assert benchmark.batch_status["historical"]["status"] == "failed"
    assert bad in benchmark.etl_stats["errors"][-1]["error"]


def test_parallel_failure_reports_every_failed_file(tmp_path):
    benchmark = _benchmark(tmp_path, True)
    first = _write_customers(tmp_path / "customer_a.csv", [1])
    second = _write_customers(tmp_path / "customer_b.csv", [2])

    with patch.object(benchmark, "_transform_csv_file", side_effect=ValueError("boom")):
        with pytest.raises(TPCDITransformationError) as raised:
            benchmark._transform_source_data_parallel({"csv": [first, second]}, "historical")

    assert sorted(raised.value.failed_files) == sorted([first, second])


def test_enhanced_data_processing_without_processors_is_not_success(tmp_path):
    benchmark = _benchmark(tmp_path, False)

    results = benchmark._run_enhanced_data_processing()

    assert results["success"] is False
    assert results["error"]


def test_enhanced_data_processing_without_files_is_not_success(tmp_path):
    benchmark = _benchmark(tmp_path, False)
    benchmark.finwire_processor = MagicMock()
    benchmark.customer_mgmt_processor = MagicMock()

    with (
        patch.object(benchmark, "_generate_finwire_data_files", return_value=[]),
        patch.object(benchmark, "_generate_customer_mgmt_data_files", return_value=[]),
    ):
        results = benchmark._run_enhanced_data_processing()

    assert results["success"] is False
    assert results["error"]
    benchmark.finwire_processor.process_finwire_file.assert_not_called()
