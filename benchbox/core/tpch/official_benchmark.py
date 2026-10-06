from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, Union

from benchbox.core.tpc_patterns import generate_official_benchmark_audit_trail
from benchbox.core.tpch.benchmark import TPCHBenchmark
from benchbox.core.tpch.maintenance_test import (
    TPCHMaintenanceTestResult,
)
from benchbox.core.tpch.power_test import TPCHPowerTestResult
from benchbox.utils.clock import elapsed_seconds, mono_time


@dataclass
class TPCHOfficialBenchmarkConfig:
    scale_factor: float = 1.0
    num_streams: int = 2
    power_test_enabled: bool = True
    throughput_test_enabled: bool = True
    maintenance_test_enabled: bool = True
    validation_enabled: bool = True
    audit_trail: bool = True
    output_dir: Optional[Path] = None
    verbose: bool = False


@dataclass
class TPCHOfficialBenchmarkResult:
    config: TPCHOfficialBenchmarkConfig
    start_time: str
    end_time: str
    total_time: float
    power_test_result: Optional[TPCHPowerTestResult]
    throughput_test_result: Optional[dict[str, Any]]
    maintenance_test_result: Optional[TPCHMaintenanceTestResult]
    power_at_size: float
    throughput_at_size: float
    success: bool
    errors: list[str]
    compliance_validated: bool = False
    audit_trail_saved: bool = False


class TPCHOfficialBenchmark:
    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        verbose: bool = False,
        **kwargs: Any,
    ) -> None:
        benchmark_kwargs = dict(kwargs)
        benchmark_kwargs.setdefault("official", True)
        self.benchmark = TPCHBenchmark(
            scale_factor=scale_factor, output_dir=output_dir, verbose=verbose, **benchmark_kwargs
        )

        self.config = TPCHOfficialBenchmarkConfig(
            scale_factor=scale_factor,
            output_dir=Path(output_dir) if output_dir else None,
            verbose=verbose,
            **kwargs,
        )

    def run_official_benchmark(
        self,
        connection_factory: Callable[[], Any],
        config: Optional[TPCHOfficialBenchmarkConfig] = None,
    ) -> TPCHOfficialBenchmarkResult:
        if config is None:
            config = self.config

        benchmark_start = mono_time()

        result = TPCHOfficialBenchmarkResult(
            config=config,
            start_time=datetime.now().isoformat(),
            end_time="",
            total_time=0.0,
            power_test_result=None,
            throughput_test_result=None,
            maintenance_test_result=None,
            power_at_size=0.0,
            throughput_at_size=0.0,
            success=True,
            errors=[],
        )

        try:
            if config.power_test_enabled:
                try:
                    connection = connection_factory()
                    connection_string = getattr(connection, "connection_string", "test")
                    connection.close()

                    power_result = self.benchmark.run_power_test(
                        connection_string=connection_string, verbose=config.verbose
                    )
                    result.power_test_result = power_result
                    result.power_at_size = power_result.get("power_at_size", 0.0)

                except Exception as e:
                    result.errors.append(f"Power Test failed: {e}")
                    result.success = False

            if config.throughput_test_enabled:
                try:
                    throughput_result = self.benchmark.run_throughput_test(
                        connection_factory=connection_factory,
                        num_streams=config.num_streams,
                    )
                    result.throughput_test_result = throughput_result
                    result.throughput_at_size = throughput_result.get("throughput_at_size", 0.0)

                except Exception as e:
                    result.errors.append(f"Throughput Test failed: {e}")
                    result.success = False

            if config.maintenance_test_enabled:
                try:
                    maintenance_result = self.benchmark.run_maintenance_test(
                        connection_factory=connection_factory, config=config
                    )
                    result.maintenance_test_result = maintenance_result

                except Exception as e:
                    result.errors.append(f"Maintenance Test failed: {e}")
                    result.success = False

            result.total_time = elapsed_seconds(benchmark_start)
            result.end_time = datetime.now().isoformat()

            return result

        except Exception as e:
            result.total_time = elapsed_seconds(benchmark_start)
            result.end_time = datetime.now().isoformat()
            result.success = False
            result.errors.append(f"Benchmark execution failed: {e}")
            return result

    def validate_compliance(self, result: TPCHOfficialBenchmarkResult) -> bool:
        if not result.success:
            return False

        if result.power_at_size <= 0 or result.throughput_at_size <= 0:
            return False

        return True

    def generate_audit_trail(
        self,
        result: TPCHOfficialBenchmarkResult,
        output_file: Optional[Union[str, Path]] = None,
    ) -> Path:
        return generate_official_benchmark_audit_trail(
            result=result,
            benchmark_title="TPC-H",
            benchmark_slug="tpch",
            output_file=output_file,
        )
