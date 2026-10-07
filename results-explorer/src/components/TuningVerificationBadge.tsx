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
    label: "Applied; no live-database check recorded",
    tone: "info",
    title:
      "The run recorded at least one applied tuning setting, but no check result was recorded in this result. A check may not have run, or its outcome was not kept.",
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
  absent: number;
  mismatches: number;
  unverifiable: number;
}

interface CheckedReceipt {
  counts: ReceiptCounts | null;
  truncated: boolean;
}

function countFrom(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
}

function tallyVerdict(entries: unknown[], verdict: string): number {
  return entries.filter(
    (entry) => entry !== null && typeof entry === "object" && (entry as { verdict?: unknown }).verdict === verdict,
  ).length;
}

function countsFromReceipt(receipt: { summary?: unknown; entries?: unknown; truncated?: unknown }): ReceiptCounts | null {
  if (receipt.summary !== null && typeof receipt.summary === "object" && !Array.isArray(receipt.summary)) {
    const summary = receipt.summary as Record<string, unknown>;
    return {
      absent: countFrom(summary.absent) ?? 0,
      mismatches: countFrom(summary.mismatch) ?? 0,
      unverifiable: countFrom(summary.unverifiable) ?? 0,
    };
  }
  if (Array.isArray(receipt.entries) && receipt.truncated !== true) {
    return {
      absent: tallyVerdict(receipt.entries, "absent"),
      mismatches: tallyVerdict(receipt.entries, "mismatch"),
      unverifiable: tallyVerdict(receipt.entries, "unverifiable"),
    };
  }
  return null;
}

function readFailedCheck(raw: string | null | undefined): CheckedReceipt | null {
  if (typeof raw !== "string" || raw.trim() === "") return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) return null;
  const receipt = parsed as { corroborated?: unknown; summary?: unknown; entries?: unknown; truncated?: unknown };
  if (receipt.corroborated !== false) return null;
  return { counts: countsFromReceipt(receipt), truncated: receipt.truncated === true };
}

function pluralize(count: number, singular: string, plural: string): string {
  return `${count} ${count === 1 ? singular : plural}`;
}

function checkedNotCorroborated(check: CheckedReceipt): VerificationEntry {
  const parts: string[] = [];
  if (check.counts !== null) {
    if (check.counts.absent > 0) parts.push(`${check.counts.absent} absent`);
    if (check.counts.mismatches > 0) parts.push(pluralize(check.counts.mismatches, "mismatch", "mismatches"));
    if (check.counts.unverifiable > 0) parts.push(`${check.counts.unverifiable} unverifiable`);
  }
  const detail = parts.length > 0 ? ` (${parts.join(", ")})` : "";
  const truncation = check.truncated
    ? " The stored receipt was truncated, so it lists only some of the statements."
    : "";
  return {
    label: `Checked; not corroborated${detail}`,
    tone: "warning",
    title: `BenchBox checked the live database after loading the data and could not confirm every applied tuning setting. See the receipt entries for each statement's result.${truncation}`,
  };
}

function resolveConfig(status: string | null | undefined, receipt?: string | null): VerificationEntry {
  if (status === null || status === undefined || status === "") return UNKNOWN_CONFIG;
  if (status === "applied_unverified") {
    const check = readFailedCheck(receipt);
    if (check !== null) return checkedNotCorroborated(check);
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
