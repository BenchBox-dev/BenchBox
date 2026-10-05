import { useState } from "preact/hooks";
import type { RoutableProps } from "preact-router";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { useDocumentTitle } from "@/lib/useDocumentTitle";
import { useUrlState } from "@/lib/useUrlState";
import {
  createDashboard,
  deleteDashboard,
  loadDashboards,
  removeChartView,
  renameChartView,
  renameDashboard,
  type Dashboard,
} from "@/lib/dashboards";

/** URL parameter carrying the open dashboard. */
const DASHBOARD_URL_KEY = "dashboard";

export function Dashboards(_: RoutableProps) {
  const [dashboards, setDashboards] = useState<Dashboard[]>(() => loadDashboards());
  const [openId, setOpenId] = useUrlState<string | null>(DASHBOARD_URL_KEY, null, {
    encode: (value) => value ?? "",
    decode: (raw) => (raw === "" ? null : raw),
  });
  const [newName, setNewName] = useState<string>("");
  useDocumentTitle("Dashboards · BenchBox Results");

  const open = dashboards.find((dashboard) => dashboard.id === openId) ?? null;

  function refresh(next: Dashboard[]): void {
    setDashboards(next);
  }

  function handleCreate() {
    const created = createDashboard(newName);
    if (!created) return;
    setNewName("");
    refresh(loadDashboards());
    setOpenId(created.id);
  }

  return (
    <div class="mx-auto max-w-7xl px-4 py-10 sm:px-6 lg:px-8">
      <PageHeader
        crumbs={[{ label: "Results", href: "/results/" }, { label: "Dashboards" }]}
        eyebrow="Saved views"
        title="Dashboards"
        subtitle="Your saved chart configurations live in this browser only. Open a saved view to return to that exact chart."
      />

      <div class="mb-6 flex flex-wrap items-center gap-2">
        <input
          type="text"
          aria-label="New dashboard name"
          placeholder="New dashboard name"
          class="rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-3 py-2 text-sm text-[var(--bb-data-fg-primary)]"
          value={newName}
          onInput={(event) => setNewName(event.currentTarget.value)}
        />
        <button
          type="button"
          class="btn btn-secondary"
          disabled={newName.trim() === ""}
          onClick={handleCreate}
        >
          New dashboard
        </button>
      </div>

      {dashboards.length === 0 ? (
        <EmptyState
          title="No dashboards yet"
          description="Open any chart and choose Save view to keep its configuration here."
        />
      ) : (
        <div class="grid gap-6 lg:grid-cols-[16rem_1fr]">
          <nav aria-label="Dashboards" class="flex flex-col gap-1">
            {dashboards.map((dashboard) => {
              const selected = dashboard.id === open?.id;
              return (
                <button
                  key={dashboard.id}
                  type="button"
                  aria-current={selected ? "true" : undefined}
                  class={`rounded-md px-3 py-2 text-left text-sm font-medium no-underline ${
                    selected
                      ? "bg-[var(--bb-surface-data)] text-[var(--bb-data-fg-primary)] shadow-sm"
                      : "text-[var(--bb-data-fg-muted)] hover:text-[var(--bb-data-fg-primary)]"
                  }`}
                  onClick={() => setOpenId(dashboard.id)}
                >
                  {dashboard.name} ({dashboard.items.length})
                </button>
              );
            })}
          </nav>
          <div>
            {open === null ? (
              <p class="text-sm text-[var(--bb-data-fg-muted)]">Select a dashboard to manage its saved chart views.</p>
            ) : (
              <DashboardDetail
                dashboard={open}
                onChanged={refresh}
                onDeleted={(id) => {
                  refresh(deleteDashboard(id));
                  setOpenId(null);
                }}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function DashboardDetail({
  dashboard,
  onChanged,
  onDeleted,
}: {
  dashboard: Dashboard;
  onChanged: (next: Dashboard[]) => void;
  onDeleted: (id: string) => void;
}) {
  const [editingName, setEditingName] = useState<boolean>(false);
  const [nameDraft, setNameDraft] = useState<string>(dashboard.name);
  const [renamingViewId, setRenamingViewId] = useState<string | null>(null);
  const [viewNameDraft, setViewNameDraft] = useState<string>("");

  function startRenameView(viewId: string, current: string): void {
    setRenamingViewId(viewId);
    setViewNameDraft(current);
  }

  return (
    <section aria-label={`${dashboard.name} dashboard`} data-testid="dashboard-detail">
      <div class="mb-4 flex flex-wrap items-center gap-2">
        {editingName ? (
          <>
            <input
              type="text"
              aria-label="Dashboard name"
              class="rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-2 py-1 text-sm text-[var(--bb-data-fg-primary)]"
              value={nameDraft}
              onInput={(event) => setNameDraft(event.currentTarget.value)}
            />
            <button
              type="button"
              class="btn btn-secondary"
              onClick={() => {
                onChanged(renameDashboard(dashboard.id, nameDraft));
                setEditingName(false);
              }}
            >
              Rename
            </button>
          </>
        ) : (
          <>
            <h2 class="text-lg font-semibold text-[var(--bb-data-fg-primary)]">{dashboard.name}</h2>
            <button
              type="button"
              class="text-xs text-[var(--bb-data-fg-muted)] hover:text-[var(--bb-data-fg-primary)] underline"
              onClick={() => {
                setNameDraft(dashboard.name);
                setEditingName(true);
              }}
            >
              Rename
            </button>
            <button
              type="button"
              class="text-xs text-[var(--bb-data-fg-muted)] hover:text-[var(--bb-tone-danger-fg)] underline"
              onClick={() => onDeleted(dashboard.id)}
            >
              Delete
            </button>
          </>
        )}
      </div>
      {dashboard.items.length === 0 ? (
        <p class="text-sm text-[var(--bb-data-fg-muted)]">
          Nothing saved here yet. Open a chart and choose Save view to keep its configuration.
        </p>
      ) : (
        <ul class="grid gap-3 sm:grid-cols-2">
          {dashboard.items.map((item) => (
            <li
              key={item.id}
              class="rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] p-4"
            >
              {renamingViewId === item.id ? (
                <span class="flex flex-wrap items-center gap-2">
                  <input
                    type="text"
                    aria-label="Saved view name"
                    class="rounded-md border border-[var(--bb-data-border-strong)] bg-[var(--bb-surface-data)] px-2 py-1 text-sm text-[var(--bb-data-fg-primary)]"
                    value={viewNameDraft}
                    onInput={(event) => setViewNameDraft(event.currentTarget.value)}
                  />
                  <button
                    type="button"
                    class="btn btn-secondary"
                    onClick={() => {
                      onChanged(renameChartView(dashboard.id, item.id, viewNameDraft));
                      setRenamingViewId(null);
                    }}
                  >
                    Rename
                  </button>
                </span>
              ) : (
                <>
                  <a href={item.url} class="font-medium text-[var(--bb-data-fg-primary)] no-underline hover:text-[var(--bb-accent)]">
                    {item.name}
                  </a>
                  <span class="mt-2 flex flex-wrap items-center gap-3 text-xs text-[var(--bb-data-fg-muted)]">
                    <button
                      type="button"
                      class="underline hover:text-[var(--bb-data-fg-primary)]"
                      onClick={() => startRenameView(item.id, item.name)}
                    >
                      Rename
                    </button>
                    <button
                      type="button"
                      class="underline hover:text-[var(--bb-tone-danger-fg)]"
                      onClick={() => onChanged(removeChartView(dashboard.id, item.id))}
                    >
                      Remove
                    </button>
                  </span>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
