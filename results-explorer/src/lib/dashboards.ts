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

/** True for same-origin explorer paths. Rejects protocol-relative URLs
 * (`//host/...`), backslash escapes (`/\...`), and absolute URLs, so a
 * seeded or imported payload can never turn a saved view into an
 * open redirect off the explorer origin. */
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

// Session fallback when localStorage writes fail (unavailable, blocked, or
// quota-exceeded): the latest snapshot is kept in this module-scoped variable
// so loadDashboards() keeps returning what the session just saved. It is
// cleared on the next successful localStorage write and does not survive a
// page reload. Only used in the browser; server-side writes stay no-ops.
let memoryDashboards: Dashboard[] | null = null;

// Ids deleted while localStorage writes were failing. Without tombstones a
// delete followed by a failed write would resurrect: the in-memory snapshot
// no longer contains the id, so the merge in readStorage would re-admit the
// stale stored copy.
let memoryTombstones: Set<string> = new Set();

function cloneDashboards(dashboards: Dashboard[]): Dashboard[] {
  return dashboards.map((dashboard) => ({ ...dashboard, items: dashboard.items.map((item) => ({ ...item })) }));
}

function readStorage(): Dashboard[] {
  let stored: Dashboard[];
  try {
    if (typeof window === "undefined") return [];
    // Property access itself can throw SecurityError when storage is
    // blocked (private browsing, restricted iframes), so it stays inside
    // the try alongside getItem/parse.
    const storage = window.localStorage;
    if (!storage) return [];
    const raw = storage.getItem(DASHBOARD_STORAGE_KEY);
    if (raw === null || raw === "") stored = [];
    else stored = parseDashboardsPayload(JSON.parse(raw));
  } catch {
    stored = [];
  }
  if (memoryDashboards === null) return stored.filter((dashboard) => !memoryTombstones.has(dashboard.id));
  // The failed-write snapshot is authoritative for its ids; entries stored by
  // another tab that the snapshot never saw are preserved alongside it.
  // Tombstoned ids stay deleted even though the snapshot no longer lists them.
  const memoryIds = new Set(memoryDashboards.map((dashboard) => dashboard.id));
  return [
    ...cloneDashboards(memoryDashboards),
    ...stored.filter((dashboard) => !memoryIds.has(dashboard.id) && !memoryTombstones.has(dashboard.id)),
  ];
}

function writeStorage(dashboards: Dashboard[]): void {
  if (typeof window !== "undefined") {
    try {
      // window.localStorage access stays inside the try: it throws
      // SecurityError when storage is blocked, and that must fall back
      // to memory rather than crash the caller.
      const storage = window.localStorage;
      if (storage) {
        const payload = dashboards.map((dashboard) => ({ ...dashboard, version: DASHBOARD_MODEL_VERSION }));
        storage.setItem(DASHBOARD_STORAGE_KEY, JSON.stringify(payload));
        memoryDashboards = null;
        memoryTombstones = new Set();
        return;
      }
    } catch {
      // Fall through to the session fallback below.
    }
  }
  // Storage is unavailable: keep the snapshot in memory so the session still
  // sees what it saved. Callers return the mutated model, which now matches
  // what loadDashboards() reads back until the page reloads. Ids absent from
  // the new snapshot but present in the old one were deleted, so tombstone
  // them to keep the stale stored copy from resurrecting.
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
  // If the write fell back to memory, tombstone the id explicitly. The
  // snapshot diff in writeStorage only covers deletes after the first
  // failed write; without this, deleting while memoryDashboards is still
  // null would resurrect the stale stored copy on the next read.
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
