# UAT Local Platform Provisioning

This runbook is the operator reference for local platforms that require a
server, container, or Spark Connect endpoint before a UAT sweep can reach them.
The index is `docs/operations/local-platform-provisioning.tsv`.

Default UAT behavior is unchanged: unreachable platforms become
`skipped_unreachable` during execute. To fail early, opt in with:

```yaml
preflight:
  local_platforms_check: true
```

For automated platforms, preflight makes one explicit `make uat-bring-up
PLATFORM=<name>` attempt before aborting. Document-only platforms must be
started by the operator.

## Automated Docker-backed platforms

These platforms have UAT-owned compose metadata, healthchecks, and a TCP probe.
They can be started explicitly:

```bash
make uat-bring-up PLATFORM=<platform>
```

- `cedardb` — `localhost:5435`, compose file `docker/cedardb/docker-compose.yml`.
- `clickhouse-server` — `localhost:9000`, compose file `docker/clickhouse/docker-compose.yml`.
- `databend` — `localhost:8000`, compose file `docker/databend/docker-compose.yml`.
- `doris` — `localhost:19031`, compose file `docker/doris/docker-compose.yml`; keep the image-provided JDK path intact.
- `influxdb` — `localhost:8181`, compose file `docker/influxdb/docker-compose.yml`.
- `lakesail` — Spark Connect endpoint `sc://localhost:50051`, compose file `docker/lakesail/docker-compose.yml`; UAT starts only `lakesail-connect` and builds the image from the public PySail package.
- `pg-duckdb` — `localhost:5432`, compose file `docker/postgres-extensions/docker-compose.pg-duckdb.yaml`; mutually exclusive with other PostgreSQL-family stacks on the default port.
- `pg-mooncake` — `localhost:5432`, compose file `docker/postgres-extensions/docker-compose.pg-mooncake.yaml`; mutually exclusive with other PostgreSQL-family stacks on the default port.
- `postgresql` — `localhost:5432`, compose file `docker/postgresql/docker-compose.yml`.
- `presto` — `localhost:18081`, compose file `docker/presto/docker-compose.yml`.
- `questdb` — `localhost:8812`, compose file `docker/questdb/docker-compose.yml`; BenchBox uses HTTP port `19000` for load paths.
- `singlestore` — `localhost:13306`, compose file `docker/singlestore/docker-compose.yml`; local password is `benchbox`.
- `starrocks` — `localhost:19030`, compose file `docker/starrocks/docker-compose.yml`; BenchBox passes FE/HTTP options during execution.
- `timescaledb` — `localhost:5432`, compose file `docker/postgres-extensions/docker-compose.timescaledb.yaml`; mutually exclusive with other PostgreSQL-family stacks on the default port.
- `trino` — `localhost:18080`, compose file `docker/trino/docker-compose.yml`; catalog configuration lives in the compose tree.
- `velox` — Spark Connect endpoint `sc://localhost:50051`, compose file `docker/velox/docker-compose.yml`; UAT starts only `velox-connect`.

## Document-only platforms

None currently. If a future local platform cannot be made project-scoped or
requires native tooling outside Docker, list it here with explicit operator
startup instructions.

## Troubleshooting

- `make uat-bring-up PLATFORM=does-not-exist` returns a non-zero exit and an
  `unknown platform` message.
- `docker ps` must work before any automated bring-up can succeed.
- If a platform remains unreachable after bring-up, inspect the platform's
  compose logs and verify the endpoint in `local-platform-provisioning.tsv`.
