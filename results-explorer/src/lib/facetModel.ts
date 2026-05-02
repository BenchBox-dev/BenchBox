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
    benchmark: normalizeStringList(input.benchmark ?? DEFAULT_FACETS.benchmark),
    scale_factor: normalizeStringList(input.scale_factor ?? DEFAULT_FACETS.scale_factor),
    phase: normalizeStringList(input.phase ?? DEFAULT_FACETS.phase),
    platform: normalizeStringList(input.platform ?? DEFAULT_FACETS.platform),
    execution_mode: normalizeStringList(input.execution_mode ?? DEFAULT_FACETS.execution_mode),
    tuning_mode: normalizeStringList(input.tuning_mode ?? DEFAULT_FACETS.tuning_mode),
    trust_tier: normalizeStringList(input.trust_tier ?? DEFAULT_FACETS.trust_tier),
    validation_status: normalizeStringList(input.validation_status ?? DEFAULT_FACETS.validation_status),
    deployment_class: normalizeStringList(input.deployment_class ?? DEFAULT_FACETS.deployment_class),
    cloud_provider: normalizeStringList(input.cloud_provider ?? DEFAULT_FACETS.cloud_provider),
    cloud_region: normalizeStringList(input.cloud_region ?? DEFAULT_FACETS.cloud_region),
    instance_or_warehouse: normalizeStringList(
      input.instance_or_warehouse ?? DEFAULT_FACETS.instance_or_warehouse,
    ),
    storage_format: normalizeStringList(input.storage_format ?? DEFAULT_FACETS.storage_format),
    cost_status: normalizeStringList(input.cost_status ?? DEFAULT_FACETS.cost_status),
    date_window: DATE_WINDOWS.has(input.date_window as DateWindowFacet)
      ? (input.date_window as DateWindowFacet)
      : DEFAULT_FACETS.date_window,
  };
}

export function readFacetParam<K extends FacetKey>(
  params: URLSearchParams,
  key: K,
): FacetState[K] {
  const raw = findFirstParam(params, [FACET_URL_KEYS[key], ...(FACET_URL_ALIASES[key] ?? [])]);
  const fallback = defaultFacetValue(key);
  if (raw === null) return fallback;
  const serde = FACET_URL_SERDES[key] as unknown as UrlSerde<FacetState[K]>;
  return serde.decode(raw) ?? fallback;
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
  addListClause("platform", facets.platform, clauses, params);
  addListClause("execution_mode", facets.execution_mode, clauses, params);
  addListClause("tuning_mode", facets.tuning_mode, clauses, params);
  addListClause("trust_label", facets.trust_tier, clauses, params);
  addListClause("validation_status", facets.validation_status, clauses, params);
  addDeploymentClause(facets.deployment_class, clauses, params);
  addListClause("cloud_provider", facets.cloud_provider, clauses, params);
  addListClause("cloud_region", facets.cloud_region, clauses, params);
  addListClause(
    "COALESCE(instance_type, warehouse_size, cluster_size)",
    facets.instance_or_warehouse,
    clauses,
    params,
  );
  addListClause("storage_format", facets.storage_format, clauses, params);
  addListClause("cost_status", facets.cost_status, clauses, params);

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

function defaultFacetValue<K extends FacetKey>(key: K): FacetState[K] {
  const value = DEFAULT_FACETS[key];
  return (Array.isArray(value) ? [...value] : value) as FacetState[K];
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

function addDeploymentClause(
  values: readonly string[],
  clauses: string[],
  params: unknown[],
) {
  const deploymentClauses: string[] = [];
  const deploymentParams: unknown[] = [];

  for (const value of values) {
    if (value === "cloud") {
      deploymentClauses.push("cloud_provider IS NOT NULL");
    } else if (value === "local") {
      deploymentClauses.push("cost_status = ?");
      deploymentParams.push("not_applicable_local");
    } else if (value === "unavailable") {
      deploymentClauses.push("cost_status = ?");
      deploymentParams.push("unavailable");
    }
  }

  if (deploymentClauses.length === 0) return;
  clauses.push(`(${deploymentClauses.join(" OR ")})`);
  params.push(...deploymentParams);
}

function dateWindowCutoffIso(value: DateWindowFacet, now = new Date()): string | null {
  if (value === "all") return null;
  const days = DATE_WINDOW_DAYS[value];
  return new Date(now.getTime() - days * 24 * 60 * 60 * 1000).toISOString();
}
