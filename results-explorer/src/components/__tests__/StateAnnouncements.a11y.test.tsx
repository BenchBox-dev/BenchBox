import { render, screen } from "@testing-library/preact";
import { describe, expect, it } from "vitest";
import { ErrorMessage } from "@/components/ErrorMessage";
import { ErrorState } from "@/components/ErrorState";
import {
  BenchmarkMatrixSkeleton,
  CompareSummarySkeleton,
  LoadingSpinner,
  QueryRowsSkeleton,
} from "@/components/LoadingSpinner";
import { expectNoAxeViolations } from "@/testing/axe-helper";

describe("loading and error state announcements", () => {
  it.each([
    ["LoadingSpinner", <LoadingSpinner message="Loading results..." />, "Loading results..."],
    ["BenchmarkMatrixSkeleton", <BenchmarkMatrixSkeleton message="Loading matrix..." />, "Loading matrix..."],
    ["QueryRowsSkeleton", <QueryRowsSkeleton message="Loading matching results..." />, "Loading matching results..."],
    ["CompareSummarySkeleton", <CompareSummarySkeleton message="Loading results for comparison..." />, "Loading results for comparison..."],
  ])("%s is a named polite live region", async (_name, element, label) => {
    const { container } = render(element);

    const status = screen.getByRole("status", { name: label });
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(status).toHaveAttribute("aria-busy", "true");
    await expectNoAxeViolations(container);
  });

  it("ErrorMessage is an assertive alert named by its title", async () => {
    const { container } = render(<ErrorMessage title="Could not load results" message="The snapshot failed to open." onRetry={() => {}} />);

    const alert = screen.getByRole("alert", { name: "Could not load results" });
    expect(alert).toHaveAttribute("aria-live", "assertive");
    expect(alert).toHaveTextContent("The snapshot failed to open.");
    await expectNoAxeViolations(container);
  });

  it("ErrorState is an assertive alert named by its title", async () => {
    const { container } = render(<ErrorState title="Result unavailable" description="It may have been withdrawn." detail="404" />);

    const alert = screen.getByRole("alert", { name: "Result unavailable" });
    expect(alert).toHaveAttribute("aria-live", "assertive");
    await expectNoAxeViolations(container);
  });
});
