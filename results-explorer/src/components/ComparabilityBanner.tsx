import { useState } from "preact/hooks";

// ---------------------------------------------------------------------------
// ComparabilityBanner - dismissible warning for cross-dimension comparisons
// ---------------------------------------------------------------------------

export interface ComparabilityWarning {
  dimension: string;
  values: string[];
  message: string;
}

interface Props {
  warnings: ComparabilityWarning[];
}

export function ComparabilityBanner({ warnings }: Props) {
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  const visible = warnings.filter((w) => !dismissed.has(w.dimension));
  if (visible.length === 0) return null;

  return (
    <div class="mb-6 space-y-2">
      {visible.map((w) => (
        <div
          key={w.dimension}
          class="flex items-start justify-between gap-3 rounded-md border border-yellow-200 bg-yellow-50 px-4 py-3 text-sm text-yellow-800"
        >
          <p>
            <strong>{w.dimension}:</strong> {w.values.join(" vs ")} - {w.message}
          </p>
          <button
            class="flex-shrink-0 text-yellow-600 hover:text-yellow-800 bg-transparent border-0 p-0 cursor-pointer leading-none"
            onClick={() => setDismissed((prev) => new Set([...prev, w.dimension]))}
            aria-label={`Dismiss ${w.dimension} warning`}
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// buildComparabilityWarnings - derive warnings from loaded results
// ---------------------------------------------------------------------------

interface ResultSummary {
  platform: string;
  execution_mode: string | null;
  tuning_mode: string | null;
  test_type: string | null;
  query_count: number;
}

export function buildComparabilityWarnings(results: ResultSummary[]): ComparabilityWarning[] {
  const warnings: ComparabilityWarning[] = [];
  if (results.length < 2) return warnings;

  const modes = [...new Set(results.map((r) => r.execution_mode).filter(Boolean))];
  if (modes.length > 1) {
    warnings.push({
      dimension: "Execution mode",
      values: modes as string[],
      message:
        "results may not reflect platform SQL performance differences - compare sql vs sql or dataframe vs dataframe for a fair comparison",
    });
  }

  const tunings = [...new Set(results.map((r) => r.tuning_mode).filter(Boolean))];
  if (tunings.length > 1) {
    warnings.push({
      dimension: "Tuning config",
      values: tunings as string[],
      message:
        "tuning differences can dominate platform differences - consider comparing results with the same tuning mode",
    });
  }

  const testTypes = [...new Set(results.map((r) => r.test_type).filter(Boolean))];
  if (testTypes.length > 1) {
    warnings.push({
      dimension: "Test type",
      values: testTypes as string[],
      message: "power and throughput tests measure different workloads and are not directly comparable",
    });
  }

  const counts = [...new Set(results.map((r) => r.query_count))];
  if (counts.length > 1) {
    warnings.push({
      dimension: "Query scope",
      values: counts.map(String),
      message:
        "results cover different numbers of queries - geomean is comparable only when the same query set is used",
    });
  }

  return warnings;
}
