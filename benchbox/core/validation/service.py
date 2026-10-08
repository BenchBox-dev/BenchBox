from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .engines import (
    DatabaseValidationEngine,
    DataValidationEngine,
    ValidationResult,
    ValidationSummary,
)


@dataclass(frozen=True)
class PlatformValidationResult:
    capabilities: ValidationResult
    connection_health: ValidationResult | None = None


class ValidationService:
    def __init__(
        self,
        *,
        data_engine: DataValidationEngine | None = None,
        db_engine: DatabaseValidationEngine | None = None,
    ) -> None:
        self._data_engine = data_engine or DataValidationEngine()
        self._db_engine = db_engine or DatabaseValidationEngine()

    def run_preflight(
        self,
        benchmark_type: str,
        scale_factor: float,
        output_dir: Path,
    ) -> ValidationResult:

        return self._data_engine.validate_preflight_conditions(benchmark_type, scale_factor, output_dir)

    def run_manifest(self, manifest_path: Path) -> ValidationResult:

        return self._data_engine.validate_generated_data(manifest_path)

    def run_database(
        self,
        connection: Any,
        benchmark_type: str,
        scale_factor: float,
    ) -> ValidationResult:

        return self._db_engine.validate_loaded_data(connection, benchmark_type, scale_factor)

    def run_platform(
        self,
        platform_adapter: Any,
        benchmark_type: str,
        *,
        connection: Any | None = None,
    ) -> PlatformValidationResult:

        capabilities = platform_adapter.validate_platform_capabilities(benchmark_type)
        connection_health = None
        health_checker = getattr(platform_adapter, "validate_connection_health", None)
        if connection is not None and callable(health_checker):
            connection_health = health_checker(connection)

        return PlatformValidationResult(capabilities=capabilities, connection_health=connection_health)

    def run_comprehensive(
        self,
        *,
        benchmark_type: str,
        scale_factor: float,
        output_dir: Path,
        manifest_path: Path | None = None,
        connection: Any | None = None,
        platform_adapter: Any | None = None,
    ) -> list[ValidationResult]:

        results: list[ValidationResult] = []

        preflight = self.run_preflight(benchmark_type, scale_factor, output_dir)
        results.append(preflight)

        if platform_adapter is not None:
            platform_result = self.run_platform(platform_adapter, benchmark_type, connection=connection)
            results.append(platform_result.capabilities)
            if platform_result.connection_health is not None:
                results.append(platform_result.connection_health)

        if manifest_path is not None and manifest_path.exists():
            manifest_result = self.run_manifest(manifest_path)
            results.append(manifest_result)

        if connection is not None:
            db_result = self.run_database(connection, benchmark_type, scale_factor)
            results.append(db_result)

        return results

    @staticmethod
    def summarize(results: Sequence[ValidationResult]) -> ValidationSummary:

        filtered: list[ValidationResult] = [res for res in results if res is not None]
        total = len(filtered)
        passed = sum(1 for res in filtered if res.is_valid)
        failed = total - passed
        warnings = sum(len(res.warnings) for res in filtered)

        return ValidationSummary(
            total_validations=total,
            passed_validations=passed,
            failed_validations=failed,
            warnings_count=warnings,
        )
