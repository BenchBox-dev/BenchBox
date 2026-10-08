import { StatusBadge } from "./StatusBadge";

const FUNDING_CONFIG: Record<string, { label: string; compact: string; title: string }> = {
  employer: {
    label: "Employer funded",
    compact: "Employer",
    title: "Run paid for by the submitter's employer",
  },
  personal: {
    label: "Personally funded",
    compact: "Personal",
    title: "Run paid for by the submitter personally",
  },
  "free-trial": {
    label: "Free trial",
    compact: "Trial",
    title: "Run executed on a free trial or promotional credit from the platform",
  },
  "vendor-sponsored": {
    label: "Vendor sponsored",
    compact: "Sponsored",
    title:
      "Compute or credits for this run were provided by the platform vendor - disclosed separately from who produced the result",
  },
  grant: {
    label: "Grant funded",
    compact: "Grant",
    title: "Run paid for by a research grant or similar award",
  },
};

export const UNSPECIFIED_FUNDING = "unspecified";

function configFor(funding: string): { label: string; compact: string; title: string } {
  return (
    FUNDING_CONFIG[funding] ?? {
      label: funding,
      compact: funding,
      title: `Funding source: ${funding} (unrecognised - contact maintainers)`,
    }
  );
}

export function fundingDescription(funding: string): string {
  return configFor(funding).title;
}

interface FundingChipProps {
  funding: string | null | undefined;
  compact?: boolean;
}

export function FundingChip({ funding, compact = false }: FundingChipProps) {
  if (!funding || funding === UNSPECIFIED_FUNDING) return null;

  const config = configFor(funding);
  return (
    <StatusBadge role="funding" tone="neutral" title={config.title}>
      {compact ? config.compact : config.label}
    </StatusBadge>
  );
}

export default FundingChip;
