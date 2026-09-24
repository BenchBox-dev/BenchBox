/**
 * Shown in place of a rank table when a cohort is excluded from ranking
 * (see `formatCohortExclusion` in `@/lib/displayEligibility`). Timing
 * evidence and receipts remain reachable elsewhere on the page; only the
 * ranked leaderboard view is withheld.
 */
export function RankGateNotice({
  reason,
  benchmark,
  scaleFactor,
  phase,
}: {
  reason: string;
  benchmark: string;
  scaleFactor: string;
  phase: string;
}) {
  return (
    <section
      class="rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] p-5 text-sm shadow-sm"
      data-testid="rank-gate-notice"
      aria-label="Rank gate"
    >
      <h2 class="text-base font-semibold text-[var(--bb-data-fg-primary)]">Ranks are unavailable</h2>
      <p class="mt-2 text-[var(--bb-data-fg-muted)]">
        {benchmark} SF {scaleFactor} {phase} is not published as a leaderboard because {reason}
      </p>
      <p class="mt-2 text-xs text-[var(--bb-data-fg-subtle)]">
        Timing evidence and receipts remain available, but BenchBox will not publish a ranking here.
      </p>
    </section>
  );
}
