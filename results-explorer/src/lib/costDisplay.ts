import type { CostDeploymentFields } from "@/types";

export function normalizedCostValue(row: CostDeploymentFields): number | null {
  if (row.cost_status !== "normalized") return null;
  const value = row.normalized_cost_usd;
  if (value === null || value === undefined) return null;
  return Number.isFinite(value) ? value : null;
}

export function normalizedCostLabel(row: CostDeploymentFields): string {
  const value = normalizedCostValue(row);
  if (value !== null) return `$${value.toFixed(2)}`;
  return costStatusLabel(row);
}

export function costStatusLabel(row: CostDeploymentFields): string {
  if (row.cost_status === "not_applicable_local") return "local";
  if (row.cost_status === "unavailable") return "unavailable";
  return "-";
}

export function costModelDisclosure(rows: readonly CostDeploymentFields[]): string {
  const normalized = rows.filter((row) => normalizedCostValue(row) !== null);
  const versions = uniqueNonEmpty(normalized.map((row) => row.cost_model_version));
  const scopes = uniqueNonEmpty(normalized.map((row) => formatCostScope(row.cost_scope)));
  const versionText =
    versions.length === 1
      ? `model ${versions[0]}`
      : versions.length > 1
        ? `multiple models: ${versions.join(", ")}`
        : "model unavailable";
  const scopeText =
    scopes.length === 1
      ? scopes[0]
      : scopes.length > 1
        ? `mixed scopes: ${scopes.join(", ")}`
        : "scope unavailable";
  return `Normalized USD, ${scopeText}, ${versionText}`;
}

export function costModelSummary(row: CostDeploymentFields): string {
  const version = row.cost_model_version || "Not recorded";
  const source = row.cost_model_source ? ` (${row.cost_model_source})` : "";
  return `${version}${source}`;
}

export function costScopeSummary(row: CostDeploymentFields): string {
  return [
    formatCostScope(row.cost_scope) ?? "Not recorded",
    row.billing_unit ? `billing: ${row.billing_unit}` : null,
    row.pricing_region ? `region: ${row.pricing_region}` : null,
  ].filter((part): part is string => part !== null).join(", ");
}

function formatCostScope(scope: string | null | undefined): string | null {
  if (!scope) return null;
  return scope.split("_").join(" ");
}

function uniqueNonEmpty(values: Array<string | null | undefined>): string[] {
  return [...new Set(values.filter((value): value is string => Boolean(value)))];
}
