---
myst:
  enable_extensions:
    - attrs_block
---
<!-- markdownlint-disable MD024 -->

# Additional Utilities API

```{tags} reference, python-api
```

Complete Python API reference for additional BenchBox utilities.

## Overview

BenchBox provides several focused utility modules for common tasks: scale factor formatting, dependency validation, and system information collection. These utilities enable consistent naming, dependency management, and environment documentation.

**Utilities Covered**:

- **Scale Factor Formatting**: Consistent naming for files, directories, and schemas
- **Dependency Validation**: Verify dependencies match lock file requirements
- **System Information**: Collect system and hardware information

## Scale Factor Utilities

Utilities for consistent scale factor formatting across BenchBox.

### Overview

The scale factor utilities provide standardized formatting for scale factors in filenames, directory names, and schema names. This ensures consistency across the framework.

**Formatting Rules**:

- Values >= 1: No leading zero (`sf1`, `sf10`, `sf100`)
- Values < 1: Leading zero + decimal digits (`sf01`, `sf001`, `sf0001`)
- Non-integer values >= 1: Remove decimal point (`sf15` for 1.5)

### Quick Start

```python
from benchbox.utils.scale_factor import (
    format_scale_factor,
    format_benchmark_name,
    format_data_directory,
    format_schema_name
)

print(format_scale_factor(1.0))
print(format_scale_factor(0.1))
print(format_scale_factor(0.01))
print(format_scale_factor(10.0))

print(format_benchmark_name("tpch", 1.0))
print(format_data_directory("tpcds", 0.1))
print(format_schema_name("ssb", 10.0))
```

The scale factors print as `sf1`, `sf01`, `sf001` and `sf10`. The names print as `tpch_sf1` (benchmark name), `tpcds_sf01_data` (data directory) and `ssb_sf10` (schema name).

### API Reference

#### `benchbox.utils.scale_factor.format_scale_factor`

<span id="benchbox.utils.scale_factor.format_scale_factor"></span>

Returns the scale-factor token that BenchBox uses in file, directory and schema
names.

**Import:** `from benchbox.utils.scale_factor import format_scale_factor` · **Extras:** none

##### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `scale_factor` | `float` | required | The benchmark scale factor. |

##### Returns

`str`: `sf` followed by digits.

- **Values of 1 or more:** the value without its decimal point (`10` → `sf10`,
  `1.5` → `sf15`).
- **Values below 1:** `0` followed by the decimal digits (`0.1` → `sf01`,
  `0.01` → `sf001`).
- **Zero, negative integers, NaN and values below 1e-10:** return `sf0`.
- **Negative fractions:** return the same token as their absolute value
  (`-0.5` → `sf05`).

The token is not unique: `1.5` and `15` both return `sf15`.

##### Raises

`OverflowError` for infinity.

##### Example

```python
from benchbox.utils.scale_factor import format_scale_factor

format_scale_factor(1)
format_scale_factor(0.01)
format_scale_factor(2.25)
```

These return `sf1`, `sf001` and `sf225`.

#### `benchbox.utils.scale_factor.format_benchmark_name`

<span id="benchbox.utils.scale_factor.format_benchmark_name"></span>

Returns a benchmark name with the scale-factor token appended, as used for result file names and schema names.

**Import:** `from benchbox.utils.scale_factor import format_benchmark_name` · **Extras:** none

{#format-benchmark-name-parameters}

##### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `benchmark_name` | `str` | required | The benchmark name. It is used as given: case, spaces and an empty string are not changed or rejected. |
| `scale_factor` | `float` | required | The benchmark scale factor. |

{#format-benchmark-name-returns}

##### Returns

`str`: `<benchmark_name>_<token>`, where the token is the `format_scale_factor` result for `scale_factor`.

{#format-benchmark-name-raises}

##### Raises

The same errors as `format_scale_factor`: `OverflowError` for infinity and `TypeError` for a value that is not a number, such as `"1"`.

{#format-benchmark-name-example}

##### Example

```python
from benchbox.utils.scale_factor import format_benchmark_name

print(format_benchmark_name("tpch", 1.0))
print(format_benchmark_name("tpcds", 0.1))
print(format_benchmark_name("ssb", 10.0))
```

```text
tpch_sf1
tpcds_sf01
ssb_sf10
```

#### `benchbox.utils.scale_factor.format_data_directory`

<span id="benchbox.utils.scale_factor.format_data_directory"></span>

Returns the name of the directory that holds generated data for a benchmark at a scale factor.

**Import:** `from benchbox.utils.scale_factor import format_data_directory` · **Extras:** none

{#format-data-directory-parameters}

##### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `benchmark_name` | `str` | required | The benchmark name, used as given. |
| `scale_factor` | `float` | required | The benchmark scale factor. |

{#format-data-directory-returns}

##### Returns

`str`: `<benchmark_name>_<token>_data`. It is a name only: no directory is created and no path separator is added.

{#format-data-directory-raises}

##### Raises

The same errors as `format_scale_factor`: `OverflowError` for infinity and `TypeError` for a value that is not a number.

{#format-data-directory-example}

##### Example

```python
from benchbox.utils.scale_factor import format_data_directory

print(format_data_directory("tpch", 1.0))
print(format_data_directory("tpcds", 0.1))
print(format_data_directory("ssb", 10.0))
```

```text
tpch_sf1_data
tpcds_sf01_data
ssb_sf10_data
```

#### `benchbox.utils.scale_factor.format_schema_name`

<span id="benchbox.utils.scale_factor.format_schema_name"></span>

Returns the database schema name for a benchmark at a scale factor.

**Import:** `from benchbox.utils.scale_factor import format_schema_name` · **Extras:** none

{#format-schema-name-parameters}

##### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `benchmark_name` | `str` | required | The benchmark name, used as given. |
| `scale_factor` | `float` | required | The benchmark scale factor. |

{#format-schema-name-returns}

##### Returns

`str`: `<benchmark_name>_<token>`. The result is always equal to the `format_benchmark_name` result for the same arguments. It is a name only: no schema is created.

{#format-schema-name-raises}

##### Raises

The same errors as `format_scale_factor`: `OverflowError` for infinity and `TypeError` for a value that is not a number.

{#format-schema-name-example}

##### Example

```python
from benchbox.utils.scale_factor import format_benchmark_name, format_schema_name

print(format_schema_name("tpch", 1.0))
print(format_schema_name("tpcds", 0.1))
print(format_schema_name("ssb", 10.0))
print(format_schema_name("tpch", 0.5) == format_benchmark_name("tpch", 0.5))
```

```text
tpch_sf1
tpcds_sf01
ssb_sf10
True
```

### Usage Examples

#### Consistent File Naming

This creates the data directory with consistent naming and prints `Data directory: data/tpch_sf1_data`.

```python
from pathlib import Path
from benchbox.utils.scale_factor import format_data_directory

benchmark = "tpch"
scale_factor = 1.0

data_dir = Path("data") / format_data_directory(benchmark, scale_factor)
data_dir.mkdir(parents=True, exist_ok=True)

print(f"Data directory: {data_dir}")
```

#### Database Schema Naming

`USE SCHEMA` is Snowflake and Databricks syntax; use your platform's statement for selecting a schema.

The function creates the schema with consistent naming. This call prints `Created schema: tpch_sf1`.

```python
from benchbox.utils.scale_factor import format_schema_name

def create_benchmark_schema(conn, benchmark, scale_factor):
    schema_name = format_schema_name(benchmark, scale_factor)

    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema_name}")
    conn.execute(f"USE SCHEMA {schema_name}")

    print(f"Created schema: {schema_name}")

create_benchmark_schema(conn, "tpch", 1.0)
```

#### Result File Naming

The function saves results with consistent naming. This call prints `Saved results to: results_tpcds_sf01.json`.

```python
import json
from benchbox.utils.scale_factor import format_benchmark_name

def save_results(results, benchmark, scale_factor):
    name = format_benchmark_name(benchmark, scale_factor)
    filename = f"results_{name}.json"

    with open(filename, "w") as f:
        json.dump(results, f, indent=2)

    print(f"Saved results to: {filename}")

save_results(benchmark_results, "tpcds", 0.1)
```

## Dependency Validation Utilities

Utilities for validating BenchBox dependency definitions.

### Overview

The dependency validation utilities verify that all declared dependencies in `pyproject.toml` have corresponding locked versions in `uv.lock` that satisfy the declared specifiers. This ensures dependency consistency and helps catch dependency issues early.

**Key Features**:

- Validate core dependencies
- Validate optional dependencies (extras)
- Build a summary of the Python range and optional dependency groups
- CLI tool for CI/CD integration

### Quick Start

The functions take parsed TOML, so read the files with the standard library `tomllib`.

```python
import tomllib
from pathlib import Path
from benchbox.utils.dependency_validation import validate_dependency_versions

pyproject_data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
lock_data = tomllib.loads(Path("uv.lock").read_text(encoding="utf-8"))
problems = validate_dependency_versions(pyproject_data, lock_data)

if problems:
    print("❌ Dependency validation failed:")
    for problem in problems:
        print(f"  - {problem}")
else:
    print("✅ All dependencies validated successfully")
```

### API Reference

#### `benchbox.utils.dependency_validation.validate_dependency_versions`

<span id="benchbox.utils.dependency_validation.validate_dependency_versions"></span>

Checks that every dependency declared in `pyproject.toml` has a locked version in `uv.lock` that satisfies its specifier, and returns the problems found.

**Import:** `from benchbox.utils.dependency_validation import validate_dependency_versions` · **Extras:** none

{#validate-dependency-versions-parameters}

##### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `pyproject_data` | `Mapping[str, object]` | required | Parsed `pyproject.toml`. Its `[project]` table supplies `dependencies` and `optional-dependencies`. |
| `lock_data` | `Mapping[str, object]` | required | Parsed `uv.lock`. Its `[[package]]` entries supply the locked names and versions. |

{#validate-dependency-versions-returns}

##### Returns

`list[str]`: one message per unsatisfied requirement, or an empty list when all are satisfied.

- **Core dependency:** `Missing satisfying lock entry for <name><specifier>`.
- **Optional dependency:** the same message followed by `(extra: <extra>)`.
- **Matching:** names are compared in canonical form. A requirement with no specifier is satisfied by any locked version of that package. Pre-release versions can satisfy a specifier.
- **Not checked:** environment markers on a requirement are ignored, and the Python version is not checked.

{#validate-dependency-versions-raises}

##### Raises

`DependencyValidationError` (a `RuntimeError` subclass defined in the same module) when `pyproject_data` has no `[project]` table. An invalid requirement string raises the `packaging` library's `InvalidRequirement`.

{#validate-dependency-versions-example}

##### Example

```python
import tomllib
from benchbox.utils.dependency_validation import validate_dependency_versions

pyproject = tomllib.loads("""
[project]
name = "demo"
dependencies = ["requests>=2.0", "rich"]

[project.optional-dependencies]
viz = ["matplotlib>=3.5"]
""")
lock = tomllib.loads("""
[[package]]
name = "requests"
version = "1.0.0"

[[package]]
name = "rich"
version = "13.7.0"
""")

for problem in validate_dependency_versions(pyproject, lock):
    print(problem)
```

```text
Missing satisfying lock entry for requests>=2.0
Missing satisfying lock entry for matplotlib>=3.5 (extra: viz)
```

#### `benchbox.utils.dependency_validation.build_matrix_summary`

<span id="benchbox.utils.dependency_validation.build_matrix_summary"></span>

Summarises the Python range and the optional dependency groups of a project.

**Import:** `from benchbox.utils.dependency_validation import build_matrix_summary` · **Extras:** none

{#build-matrix-summary-parameters}

##### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `pyproject_data` | `Mapping[str, object]` | required | Parsed `pyproject.toml`. |
| `lock_data` | `Mapping[str, object]` | required | Parsed `uv.lock`. |

{#build-matrix-summary-returns}

##### Returns

`dict[str, object]` with three keys:

- **`python_requires`:** the `requires-python` value from the lock data, or `"unspecified"` when it has none.
- **`resolution_markers`:** the lock data's `resolution-markers` list, empty when it has none.
- **`optional_dependencies`:** a dict of extra name to the list of requirement strings, sorted by extra name. It is empty when `[project]` is missing or declares no extras.

The function never validates: it does not raise for a missing `[project]` table or an unsatisfied requirement.

{#build-matrix-summary-example}

##### Example

```python
import tomllib
from benchbox.utils.dependency_validation import build_matrix_summary

pyproject = tomllib.loads("""
[project]
name = "demo"
dependencies = ["requests>=2.0", "rich"]

[project.optional-dependencies]
viz = ["matplotlib>=3.5"]
""")
lock = tomllib.loads("""
requires-python = ">=3.10"
""")

print(build_matrix_summary(pyproject, lock))
```

```text
{'python_requires': '>=3.10', 'resolution_markers': [], 'optional_dependencies': {'viz': ['matplotlib>=3.5']}}
```

### CLI Tool

The dependency validation utilities include a CLI tool for CI/CD integration:

```bash
python -m benchbox.utils.dependency_validation

python -m benchbox.utils.dependency_validation --matrix

python -m benchbox.utils.dependency_validation \
    --pyproject path/to/pyproject.toml \
    --lock path/to/uv.lock
```

The first command validates dependencies, the second displays the compatibility matrix, and the third uses custom file paths. By default it reads `pyproject.toml` and `uv.lock` in the current directory. With `--matrix` the summary is printed only after validation passes. Problems are written to standard error, one per line.

**Exit Codes**:

- `0`: All dependencies validated successfully
- `1`: Validation failed (missing or incompatible dependencies). A missing input file also exits with `1`, after a `FileNotFoundError` traceback.

### Usage Examples

#### CI/CD Integration

Save this script as `ci_check_dependencies.py`. It validates dependencies in a CI/CD pipeline and returns exit code 1 on failure.

```python
import sys
import tomllib
from pathlib import Path
from benchbox.utils.dependency_validation import validate_dependency_versions

def check_dependencies():
    try:
        pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        lock = tomllib.loads(Path("uv.lock").read_text(encoding="utf-8"))

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
```

#### Pre-commit Hook

Save this script as `.git/hooks/pre-commit` and start it with the `#!/bin/bash` line.

```bash
echo "Validating dependencies..."
python -m benchbox.utils.dependency_validation

if [ $? -ne 0 ]; then
    echo "❌ Dependency validation failed. Commit aborted."
    exit 1
fi

echo "✅ Dependencies validated"
```

#### Documentation Generation

This function generates dependency documentation from the validated data.

```python
import tomllib
from pathlib import Path
from benchbox.utils.dependency_validation import build_matrix_summary

def generate_dependency_docs():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads(Path("uv.lock").read_text(encoding="utf-8"))

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
```

## System Information Utilities

Utilities for collecting system and hardware information.

### Overview

The system information utilities provide standardized access to system, CPU, and memory information. This is useful for documenting benchmark environments and tracking system resources.

**Key Features**:

- System information (OS, architecture, hostname)
- CPU information (model, cores, usage)
- Memory information (total, available, used)
- Python version tracking
- Dataclass-based API

### Quick Start

```python
from benchbox.utils.system_info import get_system_info

info = get_system_info()

print(f"OS: {info.os_name} {info.os_version}")
print(f"CPU: {info.cpu_model} ({info.cpu_cores} cores)")
print(f"Memory: {info.total_memory_gb:.1f} GB total, "
      f"{info.available_memory_gb:.1f} GB available")
print(f"Python: {info.python_version}")
```

This collects the system information first and then prints the OS, CPU, memory and Python version.

Output on a 4-core Linux host (values vary by machine):

```text
OS: Linux 6.18.44-fc-v64
CPU: Intel(R) Xeon(R) Processor @ 2.10GHz (4 cores)
Memory: 15.7 GB total, 14.2 GB available
Python: 3.11.15
```

### API Reference

#### SystemInfo Class

`get_system_info` returns a `SystemInfo` object. The class is not part of the public contract; see [Not part of the public contract](#not-part-of-public-contract). Use the attributes shown in the `get_system_info` example, or call `get_memory_info` and `get_cpu_info` for plain dictionaries.

#### `benchbox.utils.system_info.get_system_info`

<span id="benchbox.utils.system_info.get_system_info"></span>

Returns a snapshot of the operating system, CPU, memory and Python version of the current host.

**Import:** `from benchbox.utils.system_info import get_system_info` · **Extras:** none

{#get-system-info-parameters}

##### Parameters

None.

{#get-system-info-returns}

##### Returns

A `SystemInfo` object. The examples on this page read these attributes:

- **`os_name`, `os_version`, `architecture`:** the system name, release and machine type reported by Python's `platform` module (`Linux`, `6.18.44-fc-v64`, `x86_64`).
- **`cpu_model`:** the CPU model string, or `None` when no model can be determined. An architecture name such as `x86_64` is reported as `None`, not as a model.
- **`cpu_cores`:** the number of logical cores.
- **`total_memory_gb`, `available_memory_gb`:** memory in gibibytes (bytes divided by 1024³), as floats.
- **`python_version`, `hostname`:** the running Python version and the host name.

The `SystemInfo` class is not part of the public contract. The readings come from `psutil`, which is a core dependency of BenchBox.

{#get-system-info-example}

##### Example

```python
from benchbox.utils.system_info import get_system_info

info = get_system_info()
print(info.os_name, info.architecture)
print(info.cpu_cores, round(info.total_memory_gb, 1))
print(info.cpu_model)
```

```text
Linux x86_64
4 15.7
Intel(R) Xeon(R) Processor @ 2.10GHz
```

#### `benchbox.utils.system_info.get_memory_info`

<span id="benchbox.utils.system_info.get_memory_info"></span>

Returns the current memory usage of the host as a dictionary.

**Import:** `from benchbox.utils.system_info import get_memory_info` · **Extras:** none

{#get-memory-info-parameters}

##### Parameters

None.

{#get-memory-info-returns}

##### Returns

`dict[str, float]` with four keys:

- **`total_gb`:** total memory in gibibytes.
- **`available_gb`:** memory available to new processes, in gibibytes.
- **`used_gb`:** memory in use, in gibibytes.
- **`percent_used`:** memory usage as a percentage from 0 to 100.

The call returns immediately.

{#get-memory-info-example}

##### Example

```python
from benchbox.utils.system_info import get_memory_info

memory = get_memory_info()
print(sorted(memory))
print(f"Memory: {memory['used_gb']:.1f} GB / {memory['total_gb']:.1f} GB "
      f"({memory['percent_used']:.1f}%)")
```

```text
['available_gb', 'percent_used', 'total_gb', 'used_gb']
Memory: 1.5 GB / 15.7 GB (9.8%)
```

The second line varies with the host and its load.

#### `benchbox.utils.system_info.get_cpu_info`

<span id="benchbox.utils.system_info.get_cpu_info"></span>

Returns the core counts and the current CPU usage of the host as a dictionary.

**Import:** `from benchbox.utils.system_info import get_cpu_info` · **Extras:** none

{#get-cpu-info-parameters}

##### Parameters

None.

{#get-cpu-info-returns}

##### Returns

`dict[str, Any]` with five keys:

- **`logical_cores`:** the number of logical cores.
- **`physical_cores`:** the number of physical cores.
- **`current_usage_percent`:** total CPU usage as a percentage, measured over one second.
- **`per_core_usage`:** a list of usage percentages, one per logical core, measured over a separate one-second window.
- **`model`:** the value of Python's `platform.processor()`, or `"<machine> CPU"` when that is empty. On Linux it is often only the architecture (`x86_64`), so do not rely on it as a CPU model name.

The call blocks for about two seconds, because the two usage readings are sampled one after the other.

{#get-cpu-info-example}

##### Example

```python
import time
from benchbox.utils.system_info import get_cpu_info

start = time.time()
cpu = get_cpu_info()
print(sorted(cpu))
print(cpu["logical_cores"], len(cpu["per_core_usage"]))
print(round(time.time() - start))
```

```text
['current_usage_percent', 'logical_cores', 'model', 'per_core_usage', 'physical_cores']
4 4
2
```

### Usage Examples

#### Benchmark Environment Documentation

The `document_environment` function adds system information to the benchmark results.

```python
import json
from benchbox.utils.system_info import get_system_info

def document_environment(benchmark_results):
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
```

#### Resource Monitoring

The `monitor_resources` function monitors system resources during a benchmark. The script then calculates the average memory and CPU use from the samples.

Each pass through the loop takes about three seconds: `get_cpu_info` blocks for two seconds, then the loop sleeps for one.

```python
import time
from benchbox.utils.system_info import get_memory_info, get_cpu_info

def monitor_resources(duration_seconds=60):
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

samples = monitor_resources(duration_seconds=30)

avg_memory = sum(s["memory_used_gb"] for s in samples) / len(samples)
avg_cpu = sum(s["cpu_percent"] for s in samples) / len(samples)

print(f"Average memory: {avg_memory:.1f} GB")
print(f"Average CPU: {avg_cpu:.1f}%")
```

#### System Requirements Check

The function checks whether the system meets the benchmark requirements.

```python
from benchbox.utils.system_info import get_system_info, get_memory_info

def check_system_requirements(min_memory_gb=8, min_cores=4):
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
```

Output on a 4-core host with 15.7 GB of memory:

```text
⚠️  System requirements not met:
  - Insufficient memory: 15.7 GB (minimum: 16 GB)
  - Insufficient CPU cores: 4 (minimum: 8)
```

## Best Practices

### Scale Factor Utilities

1. **Use Consistent Formatting**: Always use utility functions for naming

   ```python
   from benchbox.utils.scale_factor import format_data_directory
   data_dir = format_data_directory("tpch", 1.0)

   data_dir = f"tpch_{1.0}_data"
   ```

   The first form is consistent. Avoid the second form, which formats the name by hand and gives an inconsistent name.

2. **Apply to All Artifacts**: Use for files, directories, schemas, results

### Dependency Validation

1. **Validate in CI/CD**: Run validation in continuous integration

   Add this step to `.github/workflows/test.yml`.

   ```bash
   - name: Validate dependencies
     run: python -m benchbox.utils.dependency_validation
   ```

2. **Run Before Releases**: Ensure dependencies are valid before releasing

### System Information

1. **Document Benchmarks**: Always include system info in benchmark results

   ```python
   results = document_environment(results)
   ```

   `document_environment` is defined in the Benchmark Environment Documentation example above.

2. **Check Requirements**: Verify system meets requirements before benchmarking

## See Also

- {doc}`data-validation` - Data validation utilities
- {doc}`performance-monitoring` - Performance monitoring utilities
- {doc}`utilities` - Core utilities (dialect translation)
- {doc}`/development/getting-started` - Development guide

<span id="not-part-of-public-contract"></span>

## Not part of the public contract

<span id="benchbox.utils.system_info.SystemInfo"></span>
<span id="benchbox.utils.system_info.SystemInfo.__init__"></span>
<span id="benchbox.utils.system_info.SystemInfo.architecture"></span>
<span id="benchbox.utils.system_info.SystemInfo.available_memory_gb"></span>
<span id="benchbox.utils.system_info.SystemInfo.cpu_cores"></span>
<span id="benchbox.utils.system_info.SystemInfo.cpu_identity_provenance"></span>
<span id="benchbox.utils.system_info.SystemInfo.cpu_model"></span>
<span id="benchbox.utils.system_info.SystemInfo.cpu_vendor"></span>
<span id="benchbox.utils.system_info.SystemInfo.hostname"></span>
<span id="benchbox.utils.system_info.SystemInfo.os_name"></span>
<span id="benchbox.utils.system_info.SystemInfo.os_version"></span>
<span id="benchbox.utils.system_info.SystemInfo.python_version"></span>
<span id="benchbox.utils.system_info.SystemInfo.to_dict"></span>
<span id="benchbox.utils.system_info.SystemInfo.total_memory_gb"></span>
<span id="to_dict"></span>

The `SystemInfo` class and its members, including `to_dict`, are internal and may change without notice.
