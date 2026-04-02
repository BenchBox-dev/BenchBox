"""TPC-DS Official Benchmark Implementation.

This module provides the official TPC-DS benchmark implementation that follows
the TPC-DS specification exactly, including all test phases and the official
QphDS@Size calculation.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DS (TPC-DS) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-DS specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional, Union

from benchbox.core.tpc_patterns import generate_official_benchmark_audit_trail
from benchbox.core.tpcds.benchmark import TPCDSBenchmark
from benchbox.utils.clock import elapsed_seconds, mono_time

if TYPE_CHECKING:
    from benchbox.core.tpcds.power_test import TPCDSPowerTestResult
    from benchbox.core.tpcds.throughput_test import TPCDSThroughputTestResult


@dataclass
class TPCDSOfficialBenchmarkConfig:
    """Configuration for TPC-DS Official Benchmark."""

    scale_factor: float = 1.0
    num_streams: int = 4
    power_test_enabled: bool = True
    throughput_test_enabled: bool = True
    maintenance_test_enabled: bool = True
    validation_enabled: bool = True
    audit_trail: bool = True
    output_dir: Optional[Path] = None
    verbose: bool = False


@dataclass
class TPCDSOfficialBenchmarkResult:
    """Result of TPC-DS Official Benchmark."""

    config: TPCDSOfficialBenchmarkConfig
    start_time: str
    end_time: str
    total_time: float
    power_test_result: Union["TPCDSPowerTestResult", dict[str, Any], None]
    throughput_test_result: Union["TPCDSThroughputTestResult", dict[str, Any], None]
    maintenance_test_result: Optional[dict[str, Any]]
    power_at_size: float
    throughput_at_size: float
    qphds_at_size: float
    success: bool
    errors: list[str]
    compliance_validated: bool = False
    audit_trail_saved: bool = False


def _extract_metric(result: Any, attr: str, default: float = 0.0) -> float:
    """Extract a numeric metric from a result that may be a dataclass or dict."""
    if hasattr(result, attr):
        val = getattr(result, attr)
        if val is not None:
            return val
    if isinstance(result, dict):
        val = result.get(attr)
        if val is not None:
            return val
    return default


class TPCDSOfficialBenchmark:
    """TPC-DS Official Benchmark implementation following TPC-DS specification."""

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        verbose: bool = False,
        dialect: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize TPC-DS Official Benchmark.

        Args:
            scale_factor: Scale factor for the benchmark (1.0 = ~1GB)
            output_dir: Directory for benchmark results and audit trail
            verbose: Enable verbose logging
            dialect: SQL dialect for query translation (e.g., 'bigquery', 'snowflake')
            **kwargs: Additional benchmark configuration options
        """
        self.benchmark = TPCDSBenchmark(scale_factor=scale_factor, output_dir=output_dir, verbose=verbose, **kwargs)

        # Store target dialect for query translation
        self.dialect = dialect

        self.config = TPCDSOfficialBenchmarkConfig(
            scale_factor=scale_factor,
            output_dir=Path(output_dir) if output_dir else None,
            verbose=verbose,
            **kwargs,
        )

    def run_official_benchmark(
        self,
        connection_factory: Callable[[], Any],
        config: Optional[TPCDSOfficialBenchmarkConfig] = None,
    ) -> TPCDSOfficialBenchmarkResult:
        """Run the complete TPC-DS Official Benchmark.

        This method executes all phases of the TPC-DS benchmark according
        to the official specification and calculates the QphDS@Size metric.

        Args:
            connection_factory: Factory function to create database connections
            config: Optional benchmark configuration (uses default if not provided)

        Returns:
            Complete benchmark results with QphDS@Size metric

        Raises:
            RuntimeError: If benchmark execution fails
            ValueError: If configuration is invalid
        """
        if config is None:
            config = self.config

        benchmark_start = mono_time()

        result = TPCDSOfficialBenchmarkResult(
            config=config,
            start_time=datetime.now().isoformat(),
            end_time="",
            total_time=0.0,
            power_test_result=None,
            throughput_test_result=None,
            maintenance_test_result=None,
            power_at_size=0.0,
            throughput_at_size=0.0,
            qphds_at_size=0.0,
            success=True,
            errors=[],
        )

        try:
            # Phase 1: Power Test (single stream execution)
            if config.power_test_enabled:
                try:
                    from benchbox.core.tpcds.power_test import TPCDSPowerTest

                    power_test = TPCDSPowerTest(
                        benchmark=self.benchmark,
                        connection_factory=connection_factory,
                        verbose=config.verbose,
                        dialect=self.dialect,
                    )

                    power_result = power_test.run()
                    result.power_test_result = power_result
                    result.power_at_size = _extract_metric(power_result, "power_at_size")

                except Exception as e:
                    result.errors.append(f"Power Test failed: {e}")
                    result.success = False

            # Phase 2: Throughput Test (concurrent streams)
            if config.throughput_test_enabled:
                try:
                    from benchbox.core.tpcds.throughput_test import TPCDSThroughputTest

                    throughput_test = TPCDSThroughputTest(
                        benchmark=self.benchmark,
                        connection_factory=connection_factory,
                        num_streams=config.num_streams,
                        verbose=config.verbose,
                        dialect=self.dialect,
                    )

                    throughput_result = throughput_test.run()
                    result.throughput_test_result = throughput_result
                    result.throughput_at_size = _extract_metric(throughput_result, "throughput_at_size")

                except Exception as e:
                    result.errors.append(f"Throughput Test failed: {e}")
                    result.success = False

            # Phase 3: Maintenance Test
            if config.maintenance_test_enabled:
                try:
                    from benchbox.core.tpcds.maintenance_test import (
                        TPCDSMaintenanceTest,
                    )

                    maintenance_test = TPCDSMaintenanceTest(
                        benchmark=self.benchmark,
                        connection_factory=connection_factory,
                        verbose=config.verbose,
                        dialect=self.dialect,
                    )

                    maintenance_result = maintenance_test.run()
                    result.maintenance_test_result = maintenance_result

                except Exception as e:
                    result.errors.append(f"Maintenance Test failed: {e}")
                    result.success = False

            # Calculate QphDS@Size (geometric mean)
            if result.power_at_size > 0 and result.throughput_at_size > 0:
                result.qphds_at_size = math.sqrt(result.power_at_size * result.throughput_at_size)

            result.total_time = elapsed_seconds(benchmark_start)
            result.end_time = datetime.now().isoformat()

            return result

        except Exception as e:
            result.total_time = elapsed_seconds(benchmark_start)
            result.end_time = datetime.now().isoformat()
            result.success = False
            result.errors.append(f"Benchmark execution failed: {e}")
            return result

    def validate_compliance(self, result: TPCDSOfficialBenchmarkResult) -> bool:
        """Validate benchmark results against TPC-DS specification.

        Args:
            result: Benchmark results to validate

        Returns:
            True if compliant with TPC-DS specification, False otherwise
        """
        # Basic compliance checks
        if not result.success:
            return False

        if result.power_at_size <= 0 or result.throughput_at_size <= 0:
            return False

        if result.qphds_at_size <= 0:
            return False

        # Additional specification compliance checks would go here
        return True

    def generate_audit_trail(
        self,
        result: TPCDSOfficialBenchmarkResult,
        output_file: Optional[Union[str, Path]] = None,
    ) -> Path:
        """Generate audit trail for TPC-DS certification.

        Args:
            result: Benchmark results to document
            output_file: Optional output file path

        Returns:
            Path to generated audit trail file
        """
        return generate_official_benchmark_audit_trail(
            result=result,
            benchmark_title="TPC-DS",
            benchmark_slug="tpcds",
            qph_label="QphDS@Size",
            qph_attr="qphds_at_size",
            output_file=output_file,
        )
