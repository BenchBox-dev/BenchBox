export function docIndexDir(id: string): string | undefined {
  return id.replace(/^docs\/?/, "").replace(/\/?index$/, "") || undefined;
}
