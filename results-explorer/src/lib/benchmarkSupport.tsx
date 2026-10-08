
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";

export type BenchmarkSupportStatus =
  | "stable"
  | "beta"
  | "experimental"
  | "repo_only"
  | "deprecated"
  | "document_only";

const SUPPORT_CONFIG: Record<BenchmarkSupportStatus, { label: string; tone: StatusTone; title: string }> = {
  stable: {
    label: "Stable",
    tone: "success",
    title: "A supported benchmark for normal use.",
  },
  beta: {
    label: "Beta",
    tone: "info",
    title: "A supported beta benchmark. Details can change with documented rationale.",
  },
  experimental: {
    label: "Experimental",
    tone: "warning",
    title: "A prototype or research benchmark. It can change or be removed without a compatibility promise.",
  },
  deprecated: {
    label: "Deprecated",
    tone: "warning",
    title: "A temporarily retained benchmark. Check the migration path before relying on new results.",
  },
  document_only: {
    label: "Document-only",
    tone: "neutral",
    title: "A documented benchmark with no runnable implementation in this product.",
  },
  repo_only: {
    label: "Repo-only",
    tone: "neutral",
    title: "A contributor-only benchmark, hidden from normal discovery surfaces.",
  },
};

const SUPPORT_RANK: Record<BenchmarkSupportStatus, number> = {
  stable: 0,
  beta: 1,
  experimental: 2,
  deprecated: 3,
  document_only: 4,
  repo_only: 5,
};

export function isBenchmarkSupportStatus(value: string | null | undefined): value is BenchmarkSupportStatus {
  return (
    value === "stable" ||
    value === "beta" ||
    value === "experimental" ||
    value === "repo_only" ||
    value === "deprecated" ||
    value === "document_only"
  );
}

export function describeBenchmarkSupportStatus(value: string | null | undefined): string | null {
  return isBenchmarkSupportStatus(value) ? SUPPORT_CONFIG[value].label : null;
}

export function benchmarkSupportRank(value: string | null | undefined): number {
  return isBenchmarkSupportStatus(value) ? SUPPORT_RANK[value] : SUPPORT_RANK.repo_only + 1;
}

export function benchmarkSupportGroupLabel(value: string | null | undefined): string {
  const label = describeBenchmarkSupportStatus(value);
  return label ? `${label} benchmarks` : "Other benchmarks";
}

export function BenchmarkSupportBadge({ status }: { status: string | null | undefined }) {
  if (!isBenchmarkSupportStatus(status)) return null;
  const config = SUPPORT_CONFIG[status];
  return (
    <span data-testid={`support-badge-${status}`}>
      <StatusBadge role="generic" tone={config.tone} title={config.title}>
        {config.label}
      </StatusBadge>
    </span>
  );
}
