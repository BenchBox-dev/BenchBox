import { describe, expect, it } from "vitest";
import {
  buildLatencyBarScale,
  latencyScaleFraction,
  latencyScaleTicks,
} from "@/lib/chartMath";

describe("latency bar scale", () => {
  it("keeps compact latency ranges on a zero-based linear scale", () => {
    const scale = buildLatencyBarScale([10, 20, 40]);

    expect(scale?.mode).toBe("linear");
    expect(scale?.domainMin).toBe(0);
    expect(scale?.domainMax).toBe(40);
    expect(latencyScaleFraction(20, scale!)).toBe(0.5);
    expect(latencyScaleTicks(scale!)).toStrictEqual([0, 10, 20, 30, 40]);
  });

  it("switches to log scale when a slow outlier spans an order of magnitude", () => {
    const scale = buildLatencyBarScale([10, 100, 1000]);

    expect(scale?.mode).toBe("log");
    expect(scale?.spanRatio).toBe(100);
    expect(latencyScaleTicks(scale!)).toStrictEqual([10, 100, 1000]);

    const fast = latencyScaleFraction(10, scale!);
    const middle = latencyScaleFraction(100, scale!);
    const slow = latencyScaleFraction(1000, scale!);

    expect(fast).toBeGreaterThan(0);
    expect(middle).toBeGreaterThan(fast!);
    expect(middle).toBeLessThan(slow!);
    expect(slow).toBe(1);
  });

  it("keeps sub-millisecond values visible on log scale", () => {
    const scale = buildLatencyBarScale([0.01, 1]);

    expect(scale?.mode).toBe("log");
    expect(latencyScaleFraction(0.01, scale!)).toBeGreaterThan(0);
    expect(latencyScaleFraction(1, scale!)).toBe(1);
  });

  it("ignores null, zero, and non-finite inputs when choosing a scale", () => {
    const scale = buildLatencyBarScale([null, 0, Number.POSITIVE_INFINITY, 25]);

    expect(scale).toMatchObject({
      mode: "linear",
      min: 25,
      max: 25,
      domainMin: 0,
      domainMax: 25,
      spanRatio: 1,
    });
  });
});
