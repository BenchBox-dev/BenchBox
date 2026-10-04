// ---------------------------------------------------------------------------
// TuningVerificationBadge - renders the ADR-1 tuning verified-state
// (tuning_validation_status) as a StatusBadge. applied_verified is the only
// state earned via the post-load introspection receipt's corroboration; the
// rest are the honest execution-derived applied-ledger statuses.
// ---------------------------------------------------------------------------

import { StatusBadge, type StatusTone } from "./StatusBadge";

interface VerificationEntry {
  label: string;
  tone: StatusTone;
  title: string;
}

const UNKNOWN_CONFIG: VerificationEntry = {
  label: "Not recorded",
  tone: "neutral",
  title: "This run did not record whether the applied tuning settings were checked.",
};

export const TUNING_VERIFICATION_CONFIG: Record<string, VerificationEntry> = {
  applied_verified: {
    label: "Verified",
    tone: "success",
    title: "BenchBox checked the live database after loading the data and confirmed the applied tuning settings.",
  },
  applied_unverified: {
    label: "Applied; no check available on this platform",
    tone: "info",
    title:
      "The run recorded at least one applied tuning setting, but the result carries no post-load check of the live database.",
  },
  noop: {
    label: "Nothing applied",
    tone: "neutral",
    title: "Tuning was requested, but the run applied no tuning settings.",
  },
  not_applicable: {
    label: "Not applicable",
    tone: "neutral",
    title: "Tuning was disabled or no tuning settings applied to this run.",
  },
  failed: {
    label: "Failed",
    tone: "danger",
    title: "BenchBox tried to apply tuning settings, but every attempt failed.",
  },
};

interface ReceiptCounts {
  mismatches: number | null;
  unverifiable: number | null;
}

function countFrom(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
}

function tallyVerdict(entries: unknown[], verdict: string): number {
  return entries.filter(
    (entry) => entry !== null && typeof entry === "object" && (entry as { verdict?: unknown }).verdict === verdict,
  ).length;
}

function readReceiptCounts(raw: string | null | undefined): ReceiptCounts | null {
  if (typeof raw !== "string" || raw.trim() === "") return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) return null;
  const receipt = parsed as { summary?: unknown; entries?: unknown; truncated?: unknown };
  const summary =
    receipt.summary !== null && typeof receipt.summary === "object" && !Array.isArray(receipt.summary)
      ? (receipt.summary as { mismatch?: unknown; unverifiable?: unknown })
      : null;
  const summaryMismatches = summary ? countFrom(summary.mismatch) : null;
  const summaryUnverifiable = summary ? countFrom(summary.unverifiable) : null;
  const entriesComplete = Array.isArray(receipt.entries) && receipt.truncated !== true;
  const entries = entriesComplete ? (receipt.entries as unknown[]) : [];
  return {
    mismatches: summaryMismatches ?? (entriesComplete ? tallyVerdict(entries, "mismatch") : null),
    unverifiable: summaryUnverifiable ?? (entriesComplete ? tallyVerdict(entries, "unverifiable") : null),
  };
}

function pluralize(count: number, singular: string, plural: string): string {
  return `${count} ${count === 1 ? singular : plural}`;
}

function checkedNotCorroborated(counts: ReceiptCounts): VerificationEntry {
  const parts: string[] = [];
  if (counts.mismatches !== null && counts.unverifiable !== null && counts.mismatches + counts.unverifiable > 0) {
    parts.push(pluralize(counts.mismatches, "mismatch", "mismatches"));
    parts.push(`${counts.unverifiable} unverifiable`);
  }
  const detail = parts.length > 0 ? ` (${parts.join(", ")})` : "";
  return {
    label: `Checked; not corroborated${detail}`,
    tone: "warning",
    title:
      "BenchBox checked the live database after loading the data and could not confirm every applied tuning setting. See the receipt entries for each statement's result.",
  };
}

function resolveConfig(status: string | null | undefined, receipt?: string | null): VerificationEntry {
  if (status === null || status === undefined || status === "") return UNKNOWN_CONFIG;
  if (status === "applied_unverified") {
    const counts = readReceiptCounts(receipt);
    if (counts !== null) return checkedNotCorroborated(counts);
  }
  return TUNING_VERIFICATION_CONFIG[status] ?? UNKNOWN_CONFIG;
}

export function tuningVerificationLabel(status: string | null | undefined, receipt?: string | null): string {
  return resolveConfig(status, receipt).label;
}

interface TuningVerificationBadgeProps {
  status: string | null | undefined;
  receipt?: string | null;
}

export function TuningVerificationBadge({ status, receipt }: TuningVerificationBadgeProps) {
  const config = resolveConfig(status, receipt);
  return (
    <StatusBadge role="computed" tone={config.tone} title={config.title}>
      {config.label}
    </StatusBadge>
  );
}
