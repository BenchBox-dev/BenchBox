# New Platform Acceptance Checklist

```{tags} contributor, guide, platform
```

Use this checklist before opening a platform-support PR. It is deliberately concrete: platform breadth is only useful when the registry, docs, optional dependencies, compatibility rules, and tests move together.

## First Decision

| Question | Required answer |
| --- | --- |
| Is this SQL, DataFrame, or dual-mode? | Pick one primary path; dual-mode still needs separate SQL and DataFrame checks. |
| What is the `support_status`? | Use exactly one of `stable`, `beta`, `experimental`, `repo_only`, `deprecated`, `document_only`. |
| Is it runnable from a wheel? | If no, do not add it as a normal runtime platform. Use `repo_only` or `document_only`. |
| What dependency group enables it? | Add or reuse an optional extra; do not make base import require a platform SDK. |
| What is the blast radius? | List adapter files, registry metadata, docs, tests, SQL compatibility, and UAT/live scope. |

## SQL Platform Checklist

- Add the adapter under `benchbox/platforms/` or an existing platform family package.
- Keep platform SDK imports lazy or guarded so `import benchbox` remains cheap.
- Register the adapter in `_OPTIONAL_ADAPTERS` in `benchbox/core/platform_registry.py`.
- Add metadata in `PlatformRegistry._build_platform_metadata()` and one explicit `support_status` entry.
- Fill `capabilities`: `supports_sql`, `supports_dataframe`, `default_mode`, `platform_family`, `inherits_from`, `cost_class`, and deployment modes when relevant.
- Add `driver_package` and `installation_command`; dependency extras belong in `pyproject.toml`.
- Add DDL/query compatibility rules or an explicit exemption in the SQL compatibility inventory when the adapter rewrites SQL or DDL.
- Add unit tests for adapter construction, SQL rendering/loading behavior, registry metadata, optional import failure behavior, and any deployment-mode routing.
- Add a platform guide under `docs/platforms/` and update the comparison matrix only through registry-derived counts.
- Define smoke/UAT scope: local Docker, cloud live, or explicit no-live justification.

## DataFrame Platform Checklist

- Decide whether the platform belongs to the expression family, pandas family, Spark family, or a new family.
- Add adapter/context code under `benchbox/platforms/dataframe/` unless an existing family file already owns the behavior.
- Add registry metadata and `support_status`; DataFrame-only platforms must have `supports_sql=False`.
- Add the `-df` CLI path or confirm the existing `adapter_factory` mapping routes to the new adapter.
- Add native DataFrame query implementations or document unsupported benchmarks with benchmark-gate rules.
- Add lazy availability checks and dependency extras; GPU or native-stack dependencies must not load during base import.
- Add unit tests for family behavior, adapter lifecycle, query execution primitives, and registry capability alignment.
- Add docs under `docs/platforms/` using the `-df` CLI name and compatibility caveats.
- Validate against DuckDB SQL at SF=0.01 where the benchmark has parity expectations.

## Documentation and Drift Checks

- README and platform matrix exact counts must match `PlatformRegistry.get_platform_count_summary()`.
- The public docs should describe support status separately from local dependency availability.
- New docs should link to setup, credentials, deployment modes, and benchmark limitations.
- If a platform is experimental or deprecated, the docs must say so on the first screen.

## Measured Extension Cost

Recent platform additions show the minimum durable file count is not one adapter file:

| Example | Evidence | Durable files touched |
| --- | --- | ---: |
| LakeSail release follow-up | `b2559016b` touched registry, adapter, platform docs, and unit tests. | 4 |
| Onehouse Quanton initial support | `e0438e993` touched registry, adapter package, client, and docs. | 4 |
| Databend/Doris/LakeSail/Quanton migration | `e980da3ae` touched registry, adapters, docs, and tests across multiple platforms. | 10+ per platform family cluster |

Target for a straightforward SQL platform is **7-10 files**:

- adapter or family module,
- registry metadata and optional adapter entry,
- optional dependency extra,
- SQL compatibility rule or explicit exemption,
- unit tests,
- platform docs,
- count/drift or acceptance checklist update when a claim changes.

Target for a straightforward DataFrame platform is **8-12 files** because native query implementations and family tests usually add another surface.

## Scaffold Helper

Run the scaffold helper to print the expected file plan before starting:

```bash
uv run -- python _project/scripts/platform_scaffold.py --name newdatabase --kind sql
uv run -- python _project/scripts/platform_scaffold.py --name newframe --kind dataframe
```

The helper emits a checklist and file plan only. It is an architecture health aid, not a framework that owns platform implementation.
