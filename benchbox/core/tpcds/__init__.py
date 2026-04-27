"""Minimal TPC-DS benchmark implementation.
Hard requirement on compiled C tools.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DS (TPC-DS) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-DS specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path

from .benchmark import TPCDSBenchmark
from .c_tools import DSQGenBinary, TPCDSCTools, TPCDSError
from .compliance import TpcdsComplianceClass, classify_tpcds_run, validate_tpcds_scale
from .generator import TPCDSGenerator
from .queries import TPCDSQueryManager


def _validate_c_tools() -> None:
    """Validate C tools at import time - warn if missing but allow import.

    This allows users to import the module even if they don't have TPC-DS
    templates installed, which is useful when:
    - Only using other benchmarks (TPC-H, etc.)
    - Installing via pip (templates should be bundled but may be missing)
    - Running in restricted environments like Databricks notebooks

    If tools are missing, users will get a clear error when they try to
    actually use TPC-DS functionality.
    """
    import warnings

    try:
        # Try to initialize dsqgen binary
        dsqgen = DSQGenBinary()

        # Validate key tools exist
        if not dsqgen.templates_dir.exists():
            warnings.warn(
                f"TPC-DS query templates not found at {dsqgen.templates_dir}. "
                "TPC-DS functionality will not work until templates are installed. "
                "If you installed via pip, this may indicate a packaging issue. "
                "Please reinstall benchbox or check that _sources/tpc-ds/query_templates/ exists.",
                ImportWarning,
                stacklevel=2,
            )

    except (TPCDSError, RuntimeError) as e:
        # Warn but don't fail - let users import even if tools unavailable
        tools_path = Path(__file__).parent.parent.parent.parent / "_sources/tpc-ds/tools"
        warnings.warn(
            f"TPC-DS tools unavailable: {e}\n"
            f"TPC-DS functionality will not work until tools are compiled.\n"
            f"To compile: cd {tools_path} && make dsqgen\n"
            "If you only need other benchmarks (TPC-H, etc.), you can ignore this warning.",
            ImportWarning,
            stacklevel=2,
        )


# Validate at import - warn if tools unavailable but allow import
_validate_c_tools()

__all__ = [
    "TPCDSBenchmark",
    "TPCDSQueryManager",
    "TPCDSGenerator",
    "DSQGenBinary",
    "TPCDSCTools",
    "TPCDSError",
    "TpcdsComplianceClass",
    "classify_tpcds_run",
    "validate_tpcds_scale",
]
