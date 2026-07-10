// ---------------------------------------------------------------------------
// FundingChip - renders the `funding` disclosure as a StatusBadge with
// role="funding".
//
// Funding is ORTHOGONAL to the trust label: a vendor-supplied result can be
// employer-funded, and a community submission can be vendor-sponsored. The chip
// is therefore ADDITIVE to TrustBadge, never a replacement for it.
//
// Every value renders with the SAME `neutral` tone. This is deliberate: a tone
// gradient (e.g. vendor-sponsored → warning) would re-encode funding as a trust
// signal and invite readers to rank results by who paid for them. Funding is a
// disclosure, not a verdict. The chip text carries the meaning; the color does
// not.
//
// `unspecified` (the producer default, and the value for every bundle that
// predates the funding axis) renders NOTHING. An "Unspecified" chip on the
// overwhelming majority of results would be pure noise, and unlike trust_label
// there is no misreading to guard against: absent disclosure is the baseline
// expectation, not a silent claim of neutrality.
//
// Vocabulary source of truth: benchbox/core/results/provenance.py::FUNDING_SOURCES.
// ---------------------------------------------------------------------------

import { StatusBadge } from "./StatusBadge";

const FUNDING_CONFIG: Record<string, { label: string; title: string }> = {
  employer: {
    label: "Employer funded",
    title: "Run paid for by the submitter's employer",
  },
  personal: {
    label: "Personally funded",
    title: "Run paid for by the submitter personally",
  },
  "free-trial": {
    label: "Free trial",
    title: "Run executed on a free trial or promotional credit from the platform",
  },
  "vendor-sponsored": {
    label: "Vendor sponsored",
    title:
      "Compute or credits for this run were provided by the platform vendor - disclosed separately from who produced the result",
  },
  grant: {
    label: "Grant funded",
    title: "Run paid for by a research grant or similar award",
  },
};

/** The producer default; carries no information, so the chip is omitted. */
export const UNSPECIFIED_FUNDING = "unspecified";

/**
 * An unrecognised token is still a disclosure the producer chose to make - show
 * it verbatim rather than dropping it, so vocabulary drift between
 * provenance.py and this map surfaces in the UI instead of hiding a claim.
 */
function configFor(funding: string): { label: string; title: string } {
  return (
    FUNDING_CONFIG[funding] ?? {
      label: funding,
      title: `Funding source: ${funding} (unrecognised - contact maintainers)`,
    }
  );
}

/** Tooltip/legend prose for a funding value. Single source for both surfaces. */
export function fundingDescription(funding: string): string {
  return configFor(funding).title;
}

interface FundingChipProps {
  funding: string | null | undefined;
}

export function FundingChip({ funding }: FundingChipProps) {
  if (!funding || funding === UNSPECIFIED_FUNDING) return null;

  const config = configFor(funding);
  return (
    <StatusBadge role="funding" tone="neutral" title={config.title}>
      {config.label}
    </StatusBadge>
  );
}

export default FundingChip;
