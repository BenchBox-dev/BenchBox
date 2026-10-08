export interface VersionParts {
  core: string;
  suffix: string | null;
  full: string;
}

const CORE_AND_SUFFIX = /^(v?\d+(?:\.\d+)*)([-+].*)$/;

export function normalizeVersion(raw: string): string {
  const trimmed = raw.trim();
  if (trimmed === "") return trimmed;
  return /^v/i.test(trimmed) ? trimmed : `v${trimmed}`;
}

export function splitVersion(raw: string | null | undefined): VersionParts | null {
  if (raw === null || raw === undefined) return null;
  const full = normalizeVersion(raw);
  if (full === "") return null;
  const match = CORE_AND_SUFFIX.exec(full);
  if (!match) return { core: full, suffix: null, full };
  return { core: match[1]!, suffix: match[2]!, full };
}
