import { fireEvent, render, screen, waitFor, within } from "@testing-library/preact";
import { beforeEach, describe, expect, it } from "vitest";
import Router, { route } from "preact-router";
import { Layout } from "@/components/Layout";
import {
  HEADER_CTA,
  HEADER_LINKS,
  HEADER_NAV_ARIA_LABEL,
  getHeaderVisibleLabels,
} from "@/components/headerContract";

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
  beforeEach(() => {
    const storage = new Map<string, string>();
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: {
        getItem: (key: string) => storage.get(key) ?? null,
        setItem: (key: string, value: string) => {
          storage.set(key, value);
        },
        removeItem: (key: string) => {
          storage.delete(key);
        },
        clear: () => storage.clear(),
      },
    });
  });

  it("renders the BenchBox global nav with Results active at the hosted root", () => {
    renderAt("/");

    const globalNav = screen.getByRole("navigation", { name: HEADER_NAV_ARIA_LABEL });
    expect(within(globalNav).getAllByRole("link").map((link) => link.textContent)).toEqual(
      getHeaderVisibleLabels(),
    );
    for (const link of HEADER_LINKS) {
      expect(within(globalNav).getByRole("link", { name: link.label })).toHaveAttribute("href", link.href);
      if (link.external) {
        expect(within(globalNav).getByRole("link", { name: link.label })).toHaveAttribute("target", "_blank");
        expect(within(globalNav).getByRole("link", { name: link.label })).toHaveAttribute("rel", "noopener");
      }
    }
    expect(within(globalNav).getByRole("link", { name: "Results" })).toHaveAttribute("aria-current", "page");
    expect(within(globalNav).getByRole("link", { name: HEADER_CTA.label })).toHaveAttribute("href", HEADER_CTA.href);
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

    const globalNav = screen.getByRole("navigation", { name: HEADER_NAV_ARIA_LABEL });
    expect(within(globalNav).getAllByRole("link").map((link) => link.textContent)).toEqual(
      getHeaderVisibleLabels(),
    );
  });

  it("does not render a theme control in the header", () => {
    renderAt("/results/");
    const globalNav = screen.getByRole("navigation", { name: HEADER_NAV_ARIA_LABEL });
    expect(within(globalNav).queryAllByRole("radio")).toHaveLength(0);
    expect(within(globalNav).queryByRole("button", { name: /theme/i })).toBeNull();
  });

  it("sets the footer theme choice directly from a three-option radiogroup", () => {
    window.localStorage.removeItem("benchbox:theme");
    renderAt("/results/");

    const group = screen.getByRole("radiogroup", { name: "Color theme" });
    const system = within(group).getByRole("radio", { name: "System theme" });
    const light = within(group).getByRole("radio", { name: "Light theme" });
    const dark = within(group).getByRole("radio", { name: "Dark theme" });

    expect(system).toHaveAttribute("aria-checked", "true");
    expect(light).toHaveAttribute("aria-checked", "false");
    expect(dark).toHaveAttribute("aria-checked", "false");
    expect(document.documentElement.dataset.bbThemeChoice).toBe("system");

    fireEvent.click(dark);
    expect(document.documentElement.dataset.bbThemeChoice).toBe("dark");
    expect(document.documentElement.dataset.bbTheme).toBe("dark");
    expect(window.localStorage.getItem("benchbox:theme")).toBe("dark");
    expect(dark).toHaveAttribute("aria-checked", "true");
    expect(system).toHaveAttribute("aria-checked", "false");

    fireEvent.click(light);
    expect(document.documentElement.dataset.bbThemeChoice).toBe("light");
    expect(window.localStorage.getItem("benchbox:theme")).toBe("light");
    expect(light).toHaveAttribute("aria-checked", "true");
    expect(dark).toHaveAttribute("aria-checked", "false");

    fireEvent.click(system);
    expect(document.documentElement.dataset.bbThemeChoice).toBe("system");
    expect(window.localStorage.getItem("benchbox:theme")).toBeNull();
    expect(system).toHaveAttribute("aria-checked", "true");
  });

  it("supports the roving-tabindex radiogroup keyboard pattern", () => {
    window.localStorage.removeItem("benchbox:theme");
    renderAt("/results/");

    const group = screen.getByRole("radiogroup", { name: "Color theme" });
    const system = within(group).getByRole("radio", { name: "System theme" });
    const light = within(group).getByRole("radio", { name: "Light theme" });
    const dark = within(group).getByRole("radio", { name: "Dark theme" });

    // Initial roving tabindex: only the checked option is tabbable.
    expect(system).toHaveAttribute("tabindex", "0");
    expect(light).toHaveAttribute("tabindex", "-1");
    expect(dark).toHaveAttribute("tabindex", "-1");

    system.focus();

    fireEvent.keyDown(system, { key: "ArrowRight" });
    expect(document.activeElement).toBe(light);
    expect(light).toHaveAttribute("aria-checked", "true");
    expect(light).toHaveAttribute("tabindex", "0");
    expect(system).toHaveAttribute("aria-checked", "false");
    expect(system).toHaveAttribute("tabindex", "-1");
    expect(document.documentElement.dataset.bbThemeChoice).toBe("light");

    fireEvent.keyDown(light, { key: "ArrowLeft" });
    expect(document.activeElement).toBe(system);
    expect(system).toHaveAttribute("aria-checked", "true");
    expect(system).toHaveAttribute("tabindex", "0");
    expect(document.documentElement.dataset.bbThemeChoice).toBe("system");

    // ArrowLeft wraps from the first option to the last.
    fireEvent.keyDown(system, { key: "ArrowLeft" });
    expect(document.activeElement).toBe(dark);
    expect(dark).toHaveAttribute("aria-checked", "true");
    expect(dark).toHaveAttribute("tabindex", "0");
    expect(document.documentElement.dataset.bbThemeChoice).toBe("dark");

    fireEvent.keyDown(dark, { key: "Home" });
    expect(document.activeElement).toBe(system);
    expect(system).toHaveAttribute("aria-checked", "true");
    expect(document.documentElement.dataset.bbThemeChoice).toBe("system");

    fireEvent.keyDown(system, { key: "End" });
    expect(document.activeElement).toBe(dark);
    expect(dark).toHaveAttribute("aria-checked", "true");
    expect(document.documentElement.dataset.bbThemeChoice).toBe("dark");

    fireEvent.keyDown(dark, { key: "ArrowUp" });
    expect(document.activeElement).toBe(light);
    expect(light).toHaveAttribute("aria-checked", "true");
    expect(document.documentElement.dataset.bbThemeChoice).toBe("light");

    fireEvent.keyDown(light, { key: " " });
    expect(document.activeElement).toBe(light);
    expect(light).toHaveAttribute("aria-checked", "true");
    expect(document.documentElement.dataset.bbThemeChoice).toBe("light");
  });

  it("renders the Results Explorer subnav and marks the current explorer section", () => {
    renderAt("/results/query");

    const explorerNav = screen.getByRole("navigation", { name: "Results Explorer" });
    for (const label of ["Overview", "Benchmarks", "Platforms", "Compare", "Find runs"]) {
      expect(within(explorerNav).getByRole("link", { name: label })).toBeTruthy();
    }
    expect(within(explorerNav).getByRole("link", { name: "Find runs" })).toHaveAttribute("aria-current", "page");
    expect(within(explorerNav).getByRole("button", { name: "Open local result" })).toBeTruthy();
    expect(within(explorerNav).getByTestId("local-result-file-input")).toHaveAttribute("aria-hidden", "true");
    expect(within(explorerNav).getByTestId("local-result-file-input")).toHaveAttribute("tabindex", "-1");
    expect(within(explorerNav).getByRole("link", { name: "Overview" })).not.toHaveAttribute("aria-current");
  });

  it("updates the active explorer subnav after a client-side route() call", async () => {
    // Regression: prior to this fix, Layout read `window.location.pathname`
    // once at module render time, so navigating from Overview to Query
    // via preact-router left "Overview" highlighted indefinitely.
    renderWithRouter("/results/");

    const explorerNav = screen.getByRole("navigation", { name: "Results Explorer" });
    expect(within(explorerNav).getByRole("link", { name: "Overview" })).toHaveAttribute("aria-current", "page");

    route("/results/query");

    await waitFor(() => {
      expect(within(explorerNav).getByRole("link", { name: "Find runs" })).toHaveAttribute("aria-current", "page");
    });
    expect(within(explorerNav).getByRole("link", { name: "Overview" })).not.toHaveAttribute("aria-current");
  });

  it("global and Results nav links use the theme-aware focus-visible outline token", () => {
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
    }
  });
});
