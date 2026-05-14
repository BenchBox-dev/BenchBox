import { fireEvent, render, screen, waitFor, within } from "@testing-library/preact";
import { describe, expect, it } from "vitest";
import Router, { route } from "preact-router";
import { Layout } from "@/components/Layout";

function renderAt(path: string) {
  window.history.replaceState(null, "", path);
  return render(
    <Layout>
      <div>Page content</div>
    </Layout>,
  );
}

function renderWithRouter(initialPath: string) {
  window.history.replaceState(null, "", initialPath);
  return render(
    <Layout>
      <Router>
        <div path="/results/" />
        <div path="/results/query" />
        <div path="/results/compare" />
        <div default />
      </Router>
    </Layout>,
  );
}

describe("Layout", () => {
  it("renders the BenchBox global nav with Results active at the hosted root", () => {
    renderAt("/");

    const globalNav = screen.getByRole("navigation", { name: "BenchBox" });
    expect(within(globalNav).getAllByRole("link").map((link) => link.textContent)).toEqual([
      "Home",
      "Docs",
      "Blog",
      "Results",
      "Instruct an agent",
      "GitHub",
      "Run benchmark",
    ]);
    expect(within(globalNav).getByRole("link", { name: "Home" })).toHaveAttribute("href", "https://benchbox.dev/");
    expect(within(globalNav).getByRole("link", { name: "Docs" })).toHaveAttribute("href", "https://benchbox.dev/docs/");
    expect(within(globalNav).getByRole("link", { name: "Blog" })).toHaveAttribute("href", "https://benchbox.dev/blog/");
    expect(within(globalNav).getByRole("link", { name: "Instruct an agent" })).toHaveAttribute(
      "href",
      "https://benchbox.dev/prompts/",
    );
    expect(within(globalNav).getByRole("link", { name: "GitHub" })).toHaveAttribute(
      "href",
      "https://github.com/joeharris76/BenchBox",
    );
    expect(within(globalNav).getByRole("link", { name: "GitHub" })).toHaveAttribute("target", "_blank");
    expect(within(globalNav).getByRole("link", { name: "GitHub" })).toHaveAttribute("rel", "noopener");
    expect(within(globalNav).getByRole("link", { name: "Results" })).toHaveAttribute("aria-current", "page");
    expect(within(globalNav).getByRole("link", { name: "Run benchmark" })).toHaveAttribute(
      "href",
      "https://benchbox.dev/docs/usage/installation.html",
    );
  });

  it("keeps Results active under /results/ routes", () => {
    renderAt("/results/");

    const globalNav = screen.getByRole("navigation", { name: "BenchBox" });
    expect(within(globalNav).getByRole("link", { name: "Results" })).toHaveAttribute("aria-current", "page");
  });

  it("uses a mobile disclosure without changing the global nav contract", () => {
    renderAt("/results/");

    const toggle = screen.getByRole("button", { name: "Toggle site navigation" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    const globalNav = screen.getByRole("navigation", { name: "BenchBox" });
    expect(within(globalNav).getAllByRole("link").map((link) => link.textContent)).toEqual([
      "Home",
      "Docs",
      "Blog",
      "Results",
      "Instruct an agent",
      "GitHub",
      "Run benchmark",
    ]);
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

  it("updates the active explorer subnav after a client-side route() call", async () => {
    // Regression: prior to this fix, Layout read `window.location.pathname`
    // once at module render time, so navigating from Leaderboards to Query
    // via preact-router left "Leaderboards" highlighted indefinitely.
    renderWithRouter("/results/");

    const explorerNav = screen.getByRole("navigation", { name: "Results Explorer" });
    expect(within(explorerNav).getByRole("link", { name: "Leaderboards" })).toHaveAttribute("aria-current", "page");

    route("/results/query");

    await waitFor(() => {
      expect(within(explorerNav).getByRole("link", { name: "Query" })).toHaveAttribute("aria-current", "page");
    });
    expect(within(explorerNav).getByRole("link", { name: "Leaderboards" })).not.toHaveAttribute("aria-current");
  });

  it("hero header nav links use the on-dark focus-visible outline token", () => {
    renderAt("/results/");
    const explorerNav = screen.getByRole("navigation", { name: "Results Explorer" });
    const globalNav = screen.getByRole("navigation", { name: "BenchBox" });

    for (const link of [
      ...within(explorerNav).getAllByRole("link"),
      ...within(globalNav).getAllByRole("link"),
    ]) {
      const cls = link.getAttribute("class") ?? "";
      expect(cls).toMatch(/focus-visible:outline\b/);
      expect(cls).toMatch(/focus-visible:outline-\[var\(--bb-focus-ring-on-dark\)\]/);
      expect(cls).not.toMatch(/focus-visible:outline-\[var\(--bb-focus-ring\)\]/);
    }
  });
});
