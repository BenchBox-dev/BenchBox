import { useMemo } from "preact/hooks";

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
 */

const WEEK_MS = 7 * 24 * 60 * 60 * 1000;
const WEEKS = 26;

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
      latestWeek <= referenceWeek && referenceWeek - latestWeek <= (WEEKS - 1) * WEEK_MS;
    const lastWeek = latestInWindow ? referenceWeek : latestWeek;
    const firstWeek = lastWeek - (WEEKS - 1) * WEEK_MS;
    const weeks = Array.from({ length: WEEKS }, (_, index) => firstWeek + index * WEEK_MS);

    const series = parsed
      .map((row) => {
        const counts = new Array<number>(WEEKS).fill(0);
        let inWindow = 0;
        for (const day of row.days) {
          const index = Math.round((weekStart(day) - firstWeek) / WEEK_MS);
          if (index >= 0 && index < WEEKS) {
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
          Runs per week over the last {WEEKS} weeks, by {subject}, most active first.
        </p>
      </div>
      <div class="overflow-x-auto px-4 py-3">
        <table class="w-full min-w-[36rem] border-separate border-spacing-0" data-testid="submission-activity-grid">
          <caption class="sr-only">
            Published runs per week for each {subject} over the last {WEEKS} weeks.
          </caption>
          <tbody>
            {shown.map((row) => (
              <tr key={row.id}>
                <th
                  scope="row"
                  class="w-[11rem] max-w-[11rem] truncate py-0.5 pr-3 text-left text-xs font-medium"
                >
                  <a href={row.href} class="no-underline hover:underline" title={row.label}>
                    {row.label}
                  </a>
                </th>
                {row.counts.map((count, index) => (
                  <td key={model.weeks[index]} class="p-0">
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
                        model.weeks[index]!,
                      )
                        .toISOString()
                        .slice(0, 10)}`}
                    />
                  </td>
                ))}
                <td class="w-10 py-0.5 pl-3 text-right font-mono text-xs text-[var(--bb-data-fg-muted)]">
                  {row.inWindow}
                </td>
              </tr>
            ))}
            <tr aria-hidden="true">
              <td />
              {model.weeks.map((week, index) => {
                const date = new Date(week);
                const isMonthStart = index === 0 || date.getUTCMonth() !== new Date(model.weeks[index - 1]!).getUTCMonth();
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
