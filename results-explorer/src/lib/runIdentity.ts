// Run-identity formatter: produces stable, distinguishable labels for
// benchmark runs across charts, compare controls, and tables.
//
// The motivating problem (`results-explorer-run-identity-disambiguation`):
// repeated `platform` values like "DataFusion", "Polars", "PySpark", and
// "Spark" produce indistinguishable column headers, legend rows, and
// compare-card titles whenever two runs share a platform name. Color
// alone is not enough to identify a run.
//
// Contract:
//   - The same source row should produce the same label across variants
//     (modulo length/composition).
//   - When a cohort is supplied (e.g., the four runs in a Compare view
//     or the row set on a Rank chart), `formatRunIdentitiesForCohort`
//     appends *only enough* qualifiers to make every label in the cohort
//     unique. Non-duplicate runs keep their plain platform label.
//   - Qualifier priority: driver/platform version → run date → scale →
//     deployment fingerprint → trust tier → short result_id (last
//     resort, only when nothing else differs).

export interface RunIdentitySource {
  result_id: string;
  short_id?: string | null;
  platform: string;
  platform_version?: string | null;
  driver_version?: string | null;
  run_date?: string | null;
  scale_factor?: number | null;
  deployment_class?: string | null;
  instance_or_warehouse?: string | null;
  trust_label?: string | null;
}

export type RunIdentityVariant =
  | "compact"
  | "chart"
  | "table"
  | "selectOption"
  | "tooltip";

export interface RunIdentityLabels {
  compact: string;
  disambiguated: string;
  table: string;
  full: string;
  title: string;
  ariaLabel: string;
}

interface QualifierDescriptor {
  key: string;
  value: (source: RunIdentitySource) => string | null;
}

interface QualifierSlot {
  key: string;
  value: string;
}

// Natural qualifiers (in priority order) that distinguish runs in a
// human-meaningful way. The result_id tiebreaker is intentionally NOT
// in this list — it is only appended by the cohort-aware code path
// when no natural qualifier disambiguates a duplicate platform name.
const NATURAL_QUALIFIERS: QualifierDescriptor[] = [
  {
    key: "version",
    value: (s) => versionLabel(s.driver_version ?? s.platform_version ?? null),
  },
  { key: "run_date", value: (s) => (s.run_date ? s.run_date.slice(0, 10) : null) },
  {
    key: "scale_factor",
    value: (s) => (s.scale_factor !== null && s.scale_factor !== undefined ? `SF ${s.scale_factor}` : null),
  },
  {
    key: "deployment",
    value: (s) => {
      const parts: string[] = [];
      if (s.deployment_class && s.deployment_class !== "local") parts.push(s.deployment_class);
      if (s.instance_or_warehouse) parts.push(s.instance_or_warehouse);
      return parts.length > 0 ? parts.join(" ") : null;
    },
  },
  { key: "trust_label", value: (s) => (s.trust_label ? s.trust_label : null) },
];

function describeNaturalQualifiers(source: RunIdentitySource): string[] {
  const out: string[] = [];
  for (const qualifier of NATURAL_QUALIFIERS) {
    const value = qualifier.value(source);
    if (value !== null && value !== "") out.push(value);
  }
  return out;
}

function versionLabel(version: string | null | undefined): string | null {
  if (!version) return null;
  return version.startsWith("v") || version.startsWith("V") ? version : `v${version}`;
}

function shortResultIdToken(resultId: string): string {
  const parts = resultId.split(/[-_./:]+/).filter(Boolean);
  if (parts.length > 1) return parts[parts.length - 1]!;
  return resultId.slice(-8);
}

function compactIdToken(source: RunIdentitySource): string {
  const shortId = source.short_id?.trim();
  return shortId && /^[0-9a-f]{8,}$/i.test(shortId) ? shortId : shortResultIdToken(source.result_id);
}

// Cohort-aware qualifier list: natural qualifiers, then the trailing
// result_id token for compact disambiguation, then the full result_id as
// a guaranteed-unique terminal fallback. BenchBox result_ids end in the
// content hash segment, so the trailing token distinguishes typical
// same-platform duplicate runs without appending their shared prefix.
function describeCohortQualifierSlots(source: RunIdentitySource): QualifierSlot[] {
  const slots: QualifierSlot[] = [];
  for (const qualifier of NATURAL_QUALIFIERS) {
    const value = qualifier.value(source);
    if (value !== null && value !== "") slots.push({ key: qualifier.key, value });
  }
  slots.push({ key: "short_result_id", value: compactIdToken(source) });
  slots.push({ key: "result_id", value: source.result_id });
  return slots;
}

function distinguishingQualifierKeys(slotsBySource: readonly QualifierSlot[][], indices: readonly number[]): Set<string> {
  const keys = new Set(slotsBySource.flatMap((slots) => slots.map((slot) => slot.key)));
  const distinguishing = new Set<string>();
  for (const key of keys) {
    const values = new Set(
      indices.map((index) => slotsBySource[index]!.find((slot) => slot.key === key)?.value ?? ""),
    );
    if (values.size > 1) distinguishing.add(key);
  }
  return distinguishing;
}

function joinForVariant(base: string, qualifiers: string[], variant: RunIdentityVariant): string {
  if (qualifiers.length === 0) return base;
  switch (variant) {
    case "compact":
    case "chart":
      // Chart axes and tight legends — show every qualifier the cohort
      // needs to remain distinguishable, space-separated. Stripping any
      // qualifier would re-introduce duplicates.
      return `${base} ${qualifiers.join(" ")}`;
    case "table":
    case "selectOption":
      return `${base} · ${qualifiers.join(" · ")}`;
    case "tooltip":
      return `${base}\n${qualifiers.join("\n")}`;
    default:
      return base;
  }
}

/**
 * Single-source formatter. Use this when the caller does not have a
 * cohort context. The output always includes the platform name and may
 * include the highest-priority qualifier(s).
 *
 * For chart axes and tight legends prefer the cohort-aware
 * `formatRunIdentitiesForCohort`, which only attaches qualifiers when
 * the cohort has duplicates.
 */
export function formatRunIdentity(source: RunIdentitySource, variant: RunIdentityVariant): string {
  return joinForVariant(source.platform, describeNaturalQualifiers(source), variant);
}

/**
 * Cohort-aware formatter. For each source in `sources`, returns the
 * shortest label (within the chosen variant) that is unique across the
 * cohort. Non-duplicates keep their plain platform name; duplicates
 * append qualifiers in priority order until they are distinguishable.
 *
 * The returned array is parallel to the input array, so call sites can
 * use it with the same indexing as their existing data structures.
 */
export function formatRunIdentitiesForCohort(
  sources: readonly RunIdentitySource[],
  variant: RunIdentityVariant,
): string[] {
  const baseLabels = sources.map((source) => source.platform);
  // Buckets of sources that currently share a base platform name.
  const bucketsByLabel = new Map<string, number[]>();
  baseLabels.forEach((label, i) => {
    if (!bucketsByLabel.has(label)) bucketsByLabel.set(label, []);
    bucketsByLabel.get(label)!.push(i);
  });

  // Per-source qualifier slots (natural + last-resort ids).
  const slotsBySource = sources.map(describeCohortQualifierSlots);
  // Qualifiers selected for each source. Sources whose bucket has only one
  // entry stay empty.
  const usedQualifiers = sources.map((): string[] => []);

  // For every duplicate bucket, discard qualifiers that are invariant within
  // that bucket, then append distinguishing qualifiers until every label is
  // unique. The cap still walks through the terminal full-result_id fallback,
  // so ordinary same-platform duplicates do not silently collapse.
  for (const [, indices] of bucketsByLabel) {
    if (indices.length < 2) continue;
    const distinguishingKeys = distinguishingQualifierKeys(slotsBySource, indices);
    const qualifierLists = new Map(
      indices.map((i) => [
        i,
        slotsBySource[i]!
          .filter((slot) => distinguishingKeys.has(slot.key))
          .map((slot) => slot.value),
      ]),
    );
    const maxQualifiers = Math.max(...indices.map((i) => qualifierLists.get(i)!.length));
    let round = 0;
    while (round <= maxQualifiers) {
      const provisional = indices.map((i) => {
        const used = qualifierLists.get(i)!.slice(0, round);
        return `${sources[i]!.platform}${used.length > 0 ? " " + used.join(" ") : ""}`;
      });
      const seen = new Map<string, number>();
      let allUnique = true;
      for (const label of provisional) {
        const count = (seen.get(label) ?? 0) + 1;
        seen.set(label, count);
        if (count > 1) allUnique = false;
      }
      if (allUnique) break;
      round += 1;
    }
    for (const i of indices) usedQualifiers[i] = qualifierLists.get(i)!.slice(0, round);
  }

  return sources.map((source, i) => {
    return joinForVariant(source.platform, usedQualifiers[i]!, variant);
  });
}

export function formatRunIdentityFull(source: RunIdentitySource): string {
  const parts = [
    source.platform,
    versionLabel(source.driver_version ?? source.platform_version ?? null),
    source.run_date ? source.run_date.slice(0, 10) : null,
    source.scale_factor !== null && source.scale_factor !== undefined ? `SF ${source.scale_factor}` : null,
    NATURAL_QUALIFIERS.find((qualifier) => qualifier.key === "deployment")?.value(source) ?? null,
    source.trust_label ?? null,
    compactIdToken(source),
  ].filter((part): part is string => part !== null && part !== "");
  return parts.join(" · ");
}

export function formatRunIdentityLabelsForCohort(
  sources: readonly RunIdentitySource[],
): RunIdentityLabels[] {
  const compact = formatRunIdentitiesForCohort(sources, "compact");
  const disambiguated = formatRunIdentitiesForCohort(sources, "chart");
  const table = formatRunIdentitiesForCohort(sources, "table");
  return sources.map((source, index) => {
    const full = formatRunIdentityFull(source);
    return {
      compact: compact[index] ?? source.platform,
      disambiguated: disambiguated[index] ?? source.platform,
      table: table[index] ?? source.platform,
      full,
      title: full,
      ariaLabel: full,
    };
  });
}

export function truncateRunIdentityLabel(label: string, maxLen: number): string {
  if (label.length <= maxLen) return label;
  if (maxLen <= 1) return "…";

  const trailingToken = label.split(/\s+/).filter(Boolean).at(-1) ?? "";
  if (trailingToken.length >= 4 && trailingToken.length <= maxLen - 3) {
    const suffix = ` ${trailingToken}`;
    const headLen = Math.max(1, maxLen - suffix.length - 1);
    return `${label.slice(0, headLen).trimEnd()}…${suffix}`;
  }

  return middleTruncate(label, maxLen);
}

function middleTruncate(label: string, maxLen: number): string {
  if (label.length <= maxLen) return label;
  if (maxLen <= 1) return "…";
  const tailLen = Math.max(4, Math.floor((maxLen - 1) / 2));
  const headLen = Math.max(1, maxLen - tailLen - 1);
  return `${label.slice(0, headLen).trimEnd()}…${label.slice(-tailLen)}`;
}

export function preserveUniqueAfterTruncation(identities: readonly string[], maxLen: number): string[] {
  const truncated = identities.map((identity) => truncateRunIdentityLabel(identity, maxLen));
  const counts = new Map<string, number>();
  for (const value of truncated) counts.set(value, (counts.get(value) ?? 0) + 1);
  if ([...counts.values()].every((count) => count === 1)) return truncated;

  const repaired = identities.map((identity, index) => {
    const candidate = truncated[index]!;
    return (counts.get(candidate) ?? 0) > 1 ? middleTruncate(identity, maxLen) : candidate;
  });
  const repairedCounts = new Map<string, number>();
  for (const value of repaired) repairedCounts.set(value, (repairedCounts.get(value) ?? 0) + 1);
  if ([...repairedCounts.values()].every((count) => count === 1)) return repaired;

  return identities.map((identity, index) => {
    const candidate = repaired[index]!;
    return (repairedCounts.get(candidate) ?? 0) > 1 ? middleTruncate(`${identity} ${index + 1}`, maxLen) : candidate;
  });
}
