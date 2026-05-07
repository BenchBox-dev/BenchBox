import type { RoutableProps } from "preact-router";
import { useDocumentTitle } from "@/lib/useDocumentTitle";

interface NotFoundProps extends RoutableProps {
  /** Optional context-specific copy that replaces the default
   *  "Page not found." sub-heading. Pass when the caller can give the user
   *  a more informative reason than the generic 404 (e.g. "Benchmark
   *  `foo` is not part of the published corpus."). */
  message?: string;
}

export function NotFound({ message }: NotFoundProps = {}) {
  useDocumentTitle("Not found · BenchBox Results");
  return (
    <div class="mx-auto max-w-7xl px-4 py-24 text-center sm:px-6 lg:px-8">
      <h1 class="text-4xl font-bold text-[var(--bb-data-fg-primary)]">404</h1>
      <p class="mt-4 text-lg text-[var(--bb-data-fg-muted)]">{message ?? "Page not found."}</p>
      <a href="/results/" class="mt-6 inline-block btn btn-primary no-underline">
        Back to Results
      </a>
    </div>
  );
}
