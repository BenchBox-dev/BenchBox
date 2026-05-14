/**
 * Tests for chartTheme.ts.
 *
 * Cases:
 *   (a) PALETTE has 4 distinct colors
 *   (b) paletteColor(i) wraps correctly for i >= PALETTE.length
 *   (c) No exports collide with each other (all values are defined)
 */

import { describe, it, expect } from "vitest";
import {
  PALETTE,
  FASTER_FILL,
  SLOWER_FILL,
  DIVERGING_MAX_PCT,
  paletteColor,
  TIME_SERIES_PALETTE,
  timeSeriesColor,
  HEAT_MIN_RATIO,
  HEAT_MAX_RATIO,
  SPEEDUP_LOG2_MIN,
  SPEEDUP_LOG2_MAX,
  SPEEDUP_LOG2_RANGE,
  SPEEDUP_GRID_STOPS,
  PHASE_COLORS,
} from "@/lib/chartTheme";

describe("chartTheme", () => {
  it("PALETTE has 4 distinct colors", () => {
    expect(PALETTE.length).toBe(4);
    expect(new Set(PALETTE).size).toBe(4);
  });

  it("paletteColor(i) returns PALETTE[i] for i < 4", () => {
    for (let i = 0; i < PALETTE.length; i++) {
      expect(paletteColor(i)).toBe(PALETTE[i]);
    }
  });

  it("paletteColor wraps with modulo for i >= 4", () => {
    expect(paletteColor(4)).toBe(PALETTE[0]);
    expect(paletteColor(7)).toBe(PALETTE[3]);
    expect(paletteColor(8)).toBe(PALETTE[0]);
  });

  it("paletteColor never returns undefined", () => {
    for (let i = 0; i < 20; i++) {
      expect(paletteColor(i)).toBeTruthy();
    }
  });

  it("FASTER_FILL and SLOWER_FILL are distinct", () => {
    expect(FASTER_FILL).not.toBe(SLOWER_FILL);
  });

  it("DIVERGING_MAX_PCT is a positive number", () => {
    expect(DIVERGING_MAX_PCT).toBeGreaterThan(0);
  });

  // -----------------------------------------------------------------------
  // TIME_SERIES_PALETTE / timeSeriesColor
  // -----------------------------------------------------------------------

  it("TIME_SERIES_PALETTE has 8 distinct colors", () => {
    expect(TIME_SERIES_PALETTE.length).toBe(8);
    expect(new Set(TIME_SERIES_PALETTE).size).toBe(8);
  });

  it("timeSeriesColor wraps with modulo", () => {
    for (let i = 0; i < TIME_SERIES_PALETTE.length; i++) {
      expect(timeSeriesColor(i)).toBe(TIME_SERIES_PALETTE[i]);
    }
    expect(timeSeriesColor(TIME_SERIES_PALETTE.length)).toBe(TIME_SERIES_PALETTE[0]);
  });

  it("timeSeriesColor never returns undefined", () => {
    for (let i = 0; i < 20; i++) {
      expect(timeSeriesColor(i)).toBeTruthy();
    }
  });

  // -----------------------------------------------------------------------
  // HEAT_MIN_RATIO / HEAT_MAX_RATIO
  // -----------------------------------------------------------------------

  it("HEAT_MIN_RATIO is 1 (fastest anchor)", () => {
    expect(HEAT_MIN_RATIO).toBe(1);
  });

  it("HEAT_MAX_RATIO is 10 (slowest clamp)", () => {
    expect(HEAT_MAX_RATIO).toBe(10);
  });

  it("HEAT_MIN_RATIO < HEAT_MAX_RATIO", () => {
    expect(HEAT_MIN_RATIO).toBeLessThan(HEAT_MAX_RATIO);
  });

  // -----------------------------------------------------------------------
  // SPEEDUP_LOG2_* constants
  // -----------------------------------------------------------------------

  it("SPEEDUP_LOG2_RANGE equals MAX minus MIN", () => {
    expect(SPEEDUP_LOG2_RANGE).toBeCloseTo(SPEEDUP_LOG2_MAX - SPEEDUP_LOG2_MIN, 10);
  });

  it("SPEEDUP_LOG2_MIN < 0 (scales below 1× are valid)", () => {
    expect(SPEEDUP_LOG2_MIN).toBeLessThan(0);
  });

  it("SPEEDUP_LOG2_MAX > 0 (scales above 1× are valid)", () => {
    expect(SPEEDUP_LOG2_MAX).toBeGreaterThan(0);
  });

  it("SPEEDUP_GRID_STOPS are all positive numbers", () => {
    for (const stop of SPEEDUP_GRID_STOPS) {
      expect(stop).toBeGreaterThan(0);
    }
  });

  // -----------------------------------------------------------------------
  // PHASE_COLORS
  // -----------------------------------------------------------------------

  it("PHASE_COLORS covers the 6 canonical phase names", () => {
    const phases = ["data_generation", "schema_creation", "data_loading", "validation", "power_test", "throughput_test"];
    for (const phase of phases) {
      expect(PHASE_COLORS[phase]).toBeTruthy();
    }
  });

  it("PHASE_COLORS values are distinct CSS variable tokens", () => {
    const values = Object.values(PHASE_COLORS);
    expect(new Set(values).size).toBe(values.length);
    for (const v of values) {
      expect(v).toMatch(/^var\(--bb-chart-[a-z0-9-]+\)$/);
    }
  });
});
