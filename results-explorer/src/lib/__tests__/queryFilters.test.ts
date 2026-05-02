import { describe, it, expect } from "vitest";
import {
  buildFacetCountQuery,
  buildSelectQuery,
  DEFAULT_ROW_LIMIT,
  UNLIMITED_ROW_LIMIT,
  type QueryFilterState,
  type QuerySort,
} from "@/lib/queryFilters";

const EMPTY_FILTERS: QueryFilterState = {
  benchmarks: [],
  platforms: [],
  scaleFactors: [],
  tuningModes: [],
  trustTiers: [],
  validationStatuses: [],
  costStatuses: [],
  costModelVersions: [],
  cloudProviders: [],
  cloudRegions: [],
  instanceTypes: [],
  warehouseSizes: [],
  storageFormats: [],
  hasCost: "all",
  dateWindow: "all",
};

const DEFAULT_SORT: QuerySort = { column: "run_date", direction: "desc" };

describe("buildSelectQuery LIMIT", () => {
  it("applies DEFAULT_ROW_LIMIT when no limit is passed", () => {
    const { sql } = buildSelectQuery(EMPTY_FILTERS, ["result_id"], DEFAULT_SORT);
    expect(sql).toContain(`LIMIT ${DEFAULT_ROW_LIMIT}`);
  });

  it("respects an explicit limit override", () => {
    const { sql } = buildSelectQuery(EMPTY_FILTERS, ["result_id"], DEFAULT_SORT, 50);
    expect(sql).toContain("LIMIT 50");
  });

  it("uses UNLIMITED_ROW_LIMIT for CSV-style exports", () => {
    const { sql } = buildSelectQuery(EMPTY_FILTERS, ["result_id"], DEFAULT_SORT, UNLIMITED_ROW_LIMIT);
    expect(sql).toContain(`LIMIT ${UNLIMITED_ROW_LIMIT}`);
    expect(UNLIMITED_ROW_LIMIT).toBe(Number.MAX_SAFE_INTEGER);
  });

  it("falls back to DEFAULT_ROW_LIMIT when an invalid limit is supplied", () => {
    const { sql } = buildSelectQuery(EMPTY_FILTERS, ["result_id"], DEFAULT_SORT, Number.NaN);
    expect(sql).toContain(`LIMIT ${DEFAULT_ROW_LIMIT}`);

    const negative = buildSelectQuery(EMPTY_FILTERS, ["result_id"], DEFAULT_SORT, -5);
    expect(negative.sql).toContain(`LIMIT ${DEFAULT_ROW_LIMIT}`);
  });

  it("floors fractional limits", () => {
    const { sql } = buildSelectQuery(EMPTY_FILTERS, ["result_id"], DEFAULT_SORT, 123.9);
    expect(sql).toContain("LIMIT 123");
  });

  it("allows normalized cost and deployment columns in projections and sorting", () => {
    const { sql } = buildSelectQuery(
      EMPTY_FILTERS,
      ["result_id", "normalized_cost_usd", "cost_status", "cloud_provider", "warehouse_size"],
      { column: "normalized_cost_usd", direction: "asc" },
      25,
    );

    expect(sql).toContain("SELECT result_id, normalized_cost_usd, cost_status, cloud_provider, warehouse_size");
    expect(sql).toContain("ORDER BY normalized_cost_usd ASC");
  });
});

describe("buildWhereClause - normalized cost/deployment facets", () => {
  it("filters by normalized cost status and deployment metadata", () => {
    const filters: QueryFilterState = {
      ...EMPTY_FILTERS,
      costStatuses: ["normalized"],
      costModelVersions: ["2026.05.0"],
      cloudProviders: ["aws"],
      cloudRegions: ["us-east-1"],
      warehouseSizes: ["MEDIUM"],
      storageFormats: ["parquet"],
    };

    const { sql, params } = buildSelectQuery(filters, ["result_id"], DEFAULT_SORT, 10);

    expect(sql).toContain("cost_status IN (?)");
    expect(sql).toContain("cost_model_version IN (?)");
    expect(sql).toContain("cloud_provider IN (?)");
    expect(sql).toContain("cloud_region IN (?)");
    expect(sql).toContain("warehouse_size IN (?)");
    expect(sql).toContain("storage_format IN (?)");
    expect(params).toEqual(["normalized", "2026.05.0", "aws", "us-east-1", "MEDIUM", "parquet"]);
  });

  it("can exclude one deployment facet while preserving the others", () => {
    const filters: QueryFilterState = {
      ...EMPTY_FILTERS,
      costStatuses: ["normalized"],
      cloudProviders: ["aws"],
    };

    const { sql, params } = buildFacetCountQuery("cloud_provider", filters, { exclude: "cloudProviders" });

    expect(sql).toContain("cost_status IN (?)");
    expect(sql).not.toContain("cloud_provider IN (?)");
    expect(params).toEqual(["normalized"]);
  });
});

describe("buildFacetCountQuery - date_window derived", () => {
  it("produces valid SQL with no other active filters (opens a fresh WHERE)", () => {
    const { sql, params } = buildFacetCountQuery("run_date", EMPTY_FILTERS, {
      exclude: "dateWindow",
      derived: "date_window",
    });
    // Must not contain bare `AND` without a preceding WHERE
    expect(sql).not.toMatch(/FROM bench\.results\s+AND/);
    // Must contain WHERE for each UNION branch
    const whereCount = (sql.match(/WHERE run_date >= \?/g) ?? []).length;
    expect(whereCount).toBe(3);
    // params: 3 cutoff values (no base params when no filters active)
    expect(params).toHaveLength(3);
  });

  it("produces valid SQL when other filters are active (appends AND to existing WHERE)", () => {
    const filters: QueryFilterState = { ...EMPTY_FILTERS, benchmarks: ["tpch"] };
    const { sql, params } = buildFacetCountQuery("run_date", filters, {
      exclude: "dateWindow",
      derived: "date_window",
    });
    // Each UNION branch should have WHERE benchmark IN (?) AND run_date >= ?
    expect(sql).not.toMatch(/FROM bench\.results\s+AND/);
    const whereCount = (sql.match(/WHERE benchmark IN/g) ?? []).length;
    expect(whereCount).toBe(3);
    // 3 × (1 benchmark param + 1 cutoff param)
    expect(params).toHaveLength(6);
  });
});
