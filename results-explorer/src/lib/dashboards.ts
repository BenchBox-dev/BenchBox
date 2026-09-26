// ---------------------------------------------------------------------------
// dashboards - user-saveable chart configurations.
//
// A dashboard is a named collection of saved chart views. Each saved view
// stores the URL that reproduces it (chart selection, sort, filters, and
// deep-link anchor all live in explorer URL state), so dashboards need no
// backend: they persist to localStorage and reopen as plain navigation.
//
// Model versions: payloads carry a `version` field; anything that does not
// validate against the current shape is ignored entry-wise (one corrupt
// dashboard never takes down the rest).
// ---------------------------------------------------------------------------

export interface SavedChartView {
  id: string;
  name: string;
  /** Path + query + hash that reproduces the configured chart view. */
  url: string;
  /** Registry chart id when the view targets one chart card (may be null). */
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

function parseSavedView(raw: unknown): SavedChartView | null {
  if (!isRecord(raw)) return null;
  const id = asNonEmptyString(raw.id);
  const name = asNonEmptyString(raw.name);
  const url = asNonEmptyString(raw.url);
  if (id === null || name === null || url === null) return null;
  if (!url.startsWith("/")) return null;
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

function readStorage(): Dashboard[] {
  try {
    if (typeof window === "undefined" || !window.localStorage) return [];
    const raw = window.localStorage.getItem(DASHBOARD_STORAGE_KEY);
    if (raw === null || raw === "") return [];
    return parseDashboardsPayload(JSON.parse(raw));
  } catch {
    return [];
  }
}

function writeStorage(dashboards: Dashboard[]): void {
  try {
    if (typeof window === "undefined" || !window.localStorage) return;
    const payload = dashboards.map((dashboard) => ({ ...dashboard, version: DASHBOARD_MODEL_VERSION }));
    window.localStorage.setItem(DASHBOARD_STORAGE_KEY, JSON.stringify(payload));
  } catch {
    // Storage can be unavailable in privacy contexts; dashboards then live
    // for the session only. Callers re-read through loadDashboards().
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
  return next;
}

export function addChartView(
  dashboardId: string,
  view: { name: string; url: string; chartId?: string | null },
): Dashboard[] {
  const name = view.name.trim();
  if (name === "" || !view.url.startsWith("/")) return readStorage();
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
