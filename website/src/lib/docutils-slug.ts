export function docutilsSlug(text: string): string {
  const slug = text
    .normalize("NFKD")
    .replace(/[^\x00-\x7f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^[-0-9]+|-+$/g, "");
  return slug || "id";
}
