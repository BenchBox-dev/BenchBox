import { useMemo, useRef } from "preact/hooks";
import { TableScrollHint } from "@/components/TableScrollHint";
import { useIsNarrowViewport } from "@/lib/useIsNarrowViewport";

const WEEK_MS = 7 * 24 * 60 * 60 * 1000;
const WEEKS_DESKTOP = 26;
const WEEKS_MOBILE = 10;
const MOBILE_QUERY = "(max-width: 639px)";

export interface SubmissionActivityRow {
  id: string;
  label: string;
  href: string;
  dates: readonly string[];
}

interface Props {
  rows: readonly SubmissionActivityRow[];
  subject: string;
  reference?: Date;
  maxRows?: number;
}

function weekStart(ms: number): number {
  const date = new Date(ms);
  const day = (date.getUTCDay() + 6) % 7;
  return Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()) - day * 24 * 60 * 60 * 1000;
}

function parseDay(raw: string): number | null {
  const parsed = Date.parse(/^\d{4}-\d{2}-\d{2}$/.test(raw) ? `${raw}T00:00:00Z` : raw);
  return Number.isNaN(parsed) ? null : parsed;
}

export function SubmissionActivity({ rows, subject, reference, maxRows = 20 }: Props) {
  const scrollerRef = useRef<HTMLDivElement>(null);
  const isMobile = useIsNarrowViewport(MOBILE_QUERY);
  const weekCount = isMobile ? WEEKS_MOBILE : WEEKS_DESKTOP;

  const model = useMemo(() => {
    const parsed = rows.map((row) => ({
      ...row,
      days: row.dates.map(parseDay).filter((value): value is number => value !== null),
    }));
    const latest = parsed.flatMap((row) => row.days).reduce((max, day) => (day > max ? day : max), 0);
    if (latest === 0) return null;

    const referenceWeek = weekStart((reference ?? new Date()).getTime());
    const latestWeek = weekStart(latest);
    const latestInWindow =
      latestWeek <= referenceWeek && referenceWeek - latestWeek <= (WEEKS_DESKTOP - 1) * WEEK_MS;
    const lastWeek = latestInWindow ? referenceWeek : latestWeek;
    const firstWeek = lastWeek - (WEEKS_DESKTOP - 1) * WEEK_MS;
    const weeks = Array.from({ length: WEEKS_DESKTOP }, (_, index) => firstWeek + index * WEEK_MS);

    const series = parsed
      .map((row) => {
        const counts = new Array<number>(WEEKS_DESKTOP).fill(0);
        let inWindow = 0;
        for (const day of row.days) {
          const index = Math.round((weekStart(day) - firstWeek) / WEEK_MS);
          if (index >= 0 && index < WEEKS_DESKTOP) {
            counts[index] = (counts[index] ?? 0) + 1;
            inWindow += 1;
          }
        }
        return { ...row, counts, inWindow, total: row.days.length };
      })
      .filter((row) => row.inWindow > 0)
      .sort((left, right) => right.inWindow - left.inWindow || left.label.localeCompare(right.label));

    const peak = series.reduce((max, row) => Math.max(max, ...row.counts), 0);
    return { weeks, series, peak, firstWeek, lastWeek };
  }, [rows, reference]);

  if (model === null || model.series.length === 0) return null;

  const shown = model.series.slice(0, maxRows);
  const hidden = model.series.length - shown.length;
  const monthFormat = new Intl.DateTimeFormat(undefined, { month: "short", timeZone: "UTC" });
  const visibleWeeks = model.weeks.slice(model.weeks.length - weekCount);

  return (
    <section
      class="mb-6 overflow-hidden rounded-lg border border-[var(--bb-data-border)] bg-[var(--bb-surface-data)]"
      aria-labelledby="submission-activity-title"
      data-testid="submission-activity"
    >
      <div class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-[var(--bb-data-border)] px-4 py-3">
        <h2 id="submission-activity-title" class="text-base font-semibold text-[var(--bb-data-fg-primary)]">
          When were these runs published?
        </h2>
        <p class="text-xs text-[var(--bb-data-fg-muted)]">
          Runs per week over the last {WEEKS_DESKTOP} weeks, by {subject}, most active first.
          {isMobile
            ? ` Showing the trailing ${WEEKS_MOBILE} of ${WEEKS_DESKTOP} weeks; totals cover all ${WEEKS_DESKTOP}.`
            : ""}
        </p>
      </div>
      <TableScrollHint
        scrollerRef={scrollerRef}
        testId="submission-activity-scroll-hint"
        wrapperClassName="flex justify-end px-4 pt-2"
      />
      <div ref={scrollerRef} class="overflow-x-auto px-4 py-3" data-testid="submission-activity-scroll-container">
        <table
          class="w-full min-w-[18rem] sm:min-w-[36rem] border-separate border-spacing-0"
          data-testid="submission-activity-grid"
        >
          <caption class="sr-only">
            Published runs per week for each {subject} over the last {WEEKS_DESKTOP} weeks.
            {isMobile
              ? ` Showing the trailing ${WEEKS_MOBILE} of ${WEEKS_DESKTOP} weeks on this screen; totals cover all ${WEEKS_DESKTOP} weeks.`
              : ""}
          </caption>
          <tbody>
            {shown.map((row) => {
              const visibleCounts = row.counts.slice(row.counts.length - weekCount);
              return (
                <tr key={row.id}>
                  <th
                    scope="row"
                    class="w-20 max-w-20 truncate py-0.5 pr-2 text-left text-xs font-medium sm:w-[11rem] sm:max-w-[11rem] sm:pr-3"
                  >
                    <a href={row.href} class="no-underline hover:underline" title={row.label}>
                      {row.label}
                    </a>
                  </th>
                  {visibleCounts.map((count, index) => (
                    <td key={visibleWeeks[index]} class="w-4 p-0 sm:w-auto"
                      aria-label={`${row.label}: ${count} ${count === 1 ? "run" : "runs"} in the week of ${new Date(visibleWeeks[index]!).toISOString().slice(0, 10)}`}>
                      <div
                        class="mx-px my-px h-3.5 rounded-sm"
                        style={{
                          backgroundColor:
                            count === 0
                              ? "var(--bb-surface-data-muted)"
                              : `color-mix(in srgb, var(--bb-accent) ${Math.round(
                                  25 + (count / model.peak) * 75,
                                )}%, transparent)`,
                        }}
                        title={`${row.label}: ${count} ${count === 1 ? "run" : "runs"} in the week of ${new Date(
                          visibleWeeks[index]!,
                        )
                          .toISOString()
                          .slice(0, 10)}`}
                      />
                    </td>
                  ))}
                  <td class="w-8 py-0.5 pl-2 text-right font-mono text-xs text-[var(--bb-data-fg-muted)] sm:w-10 sm:pl-3">
                    {row.inWindow}
                  </td>
                </tr>
              );
            })}
            <tr aria-hidden="true">
              <td />
              {visibleWeeks.map((week, index) => {
                const date = new Date(week);
                const isMonthStart = index === 0 || date.getUTCMonth() !== new Date(visibleWeeks[index - 1]!).getUTCMonth();
                return (
                  <td key={week} class="pt-1 text-[10px] text-[var(--bb-data-fg-subtle)]">
                    {isMonthStart ? monthFormat.format(date) : ""}
                  </td>
                );
              })}
              <td />
            </tr>
          </tbody>
        </table>
      </div>
      {hidden > 0 && (
        <p class="border-t border-[var(--bb-data-border)] px-4 py-2 text-xs text-[var(--bb-data-fg-muted)]">
          {hidden} less active {hidden === 1 ? subject : `${subject}s`} not shown.
        </p>
      )}
    </section>
  );
}
