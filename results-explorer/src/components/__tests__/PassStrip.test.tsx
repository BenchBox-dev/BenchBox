/**
 * The per-query pass view.
 *
 * Every figure is computed from the run's own executions and captioned with
 * the reduction it performed, so nothing here can disagree with the executions
 * displayed beside it.
 */

import { render, screen } from "@testing-library/preact";
import { describe, expect, it } from "vitest";

import { PassStrip, hasNoRecordedWarmup, summarizeQueryPasses } from "@/components/PassStrip";
import type { QueryTiming } from "@/types";

const exec = (
  query_id: string,
  duration_ms: number,
  run_type: string | null,
  iter: number | null,
  status: "pass" | "fail" = "pass",
): QueryTiming => ({ query_id, duration_ms, status, run_type, iter, stream: null });

describe("summarizeQueryPasses", () => {
  it("reduces warm passes with a true median, matching the published contract", () => {
    const s = summarizeQueryPasses([
      exec("Q1", 10, "measurement", 1),
      exec("Q1", 30, "measurement", 2),
      exec("Q1", 20, "measurement", 3),
    ])[0]!;
    expect(s.warmMedian).toBe(20);
    expect(s.warmMin).toBe(10);
    expect(s.spreadMs).toBe(20);
  });

  it("takes a true median for an even sample, not the upper middle", () => {
    const s = summarizeQueryPasses([
      exec("Q1", 10, "measurement", 1),
      exec("Q1", 20, "measurement", 2),
    ])[0]!;
    expect(s.warmMedian).toBe(15);
  });

  it("excludes failed executions from every warm figure", () => {
    // A failed execution is not a measurement. Including it would let a fast
    // failure look like a fast query.
    const s = summarizeQueryPasses([
      exec("Q1", 10, "measurement", 1),
      exec("Q1", 1, "measurement", 2, "fail"),
      exec("Q1", 20, "measurement", 3),
    ])[0]!;
    expect(s.warmValues).toEqual([10, 20]);
    expect(s.warmMin).toBe(10);
  });

  it("excludes the warmup pass from the warm reduction", () => {
    const s = summarizeQueryPasses([
      exec("Q1", 100, "warmup", 0),
      exec("Q1", 10, "measurement", 1),
      exec("Q1", 20, "measurement", 2),
    ])[0]!;
    expect(s.warmMedian).toBe(15);
    expect(s.warmupMs).toBe(100);
  });

  it("computes the warmup ratio against the warm median", () => {
    const s = summarizeQueryPasses([
      exec("Q1", 30, "warmup", 0),
      exec("Q1", 10, "measurement", 1),
      exec("Q1", 20, "measurement", 2),
    ])[0]!;
    expect(s.warmupRatio).toBe(2);
  });

  it("reports the warmup ratio as absent, never estimated, with no warmup", () => {
    // w0 measured a corpus p50 of 1.01x, so 1.0 would be a plausible-looking
    // default -- which is exactly why it must not be one. A run with no warmup
    // has no penalty to report.
    const s = summarizeQueryPasses([exec("Q1", 10, "measurement", 1)])[0]!;
    expect(s.warmupMs).toBeNull();
    expect(s.warmupRatio).toBeNull();
  });

  it("has no spread for a single warm pass", () => {
    const s = summarizeQueryPasses([exec("Q1", 10, "measurement", 1)])[0]!;
    expect(s.spreadMs).toBeNull();
  });

  it("treats unlabelled legacy executions as warm, matching the pipeline", () => {
    const s = summarizeQueryPasses([exec("Q1", 10, null, null), exec("Q1", 20, null, null)])[0]!;
    expect(s.warmMedian).toBe(15);
  });

  it("orders queries numerically, so Q2 precedes Q10", () => {
    const out = summarizeQueryPasses([
      exec("10", 1, "measurement", 1),
      exec("2", 1, "measurement", 1),
    ]);
    expect(out.map((s) => s.queryId)).toEqual(["2", "10"]);
  });
});

describe("rendering", () => {
  const withWarmup = [
    exec("Q1", 30, "warmup", 0),
    exec("Q1", 10, "measurement", 1),
    exec("Q1", 20, "measurement", 2),
  ];

  it("names the reduction it performed rather than promising a penalty", () => {
    // The corpus p50 warmup ratio is 1.01x. A caption promising a penalty
    // would leave a reader thinking a 1.00x column was broken.
    render(<PassStrip queries={withWarmup} />);
    expect(screen.getByText(/median of this run's passing measurement passes/)).toBeTruthy();
  });

  it("states how many of how many queries are shown", () => {
    render(<PassStrip queries={withWarmup} />);
    expect(screen.getByText(/Showing 1 of 1 query/)).toBeTruthy();
  });

  it("says a run recorded no warmup rather than showing a blank column", () => {
    render(<PassStrip queries={[exec("Q1", 10, "measurement", 1)]} />);
    expect(screen.getByTestId("no-warmup-note").textContent).toContain("absent, not zero");
  });

  it("omits the no-warmup note when warmup exists", () => {
    render(<PassStrip queries={withWarmup} />);
    expect(screen.queryByTestId("no-warmup-note")).toBeNull();
  });

  it("renders an em dash, not a number, for an absent warmup ratio", () => {
    render(<PassStrip queries={[exec("Q1", 10, "measurement", 1)]} />);
    expect(screen.getByTestId("warmup-ratio-Q1").textContent).toBe("—");
  });

  it("renders nothing when the run has no executions", () => {
    const { container } = render(<PassStrip queries={[]} />);
    expect(container.textContent).toBe("");
  });
});

describe("hasNoRecordedWarmup", () => {
  it("is true only when no query recorded one", () => {
    expect(hasNoRecordedWarmup(summarizeQueryPasses([exec("Q1", 10, "measurement", 1)]))).toBe(true);
    expect(
      hasNoRecordedWarmup(
        summarizeQueryPasses([exec("Q1", 30, "warmup", 0), exec("Q1", 10, "measurement", 1)]),
      ),
    ).toBe(false);
  });
});
