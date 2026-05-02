interface LoadingSpinnerProps {
  message?: string;
}

export function LoadingSpinner({ message = "Loading..." }: LoadingSpinnerProps) {
  return (
    <section
      role="status"
      aria-live="polite"
      aria-busy="true"
      class="mx-auto max-w-5xl px-4 py-10 sm:px-6 lg:px-8"
    >
      <p class="mb-4 text-sm font-medium text-gray-500">{message}</p>
      <div class="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm">
        <div class="grid grid-cols-4 gap-4 border-b border-gray-200 bg-gray-50 p-4">
          <SkeletonBlock className="h-4" />
          <SkeletonBlock className="h-4" />
          <SkeletonBlock className="h-4" />
          <SkeletonBlock className="h-4" />
        </div>
        <div class="divide-y divide-gray-100">
          {Array.from({ length: 5 }).map((_, row) => (
            <div key={row} class="grid grid-cols-4 gap-4 p-4 bb-skeleton-row">
              <SkeletonBlock className="h-4" />
              <SkeletonBlock className="h-4" />
              <SkeletonBlock className="h-4" />
              <SkeletonBlock className="h-4" />
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export function SkeletonBlock({ className = "" }: { className?: string }) {
  return <div aria-hidden="true" class={`bb-skeleton ${className}`} />;
}
