import { Select } from "@/components/Select";
import { StatusBadge } from "@/components/StatusBadge";
import {
  ALL_WARM,
  WARMUP,
  basisUnavailableLabel,
  encodeBasis,
  formatBasisLabel,
  isDefaultBasis,
  warmPass,
  type BasisStatistic,
  type MeasurementBasis,
  type PassSelection,
} from "@/lib/measurementBasis";

/**
 * The shared measurement-basis control for a cross-run comparison.
 *
 * ONE bar for the whole comparison, not one per run. That is the visible form
 * of the model's central invariant: a comparison spanning more than one run
 * reads every run through the same basis, because reading one run's min
 * against another's median measures the statistic rather than the engine.
 * The lock affordance says so in words, so the guarantee is legible on the
 * page and not just in the type system.
 */
export interface MeasurementBasisBarProps {
  basis: MeasurementBasis;
  onBasisChange: (basis: MeasurementBasis) => void;
  /** Pass selections this comparison's runs can actually serve. */
  availablePasses: readonly PassSelection[];
  /** How many queries the figures are computed over, after intersection. */
  comparableQueryCount: number;
  /** Total logical queries before the shared-query-set rule dropped any. */
  totalQueryCount: number;
  /** How many runs share this basis. */
  runCount: number;
  /**
   * True when the current pass selection resolves to a single execution, so
   * median and min are the same number.
   */
  statisticCollapsed: boolean;
  /** Why a basis is unavailable, when one is. */
  unavailableReason?: Parameters<typeof basisUnavailableLabel>[0] | null;
}

const STATISTIC_OPTIONS: { value: BasisStatistic; label: string }[] = [
  { value: "median", label: "Median" },
  { value: "min", label: "Fastest" },
];

function passToken(passes: PassSelection): string {
  return encodeBasis({ passes, statistic: "median" });
}

function passLabel(passes: PassSelection): string {
  switch (passes.kind) {
    case "all_warm":
      return "All warm passes";
    case "warmup":
      return "Warmup pass";
    case "warm_pass":
      return `Warm pass ${passes.pass}`;
  }
}

function decodePassToken(token: string): PassSelection {
  if (token === "warmup") return WARMUP;
  const match = /^warm_pass_(\d+)$/.exec(token);
  if (match?.[1] !== undefined) return warmPass(Number(match[1]));
  return ALL_WARM;
}

export function MeasurementBasisBar({
  basis,
  onBasisChange,
  availablePasses,
  comparableQueryCount,
  totalQueryCount,
  runCount,
  statisticCollapsed,
  unavailableReason = null,
}: MeasurementBasisBarProps) {
  const excluded = totalQueryCount - comparableQueryCount;
  const measuring = isDefaultBasis(basis)
    ? "the published median over all warm passes"
    : `the ${formatBasisLabel(basis)}`;

  return (
    <section
      class="panel mb-4 flex flex-wrap items-start justify-between gap-3 px-3 py-2 shadow-sm"
      aria-label="Measurement basis"
    >
      <div class="min-w-0">
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-sm font-medium text-[var(--bb-data-fg-primary)]">Measurement basis</span>
          <StatusBadge role="comparison" tone="neutral" title="All runs in this comparison share one basis">
            {`Shared across ${runCount} runs`}
          </StatusBadge>
        </div>
        <p class="mt-1 text-xs text-[var(--bb-data-fg-muted)]">
          {`Query-derived latency figures use ${measuring}, over ${comparableQueryCount} of ${totalQueryCount} queries every selected run can answer.`}
          {excluded > 0
            ? ` ${excluded} ${excluded === 1 ? "query is" : "queries are"} excluded from every run so the geomeans compare like with like.`
            : ""}
        </p>
        <p class="mt-1 text-xs text-[var(--bb-data-fg-subtle)]">
          Whole-run wall-clock totals and phase durations remain run-wide context.
        </p>
        {unavailableReason ? (
          <p class="mt-1 text-xs text-[var(--bb-data-fg-subtle)]">{basisUnavailableLabel(unavailableReason)}</p>
        ) : null}
      </div>

      <div class="flex flex-wrap items-center gap-3">
        <div>
          <label class="text-xs font-medium text-[var(--bb-data-fg-primary)]" for="basis-passes">
            Passes
          </label>
          <Select
            id="basis-passes"
            ariaLabel="Measurement passes"
            size="sm"
            value={passToken(basis.passes)}
            onChange={(token) => onBasisChange({ passes: decodePassToken(token), statistic: basis.statistic })}
            options={availablePasses.map((passes) => ({
              value: passToken(passes),
              label: passLabel(passes),
            }))}
          />
        </div>

        {/*
          The collapsed state is its OWN branch, never a `disabled` attribute
          computed from a boolean. A disabled select still renders as a
          control, and a truthiness bug would leave it interactive while
          presenting a choice the data cannot express -- failing open, silently.
          Rendering different markup cannot fail that way: there is no control
          to interact with.
        */}
        {statisticCollapsed ? (
          <div>
            <span class="text-xs font-medium text-[var(--bb-data-fg-primary)]">Statistic</span>
            <p class="mt-0.5 text-xs text-[var(--bb-data-fg-muted)]" data-testid="statistic-locked">
              Single value — median and fastest are the same over one execution.
            </p>
          </div>
        ) : (
          <div>
            <label class="text-xs font-medium text-[var(--bb-data-fg-primary)]" for="basis-statistic">
              Statistic
            </label>
            <Select
              id="basis-statistic"
              ariaLabel="Measurement statistic"
              size="sm"
              value={basis.statistic}
              onChange={(value) => onBasisChange({ passes: basis.passes, statistic: value as BasisStatistic })}
              options={STATISTIC_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
            />
          </div>
        )}
      </div>
    </section>
  );
}
