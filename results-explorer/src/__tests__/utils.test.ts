import { describe, expect, it } from "vitest";
import { fmtScore, fmtScoreCompact, fmtScoreExact, isKnownBenchmark } from "@/utils";

describe("isKnownBenchmark", () => {
  it("matches only explicit benchmark labels", () => {
    expect(isKnownBenchmark("tpch")).toBe(true);
    expect(isKnownBenchmark("flightdata")).toBe(true);
    expect(isKnownBenchmark("tsbs_devops")).toBe(true);
    expect(isKnownBenchmark("toString")).toBe(false);
    expect(isKnownBenchmark("does-not-exist")).toBe(false);
  });
});

describe("score formatting", () => {
  it("uses compact power scores for dense shared displays", () => {
    expect(fmtScore(3000.42)).toBe("3,000");
    expect(fmtScore(1520.99)).toBe("1,521");
  });

  it("removes noisy decimals from large power scores for compact displays", () => {
    expect(fmtScoreCompact(3000.42)).toBe("3,000");
    expect(fmtScoreCompact(1520.99)).toBe("1,521");
  });

  it("keeps exact score text available for tooltips and details", () => {
    expect(fmtScoreExact(3000.42)).toBe("3,000.42");
  });
});
