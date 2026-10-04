import { useId } from "preact/hooks";
import { resetDuckDbInitializationFailures } from "@/db";

interface ErrorMessageProps {
  title?: string;
  message: string;
  onRetry?: () => void;
}

export function ErrorMessage({ title = "Something went wrong", message, onRetry }: ErrorMessageProps) {
  const titleId = useId();
  return (
    <div role="alert" aria-live="assertive" aria-atomic="true" aria-labelledby={titleId} class="rounded-lg p-6 tone-danger">
      <h3 id={titleId} class="mb-1 text-sm font-semibold">{title}</h3>
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
