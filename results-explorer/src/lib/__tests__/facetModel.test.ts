import { act, renderHook } from "@testing-library/preact";
import { describe, expect, it, beforeEach } from "vitest";
import {
  ALL_FACET_KEYS,
  DEFAULT_FACETS,
  FACET_KEYS,
  FACET_URL_KEYS,
  FACET_URL_SERDES,
  HARDWARE_FACET_KEYS,
  facetsToWhereClause,
  normalizeFacetState,
  readFacetParam,
  useFacetField,
  type ExplorerFacetKey,
  type FacetState,
} from "@/lib/facetModel";
import { matchesFacetRow } from "@/lib/facetMatching";
import { useUrlState, type UrlSerde } from "@/lib/useUrlState";

const SAMPLE_VALUES: { [K in ExplorerFacetKey]: FacetState[K] } = {
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
  platform_version: ["1.1.0", "1.2.0"],
  arch: ["arm64", "x86_64"],
  cpu_family: ["apple_silicon", "graviton"],
};

function clearSearch() {
  window.history.replaceState(null, "", "/");
}

function renderFacetUrlState(key: ExplorerFacetKey) {
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
    expect(HARDWARE_FACET_KEYS).toStrictEqual([
      "platform_version",
      "arch",
      "cpu_family",
    ]);
    expect(ALL_FACET_KEYS).toStrictEqual([
      ...FACET_KEYS,
      ...HARDWARE_FACET_KEYS,
    ]);
  });

  for (const key of ALL_FACET_KEYS) {
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
    const params = new URLSearchParams(
      "bm=tpch,ssb&date_window=30d&deployment_class=cloud&instance_type=m6i.large&warehouse_size=MEDIUM",
    );

    expect(readFacetParam(params, "benchmark")).toEqual(["tpch", "ssb"]);
    expect(readFacetParam(params, "date_window")).toBe("30d");
    expect(readFacetParam(params, "deployment_class")).toEqual(["cloud"]);
    // w16: when both ?instance_type= and ?warehouse_size= are present, the
    // shared `instance_or_warehouse` facet must merge them rather than
    // dropping one. Pre-w16 this returned only ["m6i.large"], silently
    // discarding the warehouse_size value on the next mount.
    expect(readFacetParam(params, "instance_or_warehouse")).toEqual(["m6i.large", "MEDIUM"]);
  });

  it("merges multiple legacy aliases for instance_or_warehouse (w16)", () => {
    // Multi-value aliases on each side: both halves of the union should
    // survive after dedupe.
    const params = new URLSearchParams("instance_type=m6i.large,c5.xlarge&warehouse_size=MEDIUM,LARGE");
    expect(readFacetParam(params, "instance_or_warehouse")).toEqual([
      "m6i.large",
      "c5.xlarge",
      "MEDIUM",
      "LARGE",
    ]);
  });

  it("dedupes overlapping alias values when merging (w16)", () => {
    const params = new URLSearchParams("instance_type=foo,bar&warehouse_size=bar,baz");
    expect(readFacetParam(params, "instance_or_warehouse")).toEqual(["foo", "bar", "baz"]);
  });

  it("canonical key takes precedence over aliases when both are present (w16)", () => {
    // The canonical URL key for instance_or_warehouse is `shape` (see
    // FACET_URL_KEYS); aliases include `instance_type` and `warehouse_size`.
    const params = new URLSearchParams(
      "shape=canonical&instance_type=foo&warehouse_size=bar",
    );
    expect(readFacetParam(params, "instance_or_warehouse")).toEqual(["canonical"]);
  });

  it("treats legacy all sentinel values as default selections", () => {
    const params = new URLSearchParams("phase=all&tuning=all&trust=all");

    expect(readFacetParam(params, "phase")).toEqual([]);
    expect(readFacetParam(params, "tuning_mode")).toEqual([]);
    expect(readFacetParam(params, "trust_tier")).toEqual([]);
  });

  it("can mount one shared facet without canonicalizing unrelated aliases", () => {
    window.history.replaceState(null, "", "/?warehouse_size=MEDIUM");

    const { result } = renderHook(() => useFacetField("benchmark"));
    expect(result.current[0]).toEqual([]);
    expect(new URL(window.location.href).searchParams.get("warehouse_size")).toBe("MEDIUM");
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

    expect(sql).toContain("CASE WHEN benchmark = 'star_schema' THEN 'ssb'");
    expect(sql).toContain("scale_factor IN (?)");
    expect(sql).toContain("THEN 'unknown' ELSE trim(lower(test_type)) END IN (?)");
    expect(sql).toContain("(platform IN (?) OR platform_id IN (?))");
    expect(sql).toContain("deployment_class IN (?, ?)");
    expect(sql).toContain("instance_or_warehouse IN (?)");
    expect(sql).toContain("run_date >= ?");
    expect(params).toEqual([
      "tpch",
      0.01,
      "power",
      "DuckDB",
      "DuckDB",
      "sql",
      "default",
      "maintainer-run",
      "exact",
      "cloud",
      "local",
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

  it("preserves the legacy untuned tuning sentinel as NULL tuning mode", () => {
    const { sql, params } = facetsToWhereClause({ tuning_mode: ["untuned", "auto"] });

    expect(sql).toContain("(tuning_mode IN (?) OR tuning_mode IS NULL)");
    expect(params).toEqual(["auto"]);
  });

  // The `unknown` phase cohort is user-selectable, and `matchesFacetRow` folds a
  // null/blank `test_type` into it. A raw `test_type IN ('unknown')` predicate
  // matched no null-phase row, so the cohort that produced the facet returned an
  // empty leaderboard.
  it("folds null and blank test_type into the unknown phase cohort", () => {
    const { sql, params } = facetsToWhereClause({ phase: ["unknown"] });

    expect(sql).toContain("coalesce(test_type, '')");
    expect(sql).toContain("THEN 'unknown'");
    expect(params).toEqual(["unknown"]);

    const rowMatches = matchesFacetRow({ test_type: null }, normalizeFacetState({ phase: ["unknown"] }), {
      keys: ["phase"],
    });
    expect(rowMatches).toBe(true);
  });

  it("canonicalizes phase casing on both the SQL and in-memory sides", () => {
    const { params } = facetsToWhereClause({ phase: ["POWER", "power", " Power "] });

    // canonicalPhase() trims and lowercases, so the three spellings collapse to
    // one bound parameter rather than three literals that miss stored casing.
    expect(params).toEqual(["power"]);

    const rowMatches = matchesFacetRow({ test_type: "POWER" }, normalizeFacetState({ phase: ["power"] }), {
      keys: ["phase"],
    });
    expect(rowMatches).toBe(true);
  });

  describe("hardware identity and engine version facets", () => {
    it("reads platform_version, arch, and cpu_family from URL aliases", () => {
      const params = new URLSearchParams(
        "engine_version=1.2.0&architecture=arm64&cpu=apple_silicon",
      );

      expect(readFacetParam(params, "platform_version")).toEqual(["1.2.0"]);
      expect(readFacetParam(params, "arch")).toEqual(["arm64"]);
      expect(readFacetParam(params, "cpu_family")).toEqual(["apple_silicon"]);
    });

    it("reads canonical URL parameters for platform_version, arch, and cpu_family", () => {
      const params = new URLSearchParams(
        "version=1.1.0,1.2.0&arch=arm64,x86_64&cpu_family=apple_silicon,graviton",
      );

      expect(readFacetParam(params, "platform_version")).toEqual(["1.1.0", "1.2.0"]);
      expect(readFacetParam(params, "arch")).toEqual(["arm64", "x86_64"]);
      expect(readFacetParam(params, "cpu_family")).toEqual(["apple_silicon", "graviton"]);
    });

    it("degrades gracefully to all-inclusive when parameters are missing or empty", () => {
      const emptyParams = new URLSearchParams("");
      expect(readFacetParam(emptyParams, "platform_version")).toEqual([]);
      expect(readFacetParam(emptyParams, "arch")).toEqual([]);
      expect(readFacetParam(emptyParams, "cpu_family")).toEqual([]);

      const blankParams = new URLSearchParams("version=&arch=&cpu_family=");
      expect(readFacetParam(blankParams, "platform_version")).toEqual([]);
      expect(readFacetParam(blankParams, "arch")).toEqual([]);
      expect(readFacetParam(blankParams, "cpu_family")).toEqual([]);
    });

    it("generates correct WHERE clauses for hardware facets", () => {
      const { sql, params } = facetsToWhereClause({
        platform_version: ["1.2.0"],
        arch: ["arm64"],
        cpu_family: ["apple_silicon"],
      });

      expect(sql).toContain("platform_version IN (?)");
      expect(sql).toContain("result_id IN (SELECT result_id FROM bench.result_environment WHERE arch IN (?))");
      expect(sql).toContain("result_id IN (SELECT result_id FROM bench.result_environment WHERE cpu_family IN (?))");
      expect(params).toEqual(["1.2.0", "arm64", "apple_silicon"]);
    });

    it("matches in-memory rows for hardware facets in matchesFacetRow", () => {
      const row = {
        platform_version: "1.2.0",
        arch: "arm64",
        cpu_family: "apple_silicon",
      };

      expect(
        matchesFacetRow(row, normalizeFacetState({ platform_version: ["1.2.0"] }), {
          keys: ["platform_version"],
        }),
      ).toBe(true);
      expect(
        matchesFacetRow(row, normalizeFacetState({ arch: ["arm64"] }), {
          keys: ["arch"],
        }),
      ).toBe(true);
      expect(
        matchesFacetRow(row, normalizeFacetState({ cpu_family: ["apple_silicon"] }), {
          keys: ["cpu_family"],
        }),
      ).toBe(true);

      // Missing candidate in row does not match non-empty filter
      const emptyRow = {
        platform_version: null,
        arch: null,
        cpu_family: null,
      };
      expect(
        matchesFacetRow(emptyRow, normalizeFacetState({ arch: ["arm64"] }), {
          keys: ["arch"],
        }),
      ).toBe(false);

      // Empty filter matches any row (all-inclusive)
      expect(
        matchesFacetRow(emptyRow, normalizeFacetState({}), {
          keys: ["platform_version", "arch", "cpu_family"],
        }),
      ).toBe(true);
    });
  });
});
