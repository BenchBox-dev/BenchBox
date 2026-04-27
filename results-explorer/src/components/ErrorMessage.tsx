interface ErrorMessageProps {
  title?: string;
  message: string;
}

export function ErrorMessage({ title = "Error", message }: ErrorMessageProps) {
  return (
    <div class="rounded-lg border border-red-200 bg-red-50 p-6">
      <h3 class="mb-1 text-sm font-semibold text-red-800">{title}</h3>
      <p class="text-sm text-red-700">{message}</p>
    </div>
  );
}
