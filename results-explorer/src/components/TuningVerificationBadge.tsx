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
  label: "Not Recorded",
  tone: "neutral",
  title: "Tuning verification state unknown - the run predates the applied-tuning ledger or did not record it",
};

export const TUNING_VERIFICATION_CONFIG: Record<string, VerificationEntry> = {
  applied_verified: {
    label: "Verified",
    tone: "success",
    title:
      "Introspection-corroborated: the applied tuning was confirmed against the live database " +
      "catalog after load (post-load introspection receipt, ADR-1).",
  },
  applied_unverified: {
    label: "Applied (self-attested)",
    tone: "info",
    title:
      "At least one tuning statement executed successfully, but the run was not corroborated by " +
      "post-load introspection - a self-attested claim, not independently verified (ADR-1).",
  },
  noop: {
    label: "No-op",
    tone: "neutral",
    title: "Tuning was requested but the execution path ran no tuning statement on this platform.",
  },
  not_applicable: {
    label: "Not Applicable",
    tone: "neutral",
    title: "Tuning was disabled, or there was no effective tuning configuration for this run.",
  },
  failed: {
    label: "Failed",
    tone: "danger",
    title: "Tuning was attempted but every tuning statement failed to apply.",
  },
};

function resolveConfig(status: string | null | undefined): VerificationEntry {
  if (status === null || status === undefined || status === "") return UNKNOWN_CONFIG;
  return TUNING_VERIFICATION_CONFIG[status] ?? UNKNOWN_CONFIG;
}

export function tuningVerificationLabel(status: string | null | undefined): string {
  return resolveConfig(status).label;
}

interface TuningVerificationBadgeProps {
  status: string | null | undefined;
}

export function TuningVerificationBadge({ status }: TuningVerificationBadgeProps) {
  const config = resolveConfig(status);
  return (
    <StatusBadge role="computed" tone={config.tone} title={config.title}>
      {config.label}
    </StatusBadge>
  );
}
