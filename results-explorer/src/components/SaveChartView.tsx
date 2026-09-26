import { useState } from "preact/hooks";
import {
  addChartView,
  createDashboard,
  loadDashboards,
  type Dashboard,
} from "@/lib/dashboards";

interface SaveChartViewProps {
  /** Registry chart id when the button targets one chart card (tabs layout passes the open chart). */
  chartId?: string | null;
  /** Chart title used as the default saved-view name. */
  chartTitle: string;
  /** Deep-link anchor appended to the saved URL (card anchors in long layout). */
  anchorId?: string;
}

/** Save the current chart view (URL state included) into a user dashboard. */
export function SaveChartView({ chartId = null, chartTitle, anchorId }: SaveChartViewProps) {
  const [dashboards, setDashboards] = useState<Dashboard[]>(() => loadDashboards());
  const [dashboardId, setDashboardId] = useState<string>("");
  const [newName, setNewName] = useState<string>("");
  const [saved, setSaved] = useState<boolean>(false);

  function currentViewUrl(): string {
    if (typeof window === "undefined") return "/";
    const url = new URL(window.location.href);
    const path = `${url.pathname}${url.search}`;
    if (anchorId) return `${path}#${anchorId}`;
    return `${path}${url.hash}`;
  }

  function defaultViewName(): string {
    const title = typeof document !== "undefined" ? document.title.replace(/\s*[·|]\s*BenchBox Results\s*$/, "").trim() : "";
    const page = title === "" ? "Chart view" : title;
    return `${chartTitle} · ${page}`;
  }

  function handleSave() {
    let targetId = dashboardId;
    if (targetId === "__new__") {
      const created = createDashboard(newName);
      if (!created) return;
      targetId = created.id;
      setNewName("");
    }
    if (targetId === "") return;
    const next = addChartView(targetId, { name: defaultViewName(), url: currentViewUrl(), chartId });
    setDashboards(next);
    setDashboardId(targetId);
    setSaved(true);
  }

  return (
    <span class="inline-flex flex-wrap items-center gap-2" data-testid="save-chart-view">
      <select
        aria-label="Dashboard to save this chart view into"
        class="rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-2 py-1 text-xs text-[var(--bb-data-fg-primary)]"
        value={dashboardId}
        onChange={(event) => {
          setDashboardId(event.currentTarget.value);
          setSaved(false);
        }}
      >
        <option value="">Save to…</option>
        {dashboards.map((dashboard) => (
          <option key={dashboard.id} value={dashboard.id}>
            {dashboard.name}
          </option>
        ))}
        <option value="__new__">New dashboard…</option>
      </select>
      {dashboardId === "__new__" && (
        <input
          type="text"
          aria-label="New dashboard name"
          placeholder="Dashboard name"
          class="rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-2 py-1 text-xs text-[var(--bb-data-fg-primary)]"
          value={newName}
          onInput={(event) => {
            setNewName(event.currentTarget.value);
            setSaved(false);
          }}
        />
      )}
      <button
        type="button"
        class="rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-2 py-1 text-xs font-medium text-[var(--bb-data-fg-muted)] hover:text-[var(--bb-data-fg-primary)] disabled:opacity-50"
        disabled={dashboardId === "" || (dashboardId === "__new__" && newName.trim() === "")}
        onClick={handleSave}
        title="Save this chart view to a dashboard"
      >
        {saved ? "Saved ✓" : "Save view"}
      </button>
      <a href="/results/dashboards/" class="text-xs text-[var(--bb-data-fg-muted)] hover:text-[var(--bb-data-fg-primary)] no-underline">
        Dashboards
      </a>
    </span>
  );
}
