from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class ValidationError:
    field: str
    message: str
    value: Any = None


class ResultValidator:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        self.errors: list[ValidationError] = []

    def validate_all(self) -> bool:
        self.errors.clear()
        self._validate_required_fields()
        self._validate_benchmark_metadata()
        self._validate_timing_fields()
        self._validate_query_results()
        self._validate_execution_phases()
        return len(self.errors) == 0

    def _validate_required_fields(self) -> None:
        required = [
            "benchmark_name",
            "platform",
            "scale_factor",
            "execution_id",
            "timestamp",
            "duration_seconds",
            "total_queries",
            "successful_queries",
            "failed_queries",
        ]
        for field in required:
            if field not in self.result:
                self.errors.append(ValidationError(field, f"Required field '{field}' is missing"))
            elif self.result[field] is None:
                self.errors.append(ValidationError(field, f"Required field '{field}' is null"))

    def _validate_benchmark_metadata(self) -> None:
        exec_id = self.result.get("execution_id")
        if exec_id is not None and (not isinstance(exec_id, str) or not exec_id.strip()):
            self.errors.append(ValidationError("execution_id", "execution_id must be a non-empty string", exec_id))

        timestamp = self.result.get("timestamp")
        if timestamp is not None:
            try:
                if isinstance(timestamp, str):
                    datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                self.errors.append(ValidationError("timestamp", f"Invalid timestamp format: {timestamp}", timestamp))

        sf = self.result.get("scale_factor")
        if sf is not None and (not isinstance(sf, int | float) or sf <= 0):
            self.errors.append(ValidationError("scale_factor", "scale_factor must be positive", sf))

        platform = self.result.get("platform")
        if platform is not None and (not isinstance(platform, str) or not platform.strip()):
            self.errors.append(ValidationError("platform", "platform must be a non-empty string", platform))

        bm_name = self.result.get("benchmark_name")
        if bm_name is not None and (not isinstance(bm_name, str) or not bm_name.strip()):
            self.errors.append(ValidationError("benchmark_name", "benchmark_name must be a non-empty string", bm_name))

    def _validate_timing_fields(self) -> None:
        duration = self.result.get("duration_seconds")
        if duration is not None and (not isinstance(duration, int | float) or duration < 0):
            self.errors.append(ValidationError("duration_seconds", "duration_seconds must be non-negative", duration))

        total_exec = self.result.get("total_execution_time")
        if total_exec is not None and (not isinstance(total_exec, int | float) or total_exec < 0):
            self.errors.append(
                ValidationError("total_execution_time", "total_execution_time must be non-negative", total_exec)
            )

    def _validate_query_results(self) -> None:
        query_results = self.result.get("query_results")
        if query_results is None:
            return

        if not isinstance(query_results, list):
            self.errors.append(ValidationError("query_results", "query_results must be an array", type(query_results)))
            return

        total = self.result.get("total_queries", 0)
        successful = self.result.get("successful_queries", 0)
        failed = self.result.get("failed_queries", 0)

        if total != successful + failed:
            self.errors.append(
                ValidationError(
                    "query_counts",
                    f"total_queries ({total}) != successful ({successful}) + failed ({failed})",
                )
            )

        for i, qr in enumerate(query_results):
            self._validate_single_query_result(qr, i)

    def _validate_single_query_result(self, qr: dict[str, Any], index: int) -> None:
        if not isinstance(qr, dict):
            self.errors.append(ValidationError(f"query_results[{index}]", "Query result must be an object", type(qr)))
            return

        query_id = qr.get("query_id")
        if query_id is None or (isinstance(query_id, str) and not query_id.strip()):
            self.errors.append(
                ValidationError(f"query_results[{index}].query_id", "query_id is required and must be non-empty")
            )

        status = qr.get("status")
        valid_statuses = {"SUCCESS", "FAILED", "ERROR", "TIMEOUT", "SKIPPED"}
        if status is not None and status not in valid_statuses:
            self.errors.append(
                ValidationError(
                    f"query_results[{index}].status",
                    f"Invalid status '{status}', expected one of {valid_statuses}",
                    status,
                )
            )

        exec_time = qr.get("execution_time_ms")
        if exec_time is not None and status == "SUCCESS" and (not isinstance(exec_time, int | float) or exec_time < 0):
            self.errors.append(
                ValidationError(
                    f"query_results[{index}].execution_time_ms",
                    "execution_time_ms must be non-negative for successful queries",
                    exec_time,
                )
            )

    def _validate_execution_phases(self) -> None:
        phases = self.result.get("execution_phases")
        if phases is None:
            return

        if not isinstance(phases, dict):
            self.errors.append(ValidationError("execution_phases", "execution_phases must be an object", type(phases)))
            return

        setup = phases.get("setup")
        if setup is not None:
            self._validate_setup_phase(setup)

        power_test = phases.get("power_test")
        if power_test is not None:
            self._validate_power_test_phase(power_test)

        throughput_test = phases.get("throughput_test")
        if throughput_test is not None:
            self._validate_throughput_test_phase(throughput_test)

    def _validate_setup_phase(self, setup: dict[str, Any]) -> None:
        if not isinstance(setup, dict):
            self.errors.append(ValidationError("execution_phases.setup", "setup must be an object", type(setup)))
            return

        data_gen = setup.get("data_generation")
        if data_gen is not None and isinstance(data_gen, dict):
            duration = data_gen.get("duration_ms")
            if duration is not None and (not isinstance(duration, int | float) or duration < 0):
                self.errors.append(
                    ValidationError(
                        "execution_phases.setup.data_generation.duration_ms",
                        "duration_ms must be non-negative",
                        duration,
                    )
                )

        data_load = setup.get("data_loading")
        if data_load is not None and isinstance(data_load, dict):
            duration = data_load.get("duration_ms")
            if duration is not None and (not isinstance(duration, int | float) or duration < 0):
                self.errors.append(
                    ValidationError(
                        "execution_phases.setup.data_loading.duration_ms",
                        "duration_ms must be non-negative",
                        duration,
                    )
                )

    def _validate_power_test_phase(self, power_test: dict[str, Any]) -> None:
        if not isinstance(power_test, dict):
            self.errors.append(
                ValidationError("execution_phases.power_test", "power_test must be an object", type(power_test))
            )
            return

        duration = power_test.get("duration_ms")
        if duration is not None and (not isinstance(duration, int | float) or duration < 0):
            self.errors.append(
                ValidationError(
                    "execution_phases.power_test.duration_ms",
                    "duration_ms must be non-negative",
                    duration,
                )
            )

        query_execs = power_test.get("query_executions")
        if query_execs is not None:
            if not isinstance(query_execs, list):
                self.errors.append(
                    ValidationError(
                        "execution_phases.power_test.query_executions",
                        "query_executions must be an array",
                        type(query_execs),
                    )
                )
            else:
                for i, qe in enumerate(query_execs):
                    self._validate_query_execution(qe, f"execution_phases.power_test.query_executions[{i}]")

    def _validate_throughput_test_phase(self, throughput_test: dict[str, Any]) -> None:
        if not isinstance(throughput_test, dict):
            self.errors.append(
                ValidationError(
                    "execution_phases.throughput_test",
                    "throughput_test must be an object",
                    type(throughput_test),
                )
            )
            return

        num_streams = throughput_test.get("num_streams")
        if num_streams is not None and (not isinstance(num_streams, int) or num_streams < 1):
            self.errors.append(
                ValidationError(
                    "execution_phases.throughput_test.num_streams",
                    "num_streams must be a positive integer",
                    num_streams,
                )
            )

        streams = throughput_test.get("streams")
        if streams is not None and isinstance(streams, list):
            for i, stream in enumerate(streams):
                if isinstance(stream, dict):
                    duration = stream.get("duration_ms")
                    if duration is not None and (not isinstance(duration, int | float) or duration < 0):
                        self.errors.append(
                            ValidationError(
                                f"execution_phases.throughput_test.streams[{i}].duration_ms",
                                "duration_ms must be non-negative",
                                duration,
                            )
                        )

    def _validate_query_execution(self, qe: dict[str, Any], path: str) -> None:
        if not isinstance(qe, dict):
            self.errors.append(ValidationError(path, "Query execution must be an object", type(qe)))
            return

        query_id = qe.get("query_id")
        if query_id is None or (isinstance(query_id, str) and not query_id.strip()):
            self.errors.append(ValidationError(f"{path}.query_id", "query_id is required and must be non-empty"))

        exec_time = qe.get("execution_time_ms")
        if exec_time is not None and (not isinstance(exec_time, int | float) or exec_time < 0):
            self.errors.append(
                ValidationError(f"{path}.execution_time_ms", "execution_time_ms must be non-negative", exec_time)
            )

        status = qe.get("status")
        valid_statuses = {"SUCCESS", "FAILED", "ERROR", "TIMEOUT", "SKIPPED"}
        if status is not None and status not in valid_statuses:
            self.errors.append(
                ValidationError(f"{path}.status", f"Invalid status '{status}', expected one of {valid_statuses}")
            )


def load_result_json(path: Path | str) -> dict[str, Any]:
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate_result_structure(result: dict[str, Any]) -> tuple[bool, list[ValidationError]]:
    validator = ResultValidator(result)
    is_valid = validator.validate_all()
    return is_valid, validator.errors


def validate_execution_phases(result: dict[str, Any]) -> tuple[bool, list[ValidationError]]:
    validator = ResultValidator(result)
    validator._validate_execution_phases()
    return len(validator.errors) == 0, validator.errors


def assert_benchmark_result_valid(result: dict[str, Any]) -> None:
    is_valid, errors = validate_result_structure(result)
    if not is_valid:
        error_messages = "\n".join(f"  - {e.field}: {e.message}" for e in errors)
        raise AssertionError(f"Benchmark result validation failed:\n{error_messages}")


def assert_query_execution_valid(
    query_exec: dict[str, Any],
    *,
    require_positive_time: bool = True,
    require_rows_returned: bool = False,
) -> None:
    assert "query_id" in query_exec, "query_id is required"
    assert query_exec["query_id"], "query_id must be non-empty"

    assert "status" in query_exec, "status is required"
    assert query_exec["status"] in {"SUCCESS", "FAILED", "ERROR", "TIMEOUT", "SKIPPED"}, (
        f"Invalid status: {query_exec['status']}"
    )

    if query_exec["status"] == "SUCCESS":
        assert "execution_time_ms" in query_exec, "execution_time_ms is required for successful queries"
        if require_positive_time:
            assert query_exec["execution_time_ms"] > 0, "execution_time_ms must be positive"
        else:
            assert query_exec["execution_time_ms"] >= 0, "execution_time_ms must be non-negative"

        if require_rows_returned:
            assert "rows_returned" in query_exec, "rows_returned is required"


def assert_phase_timing_valid(
    phase: dict[str, Any],
    phase_name: str,
    *,
    require_positive_duration: bool = True,
) -> None:
    assert "duration_ms" in phase, f"{phase_name} must have duration_ms"
    duration = phase["duration_ms"]
    assert isinstance(duration, int | float), f"{phase_name}.duration_ms must be numeric"
    if require_positive_duration:
        assert duration > 0, f"{phase_name}.duration_ms must be positive"
    else:
        assert duration >= 0, f"{phase_name}.duration_ms must be non-negative"
