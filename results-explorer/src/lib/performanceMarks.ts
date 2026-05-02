export const EXPLORER_PERFORMANCE_MARKS = {
  DB_INIT_START: "db-init-start",
  DB_INIT_READY: "db-init-ready",
  HOME_LEADERBOARD_DATA_START: "home-leaderboard-data-start",
  HOME_LEADERBOARD_DATA_READY: "leaderboard-data-ready",
  LEADERBOARD_RENDERED: "leaderboard-rendered",
} as const;

export const EXPLORER_PERFORMANCE_MEASURES = {
  DB_INIT: "db-init",
  HOME_LEADERBOARD_DATA: "home-leaderboard-data",
  LEADERBOARD_RENDER_AFTER_DATA: "leaderboard-render-after-data",
} as const;

type ExplorerPerformanceMark =
  (typeof EXPLORER_PERFORMANCE_MARKS)[keyof typeof EXPLORER_PERFORMANCE_MARKS];
type ExplorerPerformanceMeasure =
  (typeof EXPLORER_PERFORMANCE_MEASURES)[keyof typeof EXPLORER_PERFORMANCE_MEASURES];

interface MarkOptions {
  once?: boolean;
  detail?: Record<string, unknown>;
}

interface MeasureOptions {
  once?: boolean;
}

const markedOnce = new Set<ExplorerPerformanceMark>();
const measuredOnce = new Set<ExplorerPerformanceMeasure>();

export function markExplorerPerformance(
  name: ExplorerPerformanceMark,
  options: MarkOptions = {},
): PerformanceMark | null {
  const perf = getPerformance();
  if (!perf || typeof perf.mark !== "function") return null;
  if (options.once && markedOnce.has(name)) return null;

  try {
    const mark = perf.mark(name, options.detail === undefined ? undefined : { detail: options.detail });
    if (options.once) markedOnce.add(name);
    logExplorerPerformance("mark", name, mark.startTime);
    return mark;
  } catch {
    return null;
  }
}

export function measureExplorerPerformance(
  name: ExplorerPerformanceMeasure,
  startMark: ExplorerPerformanceMark,
  endMark: ExplorerPerformanceMark,
  options: MeasureOptions = {},
): PerformanceMeasure | null {
  const perf = getPerformance();
  if (!perf || typeof perf.measure !== "function" || typeof perf.getEntriesByName !== "function") {
    return null;
  }
  if (options.once && measuredOnce.has(name)) return null;
  if (!hasMark(perf, startMark) || !hasMark(perf, endMark)) return null;

  try {
    const measure = perf.measure(name, startMark, endMark);
    if (options.once) measuredOnce.add(name);
    logExplorerPerformance("measure", name, measure.duration);
    return measure;
  } catch {
    return null;
  }
}

export function clearExplorerPerformanceEntriesForTests(): void {
  const perf = getPerformance();
  markedOnce.clear();
  measuredOnce.clear();
  if (!perf) return;
  for (const mark of Object.values(EXPLORER_PERFORMANCE_MARKS)) {
    perf.clearMarks?.(mark);
  }
  for (const measure of Object.values(EXPLORER_PERFORMANCE_MEASURES)) {
    perf.clearMeasures?.(measure);
  }
}

function hasMark(perf: Performance, mark: ExplorerPerformanceMark): boolean {
  return perf.getEntriesByName(mark, "mark").length > 0;
}

function getPerformance(): Performance | null {
  return typeof globalThis.performance === "undefined" ? null : globalThis.performance;
}

function logExplorerPerformance(kind: "mark" | "measure", name: string, valueMs: number): void {
  if (!isPerformanceLoggingEnabled()) return;
  globalThis.console?.debug?.(`[BenchBox perf] ${kind} ${name}: ${valueMs.toFixed(1)} ms`);
}

function isPerformanceLoggingEnabled(): boolean {
  if (import.meta.env.DEV && import.meta.env.MODE !== "test") return true;
  const win = typeof window === "undefined" ? null : window;
  if (!win) return false;

  try {
    if (new URLSearchParams(win.location.search).get("bb_perf") === "1") return true;
    return win.localStorage?.getItem("benchbox:perf-debug") === "1";
  } catch {
    return false;
  }
}
