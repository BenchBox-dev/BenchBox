/**
 * Shared responsive thresholds for SVG charts.
 *
 * Charts use their measured container width rather than the viewport directly
 * because a chart can be rendered in a card, a drawer, or a full-width panel.
 */
export const NARROW_CHART_BREAKPOINT = 520;
export const NARROW_CHART_MIN_WIDTH = 320;

export function isNarrowChart(width: number): boolean {
  return width > 0 && width < NARROW_CHART_BREAKPOINT;
}
