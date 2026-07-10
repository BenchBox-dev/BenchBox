import type { ComponentChildren } from "preact";
import { useState } from "preact/hooks";
import { FundingChip, fundingDescription, UNSPECIFIED_FUNDING } from "@/components/FundingChip";
import { TrustBadge, trustLabelDescription } from "@/components/TrustBadge";

// ---------------------------------------------------------------------------
// ProvenanceLegend - collapsible "What do these labels mean?" panel.
//
// docs/reference/hosted-results-contract.md (§ Trust label rendering rules)
// requires that "a legend explaining all trust labels is accessible from every
// page that displays them". This is that legend, extended with the orthogonal
// funding axis.
//
// Rows render the REAL TrustBadge / FundingChip components and pull their prose
// from the components' own config via trustLabelDescription() /
// fundingDescription(). The legend therefore cannot drift from the badges it
// explains - there is one source for each string.
//
// Rendered on every page that shows a TrustBadge or FundingChip - ResultDetail,
// BenchmarkIndex, PlatformIndex, Compare, and Home (meta leaderboard) - per the
// hosted-results-contract rule that a legend explaining the labels is reachable
// from every surface that displays them. It is collapsed by default so it costs
// a line of chrome, not a screenful.
// ---------------------------------------------------------------------------

/**
 * Canonical trust labels, one row each. TRUST_CONFIG additionally carries
 * alias keys (`ci`/`ci-verified`/`ci-validated`, `local`/`local-run`) that map
 * onto the same badge; listing every alias would show the reader duplicate
 * rows, so the legend names the canonical spelling only.
 */
const LEGEND_TRUST_LABELS = [
  "maintainer-run",
  "community-submission",
  "vendor-supplied",
  "ci-verified",
  "local-run",
  "unofficial-research",
] as const;

/**
 * Mirror of benchbox/core/results/provenance.py::FUNDING_SOURCES minus
 * `unspecified`, which is covered by its own explanatory row below because it
 * renders no chip at all.
 */
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
            <h3 class="mb-1 font-semibold text-[var(--bb-data-fg-primary)]">Trust label</h3>
            <p class="mb-3 text-[var(--bb-data-fg-muted)]">
              Who produced this result, and under what review. Every result carries exactly one.
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
              Who paid for the run. This is a disclosure, not a trust signal, and it is independent
              of the trust label - a vendor-supplied result can be employer-funded, and a community
              submission can be vendor-sponsored. All funding chips share one neutral color so that
              no funding source reads as better or worse than another.
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
