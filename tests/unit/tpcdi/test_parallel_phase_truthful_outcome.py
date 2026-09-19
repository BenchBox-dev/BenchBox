"""
Copyright 2026 Joe Harris / BenchBox Project

Fail-closed outcome tests for the TPC-DI parallel phase.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import sqlite3
from unittest.mock import patch

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


pytest.importorskip("pandas")

from benchbox.core.tpcdi.benchmark import TPCDIBenchmark
from benchbox.core.tpcdi.config import TPCDIConfig
from benchbox.core.tpcdi.etl.parallel_batch_processor import (
    BatchProcessingTask,
    ParallelBatchProcessor,
    ParallelProcessingConfig,
)


@pytest.fixture
def scheduler():
    """Scheduler with monitoring disabled for deterministic unit tests."""
    config = ParallelProcessingConfig(
        max_workers=2,
        enable_dependency_resolution=True,
        task_timeout_seconds=300,
        retry_failed_tasks=False,
        enable_performance_monitoring=False,
    )
    processor = ParallelBatchProcessor(config)
    yield processor
    processor.worker_pool.shutdown(wait=False, cancel_futures=True)


def _ok_task(task_id, value=1):
    def _run(data):
        return {"processed": data.get("value", 0) * 2}

    return BatchProcessingTask(
        task_id=task_id,
        task_function=_run,
        task_data={"value": value},
        dependencies=[],
    )


class TestSchedulerTruthfulOutcome:
    def test_zero_tasks_reports_incomplete_not_success(self, scheduler):
        stats = scheduler.execute_parallel_batch()

        assert stats["success"] is False
        assert stats["outcome"] == "incomplete"
        assert stats["tasks_completed"] == 0
        assert stats["tasks_failed"] == 0
        assert "error_message" in stats

    def test_worker_exception_preserves_cause_and_fails(self, scheduler):
        def _boom(data):
            raise ValueError("Simulated task failure")

        scheduler.submit_task(BatchProcessingTask(task_id="bad_task", task_function=_boom, task_data={}))
        scheduler.submit_task(_ok_task("good_task"))

        stats = scheduler.execute_parallel_batch()

        assert stats["success"] is False
        assert stats["outcome"] == "failed"
        assert stats["tasks_failed"] == 1
        assert stats["tasks_completed"] == 1
        assert stats["failed_task_ids"] == ["bad_task"]
        cause = scheduler.completed_tasks["bad_task"].error_message
        assert "Simulated task failure" in cause
        # The healthy task result is untouched by the sibling failure.
        assert scheduler.completed_tasks["good_task"].success is True

    def test_timeout_reports_timed_out_with_pending_work(self, scheduler):
        scheduler.submit_task(_ok_task("ready_task"))
        scheduler.submit_task(
            BatchProcessingTask(
                task_id="blocked_task",
                task_function=lambda data: {"processed": True},
                task_data={},
                dependencies=["never_submitted"],
            )
        )

        stats = scheduler.execute_parallel_batch(timeout_seconds=0.2)

        assert stats["success"] is False
        assert stats["outcome"] == "timed_out"
        assert stats["timed_out"] is True
        # The blocked task never reaches a worker; at least it stays pending.
        assert stats["tasks_pending"] >= 1
        assert stats["tasks_completed"] <= 1
        assert "unprocessed" in stats["error_message"]

    def test_function_task_executes_with_small_pool(self, scheduler):
        """A function task must run its function even with a two-worker pool."""
        scheduler.submit_task(_ok_task("small_pool_task", value=21))

        stats = scheduler.execute_parallel_batch()

        assert stats["success"] is True
        result = scheduler.completed_tasks["small_pool_task"]
        # The function ran: result_data carries its return value, which the
        # specialized simulators never produce.
        assert result.result_data == {"processed": 42}

    def test_submit_rejects_non_executable_task_before_mutation(self, scheduler):
        with pytest.raises(ValueError, match="non-executable"):
            scheduler.submit_task(BatchProcessingTask(task_id="ghost_task"))

        assert scheduler.task_queue.qsize() == 0
        assert "ghost_task" not in scheduler.pending_tasks

    def test_healthy_run_still_reports_completed(self, scheduler):
        for i in range(3):
            scheduler.submit_task(_ok_task(f"task_{i}", value=i))

        stats = scheduler.execute_parallel_batch()

        assert stats["success"] is True
        assert stats["outcome"] == "completed"
        assert stats["tasks_completed"] == 3
        assert stats["tasks_failed"] == 0
        assert stats["tasks_pending"] == 0


class StubScheduler:
    """Stand-in for the parallel scheduler with a canned result."""

    def __init__(self, result):
        self._result = result

    def submit_task(self, task):
        return task.task_id

    def execute_parallel_batch(self, timeout_seconds=None):
        return dict(self._result)


@pytest.fixture
def tpcdi_benchmark(tmp_path):
    config = TPCDIConfig(scale_factor=0.01, output_dir=tmp_path, enable_parallel=True, max_workers=2)
    return TPCDIBenchmark(config=config)


def _scheduler_result(**overrides):
    result = {
        "tasks_submitted": 3,
        "tasks_completed": 3,
        "tasks_failed": 0,
        "tasks_pending": 0,
        "timed_out": False,
        "failed_task_ids": [],
        "success": True,
        "outcome": "completed",
    }
    result.update(overrides)
    return result


class TestWrapperPropagatesSchedulerOutcome:
    def test_scheduler_failure_with_zero_failed_tasks_is_not_success(self, tpcdi_benchmark):
        tpcdi_benchmark.parallel_batch_processor = StubScheduler(
            _scheduler_result(success=False, outcome="failed", error_message="scheduler boom")
        )

        results = tpcdi_benchmark._run_parallel_batch_processing()

        assert results["success"] is False
        assert results["outcome"] == "failed"
        assert "parallel_batch_processing" in results["error"]
        assert "scheduler boom" in results["error"]

    def test_scheduler_incomplete_zero_task_result_is_not_success(self, tpcdi_benchmark):
        tpcdi_benchmark.parallel_batch_processor = StubScheduler(
            _scheduler_result(
                tasks_submitted=0,
                tasks_completed=0,
                success=False,
                outcome="incomplete",
                error_message="No executable work was submitted for parallel execution",
            )
        )

        results = tpcdi_benchmark._run_parallel_batch_processing()

        assert results["success"] is False
        assert results["outcome"] == "incomplete"
        assert results["batches_processed"] == 0

    def test_scheduler_timeout_is_not_success(self, tpcdi_benchmark):
        tpcdi_benchmark.parallel_batch_processor = StubScheduler(
            _scheduler_result(
                tasks_completed=2,
                tasks_pending=1,
                timed_out=True,
                success=False,
                outcome="timed_out",
                error_message="timed out with 1 of 3 tasks unprocessed",
            )
        )

        results = tpcdi_benchmark._run_parallel_batch_processing()

        assert results["success"] is False
        assert results["outcome"] == "timed_out"

    def test_unavailable_processor_fails_with_named_cause(self, tpcdi_benchmark):
        tpcdi_benchmark.parallel_batch_processor = None

        results = tpcdi_benchmark._run_parallel_batch_processing()

        assert results["success"] is False
        assert "unavailable" in results["error"]
        assert "parallel_batch_processing" in results["error"]

    def test_healthy_scheduler_result_still_succeeds(self, tpcdi_benchmark):
        tpcdi_benchmark.parallel_batch_processor = StubScheduler(_scheduler_result())

        results = tpcdi_benchmark._run_parallel_batch_processing()

        assert results["success"] is True
        assert results["outcome"] == "completed"
        assert results["batches_processed"] == 3


def _phase_results(parallel_success=True, parallel_outcome="completed"):
    parallel: dict = {
        "success": parallel_success,
        "outcome": parallel_outcome,
        "batches_processed": 3 if parallel_success else 0,
        "workers_used": 2,
    }
    if not parallel_success:
        parallel["error"] = "parallel_batch_processing: scheduler did not report success"
    return {
        "_run_enhanced_data_processing": {
            "success": True,
            "total_records": 10,
            "finwire_records": 6,
            "customer_mgmt_records": 4,
        },
        "_run_enhanced_scd_processing": {
            "success": True,
            "records_processed": 8,
            "changes_detected": 2,
        },
        "_run_parallel_batch_processing": parallel,
        "_run_incremental_data_loading": {
            "success": True,
            "batches_loaded": 1,
            "records_loaded": 5,
        },
        "_run_data_quality_monitoring": {
            "success": True,
            "rules_executed": 2,
            "quality_score": 0.9,
            "issues_detected": 0,
        },
    }


def _run_pipeline(tpcdi_benchmark, connection, stubs):
    with (
        patch.object(
            tpcdi_benchmark,
            "_run_enhanced_data_processing",
            return_value=stubs["_run_enhanced_data_processing"],
        ),
        patch.object(
            tpcdi_benchmark,
            "_run_enhanced_scd_processing",
            return_value=stubs["_run_enhanced_scd_processing"],
        ),
        patch.object(
            tpcdi_benchmark,
            "_run_parallel_batch_processing",
            return_value=stubs["_run_parallel_batch_processing"],
        ),
        patch.object(
            tpcdi_benchmark,
            "_run_incremental_data_loading",
            return_value=stubs["_run_incremental_data_loading"],
        ),
        patch.object(
            tpcdi_benchmark,
            "_run_data_quality_monitoring",
            return_value=stubs["_run_data_quality_monitoring"],
        ),
    ):
        return tpcdi_benchmark.run_enhanced_etl_pipeline(
            connection,
            dialect="sqlite",
            enable_parallel_processing=True,
            enable_data_quality_monitoring=True,
            enable_error_recovery=False,
        )


class TestPipelineFailsClosed:
    def test_failed_requested_phase_fails_pipeline_without_success_print(self, tpcdi_benchmark, capsys):
        connection = sqlite3.connect(":memory:")
        try:
            results = _run_pipeline(
                tpcdi_benchmark, connection, _phase_results(parallel_success=False, parallel_outcome="failed")
            )
        finally:
            connection.close()

        assert results["success"] is False
        assert "parallel_batch_processing" in results["failed_phases"]
        assert "parallel_batch_processing" in results["error"]
        assert results["phases"]["parallel_batch_processing"]["success"] is False
        printed = capsys.readouterr().out
        assert "completed successfully" not in printed
        assert "incomplete" in printed

    def test_all_phases_successful_reports_success(self, tpcdi_benchmark, capsys):
        connection = sqlite3.connect(":memory:")
        try:
            results = _run_pipeline(tpcdi_benchmark, connection, _phase_results(parallel_success=True))
        finally:
            connection.close()

        assert results["success"] is True
        assert results["failed_phases"] == []
        assert "completed successfully" in capsys.readouterr().out

    def test_disabled_phases_are_not_required(self, tpcdi_benchmark):
        connection = sqlite3.connect(":memory:")
        try:
            with (
                patch.object(
                    tpcdi_benchmark,
                    "_run_enhanced_data_processing",
                    return_value={"success": True, "total_records": 1},
                ),
                patch.object(
                    tpcdi_benchmark,
                    "_run_enhanced_scd_processing",
                    return_value={"success": True, "records_processed": 1},
                ),
                patch.object(
                    tpcdi_benchmark,
                    "_run_incremental_data_loading",
                    return_value={"success": True, "batches_loaded": 1, "records_loaded": 1},
                ),
            ):
                results = tpcdi_benchmark.run_enhanced_etl_pipeline(
                    connection,
                    dialect="sqlite",
                    enable_parallel_processing=False,
                    enable_data_quality_monitoring=False,
                    enable_error_recovery=False,
                )
        finally:
            connection.close()

        assert results["success"] is True
        assert "parallel_batch_processing" not in results["phases"]
        assert "data_quality_monitoring" not in results["phases"]
