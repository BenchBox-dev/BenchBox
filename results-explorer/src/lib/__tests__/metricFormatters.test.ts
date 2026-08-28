import { describe, expect, it } from "vitest";
import {
  formatAverageRank,
  formatCoverage,
  formatDurationSeconds,
  formatLatencyMs,
  formatMetricValue,
  formatPowerScore,
  formatPowerScoreExact,
  formatRank,
  formatSpeedup,
  formatUsd,
} from "@/lib/metricFormatters";

describe("metric formatters", () => {
  it("formats large power scores compactly without losing exact tooltip text", () => {
    expect(formatPowerScore(3000.42).valueText).toBe("3,000");
    expect(formatPowerScore(1520.99).valueText).toBe("1,521");
    expect(formatPowerScore(11636.652993864305).valueText).toBe("11,637");
    expect(formatPowerScoreExact(3000.42).valueText).toBe("3,000.42");
    expect(formatPowerScoreExact(11636.652993864305).valueText).toBe("11,636.652993864305");
    expect(formatPowerScore(3000.42).sortValue).toBe(3000.42);
  });

  it("keeps latency in milliseconds below 1000 ms and seconds above the threshold", () => {
    expect(formatLatencyMs(0.42).valueText).toBe("0.4 ms");
    expect(formatLatencyMs(0.42, { subMillisecond: "compact" }).valueText).toBe("<1 ms");
    expect(formatLatencyMs(999.4).valueText).toBe("999 ms");
    expect(formatLatencyMs(1200).valueText).toBe("1.2 s");
  });

  it("formats duration seconds separately from millisecond latency", () => {
    expect(formatDurationSeconds(0.0049).valueText).toBe("0.0049 s");
    expect(formatDurationSeconds(12.345).valueText).toBe("12.35 s");
    expect(formatDurationSeconds(null).valueText).toBe("No duration recorded");
  });

  it("formats speedups, ranks, and coverage with explicit denominators", () => {
    expect(formatSpeedup(1.589).valueText).toBe("1.59x");
    expect(formatSpeedup(1, { unit: "×" }).valueText).toBe("1.00×");
    expect(formatRank(2, 11).valueText).toBe("2/11");
    expect(formatAverageRank(1).valueText).toBe("1.0");
    expect(formatCoverage(3, 5, { unitLabel: "cohorts" }).valueText).toBe("3/5 cohorts");
  });

  it("uses magnitude-aware currency precision", () => {
    expect(formatUsd(12.5).valueText).toBe("$12.50");
    expect(formatUsd(0.0049).valueText).toBe("$0.0049");
    expect(formatUsd(1234.56).valueText).toBe("$1,235");
  });

  it("returns a common contract for semantic formatter dispatch", () => {
    expect(formatMetricValue({ type: "latency_ms", value: 42 }).accessibleText).toBe("42 ms latency");
    expect(formatMetricValue({ type: "rank", rank: null }).sortValue).toBeNull();
  });
});
