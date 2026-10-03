Cloud Storage Integration API
=============================

.. tags:: reference, python-api, cloud-storage

Complete Python API reference for BenchBox cloud storage integration.

Overview
--------

BenchBox provides seamless cloud storage integration through a minimal abstraction layer built on ``cloudpathlib``. The cloud storage API enables benchmarks to work with cloud storage locations (S3, GCS, Azure Blob Storage) while maintaining the same interface as local paths.

**Key Features**:

- **Unified Path Handling**: Transparent support for local and cloud paths
- **Local Staging**: Resolved staging paths retain remote targets for adapter-owned upload
- **Credential Validation**: Built-in validation for cloud credentials
- **Multi-Cloud Support**: AWS S3, Google Cloud Storage, Azure Blob Storage
- **Platform Integration**: Native integration with cloud database platforms
- **Error Handling**: Comprehensive error messages and troubleshooting guidance

Quick Start
-----------

Cloud storage paths work transparently with BenchBox:

.. code-block:: python

    from benchbox.tpch import TPCH
    from benchbox.platforms.duckdb import DuckDBAdapter

    benchmark = TPCH(
        scale_factor=0.01,
        output_dir="s3://my-bucket/benchbox/tpch-data"
    )

    benchmark.generate_data()

    adapter = DuckDBAdapter()
    results = adapter.run_benchmark(benchmark)

Installation
------------

Cloud storage support requires the optional ``cloudstorage`` dependency:

.. code-block:: bash

    uv add benchbox --extra cloudstorage

    uv pip install "benchbox[cloud]"

Supported Providers
-------------------

**AWS S3**: ``s3://bucket/path``
    Amazon S3 object storage with native DuckDB, Snowflake, and Redshift support.

**Google Cloud Storage**: ``gs://bucket/path``
    Google Cloud Storage with native BigQuery and DuckDB support.

**Azure Blob Storage**: ``abfss://container@account.dfs.core.windows.net/path``
    Azure Data Lake Storage Gen2 with native Databricks and DuckDB support.

**Databricks Unity Catalog**: ``dbfs:/Volumes/catalog/schema/volume/path``
    Databricks-managed cloud storage with automatic credential handling.

API Reference
-------------

Path Detection
~~~~~~~~~~~~~~

.. py:function:: benchbox.utils.cloud_storage.is_cloud_path(path: Union[str, Path]) -> bool

   Classify the string representation of a path. Recognize s3, gs/gcs, az/azure,
   abfss/abfs and dbfs URI schemes, plus supported Snowflake stage references.
   Classification is not credential validation or evidence that a platform supports
   that storage target. No cloud request is made by this classifier.


Check if a path points to cloud storage.

**Parameters**:

- **path** (str | Path): Path to check

**Returns**: bool - True if path is cloud storage

**Examples**:

.. code-block:: python

    from benchbox.utils.cloud_storage import is_cloud_path

    assert is_cloud_path("s3://bucket/path")
    assert is_cloud_path("gs://bucket/path")
    assert is_cloud_path("abfss://container@account.dfs.core.windows.net/path")

    assert not is_cloud_path("/local/path")
    assert not is_cloud_path("./relative/path")

Path Creation
~~~~~~~~~~~~~

.. py:function:: benchbox.utils.cloud_storage.create_path_handler(path: Union[str, Path]) -> Union[Path, CloudPath, DatabricksPath, CloudStagingPath]

   Return a local Path for local locations or a cloudpathlib handler for supported
   ordinary cloud URIs. Normalize recognized URI aliases before cloudpathlib use.
   Databricks dbfs:/Volumes/catalog/schema/volume, Snowflake stage references and
   ADLS abfss/abfs paths create a local temporary staging directory whose wrapper
   retains the remote target for the platform adapter. Existing DatabricksPath,
   CloudStagingPath and recognized loaded CloudPath objects pass through unchanged.

   Staging wrappers expose a local path to generators; constructing a handler does
   not upload generated files. Preserve cloud_target (CloudStagingPath) or dbfs_target (DatabricksPath) when passing a wrapper through
   the benchmark's output-directory plumbing.

   :raises ImportError: An ordinary cloud path requires unavailable cloudpathlib.
   :raises ValueError: A Databricks path does not name a Unity Catalog Volume, or cloudpathlib rejects the path.


Create appropriate path handler for local or cloud paths.

**Parameters**:

- **path** (str | Path): Local or cloud storage path

**Returns**: Path | CloudPath | DatabricksPath | CloudStagingPath - A local, ordinary cloud, or local staging path handler

**Raises**:

- **ImportError**: If cloud path provided but cloudpathlib not installed
- **ValueError**: If cloud path format is invalid

**Examples**:

.. code-block:: python

    from benchbox.utils.cloud_storage import create_path_handler

    local_path = create_path_handler("/tmp/data")
    print(type(local_path))

    cloud_path = create_path_handler("s3://bucket/data")
    print(type(cloud_path))

    local_path.mkdir(parents=True, exist_ok=True)
    cloud_path.mkdir(parents=True, exist_ok=True)

Local Staging Path Wrappers
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: benchbox.utils.cloud_storage.DatabricksPath(local_path: Union[str, Path], dbfs_target: str)

   Associate a local filesystem path with a remote upload target stored in
   ``dbfs_target``. Construction converts strings to pathlib.Path and retains a
   supplied Path. It does not create directories or upload files; directory
   persistence and cleanup belong to the caller that supplies local_path.

   ``str(wrapper)`` and ``os.fspath(wrapper)`` expose the local path. Keep the
   wrapper when passing the output directory to an adapter: converting it to
   Path discards its remote target. The ``/`` operator returns a plain local
   Path, as do joinpath(), parent and resolve().

   Two wrappers of this same class compare their local paths and remote
   targets. Comparison with a string or Path uses only the local path. Hashing
   uses the local path. Filesystem queries and mutations below are local.

   .. py:attribute:: dbfs_target
      :type: str

      The remote target supplied at construction, retained verbatim.

   .. py:method:: exists() -> bool

      Return whether the local path exists.

   .. py:method:: mkdir(parents: bool=True, exist_ok: bool=True) -> None

      Create the local directory. Both parent creation and acceptance of an existing directory default to True.

   .. py:method:: is_dir() -> bool

      Return whether the local path names a directory.

   .. py:method:: is_file() -> bool

      Return whether the local path names a regular file.

   .. py:method:: iterdir() -> Iterator[Path]

      Return an iterator over immediate children as plain local Path objects.

   .. py:method:: glob(pattern: str) -> Iterator[Path]

      Return an iterator over matching local Path objects, using pathlib glob semantics.

   .. py:method:: rglob(pattern: str) -> Iterator[Path]

      Return an iterator over matching local Path objects recursively.

   .. py:attribute:: name
      :type: str

      The final component of the local path.

   .. py:attribute:: parent
      :type: Path

      The local parent as a plain Path; the returned object does not retain the remote target.

   .. py:attribute:: parts
      :type: tuple

      The local path components as a tuple. This is a property.

   .. py:method:: as_posix() -> str

      Return the local path with forward slashes.

   .. py:attribute:: suffix
      :type: str

      The suffix of the final local path component, including its leading dot when present.

   .. py:method:: joinpath(*other: Union[str, Path]) -> Path

      Join local components and return a plain Path without remote target metadata.

   .. py:method:: stat(*, follow_symlinks: bool=True) -> os.stat_result

      Return local filesystem metadata. Follow symlinks unless follow_symlinks=False.

   .. py:method:: resolve(strict: bool=False) -> Path

      Resolve the local path to an absolute plain Path. strict=False permits missing components; the returned Path does not retain the remote target.

.. py:class:: benchbox.utils.cloud_storage.CloudStagingPath(local_path: Union[str, Path], cloud_target: str)

   Associate a local filesystem path with a remote upload target stored in
   ``cloud_target``. Construction converts strings to pathlib.Path and retains a
   supplied Path. It does not create directories or upload files; directory
   persistence and cleanup belong to the caller that supplies local_path.

   ``str(wrapper)`` and ``os.fspath(wrapper)`` expose the local path. Keep the
   wrapper when passing the output directory to an adapter: converting it to
   Path discards its remote target. The ``/`` operator returns a plain local
   Path, as do joinpath(), parent and resolve().

   Two wrappers of this same class compare their local paths and remote
   targets. Comparison with a string or Path uses only the local path. Hashing
   uses the local path. Filesystem queries and mutations below are local.

   .. py:attribute:: cloud_target
      :type: str

      The remote target supplied at construction, retained verbatim.

   .. py:method:: exists() -> bool

      Return whether the local path exists.

   .. py:method:: mkdir(parents: bool=True, exist_ok: bool=True) -> None

      Create the local directory. Both parent creation and acceptance of an existing directory default to True.

   .. py:method:: is_dir() -> bool

      Return whether the local path names a directory.

   .. py:method:: is_file() -> bool

      Return whether the local path names a regular file.

   .. py:method:: iterdir() -> Iterator[Path]

      Return an iterator over immediate children as plain local Path objects.

   .. py:method:: glob(pattern: str) -> Iterator[Path]

      Return an iterator over matching local Path objects, using pathlib glob semantics.

   .. py:method:: rglob(pattern: str) -> Iterator[Path]

      Return an iterator over matching local Path objects recursively.

   .. py:attribute:: name
      :type: str

      The final component of the local path.

   .. py:attribute:: parent
      :type: Path

      The local parent as a plain Path; the returned object does not retain the remote target.

   .. py:attribute:: parts
      :type: tuple

      The local path components as a tuple. This is a property.

   .. py:attribute:: suffix
      :type: str

      The suffix of the final local path component, including its leading dot when present.

   .. py:method:: joinpath(*other: Union[str, Path]) -> Path

      Join local components and return a plain Path without remote target metadata.

   .. py:method:: stat(*, follow_symlinks: bool=True) -> os.stat_result

      Return local filesystem metadata. Follow symlinks unless follow_symlinks=False.

   .. py:method:: as_posix() -> str

      Return the local path with forward slashes.

   .. py:method:: resolve(strict: bool=False) -> Path

      Resolve the local path to an absolute plain Path. strict=False permits missing components; the returned Path does not retain the remote target.

Credential Validation
~~~~~~~~~~~~~~~~~~~~~

.. py:function:: benchbox.utils.cloud_storage.validate_cloud_credentials(path: Union[str, Path]) -> dict[str, Any]

   Return valid, provider, error and env_vars keys. Local paths are valid without
   credentials. Databricks and Snowflake stage paths return valid=True as deferred
   adapter checks; this does not prove authorization. ADLS checks expected Azure
   environment variables without importing cloudpathlib. Ordinary cloud providers
   require cloudpathlib; S3 accepts environment credentials, AWS_PROFILE, or an AWS
   credentials/config file, while other providers check their expected variables.

   Ordinary cloud validation then constructs a path and calls exists(), which can
   issue a remote request. A successful credential check does not guarantee that
   the object exists or that writes are authorized. Provider/SDK failures return
   valid=False and an error description.


Validate cloud credentials for a given path.

**Parameters**:

- **path** (str | Path): Cloud storage path to validate

**Returns**: dict - Validation results with keys:

  - **valid** (bool): Whether credentials are valid
  - **provider** (str): Cloud provider (s3, gs, azure)
  - **error** (str | None): Error message if validation failed
  - **env_vars** (list[str]): Environment variables checked

**Examples**:

.. code-block:: python

    from benchbox.utils.cloud_storage import validate_cloud_credentials

    result = validate_cloud_credentials("s3://my-bucket/data")

    if result["valid"]:
        print("✅ S3 credentials are valid")
    else:
        print(f"❌ Credential validation failed: {result['error']}")
        print(f"Required environment variables: {result['env_vars']}")


Path Information
~~~~~~~~~~~~~~~~

.. py:function:: benchbox.utils.cloud_storage.get_cloud_path_info(path: Union[str, Path]) -> dict[str, Any]

   Return is_cloud, provider, bucket, path and credentials_valid. Local paths have
   bucket=None and credentials_valid=True. Databricks adds volume_info with catalog,
   schema and volume; Snowflake adds stage_info. ADLS splits the URI authority into
   container bucket and account. Ordinary cloud information includes account
   (None for other providers) and calls validate_cloud_credentials, so inspection
   can issue remote requests. Databricks/Snowflake credential flags defer to their
   platform adapter rather than verifying access here.


Get detailed information about a cloud path.

**Parameters**:

- **path** (str | Path): Path to analyze

**Returns**: dict - Path information with keys:

  - **is_cloud** (bool): Whether path is cloud storage
  - **provider** (str): Provider name (s3, gs, azure, local)
  - **bucket** (str | None): Bucket/container name
  - **path** (str): Path within bucket
  - **credentials_valid** (bool): Whether credentials are valid

**Examples**:

.. code-block:: python

    from benchbox.utils.cloud_storage import get_cloud_path_info

    info = get_cloud_path_info("s3://my-bucket/benchbox/tpch-data")
    print(info)

    info = get_cloud_path_info("/tmp/data")
    print(info)

Directory Creation
~~~~~~~~~~~~~~~~~~

.. py:function:: benchbox.utils.cloud_storage.ensure_cloud_directory(path: Union[str, Path, CloudPath]) -> Union[Path, CloudPath, DatabricksPath]

   Resolve strings/Paths with create_path_handler and return the resulting handler.
   Call mkdir(parents=True, exist_ok=True) when available. Otherwise check exists()
   and log that an absent directory may be created on its first write. Remote
   handlers can issue cloud requests; provider errors propagate. Object stores do
   not necessarily have a physical directory to create.


Ensure cloud or local directory exists.

**Parameters**:

- **path** (str | Path | CloudPath): Directory path to create

**Returns**: Path | CloudPath | DatabricksPath | CloudStagingPath. The resolved
handler retains staging-wrapper behavior. The declared return annotation omits
CloudStagingPath; callers can receive it at runtime.

**Raises**:

- **Exception**: If directory creation fails

**Examples**:

.. code-block:: python

    from benchbox.utils.cloud_storage import ensure_cloud_directory

    s3_dir = ensure_cloud_directory("s3://bucket/benchbox/results")

    local_dir = ensure_cloud_directory("/tmp/benchbox/results")

    print(s3_dir.exists())
    print(local_dir.exists())

Cloud Path Adapter
~~~~~~~~~~~~~~~~~~

.. py:class:: benchbox.utils.cloud_storage.CloudPathAdapter(path: Union[str, Path])

   Wrap a local or cloud path behind a small common interface. Construction resolves
   a path handler and, for cloud paths, obtains path information; credential
   inspection can therefore issue a remote request. original_path, is_cloud,
   path_handler and path_info hold the resolved state.

.. py:method:: benchbox.utils.cloud_storage.CloudPathAdapter.exists() -> bool

   Return the handler existence result, or False when the handler raises. An access error and absence therefore share this result.


.. py:method:: benchbox.utils.cloud_storage.CloudPathAdapter.mkdir(parents: bool=True, exist_ok: bool=True) -> None

   Call the handler mkdir with the supplied parents/exist_ok flags when available; otherwise do nothing. Handler errors propagate.


.. py:method:: benchbox.utils.cloud_storage.CloudPathAdapter.__str__() -> str

   Return the underlying handler string representation.


.. py:method:: benchbox.utils.cloud_storage.CloudPathAdapter.__truediv__(other: str) -> CloudPathAdapter

   Join a component using the underlying handler and wrap the result in a new CloudPathAdapter.


.. py:property:: benchbox.utils.cloud_storage.CloudPathAdapter.name
   :type: str

   Return the handler final path component.


.. py:property:: benchbox.utils.cloud_storage.CloudPathAdapter.parent
   :type: CloudPathAdapter

   Return a new CloudPathAdapter for the parent; new cloud adapter construction can inspect credentials.



Unified interface for local and cloud paths with transparent operation handling.

**Constructor**:

**Parameters**:

- **path** (str | Path): Local or cloud storage path

**Attributes**:

- **original_path** (str): Original path string
- **is_cloud** (bool): Whether path is cloud storage
- **path_handler** (Path | CloudPath): Underlying path object
- **path_info** (dict): Cloud path information

**Methods**:

- **exists()** → bool: Check if path exists
- **mkdir(parents=True, exist_ok=True)**: Create directory
- **name** (property): Get the name of the path
- **parent** (property): Get the parent directory

**Examples**:

.. code-block:: python

    from benchbox.utils.cloud_storage import CloudPathAdapter

    adapter = CloudPathAdapter("s3://bucket/data")

    if not adapter.exists():
        adapter.mkdir(parents=True, exist_ok=True)

    subdir = adapter / "benchbox" / "tpch"
    print(subdir)

    print(adapter.name)
    print(adapter.parent)

    local = CloudPathAdapter("/tmp/data")
    local.mkdir()
    subdir = local / "results"
    print(subdir.exists())

Cloud Storage Generator Mixin
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: benchbox.utils.cloud_storage.CloudStorageGeneratorMixin

   Provide a generator extension hook that invokes local generation for a resolved
   output path. The mixin does not upload files or resolve a URI itself. Staging
   wrappers retain cloud_target or dbfs_target for adapter-owned upload during loading.

.. py:method:: benchbox.utils.cloud_storage.CloudStorageGeneratorMixin._is_cloud_output(output_dir) -> bool

   Classify output_dir after converting it to a string with is_cloud_path.


.. py:method:: benchbox.utils.cloud_storage.CloudStorageGeneratorMixin._handle_cloud_or_local_generation(output_dir, local_generate_func, verbose: bool=False)

   Call local_generate_func(output_dir) and return its value unchanged. The callback
   owns local file creation; pass a Path or resolved staging wrapper rather than a
   raw cloud URI to a callback that uses local filesystem operations. verbose is
   accepted for compatibility but has no effect in this hook.



Mixin class for generators using local or resolved staging paths.

**Purpose**: Invoke the local generator callback without discarding a resolved staging wrapper. The platform adapter owns remote upload.

**Methods**:

.. method:: _is_cloud_output(output_dir) -> bool

   Check if output directory is a cloud path.

.. method:: _handle_cloud_or_local_generation(output_dir, local_generate_func, verbose=False)

   Invoke local_generate_func with the supplied resolved output path.

   **Parameters**:

   - **output_dir** (str | Path): Output directory (local or cloud)
   - **local_generate_func** (callable): Function to generate data locally
   - **verbose** (bool): Whether to print verbose output

   **Returns**: The callback return value, unchanged (typically a mapping of table names to generated local file paths)

**Usage in Generators**:

.. code-block:: python

    from benchbox.utils.cloud_storage import CloudStorageGeneratorMixin, create_path_handler

    class MyBenchmarkGenerator(CloudStorageGeneratorMixin):
        def generate_data(self, output_dir, verbose=False):
            def local_generate(local_dir):
                return {
                    "table1": local_dir / "table1.csv",
                    "table2": local_dir / "table2.csv"
                }

            return self._handle_cloud_or_local_generation(
                create_path_handler(output_dir), local_generate, verbose
            )

Usage Guide Formatting
~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: benchbox.utils.cloud_storage.format_cloud_usage_guide(provider: str) -> str

   Return the built-in setup guide for the exact provider key s3, gs, azure or dbfs.
   Other keys return "No setup guide available for provider: ...". This formats text
   only; it does not configure credentials or verify a provider connection.


Format setup guide for cloud storage provider.

**Parameters**:

- **provider** (str): Cloud provider (s3, gs, azure)

**Returns**: str - Formatted usage guide

**Examples**:

.. code-block:: python

    from benchbox.utils.cloud_storage import format_cloud_usage_guide

    guide = format_cloud_usage_guide("s3")
    print(guide)

Support Validation
~~~~~~~~~~~~~~~~~~

.. py:function:: benchbox.utils.cloud_storage.validate_cloud_path_support() -> bool

   Return whether cloudpathlib can be loaded. This may load the optional library,
   but does not test credentials, a remote path, or staging-only platform support.


Validate that cloud path support is available.

**Returns**: bool - True if cloudpathlib is installed

**Examples**:

.. code-block:: python

    from benchbox.utils.cloud_storage import validate_cloud_path_support

    if validate_cloud_path_support():
        print("✅ Cloud storage support is available")
    else:
        print("❌ Install cloud storage support:")
        print('   uv add benchbox --extra cloudstorage')


Provider Classification and Output Preservation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: benchbox.utils.cloud_storage.is_snowflake_stage_path(path: Union[str, Path]) -> bool

   Recognize leading ``@`` user (``@~``), table (``@%table``), named and up to
   three-part qualified stage references, optionally followed by a slash and
   subpath. Identifiers are unquoted or double quoted; doubled quotes escape a
   quote within a quoted identifier. A slash inside a quoted stage identifier
   belongs to that identifier. PurePath inputs normalize backslashes to slashes;
   strings retain their spelling. An ``@`` within a cloud URI is not a stage.

.. py:function:: benchbox.utils.cloud_storage.snowflake_stage_mode_error(path: Union[str, Path], *, table_mode: str = "native") -> str | None

   Return no error for non-stage inputs. For a stage, case-insensitive external
   mode returns an explanatory error because CREATE STAGE URL requires a cloud
   URI. All other modes accept only user stages and reject named/table stages:
   native loads upload to each table's own stage instead of reusing staging_root.
   This produces an error string; it does not raise or validate credentials.

.. py:function:: benchbox.utils.cloud_storage.is_adls_path(path: Union[str, Path]) -> bool

   Recognize the abfss and abfs scheme family. These URIs encode their storage
   account in the authority, so conversion to az would lose that account;
   create_path_handler stages them locally with the original target retained.

.. py:function:: benchbox.utils.cloud_storage.is_databricks_path(path: Union[str, Path]) -> bool

   Recognize the dbfs URI scheme. This predicate does not check the UC Volume
   path shape; create_path_handler requires the literal dbfs:/Volumes/ prefix.

.. py:function:: benchbox.utils.cloud_storage.cloud_provider_family(path: Union[str, Path]) -> Union[str, None]

   Return aws for s3, gcp for gs/gcs, azure for az/azure/abfss/abfs, or databricks
   for dbfs. Return None for local paths, unknown schemes and schemeless Snowflake
   stages. Provider gating uses these families rather than separate alias lists.

.. py:class:: benchbox.utils.cloud_storage.CloudScheme(canonical: str, aliases: tuple[str, ...], family: str, env_vars: tuple[str, ...], stages_locally: bool = False)

   Immutable named tuple describing a supported scheme. canonical is the spelling
   registered by cloudpathlib, or the retained spelling for a staged family;
   aliases lists accepted alternative spellings; family supports platform gates;
   env_vars lists credential variables checked by validate_cloud_credentials.
   stages_locally selects generic local staging instead of cloudpathlib.
   dbfs has this flag False and uses the separate DatabricksPath branch.
   The shared scheme table drives recognition, alias normalization, provider
   families and credential checks so adding a spelling does not bypass one of
   those checks. Non-staged aliases gcs and azure rewrite to gs and az; abfs
   retains its account-bearing URI instead of rewriting to cloudpathlib az.

.. py:function:: benchbox.utils.cloud_storage.normalize_output_dir(path: Union[str, Path, None]) -> Union[Path, CloudPath, DatabricksPath, CloudStagingPath, None]

   Preserve None and existing local Path, DatabricksPath and CloudStagingPath
   objects by identity. Otherwise delegate to create_path_handler, including its
   cloudpathlib support and errors. Benchmark output-directory assignments must
   retain staging wrappers rather than pass them through Path, which would keep
   only the local cache and discard the remote upload target.

Remote File Operations
~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: benchbox.utils.cloud_storage.RemoteFileSystemAdapter

   Protocol for validation-time remote file operations. Inputs are opaque absolute
   remote paths including their scheme; implementations own remote access.

   .. py:method:: file_exists(remote_path: str) -> bool

      Report whether the remote file exists.

   .. py:method:: read_file(remote_path: str) -> bytes

      Read the file contents as bytes.

   .. py:method:: write_file(remote_path: str, content: bytes) -> None

      Write the supplied bytes to the remote file.

   .. py:method:: list_files(remote_path: str, pattern: str = "*") -> list[str]

      List matching paths under the remote location.

.. py:class:: benchbox.utils.cloud_storage.DatabricksVolumeAdapter(workspace_client: Any | None = None, *, host: str | None = None, token: str | None = None)

   Implement RemoteFileSystemAdapter through the Databricks Files API. Construction
   lazily imports databricks.sdk even when workspace_client is supplied; missing
   or failing SDK imports raise ImportError. Use the supplied client, or construct
   WorkspaceClient with https:// prefixed to a nonempty host and the supplied
   token; None leaves those settings to SDK configuration. Remove the dbfs:
   marker before Files API calls.

   file_exists returns False on provider errors. read_file accepts downloaded
   bytes or a stream with read(); write_file uploads a BytesIO with overwrite=True.
   Read/write errors become RuntimeError with the original exception as cause.
   list_files extracts path, then file_path, then string representation from
   returned objects; fnmatch filters their final slash-separated component with
   the supplied pattern. Listing errors return an empty list. Dictionary entries
   have no special key lookup. These operations can make real remote requests.

.. py:function:: benchbox.utils.cloud_storage.get_remote_fs_adapter(remote_path: str) -> RemoteFileSystemAdapter

   Support only dbfs paths. Lazily construct WorkspaceClient using SDK environment
   configuration and return DatabricksVolumeAdapter. Missing SDK support raises
   ImportError; other initialization failures raise RuntimeError with credential
   guidance. Other providers raise ValueError. This factory does not validate
   the UC Volume prefix or introduce placeholder support for other providers.

Usage Examples
--------------

Multi-Cloud Benchmark Execution
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Run benchmarks across multiple cloud providers:

.. code-block:: python

    from benchbox.tpch import TPCH
    from benchbox.platforms.duckdb import DuckDBAdapter
    from benchbox.utils.cloud_storage import (
        validate_cloud_credentials,
        get_cloud_path_info
    )

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

        cred_result = validate_cloud_credentials(location)

        if not cred_result["valid"]:
            print(f"⚠️  Skipping {provider}: {cred_result['error']}")
            continue

        info = get_cloud_path_info(location)
        print(f"✅ Credentials valid for {info['provider']}")
        print(f"   Bucket: {info['bucket']}")
        print(f"   Path: {info['path']}")

        benchmark = TPCH(scale_factor=0.01, output_dir=location)

        try:
            benchmark.generate_data(verbose=True)

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

    print(f"\n{'='*60}")
    print("RESULTS SUMMARY")
    print(f"{'='*60}")
    for provider, result in results.items():
        if result["status"] == "success":
            print(f"{provider.upper():10s}: ✅ {result['total_time']:.2f}s ({result['queries']} queries)")
        else:
            print(f"{provider.upper():10s}: ❌ {result['error']}")

Credential Validation Workflow
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Validate cloud credentials before benchmark execution:

.. code-block:: python

    from benchbox.utils.cloud_storage import (
        validate_cloud_credentials,
        format_cloud_usage_guide,
        is_cloud_path
    )

    def validate_and_setup_storage(output_path: str) -> bool:

        if not is_cloud_path(output_path):
            print("✅ Using local storage - no cloud setup needed")
            return True

        print(f"Cloud storage output detected: {output_path}")

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

            guide = format_cloud_usage_guide(result['provider'])
            print(guide)

            return False

    if validate_and_setup_storage("s3://my-bucket/data"):
        pass
    else:
        print("Please configure cloud credentials and try again")

Cloud Path Adapter Pattern
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use CloudPathAdapter for transparent local/cloud path handling:

.. code-block:: python

    from benchbox.utils.cloud_storage import CloudPathAdapter

    def organize_benchmark_results(base_path: str, benchmark_name: str):

        base = CloudPathAdapter(base_path)

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

    s3_dirs = organize_benchmark_results(
        "s3://my-bucket/benchbox",
        "tpch"
    )

    local_dirs = organize_benchmark_results(
        "/tmp/benchbox",
        "tpch"
    )

    print(s3_dirs)

Custom Data Generator with Cloud Support
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Create a generator that writes to a local or resolved staging path:

.. code-block:: python

    from pathlib import Path
    from benchbox.utils.cloud_storage import CloudStorageGeneratorMixin, create_path_handler

    class CustomBenchmarkGenerator(CloudStorageGeneratorMixin):

        def __init__(self, row_count: int):
            self.row_count = row_count

        def generate_data(self, output_dir, verbose: bool = False):

            def local_generate(local_dir: Path):
                local_dir = Path(local_dir)
                import csv

                local_dir.mkdir(parents=True, exist_ok=True)

                customer_path = local_dir / "customer.csv"
                with open(customer_path, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(['id', 'name', 'region'])
                    for i in range(self.row_count):
                        writer.writerow([i, f'Customer{i}', f'Region{i % 5}'])

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
                create_path_handler(output_dir),
                local_generate,
                verbose
            )

    generator = CustomBenchmarkGenerator(row_count=1000)
    local_paths = generator.generate_data("/tmp/custom-benchmark", verbose=True)
    print(f"Generated locally: {local_paths}")

    staged_target = create_path_handler("dbfs:/Volumes/catalog/schema/volume/data")
    staged_paths = generator.generate_data(staged_target, verbose=True)
    print(f"Generated locally for {staged_target.dbfs_target}: {staged_paths}")

The staged files remain local at this point. A compatible platform adapter must
upload them during loading; the mixin has not transferred them to the remote
volume. Creating this staging wrapper does not validate Databricks credentials.

Path Information Inspection
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Inspect and analyze cloud paths programmatically:

.. code-block:: python

    from benchbox.utils.cloud_storage import (
        is_cloud_path,
        get_cloud_path_info,
        validate_cloud_credentials
    )

    def analyze_storage_path(path: str):

        print(f"Analyzing path: {path}")
        print("=" * 60)

        if not is_cloud_path(path):
            print("Type: Local filesystem")
            return

        print("Type: Cloud storage")

        info = get_cloud_path_info(path)

        print(f"Provider: {info['provider'].upper()}")
        print(f"Bucket/Container: {info['bucket']}")
        print(f"Path: {info['path']}")

        cred = validate_cloud_credentials(path)

        if cred["valid"]:
            print("Credentials: ✅ Valid")
        else:
            print(f"Credentials: ❌ Invalid - {cred['error']}")
            print(f"Required environment variables: {', '.join(cred['env_vars'])}")

    analyze_storage_path("s3://my-bucket/benchbox/tpch-data")

    analyze_storage_path("/tmp/local/data")

Best Practices
--------------

1. **Always Validate Credentials**

   Validate cloud credentials before starting long-running benchmark operations:

   .. code-block:: python

       from benchbox.utils.cloud_storage import validate_cloud_credentials

       result = validate_cloud_credentials(output_path)
       if not result["valid"]:
           print(f"Error: {result['error']}")
           exit(1)

       benchmark.generate_data()

2. **Use Path Adapters for Portability**

   Use CloudPathAdapter for code that works with both local and cloud storage:

   .. code-block:: python

       from benchbox.utils.cloud_storage import CloudPathAdapter

       path = CloudPathAdapter(user_provided_path)
       path.mkdir()
       results_file = path / "results.json"

3. **Handle Network Errors Gracefully**

   Cloud operations can fail due to network issues - handle errors appropriately:

   .. code-block:: python

       try:
           benchmark.generate_data(output_dir="s3://bucket/data")
       except Exception as e:
           if "credentials" in str(e).lower():
               print("Credential error - check cloud setup")
           elif "network" in str(e).lower():
               print("Network error - retry with exponential backoff")
           else:
               raise

4. **Organize Cloud Storage Efficiently**

   Use consistent naming conventions for cloud storage:

   .. code-block:: python

       output_dir = f"s3://bucket/benchmarks/{benchmark_name}/sf{scale_factor}"

       from datetime import datetime
       timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
       results_dir = f"s3://bucket/results/{timestamp}"

5. **Reuse Generated Data**

   Cloud storage persists across runs - check for existing data before regenerating:

   .. code-block:: python

       from benchbox.utils.cloud_storage import CloudPathAdapter

       output = CloudPathAdapter(output_dir)

       if output.exists():
           print("Data already exists in cloud storage - skipping generation")
       else:
           benchmark.generate_data()

Common Issues
-------------

Missing cloudpathlib Dependency
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Problem**: ImportError when using cloud paths

**Solution**:

.. code-block:: python

    from benchbox.utils.cloud_storage import validate_cloud_path_support

    if not validate_cloud_path_support():
        print("Cloud storage not available. Install with:")
        print('  uv add benchbox --extra cloudstorage')

Invalid Credentials
~~~~~~~~~~~~~~~~~~~

**Problem**: Cloud operations fail with credential errors

**Solution**:

.. code-block:: python

    from benchbox.utils.cloud_storage import (
        validate_cloud_credentials,
        format_cloud_usage_guide
    )

    result = validate_cloud_credentials("s3://bucket/path")

    if not result["valid"]:
        guide = format_cloud_usage_guide(result["provider"])
        print(guide)

Path Format Errors
~~~~~~~~~~~~~~~~~~

**Problem**: Invalid cloud path format

**Solution**:

.. code-block:: python

    s3_path = "s3://bucket/path"
    gcs_path = "gs://bucket/path"
    azure_path = "abfss://container@account.dfs.core.windows.net/path"

    bad_s3 = "s3:/bucket/path"
    bad_gcs = "gcs://bucket/path"

Network Timeouts
~~~~~~~~~~~~~~~~

**Problem**: Large file uploads timeout

**Solution**:

.. code-block:: python

    test_benchmark = TPCH(scale_factor=0.01, output_dir="s3://bucket/test")
    test_benchmark.generate_data(verbose=True)

    full_benchmark = TPCH(scale_factor=10.0, output_dir="s3://bucket/full")
    full_benchmark.generate_data(verbose=True)

See Also
--------

- :doc:`/guides/cloud-storage` - Cloud storage usage guide
- :doc:`/usage/configuration` - Configuration options
- :doc:`utilities` - Other utility functions
- :doc:`/usage/troubleshooting` - Troubleshooting guide
- :doc:`platforms/databricks` - Databricks cloud integration
- :doc:`platforms/bigquery` - BigQuery cloud integration
- :doc:`platforms/snowflake` - Snowflake cloud integration

External Resources
~~~~~~~~~~~~~~~~~~

- `cloudpathlib Documentation <https://cloudpathlib.drivendata.org/>`_ - Underlying cloud path library
- `AWS S3 Documentation <https://docs.aws.amazon.com/s3/>`_ - Amazon S3 object storage
- `Google Cloud Storage Documentation <https://docs.cloud.google.com/storage/docs>`_ - GCS documentation
- `Azure Blob Storage Documentation <https://learn.microsoft.com/en-us/azure/storage/blobs/>`_ - Azure storage
