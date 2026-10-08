import { useState } from "preact/hooks";
import { formatRunAge, formatRunDate } from "@/lib/runAge";

interface RunAgeProps {
  runDate: string | null | undefined;
  reference?: Date;
}

export function RunAge({ runDate, reference }: RunAgeProps) {
  const age = formatRunAge(runDate, reference);
  if (age === null) return null;
  return <span aria-label={`Run age: ${age}`}> · {age}</span>;
}

export function RunDateWithAge({ runDate, reference }: RunAgeProps) {
  return <RunDateChip runDate={runDate} reference={reference} />;
}

interface RunDateChipProps extends RunAgeProps {
  class?: string;
}

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
