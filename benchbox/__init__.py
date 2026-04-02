"""BenchBox - Embedded benchmark datasets and queries for databases.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import logging
from dataclasses import dataclass
from importlib import import_module
from types import ModuleType
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple, Type, Union

# __version__ must be defined before `from . import platforms` because the
# platforms import chain can circle back to benchbox.cli.app which reads
# benchbox.__version__ at module level.
__version__ = "0.2.0"

from benchbox.base import BaseBenchmark
from benchbox.nyctaxi import NYCTaxi
from benchbox.tpcds import TPCDS
from benchbox.tpch import TPCH
from benchbox.tpch_skew import TPCHSkew
from benchbox.tpchavoc import TPCHavoc
from benchbox.tsbs_devops import TSBSDevOps

from . import platforms

# Perform version consistency check on import (but don't fail - just warn)
try:
    from benchbox.utils.version import validate_version_consistency

    try:
        validate_version_consistency()
    except RuntimeError as exc:
        import warnings

        warnings.warn(
            f"{exc}",
            UserWarning,
            stacklevel=2,
        )
except ImportError:
    # Fallback gracefully if version utilities not available
    pass

if TYPE_CHECKING:
    from benchbox.amplab import AMPLab
    from benchbox.clickbench import ClickBench
    from benchbox.coffeeshop import CoffeeShop
    from benchbox.h2odb import H2ODB
    from benchbox.joinorder import JoinOrder
    from benchbox.nyctaxi import NYCTaxi as NYCTaxi_  # noqa: F401
    from benchbox.read_primitives import ReadPrimitives
    from benchbox.ssb import SSB
    from benchbox.tpcdi import TPCDI
    from benchbox.tpcds_obt import TPCDSOBT


@dataclass(frozen=True)
class _BenchmarkSpec:
    """Configuration describing how to import a benchmark lazily."""

    module: str
    class_name: str
    optional_dependencies: tuple[str, ...] = ()
    store_errors: bool = True


# Registry of lazily imported benchmarks (name -> import specification)
_BENCHMARK_REGISTRY: dict[str, _BenchmarkSpec] = {
    "TPCDI": _BenchmarkSpec("tpcdi", "TPCDI", ("tpcdi",)),
    "SSB": _BenchmarkSpec("ssb", "SSB", ("ssb",)),
    "AMPLab": _BenchmarkSpec("amplab", "AMPLab", ("amplab",)),
    "H2ODB": _BenchmarkSpec("h2odb", "H2ODB", ("h2odb",)),
    "ClickBench": _BenchmarkSpec("clickbench", "ClickBench", ("clickbench",)),
    "MetadataPrimitives": _BenchmarkSpec("metadata_primitives", "MetadataPrimitives", ()),
    "ReadPrimitives": _BenchmarkSpec("read_primitives", "ReadPrimitives", ()),
    "WritePrimitives": _BenchmarkSpec("write_primitives", "WritePrimitives", ()),
    "TransactionPrimitives": _BenchmarkSpec("transaction_primitives", "TransactionPrimitives", ()),
    "JoinOrder": _BenchmarkSpec("joinorder", "JoinOrder", ("joinorder",)),
    "CoffeeShop": _BenchmarkSpec("coffeeshop", "CoffeeShop", ("coffeeshop",)),
    "DataVault": _BenchmarkSpec("datavault", "DataVault", ()),
    "TPCDSOBT": _BenchmarkSpec("tpcds_obt", "TPCDSOBT", ()),
}


# Public re-exports for MCP and external consumers — resolved lazily in
# __getattr__ to avoid importing heavy registry modules at package load time.
_PUBLIC_REEXPORTS: dict[str, tuple[str, str]] = {
    "TPCH_DATAFRAME_QUERIES": ("benchbox.core.tpch.dataframe_queries", "TPCH_DATAFRAME_QUERIES"),
    "TPCDS_DATAFRAME_QUERIES": ("benchbox.core.tpcds.dataframe_queries", "TPCDS_DATAFRAME_QUERIES"),
    "DATAFRAME_PLATFORMS": ("benchbox.platforms.dataframe.platform_checker", "DATAFRAME_PLATFORMS"),
}

# Lazy import cache for benchmark classes (stores class or ImportError/None)
_lazy_cache: dict[str, Union[type[BaseBenchmark], ImportError, None]] = {}


def _import_module(module_path: str):
    """Wrapper for importlib.import_module to allow monkeypatching in tests."""

    return import_module(module_path)


def _load_benchmark_class(name: str) -> tuple[Optional[type[BaseBenchmark]], Optional[ImportError]]:
    """Load a benchmark class from the registry, caching the result."""

    cached = _lazy_cache.get(name)
    if isinstance(cached, ImportError):
        return None, cached
    if cached is not None:
        return cached, None

    spec = _BENCHMARK_REGISTRY[name]
    module_path = f"benchbox.{spec.module}"
    logger = logging.getLogger(module_path)

    try:
        module = _import_module(module_path)
        benchmark_class = getattr(module, spec.class_name)
        _lazy_cache[name] = benchmark_class
        logger.debug("Successfully lazy-loaded %s from %s", spec.class_name, module_path)
        return benchmark_class, None
    except ImportError as exc:
        # Store ImportError for enhanced error reporting if requested
        if spec.store_errors:
            _lazy_cache[name] = exc
        else:
            _lazy_cache[name] = None
        logger.debug("Failed to lazy-load %s from %s: %s", spec.class_name, module_path, exc)
        return None, exc


def _clear_lazy_cache() -> None:
    """Clear the lazy import cache (used in tests)."""

    _lazy_cache.clear()


# Expose lazy-loaded classes as module attributes
def __getattr__(name: str) -> Any:
    """Module-level __getattr__ for lazy loading with enhanced error reporting."""
    # Import here to avoid circular imports
    try:
        from benchbox.utils.version import create_import_error
    except ImportError:
        # Fallback to simple error if version utils not available
        def create_import_error(benchmark_name, missing_dependencies=None, original_error=None):
            """Create a minimal import error when rich dependency reporting is unavailable."""
            return ImportError(f"Could not import {benchmark_name}")

    if name == "platforms":
        return platforms

    if name in _PUBLIC_REEXPORTS:
        module_path, attr = _PUBLIC_REEXPORTS[name]
        return getattr(import_module(module_path), attr)

    # Map benchmark names to their lazy importers and potential missing dependencies
    if name in _BENCHMARK_REGISTRY:
        spec = _BENCHMARK_REGISTRY[name]
        cls, original_error = _load_benchmark_class(name)
        if cls is None:
            raise create_import_error(
                benchmark_name=name,
                missing_dependencies=list(spec.optional_dependencies) or None,
                original_error=original_error,
            )
        return cls
    else:
        raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


# Define __all__ for explicit imports
__all__ = [
    "platforms",
    "BaseBenchmark",
    "TPCH",
    "TPCDS",
    "TPCHavoc",
    "TPCHSkew",
    "TSBSDevOps",
    "NYCTaxi",
    "TPCDI",
    "SSB",
    "AMPLab",
    "H2ODB",
    "ClickBench",
    "MetadataPrimitives",
    "ReadPrimitives",
    "WritePrimitives",
    "TransactionPrimitives",
    "JoinOrder",
    "CoffeeShop",
    "DataVault",
    "TPCDSOBT",
    # Public re-exports (MCP / external consumers)
    "TPCH_DATAFRAME_QUERIES",
    "TPCDS_DATAFRAME_QUERIES",
    "DATAFRAME_PLATFORMS",
]
