export function formatCount(count: number, singular: string, plural = `${singular}s`): string {
  const noun = count === 1 ? singular : plural;
  return `${count.toLocaleString()} ${noun}`;
}

export function formatWarningCount(count: number): string {
  return formatCount(count, "warning");
}

export function formatWarningClassSummary(count: number, labels: readonly string[], maxLabels = 3): string {
  if (count <= 0) return "No warnings";
  const visibleLabels = labels.slice(0, maxLabels);
  if (visibleLabels.length === 0) return formatWarningCount(count);
  const extraCount = Math.max(0, count - visibleLabels.length);
  const extraText = extraCount > 0 ? `, +${formatCount(extraCount, "more", "more")}` : "";
  return removeDuplicatedTerminalPunctuation(
    ensureSentence(`Warning classes: ${visibleLabels.join(", ")}${extraText}`),
  );
}

export function formatCandidateCount(count: number): string {
  return formatCount(count, "candidate");
}

export function formatSelectedCount(count: number, noun = "result"): string {
  return `${formatCount(count, noun)} selected`;
}

export function ensureSentence(value: string): string {
  const trimmed = value.trim();
  if (trimmed.length === 0) return "";
  return /[.!?]$/.test(trimmed) ? trimmed : `${trimmed}.`;
}

export function removeDuplicatedTerminalPunctuation(value: string): string {
  return value.replace(/([.!?])\1+/g, "$1");
}
