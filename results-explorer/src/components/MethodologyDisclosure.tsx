import { useState } from "preact/hooks";
import type { DetailResult } from "@/types";
import { TuningBadge } from "@/components/TuningBadge";

// ---------------------------------------------------------------------------
// MethodologyDisclosure - collapsible "How this was measured" panel
// ---------------------------------------------------------------------------

interface Props {
  detail: DetailResult;
}

export function modeLabel(mode: string | null): string {
  if (!mode) return "Not recorded";
  if (mode === "sql") return "SQL (query engine)";
  if (mode === "dataframe") return "DataFrame (in-process)";
  return mode;
}

export function testTypeLabel(testType: string | null): string {
  if (!testType) return "Not recorded";
  if (testType === "power") return "Power test (single-stream sequential)";
  if (testType === "throughput") return "Throughput test (concurrent streams)";
  return testType;
}

export function MethodologyDisclosure({ detail }: Props) {
  const [expanded, setExpanded] = useState(false);

  return (
    <section class="card">
      <button
        class="flex w-full items-center justify-between text-left"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        <h2 class="text-base font-semibold text-gray-900">How this was measured</h2>
        <span class="text-sm text-gray-400">{expanded ? "↑ Hide" : "↓ Show"}</span>
      </button>

      {expanded && (
        <dl class="mt-4 space-y-3 text-sm">
          <DisclosureRow
            label="Primary metric"
            value="Geometric mean of per-query execution times (measurement runs only). Lower is faster."
          />
          <DisclosureRow label="Execution mode" value={modeLabel(detail.execution_mode)} />
          <DisclosureRow label="Test type" value={testTypeLabel(detail.test_type)} />
          <div class="flex gap-3">
            <dt class="w-36 flex-shrink-0 text-gray-500">Tuning state</dt>
            <dd>
              {detail.tuning_mode ? (
                <TuningBadge tuningMode={detail.tuning_mode} />
              ) : (
                <span class="text-gray-700">Not recorded</span>
              )}
            </dd>
          </div>
          <DisclosureRow
            label="Query scope"
            value={`${detail.queries.length} quer${detail.queries.length === 1 ? "y" : "ies"}`}
          />
          <DisclosureRow label="Validation" value={detail.validation_status ?? "Not recorded"} />
        </dl>
      )}
    </section>
  );
}

function DisclosureRow({ label, value }: { label: string; value: string }) {
  return (
    <div class="flex gap-3">
      <dt class="w-36 flex-shrink-0 text-gray-500">{label}</dt>
      <dd class="text-gray-700">{value}</dd>
    </div>
  );
}
