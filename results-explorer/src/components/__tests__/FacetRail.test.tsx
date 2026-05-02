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

const ENVIRONMENT_GROUPS: FacetGroup[] = [
  {
    key: "cloud_provider",
    label: "Cloud provider",
    selected: ["aws"],
    searchable: true,
    options: [
      { value: "aws", label: "aws", count: 7 },
      { value: "gcp", label: "gcp", count: 4 },
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

  it("renders canonical environment facet values with stable display labels", () => {
    const onToggle = vi.fn();

    render(
      <FacetRail
        groups={ENVIRONMENT_GROUPS}
        resultCount={11}
        activeChips={[
          { key: "cloud_provider:gcp", facetKey: "cloud_provider", value: "gcp", label: "gcp" },
        ]}
        onToggle={onToggle}
        onReset={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "GCP" })).toBeTruthy();

    const providerSection = screen.getByRole("heading", { name: "Cloud provider" }).closest("section")!;
    expect(within(providerSection).getByRole("checkbox", { name: "AWS" })).toBeChecked();

    fireEvent.input(within(providerSection).getByRole("searchbox"), { target: { value: "gcp" } });
    fireEvent.click(within(providerSection).getByRole("checkbox", { name: "GCP" }));
    expect(onToggle).toHaveBeenCalledWith("cloud_provider", "gcp");
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

    expect(screen.getByRole("button", { name: /Filters/ })).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("dialog", { name: "Filter results" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Filters/ }));
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
    expect(screen.getByRole("dialog", { name: "Filter results" })).toBeTruthy();
  });
});
