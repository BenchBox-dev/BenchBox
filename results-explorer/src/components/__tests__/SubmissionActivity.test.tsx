/**
 * Submission activity: the corpus index pages listed counts without ever
 * showing whether a subject is still receiving runs. These tests pin the
 * claims the chart makes - weekly buckets, ordered by submissions in the
 * window, counting only runs that fall inside it.
 */

import { render, screen, within } from "@testing-library/preact";
import { describe, it, expect } from "vitest";

import { SubmissionActivity } from "@/components/SubmissionActivity";

const REFERENCE = new Date("2026-09-08T00:00:00Z");

function rowLabels(): string[] {
  const grid = screen.getByTestId("submission-activity-grid");
  return Array.from(grid.querySelectorAll("th[scope='row']")).map((cell) => cell.textContent ?? "");
}

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
});
