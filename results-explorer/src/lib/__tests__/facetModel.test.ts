import { act, renderHook } from "@testing-library/preact";
import { describe, expect, it, beforeEach } from "vitest";
import {
  DEFAULT_FACETS,
  FACET_KEYS,
  FACET_URL_KEYS,
  FACET_URL_SERDES,
  facetsToWhereClause,
  readFacetParam,
  type FacetKey,
  type FacetState,
} from "@/lib/facetModel";
import { useUrlState, type UrlSerde } from "@/lib/useUrlState";

const SAMPLE_VALUES: { [K in FacetKey]: FacetState[K] } = {
  benchmark: ["tpch", "star_schema"],
  scale_factor: ["0.01", "1"],
  phase: ["power", "throughput"],
  platform: ["DuckDB", "ClickHouse"],
  execution_mode: ["sql"],
  tuning_mode: ["default", "tuned"],
  trust_tier: ["maintainer-run"],
  validation_status: ["exact", "loose"],
  deployment_class: ["cloud", "local"],
  cloud_provider: ["aws", "gcp"],
  cloud_region: ["us-east-1"],
  instance_or_warehouse: ["m6i.large", "MEDIUM"],
  storage_format: ["parquet"],
  cost_status: ["normalized"],
  date_window: "90d",
};

function clearSearch() {
  window.history.replaceState(null, "", "/");
}

function renderFacetUrlState(key: FacetKey) {
  return renderHook(() =>
    useUrlState<unknown>(
      FACET_URL_KEYS[key],
      DEFAULT_FACETS[key],
      FACET_URL_SERDES[key] as UrlSerde<unknown>,
    ),
  );
}

describe("facet URL contract", () => {
  beforeEach(() => {
    clearSearch();
  });

  it("defines every expected facet key", () => {
    expect(FACET_KEYS).toStrictEqual([
      "benchmark",
      "scale_factor",
      "phase",
      "platform",
      "execution_mode",
      "tuning_mode",
      "trust_tier",
      "validation_status",
      "deployment_class",
      "cloud_provider",
      "cloud_region",
      "instance_or_warehouse",
      "storage_format",
      "cost_status",
      "date_window",
    ]);
  });

  for (const key of FACET_KEYS) {
    it(`round-trips ${key} through useUrlState`, () => {
      const sample = SAMPLE_VALUES[key];
      const first = renderFacetUrlState(key);

      act(() => {
        first.result.current[1](sample);
      });
      first.unmount();

      const second = renderFacetUrlState(key);
      expect(second.result.current[0]).toEqual(sample);
    });
  }

  it("reads legacy aliases while preserving the new canonical key", () => {
    const params = new URLSearchParams("bm=tpch,ssb&date_window=30d");

    expect(readFacetParam(params, "benchmark")).toEqual(["tpch", "ssb"]);
    expect(readFacetParam(params, "date_window")).toBe("30d");
  });
});

describe("facetsToWhereClause", () => {
  it("builds a parameterized WHERE clause for core, deployment, and cost facets", () => {
    const { sql, params } = facetsToWhereClause(
      {
        benchmark: ["tpch"],
        scale_factor: ["0.01", "not-a-number"],
        phase: ["power"],
        platform: ["DuckDB"],
        execution_mode: ["sql"],
        tuning_mode: ["default"],
        trust_tier: ["maintainer-run"],
        validation_status: ["exact"],
        deployment_class: ["cloud", "local"],
        cloud_provider: ["aws"],
        cloud_region: ["us-east-1"],
        instance_or_warehouse: ["MEDIUM"],
        storage_format: ["parquet"],
        cost_status: ["normalized"],
        date_window: "30d",
      },
      { now: new Date("2026-05-02T00:00:00.000Z") },
    );

    expect(sql).toContain("benchmark IN (?)");
    expect(sql).toContain("scale_factor IN (?)");
    expect(sql).toContain("test_type IN (?)");
    expect(sql).toContain("(cloud_provider IS NOT NULL OR cost_status = ?)");
    expect(sql).toContain("COALESCE(instance_type, warehouse_size, cluster_size) IN (?)");
    expect(sql).toContain("run_date >= ?");
    expect(params).toEqual([
      "tpch",
      0.01,
      "power",
      "DuckDB",
      "sql",
      "default",
      "maintainer-run",
      "exact",
      "not_applicable_local",
      "aws",
      "us-east-1",
      "MEDIUM",
      "parquet",
      "normalized",
      "2026-04-02T00:00:00.000Z",
    ]);
  });

  it("returns an empty clause for default facets", () => {
    expect(facetsToWhereClause()).toEqual({ sql: "", params: [] });
  });
});
