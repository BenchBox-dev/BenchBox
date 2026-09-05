const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * Formats the elapsed UTC calendar days since a result run.
 *
 * The optional reference time keeps callers and tests deterministic. Invalid or
 * missing dates are intentionally omitted rather than rendered as a misleading
 * age.
 */
export function formatRunAge(runDate: string | null | undefined, reference = new Date()): string | null {
  const runDay = utcCalendarDay(runDate);
  const referenceDay = utcCalendarDay(reference);
  if (runDay === null || referenceDay === null) return null;

  const days = Math.round((referenceDay - runDay) / DAY_MS);
  if (days === 0) return "today";
  if (days === 1) return "1 day ago";
  if (days > 1) return `${days} days ago`;
  if (days === -1) return "in 1 day";
  return `in ${Math.abs(days)} days`;
}

function utcCalendarDay(value: string | Date | null | undefined): number | null {
  if (value instanceof Date) {
    if (Number.isNaN(value.getTime())) return null;
    return Date.UTC(value.getUTCFullYear(), value.getUTCMonth(), value.getUTCDate());
  }
  if (typeof value !== "string") return null;

  const match = /^(\d{4})-(\d{2})-(\d{2})(?:$|T)/.exec(value);
  if (!match) return null;
  const [, yearText, monthText, dayText] = match;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const timestamp = Date.UTC(year, month - 1, day);
  const date = new Date(timestamp);
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return null;
  return timestamp;
}
