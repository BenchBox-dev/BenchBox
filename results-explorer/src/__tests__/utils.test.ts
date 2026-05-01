import { describe, expect, it } from "vitest";
import { isKnownBenchmark } from "@/utils";

describe("isKnownBenchmark", () => {
  it("matches only explicit benchmark labels", () => {
    expect(isKnownBenchmark("tpch")).toBe(true);
    expect(isKnownBenchmark("flightdata")).toBe(true);
    expect(isKnownBenchmark("tsbs_devops")).toBe(true);
    expect(isKnownBenchmark("toString")).toBe(false);
    expect(isKnownBenchmark("does-not-exist")).toBe(false);
  });
});
