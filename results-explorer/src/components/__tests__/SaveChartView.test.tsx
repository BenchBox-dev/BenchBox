import { fireEvent, render, screen } from "@testing-library/preact";
import { beforeEach, describe, expect, it } from "vitest";
import { SaveChartView } from "@/components/SaveChartView";
import { createDashboard, loadDashboards } from "@/lib/dashboards";

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

describe("SaveChartView", () => {
  beforeEach(() => {
    mockStorage();
    window.history.replaceState(null, "", "/results/tpch/?chart=query_heatmap");
  });

  it("saves the current view url into a new dashboard", () => {
    render(<SaveChartView chartId="query_heatmap" chartTitle="Query matrix" anchorId="benchmark-section-matrix" />);

    fireEvent.change(screen.getByLabelText("Dashboard to save this chart view into"), {
      target: { value: "__new__" },
    });
    fireEvent.input(screen.getByLabelText("New dashboard name"), { target: { value: "Weekly review" } });
    fireEvent.click(screen.getByRole("button", { name: "Save view" }));

    expect(screen.getByRole("button", { name: "Saved ✓" })).toBeTruthy();
    const dashboards = loadDashboards();
    expect(dashboards).toHaveLength(1);
    expect(dashboards[0]?.items).toHaveLength(1);
    expect(dashboards[0]?.items[0]?.url).toBe("/results/tpch/?chart=query_heatmap#benchmark-section-matrix");
    expect(dashboards[0]?.items[0]?.chartId).toBe("query_heatmap");
  });

  it("saves into an existing dashboard", () => {
    const dashboard = createDashboard("Board")!;

    render(<SaveChartView chartId="rank_table" chartTitle="Query ranks" />);

    fireEvent.change(screen.getByLabelText("Dashboard to save this chart view into"), {
      target: { value: dashboard.id },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save view" }));

    expect(loadDashboards()[0]?.items).toHaveLength(1);
  });

  it("stays disabled until a target dashboard is chosen", () => {
    render(<SaveChartView chartId="rank_table" chartTitle="Query ranks" />);

    expect(screen.getByRole("button", { name: "Save view" })).toHaveProperty("disabled", true);
  });
});
