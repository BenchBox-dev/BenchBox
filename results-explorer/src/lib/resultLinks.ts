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
  const date = row.run_date ? ` from ${row.run_date.slice(0, 10)}` : "";
  return `Open ${target} for ${platform}public ID ${visibleResultIdForRow(row)}${date}`;
}

export function buildCompareUrl(ids: readonly string[]): string {
  return `/results/compare?ids=${ids.map(encodeURIComponent).join(",")}`;
}

export function displayCompareId(id: string): string {
  return id.length > 12 ? `${id.slice(0, 8)}...` : id;
}
