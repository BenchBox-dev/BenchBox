import { useCallback, useEffect, useMemo, useState } from "preact/hooks";
import type { UrlSerde } from "@/lib/useUrlState";

export const FACET_KEYS = [
  "benchmark",
  "scale_factor",
  "phase",
  "platform",
  "execution_mode",
  "tuning_mode",
  "trust_tier",
  "validation_status",
  "deployment_class",
  "cloud_provider",
  "cloud_region",
  "instance_or_warehouse",
  "storage_format",
  "cost_status",
  "date_window",
] as const;

export type FacetKey = (typeof FACET_KEYS)[number];
export type DateWindowFacet = "all" | "30d" | "90d" | "365d";

export interface FacetState {
  benchmark: string[];
  scale_factor: string[];
  phase: string[];
  platform: string[];
  execution_mode: string[];
  tuning_mode: string[];
  trust_tier: string[];
  validation_status: string[];
  deployment_class: string[];
  cloud_provider: string[];
  cloud_region: string[];
  instance_or_warehouse: string[];
  storage_format: string[];
  cost_status: string[];
  date_window: DateWindowFacet;
}

export type PartialFacetState = Partial<{
  [K in FacetKey]: FacetState[K];
}>;

export interface FacetWhereClause {
  sql: string;
  params: unknown[];
}

export interface UseFacetStateResult {
  facets: FacetState;
  where: FacetWhereClause;
  setFacet: <K extends FacetKey>(key: K, value: FacetState[K]) => void;
  resetFacets: () => void;
}

export const DEFAULT_FACETS: FacetState = {
  benchmark: [],
  scale_factor: [],
  phase: [],
  platform: [],
  execution_mode: [],
  tuning_mode: [],
  trust_tier: [],
  validation_status: [],
  deployment_class: [],
  cloud_provider: [],
  cloud_region: [],
  instance_or_warehouse: [],
  storage_format: [],
  cost_status: [],
  date_window: "all",
};

export const FACET_URL_KEYS: Record<FacetKey, string> = {
  benchmark: "benchmark",
  scale_factor: "sf",
  phase: "phase",
  platform: "platform",
  execution_mode: "execution",
  tuning_mode: "tuning",
  trust_tier: "trust",
  validation_status: "validation",
  deployment_class: "deployment",
  cloud_provider: "cloud_provider",
  cloud_region: "cloud_region",
  instance_or_warehouse: "shape",
  storage_format: "storage_format",
  cost_status: "cost_status",
  date_window: "window",
};

export const FACET_URL_ALIASES: Partial<Record<FacetKey, readonly string[]>> = {
  benchmark: ["bm"],
  scale_factor: ["scale_factor"],
  execution_mode: ["execution_mode"],
  trust_tier: ["trust_tier"],
  validation_status: ["validation_status"],
  deployment_class: ["deployment_class"],
  instance_or_warehouse: ["instance_type", "warehouse_size"],
  date_window: ["date_window"],
};

const DATE_WINDOWS = new Set<DateWindowFacet>(["all", "30d", "90d", "365d"]);
const DATE_WINDOW_DAYS: Record<Exclude<DateWindowFacet, "all">, number> = {
  "30d": 30,
  "90d": 90,
  "365d": 365,
};
const LEGACY_ALL_SENTINEL_KEYS = new Set<FacetKey>(["phase", "tuning_mode", "trust_tier"]);
const FACET_FILTER_COLUMNS = {
  deployment_class: "deployment_class",
  cloud_provider: "cloud_provider",
  cloud_region: "cloud_region",
  instance_or_warehouse: "instance_or_warehouse",
  storage_format: "storage_format",
  cost_status: "cost_status",
} as const satisfies Partial<Record<FacetKey, string>>;

const multiValueSerde: UrlSerde<string[]> = {
  encode: (values) => normalizeStringList(values).join(","),
  decode: (raw) => normalizeStringList(raw === "" ? [] : raw.split(",")),
};

const dateWindowSerde: UrlSerde<DateWindowFacet> = {
  encode: (value) => value,
  decode: (raw) => (DATE_WINDOWS.has(raw as DateWindowFacet) ? (raw as DateWindowFacet) : null),
};

export const FACET_URL_SERDES = {
  benchmark: multiValueSerde,
  scale_factor: multiValueSerde,
  phase: multiValueSerde,
  platform: multiValueSerde,
  execution_mode: multiValueSerde,
  tuning_mode: multiValueSerde,
  trust_tier: multiValueSerde,
  validation_status: multiValueSerde,
  deployment_class: multiValueSerde,
  cloud_provider: multiValueSerde,
  cloud_region: multiValueSerde,
  instance_or_warehouse: multiValueSerde,
  storage_format: multiValueSerde,
  cost_status: multiValueSerde,
  date_window: dateWindowSerde,
} satisfies { [K in FacetKey]: UrlSerde<FacetState[K]> };

export function normalizeFacetState(input: PartialFacetState = {}): FacetState {
  return {
    benchmark: normalizeFacetList("benchmark", input.benchmark ?? DEFAULT_FACETS.benchmark),
    scale_factor: normalizeFacetList("scale_factor", input.scale_factor ?? DEFAULT_FACETS.scale_factor),
    phase: normalizeFacetList("phase", input.phase ?? DEFAULT_FACETS.phase),
    platform: normalizeFacetList("platform", input.platform ?? DEFAULT_FACETS.platform),
    execution_mode: normalizeFacetList("execution_mode", input.execution_mode ?? DEFAULT_FACETS.execution_mode),
    tuning_mode: normalizeFacetList("tuning_mode", input.tuning_mode ?? DEFAULT_FACETS.tuning_mode),
    trust_tier: normalizeFacetList("trust_tier", input.trust_tier ?? DEFAULT_FACETS.trust_tier),
    validation_status: normalizeFacetList(
      "validation_status",
      input.validation_status ?? DEFAULT_FACETS.validation_status,
    ),
    deployment_class: normalizeFacetList(
      "deployment_class",
      input.deployment_class ?? DEFAULT_FACETS.deployment_class,
    ),
    cloud_provider: normalizeFacetList("cloud_provider", input.cloud_provider ?? DEFAULT_FACETS.cloud_provider),
    cloud_region: normalizeFacetList("cloud_region", input.cloud_region ?? DEFAULT_FACETS.cloud_region),
    instance_or_warehouse: normalizeFacetList(
      "instance_or_warehouse",
      input.instance_or_warehouse ?? DEFAULT_FACETS.instance_or_warehouse,
    ),
    storage_format: normalizeFacetList("storage_format", input.storage_format ?? DEFAULT_FACETS.storage_format),
    cost_status: normalizeFacetList("cost_status", input.cost_status ?? DEFAULT_FACETS.cost_status),
    date_window: DATE_WINDOWS.has(input.date_window as DateWindowFacet)
      ? (input.date_window as DateWindowFacet)
      : DEFAULT_FACETS.date_window,
  };
}

export function readFacetParam<K extends FacetKey>(
  params: URLSearchParams,
  key: K,
): FacetState[K] {
  const fallback = defaultFacetValue(key);
  const serde = FACET_URL_SERDES[key] as unknown as UrlSerde<FacetState[K]>;
  const canonicalKey = FACET_URL_KEYS[key];
  const aliases = FACET_URL_ALIASES[key] ?? [];

  // w16: when the canonical URL key is absent and multiple legacy aliases
  // are present, merge their values into the canonical list rather than
  // keeping only the first hit. Example: `?instance_type=foo&warehouse_size=bar`
  // for `instance_or_warehouse` previously kept just one and silently dropped
  // the other on the next mount; now both flow through.
  if (params.get(canonicalKey) === null && aliases.length > 0) {
    const aliasRaws = aliases
      .map((alias) => params.get(alias))
      .filter((value): value is string => value !== null);
    if (aliasRaws.length > 0) {
      const decodedValues = aliasRaws
        .map((raw) => serde.decode(raw))
        .filter((value): value is FacetState[K] => value !== null);
      if (decodedValues.length === 0) return fallback;
      // For array-valued facets, concatenate then dedupe; for scalar facets
      // (e.g. date_window) the first decoded value wins, matching the
      // pre-w16 single-source behavior since they don't have multi-alias
      // arrays in practice.
      const first = decodedValues[0]!;
      if (Array.isArray(first)) {
        const merged: string[] = [];
        const seen = new Set<string>();
        for (const decoded of decodedValues as unknown as readonly string[][]) {
          for (const item of decoded) {
            if (!seen.has(item)) {
              seen.add(item);
              merged.push(item);
            }
          }
        }
        return normalizeFacetValue(key, merged as FacetState[K]);
      }
      return normalizeFacetValue(key, first);
    }
  }

  const raw = findFirstParam(params, [canonicalKey, ...aliases]);
  if (raw === null) return fallback;
  const decoded = serde.decode(raw);
  return decoded === null ? fallback : normalizeFacetValue(key, decoded);
}

export function useFacetState(): UseFacetStateResult {
  const [benchmark, setBenchmark] = useFacetUrlState("benchmark");
  const [scaleFactor, setScaleFactor] = useFacetUrlState("scale_factor");
  const [phase, setPhase] = useFacetUrlState("phase");
  const [platform, setPlatform] = useFacetUrlState("platform");
  const [executionMode, setExecutionMode] = useFacetUrlState("execution_mode");
  const [tuningMode, setTuningMode] = useFacetUrlState("tuning_mode");
  const [trustTier, setTrustTier] = useFacetUrlState("trust_tier");
  const [validationStatus, setValidationStatus] = useFacetUrlState("validation_status");
  const [deploymentClass, setDeploymentClass] = useFacetUrlState("deployment_class");
  const [cloudProvider, setCloudProvider] = useFacetUrlState("cloud_provider");
  const [cloudRegion, setCloudRegion] = useFacetUrlState("cloud_region");
  const [instanceOrWarehouse, setInstanceOrWarehouse] = useFacetUrlState("instance_or_warehouse");
  const [storageFormat, setStorageFormat] = useFacetUrlState("storage_format");
  const [costStatus, setCostStatus] = useFacetUrlState("cost_status");
  const [dateWindow, setDateWindow] = useFacetUrlState("date_window");

  const facets = useMemo<FacetState>(
    () => ({
      benchmark,
      scale_factor: scaleFactor,
      phase,
      platform,
      execution_mode: executionMode,
      tuning_mode: tuningMode,
      trust_tier: trustTier,
      validation_status: validationStatus,
      deployment_class: deploymentClass,
      cloud_provider: cloudProvider,
      cloud_region: cloudRegion,
      instance_or_warehouse: instanceOrWarehouse,
      storage_format: storageFormat,
      cost_status: costStatus,
      date_window: dateWindow,
    }),
    [
      benchmark,
      cloudProvider,
      cloudRegion,
      costStatus,
      dateWindow,
      deploymentClass,
      executionMode,
      instanceOrWarehouse,
      phase,
      platform,
      scaleFactor,
      storageFormat,
      trustTier,
      tuningMode,
      validationStatus,
    ],
  );
  const where = useMemo(() => facetsToWhereClause(facets), [facets]);

  function setFacet<K extends FacetKey>(key: K, value: FacetState[K]) {
    const setters = {
      benchmark: setBenchmark,
      scale_factor: setScaleFactor,
      phase: setPhase,
      platform: setPlatform,
      execution_mode: setExecutionMode,
      tuning_mode: setTuningMode,
      trust_tier: setTrustTier,
      validation_status: setValidationStatus,
      deployment_class: setDeploymentClass,
      cloud_provider: setCloudProvider,
      cloud_region: setCloudRegion,
      instance_or_warehouse: setInstanceOrWarehouse,
      storage_format: setStorageFormat,
      cost_status: setCostStatus,
      date_window: setDateWindow,
    } satisfies { [Facet in FacetKey]: (next: FacetState[Facet]) => void };
    (setters[key] as (next: FacetState[K]) => void)(value);
  }

  function resetFacets() {
    for (const key of FACET_KEYS) {
      setFacet(key, defaultFacetValue(key));
    }
  }

  return { facets, where, setFacet, resetFacets };
}

export function useFacetField<K extends FacetKey>(key: K): [FacetState[K], (value: FacetState[K]) => void] {
  return useFacetUrlState(key);
}

export function facetsToWhereClause(
  input: PartialFacetState = {},
  options: { now?: Date } = {},
): FacetWhereClause {
  const facets = normalizeFacetState(input);
  const clauses: string[] = [];
  const params: unknown[] = [];

  addListClause("benchmark", facets.benchmark, clauses, params);
  addNumericListClause("scale_factor", facets.scale_factor, clauses, params);
  addListClause("test_type", facets.phase, clauses, params);
  addPlatformClause(facets.platform, clauses, params);
  addListClause("execution_mode", facets.execution_mode, clauses, params);
  addNullableSentinelClause("tuning_mode", facets.tuning_mode, "untuned", clauses, params);
  addListClause("trust_label", facets.trust_tier, clauses, params);
  addListClause("validation_status", facets.validation_status, clauses, params);
  addListClause(FACET_FILTER_COLUMNS.deployment_class, facets.deployment_class, clauses, params);
  addListClause(FACET_FILTER_COLUMNS.cloud_provider, facets.cloud_provider, clauses, params);
  addListClause(FACET_FILTER_COLUMNS.cloud_region, facets.cloud_region, clauses, params);
  addListClause(FACET_FILTER_COLUMNS.instance_or_warehouse, facets.instance_or_warehouse, clauses, params);
  addListClause(FACET_FILTER_COLUMNS.storage_format, facets.storage_format, clauses, params);
  addListClause(FACET_FILTER_COLUMNS.cost_status, facets.cost_status, clauses, params);

  const cutoff = dateWindowCutoffIso(facets.date_window, options.now);
  if (cutoff !== null) {
    clauses.push("run_date >= ?");
    params.push(cutoff);
  }

  return {
    sql: clauses.length > 0 ? `WHERE ${clauses.join(" AND ")}` : "",
    params,
  };
}

function normalizeStringList(values: readonly string[]): string[] {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))];
}

function normalizeFacetList(key: FacetKey, values: readonly string[]): string[] {
  const normalized = normalizeStringList(values);
  if (!LEGACY_ALL_SENTINEL_KEYS.has(key)) return normalized;
  return normalized.filter((value) => value !== "all");
}

function normalizeFacetValue<K extends FacetKey>(key: K, value: FacetState[K]): FacetState[K] {
  if (!Array.isArray(value)) return value;
  return normalizeFacetList(key, value) as FacetState[K];
}

function useFacetUrlState<K extends FacetKey>(key: K): [FacetState[K], (value: FacetState[K]) => void] {
  const [value, setValueRaw] = useState<FacetState[K]>(() => initialFacetValue(key));

  useEffect(() => {
    if (typeof window === "undefined") return;
    writeFacetParam(key, readFacetParam(new URLSearchParams(window.location.search), key));
  }, [key]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    function onPopState() {
      setValueRaw(readFacetParam(new URLSearchParams(window.location.search), key));
    }
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [key]);

  const setValue = useCallback(
    (next: FacetState[K]) => {
      setValueRaw(next);
      writeFacetParam(key, next);
    },
    [key],
  );

  return [value, setValue];
}

function initialFacetValue<K extends FacetKey>(key: K): FacetState[K] {
  if (typeof window === "undefined") return defaultFacetValue(key);
  return readFacetParam(new URLSearchParams(window.location.search), key);
}

function defaultFacetValue<K extends FacetKey>(key: K): FacetState[K] {
  const value = DEFAULT_FACETS[key];
  return (Array.isArray(value) ? [...value] : value) as FacetState[K];
}

function writeFacetParam<K extends FacetKey>(key: K, value: FacetState[K]) {
  if (typeof window === "undefined") return;
  const params = new URLSearchParams(window.location.search);
  const originalSearch = params.toString();
  const urlKey = FACET_URL_KEYS[key];
  const aliases = FACET_URL_ALIASES[key] ?? [];
  const serde = FACET_URL_SERDES[key] as unknown as UrlSerde<FacetState[K]>;
  const encoded = serde.encode(value);
  const encodedDefault = serde.encode(defaultFacetValue(key));

  for (const alias of aliases) {
    params.delete(alias);
  }
  if (encoded === "" || encoded === encodedDefault) {
    params.delete(urlKey);
  } else {
    params.set(urlKey, encoded);
  }
  if (params.toString() !== originalSearch) replaceSearch(params);
}

function replaceSearch(params: URLSearchParams) {
  const newSearch = params.toString();
  const search = newSearch.length > 0 ? `?${newSearch}` : "";
  history.replaceState(null, "", `${window.location.pathname}${search}${window.location.hash}`);
}

function findFirstParam(params: URLSearchParams, keys: readonly string[]): string | null {
  for (const key of keys) {
    const value = params.get(key);
    if (value !== null) return value;
  }
  return null;
}

function addListClause(
  column: string,
  values: readonly string[],
  clauses: string[],
  params: unknown[],
) {
  if (values.length === 0) return;
  clauses.push(`${column} IN (${values.map(() => "?").join(", ")})`);
  params.push(...values);
}

function addNumericListClause(
  column: string,
  values: readonly string[],
  clauses: string[],
  params: unknown[],
) {
  const numericValues = values.map((value) => Number(value)).filter((value) => Number.isFinite(value));
  if (numericValues.length === 0) return;
  clauses.push(`${column} IN (${numericValues.map(() => "?").join(", ")})`);
  params.push(...numericValues);
}

function addPlatformClause(values: readonly string[], clauses: string[], params: unknown[]) {
  if (values.length === 0) return;
  const placeholders = values.map(() => "?").join(", ");
  clauses.push(`(platform IN (${placeholders}) OR platform_id IN (${placeholders}))`);
  params.push(...values, ...values);
}

function addNullableSentinelClause(
  column: string,
  values: readonly string[],
  nullSentinel: string,
  clauses: string[],
  params: unknown[],
) {
  if (values.length === 0) return;
  const concreteValues = values.filter((value) => value !== nullSentinel);
  const subclauses: string[] = [];
  if (concreteValues.length > 0) {
    subclauses.push(`${column} IN (${concreteValues.map(() => "?").join(", ")})`);
    params.push(...concreteValues);
  }
  if (values.includes(nullSentinel)) {
    subclauses.push(`${column} IS NULL`);
  }
  if (subclauses.length > 0) clauses.push(`(${subclauses.join(" OR ")})`);
}

function dateWindowCutoffIso(value: DateWindowFacet, now = new Date()): string | null {
  if (value === "all") return null;
  const days = DATE_WINDOW_DAYS[value];
  return new Date(now.getTime() - days * 24 * 60 * 60 * 1000).toISOString();
}
