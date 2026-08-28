import { describe, expect, it } from "vitest";
import { formatQueryCell, formatQueryColumnLabel } from "@/lib/queryLabels";

describe("query label metric formatting", () => {
  it("labels metric direction explicitly", () => {
    expect(formatQueryColumnLabel("power_score")).toBe("Power score (higher is better)");
    expect(formatQueryColumnLabel("display_geomean_ms")).toBe("Display geomean (lower is better)");
  });

  it("formats semantic metric cells without changing missing-state copy", () => {
    expect(formatQueryCell("power_score", 3000.42)).toBe("3,000");
    expect(formatQueryCell("display_geomean_ms", 999.4)).toBe("999 ms");
    expect(formatQueryCell("display_geomean_ms", 1200)).toBe("1.2 s");
    expect(formatQueryCell("total_duration_s", 0.0049)).toBe("0.0049 s");
    expect(formatQueryCell("total_duration_s", 12.345)).toBe("12.35 s");
    expect(formatQueryCell("normalized_cost_usd", 0.0049)).toBe("$0.0049");
    expect(formatQueryCell("power_score", null)).toBe("No power score");
    expect(formatQueryCell("display_geomean_ms", null)).toBe("No timing recorded");
  });

  it("keeps raw plain numeric columns readable without adding false units", () => {
    expect(formatQueryCell("query_count", 22)).toBe("22");
    expect(formatQueryCell("scale_factor", 0.01)).toBe("SF 0.01");
  });
});
