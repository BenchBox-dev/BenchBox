export function compareIdForRow(row: { result_id: string; short_id?: string | null }): string {
  return row.short_id || row.result_id;
}

export function buildCompareUrl(ids: readonly string[]): string {
  return `/results/compare?ids=${ids.map(encodeURIComponent).join(",")}`;
}

export function displayCompareId(id: string): string {
  return id.length > 12 ? `${id.slice(0, 8)}...` : id;
}
