import { queryRows } from "@/db";

export interface SchemaColumn {
  name: string;
  type: string;
}

let cachedBenchSchema: string | null = null;

async function benchSchemaName(): Promise<string> {
  if (cachedBenchSchema !== null) return cachedBenchSchema;
  const rows = await queryRows<{ schema_name: string }>(
    "SELECT DISTINCT schema_name FROM duckdb_columns() WHERE database_name = 'bench'",
  );
  const names = rows.map((r) => r.schema_name).filter((n) => n && n !== "information_schema");
  cachedBenchSchema = names.includes("main") ? "main" : names[0] ?? "main";
  return cachedBenchSchema;
}

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
