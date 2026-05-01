import type { ComponentChildren } from "preact";

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
  const currentPath = typeof window === "undefined" ? "/results/" : window.location.pathname;
  const inResults = currentPath === "/" || currentPath === "/results" || currentPath.startsWith("/results/");

  return (
    <header class="border-b border-gray-200 bg-white shadow-sm">
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
              class="rounded-md bg-[var(--bb-accent)] px-3 py-1.5 text-sm font-semibold text-[var(--bb-fg-inverse)] no-underline hover:bg-[var(--bb-accent-hover)] hover:text-white"
            >
              Run benchmark
            </a>
          </nav>
        </div>
      </div>
      <div class="border-t border-[var(--bb-border-subtle)] bg-white">
        <div class="mx-auto max-w-7xl overflow-x-auto px-4 sm:px-6 lg:px-8">
          <nav aria-label="Results Explorer" class="flex min-h-12 items-center gap-5 text-sm">
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
      class={`font-medium no-underline ${
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
      class={`whitespace-nowrap border-b-2 py-3 font-medium no-underline ${
        active
          ? "border-brand-600 text-gray-950"
          : "border-transparent text-gray-600 hover:border-gray-300 hover:text-gray-950"
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
    <footer class="border-t border-gray-200 bg-white py-8">
      <div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div class="flex flex-col items-center justify-between gap-4 sm:flex-row">
          <p class="text-sm text-gray-500">
            &copy; {new Date().getFullYear()} BenchBox. The current public corpus is{" "}
            <span class="font-medium">maintainer-curated</span>, and new submissions go through PR
            validation and maintainer review before they appear here. Reproduce runs with{" "}
            <code class="rounded bg-gray-100 px-1 py-0.5 text-xs">benchbox run</code>.
          </p>
          <nav class="flex items-center gap-4">
            <a href="https://benchbox.dev" class="text-sm text-gray-500 hover:text-gray-700 no-underline">
              benchbox.dev
            </a>
            <a href="https://github.com/joeharris76/BenchBox" class="text-sm text-gray-500 hover:text-gray-700 no-underline">
              GitHub
            </a>
          </nav>
        </div>
      </div>
    </footer>
  );
}
