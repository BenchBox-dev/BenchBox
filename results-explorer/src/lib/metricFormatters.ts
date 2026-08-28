export type MetricDisplayContext = "table" | "chart" | "axis" | "tooltip" | "receipt" | "export";
export type SpeedupUnit = "x" | "×";

export interface MetricFormatResult {
  valueText: string;
  unitText: string | null;
  accessibleText: string;
  sortValue: number | null;
}

interface ScalarMetricInput {
  value: number | null | undefined;
  missingText?: string;
  context?: MetricDisplayContext;
}

interface ScalarMetricOptions {
  missingText?: string;
  context?: MetricDisplayContext;
}

interface PowerScoreOptions extends ScalarMetricOptions {
  exact?: boolean;
}

interface LatencyOptions extends ScalarMetricOptions {
  subMillisecond?: "precise" | "compact";
}

interface SpeedupOptions extends ScalarMetricOptions {
  unit?: SpeedupUnit;
}

interface CoverageOptions {
  covered: number | null | undefined;
  total: number | null | undefined;
  unitLabel?: string;
  missingText?: string;
}

interface CoverageFormatOptions {
  unitLabel?: string;
  missingText?: string;
}

export type MetricFormatInput =
  | ({ type: "power_score" } & ScalarMetricInput & PowerScoreOptions)
  | ({ type: "latency_ms" } & ScalarMetricInput & LatencyOptions)
  | ({ type: "duration_s" } & ScalarMetricInput)
  | ({ type: "speedup" } & ScalarMetricInput & SpeedupOptions)
  | ({ type: "rank"; rank: number | null | undefined; total?: number | null | undefined; missingText?: string })
  | ({ type: "average_rank" } & ScalarMetricInput)
  | ({ type: "coverage" } & CoverageOptions)
  | ({ type: "cost_usd" } & ScalarMetricInput)
  | ({ type: "plain_number" } & ScalarMetricInput);

export function formatMetricValue(input: MetricFormatInput): MetricFormatResult {
  switch (input.type) {
    case "power_score":
      return formatPowerScore(input.value, input);
    case "latency_ms":
      return formatLatencyMs(input.value, input);
    case "duration_s":
      return formatDurationSeconds(input.value, input);
    case "speedup":
      return formatSpeedup(input.value, input);
    case "rank":
      return formatRank(input.rank, input.total, input);
    case "average_rank":
      return formatAverageRank(input.value, input);
    case "coverage":
      return formatCoverage(input.covered, input.total, input);
    case "cost_usd":
      return formatUsd(input.value, input);
    case "plain_number":
      return formatPlainNumber(input.value, input);
  }
}

export function formatPowerScore(value: number | null | undefined, options: PowerScoreOptions = {}): MetricFormatResult {
  const numeric = finiteNumber(value);
  if (numeric === null) return missing(options.missingText ?? "-", "power score");

  const text = options.exact ? formatNumber(numeric, { maximumFractionDigits: 12 }) : compactScore(numeric);
  return result(text, null, numeric, options.exact ? `exact power score ${text}` : `power score ${text}`);
}

export function formatPowerScoreExact(value: number | null | undefined, missingText = "-"): MetricFormatResult {
  return formatPowerScore(value, { exact: true, missingText });
}

export function formatLatencyMs(value: number | null | undefined, options: LatencyOptions = {}): MetricFormatResult {
  const numeric = finiteNumber(value);
  if (numeric === null) return missing(options.missingText ?? "N/A", "latency");

  const abs = Math.abs(numeric);
  if (abs > 0 && abs < 1 && options.subMillisecond === "compact") {
    const text = numeric < 0 ? ">-1 ms" : "<1 ms";
    return result(text, "ms", numeric, `${text} latency`);
  }

  if (abs >= 1000) {
    const seconds = numeric / 1000;
    const text = `${formatNumber(seconds, {
      maximumFractionDigits: abs >= 10_000 ? 1 : 2,
    })} s`;
    return result(text, "s", numeric, `${text} latency`);
  }

  const maximumFractionDigits = abs > 0 && abs < 10 ? 1 : 0;
  const text = `${formatNumber(numeric, { maximumFractionDigits })} ms`;
  return result(text, "ms", numeric, `${text} latency`);
}

export function formatDurationSeconds(value: number | null | undefined, options: ScalarMetricOptions = {}): MetricFormatResult {
  const numeric = finiteNumber(value);
  if (numeric === null) return missing(options.missingText ?? "No duration recorded", "duration");
  const abs = Math.abs(numeric);
  const maximumFractionDigits = abs > 0 && abs < 0.01 ? 4 : abs < 1 ? 3 : abs >= 100 ? 1 : 2;
  const text = `${formatNumber(numeric, { maximumFractionDigits })} s`;
  return result(text, "s", numeric, `${text} duration`);
}

export function formatSpeedup(value: number | null | undefined, options: SpeedupOptions = {}): MetricFormatResult {
  const numeric = finiteNumber(value);
  if (numeric === null) return missing(options.missingText ?? "-", "speedup");
  const unit = options.unit ?? "x";
  const text = `${formatNumber(numeric, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}${unit}`;
  return result(text, unit, numeric, `${text} speedup`);
}

export function formatRank(
  rank: number | null | undefined,
  total?: number | null | undefined,
  options: { missingText?: string } = {},
): MetricFormatResult {
  const numeric = finiteNumber(rank);
  if (numeric === null) return missing(options.missingText ?? "Unranked", "rank");
  const rankText = formatNumber(Math.round(numeric), { maximumFractionDigits: 0 });
  const totalValue = finiteNumber(total);
  const text = totalValue !== null ? `${rankText}/${formatNumber(Math.round(totalValue), { maximumFractionDigits: 0 })}` : rankText;
  return result(text, null, numeric, `rank ${text}`);
}

export function formatAverageRank(value: number | null | undefined, options: ScalarMetricOptions = {}): MetricFormatResult {
  const numeric = finiteNumber(value);
  if (numeric === null) return missing(options.missingText ?? "No score", "average rank");
  const text = formatNumber(numeric, {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
  return result(text, null, numeric, `average rank ${text}`);
}

export function formatCoverage(
  covered: number | null | undefined,
  total: number | null | undefined,
  options: CoverageFormatOptions = {},
): MetricFormatResult {
  const coveredValue = finiteNumber(covered);
  const totalValue = finiteNumber(total);
  if (coveredValue === null || totalValue === null) return missing(options.missingText ?? "Unavailable", "coverage");
  const coveredText = formatNumber(Math.round(coveredValue), { maximumFractionDigits: 0 });
  const totalText = formatNumber(Math.round(totalValue), { maximumFractionDigits: 0 });
  const unitText = options.unitLabel ? ` ${options.unitLabel}` : "";
  const text = `${coveredText}/${totalText}${unitText}`;
  return result(text, null, coveredValue, `${coveredText} of ${totalText}${unitText ? ` ${options.unitLabel}` : ""}`);
}

export function formatUsd(value: number | null | undefined, options: ScalarMetricOptions = {}): MetricFormatResult {
  const numeric = finiteNumber(value);
  if (numeric === null) return missing(options.missingText ?? "No cost recorded", "cost");
  const abs = Math.abs(numeric);
  const minimumFractionDigits = abs >= 1000 ? 0 : abs >= 1 ? 2 : abs >= 0.01 ? 2 : 0;
  const maximumFractionDigits = abs >= 1000 ? 0 : abs >= 1 ? 2 : 4;
  const text = `$${formatNumber(numeric, { minimumFractionDigits, maximumFractionDigits })}`;
  return result(text, "USD", numeric, `${text} USD`);
}

export function formatPlainNumber(value: number | null | undefined, options: ScalarMetricOptions = {}): MetricFormatResult {
  const numeric = finiteNumber(value);
  if (numeric === null) return missing(options.missingText ?? "-", "number");
  const text = formatNumber(numeric, {
    maximumFractionDigits: Number.isInteger(numeric) ? 0 : 2,
  });
  return result(text, null, numeric, text);
}

function compactScore(value: number): string {
  const abs = Math.abs(value);
  const maximumFractionDigits = abs >= 1000 ? 0 : abs >= 100 ? 1 : abs >= 10 ? 2 : abs >= 1 ? 3 : 4;
  return formatNumber(value, { maximumFractionDigits });
}

function formatNumber(
  value: number,
  options: {
    minimumFractionDigits?: number;
    maximumFractionDigits: number;
  },
): string {
  return value.toLocaleString(undefined, {
    minimumFractionDigits: options.minimumFractionDigits ?? 0,
    maximumFractionDigits: options.maximumFractionDigits,
  });
}

function finiteNumber(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function result(valueText: string, unitText: string | null, sortValue: number | null, accessibleText = valueText): MetricFormatResult {
  return { valueText, unitText, accessibleText, sortValue };
}

function missing(valueText: string, accessibleLabel: string): MetricFormatResult {
  return result(valueText, null, null, `${accessibleLabel} unavailable`);
}
