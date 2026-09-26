import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  addChartView,
  createDashboard,
  deleteDashboard,
  loadDashboards,
  parseDashboardsPayload,
  removeChartView,
  renameChartView,
  renameDashboard,
} from "@/lib/dashboards";

function seed(payload: unknown): void {
  window.localStorage.setItem("bb.dashboards.v1", JSON.stringify(payload));
}

describe("parseDashboardsPayload", () => {
  it("returns empty for non-arrays and corrupt entries", () => {
    expect(parseDashboardsPayload(null)).toEqual([]);
    expect(parseDashboardsPayload({})).toEqual([]);
    expect(parseDashboardsPayload("nope")).toEqual([]);
    expect(parseDashboardsPayload([null, 42, "x", { version: 999 }])).toEqual([]);
  });

  it("keeps valid dashboards and drops corrupt items entry-wise", () => {
    const parsed = parseDashboardsPayload([
      {
        version: 1,
        id: "dashboard-1",
        name: "Weekly review",
        createdAt: "2026-09-01T00:00:00.000Z",
        updatedAt: "2026-09-02T00:00:00.000Z",
        items: [
          { id: "view-1", name: "TPC-H matrix", url: "/results/tpch/#matrix", chartId: "query_heatmap", savedAt: "2026-09-02T00:00:00.000Z" },
          { id: "bad", name: "", url: "not-a-path" },
          null,
        ],
      },
      { version: 1, id: "dashboard-2", name: "  " },
    ]);
    expect(parsed).toHaveLength(1);
    expect(parsed[0]?.name).toBe("Weekly review");
    expect(parsed[0]?.items).toHaveLength(1);
    expect(parsed[0]?.items[0]?.url).toBe("/results/tpch/#matrix");
  });

  it("rejects future model versions", () => {
    expect(parseDashboardsPayload([{ version: 2, id: "d", name: "Future" }])).toEqual([]);
  });
});

describe("dashboard store", () => {
  beforeEach(() => {
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
  });

  it("loads empty when nothing is stored", () => {
    expect(loadDashboards()).toEqual([]);
  });

  it("creates dashboards with trimmed names and rejects blanks", () => {
    expect(createDashboard("   ")).toBeNull();
    const dashboard = createDashboard("  Weekly review  ");
    expect(dashboard?.name).toBe("Weekly review");
    expect(dashboard?.items).toEqual([]);
    expect(loadDashboards()).toHaveLength(1);
  });

  it("renames and deletes dashboards", () => {
    const dashboard = createDashboard("Old")!;
    expect(renameDashboard(dashboard.id, "   ")).toHaveLength(1);
    const renamed = renameDashboard(dashboard.id, "New");
    expect(renamed[0]?.name).toBe("New");
    expect(deleteDashboard(dashboard.id)).toEqual([]);
  });

  it("adds, renames, and removes chart views", () => {
    const dashboard = createDashboard("Board")!;
    const afterAdd = addChartView(dashboard.id, {
      name: "TPC-H matrix",
      url: "/results/tpch/?chart=query_heatmap#benchmark-section-matrix",
      chartId: "query_heatmap",
    });
    expect(afterAdd[0]?.items).toHaveLength(1);
    const viewId = afterAdd[0]!.items[0]!.id;
    const blankRename = renameChartView(dashboard.id, viewId, "  ");
    expect(blankRename[0]?.items[0]?.name).toBe("TPC-H matrix");
    const renamed = renameChartView(dashboard.id, viewId, "Matrix, power scale");
    expect(renamed[0]?.items[0]?.name).toBe("Matrix, power scale");
    expect(removeChartView(dashboard.id, viewId)[0]?.items).toEqual([]);
  });

  it("rejects views with blank names or non-path urls", () => {
    const dashboard = createDashboard("Board")!;
    expect(addChartView(dashboard.id, { name: "  ", url: "/results/" })[0]?.items).toEqual([]);
    expect(addChartView(dashboard.id, { name: "X", url: "https://evil.example/" })[0]?.items).toEqual([]);
  });

  it("ignores unknown dashboard ids", () => {
    createDashboard("Board");
    expect(addChartView("missing", { name: "X", url: "/results/" })).toHaveLength(1);
    expect(deleteDashboard("missing")).toHaveLength(1);
  });

  it("survives corrupt storage", () => {
    window.localStorage.setItem("bb.dashboards.v1", "{not json");
    expect(loadDashboards()).toEqual([]);
    seed([{ version: 1, id: "d", name: "Kept", items: [{ id: "v", name: "V", url: "/results/" }] }]);
    expect(loadDashboards()).toHaveLength(1);
  });

  it("keeps saved dashboards in memory when storage writes throw", async () => {
    vi.resetModules();
    const storage = await import("@/lib/dashboards");
    const failingStorage = {
      getItem: () => null,
      setItem: () => {
        throw new Error("quota exceeded");
      },
      removeItem: () => {},
      clear: () => {},
    };
    Object.defineProperty(window, "localStorage", { configurable: true, value: failingStorage });

    const dashboard = storage.createDashboard("Session board")!;
    expect(dashboard.name).toBe("Session board");
    const loaded = storage.loadDashboards();
    expect(loaded).toHaveLength(1);
    expect(loaded[0]?.name).toBe("Session board");

    const afterAdd = storage.addChartView(dashboard.id, { name: "Matrix", url: "/results/tpch/#matrix" });
    expect(afterAdd[0]?.items).toHaveLength(1);
    expect(storage.loadDashboards()[0]?.items).toHaveLength(1);
  });
});
