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
});
