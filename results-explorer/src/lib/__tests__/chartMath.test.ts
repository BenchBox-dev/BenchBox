/**
 * Log latency axis ticks.
 *
 * The axis has to carry enough labels to be read. Whole decades are the
 * coarsest set that usually does; a range that sits inside one decade needs
 * finer rungs, and a very narrow range needs its own endpoints.
 */

import { describe, it, expect } from "vitest";
import { buildLogLatencyScale, logLatencyTicks, logLatencyFraction } from "@/lib/chartMath";
import { formatLatencyAxisLabels } from "@/lib/metricFormatters";

describe("logLatencyTicks", () => {
  it("uses whole decades when the range spans several", () => {
    const scale = buildLogLatencyScale([0.5, 5000])!;
    expect(logLatencyTicks(scale)).toEqual([1, 10, 100, 1000]);
  });

  it("subdivides a range that falls inside one decade rather than labelling it once", () => {
    // The motivating case: a run whose queries all land between 22 ms and
    // 55 ms used to render an axis carrying the single label "10 ms".
    const scale = buildLogLatencyScale([22, 55], { lowerPad: 0.2, upperPad: 0.2 })!;
    const ticks = logLatencyTicks(scale);
    expect(ticks.length).toBeGreaterThanOrEqual(3);
    // Every tick sits inside the plotted domain, and they bracket the data.
    expect(Math.min(...ticks)).toBeLessThanOrEqual(22);
    expect(Math.max(...ticks)).toBeGreaterThanOrEqual(40);
    expect(Math.max(...ticks)).toBeLessThanOrEqual(2 ** scale.logMax);
  });

  it("labels the ends when no standard rung falls inside a very narrow range", () => {
    const scale = buildLogLatencyScale([11, 13])!;
    const ticks = logLatencyTicks(scale);
    expect(ticks.length).toBeGreaterThanOrEqual(2);
    expect(ticks[0]).toBeLessThanOrEqual(11);
    expect(ticks[ticks.length - 1]!).toBeGreaterThanOrEqual(13);
  });

  it("never crowds the axis with more labels than it can show", () => {
    const scale = buildLogLatencyScale([1.2, 90])!;
    expect(logLatencyTicks(scale).length).toBeLessThanOrEqual(8);
  });

  it("densifies a narrow padded range instead of stopping short of the axis end", () => {
    // Audit finding: queries spanning 10-15 ms, padded to an ~8-18 ms domain,
    // used to label only "10 ms" and "15 ms" - the fixed mantissa grid
    // (1, 1.5, 2, 3, 5, 7 x each decade) happens to land on those two values
    // and nothing closer to the 18 ms axis end, leaving the top third of the
    // axis unlabeled even though the plotted line extends well past 15 ms.
    const scale = buildLogLatencyScale([10, 15], { lowerPad: 0.3, upperPad: 0.3 })!;
    const ticks = logLatencyTicks(scale);
    expect(ticks.length).toBeGreaterThanOrEqual(4);
    const domainMax = 2 ** scale.logMax;
    expect(Math.max(...ticks)).toBeGreaterThan(15);
    expect(Math.max(...ticks)).toBeLessThanOrEqual(domainMax);
  });

  it("does not repeat the same rendered label across the linear-fallback ticks", () => {
    for (const domain of [[10, 10.9], [0.55, 0.95], [11.1, 11.2], [1100, 1101]] as const) {
      const scale = buildLogLatencyScale(domain, { lowerPad: 0, upperPad: 0 })!;
      const ticks = logLatencyTicks(scale, 0);
      const labels = formatLatencyAxisLabels(ticks);
      expect(labels.length).toBeGreaterThanOrEqual(2);
      expect(new Set(labels).size).toBe(labels.length);
    }
  });
});

it("keeps tick coordinates distinct and inside subfloor and narrow domains", () => {
  for (const values of [[0.01, 0.03], [11.1, 11.2], [0.09, 0.11]]) {
    const scale = buildLogLatencyScale(values)!;
    const ticks = logLatencyTicks(scale, 0);
    const positions = ticks.map((tick) => logLatencyFraction(tick, scale));
    expect(new Set(positions).size).toBe(positions.length);
    expect(ticks.every((tick) => tick >= scale.floorMs)).toBe(true);
    expect(positions.every((position) => position >= -1e-10 && position <= 1 + 1e-10)).toBe(true);
  }
});
