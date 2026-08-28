/**
 * Schema introspection against the attached `bench` DuckDB database.
 *
 * The Query workbench used to bootstrap its column picker from
 * `results_schema.json`. That sidecar is no longer required - DuckDB exposes
 * the same information via `duckdb_columns()` and we already have a READ_ONLY
 * connection to the live database. Querying DuckDB directly keeps the
 * workbench column picker in sync with whatever the pipeline actually
 * materialised.
 */

import { queryRows } from "@/db";

export interface SchemaColumn {
  name: string;
  type: string;
}

// DuckDB attaches a file-backed database under the schema name of its root
// catalog, which for a freshly-built DB is always "main". Cache the probed
// schema so browser round-trips stay one query. We probe instead of
// hard-coding so the introspection helper survives any future pipeline
// change that lands a non-default schema.
let cachedBenchSchema: string | null = null;

async function benchSchemaName(): Promise<string> {
  if (cachedBenchSchema !== null) return cachedBenchSchema;
  const rows = await queryRows<{ schema_name: string }>(
    "SELECT DISTINCT schema_name FROM duckdb_columns() WHERE database_name = 'bench'",
  );
  // Prefer 'main' when present, otherwise take the first non-system schema.
  const names = rows.map((r) => r.schema_name).filter((n) => n && n !== "information_schema");
  cachedBenchSchema = names.includes("main") ? "main" : names[0] ?? "main";
  return cachedBenchSchema;
}

/**
 * Return the columns of a base table or view in the attached `bench` schema,
 * ordered by declaration order. Use `"results"` by default - the Query
 * workbench's default SELECT target.
 */
export async function getTableSchema(tableName = "results"): Promise<SchemaColumn[]> {
  const schema = await benchSchemaName();
  return queryRows<SchemaColumn>(
    "SELECT column_name AS name, data_type AS type"
    + " FROM duckdb_columns()"
    + " WHERE database_name = 'bench' AND schema_name = ? AND table_name = ?"
    + " ORDER BY column_index",
    [schema, tableName],
  );
}

/**
 * Return the full list of user-visible relation names in the attached `bench`
 * database. Used to populate future workbench dropdowns that let analysts
 * pivot between canonical tables. Kept here (rather than in duckdbQueries.ts)
 * because it is schema metadata, not a metric surface.
 */
export async function listBenchTables(): Promise<string[]> {
  const schema = await benchSchemaName();
  const rows = await queryRows<{ table_name: string }>(
    "SELECT DISTINCT table_name"
    + " FROM duckdb_columns()"
    + " WHERE database_name = 'bench' AND schema_name = ?"
    + " ORDER BY table_name",
    [schema],
  );
  return rows.map((row) => row.table_name);
}
