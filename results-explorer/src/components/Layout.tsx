import type { ComponentChildren } from "preact";
import { useState } from "preact/hooks";
import { getCurrentUrl, useRouter } from "preact-router";
import { nextThemeChoice, useThemeChoice } from "@/lib/theme";

interface LayoutProps {
  children: ComponentChildren;
}

export function Layout({ children }: LayoutProps) {
  return (
    <div class="flex min-h-screen flex-col">
      <Header />
      <main class="flex-1">{children}</main>
      <Footer />
    </div>
  );
}

function Header() {
  // Subscribe to preact-router URL changes so client-side `route()` calls
  // re-render this component. `useRouter()` works from outside the Router
  // tree by registering a forced-update setter when the consumed context
  // is the default value.
  useRouter();
  const rawUrl = typeof window === "undefined" ? "/results/" : getCurrentUrl();
  const currentPath = rawUrl.split("?")[0]!.split("#")[0]!;
  const inResults = currentPath === "/" || currentPath === "/results" || currentPath.startsWith("/results/");
  const [menuOpen, setMenuOpen] = useState(false);
  const { choice, setChoice } = useThemeChoice();

  return (
    <header class="surface-hero" data-surface="hero">
      <div class="sticky top-0 z-[1000] border-b border-[var(--bb-border-default)] bg-[var(--bb-site-header-bg)] text-[var(--bb-fg-primary)] backdrop-blur">
        <div class="mx-auto flex min-h-16 max-w-[1200px] flex-wrap items-center justify-between gap-4 px-4 sm:px-6">
          <a href="https://benchbox.dev/" class="font-mono text-xl font-bold leading-none no-underline text-[var(--bb-accent)]">
            BenchBox
          </a>
          <button
            type="button"
            aria-label="Toggle site navigation"
            aria-controls="benchbox-site-header-nav"
            aria-expanded={menuOpen ? "true" : "false"}
            class="inline-flex h-9 w-9 items-center justify-center rounded-md border border-[var(--bb-border-default)] text-[var(--bb-fg-primary)] min-[901px]:hidden"
            onClick={() => setMenuOpen((open) => !open)}
          >
            <span aria-hidden="true" class="flex h-4 w-4 flex-col items-center justify-center gap-1">
              <span class={`${menuOpen ? "translate-y-[6px] rotate-45" : ""} block h-0.5 w-4 rounded bg-current`} />
              <span class={`${menuOpen ? "opacity-0" : ""} block h-0.5 w-4 rounded bg-current`} />
              <span class={`${menuOpen ? "-translate-y-[6px] -rotate-45" : ""} block h-0.5 w-4 rounded bg-current`} />
            </span>
          </button>
          <nav
            id="benchbox-site-header-nav"
            aria-label="BenchBox"
            class={`${menuOpen ? "flex" : "hidden"} w-full flex-col items-start gap-3 pb-4 text-[0.9375rem] min-[901px]:flex min-[901px]:w-auto min-[901px]:flex-row min-[901px]:items-center min-[901px]:justify-end min-[901px]:gap-6 min-[901px]:pb-0`}
            onClick={(event) => {
              if (event.target instanceof Element && event.target.closest("a")) {
                setMenuOpen(false);
              }
            }}
          >
            <GlobalNavLink href="https://benchbox.dev/">Home</GlobalNavLink>
            <GlobalNavLink href="https://benchbox.dev/docs/">Docs</GlobalNavLink>
            <GlobalNavLink href="https://benchbox.dev/blog/">Blog</GlobalNavLink>
            <GlobalNavLink href="https://benchbox.dev/results/" active={inResults}>
              Results
            </GlobalNavLink>
            <GlobalNavLink href="https://benchbox.dev/prompts/">Instruct an agent</GlobalNavLink>
            <GlobalNavLink href="https://github.com/joeharris76/BenchBox" external>
              GitHub
            </GlobalNavLink>
            <a
              href="https://benchbox.dev/docs/usage/installation.html"
              class="inline-flex min-h-8 items-center justify-center whitespace-nowrap rounded bg-[var(--bb-accent)] px-3 py-1.5 font-bold text-[var(--bb-fg-inverse)] no-underline hover:bg-[var(--bb-accent-hover)] hover:text-[var(--bb-fg-inverse)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--bb-focus-ring-on-dark)]"
            >
              Run benchmark
            </a>
            <button
              type="button"
              aria-label={`Theme: ${choice}. Activate to switch theme.`}
              data-benchbox-theme-toggle
              class="min-h-8 rounded-md border border-[var(--bb-border-default)] bg-[var(--bb-site-header-control-bg)] px-3 py-1.5 text-sm font-semibold text-[var(--bb-fg-primary)] hover:bg-[var(--bb-site-header-control-hover-bg)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--bb-focus-ring-on-dark)]"
              onClick={() => setChoice(nextThemeChoice(choice))}
            >
              {themeLabel(choice)}
            </button>
          </nav>
        </div>
      </div>
      <div class="border-t border-[var(--bb-border-default)] bg-[var(--bb-surface-hero-muted)] text-[var(--bb-fg-primary)]">
        <div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          {/* Wraps to a second row at the smallest mobile widths so the
              `Query` item never falls off-canvas (audit 2026-05-07). At
              ≥640px (sm) the row collapses back to single-line. */}
          <nav
            aria-label="Results Explorer"
            data-testid="results-explorer-nav"
            class="flex min-h-12 flex-wrap items-center gap-x-5 gap-y-1 py-1 text-sm sm:flex-nowrap sm:overflow-x-auto"
          >
            <ExplorerNavLink href="/results/" active={currentPath === "/results" || currentPath === "/results/"}>
              Leaderboards
            </ExplorerNavLink>
            <ExplorerNavLink href="/results/tpch/" active={isBenchmarkPath(currentPath)}>
              Benchmarks
            </ExplorerNavLink>
            <ExplorerNavLink href="/results/p/duckdb/" active={currentPath.startsWith("/results/p/")}>
              Platforms
            </ExplorerNavLink>
            <ExplorerNavLink href="/results/compare" active={currentPath.startsWith("/results/compare")}>
              Compare
            </ExplorerNavLink>
            <ExplorerNavLink href="/results/query" active={currentPath.startsWith("/results/query")}>
              Query
            </ExplorerNavLink>
          </nav>
        </div>
      </div>
    </header>
  );
}

function GlobalNavLink({
  href,
  active = false,
  external = false,
  children,
}: {
  href: string;
  active?: boolean;
  external?: boolean;
  children: ComponentChildren;
}) {
  return (
    <a
      href={href}
      target={external ? "_blank" : undefined}
      rel={external ? "noopener" : undefined}
      aria-current={active ? "page" : undefined}
      class={`rounded-sm font-medium no-underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--bb-focus-ring-on-dark)] ${
        active ? "text-[var(--bb-fg-primary)]" : "text-[var(--bb-fg-muted)] hover:text-[var(--bb-fg-primary)]"
      }`}
    >
      {children}
    </a>
  );
}

function ExplorerNavLink({
  href,
  active = false,
  children,
}: {
  href: string;
  active?: boolean;
  children: ComponentChildren;
}) {
  return (
    <a
      href={href}
      aria-current={active ? "page" : undefined}
      class={`whitespace-nowrap border-b-2 py-3 font-medium no-underline rounded-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--bb-focus-ring-on-dark)] ${
        active
          ? "border-[var(--bb-accent)] text-[var(--bb-fg-primary)]"
          : "border-transparent text-[var(--bb-fg-muted)] hover:border-[var(--bb-border-default)] hover:text-[var(--bb-fg-primary)]"
      }`}
    >
      {children}
    </a>
  );
}

function isBenchmarkPath(path: string): boolean {
  return /^\/results\/(?!compare\/?$|query\/?$|p\/|r\/)[^/]+\/?$/.test(path);
}

function themeLabel(choice: string): string {
  return choice === "system" ? "System" : choice.charAt(0).toUpperCase() + choice.slice(1);
}

function Footer() {
  return (
    <footer class="surface-hero border-t border-[var(--bb-border-default)] py-8" data-surface="hero">
      <div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div class="flex flex-col items-center justify-between gap-4 sm:flex-row">
          <p class="text-sm text-[var(--bb-fg-muted)]">
            &copy; {new Date().getFullYear()} BenchBox. The current public corpus is{" "}
            <span class="font-medium text-[var(--bb-fg-primary)]">maintainer-curated</span>, and new submissions go through PR
            validation and maintainer review before they appear here. Reproduce runs with{" "}
            <code class="rounded bg-[var(--bb-bg-elevated)] px-1 py-0.5 text-xs text-[var(--bb-fg-primary)]">benchbox run</code>.
          </p>
          <nav class="flex items-center gap-4">
            <a href="https://benchbox.dev" class="text-sm text-[var(--bb-fg-muted)] hover:text-[var(--bb-fg-primary)] no-underline">
              benchbox.dev
            </a>
            <a href="https://github.com/joeharris76/BenchBox" class="text-sm text-[var(--bb-fg-muted)] hover:text-[var(--bb-fg-primary)] no-underline">
              GitHub
            </a>
          </nav>
        </div>
      </div>
    </footer>
  );
}
