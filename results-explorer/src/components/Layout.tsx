import type { ComponentChildren } from "preact";
import { getCurrentUrl, useRouter } from "preact-router";

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

  return (
    <header class="surface-hero" data-surface="hero">
      <div class="bg-[var(--bb-bg-primary)] text-[var(--bb-fg-primary)]">
        <div class="mx-auto flex min-h-14 max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6 lg:px-8">
          <a href="https://benchbox.dev/" class="font-mono text-lg font-bold no-underline text-[var(--bb-accent)]">
            BenchBox
          </a>
          <nav aria-label="BenchBox" class="flex flex-wrap items-center gap-4 text-sm">
            <GlobalNavLink href="https://benchbox.dev/docs/">Docs</GlobalNavLink>
            <GlobalNavLink href="https://benchbox.dev/blog/">Blog</GlobalNavLink>
            <GlobalNavLink href="/results/" active={inResults}>
              Results
            </GlobalNavLink>
            <GlobalNavLink href="https://github.com/joeharris76/BenchBox">GitHub</GlobalNavLink>
            <a
              href="https://benchbox.dev/docs/usage/installation.html"
              class="rounded-md bg-[var(--bb-accent)] px-3 py-1.5 text-sm font-semibold text-[var(--bb-fg-inverse)] no-underline hover:bg-[var(--bb-accent-hover)] hover:text-[var(--bb-fg-primary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--bb-focus-ring)]"
            >
              Run benchmark
            </a>
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
      class={`font-medium no-underline rounded-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--bb-focus-ring)] ${
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
      class={`whitespace-nowrap border-b-2 py-3 font-medium no-underline rounded-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--bb-focus-ring)] ${
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
