import { describe, expect, it } from "vitest";
import { buildOutput, normaliseState, platformsForFilters, searchFromState, stateFromSearch } from "../src/lib/prompt-builder.ts";
import { loadPromptCatalog, parseCatalogSource } from "../src/lib/prompt-catalog.ts";

const catalog = loadPromptCatalog();

describe("prompt catalog", () => {
  it("parses the generated include", () => {
    expect(catalog.defaults.platform).toBe("duckdb");
    expect(catalog.benchmarks.map((b) => b.id)).toContain("tpch");
  });

  it("rejects a file that is not the generated include", () => {
    expect(() => parseCatalogSource("var x = 1;")).toThrow(/does not assign/);
  });
});

describe("normaliseState", () => {
  it("falls back to the catalog defaults", () => {
    const state = normaliseState(catalog, {});
    expect(state).toMatchObject({ goal: "test_one", surface: "cli", interface: "sql", deployment: "local", platform: "duckdb", benchmark: "tpch", scale: "0.01" });
    expect(state.platformA).toBeUndefined();
  });

  it("resolves legacy numeric scales", () => {
    const state = normaliseState(catalog, { scale: "1" });
    expect(state.scale).toBe(catalog.scales.map(String).find((s) => parseFloat(s) === 1));
  });

  it("drops a benchmark the interface does not support", () => {
    const state = normaliseState(catalog, { interface: "dataframe", benchmark: "clickbench" });
    expect(state.benchmark).not.toBe("clickbench");
  });

  it("keeps compare when two platforms exist and fills both", () => {
    const state = normaliseState(catalog, { goal: "compare" });
    expect(state.goal).toBe("compare");
    expect(state.platformA).toBeDefined();
    expect(state.platformB).toBeDefined();
    expect(state.platformA).not.toBe(state.platformB);
    expect(state.platform).toBeUndefined();
  });

  it("keeps platform choices inside the filtered pool", () => {
    const state = normaliseState(catalog, { deployment: "managed", platform: "duckdb" });
    const pool = platformsForFilters(catalog, state.interface, state.deployment).map((p) => p.id);
    expect(pool).toContain(state.platform);
  });
});

describe("url state", () => {
  it("round trips selector values", () => {
    const state = stateFromSearch("?goal=compare&scale=0.1&junk=1&surface=");
    expect(state).toEqual({ goal: "compare", scale: "0.1" });
    expect(searchFromState(state)).toBe("goal=compare&scale=0.1");
  });
});

describe("buildOutput", () => {
  it("renders the default local quickstart", () => {
    const output = buildOutput(catalog, normaliseState(catalog, {}));
    expect(output.prompt).toContain("Goal: run TPC-H on");
    expect(output.prompt).toContain("benchbox run --platform duckdb --benchmark tpch --scale 0.01");
    expect(output.showMcpSetup).toBe(false);
    expect(output.safety).toEqual([]);
  });

  it("renders the MCP workflow with its setup block", () => {
    const output = buildOutput(catalog, normaliseState(catalog, { surface: "mcp" }));
    expect(output.showMcpSetup).toBe(true);
    expect(output.prompt).toContain("Use the BenchBox MCP server to run");
    expect(output.mcpSetup).toContain("[mcp_servers.benchbox]");
  });

  it("lists credential safety for managed paid platforms", () => {
    const state = normaliseState(catalog, { deployment: "managed", platform: "snowflake", scale: "1.0" });
    const output = buildOutput(catalog, state);
    expect(output.safety.length).toBeGreaterThan(0);
    expect(output.prompt).toContain("COST ACKNOWLEDGMENT");
    expect(output.prompt).toContain("SMOKE");
  });

  it("renders two platform flags when comparing", () => {
    const output = buildOutput(catalog, normaliseState(catalog, { goal: "compare" }));
    expect(output.prompt).toContain("Goal: compare");
    expect(output.prompt).toContain("-vs-");
  });
});
