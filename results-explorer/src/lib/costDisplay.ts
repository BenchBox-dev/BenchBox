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
  const billing = humanizeBillingFragment(row.billing_unit);
  const region = humanizeBillingFragment(row.pricing_region);
  return [
    formatCostScope(row.cost_scope) ?? "Not recorded",
    billing !== null ? `billing: ${billing}` : null,
    region !== null ? `region: ${region}` : null,
  ].filter((part): part is string => part !== null).join(", ");
}

function formatCostScope(scope: string | null | undefined): string | null {
  if (!scope) return null;
  return scope.split("_").join(" ");
}

/**
 * Convert a `billing_unit` / `pricing_region` raw value into user-facing copy.
 * The corpus stores sentinel values like `not_applicable` for local-no-cloud
 * runs; rendering those verbatim in the Run Receipt was finding #12 of the
 * 2026-05-09 post-completion review. Returns `null` when the field carries a
 * sentinel so callers can drop the fragment entirely; otherwise returns the
 * humanized form (trimmed, underscores replaced with spaces).
 */
const BILLING_FRAGMENT_SENTINELS = new Set([
  "not_applicable",
  "not applicable",
  "unknown",
  "none",
  "n/a",
  "na",
]);

export function humanizeBillingFragment(value: string | null | undefined): string | null {
  if (value === null || value === undefined) return null;
  const trimmed = value.trim();
  if (trimmed === "") return null;
  if (BILLING_FRAGMENT_SENTINELS.has(trimmed.toLowerCase())) return null;
  return trimmed.split("_").join(" ");
}

function uniqueNonEmpty(values: Array<string | null | undefined>): string[] {
  return [...new Set(values.filter((value): value is string => Boolean(value)))];
}
