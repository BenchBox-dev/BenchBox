# Microsoft Fabric Lakehouse SQL

```{tags} intermediate, guide, fabric-lakehouse, cloud-platform
```

BenchBox supports Microsoft Fabric Lakehouse SQL for **read-only query benchmarking**.

## Key Constraint

Fabric Lakehouse SQL endpoint is read-only:
- DDL is rejected (`CREATE`, `ALTER`, `DROP`)
- DML is rejected (`INSERT`, `UPDATE`, `DELETE`, `MERGE`)
- Query execution (`SELECT`) is supported

Use `fabric-spark` for `generate,load` phases, then run query phases on `fabric-lakehouse`.

## Installation

```bash
uv add benchbox --extra fabric
```

## Typical Workflow

```bash
benchbox run --platform fabric-spark --benchmark tpch --scale 1 --phases generate,load --non-interactive

benchbox run --platform fabric-lakehouse --benchmark tpch --scale 1 --phases power,throughput --non-interactive
```

Step 1 loads data through Spark. Step 2 runs the query phases through the Lakehouse SQL endpoint.

## Adapter Configuration

- `workspace`: Fabric workspace name or GUID
- `lakehouse`: Lakehouse database name
- `server`: Optional explicit SQL endpoint (`<workspace>.sql.azuresynapse.net`)
- `auth_method`: `default_credential`, `service_principal`, or `interactive`

## Notes

- Dialect: `tsql`
- Authentication: Entra ID only
- Data loading and schema creation must be done through Spark
