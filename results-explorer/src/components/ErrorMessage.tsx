interface ErrorMessageProps {
  title?: string;
  message: string;
}

export function ErrorMessage({ title = "Error", message }: ErrorMessageProps) {
  return (
    <div role="alert" class="rounded-lg p-6 tone-danger">
      <h3 class="mb-1 text-sm font-semibold">{title}</h3>
      <p class="text-sm">{message}</p>
    </div>
  );
}
