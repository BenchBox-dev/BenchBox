const DAY_MS = 24 * 60 * 60 * 1000;
const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;
const TIMESTAMP_RE = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})?$/;

/**
 * Formats the elapsed UTC calendar days since a result run.
 *
 * Plain ``YYYY-MM-DD`` values are explicit UTC calendar days. Complete ISO
 * timestamps with an offset or ``Z`` are converted to their UTC calendar day;
 * legacy timestamps without an offset are interpreted as UTC. The optional
 * reference time keeps callers and tests deterministic. Invalid or missing
 * values are intentionally omitted rather than rendered as a misleading age.
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

  const dateMatch = DATE_RE.exec(value);
  if (dateMatch) return calendarDayFromParts(dateMatch);

  const timestampMatch = TIMESTAMP_RE.exec(value);
  if (!timestampMatch || !validTimestampParts(timestampMatch)) return null;
  const parsed = new Date(timestampMatch[7] ? value : `${value}Z`);
  if (Number.isNaN(parsed.getTime())) return null;
  return Date.UTC(parsed.getUTCFullYear(), parsed.getUTCMonth(), parsed.getUTCDate());
}

function calendarDayFromParts(match: RegExpExecArray): number | null {
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const timestamp = Date.UTC(year, month - 1, day);
  const date = new Date(timestamp);
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day
    ? timestamp
    : null;
}

function validTimestampParts(match: RegExpExecArray): boolean {
  if (calendarDayFromParts(match) === null) return false;
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6]);
  if (hour > 23 || minute > 59 || second > 59) return false;
  const offset = match[7];
  if (!offset || offset === "Z") return true;
  const [, offsetHour, offsetMinute] = /[+-](\d{2}):(\d{2})/.exec(offset) ?? [];
  return Number(offsetHour) <= 23 && Number(offsetMinute) <= 59;
}
