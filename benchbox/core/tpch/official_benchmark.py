import contextlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, Union

from benchbox.core.throughput.containment import check_phase_boundary
from benchbox.core.throughput.entrypoints import (
    require_adapter,
    require_stream_minimum,
    warn_legacy_throughput_api,
)
from benchbox.core.tpc_patterns import generate_official_benchmark_audit_trail
from benchbox.core.tpch.benchmark import TPCHBenchmark
from benchbox.core.tpch.maintenance_test import (
    TPCHMaintenanceTest,
    TPCHMaintenanceTestResult,
)
from benchbox.core.tpch.power_test import TPCHPowerTest, TPCHPowerTestResult
from benchbox.utils.clock import elapsed_seconds, mono_time


@dataclass
class TPCHOfficialBenchmarkConfig:
    scale_factor: float = 1.0
    num_streams: int = 2
    seed: Optional[int] = None
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
    throughput_test_result: Optional[Any]
    maintenance_test_result: Optional[TPCHMaintenanceTestResult]
    power_at_size: float
    throughput_at_size: float
    success: bool
    errors: list[str]
    compliance_validated: bool = False
    audit_trail_saved: bool = False


def _close_quietly(connection: Any) -> None:
    close = getattr(connection, "close", None)
    if callable(close):
        with contextlib.suppress(Exception):
            close()


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
        *,
        adapter: Any = None,
        _warn_deprecated: bool = True,
    ) -> TPCHOfficialBenchmarkResult:
        if config is None:
            config = self.config

        if _warn_deprecated:
            warn_legacy_throughput_api("TPCHOfficialBenchmark.run_official_benchmark", "tpch")
        if config.throughput_test_enabled:
            require_adapter("TPCHOfficialBenchmark.run_official_benchmark", adapter)
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
                    try:
                        power_result = TPCHPowerTest(
                            benchmark=self.benchmark,
                            connection=connection,
                            scale_factor=config.scale_factor,
                            seed=config.seed,
                            verbose=config.verbose,
                        ).run()
                    finally:
                        _close_quietly(connection)
                    result.power_test_result = power_result
                    if power_result.success and power_result.queries_successful == power_result.queries_executed > 0:
                        result.power_at_size = power_result.power_at_size
                    else:
                        result.errors.append("Power Test failed: Power@Size withheld from results.")
                        result.success = False

                except Exception as e:
                    result.errors.append(f"Power Test failed: {e}")
                    result.success = False

            if config.throughput_test_enabled:
                try:
                    require_stream_minimum(config.num_streams, "num_streams")
                    shared_connection = connection_factory()
                    try:
                        throughput_result = adapter._run_routed_throughput(
                            self.benchmark,
                            shared_connection,
                            {
                                "num_streams": config.num_streams,
                                "scale_factor": config.scale_factor,
                                "verbose": config.verbose,
                                **({"seed": config.seed} if config.seed is not None else {}),
                            },
                        )
                    finally:
                        _close_quietly(shared_connection)
                    result.throughput_test_result = throughput_result
                    if throughput_result.success and throughput_result.throughput_at_size:
                        result.throughput_at_size = throughput_result.throughput_at_size
                    else:
                        result.errors.append("Throughput Test failed: Throughput@Size withheld from results.")
                        result.success = False

                except Exception as e:
                    result.errors.append(f"Throughput Test failed: {e}")
                    result.success = False

            if config.maintenance_test_enabled:
                boundary = check_phase_boundary(result.throughput_test_result)
                if not boundary.proceed:
                    refusal = f"Maintenance Test refused: {boundary.reason}"
                    result.errors.append(refusal)
                    result.success = False
                else:
                    try:
                        maintenance_result = TPCHMaintenanceTest(
                            connection_factory=connection_factory,
                            scale_factor=config.scale_factor,
                            output_dir=config.output_dir,
                            verbose=config.verbose,
                        ).run_maintenance_test(concurrent_with_queries=False, rf1_interval=0.0, rf2_interval=0.0)
                        result.maintenance_test_result = maintenance_result
                        if not maintenance_result.success:
                            result.errors.append("Maintenance Test failed: " + "; ".join(maintenance_result.errors))
                            result.success = False

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
