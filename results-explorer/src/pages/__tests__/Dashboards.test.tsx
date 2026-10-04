import { fireEvent, render, screen, within } from "@testing-library/preact";
import { beforeEach, describe, expect, it } from "vitest";
import { Dashboards } from "@/pages/Dashboards";
import { createDashboard, addChartView } from "@/lib/dashboards";

function mockStorage() {
  const storage = new Map<string, string>();
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => {
        storage.set(key, value);
      },
      removeItem: (key: string) => {
        storage.delete(key);
      },
      clear: () => storage.clear(),
    },
  });
}

describe("Dashboards page", () => {
  beforeEach(() => {
    mockStorage();
    window.history.replaceState(null, "", "/results/dashboards/");
  });

  it("renders the empty state with creation", () => {
    render(<Dashboards />);

    expect(screen.getByText("No dashboards yet")).toBeTruthy();
    fireEvent.input(screen.getByLabelText("New dashboard name"), { target: { value: "Weekly review" } });
    fireEvent.click(screen.getByRole("button", { name: "New dashboard" }));

    expect(screen.getByRole("button", { name: /Weekly review \(0\)/ })).toBeTruthy();
  });

  it("lists saved views with working open links and removal", () => {
    const dashboard = createDashboard("Board")!;
    addChartView(dashboard.id, {
      name: "TPC-H matrix",
      url: "/results/tpch/?chart=query_heatmap#benchmark-section-matrix",
      chartId: "query_heatmap",
    });
    window.history.replaceState(null, "", `/results/dashboards/?dashboard=${dashboard.id}`);

    render(<Dashboards />);

    const detail = screen.getByTestId("dashboard-detail");
    expect(within(detail).getByRole("link", { name: "TPC-H matrix" })).toHaveAttribute(
      "href",
      "/results/tpch/?chart=query_heatmap#benchmark-section-matrix",
    );
    fireEvent.click(within(detail).getByRole("button", { name: "Remove" }));
    expect(within(detail).getByText(/Nothing saved here yet/)).toBeTruthy();
  });

  it("renames dashboards and views", () => {
    const dashboard = createDashboard("Board")!;
    addChartView(dashboard.id, { name: "Old view", url: "/results/", chartId: null });
    window.history.replaceState(null, "", `/results/dashboards/?dashboard=${dashboard.id}`);

    render(<Dashboards />);

    const detail = screen.getByTestId("dashboard-detail");
    // First Rename button is the dashboard rename; per-view Renames follow.
    fireEvent.click(within(detail).getAllByRole("button", { name: "Rename" })[0]!);
    fireEvent.input(screen.getByLabelText("Dashboard name"), { target: { value: "Renamed board" } });
    fireEvent.click(within(detail).getAllByRole("button", { name: "Rename" })[0]!);
    expect(within(detail).getByRole("heading", { name: "Renamed board" })).toBeTruthy();

    fireEvent.click(within(detail).getAllByRole("button", { name: "Rename" })[1]!);
    fireEvent.input(screen.getByLabelText("Saved view name"), { target: { value: "New view" } });
    // The view confirm is now second: the dashboard Rename button precedes it.
    fireEvent.click(within(detail).getAllByRole("button", { name: "Rename" })[1]!);
    expect(within(detail).getByRole("link", { name: "New view" })).toBeTruthy();
  });

  it("deletes dashboards", () => {
    const dashboard = createDashboard("Board")!;
    window.history.replaceState(null, "", `/results/dashboards/?dashboard=${dashboard.id}`);

    render(<Dashboards />);

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(screen.getByText("No dashboards yet")).toBeTruthy();
  });
});
