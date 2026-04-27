interface LoadingSpinnerProps {
  message?: string;
}

export function LoadingSpinner({ message = "Loading..." }: LoadingSpinnerProps) {
  return (
    <div class="flex flex-col items-center justify-center gap-3 py-16">
      <div class="h-8 w-8 animate-spin rounded-full border-4 border-brand-200 border-t-brand-600" />
      <p class="text-sm text-gray-500">{message}</p>
    </div>
  );
}
