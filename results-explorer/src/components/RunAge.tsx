import { useState } from "preact/hooks";
import { formatRunAge, formatRunDate } from "@/lib/runAge";

interface RunAgeProps {
  runDate: string | null | undefined;
  reference?: Date;
}

/** Displays a safe, reader-facing age next to a separately rendered run date. */
export function RunAge({ runDate, reference }: RunAgeProps) {
  const age = formatRunAge(runDate, reference);
  if (age === null) return null;
  return <span aria-label={`Run age: ${age}`}> · {age}</span>;
}

/** Displays a run's UTC calendar date together with its informational age. */
export function RunDateWithAge({ runDate, reference }: RunAgeProps) {
  const age = formatRunAge(runDate, reference);
  return (
    <span>
      {formatRunDate(runDate)}
      {age !== null && <span aria-label={`Run age: ${age}`}> · {age}</span>}
    </span>
  );
}

interface RunDateChipProps extends RunAgeProps {
  class?: string;
}

/**
 * The site-wide treatment for a run date.
 *
 * A run date and its age are two readings of one value, so they share one
 * chip rather than being concatenated into a phrase that wraps mid-value in
 * every table cell and chart label that carries it. The chip shows the
 * calendar date - the stable, sortable reading - and swaps to the age when
 * activated. Both readings are always in the accessible name and the title,
 * so neither reading is behind an interaction for assistive technology.
 */
export function RunDateChip({ runDate, reference, class: extraClass = "" }: RunDateChipProps) {
  const [showAge, setShowAge] = useState(false);
  const date = formatRunDate(runDate);
  const age = formatRunAge(runDate, reference);

  if (age === null) {
    return (
      <span class={`bb-meta-chip ${extraClass}`} data-testid="run-date-chip">
        {date}
      </span>
    );
  }

  const both = `${date} (${age})`;
  return (
    <button
      type="button"
      class={`bb-meta-chip ${extraClass}`}
      data-testid="run-date-chip"
      data-showing={showAge ? "age" : "date"}
      title={both}
      aria-label={`Run date ${both}. Activate to switch between the date and its age.`}
      onClick={(event) => {
        event.stopPropagation();
        event.preventDefault();
        setShowAge((value) => !value);
      }}
    >
      {showAge ? age : date}
    </button>
  );
}
