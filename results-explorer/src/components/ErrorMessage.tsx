import { resetDuckDbInitializationFailures } from "@/db";

interface ErrorMessageProps {
  title?: string;
  message: string;
  // Reissue the page read after the reader explicitly requests recovery.
  onRetry?: () => void;
}

export function ErrorMessage({ title = "Something went wrong", message, onRetry }: ErrorMessageProps) {
  return (
    <div role="alert" class="rounded-lg p-6 tone-danger">
      <h3 class="mb-1 text-sm font-semibold">{title}</h3>
      <p class="text-sm">{message}</p>
      {onRetry && (
        <button type="button" class="btn btn-secondary mt-3" onClick={() => {
          resetDuckDbInitializationFailures();
          onRetry();
        }}>
          Retry
        </button>
      )}
    </div>
  );
}
