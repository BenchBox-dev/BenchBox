import { formatRunDateWithAge } from "@/lib/runAge";

export const MAX_COMPARE_SELECTIONS = 4;

export interface ResultLinkSource {
  result_id: string;
  short_id?: string | null;
  platform?: string | null;
  run_date?: string | null;
}

export function compareIdForRow(row: { result_id: string; short_id?: string | null }): string {
  return row.short_id || row.result_id;
}

export function resultDetailHref(rowOrId: ResultLinkSource | string): string {
  return `/results/r/${typeof rowOrId === "string" ? rowOrId : rowOrId.result_id}`;
}

export function resultReceiptHref(rowOrId: ResultLinkSource | string): string {
  return `${resultDetailHref(rowOrId)}#run-receipt`;
}

export function publicResultIdToken(resultId: string): string {
  const parts = resultId.split(/[-_./:]+/).filter(Boolean);
  const tail = parts.at(-1);
  return tail && /^[0-9a-f]{8,}$/i.test(tail) ? tail : resultId;
}

export function visibleResultIdForRow(row: ResultLinkSource): string {
  return publicResultIdToken(row.result_id);
}

export function resultIdentityAriaLabel(row: ResultLinkSource, target: "details" | "receipt"): string {
  const platform = row.platform ? `${row.platform} ` : "";
  const date = row.run_date ? ` from ${formatRunDateWithAge(row.run_date)}` : "";
  return `Open ${target} for ${platform}public ID ${visibleResultIdForRow(row)}${date}`;
}

export function buildCompareUrl(ids: readonly string[]): string {
  return `/results/compare?ids=${ids.map(encodeURIComponent).join(",")}`;
}

export function displayCompareId(id: string): string {
  return id.length > 12 ? `${id.slice(0, 8)}...` : id;
}

/**
 * Bounds on a within-run comparison, mirroring MAX_COMPARE_SELECTIONS.
 *
 * Two is the floor because one basis is not a comparison; four is the ceiling
 * because the layout has to stay readable at mobile width, the same reason the
 * cross-run limit exists.
 */
export const MIN_WITHIN_RUN_BASES = 2;
export const MAX_WITHIN_RUN_BASES = 4;

/**
 * Link to the within-run compare route.
 *
 * A SEPARATE route from `/results/compare`, not a mode of it. The two answer
 * different questions and obey different rules: a cross-run comparison must
 * hold exactly one basis, while this route exists precisely so the basis can
 * vary. Sharing a path would put both rule sets on one page and invite the
 * cross-run invariant to be relaxed "just for this case".
 *
 * `bases` uses the model's own comma-separated grammar; `ref` names which
 * column the ratios are measured against, by index into that list.
 */
export function withinRunCompareHref(
  resultId: string,
  encodedBases: readonly string[],
  referenceIndex = 0,
): string {
  const bases = encodedBases.join(",");
  const ref = Math.min(Math.max(0, referenceIndex), Math.max(0, encodedBases.length - 1));
  return `/results/r/${encodeURIComponent(resultId)}/passes?bases=${encodeURIComponent(bases)}&ref=${ref}`;
}

/**
 * Keep a reference index valid as columns are added and removed.
 *
 * Returning a clamped index rather than resetting to 0 preserves the user's
 * choice wherever it still exists: removing the last column should not silently
 * re-baseline a comparison the reader was in the middle of reading.
 */
export function clampReferenceIndex(referenceIndex: number, columnCount: number): number {
  if (columnCount <= 0) return 0;
  if (!Number.isFinite(referenceIndex)) return 0;
  return Math.min(Math.max(0, Math.trunc(referenceIndex)), columnCount - 1);
}
