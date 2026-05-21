"""Benchmark API contract and core-boundary guards."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import benchbox
from benchbox.base import BENCHMARK_API_SURFACE, RUN_WITH_PLATFORM_API_SURFACE, BaseBenchmark as PublicBaseBenchmark
from benchbox.core.base_benchmark import (
    BENCHMARK_API_DECISION as CORE_BASE_API_DECISION,
    BENCHMARK_API_SURFACE as CORE_BASE_API_SURFACE,
    BaseBenchmark as CoreBaseBenchmark,
)
from benchbox.core.benchmark_loader import BENCHMARK_LOADER_API_SURFACE
from benchbox.core.benchmark_registry import (
    BENCHMARK_CLASS_NAMES,
    BENCHMARK_METADATA,
    CORE_BENCHMARK_CLASS_NAMES,
    list_loader_benchmark_ids,
    list_public_benchmark_ids,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PUBLIC_CONTRACTS_DOC = PROJECT_ROOT / "docs/reference/public-contracts.md"
CORE_ONLY_BENCHMARK_IDS = {"ai_primitives", "joinorder_synthetic"}
BENCHMARK_API_COUNT_MARKER = (
    "Benchmark API snapshot: **23** registry entries; **23** loader-resolved core families; "
    "**22** public discovery entries; **21** top-level Python benchmark facades; "
    "**14** lazy facades; **7** eager facades; **2** core-only benchmark IDs."
)


def test_benchmark_api_surface_markers_match_contract_map() -> None:
    """Runtime modules should expose the API tiers documented for users and contributors."""

    contract_doc = PUBLIC_CONTRACTS_DOC.read_text()

    assert BENCHMARK_API_SURFACE == "beta-public"
    assert RUN_WITH_PLATFORM_API_SURFACE == "beta-public"
    assert PublicBaseBenchmark.api_surface == "beta-public"
    assert PublicBaseBenchmark.run_with_platform_api_surface == "beta-public"
    assert "| `benchbox.base.BaseBenchmark` | `beta-public` |" in contract_doc
    assert "| `BaseBenchmark.run_with_platform` | `beta-public` |" in contract_doc

    assert CORE_BASE_API_SURFACE == "deprecated"
    assert CORE_BASE_API_DECISION == "retained-internal-compatibility-base"
    assert CoreBaseBenchmark.api_surface == "deprecated"
    assert CoreBaseBenchmark.compatibility_marker == "retained-internal-compatibility-base"
    assert "| `benchbox.core.base_benchmark.BaseBenchmark` | `deprecated` |" in contract_doc

    assert BENCHMARK_LOADER_API_SURFACE == "internal"
    assert "| `benchbox.core.benchmark_loader` | `internal` |" in contract_doc


def test_benchmark_registry_wrapper_and_loader_counts_match_contract_map() -> None:
    """Keep public facade, internal loader, and registry counts from drifting silently."""

    top_level_benchmark_exports = set(BENCHMARK_CLASS_NAMES.values()) & set(benchbox.__all__)
    lazy_benchmark_exports = set(benchbox._BENCHMARK_REGISTRY)
    eager_benchmark_exports = top_level_benchmark_exports - lazy_benchmark_exports
    core_only_benchmark_ids = {
        benchmark_id for benchmark_id, class_name in BENCHMARK_CLASS_NAMES.items() if class_name not in benchbox.__all__
    }

    assert len(BENCHMARK_METADATA) == 23
    assert len(BENCHMARK_CLASS_NAMES) == 23
    assert len(CORE_BENCHMARK_CLASS_NAMES) == 23
    assert len(list_loader_benchmark_ids()) == 23
    assert len(list_public_benchmark_ids()) == 22
    assert len(top_level_benchmark_exports) == 21
    assert len(lazy_benchmark_exports) == 14
    assert len(eager_benchmark_exports) == 7
    assert core_only_benchmark_ids == CORE_ONLY_BENCHMARK_IDS
    assert set(list_loader_benchmark_ids()) == set(BENCHMARK_METADATA)
    assert set(list_public_benchmark_ids()) == set(BENCHMARK_METADATA) - {"joinorder_synthetic"}

    assert BENCHMARK_API_COUNT_MARKER in PUBLIC_CONTRACTS_DOC.read_text()


def test_benchmark_api_import_boundary_excludes_platform_adapter_imports() -> None:
    """Core benchmark API files must not import concrete platform adapter modules."""

    targets = [
        PROJECT_ROOT / "benchbox/base.py",
        PROJECT_ROOT / "benchbox/core/base_benchmark.py",
        PROJECT_ROOT / "benchbox/core/benchmark_loader.py",
        PROJECT_ROOT / "benchbox/core/__init__.py",
        *sorted((PROJECT_ROOT / "benchbox/core/tuning").rglob("*.py")),
    ]

    violations: list[str] = []
    for path in targets:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "benchbox.platforms" or alias.name.startswith("benchbox.platforms."):
                        violations.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno} imports {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imports_platform_package = module == "benchbox" and any(
                    alias.name == "platforms" for alias in node.names
                )
                imports_platform_module = module == "benchbox.platforms" or module.startswith("benchbox.platforms.")
                if imports_platform_package or imports_platform_module:
                    imported_names = ", ".join(alias.name for alias in node.names)
                    violations.append(
                        f"{path.relative_to(PROJECT_ROOT)}:{node.lineno} imports {module}.{imported_names}"
                    )

    assert violations == []
