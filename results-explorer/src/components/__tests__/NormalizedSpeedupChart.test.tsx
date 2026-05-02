/**
 * Tests for NormalizedSpeedupChart component.
 *
 * Cases:
 *   (a) Renders without error for valid 2-platform input
 *   (b) Returns null when fewer than 2 results or no queries
 *   (c) viewBox width tracks container offsetWidth (responsive layout)
 *   (d) Null timing entries render em-dash placeholder
 */

import { render, screen, waitFor } from "@testing-library/preact";
import { describe, it, expect, afterEach } from "vitest";
import { NormalizedSpeedupChart } from "@/components/NormalizedSpeedupChart";

const QUERIES = [
  {
    queryId: "Q1",
    timings: [
      { ms: 100, status: "pass" },
      { ms: 200, status: "pass" },
    ],
  },
  {
    queryId: "Q2",
    timings: [
      { ms: 50, status: "pass" },
      { ms: 400, status: "pass" },
    ],
  },
];
const RESULTS = [{ platform: "DuckDB" }, { platform: "SQLite" }];

describe("NormalizedSpeedupChart", () => {
  it("renders platform baseline label", () => {
    render(<NormalizedSpeedupChart queries={QUERIES} results={RESULTS} baselineIdx={0} />);
    expect(screen.getByText(/Baseline/)).toBeTruthy();
    expect(screen.getByText("DuckDB")).toBeTruthy();
  });

  it("returns null for single result", () => {
    const { container } = render(
      <NormalizedSpeedupChart queries={QUERIES} results={[{ platform: "DuckDB" }]} baselineIdx={0} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("returns null for empty queries", () => {
    const { container } = render(<NormalizedSpeedupChart queries={[]} results={RESULTS} baselineIdx={0} />);
    expect(container.firstChild).toBeNull();
  });

  // -----------------------------------------------------------------------
  // (c) viewBox width tracks container offsetWidth
  // -----------------------------------------------------------------------

  afterEach(() => {
    // Restore offsetWidth after any test that overrides it
    Object.defineProperty(HTMLElement.prototype, "offsetWidth", {
      configurable: true,
      get: () => 0,
    });
  });

  it.each([400, 800, 1200])("SVG viewBox width matches container offsetWidth at %spx", async (testWidth) => {
    Object.defineProperty(HTMLElement.prototype, "offsetWidth", {
      configurable: true,
      get: () => testWidth,
    });

    const { container } = render(<NormalizedSpeedupChart queries={QUERIES} results={RESULTS} baselineIdx={0} />);

    // useElementSize reads offsetWidth in a useEffect; wait for the re-render
    await waitFor(() => {
      const svg = container.querySelector("svg");
      const viewBox = svg?.getAttribute("viewBox") ?? "";
      expect(viewBox).toMatch(new RegExp(`^0 0 ${testWidth} `));
    });
  });

  // -----------------------------------------------------------------------
  // (d) Null timing entries render em-dash
  // -----------------------------------------------------------------------

  it("null timing entry renders em-dash placeholder", () => {
    const queriesWithNull = [{ queryId: "Q1", timings: [{ ms: 100, status: "pass" }, null] }];
    render(<NormalizedSpeedupChart queries={queriesWithNull} results={RESULTS} baselineIdx={0} />);
    // em-dash rendered for the null timing slot
    expect(screen.getByText("-")).toBeTruthy();
  });

  // -----------------------------------------------------------------------
  // Duplicate-queryId guard (blind-spot
  //   _project/blind-spots/2026-04-29-143205-react-key-collision-class.md)
  //
  // The `queries` prop is not deduped at the boundary, so a caller passing
  // variant rows for the same queryId could collide on key={queryId}. The
  // composite key `${queryId}-${rowIdx}` keeps reconciliation stable.
  // -----------------------------------------------------------------------

  it("renders both rows when two queries share the same queryId", () => {
    const queriesWithDuplicate = [
      { queryId: "Q1", timings: [{ ms: 100, status: "pass" }, { ms: 50, status: "pass" }] },
      { queryId: "Q1", timings: [{ ms: 200, status: "pass" }, { ms: 100, status: "pass" }] },
    ];
    const { container } = render(
      <NormalizedSpeedupChart queries={queriesWithDuplicate} results={RESULTS} baselineIdx={0} />,
    );
    // Two distinct row groups should render — both Q1 entries plus the
    // grid axis group. Per-row count: 2 query rows.
    const queryRows = Array.from(container.querySelectorAll("text")).filter(
      (el) => el.textContent === "Q1",
    );
    expect(queryRows.length).toBe(2);
  });
});
