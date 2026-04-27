Additional Utilities API
==========================

.. tags:: reference, python-api

Complete Python API reference for additional BenchBox utilities.

Overview
--------

BenchBox provides several focused utility modules for common tasks: scale factor formatting, dependency validation, and system information collection. These utilities enable consistent naming, dependency management, and environment documentation.

**Utilities Covered**:

- **Scale Factor Formatting**: Consistent naming for files, directories, and schemas
- **Dependency Validation**: Verify dependencies match lock file requirements
- **System Information**: Collect system and hardware information

Scale Factor Utilities
-----------------------

Utilities for consistent scale factor formatting across BenchBox.

Overview
~~~~~~~~

The scale factor utilities provide standardized formatting for scale factors in filenames, directory names, and schema names. This ensures consistency across the framework.

**Formatting Rules**:

- Values >= 1: No leading zero (``sf1``, ``sf10``, ``sf100``)
- Values < 1: Leading zero + decimal digits (``sf01``, ``sf001``, ``sf0001``)
- Non-integer values >= 1: Remove decimal point (``sf15`` for 1.5)

Quick Start
~~~~~~~~~~~

.. code-block:: python

    from benchbox.utils.scale_factor import (
        format_scale_factor,
        format_benchmark_name,
        format_data_directory,
        format_schema_name
    )

    # Format scale factors
    print(format_scale_factor(1.0))    # "sf1"
    print(format_scale_factor(0.1))    # "sf01"
    print(format_scale_factor(0.01))   # "sf001"
    print(format_scale_factor(10.0))   # "sf10"

    # Format names
    print(format_benchmark_name("tpch", 1.0))      # "tpch_sf1"
    print(format_data_directory("tpcds", 0.1))     # "tpcds_sf01_data"
    print(format_schema_name("ssb", 10.0))         # "ssb_sf10"

API Reference
~~~~~~~~~~~~~

.. autofunction:: benchbox.utils.scale_factor.format_scale_factor

**Signature**:

.. code-block:: python

    format_scale_factor(scale_factor: float) -> str

**Parameters**:

- **scale_factor** (float): Scale factor value

**Returns**: Formatted scale factor string (e.g., "sf1", "sf01", "sf001")

**Examples**:

.. code-block:: python

    # Integer values >= 1
    format_scale_factor(1.0)    # "sf1"
    format_scale_factor(10.0)   # "sf10"
    format_scale_factor(100.0)  # "sf100"

    # Decimal values < 1
    format_scale_factor(0.1)    # "sf01"
    format_scale_factor(0.01)   # "sf001"
    format_scale_factor(0.001)  # "sf0001"

    # Non-integer values >= 1
    format_scale_factor(1.5)    # "sf15"
    format_scale_factor(2.25)   # "sf225"

.. autofunction:: benchbox.utils.scale_factor.format_benchmark_name

**Signature**:

.. code-block:: python

    format_benchmark_name(benchmark_name: str, scale_factor: float) -> str

**Parameters**:

- **benchmark_name** (str): Benchmark name (e.g., "tpch", "tpcds")
- **scale_factor** (float): Scale factor value

**Returns**: Formatted benchmark name (e.g., "tpch_sf1", "tpcds_sf01")

**Examples**:

.. code-block:: python

    format_benchmark_name("tpch", 1.0)    # "tpch_sf1"
    format_benchmark_name("tpcds", 0.1)   # "tpcds_sf01"
    format_benchmark_name("ssb", 10.0)    # "ssb_sf10"

.. autofunction:: benchbox.utils.scale_factor.format_data_directory

**Signature**:

.. code-block:: python

    format_data_directory(benchmark_name: str, scale_factor: float) -> str

**Parameters**:

- **benchmark_name** (str): Benchmark name
- **scale_factor** (float): Scale factor value

**Returns**: Formatted directory name (e.g., "tpch_sf1_data", "tpcds_sf01_data")

**Examples**:

.. code-block:: python

    format_data_directory("tpch", 1.0)    # "tpch_sf1_data"
    format_data_directory("tpcds", 0.1)   # "tpcds_sf01_data"
    format_data_directory("ssb", 10.0)    # "ssb_sf10_data"

.. autofunction:: benchbox.utils.scale_factor.format_schema_name

**Signature**:

.. code-block:: python

    format_schema_name(benchmark_name: str, scale_factor: float) -> str

**Parameters**:

- **benchmark_name** (str): Benchmark name
- **scale_factor** (float): Scale factor value

**Returns**: Formatted schema name (e.g., "tpch_sf1", "tpcds_sf01")

**Examples**:

.. code-block:: python

    format_schema_name("tpch", 1.0)    # "tpch_sf1"
    format_schema_name("tpcds", 0.1)   # "tpcds_sf01"
    format_schema_name("ssb", 10.0)    # "ssb_sf10"

Usage Examples
~~~~~~~~~~~~~~

Consistent File Naming
""""""""""""""""""""""

.. code-block:: python

    from pathlib import Path
    from benchbox.utils.scale_factor import format_data_directory

    benchmark = "tpch"
    scale_factor = 1.0

    # Create data directory with consistent naming
    data_dir = Path("data") / format_data_directory(benchmark, scale_factor)
    data_dir.mkdir(parents=True, exist_ok=True)

    print(f"Data directory: {data_dir}")
    # Output: data/tpch_sf1_data

Database Schema Naming
""""""""""""""""""""""

.. code-block:: python

    from benchbox.utils.scale_factor import format_schema_name

    def create_benchmark_schema(conn, benchmark, scale_factor):
        """Create database schema with consistent naming."""
        schema_name = format_schema_name(benchmark, scale_factor)

        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema_name}")
        conn.execute(f"USE SCHEMA {schema_name}")

        print(f"Created schema: {schema_name}")

    create_benchmark_schema(conn, "tpch", 1.0)
    # Output: Created schema: tpch_sf1

Result File Naming
""""""""""""""""""

.. code-block:: python

    import json
    from benchbox.utils.scale_factor import format_benchmark_name

    def save_results(results, benchmark, scale_factor):
        """Save results with consistent naming."""
        name = format_benchmark_name(benchmark, scale_factor)
        filename = f"results_{name}.json"

        with open(filename, "w") as f:
            json.dump(results, f, indent=2)

        print(f"Saved results to: {filename}")

    save_results(benchmark_results, "tpcds", 0.1)
    # Output: Saved results to: results_tpcds_sf01.json

Dependency Validation Utilities
--------------------------------

Utilities for validating BenchBox dependency definitions.

Overview
~~~~~~~~

The dependency validation utilities verify that all declared dependencies in ``pyproject.toml`` have corresponding locked versions in ``uv.lock`` that satisfy the declared specifiers. This ensures dependency consistency and helps catch dependency issues early.

**Key Features**:

- Validate core dependencies
- Validate optional dependencies (extras)
- Build compatibility matrix
- Python version compatibility checking
- CLI tool for CI/CD integration

Quick Start
~~~~~~~~~~~

.. code-block:: python

    from pathlib import Path
    from benchbox.utils.dependency_validation import (
        _load_toml,
        validate_dependency_versions
    )

    # Load dependency files
    pyproject_data = _load_toml(Path("pyproject.toml"))
    lock_data = _load_toml(Path("uv.lock"))

    # Validate dependencies
    problems = validate_dependency_versions(pyproject_data, lock_data)

    if problems:
        print("❌ Dependency validation failed:")
        for problem in problems:
            print(f"  - {problem}")
    else:
        print("✅ All dependencies validated successfully")

API Reference
~~~~~~~~~~~~~

.. autofunction:: benchbox.utils.dependency_validation.validate_dependency_versions

**Signature**:

.. code-block:: python

    validate_dependency_versions(
        pyproject_data: Mapping[str, object],
        lock_data: Mapping[str, object]
    ) -> list[str]

**Parameters**:

- **pyproject_data** (Mapping): Parsed pyproject.toml data
- **lock_data** (Mapping): Parsed uv.lock data

**Returns**: List of problems (empty list indicates success)

**Example**:

.. code-block:: python

    from benchbox.utils.dependency_validation import (
        _load_toml,
        validate_dependency_versions
    )
    from pathlib import Path

    pyproject = _load_toml(Path("pyproject.toml"))
    lock = _load_toml(Path("uv.lock"))

    problems = validate_dependency_versions(pyproject, lock)

    if not problems:
        print("✅ All dependencies valid")
    else:
        for problem in problems:
            print(f"❌ {problem}")

.. autofunction:: benchbox.utils.dependency_validation.build_matrix_summary

**Signature**:

.. code-block:: python

    build_matrix_summary(
        pyproject_data: Mapping[str, object],
        lock_data: Mapping[str, object]
    ) -> dict[str, object]

**Parameters**:

- **pyproject_data** (Mapping): Parsed pyproject.toml data
- **lock_data** (Mapping): Parsed uv.lock data

**Returns**: Summary dictionary with Python compatibility and extras

**Example**:

.. code-block:: python

    from benchbox.utils.dependency_validation import (
        _load_toml,
        build_matrix_summary
    )
    from pathlib import Path

    pyproject = _load_toml(Path("pyproject.toml"))
    lock = _load_toml(Path("uv.lock"))

    matrix = build_matrix_summary(pyproject, lock)

    print(f"Python requires: {matrix['python_requires']}")
    print(f"Optional groups: {list(matrix['optional_dependencies'].keys())}")

CLI Tool
~~~~~~~~

The dependency validation utilities include a CLI tool for CI/CD integration:

.. code-block:: bash

    # Validate dependencies
    python -m benchbox.utils.dependency_validation

    # Display compatibility matrix
    python -m benchbox.utils.dependency_validation --matrix

    # Use custom paths
    python -m benchbox.utils.dependency_validation \
        --pyproject path/to/pyproject.toml \
        --lock path/to/uv.lock

**Exit Codes**:

- ``0``: All dependencies validated successfully
- ``1``: Validation failed (missing or incompatible dependencies)

Usage Examples
~~~~~~~~~~~~~~

CI/CD Integration
"""""""""""""""""

.. code-block:: python

    # ci_check_dependencies.py
    import sys
    from pathlib import Path
    from benchbox.utils.dependency_validation import (
        _load_toml,
        validate_dependency_versions
    )

    def check_dependencies():
        """Validate dependencies in CI/CD pipeline."""
        try:
            pyproject = _load_toml(Path("pyproject.toml"))
            lock = _load_toml(Path("uv.lock"))

            problems = validate_dependency_versions(pyproject, lock)

            if problems:
                print("❌ Dependency validation failed:")
                for problem in problems:
                    print(f"  {problem}")
                return 1
            else:
                print("✅ All dependencies valid")
                return 0

        except Exception as e:
            print(f"❌ Error: {e}")
            return 1

    if __name__ == "__main__":
        sys.exit(check_dependencies())

Pre-commit Hook
"""""""""""""""

.. code-block:: bash

    #!/bin/bash
    # .git/hooks/pre-commit

    echo "Validating dependencies..."
    python -m benchbox.utils.dependency_validation

    if [ $? -ne 0 ]; then
        echo "❌ Dependency validation failed. Commit aborted."
        exit 1
    fi

    echo "✅ Dependencies validated"

Documentation Generation
""""""""""""""""""""""""

.. code-block:: python

    from benchbox.utils.dependency_validation import (
        _load_toml,
        build_matrix_summary
    )
    from pathlib import Path

    def generate_dependency_docs():
        """Generate dependency documentation."""
        pyproject = _load_toml(Path("pyproject.toml"))
        lock = _load_toml(Path("uv.lock"))

        matrix = build_matrix_summary(pyproject, lock)

        print("# Dependency Information\n")
        print(f"Python: {matrix['python_requires']}\n")

        if matrix['optional_dependencies']:
            print("## Optional Dependencies\n")
            for extra, deps in matrix['optional_dependencies'].items():
                print(f"### {extra}")
                for dep in deps:
                    print(f"- {dep}")
                print()

    generate_dependency_docs()

System Information Utilities
-----------------------------

Utilities for collecting system and hardware information.

Overview
~~~~~~~~

The system information utilities provide standardized access to system, CPU, and memory information. This is useful for documenting benchmark environments and tracking system resources.

**Key Features**:

- System information (OS, architecture, hostname)
- CPU information (model, cores, usage)
- Memory information (total, available, used)
- Python version tracking
- Dataclass-based API

Quick Start
~~~~~~~~~~~

.. code-block:: python

    from benchbox.utils.system_info import get_system_info

    # Get system information
    info = get_system_info()

    print(f"OS: {info.os_name} {info.os_version}")
    print(f"CPU: {info.cpu_model} ({info.cpu_cores} cores)")
    print(f"Memory: {info.total_memory_gb:.1f} GB total, "
          f"{info.available_memory_gb:.1f} GB available")
    print(f"Python: {info.python_version}")

API Reference
~~~~~~~~~~~~~

SystemInfo Class
""""""""""""""""

.. autoclass:: benchbox.utils.system_info.SystemInfo

**Fields**:

- **os_name** (str): Operating system name
- **os_version** (str): Operating system version
- **architecture** (str): System architecture
- **cpu_model** (str): CPU model name
- **cpu_cores** (int): Number of CPU cores
- **total_memory_gb** (float): Total memory in GB
- **available_memory_gb** (float): Available memory in GB
- **python_version** (str): Python version
- **hostname** (str): System hostname

.. method:: to_dict() -> dict

   Convert to dictionary for compatibility.

.. autofunction:: benchbox.utils.system_info.get_system_info

**Signature**:

.. code-block:: python

    get_system_info() -> SystemInfo

**Returns**: ``SystemInfo`` dataclass with current system information

**Example**:

.. code-block:: python

    from benchbox.utils.system_info import get_system_info

    info = get_system_info()
    print(f"Running on {info.os_name} {info.os_version}")
    print(f"CPU: {info.cpu_model}")
    print(f"Cores: {info.cpu_cores}")
    print(f"Memory: {info.total_memory_gb:.1f} GB")

.. autofunction:: benchbox.utils.system_info.get_memory_info

**Signature**:

.. code-block:: python

    get_memory_info() -> dict[str, float]

**Returns**: Dictionary with memory information

**Keys**:

- ``total_gb``: Total memory in GB
- ``available_gb``: Available memory in GB
- ``used_gb``: Used memory in GB
- ``percent_used``: Memory usage percentage

**Example**:

.. code-block:: python

    from benchbox.utils.system_info import get_memory_info

    memory = get_memory_info()
    print(f"Memory: {memory['used_gb']:.1f} GB / {memory['total_gb']:.1f} GB "
          f"({memory['percent_used']:.1f}%)")

.. autofunction:: benchbox.utils.system_info.get_cpu_info

**Signature**:

.. code-block:: python

    get_cpu_info() -> dict[str, Any]

**Returns**: Dictionary with CPU information

**Keys**:

- ``logical_cores``: Number of logical cores
- ``physical_cores``: Number of physical cores
- ``current_usage_percent``: Current CPU usage percentage
- ``per_core_usage``: Per-core usage percentages (list)
- ``model``: CPU model name

**Example**:

.. code-block:: python

    from benchbox.utils.system_info import get_cpu_info

    cpu = get_cpu_info()
    print(f"CPU: {cpu['model']}")
    print(f"Cores: {cpu['physical_cores']} physical, {cpu['logical_cores']} logical")
    print(f"Usage: {cpu['current_usage_percent']:.1f}%")

Usage Examples
~~~~~~~~~~~~~~

Benchmark Environment Documentation
""""""""""""""""""""""""""""""""""""

.. code-block:: python

    import json
    from benchbox.utils.system_info import get_system_info

    def document_environment(benchmark_results):
        """Add system information to benchmark results."""
        info = get_system_info()

        benchmark_results["environment"] = {
            "os": f"{info.os_name} {info.os_version}",
            "architecture": info.architecture,
            "cpu": info.cpu_model,
            "cpu_cores": info.cpu_cores,
            "memory_gb": info.total_memory_gb,
            "python_version": info.python_version,
            "hostname": info.hostname
        }

        return benchmark_results

    results = run_benchmark()
    results = document_environment(results)

    with open("results.json", "w") as f:
        json.dump(results, f, indent=2)

Resource Monitoring
"""""""""""""""""""

.. code-block:: python

    import time
    from benchbox.utils.system_info import get_memory_info, get_cpu_info

    def monitor_resources(duration_seconds=60):
        """Monitor system resources during benchmark."""
        samples = []
        end_time = time.time() + duration_seconds

        while time.time() < end_time:
            memory = get_memory_info()
            cpu = get_cpu_info()

            samples.append({
                "timestamp": time.time(),
                "memory_used_gb": memory["used_gb"],
                "memory_percent": memory["percent_used"],
                "cpu_percent": cpu["current_usage_percent"]
            })

            time.sleep(1)

        return samples

    # Monitor during benchmark
    samples = monitor_resources(duration_seconds=30)

    # Calculate statistics
    avg_memory = sum(s["memory_used_gb"] for s in samples) / len(samples)
    avg_cpu = sum(s["cpu_percent"] for s in samples) / len(samples)

    print(f"Average memory: {avg_memory:.1f} GB")
    print(f"Average CPU: {avg_cpu:.1f}%")

System Requirements Check
"""""""""""""""""""""""""

.. code-block:: python

    from benchbox.utils.system_info import get_system_info, get_memory_info

    def check_system_requirements(min_memory_gb=8, min_cores=4):
        """Check if system meets benchmark requirements."""
        info = get_system_info()
        memory = get_memory_info()

        issues = []

        if info.total_memory_gb < min_memory_gb:
            issues.append(
                f"Insufficient memory: {info.total_memory_gb:.1f} GB "
                f"(minimum: {min_memory_gb} GB)"
            )

        if info.cpu_cores < min_cores:
            issues.append(
                f"Insufficient CPU cores: {info.cpu_cores} "
                f"(minimum: {min_cores})"
            )

        if memory["available_gb"] < min_memory_gb * 0.8:
            issues.append(
                f"Low available memory: {memory['available_gb']:.1f} GB"
            )

        if issues:
            print("⚠️  System requirements not met:")
            for issue in issues:
                print(f"  - {issue}")
            return False
        else:
            print("✅ System requirements met")
            return True

    check_system_requirements(min_memory_gb=16, min_cores=8)

Best Practices
--------------

Scale Factor Utilities
~~~~~~~~~~~~~~~~~~~~~~~

1. **Use Consistent Formatting**: Always use utility functions for naming

   .. code-block:: python

       # Good: Consistent naming
       from benchbox.utils.scale_factor import format_data_directory
       data_dir = format_data_directory("tpch", 1.0)  # "tpch_sf1_data"

       # Avoid: Manual formatting
       data_dir = f"tpch_{1.0}_data"  # Inconsistent

2. **Apply to All Artifacts**: Use for files, directories, schemas, results

Dependency Validation
~~~~~~~~~~~~~~~~~~~~~

1. **Validate in CI/CD**: Run validation in continuous integration

   .. code-block:: bash

       # .github/workflows/test.yml
       - name: Validate dependencies
         run: python -m benchbox.utils.dependency_validation

2. **Run Before Releases**: Ensure dependencies are valid before releasing

System Information
~~~~~~~~~~~~~~~~~~

1. **Document Benchmarks**: Always include system info in benchmark results

   .. code-block:: python

       info = get_system_info()
       results["environment"] = info.to_dict()

2. **Check Requirements**: Verify system meets requirements before benchmarking

See Also
--------

- :doc:`data-validation` - Data validation utilities
- :doc:`performance-monitoring` - Performance monitoring utilities
- :doc:`utilities` - Core utilities (dialect translation)
- :doc:`/development/getting-started` - Development guide
