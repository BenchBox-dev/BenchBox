export interface CompareIdPlan {
  retained: string[];
  duplicates: string[];
  overflow: string[];
}

export interface RecoveredCompareResult<T> {
  requestedId: string;
  resolvedId: string;
  detail: T;
}

export interface ConfirmedMissingCompareResult {
  requestedId: string;
  resolvedId: string;
}

export interface FailedCompareResult {
  requestedId: string;
  error: unknown;
}

export interface CompareRecoveryResult<T> {
  duplicates: string[];
  aliases: string[];
  overflow: string[];
  recovered: RecoveredCompareResult<T>[];
  missing: ConfirmedMissingCompareResult[];
  failed: FailedCompareResult[];
}

interface CompareRecoveryDependencies<T> {
  resolveId: (requestedId: string) => Promise<string>;
  loadResult: (resolvedId: string) => Promise<T | null>;
  isCancelled?: () => boolean;
}

type ResolvedId =
  | { requestedId: string; resolvedId: string; error: null }
  | { requestedId: string; resolvedId: null; error: unknown };

export function planCompareIds(rawIds: string[], limit: number): CompareIdPlan {
  const unique: string[] = [];
  const duplicates: string[] = [];
  const seen = new Set<string>();
  for (const rawId of rawIds) {
    const id = rawId.trim();
    if (!id) continue;
    if (seen.has(id)) {
      duplicates.push(id);
      continue;
    }
    seen.add(id);
    unique.push(id);
  }
  return {
    retained: unique.slice(0, limit),
    duplicates,
    overflow: unique.slice(limit),
  };
}

export async function recoverCompareResults<T>(
  rawIds: string[],
  limit: number,
  dependencies: CompareRecoveryDependencies<T>,
): Promise<CompareRecoveryResult<T> | null> {
  // Do not apply the comparison limit until aliases have resolved. A short ID
  // and its long-form alias consume one slot, not two.
  const initialPlan = planCompareIds(rawIds, rawIds.length);
  const resolved = await Promise.all(
    initialPlan.retained.map(async (requestedId): Promise<ResolvedId> => {
      try {
        return { requestedId, resolvedId: await dependencies.resolveId(requestedId), error: null };
      } catch (error) {
        return { requestedId, resolvedId: null, error };
      }
    }),
  );
  // Match the page effect's original boundary: once ID resolution finishes,
  // do not begin detail reads for a superseded URL or unmounted component.
  if (dependencies.isCancelled?.()) return null;

  const resolvedSeen = new Set<string>();
  const aliases: string[] = [];
  const deduplicated = resolved.filter((entry) => {
    if (entry.resolvedId === null) return true;
    if (resolvedSeen.has(entry.resolvedId)) {
      aliases.push(entry.requestedId);
      return false;
    }
    resolvedSeen.add(entry.resolvedId);
    return true;
  });
  const retained = deduplicated.slice(0, limit);
  const overflow = deduplicated.slice(limit).map((entry) => entry.requestedId);
  const failed: FailedCompareResult[] = retained.flatMap((entry) =>
    entry.error === null ? [] : [{ requestedId: entry.requestedId, error: entry.error }],
  );
  const candidates = retained.filter(
    (entry): entry is { requestedId: string; resolvedId: string; error: null } =>
      entry.resolvedId !== null,
  );
  const loaded = await Promise.all(
    candidates.map(async (entry) => {
      try {
        return { ...entry, detail: await dependencies.loadResult(entry.resolvedId), error: null };
      } catch (error) {
        return { ...entry, detail: null, error };
      }
    }),
  );

  const recovered: RecoveredCompareResult<T>[] = [];
  const missing: ConfirmedMissingCompareResult[] = [];
  for (const entry of loaded) {
    if (entry.error !== null) {
      failed.push({ requestedId: entry.requestedId, error: entry.error });
    } else if (entry.detail === null) {
      missing.push({ requestedId: entry.requestedId, resolvedId: entry.resolvedId });
    } else {
      recovered.push({
        requestedId: entry.requestedId,
        resolvedId: entry.resolvedId,
        detail: entry.detail,
      });
    }
  }

  return {
    duplicates: initialPlan.duplicates,
    aliases,
    overflow,
    recovered,
    missing,
    failed,
  };
}

export function shouldPreserveMultiSelectionUrl(
  rawIds: string[],
  recoveredCount: number,
  limit: number,
): boolean {
  return recoveredCount < 2 && planCompareIds(rawIds, limit).retained.length > 1;
}
