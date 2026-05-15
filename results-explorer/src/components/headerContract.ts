// Canonical contract for the shared BenchBox global header.
//
// landing/index.html, docs/_templates/page.html and landing/prompts/index.html
// emit this contract via the static `benchbox-site-header` class hooks
// defined in landing/shared/site-header.css. The Results Explorer is a Vite
// SPA and renders a Preact mirror in components/Layout.tsx; importing the
// shared static CSS into the Vite bundle is not currently practical because
// the theme-token cascade and shared deployment paths assume the static
// surfaces alone. Until that constraint changes, this module is the single
// source of truth for the visible global-header contract: Layout.tsx, the
// Layout unit tests, and the e2e header-parity gate all consume it, and the
// e2e gate cross-checks the same labels/hrefs against the static HTML.
//
// Update this file whenever the shared header markup changes; the parity
// tests will then fail until every consumer (landing, docs, prompts, the
// Results Preact mirror) is realigned.

export interface HeaderLink {
  readonly label: string;
  readonly href: string;
  readonly external?: boolean;
  // When set, this link must render `aria-current="page"` on the surface
  // whose path matches the predicate; e.g. "Results" is active under
  // `/results/*` in the Results Explorer.
  readonly activeOnSurface?: "landing" | "docs" | "blog" | "results" | "prompts";
}

export const HEADER_BRAND = {
  label: "BenchBox",
  href: "https://benchbox.dev/",
} as const;

export const HEADER_LINKS: readonly HeaderLink[] = [
  { label: "Home", href: "https://benchbox.dev/", activeOnSurface: "landing" },
  { label: "Docs", href: "https://benchbox.dev/docs/", activeOnSurface: "docs" },
  { label: "Blog", href: "https://benchbox.dev/blog/", activeOnSurface: "blog" },
  { label: "Results", href: "https://benchbox.dev/results/", activeOnSurface: "results" },
  { label: "Instruct an agent", href: "https://benchbox.dev/prompts/", activeOnSurface: "prompts" },
  { label: "GitHub", href: "https://github.com/joeharris76/BenchBox", external: true },
];

export const HEADER_CTA = {
  label: "Run benchmark",
  href: "https://benchbox.dev/docs/usage/installation.html",
} as const;

export const HEADER_NAV_ARIA_LABEL = "BenchBox";
export const HEADER_TOGGLE_ARIA_LABEL = "Toggle site navigation";

export const HEADER_THEME_LABELS = ["System", "Light", "Dark"] as const;
export const HEADER_THEME_ARIA_PATTERN =
  /^Theme:\s+(system|light|dark)\.\s+Activate to switch theme\.$/i;

// Bounding-box parity tolerances. The shared static CSS in
// `landing/shared/site-header.css` sets `min-height: 4rem` on desktop and
// `min-height: 3.75rem` at the mobile breakpoint. Results renders the same
// min-height via Tailwind (`min-h-16`). The parity gate asserts the rendered
// height stays within a tight band so future drift in either implementation
// fails the build instead of shipping silently.
export const HEADER_DESKTOP_MIN_HEIGHT_PX = 64;
export const HEADER_MOBILE_MIN_HEIGHT_PX = 60;
export const HEADER_HEIGHT_TOLERANCE_PX = 8;

export function getHeaderVisibleLabels(): string[] {
  return [...HEADER_LINKS.map((link) => link.label), HEADER_CTA.label];
}
