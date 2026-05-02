import { render, screen } from "@testing-library/preact";
import { describe, expect, it } from "vitest";
import {
  BenchmarkMatrixSkeleton,
  CompareSummarySkeleton,
  MetaLeaderboardSkeleton,
  QueryRowsSkeleton,
} from "@/components/LoadingSpinner";

describe("loading skeletons", () => {
  it("reserves the MetaLeaderboard table geometry", () => {
    const { container } = render(<MetaLeaderboardSkeleton />);

    expect(screen.getByRole("region", { name: "Cross-benchmark leaderboard loading" }))
      .toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("status")).toHaveTextContent("Initializing static DuckDB snapshot...");
    expect(container.querySelectorAll("tbody tr")).toHaveLength(5);
    expect(container.querySelectorAll(".bb-skeleton").length).toBeGreaterThan(20);
  });

  it("renders benchmark matrix and query row skeleton tables", () => {
    const matrix = render(<BenchmarkMatrixSkeleton message="Loading matrix..." />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading matrix...");
    expect(matrix.container.querySelectorAll("tbody tr")).toHaveLength(6);
    matrix.unmount();

    const query = render(<QueryRowsSkeleton message="Querying results.duckdb..." columns={3} />);
    expect(screen.getByRole("status")).toHaveTextContent("Querying results.duckdb...");
    expect(query.container.querySelectorAll("thead th")).toHaveLength(4);
  });

  it("renders a compare summary skeleton with result-card placeholders", () => {
    const { container } = render(<CompareSummarySkeleton />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading results for comparison...");
    expect(container.querySelectorAll(".card")).toHaveLength(4);
  });
});
