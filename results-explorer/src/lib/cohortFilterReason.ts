/**
 * Reason a cohort filter's select cannot be changed, or `null` when the
 * filter is enabled.
 *
 * Filters on the Benchmark and Platform result pages stay mounted at all
 * times (a filter that pops in and out of existence as other filters narrow
 * the cohort is disorienting), but one offering no real choice is disabled
 * with an explanation rather than hidden. A filter with an active selection
 * stays enabled even at zero or one remaining option, so it's never
 * impossible to see or clear.
 */
export function singleValueFilterReason(availableCount: number, hasActiveSelection: boolean): string | null {
  if (hasActiveSelection) return null;
  if (availableCount === 0) return "No data recorded for this filter in the current results.";
  if (availableCount === 1) return "Only one value is present in the current results.";
  return null;
}
