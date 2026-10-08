import type { ComponentChildren } from "preact";
import { useState } from "preact/hooks";
import { FundingChip, fundingDescription, UNSPECIFIED_FUNDING } from "@/components/FundingChip";
import { TrustBadge, trustLabelDescription } from "@/components/TrustBadge";

const LEGEND_TRUST_LABELS = [
  "maintainer-run",
  "community-submission",
  "vendor-supplied",
  "ci-verified",
  "local-run",
  "unofficial-research",
] as const;

const LEGEND_FUNDING_SOURCES = [
  "employer",
  "personal",
  "free-trial",
  "vendor-sponsored",
  "grant",
] as const;

export function ProvenanceLegend() {
  const [expanded, setExpanded] = useState(false);

  return (
    <section class="card" data-testid="provenance-legend">
      <button
        class="flex w-full items-center justify-between text-left"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        <h2 class="text-base font-semibold text-[var(--bb-data-fg-primary)]">
          What do these labels mean?
        </h2>
        <span class="text-sm text-[var(--bb-data-fg-subtle)]">{expanded ? "↑ Hide" : "↓ Show"}</span>
      </button>

      {expanded && (
        <div class="mt-4 space-y-6 text-sm">
          <div>
            <h3 class="mb-1 font-semibold text-[var(--bb-data-fg-primary)]">Result source</h3>
            <p class="mb-3 text-[var(--bb-data-fg-muted)]">
              Who produced the result and how BenchBox reviewed it.
            </p>
            <dl class="space-y-2">
              {LEGEND_TRUST_LABELS.map((label) => (
                <LegendRow
                  key={label}
                  badge={<TrustBadge trustLabel={label} />}
                  description={trustLabelDescription(label)}
                />
              ))}
            </dl>
          </div>

          <div>
            <h3 class="mb-1 font-semibold text-[var(--bb-data-fg-primary)]">Funding</h3>
            <p class="mb-3 text-[var(--bb-data-fg-muted)]">
              Who paid for the run. Funding does not change how BenchBox reviews or ranks a result.
            </p>
            <dl class="space-y-2">
              {LEGEND_FUNDING_SOURCES.map((funding) => (
                <LegendRow
                  key={funding}
                  badge={<FundingChip funding={funding} />}
                  description={fundingDescription(funding)}
                />
              ))}
              <LegendRow
                key={UNSPECIFIED_FUNDING}
                badge={<span class="text-[var(--bb-data-fg-subtle)]">(no chip)</span>}
                description="Funding was not disclosed for this run. No chip is shown."
              />
            </dl>
          </div>
        </div>
      )}
    </section>
  );
}

interface LegendRowProps {
  badge: ComponentChildren;
  description: string;
}

function LegendRow({ badge, description }: LegendRowProps) {
  return (
    <div class="flex flex-col gap-1 sm:flex-row sm:gap-3">
      <dt class="w-40 flex-shrink-0">{badge}</dt>
      <dd class="text-[var(--bb-data-fg-muted)]">{description}</dd>
    </div>
  );
}

export default ProvenanceLegend;
