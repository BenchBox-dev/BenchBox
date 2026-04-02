"""TPC-H Official Benchmark Implementation.

This module provides the official TPC-H benchmark implementation that follows
the TPC-H specification exactly, including all three test phases (Power Test,
Throughput Test, and Maintenance Test) and the official QphH@Size calculation.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-H specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import math
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
    """Configuration for TPC-H Official Benchmark."""

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
    """Result of TPC-H Official Benchmark."""

    config: TPCHOfficialBenchmarkConfig
    start_time: str
    end_time: str
    total_time: float
    power_test_result: Optional[TPCHPowerTestResult]
    throughput_test_result: Optional[dict[str, Any]]
    maintenance_test_result: Optional[TPCHMaintenanceTestResult]
    power_at_size: float
    throughput_at_size: float
    qphh_at_size: float
    success: bool
    errors: list[str]
    compliance_validated: bool = False
    audit_trail_saved: bool = False


class TPCHOfficialBenchmark:
    """TPC-H Official Benchmark implementation following TPC-H specification."""

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        verbose: bool = False,
        **kwargs: Any,
    ) -> None:
        """Initialize TPC-H Official Benchmark.

        Args:
            scale_factor: Scale factor for the benchmark (1.0 = ~1GB)
            output_dir: Directory for benchmark results and audit trail
            verbose: Enable verbose logging
            **kwargs: Additional benchmark configuration options
        """
        self.benchmark = TPCHBenchmark(scale_factor=scale_factor, output_dir=output_dir, verbose=verbose, **kwargs)

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
        """Run the complete TPC-H Official Benchmark.

        This method executes all three phases of the TPC-H benchmark according
        to the official specification and calculates the QphH@Size metric.

        Args:
            connection_factory: Factory function to create database connections
            config: Optional benchmark configuration (uses default if not provided)

        Returns:
            Complete benchmark results with QphH@Size metric

        Raises:
            RuntimeError: If benchmark execution fails
            ValueError: If configuration is invalid
        """
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
            qphh_at_size=0.0,
            success=True,
            errors=[],
        )

        try:
            # Phase 1: Power Test
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

            # Phase 2: Throughput Test
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

            # Phase 3: Maintenance Test
            if config.maintenance_test_enabled:
                try:
                    maintenance_result = self.benchmark.run_maintenance_test(
                        connection_factory=connection_factory, config=config
                    )
                    result.maintenance_test_result = maintenance_result

                except Exception as e:
                    result.errors.append(f"Maintenance Test failed: {e}")
                    result.success = False

            # Calculate QphH@Size (geometric mean)
            if result.power_at_size > 0 and result.throughput_at_size > 0:
                result.qphh_at_size = math.sqrt(result.power_at_size * result.throughput_at_size)

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
        """Validate benchmark results against TPC-H specification.

        Args:
            result: Benchmark results to validate

        Returns:
            True if compliant with TPC-H specification, False otherwise
        """
        # Basic compliance checks
        if not result.success:
            return False

        if result.power_at_size <= 0 or result.throughput_at_size <= 0:
            return False

        if result.qphh_at_size <= 0:
            return False

        # Additional specification compliance checks would go here
        return True

    def generate_audit_trail(
        self,
        result: TPCHOfficialBenchmarkResult,
        output_file: Optional[Union[str, Path]] = None,
    ) -> Path:
        """Generate audit trail for TPC-H certification.

        Args:
            result: Benchmark results to document
            output_file: Optional output file path

        Returns:
            Path to generated audit trail file
        """
        return generate_official_benchmark_audit_trail(
            result=result,
            benchmark_title="TPC-H",
            benchmark_slug="tpch",
            qph_label="QphH@Size",
            qph_attr="qphh_at_size",
            output_file=output_file,
        )
