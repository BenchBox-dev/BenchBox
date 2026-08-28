import { describe, expect, it } from "vitest";
import { formatFacetDisplayValue } from "@/lib/facetDisplay";

describe("formatFacetDisplayValue", () => {
  it("preserves hyphenated identifiers when no fallback label is provided", () => {
    expect(formatFacetDisplayValue("cloud_region", "us-east-1")).toBe("us-east-1");
    expect(formatFacetDisplayValue("result_id", "tpch-duckdb-sf0.01-20260403-7fe93365")).toBe(
      "tpch-duckdb-sf0.01-20260403-7fe93365",
    );
    expect(formatFacetDisplayValue("cost_model", "benchbox-2026.05.0")).toBe("benchbox-2026.05.0");
  });

  it("still makes underscore-delimited tokens readable", () => {
    expect(formatFacetDisplayValue("storage_format", "remote_object_store")).toBe("remote object store");
    expect(formatFacetDisplayValue("cost_status", "not_applicable_local")).toBe("not applicable local");
  });

  it("keeps known cloud provider alias normalization separate from generic display formatting", () => {
    expect(formatFacetDisplayValue("cloud_provider", "google-cloud-platform")).toBe("GCP");
  });
});
