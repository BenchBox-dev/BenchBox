/**
 * Tests for the shared Analysis card grid shell (AnalysisCardGrid + AnalysisCard):
 * the expandable card used by the benchmark page's "More views" grid and the
 * platform page's "Analysis" grid alike.
 */

import { render, screen, fireEvent } from "@testing-library/preact";
import { useState } from "preact/hooks";
import { describe, it, expect } from "vitest";

import { AnalysisCard, AnalysisCardGrid } from "@/components/AnalysisCardGrid";

function Harness({ isOpen: initialOpen = false, anchorId }: { isOpen?: boolean; anchorId?: string }) {
  const [isOpen, setIsOpen] = useState(initialOpen);
  return (
    <AnalysisCardGrid headingId="test-grid-title" count="1 card">
      <AnalysisCard
        id="widget"
        anchorId={anchorId}
        title="Widget"
        isOpen={isOpen}
        onToggle={setIsOpen}
        renderThumbnail={() => <p data-testid="widget-thumbnail">thumbnail</p>}
        renderFull={() => <p data-testid="widget-full">full content</p>}
      />
    </AnalysisCardGrid>
  );
}

describe("AnalysisCardGrid / AnalysisCard", () => {
  it("shows the thumbnail while closed and the full view once opened, never both", () => {
    render(<Harness />);
    const details = screen.getByTestId("summary-chart-preview-widget") as HTMLDetailsElement;
    expect(screen.getByTestId("widget-thumbnail")).toBeTruthy();
    expect(screen.queryByTestId("widget-full")).toBeNull();
    expect(screen.getByText("Open full chart ↗")).toBeTruthy();

    details.open = true;
    fireEvent(details, new Event("toggle"));

    expect(screen.queryByTestId("widget-thumbnail")).toBeNull();
    expect(screen.getByTestId("widget-full")).toBeTruthy();
    expect(screen.getByText("Close full chart")).toBeTruthy();
  });

  it("spans the full grid width only while open", () => {
    render(<Harness />);
    const details = screen.getByTestId("summary-chart-preview-widget") as HTMLDetailsElement;
    expect(details.className).not.toContain("sm:col-span-2 xl:col-span-4");

    details.open = true;
    fireEvent(details, new Event("toggle"));

    expect(details.className).toContain("sm:col-span-2 xl:col-span-4");
  });

  it("renders forced-open with the anchor id set for deep-link scrolling", () => {
    render(<Harness isOpen anchorId="deep-link-anchor" />);
    const details = screen.getByTestId("summary-chart-preview-widget") as HTMLDetailsElement;
    expect(details.open).toBe(true);
    expect(details.id).toBe("deep-link-anchor");
    expect(screen.getByTestId("widget-full")).toBeTruthy();
  });

  it("renders the section heading, count, and description", () => {
    render(
      <AnalysisCardGrid headingId="grid-title" title="More views" count="3 additional analyses" description="Some copy.">
        <p>child</p>
      </AnalysisCardGrid>,
    );
    expect(screen.getByRole("heading", { name: "More views" })).toBeTruthy();
    expect(screen.getByText("3 additional analyses")).toBeTruthy();
    expect(screen.getByText("Some copy.")).toBeTruthy();
  });
});
