export const CHART_COMPACT_BELOW = 480;

export const CHART_MIN_WIDTH = 240;

export interface ChartFrame {
  readonly width: number;
  readonly compact: boolean;
}

export function chartFrame(
  containerWidth: number,
  options: { compactBelow?: number; minWidth?: number } = {},
): ChartFrame {
  const minWidth = options.minWidth ?? CHART_MIN_WIDTH;
  const compactBelow = options.compactBelow ?? CHART_COMPACT_BELOW;
  const measured = Number.isFinite(containerWidth) && containerWidth > 0 ? containerWidth : minWidth;
  return {
    width: Math.max(Math.round(measured), minWidth),
    compact: measured < compactBelow,
  };
}

export interface BarRowLayout {
  readonly labelWidth: number;
  readonly rowHeight: number;
  readonly plotX: number;
  readonly plotWidth: number;
  readonly labelAbove: boolean;
  readonly labelBaseline: number;
  readonly barCenter: number;
  readonly compactTicks: boolean;
}

const LABEL_LINE_H = 18;

export function barRowLayout(
  frame: ChartFrame,
  spec: { labelWidth: number; rowHeight: number; valueTrail: number },
): BarRowLayout {
  if (frame.compact) {
    const rowHeight = spec.rowHeight + LABEL_LINE_H;
    return {
      labelWidth: 0,
      rowHeight,
      plotX: 0,
      plotWidth: frame.width,
      labelAbove: true,
      labelBaseline: 12,
      barCenter: LABEL_LINE_H + spec.rowHeight * 0.5,
      compactTicks: true,
    };
  }
  return {
    labelWidth: spec.labelWidth,
    rowHeight: spec.rowHeight,
    plotX: spec.labelWidth,
    plotWidth: Math.max(1, frame.width - spec.labelWidth - spec.valueTrail),
    labelAbove: false,
    labelBaseline: spec.rowHeight * 0.5 + 4,
    barCenter: spec.rowHeight * 0.5,
    compactTicks: false,
  };
}

export function axisLabelAnchor(x: number, width: number, inset = 24): "start" | "middle" | "end" {
  if (x <= inset) return "start";
  if (x >= width - inset) return "end";
  return "middle";
}

export interface EdgeSafeLabel {
  readonly x: number;
  readonly textAnchor: "start" | "end";
}

export function edgeSafeValueLabel(
  x: number,
  width: number,
  direction: "right" | "left",
  gap = 2,
  inset = 34,
): EdgeSafeLabel {
  if (direction === "right") {
    return x + gap > width - inset
      ? { x: Math.min(x - gap, width), textAnchor: "end" }
      : { x: x + gap, textAnchor: "start" };
  }
  return x - gap < inset
    ? { x: Math.max(x + gap, 0), textAnchor: "start" }
    : { x: x - gap, textAnchor: "end" };
}
