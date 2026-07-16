import {
  FACET_KEYS,
  FACET_URL_KEYS,
  dateWindowCutoffIso,
  type DateWindowFacet,
  type FacetKey,
  type FacetState,
} from "@/lib/facetModel";

/**
 * Explicit facet token for rows whose bundle never recorded a tuning mode.
 *
 * No producer emits this value as a real mode; it exists so "not recorded"
 * is a first-class state instead of a null silently coalesced into a
 * real-looking mode. A row with tuning_mode NULL matches a facet selection
 * only when that selection explicitly includes this sentinel (or the legacy
 * "untuned" token still emitted by existing facet chips / URLs).
 */
export const NOT_RECORDED_TUNING_MODE = "not-recorded";

/** Legacy unlabelled-tuning facet token; kept so existing chips and URLs keep matching. */
export const LEGACY_UNLABELLED_TUNING_MODE = "untuned";

export interface FacetMatchRow {
  benchmark?: string | null;
  scale_factor?: string | number | null;
  phase?: string | null;
  test_type?: string | null;
  platform?: string | null;
  platform_id?: string | null;
  execution_mode?: string | null;
  tuning_mode?: string | null;
  trust_label?: string | null;
  validation_status?: string | null;
  deployment_class?: string | null;
  cloud_provider?: string | null;
  cloud_region?: string | null;
  instance_or_warehouse?: string | null;
  storage_format?: string | null;
  cost_status?: string | null;
  run_date?: string | null;
}

export interface FacetMatchOptions {
  keys?: readonly FacetKey[];
  now?: Date;
}

export function singleFacetValue(values: readonly string[], fallback: string): string;
export function singleFacetValue(values: readonly string[], fallback?: null): string | null;
export function singleFacetValue(values: readonly string[], fallback: string | null = null): string | null {
  return values.length === 1 ? (values[0] ?? fallback) : fallback;
}

export function toggleFacetValue(current: readonly string[], value: string): string[] {
  return current.includes(value)
    ? current.filter((entry) => entry !== value)
    : [...current, value];
}

export function toDateWindowFacet(value: string): DateWindowFacet {
  if (value === "30d" || value === "90d" || value === "365d") return value;
  return "all";
}

export function appendFacetParams(params: URLSearchParams, facets: FacetState, omit: ReadonlySet<FacetKey>) {
  for (const key of FACET_KEYS) {
    if (omit.has(key)) continue;
    const value = facets[key];
    if (Array.isArray(value)) {
      if (value.length > 0) params.set(FACET_URL_KEYS[key], value.join(","));
    } else if (value !== "all") {
      params.set(FACET_URL_KEYS[key], value);
    }
  }
}

export function hasActiveFacets(facets: FacetState, keys: readonly FacetKey[]): boolean {
  return keys.some((key) => {
    const value = facets[key];
    return Array.isArray(value) ? value.length > 0 : value !== "all";
  });
}

export function matchesFacetRow(row: FacetMatchRow, facets: FacetState, options: FacetMatchOptions = {}): boolean {
  const keys = options.keys ?? FACET_KEYS;
  for (const key of keys) {
    if (!matchesFacetKey(row, facets, key, options.now)) return false;
  }
  return true;
}

export function matchesDateWindow(runDate: string | null | undefined, value: DateWindowFacet, now?: Date): boolean {
  const cutoff = dateWindowCutoffIso(value, now);
  if (cutoff === null) return true;
  if (!runDate) return false;
  return new Date(runDate).getTime() >= new Date(cutoff).getTime();
}

function matchesFacetKey(row: FacetMatchRow, facets: FacetState, key: FacetKey, now?: Date): boolean {
  switch (key) {
    case "benchmark":
      return matchesRequired(row.benchmark, facets.benchmark);
    case "scale_factor":
      return matchesRequired(row.scale_factor === undefined || row.scale_factor === null ? null : String(row.scale_factor), facets.scale_factor);
    case "phase":
      return matchesOptional(row.test_type ?? row.phase, facets.phase);
    case "platform":
      return matchesPlatform(row, facets.platform);
    case "execution_mode":
      return matchesOptional(row.execution_mode, facets.execution_mode);
    case "tuning_mode":
      return matchesTuningMode(row.tuning_mode, facets.tuning_mode);
    case "trust_tier":
      return matchesRequired(row.trust_label, facets.trust_tier);
    case "validation_status":
      return matchesOptional(row.validation_status, facets.validation_status);
    case "deployment_class":
      return matchesOptional(row.deployment_class, facets.deployment_class);
    case "cloud_provider":
      return matchesOptional(row.cloud_provider, facets.cloud_provider);
    case "cloud_region":
      return matchesOptional(row.cloud_region, facets.cloud_region);
    case "instance_or_warehouse":
      return matchesOptional(row.instance_or_warehouse, facets.instance_or_warehouse);
    case "storage_format":
      return matchesOptional(row.storage_format, facets.storage_format);
    case "cost_status":
      return matchesOptional(row.cost_status, facets.cost_status);
    case "date_window":
      return matchesDateWindow(row.run_date, facets.date_window, now);
  }
}

function matchesTuningMode(value: string | null | undefined, selected: readonly string[]): boolean {
  if (selected.length === 0) return true;
  if (value === null || value === undefined) {
    // Not-recorded rows match only an explicit not-recorded selection --
    // never a real mode. The legacy "untuned" token keeps existing chip
    // values and bookmarked URLs matching the same rows as before.
    return selected.includes(NOT_RECORDED_TUNING_MODE) || selected.includes(LEGACY_UNLABELLED_TUNING_MODE);
  }
  return selected.includes(value);
}

function matchesRequired(value: string | null | undefined, selected: readonly string[]): boolean {
  return selected.length === 0 || (value !== null && value !== undefined && selected.includes(value));
}

function matchesOptional(value: string | null | undefined, selected: readonly string[]): boolean {
  return selected.length === 0 || (value !== null && value !== undefined && selected.includes(value));
}

function matchesPlatform(row: FacetMatchRow, selected: readonly string[]): boolean {
  if (selected.length === 0) return true;
  return (
    (row.platform !== null && row.platform !== undefined && selected.includes(row.platform)) ||
    (row.platform_id !== null && row.platform_id !== undefined && selected.includes(row.platform_id))
  );
}
