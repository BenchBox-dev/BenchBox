const QUERY_ID_COLLATOR = new Intl.Collator(undefined, {
  numeric: true,
  sensitivity: "base",
});

export function compareQueryIds(a: string, b: string): number {
  return QUERY_ID_COLLATOR.compare(a, b) || a.localeCompare(b);
}

/**
 * Sort and deduplicate query identifiers.
 *
 * Dedup is defensive: callers (RankTable, QueryHeatmap, QueryHistogram) use
 * the result both for column ordering AND as React keys. A duplicate id in
 * the input would produce React key collisions and break reconciliation,
 * which is the bug class captured in
 * `_project/blind-spots/2026-04-29-143205-react-key-collision-class.md`.
 * Stable order on duplicates would not have helped there: only one of the
 * duplicates can ever survive as a column, so the right answer is to drop
 * the duplicates at the boundary rather than push composite-key gymnastics
 * into every column-iterating component.
 */
export function sortQueryIds(queryIds: readonly string[]): string[] {
  const seen = new Set<string>();
  const unique: string[] = [];
  for (const id of queryIds) {
    if (seen.has(id)) continue;
    seen.add(id);
    unique.push(id);
  }
  return unique.sort(compareQueryIds);
}

export function queryDisplayLabel(queryId: string): string {
  return queryId;
}
