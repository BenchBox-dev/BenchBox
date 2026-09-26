// Information architecture for the Results Explorer secondary navigation.
//
// The secondary nav (Overview / Benchmarks / Platforms / Compare / Find runs,
// plus the local-result action) is intentionally separate from the global
// site header: the header contract owns cross-surface parity while this
// module owns which explorer section a route belongs to.
//
// Every route rendered by `app.tsx` resolves to exactly one section or to
// explicitly no section, and `RESULTS_NAV_SECTIONS` is the single place
// where that mapping lives. In particular:
//
// - Benchmark detail pages (`/results/:benchmark/`) belong to Benchmarks.
// - Platform detail pages (`/results/p/:platform/`) belong to Platforms.
// - Run detail pages (`/results/r/:resultId`, `.../passes`) belong to no
//   section: the URL carries no benchmark slug, so no section can own them.
//   Those pages carry their own Breadcrumb wayfinding instead.
// - Local previews (`/results/local*`) belong to the local-result action,
//   which is a file action, not a route link.

export interface ResultsNavSection {
  readonly id: "overview" | "benchmarks" | "platforms" | "compare" | "query";
  readonly label: string;
  readonly href: string;
  /** Return true when the given explorer path belongs to this section. */
  readonly isActivePath: (path: string) => boolean;
}

// Single-segment paths under /results/ owned by a section other than a
// benchmark detail page. Any other single segment is a benchmark slug and
// belongs to Benchmarks. Keep in lockstep with the routes in `app.tsx`:
// adding a route here without a section silently highlights Benchmarks.
const RESERVED_RESULTS_SEGMENTS: ReadonlySet<string> = new Set([
  "benchmarks",
  "platforms",
  "compare",
  "query",
  "p",
  "r",
  "local",
]);

function firstSegment(path: string): string | null {
  const match = /^\/results\/([^/]+)\/?$/.exec(path);
  return match ? (match[1] ?? null) : null;
}

function isBenchmarkDetailPath(path: string): boolean {
  const segment = firstSegment(path);
  return segment !== null && !RESERVED_RESULTS_SEGMENTS.has(segment);
}

export const RESULTS_NAV_SECTIONS: readonly ResultsNavSection[] = [
  {
    id: "overview",
    label: "Overview",
    href: "/results/",
    isActivePath: (path) => path === "/results" || path === "/results/",
  },
  {
    id: "benchmarks",
    label: "Benchmarks",
    href: "/results/benchmarks/",
    isActivePath: (path) => path === "/results/benchmarks" || path === "/results/benchmarks/" || isBenchmarkDetailPath(path),
  },
  {
    id: "platforms",
    label: "Platforms",
    href: "/results/platforms/",
    isActivePath: (path) =>
      path === "/results/platforms" ||
      path === "/results/platforms/" ||
      path.startsWith("/results/p/"),
  },
  {
    id: "compare",
    label: "Compare",
    href: "/results/compare",
    isActivePath: (path) => path.startsWith("/results/compare"),
  },
  {
    id: "query",
    label: "Find runs",
    href: "/results/query",
    isActivePath: (path) => path.startsWith("/results/query"),
  },
];

/** Return the section that owns the given explorer path, or null. */
export function activeResultsNavSection(path: string): ResultsNavSection | null {
  return RESULTS_NAV_SECTIONS.find((section) => section.isActivePath(path)) ?? null;
}

/** Return true when the given explorer path is a local-result preview. */
export function isLocalResultPath(path: string): boolean {
  return path === "/results/local" || path === "/results/local/" || path.startsWith("/results/local/");
}
