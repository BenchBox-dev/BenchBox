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
  return (
    <header class="border-b border-gray-200 bg-white shadow-sm">
      <div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div class="flex h-16 items-center justify-between">
          {/* Logo */}
          <a href="/results/" class="flex items-center gap-2 no-underline">
            <span class="text-xl font-bold text-gray-900">BenchBox</span>
            <span class="badge badge-blue">Results</span>
          </a>

          {/* Nav links */}
          <nav class="hidden items-center gap-6 sm:flex">
            <a href="/results/" class="text-sm font-medium text-gray-600 hover:text-gray-900 no-underline">
              Home
            </a>
            <a href="/results/tpch/" class="text-sm font-medium text-gray-600 hover:text-gray-900 no-underline">
              TPC-H
            </a>
            <a href="/results/star_schema/" class="text-sm font-medium text-gray-600 hover:text-gray-900 no-underline">
              SSB
            </a>
            <a href="/results/p/duckdb/" class="text-sm font-medium text-gray-600 hover:text-gray-900 no-underline">
              Platforms
            </a>
            <a
              href="/docs/contributing-results.html"
              class="text-sm font-medium text-gray-600 hover:text-gray-900 no-underline"
            >
              Submit a Result
            </a>
            <a href="/results/compare" class="btn-primary text-xs">
              Compare
            </a>
          </nav>

          {/* Mobile menu placeholder */}
          <div class="flex items-center gap-3 sm:hidden">
            <a href="/docs/contributing-results.html" class="text-xs font-medium text-gray-600 no-underline">
              Submit
            </a>
            <a href="/results/compare" class="btn-primary text-xs">
              Compare
            </a>
          </div>
        </div>
      </div>
    </header>
  );
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
