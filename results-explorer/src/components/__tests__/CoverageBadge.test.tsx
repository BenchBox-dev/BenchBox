import { render, screen } from "@testing-library/preact";
import { describe, expect, it } from "vitest";
import { CoverageBadge } from "@/components/CoverageBadge";

describe("CoverageBadge", () => {
  it("renders normalized cloud provider values with stable labels", () => {
    render(<CoverageBadge facetKey="cloud_provider" value="aws" count={12} />);

    expect(screen.getByText("AWS")).toBeTruthy();
    expect(screen.getByText("12")).toBeTruthy();
  });

  it("preserves normalized deployment and storage vocabulary", () => {
    const { rerender } = render(<CoverageBadge facetKey="deployment_class" value="local" />);
    expect(screen.getByText("local")).toBeTruthy();

    rerender(<CoverageBadge facetKey="storage_format" value="parquet" />);
    expect(screen.getByText("parquet")).toBeTruthy();
  });
});
