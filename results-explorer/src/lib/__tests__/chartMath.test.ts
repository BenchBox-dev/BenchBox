/**
 * Log latency axis ticks.
 *
 * The axis has to carry enough labels to be read. Whole decades are the
 * coarsest set that usually does; a range that sits inside one decade needs
 * finer rungs, and a very narrow range needs its own endpoints.
 */

import { describe, it, expect } from "vitest";
import { buildLogLatencyScale, logLatencyTicks } from "@/lib/chartMath";

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
});
