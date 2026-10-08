export function singleValueFilterReason(availableCount: number, hasActiveSelection: boolean): string | null {
  if (hasActiveSelection) return null;
  if (availableCount === 0) return "No data recorded for this filter in the current results.";
  if (availableCount === 1) return "Only one value is present in the current results.";
  return null;
}
