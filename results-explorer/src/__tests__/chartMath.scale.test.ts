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
    // w15: ticks now always include the domain endpoints so the right edge
    // of the bar chart has a labelled terminal value. The interior canonical
    // powers of ten remain in the middle.
    const ticks = latencyScaleTicks(scale!);
    expect(ticks[0]).toBe(scale!.domainMin);
    expect(ticks[ticks.length - 1]).toBe(scale!.domainMax);
    for (const tick of [10, 100, 1000]) {
      expect(ticks).toContain(tick);
    }

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

  it("includes both endpoints in log-mode ticks for narrow ranges (w15)", () => {
    // 0.2-2 ms: pre-w15 the ticks omitted both endpoints because no
    // canonical power-of-ten falls in the open interval. The right edge
    // of the bar would render against an unlabelled endpoint.
    const scale = buildLatencyBarScale([0.2, 2]);
    expect(scale?.mode).toBe("log");
    const ticks = latencyScaleTicks(scale!);
    expect(ticks[0]).toBe(scale!.domainMin);
    expect(ticks[ticks.length - 1]).toBe(scale!.domainMax);
    // Interior power-of-ten (1 ms) is included between endpoints.
    expect(ticks).toContain(1);
  });

  it("includes both endpoints in log-mode ticks for very wide ranges (w15)", () => {
    // 100k-50M ms: pre-w15 omitted the upper endpoint because no
    // power-of-ten was within ±1% of it.
    const scale = buildLatencyBarScale([100_000, 50_000_000]);
    expect(scale?.mode).toBe("log");
    const ticks = latencyScaleTicks(scale!);
    expect(ticks[0]).toBe(scale!.domainMin);
    expect(ticks[ticks.length - 1]).toBe(scale!.domainMax);
    // At least one interior power of ten is present.
    expect(ticks.some((tick) => tick === 100_000 || tick === 1_000_000 || tick === 10_000_000)).toBe(
      true,
    );
  });

  it("dedupes endpoints against canonical powers-of-ten (w15)", () => {
    // 1-1000 ms: domainMin and domainMax may already equal canonical ticks
    // depending on padding; the dedupe must not produce duplicates.
    const scale = buildLatencyBarScale([1, 1000]);
    expect(scale?.mode).toBe("log");
    const ticks = latencyScaleTicks(scale!);
    expect(ticks[0]).toBe(scale!.domainMin);
    expect(ticks[ticks.length - 1]).toBe(scale!.domainMax);
    expect(new Set(ticks).size).toBe(ticks.length);
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
