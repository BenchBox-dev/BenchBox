import { describe, expect, it } from "vitest";
import { buildOutput, normaliseState, platformsForFilters, type RawState } from "../src/lib/prompt-builder.ts";
import { loadPromptCatalog } from "../src/lib/prompt-catalog.ts";

const catalog = loadPromptCatalog();

function prompt(raw: RawState): string {
  return buildOutput(catalog, normaliseState(catalog, raw)).prompt;
}

const credentialStep = "Make sure platform connection credentials/config are set outside this conversation";
const managedPaid: RawState = { deployment: "managed", platform: "snowflake", scale: "1.0" };
const hinted = catalog.platforms.find((p) => (p.platform_option_hints ?? []).length > 0 && p.deployments.includes("self-hosted"));

describe("agent prompt content", () => {
  const text = prompt({ ...managedPaid });

  it("captures output and summarises results", () => {
    expect(text).toContain("set -o pipefail");
    expect(text).toContain(" 2>&1 | tee ");
    expect(text).toContain("Announce before running");
    expect(text).toContain("SMOKE");
    expect(text).toContain("COST ACKNOWLEDGMENT");
    expect(text).toContain("confirm credit or compute spend");
    expect(text).toContain("Discover & summarize");
    expect(text).toContain("Save provenance");
    expect(text).toContain(catalog.templates.cli.force_datagen_footer);
    expect(text).toContain(catalog.templates.cli.capture_plans_footer);
    expect(text).toContain(catalog.templates.cli.results_paths);
    expect(text).toContain(catalog.templates.cli.show_cli);
  });

  it("checks dependencies and dry runs first", () => {
    expect(text).toContain("Check dependencies:");
    expect(text).toContain("Dry run first:");
    expect(text).toContain("/tmp/benchbox-dryrun-snowflake");
  });

  it("puts the credential step before the smoke step", () => {
    expect(text.indexOf(credentialStep)).toBeGreaterThan(-1);
    expect(text.indexOf(credentialStep)).toBeLessThan(text.indexOf("SMOKE: run the same live command"));
  });

  it("does not introduce an agent identity sentence", () => {
    expect(text).not.toContain("You are a coding agent with shell access");
  });

  it("lists platform option footguns", () => {
    expect(hinted).toBeDefined();
    const out = prompt({ platform: hinted?.id, deployment: "self-hosted" });
    expect(out).toContain("Likely required platform options for");
    expect(out).toContain(hinted?.platform_option_hints?.[0] as string);
  });

  it("compares from the comparison log rather than recent result paths", () => {
    const out = prompt({ goal: "compare" });
    expect(out).toContain("comparison output in");
    expect(out).toContain("Dry run first:");
    const summary = out.slice(out.indexOf("Discover & summarize"), out.indexOf("Save provenance"));
    expect(summary).not.toContain("benchbox results --paths");
    expect(summary).not.toContain(catalog.templates.cli.show_cli);
  });

  it("adds dataframe flags", () => {
    expect(prompt({ interface: "dataframe" })).toContain("--mode dataframe");
    expect(prompt({ interface: "dataframe", goal: "compare" })).toContain("--type dataframe");
  });
});

describe("dsdgen warning", () => {
  it("warns below the bundled threshold for TPC-DS", () => {
    const out = prompt({ benchmark: "tpcds", scale: "0.01" });
    expect(out).toContain("TPC-DS sub-scale warning");
    expect(out).toContain("_binaries/tpc-ds/<os>-<arch>/dsdgen");
    expect(out).toContain("_binaries/tpc-ds/linux-x86_64/dsdgen");
    expect(out).toContain("_binaries/tpc-ds/darwin-arm64/dsdgen");
    expect(out).not.toContain("_binaries/tpc-ds/<platform>/dsdgen");
  });

  it("warns when the injected smoke scale falls below the threshold", () => {
    const out = prompt({ benchmark: "tpcds", scale: "10.0", deployment: "managed", platform: "snowflake" });
    expect(out).toContain("TPC-DS sub-scale warning");
  });

  it("stays quiet for other benchmarks and for large local TPC-DS", () => {
    expect(prompt({ benchmark: "tpch", scale: "0.01" })).not.toContain("TPC-DS sub-scale warning");
    expect(prompt({ benchmark: "tpcds", scale: "10.0" })).not.toContain("TPC-DS sub-scale warning");
  });

  it("appears in the MCP workflow too", () => {
    expect(prompt({ surface: "mcp", benchmark: "tpcds", scale: "0.01" })).toContain("TPC-DS sub-scale warning");
  });
});

describe("mcp prompt content", () => {
  const single = prompt({ ...managedPaid, surface: "mcp" });
  const compare = prompt({ ...managedPaid, surface: "mcp", goal: "compare" });

  it("uses the real analysis, profile and plan tools", () => {
    expect(single).toContain(`${catalog.mcp.analysis_tool || "analyze_results"}(analysis="aggregate", platform="snowflake"`);
    expect(compare).toContain('analysis="compare", file1="<first-result-json>", file2="<second-result-json>"');
    expect(compare).toContain("only the filename component from each live response's `mcp_metadata.result_file`");
    expect(single).toContain(`${catalog.mcp.system_profile_tool || "system_profile"}()`);
    expect(single).toContain(`${catalog.mcp.plan_tool || "get_query_plan"}(result_file="<result-json>", query_id="Q1")`);
    expect(single).toContain("capture_plans=true");
    expect(single).toContain("To capture EXPLAIN plans");
  });

  it("gates smoke and cost steps and puts credentials first", () => {
    for (const out of [single, compare]) {
      expect(out).toContain("SMOKE: call ");
      expect(out).toContain("Abort if");
      expect(out).toContain("COST ACKNOWLEDGMENT");
      expect(out).toContain("target MCP call(s)");
      expect(out.indexOf(credentialStep)).toBeGreaterThan(-1);
      expect(out.indexOf(credentialStep)).toBeLessThan(out.indexOf("SMOKE: call "));
    }
    expect(single).toContain(`${catalog.mcp.run_tool}(platform="snowflake", benchmark="tpch", scale_factor=0.01, dry_run=false)`);
    expect(compare).toContain(" and ");
  });

  it("states the platform option gap instead of inventing an argument", () => {
    const out = prompt({ surface: "mcp", platform: hinted?.id, deployment: "self-hosted" });
    expect(out).toContain("Platform option gap for ");
    expect(out).toContain("MCP `run_benchmark` does not expose platform option arguments yet");
    expect(out).not.toContain("platform_options");
    expect(out).not.toContain("--platform-option");
  });

  it("adds the dataframe mode argument", () => {
    expect(prompt({ surface: "mcp", interface: "dataframe" })).toContain('mode="dataframe"');
  });
});

describe("safety blocks", () => {
  it("lists credential safety only for deployments that need secrets", () => {
    expect(buildOutput(catalog, normaliseState(catalog, managedPaid)).safety.length).toBeGreaterThan(0);
    expect(buildOutput(catalog, normaliseState(catalog, {})).safety).toEqual([]);
  });

  it("keeps dependency and dry-run safety text out of the credential list", () => {
    const state = normaliseState(catalog, managedPaid);
    const out = buildOutput(catalog, state);
    const platform = catalog.platforms.find((p) => p.id === "snowflake");
    expect(out.safety).toEqual([platform?.safety_terms?.no_secrets]);
  });
});

describe("state guards", () => {
  it("falls back from compare when fewer than two platforms qualify", () => {
    const sparse = { ...catalog, platforms: catalog.platforms.filter((p) => p.id === "duckdb") };
    expect(normaliseState(sparse, { goal: "compare" }).goal).toBe(catalog.defaults.goal);
  });

  it("keeps a valid preferred platform and replaces an invalid one", () => {
    expect(normaliseState(catalog, { platform: "sqlite" }).platform).toBe("sqlite");
    expect(normaliseState(catalog, { platform: "not-a-platform" }).platform).toBe(platformsForFilters(catalog, "sql", "local")[0].id);
  });

  it.each([["goal"], ["surface"]] as const)("replaces an unknown %s with the default", (key) => {
    const state = normaliseState(catalog, { [key]: "bogus" });
    expect(state[key]).toBe(catalog.defaults[key]);
  });

  it.each([["interface"], ["deployment"], ["benchmark"], ["scale"]] as const)("recovers from an unknown %s", (key) => {
    const state = normaliseState(catalog, { [key]: "bogus" });
    expect(state).toEqual(normaliseState(catalog, {}));
  });
});
