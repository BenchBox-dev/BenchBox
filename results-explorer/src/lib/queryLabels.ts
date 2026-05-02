const QUERY_ID_COLLATOR = new Intl.Collator(undefined, {
  numeric: true,
  sensitivity: "base",
});

export function compareQueryIds(a: string, b: string): number {
  return QUERY_ID_COLLATOR.compare(a, b) || a.localeCompare(b);
}

export function sortQueryIds(queryIds: readonly string[]): string[] {
  return [...queryIds].sort(compareQueryIds);
}

export function queryDisplayLabel(queryId: string): string {
  return queryId;
}
