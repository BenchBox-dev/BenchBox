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

// Natural qualifiers (in priority order) that distinguish runs in a
// human-meaningful way. The result_id tiebreaker is intentionally NOT
// in this list — it is only appended by the cohort-aware code path
// when no natural qualifier disambiguates a duplicate platform name.
const NATURAL_QUALIFIERS: ((s: RunIdentitySource) => string | null)[] = [
  (s) => (s.driver_version ? `v${s.driver_version}` : s.platform_version ? `v${s.platform_version}` : null),
  (s) => (s.run_date ? s.run_date.slice(0, 10) : null),
  (s) => (s.scale_factor !== null && s.scale_factor !== undefined ? `SF ${s.scale_factor}` : null),
  (s) => {
    const parts: string[] = [];
    if (s.deployment_class && s.deployment_class !== "local") parts.push(s.deployment_class);
    if (s.instance_or_warehouse) parts.push(s.instance_or_warehouse);
    return parts.length > 0 ? parts.join(" ") : null;
  },
  (s) => (s.trust_label ? s.trust_label : null),
];

function describeNaturalQualifiers(source: RunIdentitySource): string[] {
  const out: string[] = [];
  for (const fn of NATURAL_QUALIFIERS) {
    const value = fn(source);
    if (value !== null && value !== "") out.push(value);
  }
  return out;
}

function shortResultIdToken(resultId: string): string {
  const parts = resultId.split(/[-_./:]+/).filter(Boolean);
  if (parts.length > 1) return parts[parts.length - 1]!;
  return resultId.slice(-8);
}

// Cohort-aware qualifier list: natural qualifiers, then the trailing
// result_id token for compact disambiguation, then the full result_id as
// a guaranteed-unique terminal fallback. BenchBox result_ids end in the
// content hash segment, so the trailing token distinguishes typical
// same-platform duplicate runs without appending their shared prefix.
function describeCohortQualifiers(source: RunIdentitySource): string[] {
  return [...describeNaturalQualifiers(source), shortResultIdToken(source.result_id), source.result_id];
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

  // Per-source qualifier list (natural + last-resort short id).
  const qualifierLists = sources.map(describeCohortQualifiers);
  // Number of qualifier tiers each source needs to be unique within its
  // bucket. Sources whose bucket has only one entry stay at 0.
  const usedCounts = new Array(sources.length).fill(0);

  // For every duplicate bucket, append qualifiers until every label in
  // the bucket is unique. We track the qualifier-tier count per bucket
  // and apply it uniformly so members of the bucket carry comparable
  // detail. Round counts then translate to slices of each source's
  // qualifier list. The cap walks the full qualifier ladder for the
  // bucket — including the terminal full-result_id fallback — so the
  // loop always terminates with unique labels (within data
  // constraints) instead of silently accepting duplicates at a fixed
  // round count.
  for (const [, indices] of bucketsByLabel) {
    if (indices.length < 2) continue;
    const maxQualifiers = Math.max(...indices.map((i) => qualifierLists[i]!.length));
    let round = 0;
    while (round <= maxQualifiers) {
      const provisional = indices.map((i) => {
        const used = qualifierLists[i]!.slice(0, round);
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
    for (const i of indices) usedCounts[i] = round;
  }

  return sources.map((source, i) => {
    const used = qualifierLists[i]!.slice(0, usedCounts[i]);
    return joinForVariant(source.platform, used, variant);
  });
}
