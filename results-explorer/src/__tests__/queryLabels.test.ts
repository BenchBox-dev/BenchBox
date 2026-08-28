import { describe, expect, it } from "vitest";
import { queryDisplayLabel, sortQueryIds } from "@/lib/queryLabels";

describe("query labels", () => {
  it("sorts query IDs naturally without stripping benchmark-specific prefixes", () => {
    expect(sortQueryIds(["Q10", "Q2", "Q1", "query_001", "q03"])).toStrictEqual([
      "Q1",
      "Q2",
      "q03",
      "Q10",
      "query_001",
    ]);
  });

  it("keeps the original query label for display", () => {
    expect(queryDisplayLabel("Q1")).toBe("Q1");
    expect(queryDisplayLabel("q01")).toBe("q01");
    expect(queryDisplayLabel("query_001")).toBe("query_001");
  });

  it("deduplicates duplicate query IDs so callers can use them as React keys", () => {
    // Defensive contract: RankTable, QueryHeatmap, and QueryHistogram all
    // iterate this output as React keys. A duplicate would collide.
    expect(sortQueryIds(["Q3", "Q1", "Q1", "Q2", "Q3", "Q1"])).toStrictEqual([
      "Q1",
      "Q2",
      "Q3",
    ]);
  });

  it("returns an empty array for empty input", () => {
    expect(sortQueryIds([])).toStrictEqual([]);
  });
});
