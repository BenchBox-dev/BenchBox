import type { RoutableProps } from "preact-router";

export function NotFound(_: RoutableProps) {
  return (
    <div class="mx-auto max-w-7xl px-4 py-24 text-center sm:px-6 lg:px-8">
      <h1 class="text-4xl font-bold text-gray-900">404</h1>
      <p class="mt-4 text-lg text-gray-600">Page not found.</p>
      <a href="/results/" class="mt-6 inline-block btn btn-primary no-underline">
        Back to Results
      </a>
    </div>
  );
}
