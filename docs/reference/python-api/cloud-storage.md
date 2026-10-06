<!-- markdownlint-disable MD024 -->

# Cloud Storage Integration API

```{tags} reference, python-api, cloud-storage
```

Complete Python API reference for BenchBox cloud storage integration.

## Overview

BenchBox provides cloud storage integration through a minimal abstraction layer built on `cloudpathlib`. The cloud storage API enables benchmarks to work with cloud storage locations (S3, GCS, Azure Blob Storage) while maintaining the same interface as local paths.

**Key Features**:

- **Unified Path Handling**: Transparent support for local and cloud paths
- **Credential Validation**: Built-in validation for cloud credentials
- **Multi-Cloud Support**: AWS S3, Google Cloud Storage, Azure Blob Storage
- **Platform Integration**: Staging wrappers for Databricks volumes, ADLS Gen2 and Snowflake stages
- **Error Handling**: Error messages that name the missing environment variables or package

The example outputs on this page show what each function does without network access or credentials.

## Quick Start

Cloud storage paths work transparently with BenchBox:

```python
from benchbox.tpch import TPCH
from benchbox.platforms.duckdb import DuckDBAdapter

# Create benchmark with cloud storage output
benchmark = TPCH(
    scale_factor=0.01,
    output_dir="s3://my-bucket/benchbox/tpch-data"
)

# Generate data into the configured output directory
benchmark.generate_data()

# Run benchmark
adapter = DuckDBAdapter()
results = adapter.run_benchmark(benchmark)
```

This example needs the `cloudstorage` extra and credentials for the bucket.

## Installation

Cloud storage support requires the optional `cloudstorage` dependency:

```bash
# Install cloud storage support
uv add benchbox --extra cloudstorage

# Or install all cloud dependencies
uv pip install "benchbox[cloud]"
```

## Supported Providers

| Provider | URI forms | Credentials checked by `validate_cloud_credentials` | `create_path_handler` returns |
| --- | --- | --- | --- |
| **AWS S3** | `s3://bucket/path` | `AWS_ACCESS_KEY_ID` with `AWS_SECRET_ACCESS_KEY`, or `AWS_PROFILE`, or `~/.aws/credentials`, or `~/.aws/config` | a `cloudpathlib` S3 path |
| **Google Cloud Storage** | `gs://bucket/path`, `gcs://bucket/path` | `GOOGLE_APPLICATION_CREDENTIALS` | a `cloudpathlib` GCS path; `gcs://` is rewritten to `gs://` |
| **Azure Blob Storage** | `az://container/path`, `azure://container/path` | `AZURE_STORAGE_ACCOUNT_NAME` and `AZURE_STORAGE_ACCOUNT_KEY` | a `cloudpathlib` Azure Blob path; `azure://` is rewritten to `az://` |
| **Azure Data Lake Storage Gen2** | `abfss://container@account.dfs.core.windows.net/path`, `abfs://...` | `AZURE_STORAGE_ACCOUNT_NAME` and `AZURE_STORAGE_ACCOUNT_KEY` | a local staging wrapper that records the URI |
| **Databricks Unity Catalog** | `dbfs:/Volumes/catalog/schema/volume/path` | none: assumed valid, checked by the Databricks adapter | a local staging wrapper that records the URI |
| **Snowflake stage** | `@~/path`, `@stage/path`, `@%table/path`, `@db.schema.stage/path` | none: assumed valid, checked by the Snowflake adapter | a local staging wrapper that records the stage |

## API Reference

### Path Detection

#### `benchbox.utils.cloud_storage.is_cloud_path`

<span id="benchbox.utils.cloud_storage.is_cloud_path"></span>

Tells whether a path names cloud storage rather than the local file system.

**Import:** `from benchbox.utils.cloud_storage import is_cloud_path` · **Extras:** none

##### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `path` | `str` or `Path` | required | The path to classify. Any other object is converted with `str()` first. |

##### Returns

`bool`: `True` when the URI scheme is `s3`, `gs`, `gcs`, `az`, `azure`, `abfss`, `abfs` or `dbfs` (in any letter case), or when the path is a Snowflake stage reference that starts with `@`. Otherwise `False`.

The check only looks at the scheme: it does not contact a provider, read credentials or validate the rest of the path. `s3:/bucket/path` (one slash) is reported as a cloud path. Schemes such as `s3a`, `r2`, `http` and `file` return `False`.

##### Raises

Nothing it raises itself.

##### Example

```python
from benchbox.utils.cloud_storage import is_cloud_path

# Cloud storage paths
assert is_cloud_path("s3://bucket/path")
assert is_cloud_path("gs://bucket/path")
assert is_cloud_path("abfss://container@account.dfs.core.windows.net/path")
assert is_cloud_path("dbfs:/Volumes/catalog/schema/volume/path")
assert is_cloud_path("@~/staged/data")

# Local paths
assert not is_cloud_path("/local/path")
assert not is_cloud_path("./relative/path")

print(is_cloud_path("s3:/bucket/path"), is_cloud_path("s3a://bucket/path"))
```

```text
True False
```

### Path Creation

#### `benchbox.utils.cloud_storage.create_path_handler`

<span id="benchbox.utils.cloud_storage.create_path_handler"></span>

Returns an object that can be used like a local path for a local path, a cloud path or a remote staging target.

**Import:** `from benchbox.utils.cloud_storage import create_path_handler` · **Extras:** `cloudstorage`, needed only for `s3`, `gs`, `gcs`, `az` and `azure` paths

##### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `path` | `str` or `Path` | required | A local path, a cloud URI or a Snowflake stage reference. An object that this function returned earlier is passed back unchanged. |

##### Returns

The type depends on the path:

- **Local path:** a `pathlib.Path`. Nothing is created on disk.
- **`s3://`, `gs://`, `gcs://`, `az://`, `azure://`:** a `cloudpathlib` path (`S3Path`, `GSPath` or `AzureBlobPath`). `gcs://` becomes `gs://` and `azure://` becomes `az://`.
- **`dbfs:/Volumes/...`:** a staging wrapper around a new local temporary directory named `benchbox_dbfs_*`. Its `dbfs_target` attribute holds the URI.
- **`abfss://`, `abfs://`:** a staging wrapper around a new local temporary directory named `benchbox_abfss_*`. Its `cloud_target` attribute holds the URI.
- **Snowflake stage reference:** a staging wrapper around a new local temporary directory named `benchbox_stage_*`. Its `cloud_target` attribute holds the stage reference.

A staging wrapper works as a path-like object (`os.fspath` returns the local directory) and has `exists`, `mkdir`, `name`, `parent` and `/` for the local directory. The wrapper classes are internal. BenchBox does not delete the temporary directory when the function returns.

##### Raises

- **`ImportError`:** the path needs `cloudpathlib` and it is not installed. The message ends with the install command.
- **`ValueError`:** a `dbfs:` path does not start with `dbfs:/Volumes/`, or `cloudpathlib` rejects the cloud path, as it does for `s3:/bucket/path` (`Invalid cloud path format ...`).

##### Example

```python
import shutil
from benchbox.utils.cloud_storage import create_path_handler

local = create_path_handler("/tmp/data")
print(type(local).__name__, local)

staged = create_path_handler("abfss://container@account.dfs.core.windows.net/path")
print(type(staged).__name__, staged.cloud_target)
print(staged.exists())
shutil.rmtree(str(staged))

try:
    create_path_handler("dbfs:/other/x")
except ValueError as error:
    print(error)
```

```text
PosixPath /tmp/data
CloudStagingPath abfss://container@account.dfs.core.windows.net/path
True
Invalid dbfs:// path: dbfs:/other/x. Unity Catalog Volumes must use format: dbfs:/Volumes/catalog/schema/volume
```

With the `cloudstorage` extra installed:

```python
from benchbox.utils.cloud_storage import create_path_handler

print(repr(create_path_handler("s3://bucket/data")))
print(repr(create_path_handler("gcs://bucket/data")))
```

```text
S3Path('s3://bucket/data')
GSPath('gs://bucket/data')
```

Without it, `create_path_handler("s3://bucket/data")` raises `ImportError: cloudpathlib is required for cloud storage paths. uv pip install "benchbox[cloudstorage]"`.

### Credential Validation

#### `benchbox.utils.cloud_storage.validate_cloud_credentials`

<span id="benchbox.utils.cloud_storage.validate_cloud_credentials"></span>

Checks whether the credentials for a path look usable and reports what is missing.

**Import:** `from benchbox.utils.cloud_storage import validate_cloud_credentials` · **Extras:** `cloudstorage`, needed only for `s3`, `gs`, `gcs`, `az` and `azure` paths

##### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `path` | `str` or `Path` | required | The path whose provider is checked. |

##### Returns

`dict` with four keys:

- **`valid`** (`bool`): whether the credentials passed the checks below.
- **`provider`** (`str`): the URI scheme as written in `path` (`s3`, `gs`, `gcs`, `az`, `azure`, `abfss`, `abfs` or `dbfs`), `snowflake_stage` or `local`. It is `unknown` when `cloudpathlib` is missing.
- **`error`** (`str` or `None`): the reason when `valid` is `False`.
- **`env_vars`** (`list[str]`): the environment variables that apply to the provider. Empty for local paths and Snowflake stages.

By path:

- **Local path:** `valid` is `True`, `provider` is `local`.
- **`dbfs:`:** `valid` is `True` without a check, and `env_vars` lists `DATABRICKS_HOST`, `DATABRICKS_HTTP_PATH` and `DATABRICKS_TOKEN`.
- **Snowflake stage:** `valid` is `True` without a check, and `provider` is `snowflake_stage`.
- **`abfss:`, `abfs:`:** `valid` is `True` when `AZURE_STORAGE_ACCOUNT_NAME` and `AZURE_STORAGE_ACCOUNT_KEY` are both set. Otherwise `error` is `Missing environment variables: ...`. `cloudpathlib` is not needed.
- **`s3:`, `gs:`, `gcs:`, `az:`, `azure:`:** without `cloudpathlib`, `valid` is `False`, `provider` is `unknown` and `error` is `cloudpathlib not installed`. With it, the variables in the Supported Providers table are checked first (for S3, any one of the four credential sources). When they are missing, `error` names them. When they are present, the function builds the cloud path and calls `exists()` on it, which contacts the provider; a failure there sets `error` to `Credential validation failed: ...` or `Cloud path validation failed: ...`.

##### Raises

Nothing it raises itself: failures are reported in the result.

##### Example

```python
from benchbox.utils.cloud_storage import validate_cloud_credentials

for path in ["/tmp/data", "dbfs:/Volumes/c/s/v/p", "@~/data",
             "abfss://container@account.dfs.core.windows.net/path"]:
    print(validate_cloud_credentials(path))
```

With neither `AZURE_STORAGE_ACCOUNT_NAME` nor `AZURE_STORAGE_ACCOUNT_KEY` set:

```text
{'valid': True, 'provider': 'local', 'error': None, 'env_vars': []}
{'valid': True, 'provider': 'dbfs', 'error': None, 'env_vars': ['DATABRICKS_HOST', 'DATABRICKS_HTTP_PATH', 'DATABRICKS_TOKEN']}
{'valid': True, 'provider': 'snowflake_stage', 'error': None, 'env_vars': []}
{'valid': False, 'provider': 'abfss', 'error': 'Missing environment variables: AZURE_STORAGE_ACCOUNT_NAME, AZURE_STORAGE_ACCOUNT_KEY', 'env_vars': ['AZURE_STORAGE_ACCOUNT_NAME', 'AZURE_STORAGE_ACCOUNT_KEY']}
```

For `gs://bucket/path` with the `cloudstorage` extra and no `GOOGLE_APPLICATION_CREDENTIALS`, the result is `{'valid': False, 'provider': 'gs', 'error': 'Missing environment variables: GOOGLE_APPLICATION_CREDENTIALS', 'env_vars': ['GOOGLE_APPLICATION_CREDENTIALS']}`.

##### Compatibility

A `valid` result for `s3`, `gs`, `gcs`, `az` and `azure` paths comes from a live request, so it can change with the network and the bucket. The `abfss`, `dbfs` and Snowflake stage results never contact a provider.

### Path Information

#### `benchbox.utils.cloud_storage.get_cloud_path_info`

<span id="benchbox.utils.cloud_storage.get_cloud_path_info"></span>

Splits a path into provider, bucket and path parts and reports whether its credentials are valid.

**Import:** `from benchbox.utils.cloud_storage import get_cloud_path_info` · **Extras:** none

##### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `path` | `str` or `Path` | required | The path to analyse. |

##### Returns

`dict` with these keys for every path:

- **`is_cloud`** (`bool`): whether the path is cloud storage.
- **`provider`** (`str`): the URI scheme as written, `snowflake_stage` or `local`.
- **`bucket`** (`str` or `None`): the bucket or container; `None` for local paths and `dbfs:`. For a Snowflake stage it is the stage name (`~` for the user stage).
- **`path`** (`str`): the path inside the bucket without a leading slash. For a local path it is `str(path)`. For `dbfs:` it keeps its leading slash (`/Volumes/...`).
- **`credentials_valid`** (`bool`): always `True` for local, `dbfs:` and Snowflake stage paths. For other cloud paths it is the `valid` value of `validate_cloud_credentials`, so it can involve a live request.

Extra keys by path:

- **`account`:** for a URI path, the storage account for `abfss` and `abfs` URIs and `None` otherwise. For `abfss://container@account.dfs.core.windows.net/path`, `bucket` is `container` and `account` is `account`. Local, `dbfs:` and stage results have no `account` key.
- **`volume_info`:** for `dbfs:` paths, a dict with `catalog`, `schema` and `volume`.
- **`stage_info`:** for Snowflake stages, a dict with `stage` and `sub_path`.

##### Raises

Nothing it raises itself.

##### Example

```python
from benchbox.utils.cloud_storage import get_cloud_path_info

print(get_cloud_path_info("/tmp/data"))
print(get_cloud_path_info("dbfs:/Volumes/catalog/schema/volume/path"))
print(get_cloud_path_info("abfss://container@account.dfs.core.windows.net/path"))
```

The last result assumes `AZURE_STORAGE_ACCOUNT_NAME` and `AZURE_STORAGE_ACCOUNT_KEY` are not set:

```text
{'is_cloud': False, 'provider': 'local', 'bucket': None, 'path': '/tmp/data', 'credentials_valid': True}
{'is_cloud': True, 'provider': 'dbfs', 'bucket': None, 'path': '/Volumes/catalog/schema/volume/path', 'credentials_valid': True, 'volume_info': {'catalog': 'catalog', 'schema': 'schema', 'volume': 'volume'}}
{'is_cloud': True, 'provider': 'abfss', 'bucket': 'container', 'account': 'account', 'path': 'path', 'credentials_valid': False}
```

### Directory Creation

#### `benchbox.utils.cloud_storage.ensure_cloud_directory`

<span id="benchbox.utils.cloud_storage.ensure_cloud_directory"></span>

Makes sure a directory exists and returns the path object for it.

**Import:** `from benchbox.utils.cloud_storage import ensure_cloud_directory` · **Extras:** `cloudstorage`, needed only for `s3`, `gs`, `gcs`, `az` and `azure` paths

##### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `path` | `str`, `Path` or `CloudPath` | required | The directory. A `str` or `Path` goes through `create_path_handler`; a path object is used as it is. |

##### Returns

The path object, as `create_path_handler` returns it. The function calls `mkdir(parents=True, exist_ok=True)` on it, so a local directory is created with its parents and an existing one is left alone. For `dbfs:`, `abfss:` and Snowflake stage paths, the directory that is created is the local staging directory.

##### Raises

Whatever `create_path_handler` or the directory creation raises, after logging the failure: `ImportError` or `ValueError` for a bad cloud path, and `OSError` subclasses such as `PermissionError` for a local directory that cannot be created.

##### Example

```python
import tempfile
from pathlib import Path
from benchbox.utils.cloud_storage import ensure_cloud_directory

with tempfile.TemporaryDirectory() as root:
    results = ensure_cloud_directory(Path(root) / "benchbox" / "results")
    print(type(results).__name__, results.exists())
    print(ensure_cloud_directory(results) is results)
```

```text
PosixPath True
False
```

The last line is `False` because passing a `Path` builds a new `Path` object each time.

### Cloud Path Adapter

#### `benchbox.utils.cloud_storage.CloudPathAdapter`

<span id="benchbox.utils.cloud_storage.CloudPathAdapter"></span>
<span id="benchbox.utils.cloud_storage.CloudPathAdapter.__init__"></span>

Wraps a local or cloud path in one small interface for existence checks, directory creation, joining and name access.

**Import:** `from benchbox.utils.cloud_storage import CloudPathAdapter` · **Extras:** `cloudstorage`, needed only for `s3`, `gs`, `gcs`, `az` and `azure` paths

##### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `path` | `str` or `Path` | required | A local path, a cloud URI or a Snowflake stage reference. |

##### Returns

A `CloudPathAdapter` with these attributes:

- **`original_path`** (`str`): `str(path)`.
- **`is_cloud`** (`bool`): the `is_cloud_path` result.
- **`path_handler`**: the `create_path_handler` result.
- **`path_info`** (`dict`): the `get_cloud_path_info` result for a cloud path, and `{'is_cloud': False, 'provider': 'local'}` for a local path.

**Methods and properties:**

<span id="benchbox.utils.cloud_storage.CloudPathAdapter.exists"></span>
`exists()` returns `bool`. It returns `False` instead of raising when the check fails.

<span id="benchbox.utils.cloud_storage.CloudPathAdapter.mkdir"></span>
`mkdir(parents=True, exist_ok=True)` creates the directory and returns `None`.

<span id="benchbox.utils.cloud_storage.CloudPathAdapter.__truediv__"></span>
`adapter / "name"` returns a new `CloudPathAdapter` for the joined path. Joins can be chained.

<span id="benchbox.utils.cloud_storage.CloudPathAdapter.__str__"></span>
`str(adapter)` returns `str(path_handler)`.

<span id="benchbox.utils.cloud_storage.CloudPathAdapter.name"></span>
`name` is the last component of the path, as a `str`.

<span id="benchbox.utils.cloud_storage.CloudPathAdapter.parent"></span>
`parent` is a `CloudPathAdapter` for the parent directory.

##### Raises

The constructor raises what `create_path_handler` raises: `ImportError` for a `s3`, `gs`, `gcs`, `az` or `azure` path without `cloudpathlib`, and `ValueError` for a malformed cloud path or a `dbfs:` path outside `dbfs:/Volumes/`.

##### Example

```python
import tempfile
from benchbox.utils.cloud_storage import CloudPathAdapter

with tempfile.TemporaryDirectory() as root:
    adapter = CloudPathAdapter(root + "/data")
    print(adapter.is_cloud, adapter.path_info)
    print(adapter.exists())
    adapter.mkdir()
    print(adapter.exists())

    subdir = adapter / "benchbox" / "tpch"
    subdir.mkdir()
    print(subdir.exists(), subdir.name, subdir.parent.name)
    print(str(subdir).removeprefix(root))
```

```text
False {'is_cloud': False, 'provider': 'local'}
False
True
True tpch benchbox
/data/benchbox/tpch
```

With the `cloudstorage` extra installed, joining and naming work on cloud URIs without a request:

```python
from benchbox.utils.cloud_storage import CloudPathAdapter

adapter = CloudPathAdapter("s3://bucket/data")
print(adapter / "benchbox" / "tpch")
print(adapter.name, adapter.parent)
```

```text
s3://bucket/data/benchbox/tpch
data s3://bucket
```

##### Compatibility

- **Credential check at construction:** for a cloud URI the constructor calls `get_cloud_path_info`, which validates credentials. With credentials configured, that includes a live request.
- **Staging paths:** for `dbfs:`, `abfss:` and Snowflake stage paths, `path_handler` is a local staging wrapper. `exists()` checks the local staging directory, and `adapter / "name"` returns an adapter for a plain local path (`is_cloud` is `False`), which no longer carries the remote target.

### Cloud Storage Generator Mixin

#### `benchbox.utils.cloud_storage.CloudStorageGeneratorMixin`

<span id="benchbox.utils.cloud_storage.CloudStorageGeneratorMixin"></span>

Gives a data generator two helper methods for deciding whether its output directory is remote and for running its generation function on that directory.

**Import:** `from benchbox.utils.cloud_storage import CloudStorageGeneratorMixin` · **Extras:** none

##### Parameters

None: the mixin takes no constructor arguments.

##### Returns

Subclass instances gain two methods. Both begin with an underscore because subclasses call them; they are the whole interface of the mixin.

<span id="is_cloud_output"></span>
`_is_cloud_output(output_dir) -> bool` returns `is_cloud_path(str(output_dir))`.

<span id="handle_cloud_or_local_generation"></span>
`_handle_cloud_or_local_generation(output_dir, local_generate_func, verbose=False)` calls `local_generate_func(output_dir)` and returns its result unchanged, which is normally a dict of table name to file path. `output_dir` is passed on as given, with no conversion, and `verbose` has no effect. The method uploads nothing.

##### Raises

Nothing it raises itself. Exceptions from `local_generate_func` propagate.

##### Example

```python
import tempfile
from pathlib import Path
from benchbox.utils.cloud_storage import CloudStorageGeneratorMixin, create_path_handler

class CustomBenchmarkGenerator(CloudStorageGeneratorMixin):
    def __init__(self, row_count: int):
        self.row_count = row_count

    def generate_data(self, output_dir):
        def local_generate(local_dir):
            local_dir = Path(local_dir)
            local_dir.mkdir(parents=True, exist_ok=True)
            customer = local_dir / "customer.csv"
            customer.write_text("id,name\n" + "".join(f"{i},Customer{i}\n" for i in range(self.row_count)))
            return {"customer": customer}

        return self._handle_cloud_or_local_generation(output_dir, local_generate)

generator = CustomBenchmarkGenerator(row_count=3)
print(generator._is_cloud_output("s3://bucket/data"), generator._is_cloud_output("/tmp/data"))

with tempfile.TemporaryDirectory() as root:
    files = generator.generate_data(root + "/custom")
    print({table: path.name for table, path in files.items()})

staged = create_path_handler("abfss://container@account.dfs.core.windows.net/custom")
files = generator.generate_data(staged)
print({table: path.parent == Path(str(staged)) for table, path in files.items()}, staged.cloud_target)
```

```text
True False
{'customer': 'customer.csv'}
{'customer': True} abfss://container@account.dfs.core.windows.net/custom
```

##### Compatibility

- **Pass a handler, not a URI string:** a string such as `"s3://bucket/data"` reaches `local_generate_func` as a string, so a function that builds `Path(output_dir)` writes into a local directory with that name. Convert URIs with `create_path_handler` first, as the example does for `abfss://`.
- **Staging wrappers:** for `dbfs:`, `abfss:` and Snowflake stage targets the generation function writes to the local staging directory. Uploading from there to the remote target is not done by this mixin.
- **No upload method:** <span id="generate_with_cloud_upload"></span>the mixin has no `_generate_with_cloud_upload` method.

### Usage Guide Formatting

#### `benchbox.utils.cloud_storage.format_cloud_usage_guide`

<span id="benchbox.utils.cloud_storage.format_cloud_usage_guide"></span>

Returns a short setup guide for a cloud provider.

**Import:** `from benchbox.utils.cloud_storage import format_cloud_usage_guide` · **Extras:** none

##### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `provider` | `str` | required | One of `s3`, `gs`, `azure` or `dbfs`. |

##### Returns

`str`: the guide, with the environment variables to set and an example `benchbox run` command. The text starts and ends with a line break. For any other value, including `gcs`, `az`, `abfss` and an empty string, it returns `No setup guide available for provider: <provider>`.

##### Raises

Nothing it raises itself.

##### Example

```python
from benchbox.utils.cloud_storage import format_cloud_usage_guide

print(format_cloud_usage_guide("gs").strip())
print()
print(format_cloud_usage_guide("abfss"))
```

```text
Google Cloud Storage Setup:
1. Set up authentication:
   export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

2. Usage example:
   benchbox run --platform duckdb --benchmark tpch --scale 0.01 \
                 --output gs://your-bucket/benchbox/results

No setup guide available for provider: abfss
```

##### Compatibility

`validate_cloud_credentials` reports the provider as the scheme written in the path, so its `provider` value is `gcs`, `az` or `abfss` for those spellings and has no guide here. Pass `gs` or `azure` for those providers.

### Support Validation

#### `benchbox.utils.cloud_storage.validate_cloud_path_support`

<span id="benchbox.utils.cloud_storage.validate_cloud_path_support"></span>

Tells whether `cloudpathlib` can be imported.

**Import:** `from benchbox.utils.cloud_storage import validate_cloud_path_support` · **Extras:** none

##### Parameters

None.

##### Returns

`bool`: `True` when `cloudpathlib` is installed, `False` otherwise. The function does not check credentials, and `dbfs:`, `abfss:` and Snowflake stage paths do not need `cloudpathlib`.

##### Raises

Nothing it raises itself.

##### Example

```python
from benchbox.utils.cloud_storage import validate_cloud_path_support

if validate_cloud_path_support():
    print("✅ Cloud storage support is available")
else:
    print("❌ Install cloud storage support:")
    print('   uv add benchbox --extra cloudstorage')
```

Without `cloudpathlib`:

```text
❌ Install cloud storage support:
   uv add benchbox --extra cloudstorage
```

## Usage Examples

### Multi-Cloud Benchmark Execution

Run benchmarks across multiple cloud providers. The benchmark steps need credentials for each provider. Without credentials, every provider is skipped and the loop prints the error from `validate_cloud_credentials`.

```python
from benchbox.tpch import TPCH
from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox.utils.cloud_storage import (
    validate_cloud_credentials,
    get_cloud_path_info
)

# Define cloud storage locations
cloud_locations = {
    "aws": "s3://my-benchbox-bucket/tpch-data",
    "gcp": "gs://my-benchbox-bucket/tpch-data",
    "azure": "abfss://benchbox@myaccount.dfs.core.windows.net/tpch-data"
}

results = {}

for provider, location in cloud_locations.items():
    print(f"\n{'='*60}")
    print(f"Running TPC-H benchmark on {provider.upper()}")
    print(f"{'='*60}")

    # Validate credentials before starting
    cred_result = validate_cloud_credentials(location)

    if not cred_result["valid"]:
        print(f"⚠️  Skipping {provider}: {cred_result['error']}")
        continue

    # Get path information
    info = get_cloud_path_info(location)
    print(f"✅ Credentials valid for {info['provider']}")
    print(f"   Bucket: {info['bucket']}")
    print(f"   Path: {info['path']}")

    # Create and run benchmark
    benchmark = TPCH(scale_factor=0.01, output_dir=location)

    try:
        benchmark.generate_data()

        adapter = DuckDBAdapter()
        result = adapter.run_benchmark(benchmark)

        results[provider] = {
            "status": "success",
            "total_time": result.total_execution_time,
            "queries": len(result.query_results)
        }

        print(f"\n✅ {provider.upper()} completed: {result.total_execution_time:.2f}s")

    except Exception as e:
        results[provider] = {"status": "failed", "error": str(e)}
        print(f"\n❌ {provider.upper()} failed: {e}")

# Summary
print(f"\n{'='*60}")
print("RESULTS SUMMARY")
print(f"{'='*60}")
for provider, result in results.items():
    if result["status"] == "success":
        print(f"{provider.upper():10s}: ✅ {result['total_time']:.2f}s ({result['queries']} queries)")
    else:
        print(f"{provider.upper():10s}: ❌ {result['error']}")
```

### Credential Validation Workflow

Validate cloud credentials before benchmark execution:

```python
from benchbox.utils.cloud_storage import (
    validate_cloud_credentials,
    format_cloud_usage_guide,
    is_cloud_path
)

def validate_and_setup_storage(output_path: str) -> bool:
    """Validate cloud storage setup and provide guidance if needed."""

    # Check if path is cloud storage
    if not is_cloud_path(output_path):
        print("✅ Using local storage - no cloud setup needed")
        return True

    print(f"Cloud storage output detected: {output_path}")

    # Validate credentials
    result = validate_cloud_credentials(output_path)

    if result["valid"]:
        print(f"✅ Cloud storage credentials validated")
        print(f"   Provider: {result['provider']}")
        return True
    else:
        print(f"❌ Cloud storage credentials validation failed:")
        print(f"   Provider: {result['provider']}")
        print(f"   Error: {result['error']}")
        print()

        # Show setup guide
        guide = format_cloud_usage_guide(result['provider'])
        print(guide)

        return False

# Usage
if validate_and_setup_storage("s3://my-bucket/data"):
    # Proceed with benchmark
    pass
else:
    # Show error and exit
    print("Please configure cloud credentials and try again")
```

With the `cloudstorage` extra installed and no AWS credentials configured, the output is:

```text
Cloud storage output detected: s3://my-bucket/data
❌ Cloud storage credentials validation failed:
   Provider: s3
   Error: No AWS credentials found. Configure via:
  - aws configure (creates ~/.aws/credentials)
  - AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY env vars
  - AWS_PROFILE env var with named profile


AWS S3 Setup:
1. Set environment variables:
   export AWS_ACCESS_KEY_ID=your_access_key
   export AWS_SECRET_ACCESS_KEY=your_secret_key
   export AWS_DEFAULT_REGION=us-west-2

2. Usage example:
   benchbox run --platform duckdb --benchmark tpch --scale 0.01 \
                 --output s3://your-bucket/benchbox/results

Please configure cloud credentials and try again
```

Without `cloudpathlib`, the same call reports `Provider: unknown` and `Error: cloudpathlib not installed`.

### Cloud Path Adapter Pattern

Use CloudPathAdapter for transparent local/cloud path handling:

```python
from benchbox.utils.cloud_storage import CloudPathAdapter

def organize_benchmark_results(base_path: str, benchmark_name: str):
    """Organize benchmark results with transparent cloud/local handling."""

    # CloudPathAdapter works with both local and cloud paths
    base = CloudPathAdapter(base_path)

    # Create directory structure
    benchmark_dir = base / benchmark_name
    benchmark_dir.mkdir()

    results_dir = benchmark_dir / "results"
    results_dir.mkdir()

    data_dir = benchmark_dir / "data"
    data_dir.mkdir()

    print(f"Created benchmark structure at: {base}")
    print(f"  - Results: {results_dir}")
    print(f"  - Data: {data_dir}")

    return {
        "benchmark_dir": str(benchmark_dir),
        "results_dir": str(results_dir),
        "data_dir": str(data_dir)
    }

# Works with local paths
local_dirs = organize_benchmark_results(
    "/tmp/benchbox",
    "tpch"
)

print(local_dirs)
```

```text
Created benchmark structure at: /tmp/benchbox
  - Results: /tmp/benchbox/tpch/results
  - Data: /tmp/benchbox/tpch/data
{'benchmark_dir': '/tmp/benchbox/tpch', 'results_dir': '/tmp/benchbox/tpch/results', 'data_dir': '/tmp/benchbox/tpch/data'}
```

With the `cloudstorage` extra and credentials, an `s3://` base path gives the same structure with `s3://...` values.

### Custom Data Generator with Cloud Support

Create a custom data generator on top of `CloudStorageGeneratorMixin`:

```python
from pathlib import Path
from benchbox.utils.cloud_storage import CloudStorageGeneratorMixin, create_path_handler

class CustomBenchmarkGenerator(CloudStorageGeneratorMixin):
    """Custom benchmark generator with cloud storage support."""

    def __init__(self, row_count: int):
        self.row_count = row_count

    def generate_data(self, output_dir, verbose: bool = False):
        """Generate benchmark data into a local or staging directory."""

        def local_generate(local_dir):
            """Generate data locally."""
            import csv

            local_dir = Path(local_dir)
            local_dir.mkdir(parents=True, exist_ok=True)

            # Generate customer table
            customer_path = local_dir / "customer.csv"
            with open(customer_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['id', 'name', 'region'])
                for i in range(self.row_count):
                    writer.writerow([i, f'Customer{i}', f'Region{i % 5}'])

            # Generate orders table
            orders_path = local_dir / "orders.csv"
            with open(orders_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['order_id', 'customer_id', 'amount'])
                for i in range(self.row_count * 3):
                    writer.writerow([i, i % self.row_count, i * 10.5])

            return {
                "customer": customer_path,
                "orders": orders_path
            }

        return self._handle_cloud_or_local_generation(
            output_dir,
            local_generate,
            verbose
        )

generator = CustomBenchmarkGenerator(row_count=1000)

# Local storage
local_paths = generator.generate_data("/tmp/custom-benchmark")
print(f"Generated locally: {local_paths}")

# ADLS Gen2 target: generate into the local staging directory
staged = create_path_handler("abfss://container@account.dfs.core.windows.net/custom-benchmark")
staged_paths = generator.generate_data(staged)
print(sorted(staged_paths), staged.cloud_target)
```

```text
Generated locally: {'customer': PosixPath('/tmp/custom-benchmark/customer.csv'), 'orders': PosixPath('/tmp/custom-benchmark/orders.csv')}
['customer', 'orders'] abfss://container@account.dfs.core.windows.net/custom-benchmark
```

### Path Information Inspection

Inspect and analyze cloud paths programmatically:

```python
from benchbox.utils.cloud_storage import (
    is_cloud_path,
    get_cloud_path_info,
    validate_cloud_credentials
)

def analyze_storage_path(path: str):
    """Comprehensive storage path analysis."""

    print(f"Analyzing path: {path}")
    print("=" * 60)

    # Check if cloud path
    if not is_cloud_path(path):
        print("Type: Local filesystem")
        return

    print("Type: Cloud storage")

    # Get detailed information
    info = get_cloud_path_info(path)

    print(f"Provider: {info['provider'].upper()}")
    print(f"Bucket/Container: {info['bucket']}")
    print(f"Path: {info['path']}")

    # Validate credentials
    cred = validate_cloud_credentials(path)

    if cred["valid"]:
        print("Credentials: ✅ Valid")
    else:
        print(f"Credentials: ❌ Invalid - {cred['error']}")
        print(f"Required environment variables: {', '.join(cred['env_vars'])}")

# Analyze different paths
analyze_storage_path("abfss://container@account.dfs.core.windows.net/benchbox/tpch-data")
analyze_storage_path("/tmp/local/data")
```

With no Azure variables set:

```text
Analyzing path: abfss://container@account.dfs.core.windows.net/benchbox/tpch-data
============================================================
Type: Cloud storage
Provider: ABFSS
Bucket/Container: container
Path: benchbox/tpch-data
Credentials: ❌ Invalid - Missing environment variables: AZURE_STORAGE_ACCOUNT_NAME, AZURE_STORAGE_ACCOUNT_KEY
Required environment variables: AZURE_STORAGE_ACCOUNT_NAME, AZURE_STORAGE_ACCOUNT_KEY
Analyzing path: /tmp/local/data
============================================================
Type: Local filesystem
```

## Best Practices

1. **Always Validate Credentials**

   Validate cloud credentials before starting long-running benchmark operations:

   ```python
   from benchbox.utils.cloud_storage import validate_cloud_credentials

   # Validate before benchmark
   result = validate_cloud_credentials(output_path)
   if not result["valid"]:
       print(f"Error: {result['error']}")
       exit(1)

   # Proceed with benchmark
   benchmark.generate_data()
   ```

2. **Use Path Adapters for Portability**

   Use CloudPathAdapter for code that works with both local and cloud storage:

   ```python
   from benchbox.utils.cloud_storage import CloudPathAdapter

   # Works with any path type
   path = CloudPathAdapter(user_provided_path)
   path.mkdir()
   results_file = path / "results.json"
   ```

3. **Handle Network Errors Gracefully**

   Cloud operations can fail due to network issues - handle errors appropriately:

   ```python
   try:
       benchmark.generate_data()
   except Exception as e:
       if "credentials" in str(e).lower():
           print("Credential error - check cloud setup")
       elif "network" in str(e).lower():
           print("Network error - retry with exponential backoff")
       else:
           raise
   ```

4. **Organize Cloud Storage Efficiently**

   Use consistent naming conventions for cloud storage:

   ```python
   # Good: Organized by benchmark and scale
   output_dir = f"s3://bucket/benchmarks/{benchmark_name}/sf{scale_factor}"

   # Good: Include timestamp for results
   from datetime import datetime
   timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
   results_dir = f"s3://bucket/results/{timestamp}"
   ```

5. **Reuse Generated Data**

   Cloud storage persists across runs - check for existing data before regenerating:

   ```python
   from benchbox.utils.cloud_storage import CloudPathAdapter

   output = CloudPathAdapter(output_dir)

   if output.exists():
       print("Data already exists in cloud storage - skipping generation")
   else:
       benchmark.generate_data()
   ```

   `exists()` returns `False` when the check fails, for example because of missing credentials, so a `False` result does not prove that the data is absent.

## Common Issues

### Missing cloudpathlib Dependency

**Problem**: ImportError when using cloud paths

**Solution**:

```python
# Install cloud storage support
# uv add benchbox --extra cloudstorage

from benchbox.utils.cloud_storage import validate_cloud_path_support

if not validate_cloud_path_support():
    print("Cloud storage not available. Install with:")
    print('  uv add benchbox --extra cloudstorage')
```

### Invalid Credentials

**Problem**: Cloud operations fail with credential errors

**Solution**:

```python
from benchbox.utils.cloud_storage import (
    validate_cloud_credentials,
    format_cloud_usage_guide
)

result = validate_cloud_credentials("s3://bucket/path")

if not result["valid"]:
    # Show provider-specific setup guide
    guide = format_cloud_usage_guide(result["provider"])
    print(guide)
```

### Path Format Errors

**Problem**: Invalid cloud path format

**Solution**:

```python
# Correct formats
s3_path = "s3://bucket/path"           # ✅ AWS S3
gcs_path = "gs://bucket/path"          # ✅ Google Cloud Storage ("gcs://" is accepted as an alias)
azure_path = "abfss://container@account.dfs.core.windows.net/path"  # ✅ Azure

# Incorrect formats
bad_s3 = "s3:/bucket/path"             # ❌ Missing slash: create_path_handler raises ValueError
bad_s3a = "s3a://bucket/path"          # ❌ Not a recognised scheme: treated as a local path
```

### Network Timeouts

**Problem**: Large file uploads timeout

**Solution**:

```python
# For large benchmarks, use smaller scale factors initially
# to test cloud connectivity

# Test with small scale first
test_benchmark = TPCH(scale_factor=0.01, output_dir="s3://bucket/test")
test_benchmark.generate_data()

# Then proceed with full scale
full_benchmark = TPCH(scale_factor=10.0, output_dir="s3://bucket/full")
full_benchmark.generate_data()
```

## See Also

- {doc}`/guides/cloud-storage` - Cloud storage usage guide
- {doc}`/usage/configuration` - Configuration options
- {doc}`utilities` - Other utility functions
- {doc}`/usage/troubleshooting` - Troubleshooting guide
- {doc}`platforms/databricks` - Databricks cloud integration
- {doc}`platforms/bigquery` - BigQuery cloud integration
- {doc}`platforms/snowflake` - Snowflake cloud integration

### External Resources

- [cloudpathlib Documentation](https://cloudpathlib.drivendata.org/) - Underlying cloud path library
- [AWS S3 Documentation](https://docs.aws.amazon.com/s3/) - Amazon S3 object storage
- [Google Cloud Storage Documentation](https://docs.cloud.google.com/storage/docs) - GCS documentation
- [Azure Blob Storage Documentation](https://learn.microsoft.com/en-us/azure/storage/blobs/) - Azure storage
