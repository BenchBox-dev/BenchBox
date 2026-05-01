import { render, screen, within } from "@testing-library/preact";
import { describe, expect, it } from "vitest";
import { Layout } from "@/components/Layout";

function renderAt(path: string) {
  window.history.replaceState(null, "", path);
  return render(
    <Layout>
      <div>Page content</div>
    </Layout>,
  );
}

describe("Layout", () => {
  it("renders the BenchBox global nav with Results active under /results/", () => {
    renderAt("/results/");

    const globalNav = screen.getByRole("navigation", { name: "BenchBox" });
    expect(within(globalNav).getByRole("link", { name: "Docs" })).toHaveAttribute(
      "href",
      "https://benchbox.dev/docs/",
    );
    expect(within(globalNav).getByRole("link", { name: "Blog" })).toHaveAttribute(
      "href",
      "https://benchbox.dev/blog/",
    );
    expect(within(globalNav).getByRole("link", { name: "GitHub" })).toHaveAttribute(
      "href",
      "https://github.com/joeharris76/BenchBox",
    );
    expect(within(globalNav).getByRole("link", { name: "Results" })).toHaveAttribute("aria-current", "page");
    expect(within(globalNav).getByRole("link", { name: "Run benchmark" })).toHaveAttribute(
      "href",
      "https://benchbox.dev/docs/usage/installation.html",
    );
  });

  it("renders the Results Explorer subnav and marks the current explorer section", () => {
    renderAt("/results/query");

    const explorerNav = screen.getByRole("navigation", { name: "Results Explorer" });
    for (const label of ["Leaderboards", "Benchmarks", "Platforms", "Compare", "Query"]) {
      expect(within(explorerNav).getByRole("link", { name: label })).toBeTruthy();
    }
    expect(within(explorerNav).getByRole("link", { name: "Query" })).toHaveAttribute("aria-current", "page");
    expect(within(explorerNav).getByRole("link", { name: "Leaderboards" })).not.toHaveAttribute("aria-current");
  });
});
