import { describe, it, expect } from "vitest";
import type { CostDeploymentFields } from "@/types";
import {
  costModelSummary,
  costScopeSummary,
  costStatusLabel,
  humanizeBillingFragment,
  normalizedCostLabel,
  normalizedCostValue,
} from "@/lib/costDisplay";

function makeRow(overrides: Partial<CostDeploymentFields> = {}): CostDeploymentFields {
  return {
    cost_status: null,
    cost_scope: null,
    cost_model_version: null,
    cost_model_source: null,
    normalized_cost_usd: null,
    billing_unit: null,
    pricing_region: null,
    deployment_class: null,
    cloud_provider: null,
    cloud_region: null,
    instance_or_warehouse: null,
    storage_format: null,
    ...overrides,
  } as CostDeploymentFields;
}

describe("humanizeBillingFragment", () => {
  it("returns null for null/undefined/empty/whitespace inputs", () => {
    expect(humanizeBillingFragment(null)).toBeNull();
    expect(humanizeBillingFragment(undefined)).toBeNull();
    expect(humanizeBillingFragment("")).toBeNull();
    expect(humanizeBillingFragment("   ")).toBeNull();
  });

  it("returns null for sentinel values (case-insensitive)", () => {
    expect(humanizeBillingFragment("not_applicable")).toBeNull();
    expect(humanizeBillingFragment("Not Applicable")).toBeNull();
    expect(humanizeBillingFragment("unknown")).toBeNull();
    expect(humanizeBillingFragment("UNKNOWN")).toBeNull();
    expect(humanizeBillingFragment("none")).toBeNull();
    expect(humanizeBillingFragment("n/a")).toBeNull();
    expect(humanizeBillingFragment("N/A")).toBeNull();
    expect(humanizeBillingFragment("na")).toBeNull();
  });

  it("humanizes real values by replacing underscores with spaces", () => {
    expect(humanizeBillingFragment("per_query")).toBe("per query");
    expect(humanizeBillingFragment("us_west_2")).toBe("us west 2");
    expect(humanizeBillingFragment("EU-Frankfurt")).toBe("EU-Frankfurt");
  });
});

describe("costScopeSummary", () => {
  it("renders just the cost scope when billing and region are sentinel", () => {
    const summary = costScopeSummary(
      makeRow({ cost_scope: "compute_only", billing_unit: "not_applicable", pricing_region: "not_applicable" }),
    );
    expect(summary).toBe("compute only");
    expect(summary).not.toContain("not_applicable");
    expect(summary).not.toContain("billing:");
    expect(summary).not.toContain("region:");
  });

  it("renders billing and region fragments when they carry real values", () => {
    const summary = costScopeSummary(
      makeRow({ cost_scope: "compute_only", billing_unit: "per_query", pricing_region: "us-west-2" }),
    );
    expect(summary).toBe("compute only, billing: per query, region: us-west-2");
  });

  it("renders only the present fragment when one side is sentinel and the other is real", () => {
    const summary = costScopeSummary(
      makeRow({ cost_scope: "compute_only", billing_unit: "per_hour", pricing_region: "Unknown" }),
    );
    expect(summary).toBe("compute only, billing: per hour");
  });

  it("falls back to 'Not recorded' when cost_scope is missing and billing/region are sentinel", () => {
    const summary = costScopeSummary(
      makeRow({ cost_scope: null, billing_unit: "not_applicable", pricing_region: null }),
    );
    expect(summary).toBe("Not recorded");
  });
});

describe("costStatusLabel and normalizedCost helpers (unaffected by w1)", () => {
  it("returns 'local' for not_applicable_local", () => {
    expect(costStatusLabel(makeRow({ cost_status: "not_applicable_local" }))).toBe("local");
  });

  it("returns the dollar value when normalized cost is finite", () => {
    expect(normalizedCostValue(makeRow({ cost_status: "normalized", normalized_cost_usd: 12.5 }))).toBe(12.5);
    expect(normalizedCostLabel(makeRow({ cost_status: "normalized", normalized_cost_usd: 12.5 }))).toBe("$12.50");
  });

  it("falls back to status label when normalized cost is missing", () => {
    expect(normalizedCostLabel(makeRow({ cost_status: "not_applicable_local" }))).toBe("local");
  });

  it("includes cost_model_source in costModelSummary parens when present", () => {
    expect(costModelSummary(makeRow({ cost_model_version: "v3", cost_model_source: "ondemand" }))).toBe(
      "v3 (ondemand)",
    );
    expect(costModelSummary(makeRow({ cost_model_version: "v3" }))).toBe("v3");
  });
});
