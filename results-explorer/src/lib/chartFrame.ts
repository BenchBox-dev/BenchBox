/**
 * chartFrame - shared sizing contract for the Explorer's SVG charts.
 *
 * A chart draws in a coordinate system whose width equals its measured
 * container width, and publishes that as `width="100%"` plus a matching
 * `viewBox`. Because the viewBox width and the rendered CSS width agree, the
 * user-unit scale is 1 for any container at or above `CHART_MIN_WIDTH`: an
 * 11-unit label is 11 screen pixels, and no part of the drawing falls outside
 * the box. Below that floor the drawing does scale down, so text shrinks with
 * it - a deliberate trade, because the alternative at 120px is a layout with
 * no room for a bar. Scaling keeps the whole chart on screen; cropping did
 * not.
 *
 * The alternative - authoring at a fixed floor and relying on
 * `max-width: 100%` - does not survive a narrow column. Without a viewBox the
 * box shrinks while the coordinate system does not, so the right-hand and
 * bottom edges are never painted; and the wrapping `overflow-x-auto` cannot
 * scroll to them, because the box now fits its parent. Moving the label size
 * from an attribute into CSS does not help either: `font-size` inside an SVG
 * is measured in user units whether it arrives as an attribute or a rule.
 *
 * Row-based charts (one bar per run) therefore reflow below `COMPACT_BELOW`
 * rather than holding a label gutter the column cannot afford: the label moves
 * onto its own line above the bar, the value keeps the opposite end of that
 * line, and the bar spans the full width.
 *
 * Charts too dense to reflow - a per-query histogram, a grouped timing chart -
 * opt out by declaring a `minWidth` and scrolling inside their own container,
 * the contract QueryTimingChart already uses.
 */

/** Container width below which a bar row cannot afford a label gutter. */
export const CHART_COMPACT_BELOW = 480;

/**
 * Floor on the drawing width. Below this the frame does scale down, because a
 * legible layout is no longer available at 1:1 - but it scales rather than
 * crops, so the whole chart stays on screen.
 */
export const CHART_MIN_WIDTH = 240;

export interface ChartFrame {
  /** Drawing width in user units. Equals the container width above the floor. */
  readonly width: number;
  /** True when the container is too narrow for a side label gutter. */
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
  /** Width of the left label gutter. Zero when the label sits above its bar. */
  readonly labelWidth: number;
  /** Height of one row, including the label line when there is one. */
  readonly rowHeight: number;
  /** X origin of the plot area. */
  readonly plotX: number;
  /** Width available to the bar itself. */
  readonly plotWidth: number;
  /** True when the label and value share a line above the bar. */
  readonly labelAbove: boolean;
  /** Baseline offset of the label line, relative to the top of the row. */
  readonly labelBaseline: number;
  /** Vertical centre of the bar, relative to the top of the row. */
  readonly barCenter: number;
  /**
   * True when the axis should carry fewer tick labels. Five labels across a
   * 240-unit axis overlap; three do not.
   */
  readonly compactTicks: boolean;
}

/** Height added to a row when its label moves onto its own line. */
const LABEL_LINE_H = 18;

/**
 * Resolve one bar row's geometry for the current frame.
 *
 * `valueTrail` is the space a wide layout reserves after the bar for its value
 * label. A compact layout does not need it: the value moves to the end of the
 * label line, where it cannot be pushed off the right edge by a long bar.
 */
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

/**
 * Anchor for an axis tick label at `x` on a drawing `width` wide.
 *
 * A centred label on the outermost tick puts half its box outside the drawing,
 * where it is cropped. Tucking the first and last labels inside costs a little
 * precision about where the tick sits and buys a label the reader can read.
 */
export function axisLabelAnchor(x: number, width: number, inset = 24): "start" | "middle" | "end" {
  if (x <= inset) return "start";
  if (x >= width - inset) return "end";
  return "middle";
}

export interface EdgeSafeLabel {
  readonly x: number;
  readonly textAnchor: "start" | "end";
}

/**
 * Place a value label that trails the end of a bar.
 *
 * A bar at its maximum reaches the edge of the plot, and a label started just
 * past it is drawn outside the drawing and cropped. Near either edge the label
 * turns back on itself and sits inside the bar instead, which is always
 * readable even though it costs the small gap.
 *
 * `inset` is the room the label is assumed to need. It is a bound, not a
 * measurement: measuring text means laying it out first, which is the fragile
 * path this file exists to avoid.
 */
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
