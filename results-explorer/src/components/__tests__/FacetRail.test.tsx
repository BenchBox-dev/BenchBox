import { fireEvent, render, screen, within } from "@testing-library/preact";
import { describe, expect, it, vi } from "vitest";
import { FacetDrawer, FacetRail, type FacetGroup } from "@/components/FacetRail";

const GROUPS: FacetGroup[] = [
  {
    key: "benchmark",
    label: "Benchmark",
    selected: ["tpch"],
    options: [
      { value: "tpch", label: "TPC-H", count: 12 },
      { value: "clickbench", label: "ClickBench", count: 4 },
    ],
  },
  {
    key: "platform",
    label: "Platform",
    selected: [],
    searchable: true,
    options: [
      { value: "duckdb", label: "DuckDB", count: 8 },
      { value: "sqlite", label: "SQLite", count: 3 },
    ],
  },
];

describe("FacetRail", () => {
  it("renders active chips, counts, searchable groups, and reset", () => {
    const onToggle = vi.fn();
    const onReset = vi.fn();

    render(
      <FacetRail
        groups={GROUPS}
        resultCount={16}
        activeChips={[{ key: "benchmark:tpch", label: "TPC-H" }]}
        onToggle={onToggle}
        onReset={onReset}
      />,
    );

    expect(screen.getByText("16 matching results")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "TPC-H" }));
    expect(onReset).toHaveBeenCalled();

    const platformSection = screen.getByRole("heading", { name: "Platform" }).closest("section")!;
    fireEvent.input(within(platformSection).getByRole("searchbox"), { target: { value: "duck" } });
    expect(within(platformSection).getByText("DuckDB")).toBeTruthy();
    expect(within(platformSection).queryByText("SQLite")).toBeNull();

    fireEvent.click(within(platformSection).getByRole("checkbox"));
    expect(onToggle).toHaveBeenCalledWith("platform", "duckdb");

    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(onReset).toHaveBeenCalledTimes(2);
  });
});

describe("FacetDrawer", () => {
  it("shows a closed summary and opens the facet dialog", () => {
    const onOpenChange = vi.fn();

    const { rerender } = render(
      <FacetDrawer
        groups={GROUPS}
        resultCount={16}
        activeChips={[{ key: "benchmark:tpch", label: "TPC-H" }]}
        onToggle={vi.fn()}
        onReset={vi.fn()}
        open={false}
        onOpenChange={onOpenChange}
      />,
    );

    const trigger = screen.getByRole("button", { name: /Filters/ });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveAttribute("data-result-count", "16");
    expect(within(trigger).getByText("TPC-H")).toBeTruthy();
    expect(within(trigger).getByText("16 results")).toBeTruthy();
    expect(screen.queryByRole("dialog", { name: "Filter results" })).toBeNull();
    fireEvent.click(trigger);
    expect(onOpenChange).toHaveBeenCalledWith(true);

    rerender(
      <FacetDrawer
        groups={GROUPS}
        resultCount={16}
        activeChips={[{ key: "benchmark:tpch", label: "TPC-H" }]}
        onToggle={vi.fn()}
        onReset={vi.fn()}
        open
        onOpenChange={onOpenChange}
      />,
    );
    const dialog = screen.getByRole("dialog", { name: "Filter results" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAttribute("tabindex", "-1");
    expect(dialog.className).toContain("fixed inset-0");

    dialog.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(screen.getByRole("button", { name: "Done" })).toHaveFocus();

    fireEvent.click(screen.getByRole("button", { name: "Close filters" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
