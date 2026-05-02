<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Result Execution Environment Contract

```{tags} contributor, architecture, results
```

BenchBox schema v2.1 result artifacts separate the machine that runs BenchBox
from the database, DataFrame engine, container, or cloud service that executes
the measured queries. The normalized contract lives in the top-level
`environment` block and the normalized `platform` facets. Legacy blocks remain
available during the migration window.

## Canonical Blocks

| Block | Purpose | Compatibility relationship |
| --- | --- | --- |
| `environment.client_host` | BenchBox client process host: OS, architecture, CPU count, memory, Python, and anonymized machine ID. | Mirrors the legacy flat `environment.os`, `environment.arch`, and related host keys. |
| `environment.platform_runtime` | Runtime that executed the measured engine: local process, DataFrame process, Docker container, remote server, managed cloud, serverless, or unknown. | Replaces assumptions previously inferred from `platform.name`, `system_profile`, or localhost config. |
| `environment.container` | Optional Docker/container details when the platform runtime is proven container-backed. | Absent or `collection_status="unavailable"` when Docker is not involved or cannot be inspected. |
| `platform.deployment` | Deployment and connection shape: embedded, localhost server, remote self-hosted server, managed cloud, or serverless. | Normalized replacement for adapter-specific `connection_mode` and host/endpoint hints. |
| `platform.cloud` | Cloud provider, region/location, and anonymized account/project/workspace identifiers. | Normalized replacement for adapter-specific cloud config fields. |
| `platform.compute` | Compute shape: warehouse, workgroup, cluster, slots, RPU, node type/count, cache flags, and collection state. | Normalized replacement for adapter-specific warehouse/cluster/workgroup metadata. |
| `platform.storage` | Storage and staging shape: table format, staging location type, bucket/prefix, compression, and cleanup policy. | Normalized replacement for adapter-specific staging/output config. |
| `platform.raw_config` | Sanitized adapter config retained for diagnostics and legacy consumers. | Compatibility block; not canonical for cross-platform analysis. |
| `platform.raw_metadata` | Sanitized observed adapter metadata retained for diagnostics and legacy consumers. | Compatibility block; not canonical for cross-platform analysis. |

Consumers should prefer normalized fields first. Use `platform.raw_config`,
`platform.raw_metadata`, `platform.config`, `platform_info`, and
`platform_metadata` only as compatibility fallbacks.

## Runtime Types

| `runtime_type` | Meaning |
| --- | --- |
| `local_process` | The measured engine runs in the same local process family as BenchBox, such as embedded DuckDB. |
| `dataframe_process` | A DataFrame backend executes in-process or in a local Python-managed runtime. |
| `docker_container` | The measured server runs in a Docker/container runtime discovered by metadata collection. |
| `remote_server` | BenchBox connects to a self-hosted server outside the client process, with no Docker proof. |
| `managed_cloud` | BenchBox connects to a managed cloud warehouse, service, or cluster. |
| `serverless` | BenchBox submits work to a serverless query service such as Athena or BigQuery on-demand. |
| `unknown` | BenchBox cannot prove the platform runtime shape. This is a valid result state. |

Do not treat `localhost` as `local_process`. Many BenchBox integration
platforms expose a localhost port from a Linux container while the BenchBox
client runs on macOS.

## Source And Collection Status

Fields that can come from several places carry provenance:

| Value | Meaning |
| --- | --- |
| `registered_default` | Value came from a registered platform-option default. |
| `saved_config` | Value came from saved config or credentials after secret stripping. |
| `environment_variable` | Value came from an environment variable. |
| `cli_option` | Value came from `--platform-option`. |
| `runtime_override` | Value came from a runtime override. |
| `requested` | Value was requested/configured but not observed from the platform. |
| `observed` | Value was observed from Docker, SQL, SDK, or cloud metadata APIs. |
| `inferred` | Value was conservatively inferred from safe local metadata. |
| `unavailable` | Value could not be collected or does not apply. |

Collection status is separate from source:

| Value | Meaning |
| --- | --- |
| `available` | The block or field was collected successfully. |
| `partial` | Some useful fields are present, but the block is incomplete. |
| `unavailable` | Metadata is absent, unsupported, permission-denied, or not applicable. |
| `error` | Collection attempted and failed; include error class/message when safe. |
| `not_requested` | Collection was intentionally skipped. |

Cloud and Docker metadata collection must never fail a benchmark. Permission
denial, missing Docker, missing optional SDKs, or unavailable metadata APIs are
represented as `collection_status="unavailable"` or `partial`.

## Examples

### Embedded Local Process

```json
{
  "environment": {
    "client_host": {"os": "Linux 6.8", "arch": "x86_64"},
    "platform_runtime": {
      "runtime_type": "local_process",
      "collection_status": "available",
      "source": "observed",
      "os": "Linux",
      "arch": "x86_64"
    }
  },
  "platform": {
    "deployment": {
      "deployment_type": "embedded",
      "connection_mode": "in-memory",
      "endpoint_class": "embedded_process",
      "metadata_source": "observed",
      "collection_status": "available"
    },
    "raw_config": {"database": ":memory:", "threads": 4}
  }
}
```

### Docker-Backed Localhost Server

```json
{
  "environment": {
    "client_host": {"os": "Darwin 24.4.0", "arch": "arm64"},
    "platform_runtime": {
      "runtime_type": "docker_container",
      "collection_status": "available",
      "source": "observed",
      "os": "Linux",
      "arch": "amd64"
    },
    "container": {
      "collection_status": "available",
      "source": "observed",
      "image": "clickhouse/clickhouse-server:24.1",
      "port_mappings": {"8123/tcp": [{"host_port": "8123"}]}
    }
  },
  "platform": {
    "deployment": {
      "deployment_type": "self_hosted",
      "connection_mode": "localhost",
      "endpoint_class": "localhost_port",
      "metadata_source": "observed",
      "collection_status": "available"
    },
    "raw_config": {"host": "localhost", "port": 8123}
  }
}
```

### Managed Cloud Warehouse

```json
{
  "environment": {
    "platform_runtime": {
      "runtime_type": "managed_cloud",
      "collection_status": "partial",
      "source": "requested"
    }
  },
  "platform": {
    "deployment": {
      "deployment_type": "managed_cloud",
      "endpoint_class": "cloud_endpoint",
      "metadata_source": "requested",
      "collection_status": "partial"
    },
    "cloud": {
      "provider": "aws",
      "region": "us-east-1",
      "account": "account_4f3a9f7f2c10",
      "source": "requested",
      "collection_status": "partial"
    },
    "compute": {
      "warehouse": "warehouse_f91c6c42a771",
      "warehouse_size": "XSMALL",
      "result_cache_enabled": false,
      "source": "requested",
      "collection_status": "partial"
    }
  }
}
```

### Serverless Query Engine

```json
{
  "environment": {
    "platform_runtime": {
      "runtime_type": "serverless",
      "collection_status": "partial",
      "source": "requested"
    }
  },
  "platform": {
    "deployment": {
      "deployment_type": "managed_cloud",
      "connection_mode": "serverless",
      "endpoint_class": "cloud_endpoint"
    },
    "cloud": {"provider": "aws", "region": "us-west-2"},
    "compute": {
      "workgroup": "workgroup_7c067df4a6e1",
      "source": "requested",
      "collection_status": "partial"
    },
    "storage": {
      "staging_location": "path_e9b0e4610e50",
      "bucket": "bucket_887660335609",
      "prefix": "prefix_69fe07c2dd89",
      "table_format": "parquet"
    }
  }
}
```

### Metadata Unavailable

```json
{
  "environment": {
    "platform_runtime": {
      "runtime_type": "managed_cloud",
      "collection_status": "unavailable",
      "source": "unavailable",
      "collection_error_class": "Forbidden"
    }
  },
  "platform": {
    "deployment": {
      "deployment_type": "managed_cloud",
      "endpoint_class": "cloud_endpoint",
      "metadata_source": "unavailable",
      "collection_status": "unavailable"
    },
    "cloud": {
      "provider": "gcp",
      "region_collection_status": "unavailable",
      "source": "unavailable",
      "collection_status": "unavailable"
    }
  }
}
```

## Anonymization Policy

`ResultExporter(anonymize=True)` is the public-export default. It applies to
normalized blocks, compatibility raw blocks, `config.platform_options`, and
execution metadata before JSON is written.

| Data class | Public export behavior |
| --- | --- |
| Passwords, tokens, secrets, access keys, private keys, session tokens, connection strings, credential files | Redacted as `"<redacted>"`. |
| Hostnames, endpoints, account IDs, project IDs, workspace URLs, HTTP paths | Stable hashed identifiers such as `host_<hash>` or `endpoint_<hash>`. |
| Bucket names, prefixes, databases, schemas, warehouses, workgroups, clusters, container IDs/names | Stable hashed identifiers with field-specific prefixes. |
| Bind mount paths, local data paths, staging/output locations | Stable `path_<hash>` identifiers. |
| Provider, region, runtime type, endpoint class, node type, size, cache flags, source, collection status | Preserved because they are required for comparison and do not identify a private resource by themselves. |

Use `ResultExporter(anonymize=False)` only for explicit private/internal
artifacts. Private exports preserve raw metadata and can contain infrastructure
identifiers or secrets that should not be submitted publicly.

## Migration Guidance

Existing consumers can migrate without breaking old artifacts:

1. Read `environment.client_host` first. Fall back to legacy flat
   `environment.os`, `environment.arch`, `environment.cpu_count`,
   `environment.memory_gb`, `environment.python`, and `system_profile` only
   when `client_host` is absent.
2. Read `environment.platform_runtime.runtime_type` for where measured work ran.
   Do not infer runtime type from `platform.name`, `platform.config.host`, or
   `localhost`.
3. Read `platform.deployment`, `platform.cloud`, `platform.compute`, and
   `platform.storage` for normalized comparison dimensions.
4. Use `platform.raw_config`, `platform.raw_metadata`, `platform.config`,
   `platform_info`, and `platform_metadata` as diagnostics or compatibility
   fallbacks only.
5. Treat missing normalized fields in older v2 artifacts as
   `runtime_type="unknown"` and `collection_status="unavailable"`.
6. Treat `source` and `collection_status` as part of the value. A requested
   warehouse and an observed warehouse are not equivalent evidence.

The compatibility tests and golden fixtures for this contract live in:

- `tests/fixtures/golden/results/environment_capture_schema_cases.json`
- `tests/unit/core/results/test_environment_schema_compatibility.py`
- `tests/unit/core/results/test_environment_anonymization.py`
