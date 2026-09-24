import { describe, it, expect } from "vitest";
import {
  axisLabelAnchor,
  barRowLayout,
  chartFrame,
  CHART_COMPACT_BELOW,
  CHART_MIN_WIDTH,
} from "@/lib/chartFrame";

describe("chartFrame", () => {
  it("draws at the measured container width, so the user-unit scale is 1", () => {
    // A viewBox this wide, published as width="100%" in a container this wide,
    // renders one user unit per CSS pixel: an 11-unit label is 11px on screen.
    expect(chartFrame(1166).width).toBe(1166);
    expect(chartFrame(293).width).toBe(293);
  });

  it("scales rather than crops below the legibility floor", () => {
    expect(chartFrame(120).width).toBe(CHART_MIN_WIDTH);
  });

  it("falls back to the floor when the container has not been measured", () => {
    expect(chartFrame(0).width).toBe(CHART_MIN_WIDTH);
    expect(chartFrame(Number.NaN).width).toBe(CHART_MIN_WIDTH);
  });

  it("reports compact only below the threshold", () => {
    expect(chartFrame(CHART_COMPACT_BELOW - 1).compact).toBe(true);
    expect(chartFrame(CHART_COMPACT_BELOW).compact).toBe(false);
    expect(chartFrame(1166).compact).toBe(false);
  });

  it("honours a caller-supplied floor", () => {
    expect(chartFrame(120, { minWidth: 300 }).width).toBe(300);
  });
});

describe("barRowLayout", () => {
  const spec = { labelWidth: 160, rowHeight: 36, valueTrail: 96 };

  it("keeps a side gutter and a value trail when the column can afford them", () => {
    const layout = barRowLayout(chartFrame(1000), spec);
    expect(layout.labelAbove).toBe(false);
    expect(layout.labelWidth).toBe(160);
    expect(layout.plotX).toBe(160);
    expect(layout.plotWidth).toBe(1000 - 160 - 96);
    expect(layout.rowHeight).toBe(36);
  });

  it("moves the label onto its own line and frees the full width for the bar", () => {
    const layout = barRowLayout(chartFrame(320), spec);
    expect(layout.labelAbove).toBe(true);
    expect(layout.labelWidth).toBe(0);
    expect(layout.plotX).toBe(0);
    expect(layout.plotWidth).toBe(320);
    expect(layout.rowHeight).toBeGreaterThan(36);
  });

  it("keeps the bar inside the row it grew taller for", () => {
    const layout = barRowLayout(chartFrame(320), spec);
    expect(layout.labelBaseline).toBeLessThan(layout.barCenter);
    expect(layout.barCenter).toBeLessThan(layout.rowHeight);
  });

  it("thins the axis when there is no room for five tick labels", () => {
    expect(barRowLayout(chartFrame(320), spec).compactTicks).toBe(true);
    expect(barRowLayout(chartFrame(1000), spec).compactTicks).toBe(false);
  });
});

describe("axisLabelAnchor", () => {
  it("tucks the outermost tick labels inside the drawing", () => {
    // Centred on the last tick, half the label's box sits outside the drawing
    // and is cropped.
    expect(axisLabelAnchor(293, 293)).toBe("end");
    expect(axisLabelAnchor(0, 293)).toBe("start");
  });

  it("leaves interior ticks centred on their mark", () => {
    expect(axisLabelAnchor(150, 293)).toBe("middle");
  });
});
