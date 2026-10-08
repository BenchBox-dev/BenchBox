export interface SavedChartView {
  id: string;
  name: string;
  url: string;
  chartId: string | null;
  savedAt: string;
}

export interface Dashboard {
  id: string;
  name: string;
  createdAt: string;
  updatedAt: string;
  items: SavedChartView[];
}

export const DASHBOARD_MODEL_VERSION = 1;
const DASHBOARD_STORAGE_KEY = "bb.dashboards.v1";
const DASHBOARD_ID_PREFIX = "dashboard-";
const VIEW_ID_PREFIX = "view-";

function newId(prefix: string): string {
  const random = Math.floor(Math.random() * 0xffffff).toString(16).padStart(6, "0");
  return `${prefix}${Date.now().toString(36)}-${random}`;
}

function nowIso(): string {
  return new Date().toISOString();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asNonEmptyString(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

function asStringOrNull(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  return typeof value === "string" ? value : null;
}

export function isInternalExplorerPath(url: string): boolean {
  if (!url.startsWith("/") || url.startsWith("//") || url.startsWith("/\\")) return false;
  try {
    const parsed = new URL(url, "https://explorer.internal");
    return parsed.origin === "https://explorer.internal" && parsed.pathname.startsWith("/");
  } catch {
    return false;
  }
}

function parseSavedView(raw: unknown): SavedChartView | null {
  if (!isRecord(raw)) return null;
  const id = asNonEmptyString(raw.id);
  const name = asNonEmptyString(raw.name);
  const url = asNonEmptyString(raw.url);
  if (id === null || name === null || url === null) return null;
  if (!isInternalExplorerPath(url)) return null;
  const chartId = asStringOrNull(raw.chartId);
  const savedAt = asNonEmptyString(raw.savedAt) ?? nowIso();
  return { id, name, url, chartId, savedAt };
}

function parseDashboard(raw: unknown): Dashboard | null {
  if (!isRecord(raw)) return null;
  if (raw.version !== DASHBOARD_MODEL_VERSION) return null;
  const id = asNonEmptyString(raw.id);
  const name = asNonEmptyString(raw.name);
  if (id === null || name === null) return null;
  const createdAt = asNonEmptyString(raw.createdAt) ?? nowIso();
  const updatedAt = asNonEmptyString(raw.updatedAt) ?? createdAt;
  const items: SavedChartView[] = [];
  if (Array.isArray(raw.items)) {
    for (const item of raw.items) {
      const view = parseSavedView(item);
      if (view !== null) items.push(view);
    }
  }
  return { id, name, createdAt, updatedAt, items };
}

export function parseDashboardsPayload(raw: unknown): Dashboard[] {
  if (!Array.isArray(raw)) return [];
  const dashboards: Dashboard[] = [];
  for (const entry of raw) {
    const dashboard = parseDashboard(entry);
    if (dashboard !== null) dashboards.push(dashboard);
  }
  return dashboards;
}

let memoryDashboards: Dashboard[] | null = null;

let memoryTombstones: Set<string> = new Set();

function cloneDashboards(dashboards: Dashboard[]): Dashboard[] {
  return dashboards.map((dashboard) => ({ ...dashboard, items: dashboard.items.map((item) => ({ ...item })) }));
}

function readStorage(): Dashboard[] {
  let stored: Dashboard[];
  try {
    if (typeof window === "undefined") return [];
    const storage = window.localStorage;
    if (!storage) return [];
    const raw = storage.getItem(DASHBOARD_STORAGE_KEY);
    if (raw === null || raw === "") stored = [];
    else stored = parseDashboardsPayload(JSON.parse(raw));
  } catch {
    stored = [];
  }
  if (memoryDashboards === null) return stored.filter((dashboard) => !memoryTombstones.has(dashboard.id));
  const memoryIds = new Set(memoryDashboards.map((dashboard) => dashboard.id));
  return [
    ...cloneDashboards(memoryDashboards),
    ...stored.filter((dashboard) => !memoryIds.has(dashboard.id) && !memoryTombstones.has(dashboard.id)),
  ];
}

function writeStorage(dashboards: Dashboard[]): void {
  if (typeof window !== "undefined") {
    try {
      const storage = window.localStorage;
      if (storage) {
        const payload = dashboards.map((dashboard) => ({ ...dashboard, version: DASHBOARD_MODEL_VERSION }));
        storage.setItem(DASHBOARD_STORAGE_KEY, JSON.stringify(payload));
        memoryDashboards = null;
        memoryTombstones = new Set();
        return;
      }
    } catch {
    }
  }
  if (typeof window !== "undefined") {
    if (memoryDashboards !== null) {
      const nextIds = new Set(dashboards.map((dashboard) => dashboard.id));
      for (const dashboard of memoryDashboards) {
        if (!nextIds.has(dashboard.id)) memoryTombstones.add(dashboard.id);
      }
    }
    memoryDashboards = cloneDashboards(dashboards);
  }
}

export function loadDashboards(): Dashboard[] {
  return readStorage();
}

export function createDashboard(name: string): Dashboard | null {
  const trimmed = name.trim();
  if (trimmed === "") return null;
  const timestamp = nowIso();
  const dashboard: Dashboard = {
    id: newId(DASHBOARD_ID_PREFIX),
    name: trimmed,
    createdAt: timestamp,
    updatedAt: timestamp,
    items: [],
  };
  writeStorage([...readStorage(), dashboard]);
  return dashboard;
}

export function renameDashboard(id: string, name: string): Dashboard[] {
  const trimmed = name.trim();
  if (trimmed === "") return readStorage();
  const next = readStorage().map((dashboard) =>
    dashboard.id === id ? { ...dashboard, name: trimmed, updatedAt: nowIso() } : dashboard,
  );
  writeStorage(next);
  return next;
}

export function deleteDashboard(id: string): Dashboard[] {
  const next = readStorage().filter((dashboard) => dashboard.id !== id);
  writeStorage(next);
  if (memoryDashboards !== null) memoryTombstones.add(id);
  return next;
}

export function addChartView(
  dashboardId: string,
  view: { name: string; url: string; chartId?: string | null },
): Dashboard[] {
  const name = view.name.trim();
  if (name === "" || !isInternalExplorerPath(view.url)) return readStorage();
  const next = readStorage().map((dashboard) =>
    dashboard.id === dashboardId
      ? {
          ...dashboard,
          updatedAt: nowIso(),
          items: [
            ...dashboard.items,
            {
              id: newId(VIEW_ID_PREFIX),
              name,
              url: view.url,
              chartId: view.chartId ?? null,
              savedAt: nowIso(),
            },
          ],
        }
      : dashboard,
  );
  writeStorage(next);
  return next;
}

export function renameChartView(dashboardId: string, viewId: string, name: string): Dashboard[] {
  const trimmed = name.trim();
  if (trimmed === "") return readStorage();
  const next = readStorage().map((dashboard) =>
    dashboard.id === dashboardId
      ? {
          ...dashboard,
          updatedAt: nowIso(),
          items: dashboard.items.map((item) => (item.id === viewId ? { ...item, name: trimmed } : item)),
        }
      : dashboard,
  );
  writeStorage(next);
  return next;
}

export function removeChartView(dashboardId: string, viewId: string): Dashboard[] {
  const next = readStorage().map((dashboard) =>
    dashboard.id === dashboardId
      ? { ...dashboard, updatedAt: nowIso(), items: dashboard.items.filter((item) => item.id !== viewId) }
      : dashboard,
  );
  writeStorage(next);
  return next;
}
