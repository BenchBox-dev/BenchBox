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
