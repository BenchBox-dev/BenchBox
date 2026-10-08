# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

import pytest


class ScenarioType(Enum):
    UNIT = "unit"
    INTEGRATION = "integration"
    PERFORMANCE = "performance"
    REGRESSION = "regression"
    ERROR_HANDLING = "error_handling"
    COMPATIBILITY = "compatibility"


class ScenarioComplexity(Enum):
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"
    STRESS = "stress"


@dataclass
class BenchmarkScenario:
    name: str
    scenario_type: ScenarioType
    complexity: ScenarioComplexity
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    expected_outcome: dict[str, Any] = field(default_factory=dict)
    setup_requirements: list[str] = field(default_factory=list)
    cleanup_requirements: list[str] = field(default_factory=list)
    timeout_seconds: Optional[float] = None
    tags: list[str] = field(default_factory=list)

    def should_run_in_ci(self) -> bool:
        if self.complexity == ScenarioComplexity.STRESS:
            return False
        return not (self.timeout_seconds and self.timeout_seconds > 60)


class TPCDSBenchmarkScenarios:
    @staticmethod
    def get_unit_test_scenarios() -> list[BenchmarkScenario]:
        return [
            BenchmarkScenario(
                name="query_manager_basic",
                scenario_type=ScenarioType.UNIT,
                complexity=ScenarioComplexity.SIMPLE,
                description="Basic query manager functionality",
                parameters={
                    "query_ids": [1, 2, 3, 5, 10],
                    "use_enhanced_parsing": False,
                },
                expected_outcome={
                    "queries_retrieved": 5,
                    "all_queries_valid": True,
                    "query_min_length": 100,
                },
                timeout_seconds=5.0,
                tags=["fast", "basic"],
            ),
            BenchmarkScenario(
                name="parameter_generation_comprehensive",
                scenario_type=ScenarioType.UNIT,
                complexity=ScenarioComplexity.MODERATE,
                description="Comprehensive parameter generation testing",
                parameters={
                    "param_types": ["YEAR", "MONTH", "STATE", "CATEGORY", "COLOR"],
                    "iterations_per_type": 100,
                    "validate_ranges": True,
                },
                expected_outcome={
                    "all_params_generated": True,
                    "params_in_valid_range": True,
                    "generation_time_ms": 1000,
                },
                timeout_seconds=10.0,
                tags=["parameters", "comprehensive"],
            ),
            BenchmarkScenario(
                name="stream_generation_validation",
                scenario_type=ScenarioType.UNIT,
                complexity=ScenarioComplexity.MODERATE,
                description="Stream generation and validation",
                parameters={
                    "num_streams": 3,
                    "query_range": (1, 20),
                    "seed": 42,
                    "validate_reproducibility": True,
                },
                expected_outcome={
                    "streams_generated": 3,
                    "reproducible_results": True,
                    "queries_per_stream": 20,
                },
                timeout_seconds=15.0,
                tags=["streams", "reproducibility"],
            ),
            BenchmarkScenario(
                name="validation_framework_complete",
                scenario_type=ScenarioType.UNIT,
                complexity=ScenarioComplexity.COMPLEX,
                description="Complete validation framework testing",
                parameters={
                    "test_infrastructure": True,
                    "test_query_generation": True,
                    "test_parameter_validation": True,
                    "test_performance": True,
                },
                expected_outcome={
                    "infrastructure_valid": True,
                    "queries_valid": True,
                    "parameters_valid": True,
                    "performance_acceptable": True,
                },
                timeout_seconds=30.0,
                tags=["validation", "comprehensive"],
            ),
        ]

    @staticmethod
    def get_integration_test_scenarios() -> list[BenchmarkScenario]:
        return [
            BenchmarkScenario(
                name="end_to_end_query_workflow",
                scenario_type=ScenarioType.INTEGRATION,
                complexity=ScenarioComplexity.MODERATE,
                description="End-to-end query generation workflow",
                parameters={
                    "test_queries": [1, 5, 10, 15, 20],
                    "test_all_variants": True,
                    "validate_sql_syntax": True,
                    "test_parameterization": True,
                },
                expected_outcome={
                    "all_queries_generated": True,
                    "sql_syntax_valid": True,
                    "parameters_substituted": True,
                    "no_template_placeholders": True,
                },
                timeout_seconds=20.0,
                tags=["workflow", "end-to-end"],
            ),
            BenchmarkScenario(
                name="database_integration_comprehensive",
                scenario_type=ScenarioType.INTEGRATION,
                complexity=ScenarioComplexity.COMPLEX,
                description="Comprehensive database integration testing",
                parameters={
                    "create_test_database": True,
                    "populate_sample_data": True,
                    "test_query_execution": True,
                    "test_data_consistency": True,
                    "cleanup_database": True,
                },
                expected_outcome={
                    "database_created": True,
                    "data_populated": True,
                    "queries_executed": True,
                    "results_consistent": True,
                    "cleanup_successful": True,
                },
                setup_requirements=["sqlite3"],
                cleanup_requirements=["remove_test_database"],
                timeout_seconds=45.0,
                tags=["database", "comprehensive"],
            ),
            BenchmarkScenario(
                name="cross_component_interaction",
                scenario_type=ScenarioType.INTEGRATION,
                complexity=ScenarioComplexity.COMPLEX,
                description="Test interaction between all major components",
                parameters={
                    "test_query_manager": True,
                    "test_parameter_generation": True,
                    "test_stream_generation": True,
                    "test_validation": True,
                    "test_performance_monitoring": True,
                },
                expected_outcome={
                    "components_integrated": True,
                    "data_flow_correct": True,
                    "performance_acceptable": True,
                    "no_resource_leaks": True,
                },
                timeout_seconds=60.0,
                tags=["integration", "cross-component"],
            ),
        ]

    @staticmethod
    def get_performance_test_scenarios() -> list[BenchmarkScenario]:
        return [
            BenchmarkScenario(
                name="query_generation_benchmark",
                scenario_type=ScenarioType.PERFORMANCE,
                complexity=ScenarioComplexity.MODERATE,
                description="Benchmark query generation performance",
                parameters={
                    "test_queries": list(range(1, 51)),
                    "iterations": 10,
                    "measure_memory": True,
                    "measure_cpu": True,
                },
                expected_outcome={
                    "queries_per_second": 100,
                    "memory_usage_mb": 50,
                    "cpu_usage_percent": 80,
                },
                timeout_seconds=30.0,
                tags=["performance", "benchmark"],
            ),
            BenchmarkScenario(
                name="concurrent_access_stress",
                scenario_type=ScenarioType.PERFORMANCE,
                complexity=ScenarioComplexity.STRESS,
                description="Stress test concurrent access patterns",
                parameters={
                    "num_threads": 8,
                    "queries_per_thread": 50,
                    "concurrent_duration_seconds": 60,
                    "measure_contention": True,
                },
                expected_outcome={
                    "no_race_conditions": True,
                    "performance_degradation_percent": 20,
                    "all_threads_complete": True,
                },
                timeout_seconds=120.0,
                tags=["performance", "concurrent", "stress"],
            ),
            BenchmarkScenario(
                name="memory_efficiency_sustained",
                scenario_type=ScenarioType.PERFORMANCE,
                complexity=ScenarioComplexity.COMPLEX,
                description="Test memory efficiency under sustained load",
                parameters={
                    "duration_minutes": 5,
                    "queries_per_minute": 100,
                    "monitor_memory_growth": True,
                    "force_gc_periodically": True,
                },
                expected_outcome={
                    "memory_stable": True,
                    "no_memory_leaks": True,
                    "performance_stable": True,
                },
                timeout_seconds=360.0,
                tags=["performance", "memory", "sustained"],
            ),
            BenchmarkScenario(
                name="caching_effectiveness",
                scenario_type=ScenarioType.PERFORMANCE,
                complexity=ScenarioComplexity.MODERATE,
                description="Test caching effectiveness and performance",
                parameters={
                    "cache_types": ["template", "parameter", "query"],
                    "cache_hit_scenarios": 100,
                    "cache_miss_scenarios": 50,
                    "measure_speedup": True,
                },
                expected_outcome={
                    "cache_hit_rate": 0.8,
                    "performance_speedup": 2.0,
                    "cache_memory_reasonable": True,
                },
                timeout_seconds=20.0,
                tags=["performance", "caching"],
            ),
        ]

    @staticmethod
    def get_regression_test_scenarios() -> list[BenchmarkScenario]:
        return [
            BenchmarkScenario(
                name="api_backward_compatibility",
                scenario_type=ScenarioType.REGRESSION,
                complexity=ScenarioComplexity.MODERATE,
                description="Test API backward compatibility",
                parameters={
                    "test_old_api_methods": True,
                    "test_parameter_formats": True,
                    "test_return_formats": True,
                    "compare_with_baseline": True,
                },
                expected_outcome={
                    "old_apis_work": True,
                    "results_identical": True,
                    "no_breaking_changes": True,
                },
                timeout_seconds=15.0,
                tags=["regression", "compatibility"],
            ),
            BenchmarkScenario(
                name="performance_regression_detection",
                scenario_type=ScenarioType.REGRESSION,
                complexity=ScenarioComplexity.MODERATE,
                description="Detect performance regressions",
                parameters={
                    "baseline_performance": {
                        "query_time_ms": 10,
                        "memory_mb": 20,
                        "throughput_qps": 100,
                    },
                    "tolerance_percent": 20,
                    "test_iterations": 5,
                },
                expected_outcome={
                    "no_performance_regression": True,
                    "within_tolerance": True,
                    "consistent_performance": True,
                },
                timeout_seconds=25.0,
                tags=["regression", "performance"],
            ),
            BenchmarkScenario(
                name="output_format_stability",
                scenario_type=ScenarioType.REGRESSION,
                complexity=ScenarioComplexity.SIMPLE,
                description="Test output format stability",
                parameters={
                    "test_query_outputs": [1, 5, 10, 20],
                    "test_stream_outputs": True,
                    "test_schema_outputs": True,
                    "compare_checksums": True,
                },
                expected_outcome={
                    "output_formats_stable": True,
                    "checksums_match": True,
                    "no_format_changes": True,
                },
                timeout_seconds=10.0,
                tags=["regression", "output"],
            ),
        ]

    @staticmethod
    def get_error_handling_scenarios() -> list[BenchmarkScenario]:
        return [
            BenchmarkScenario(
                name="invalid_input_handling",
                scenario_type=ScenarioType.ERROR_HANDLING,
                complexity=ScenarioComplexity.MODERATE,
                description="Test handling of invalid inputs",
                parameters={
                    "invalid_query_ids": [-1, 0, 999, "invalid"],
                    "invalid_parameters": [None, {}, {"INVALID": "value"}],
                    "malformed_data": True,
                    "test_graceful_degradation": True,
                },
                expected_outcome={
                    "errors_handled_gracefully": True,
                    "appropriate_error_messages": True,
                    "no_crashes": True,
                    "state_remains_consistent": True,
                },
                timeout_seconds=10.0,
                tags=["error-handling", "robustness"],
            ),
            BenchmarkScenario(
                name="resource_exhaustion_handling",
                scenario_type=ScenarioType.ERROR_HANDLING,
                complexity=ScenarioComplexity.COMPLEX,
                description="Test behavior under resource exhaustion",
                parameters={
                    "simulate_low_memory": True,
                    "simulate_high_cpu": True,
                    "simulate_io_errors": True,
                    "test_recovery": True,
                },
                expected_outcome={
                    "graceful_degradation": True,
                    "error_reporting": True,
                    "recovery_possible": True,
                    "no_data_corruption": True,
                },
                timeout_seconds=30.0,
                tags=["error-handling", "resources"],
            ),
            BenchmarkScenario(
                name="concurrent_error_scenarios",
                scenario_type=ScenarioType.ERROR_HANDLING,
                complexity=ScenarioComplexity.COMPLEX,
                description="Test error handling under concurrent access",
                parameters={
                    "num_threads": 5,
                    "error_injection_rate": 0.2,
                    "test_deadlock_prevention": True,
                    "test_error_isolation": True,
                },
                expected_outcome={
                    "no_deadlocks": True,
                    "errors_isolated": True,
                    "other_threads_unaffected": True,
                    "consistent_state": True,
                },
                timeout_seconds=20.0,
                tags=["error-handling", "concurrent"],
            ),
        ]

    @staticmethod
    def get_compatibility_scenarios() -> list[BenchmarkScenario]:
        return [
            BenchmarkScenario(
                name="database_compatibility",
                scenario_type=ScenarioType.COMPATIBILITY,
                complexity=ScenarioComplexity.MODERATE,
                description="Test compatibility across database systems",
                parameters={
                    "databases": ["sqlite", "postgresql", "mysql"],
                    "test_sql_generation": True,
                    "test_dialect_translation": True,
                    "validate_syntax": True,
                },
                expected_outcome={
                    "all_databases_supported": True,
                    "sql_valid_for_each": True,
                    "consistent_results": True,
                },
                setup_requirements=["database_drivers"],
                timeout_seconds=30.0,
                tags=["compatibility", "database"],
            ),
            BenchmarkScenario(
                name="python_version_compatibility",
                scenario_type=ScenarioType.COMPATIBILITY,
                complexity=ScenarioComplexity.SIMPLE,
                description="Test compatibility across Python versions",
                parameters={
                    "test_import_compatibility": True,
                    "test_api_compatibility": True,
                    "test_performance_consistency": True,
                },
                expected_outcome={
                    "imports_successful": True,
                    "apis_work": True,
                    "performance_acceptable": True,
                },
                timeout_seconds=15.0,
                tags=["compatibility", "python"],
            ),
            BenchmarkScenario(
                name="scale_factor_compatibility",
                scenario_type=ScenarioType.COMPATIBILITY,
                complexity=ScenarioComplexity.MODERATE,
                description="Test compatibility across different scale factors",
                parameters={
                    "scale_factors": [0.001, 0.01, 0.1, 1.0],
                    "test_functionality": True,
                    "test_performance_scaling": True,
                    "validate_correctness": True,
                },
                expected_outcome={
                    "all_scales_work": True,
                    "performance_scales_reasonably": True,
                    "results_consistent": True,
                },
                timeout_seconds=45.0,
                tags=["compatibility", "scaling"],
            ),
        ]


class ScenarioRunner:
    def __init__(self):
        self.results = {}
        self.current_scenario = None

    def run_scenario(self, scenario: BenchmarkScenario, test_function: Callable) -> dict[str, Any]:
        self.current_scenario = scenario

        start_time = time.time()
        result = {
            "scenario_name": scenario.name,
            "start_time": start_time,
            "status": "running",
            "error": None,
            "metrics": {},
            "outcome": {},
        }

        try:
            test_result = test_function(scenario.parameters)

            result["status"] = "passed"
            result["outcome"] = test_result

            if scenario.expected_outcome:
                validation_result = self._validate_outcome(test_result, scenario.expected_outcome)
                result["validation"] = validation_result

        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)

        finally:
            result["end_time"] = time.time()
            result["duration"] = result["end_time"] - start_time

            if scenario.timeout_seconds and result["duration"] > scenario.timeout_seconds:
                result["status"] = "timeout"

        self.results[scenario.name] = result
        return result

    def _validate_outcome(self, actual: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
        validation = {
            "passed": True,
            "mismatches": [],
            "missing_keys": [],
            "extra_keys": [],
        }

        for key in expected:
            if key not in actual:
                validation["missing_keys"].append(key)
                validation["passed"] = False
            else:
                expected_val = expected[key]
                actual_val = actual[key]

                if isinstance(expected_val, (int, float)) and isinstance(actual_val, (int, float)):
                    if abs(actual_val - expected_val) > abs(expected_val * 0.1):
                        validation["mismatches"].append({"key": key, "expected": expected_val, "actual": actual_val})
                        validation["passed"] = False
                elif actual_val != expected_val:
                    validation["mismatches"].append({"key": key, "expected": expected_val, "actual": actual_val})
                    validation["passed"] = False

        for key in actual:
            if key not in expected:
                validation["extra_keys"].append(key)

        return validation

    def get_summary(self) -> dict[str, Any]:
        total = len(self.results)
        passed = sum(1 for r in self.results.values() if r["status"] == "passed")
        failed = sum(1 for r in self.results.values() if r["status"] == "failed")
        timeout = sum(1 for r in self.results.values() if r["status"] == "timeout")

        return {
            "total_scenarios": total,
            "passed": passed,
            "failed": failed,
            "timeout": timeout,
            "success_rate": passed / total if total > 0 else 0,
            "scenarios": self.results,
        }


@pytest.fixture
def tpcds_test_scenarios():
    return {
        "unit": TPCDSBenchmarkScenarios.get_unit_test_scenarios(),
        "integration": TPCDSBenchmarkScenarios.get_integration_test_scenarios(),
        "performance": TPCDSBenchmarkScenarios.get_performance_test_scenarios(),
        "regression": TPCDSBenchmarkScenarios.get_regression_test_scenarios(),
        "error_handling": TPCDSBenchmarkScenarios.get_error_handling_scenarios(),
        "compatibility": TPCDSBenchmarkScenarios.get_compatibility_scenarios(),
    }


@pytest.fixture
def scenario_runner():
    return ScenarioRunner()


@pytest.fixture
def ci_friendly_scenarios(tpcds_test_scenarios):
    ci_scenarios = {}
    for category, scenarios in tpcds_test_scenarios.items():
        ci_scenarios[category] = [s for s in scenarios if s.should_run_in_ci()]
    return ci_scenarios


def parametrize_by_complexity(complexities: list[ScenarioComplexity] = None):
    if complexities is None:
        complexities = [ScenarioComplexity.SIMPLE, ScenarioComplexity.MODERATE]

    def decorator(func):
        return pytest.mark.parametrize("complexity", complexities)(func)

    return decorator


def parametrize_by_scenario_type(scenario_types: list[ScenarioType] = None):
    if scenario_types is None:
        scenario_types = [ScenarioType.UNIT, ScenarioType.INTEGRATION]

    def decorator(func):
        return pytest.mark.parametrize("scenario_type", scenario_types)(func)

    return decorator


if __name__ == "__main__":
    scenarios = TPCDSBenchmarkScenarios()

    print("Unit Test Scenarios:")
    for scenario in scenarios.get_unit_test_scenarios():
        print(f"  - {scenario.name}: {scenario.description}")

    print("\nIntegration Test Scenarios:")
    for scenario in scenarios.get_integration_test_scenarios():
        print(f"  - {scenario.name}: {scenario.description}")

    print("\nPerformance Test Scenarios:")
    for scenario in scenarios.get_performance_test_scenarios():
        print(f"  - {scenario.name}: {scenario.description}")

    print("\nRegression Test Scenarios:")
    for scenario in scenarios.get_regression_test_scenarios():
        print(f"  - {scenario.name}: {scenario.description}")

    print("\nError Handling Scenarios:")
    for scenario in scenarios.get_error_handling_scenarios():
        print(f"  - {scenario.name}: {scenario.description}")

    print("\nCompatibility Scenarios:")
    for scenario in scenarios.get_compatibility_scenarios():
        print(f"  - {scenario.name}: {scenario.description}")

    all_scenarios = []
    all_scenarios.extend(scenarios.get_unit_test_scenarios())
    all_scenarios.extend(scenarios.get_integration_test_scenarios())
    all_scenarios.extend(scenarios.get_performance_test_scenarios())
    all_scenarios.extend(scenarios.get_regression_test_scenarios())
    all_scenarios.extend(scenarios.get_error_handling_scenarios())
    all_scenarios.extend(scenarios.get_compatibility_scenarios())

    ci_friendly = [s for s in all_scenarios if s.should_run_in_ci()]
    print(f"\nTotal scenarios: {len(all_scenarios)}")
    print(f"CI-friendly scenarios: {len(ci_friendly)}")
    print(f"CI coverage: {len(ci_friendly) / len(all_scenarios) * 100:.1f}%")
