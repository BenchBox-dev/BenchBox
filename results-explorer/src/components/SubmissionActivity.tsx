import { useMemo, useRef } from "preact/hooks";
import { TableScrollHint } from "@/components/TableScrollHint";
import { useIsNarrowViewport } from "@/lib/useIsNarrowViewport";

/**
 * Submission activity: when runs were published, one row per subject.
 *
 * The index pages listed counts without ever showing the shape of the corpus
 * over time - whether a benchmark is actively receiving runs or was populated
 * once and left. This is the smallest chart that answers that: weekly buckets
 * across a fixed window, one row per subject, ordered by total submissions.
 *
 * Deliberately not a general-purpose heatmap. It counts published runs; it
 * makes no performance claim, so it carries no eligibility policy.
 *
 * The underlying window is always `WEEKS_DESKTOP`: which subjects have a row,
 * their order, each row's total, and the colour scale (`peak`) are all
 * computed over that full window regardless of viewport. Below the `sm`
 * breakpoint there is not enough width to show 26 week columns next to a
 * legible row label, so rendering crops to the trailing `WEEKS_MOBILE`
 * columns of that same data rather than recomputing a narrower window. A
 * subject last active inside the 26-week window but before the visible
 * 10-week slice still gets a row; its cells just don't reach that far back.
 * This is what keeps a row's presence, order and colour identical at both
 * sizes - a narrower *computed* window could not do that, since any subject
 * last active more than `WEEKS_MOBILE` weeks ago would silently disappear
 * from the mobile table with nothing disclosing the drop.
 */

const WEEK_MS = 7 * 24 * 60 * 60 * 1000;
const WEEKS_DESKTOP = 26;
const WEEKS_MOBILE = 10;
const MOBILE_QUERY = "(max-width: 639px)";

export interface SubmissionActivityRow {
  id: string;
  label: string;
  href: string;
  /** Run dates (YYYY-MM-DD or full ISO). Unparseable values are ignored. */
  dates: readonly string[];
}

interface Props {
  rows: readonly SubmissionActivityRow[];
  /** Noun for the subject of each row, e.g. "benchmark". */
  subject: string;
  /** Fixes "now" for tests. */
  reference?: Date;
  /** Rows to draw before collapsing the rest into a summary line. */
  maxRows?: number;
}

/** Start-of-week (Monday, UTC) containing `ms`. */
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

  // Always computed over WEEKS_DESKTOP - see the module doc comment.
  // `isMobile` only decides how many trailing columns get rendered, below.
  const model = useMemo(() => {
    const parsed = rows.map((row) => ({
      ...row,
      days: row.dates.map(parseDay).filter((value): value is number => value !== null),
    }));
    const latest = parsed.flatMap((row) => row.days).reduce((max, day) => (day > max ? day : max), 0);
    if (latest === 0) return null;

    // The window normally ends on today, so a current corpus shows the weeks it
    // has been quiet. Once the newest submission falls outside that window it
    // anchors to that submission instead: ending on today would put every row
    // out of range and render nothing at all, hiding a corpus that was active
    // in the past. A submission dated ahead of today anchors the same way.
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
  // Crop to the trailing `weekCount` columns of the fixed-window data; see
  // the module doc comment for why this is a render-time slice, not a
  // narrower computed window.
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
