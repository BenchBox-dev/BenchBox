/**
 * Submission activity: the corpus index pages listed counts without ever
 * showing whether a subject is still receiving runs. These tests pin the
 * claims the chart makes - weekly buckets, ordered by submissions in the
 * window, counting only runs that fall inside it.
 */

import { act, render, screen, within } from "@testing-library/preact";
import { afterEach, describe, it, expect, vi } from "vitest";

import { SubmissionActivity } from "@/components/SubmissionActivity";

const REFERENCE = new Date("2026-09-08T00:00:00Z");

it("exposes weekly values without hover", () => {
  render(<SubmissionActivity rows={[{ id: "tpch", label: "TPC-H", href: "/results/tpch/", dates: ["2026-09-08"] }]} subject="benchmark" reference={REFERENCE} />);
  expect(screen.getByRole("cell", { name: "TPC-H: 1 run in the week of 2026-09-07" })).toBeTruthy();
});

function rowLabels(): string[] {
  const grid = screen.getByTestId("submission-activity-grid");
  return Array.from(grid.querySelectorAll("th[scope='row']")).map((cell) => cell.textContent ?? "");
}

/** Stub `window.matchMedia` so the component reads a fixed narrow/wide viewport. */
function stubViewport(matches: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches,
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
    })),
  );
}

/**
 * Stub `window.matchMedia` with a fake MediaQueryList whose `matches` can be
 * flipped after render, firing every registered "change" listener - the path
 * a real viewport resize takes. `stubViewport` above cannot exercise this: its
 * `addEventListener` is a no-op, so a component that dropped its subscription
 * entirely would still pass every test that only calls `stubViewport` once.
 */
function stubResizableViewport(initialMatches: boolean) {
  let matches = initialMatches;
  const listeners = new Set<() => void>();
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      get matches() {
        return matches;
      },
      media: query,
      addEventListener: (_type: string, listener: () => void) => listeners.add(listener),
      removeEventListener: (_type: string, listener: () => void) => listeners.delete(listener),
    })),
  );
  return {
    change(next: boolean) {
      matches = next;
      for (const listener of listeners) listener();
    },
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SubmissionActivity", () => {
  const rows = [
    { id: "tpch", label: "TPC-H", href: "/results/tpch/", dates: ["2026-09-01", "2026-09-02", "2026-08-20"] },
    { id: "ssb", label: "SSB", href: "/results/ssb/", dates: ["2026-08-20"] },
  ];

  it("orders subjects by submissions inside the window", () => {
    render(<SubmissionActivity rows={rows} subject="benchmark" reference={REFERENCE} />);
    expect(rowLabels()).toEqual(["TPC-H", "SSB"]);
  });

  it("counts runs per subject and links each row to its page", () => {
    render(<SubmissionActivity rows={rows} subject="benchmark" reference={REFERENCE} />);
    const grid = screen.getByTestId("submission-activity-grid");
    const firstRow = grid.querySelector("tbody tr")!;
    expect(within(firstRow as HTMLElement).getByRole("link", { name: "TPC-H" })).toHaveAttribute(
      "href",
      "/results/tpch/",
    );
    expect((firstRow.lastElementChild as HTMLElement).textContent).toBe("3");
  });

  it("drops subjects whose runs all fall outside the window", () => {
    render(
      <SubmissionActivity
        rows={[...rows, { id: "old", label: "Ancient", href: "/results/old/", dates: ["2020-01-01"] }]}
        subject="benchmark"
        reference={REFERENCE}
      />,
    );
    expect(rowLabels()).not.toContain("Ancient");
  });

  it("anchors the window to the newest submission when the corpus is stale", () => {
    // Every run predates the 26-week window ending today. Anchoring to today
    // would drop all of them and render nothing, hiding a corpus that was
    // active in the past - the one case this chart most needs to show.
    render(
      <SubmissionActivity
        rows={[{ id: "tpch", label: "TPC-H", href: "/results/tpch/", dates: ["2024-03-04", "2024-03-11"] }]}
        subject="benchmark"
        reference={REFERENCE}
      />,
    );
    expect(rowLabels()).toEqual(["TPC-H"]);
  });

  it("renders nothing when no run carries a usable date", () => {
    const { container } = render(
      <SubmissionActivity
        rows={[{ id: "x", label: "X", href: "/x", dates: ["not-a-date"] }]}
        subject="benchmark"
        reference={REFERENCE}
      />,
    );
    expect(container.textContent).toBe("");
  });

  it("collapses the long tail into a count rather than a hundred rows", () => {
    const many = Array.from({ length: 25 }, (_, index) => ({
      id: `p${index}`,
      label: `Platform ${index}`,
      href: `/results/p/${index}/`,
      dates: ["2026-09-01"],
    }));
    render(<SubmissionActivity rows={many} subject="platform" reference={REFERENCE} maxRows={20} />);
    expect(rowLabels()).toHaveLength(20);
    expect(screen.getByText("5 less active platforms not shown.")).toBeTruthy();
  });

  it("narrows the week window below the sm breakpoint so every cell stays on screen", () => {
    stubViewport(true);
    const rows = [
      { id: "tpch", label: "TPC-H", href: "/results/tpch/", dates: ["2026-09-01", "2026-08-20"] },
    ];
    render(<SubmissionActivity rows={rows} subject="benchmark" reference={REFERENCE} />);

    // The caption always states the 26-week total window - it must agree with
    // the row totals, which are always 26-week sums - and separately discloses
    // that only the trailing 10 columns are rendered here.
    expect(screen.getByText(/Runs per week over the last 26 weeks/)).toBeTruthy();
    expect(screen.getByText(/Showing the trailing 10 of 26 weeks; totals cover all 26/)).toBeTruthy();
    const grid = screen.getByTestId("submission-activity-grid");
    const firstDataRow = within(grid).getAllByRole("row")[0]!;
    // One label cell + N week cells + one total cell.
    expect(firstDataRow.children).toHaveLength(12);
  });

  it("uses the full desktop week window when the viewport is not narrow", () => {
    stubViewport(false);
    const rows = [
      { id: "tpch", label: "TPC-H", href: "/results/tpch/", dates: ["2026-09-01", "2026-08-20"] },
    ];
    render(<SubmissionActivity rows={rows} subject="benchmark" reference={REFERENCE} />);

    expect(screen.getByText(/Runs per week over the last 26 weeks/)).toBeTruthy();
    expect(screen.queryByText(/Showing the trailing/)).toBeNull();
    const grid = screen.getByTestId("submission-activity-grid");
    const firstDataRow = within(grid).getAllByRole("row")[0]!;
    expect(firstDataRow.children).toHaveLength(28);
  });

  it("keeps a subject last active between the mobile and desktop windows visible at both widths", () => {
    // 15 weeks back: inside the 26-week desktop window, outside the 10-week
    // mobile one. A window narrowed for mobile would drop this row there
    // with nothing on screen to say so; cropping which columns render must not.
    const oldDate = new Date(REFERENCE.getTime() - 15 * 7 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
    const rows = [
      { id: "tpch", label: "TPC-H", href: "/results/tpch/", dates: ["2026-09-01"] },
      { id: "old", label: "Old Platform", href: "/results/old/", dates: [oldDate] },
    ];

    stubViewport(false);
    const desktop = render(<SubmissionActivity rows={rows} subject="platform" reference={REFERENCE} />);
    expect(rowLabels()).toEqual(["Old Platform", "TPC-H"]);
    // "Old Platform" is the row this test is about: its only run sorts first
    // (tied inWindow counts break alphabetically), so it's row 0.
    const desktopTotal = within(screen.getByTestId("submission-activity-grid"))
      .getAllByRole("row")[0]!.lastElementChild!.textContent;
    desktop.unmount();

    stubViewport(true);
    render(<SubmissionActivity rows={rows} subject="platform" reference={REFERENCE} />);
    expect(rowLabels()).toEqual(["Old Platform", "TPC-H"]);
    const mobileTotal = within(screen.getByTestId("submission-activity-grid"))
      .getAllByRole("row")[0]!.lastElementChild!.textContent;

    // Row order and each row's total are viewport-independent; only the
    // number of rendered week columns differs. The caption's stated window
    // (26 weeks) matches this total at both sizes - only the rendered slice
    // is smaller on mobile, and that crop is disclosed separately.
    expect(mobileTotal).toBe(desktopTotal);
  });

  it("re-renders with the other window when matchMedia reports a viewport change", () => {
    const viewport = stubResizableViewport(false);
    const rows = [{ id: "tpch", label: "TPC-H", href: "/results/tpch/", dates: ["2026-09-01", "2026-08-20"] }];
    render(<SubmissionActivity rows={rows} subject="benchmark" reference={REFERENCE} />);

    expect(screen.getByText(/Runs per week over the last 26 weeks/)).toBeTruthy();
    let grid = screen.getByTestId("submission-activity-grid");
    expect(within(grid).getAllByRole("row")[0]!.children).toHaveLength(28);

    act(() => viewport.change(true));

    expect(screen.getByText(/Runs per week over the last 26 weeks/)).toBeTruthy();
    expect(screen.getByText(/Showing the trailing 10 of 26 weeks; totals cover all 26/)).toBeTruthy();
    grid = screen.getByTestId("submission-activity-grid");
    expect(within(grid).getAllByRole("row")[0]!.children).toHaveLength(12);
  });
});
