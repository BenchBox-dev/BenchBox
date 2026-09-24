/**
 * Version display splitting.
 *
 * Platform versions carry two very different kinds of information in one
 * string: a release core the reader compares across runs (`2.0.0`), and a
 * build or prerelease suffix that identifies one artifact (`-alpha38615`).
 * The suffix is longer than the core, varies per build, and is the reason
 * version values blow out column widths and chart labels. Split them so a
 * surface can lead with the core and keep the suffix one interaction away
 * without ever discarding it.
 */

export interface VersionParts {
  /** Normalized `v`-prefixed release core, e.g. `v2.0.0`. */
  core: string;
  /** Prerelease/build suffix including its leading separator, or null. */
  suffix: string | null;
  /** The full normalized version, core + suffix. */
  full: string;
}

const CORE_AND_SUFFIX = /^(v?\d+(?:\.\d+)*)([-+].*)$/;

/** Normalizes a raw version to a single `v`-prefixed string. */
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
