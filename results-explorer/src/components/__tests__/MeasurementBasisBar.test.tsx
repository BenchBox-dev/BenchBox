/**
 * The shared measurement-basis bar.
 *
 * One bar for the whole comparison is the visible form of the model's central
 * invariant: every run is read through the same basis. These tests pin the two
 * behaviours w2 calls out specifically -- the lock affordance, and the
 * collapsed statistic rendering as its own branch rather than a disabled
 * control that could fail open.
 */

import { render, screen } from "@testing-library/preact";
import { describe, expect, it, vi } from "vitest";

import { MeasurementBasisBar } from "@/components/MeasurementBasisBar";
import { ALL_WARM, DEFAULT_BASIS, WARMUP, warmPass, type MeasurementBasis } from "@/lib/measurementBasis";

const PASSES = [ALL_WARM, WARMUP, warmPass(1), warmPass(2), warmPass(3)];

function renderBar(overrides: Partial<Parameters<typeof MeasurementBasisBar>[0]> = {}) {
  const onBasisChange = vi.fn();
  render(
    <MeasurementBasisBar
      basis={DEFAULT_BASIS}
      onBasisChange={onBasisChange}
      availablePasses={PASSES}
      comparableQueryCount={22}
      totalQueryCount={22}
      runCount={2}
      statisticCollapsed={false}
      {...overrides}
    />,
  );
  return { onBasisChange };
}

describe("the shared basis lock", () => {
  it("states that the basis is shared across the comparison's runs", () => {
    renderBar({ runCount: 2 });
    expect(screen.getByText("Shared across 2 runs")).toBeTruthy();
  });

  it("names what is measured and over how many comparable queries", () => {
    renderBar({ comparableQueryCount: 22, totalQueryCount: 22 });
    expect(screen.getByText(/over 22 of 22 queries every selected run can answer/)).toBeTruthy();
    expect(screen.getByText(/wall-clock totals and phase durations remain run-wide context/)).toBeTruthy();
  });

  it("says why queries were excluded when the shared set is smaller", () => {
    // The count alone is not enough: a reader seeing 102 of 103 needs to know
    // the missing query left EVERY run's geomean, not just the one that could
    // not answer it.
    renderBar({ comparableQueryCount: 102, totalQueryCount: 103 });
    expect(screen.getByText(/1 query is excluded from every run/)).toBeTruthy();
  });

  it("pluralises the exclusion sentence", () => {
    renderBar({ comparableQueryCount: 100, totalQueryCount: 103 });
    expect(screen.getByText(/3 queries are excluded from every run/)).toBeTruthy();
  });
});

describe("the statistic control", () => {
  it("offers median and fastest when the selection yields several executions", () => {
    renderBar({ statisticCollapsed: false });
    expect(screen.getByLabelText("Measurement statistic")).toBeTruthy();
    expect(screen.queryByTestId("statistic-locked")).toBeNull();
  });

  it("renders a locked display, not a control, when the statistic collapses", () => {
    // w2 is explicit: not a `disabled` attribute computed from a boolean. A
    // disabled select still renders as a control, and a truthiness bug would
    // leave it interactive while presenting a choice the data cannot express.
    // Asserting the control is ABSENT is what makes that unable to fail open.
    renderBar({ statisticCollapsed: true });
    expect(screen.queryByLabelText("Measurement statistic")).toBeNull();
    expect(screen.getByTestId("statistic-locked")).toBeTruthy();
  });

  it("says why the statistic is locked", () => {
    renderBar({ statisticCollapsed: true });
    expect(screen.getByText(/median and fastest are the same over one execution/)).toBeTruthy();
  });

  it("keeps the pass control usable while the statistic is locked", () => {
    // Collapsing the statistic must not disable the whole bar: changing the
    // pass selection is exactly how a reader escapes the collapsed state.
    renderBar({ statisticCollapsed: true });
    expect(screen.getByLabelText("Measurement passes")).toBeTruthy();
  });
});

describe("basis changes", () => {
  it("keeps the statistic when only the pass selection changes", () => {
    const minBasis: MeasurementBasis = { passes: ALL_WARM, statistic: "min" };
    const { onBasisChange } = renderBar({ basis: minBasis });
    const select = screen.getByLabelText("Measurement passes") as HTMLSelectElement;
    select.value = "warm_pass_2";
    select.dispatchEvent(new Event("change", { bubbles: true }));
    expect(onBasisChange).toHaveBeenCalledWith({ passes: warmPass(2), statistic: "min" });
  });

  it("keeps the pass selection when only the statistic changes", () => {
    const { onBasisChange } = renderBar({ basis: { passes: warmPass(3), statistic: "median" } });
    const select = screen.getByLabelText("Measurement statistic") as HTMLSelectElement;
    select.value = "min";
    select.dispatchEvent(new Event("change", { bubbles: true }));
    expect(onBasisChange).toHaveBeenCalledWith({ passes: warmPass(3), statistic: "min" });
  });

  it("only offers pass selections the runs can serve", () => {
    renderBar({ availablePasses: [ALL_WARM, WARMUP] });
    const select = screen.getByLabelText("Measurement passes") as HTMLSelectElement;
    const values = Array.from(select.options).map((o) => o.value);
    expect(values).toEqual(["default", "warmup"]);
  });
});
