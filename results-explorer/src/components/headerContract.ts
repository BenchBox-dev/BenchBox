export interface HeaderLink {
  readonly label: string;
  readonly href: string;
  readonly external?: boolean;
  readonly activeOnSurface?: "landing" | "docs" | "blog" | "results";
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
  { label: "GitHub", href: "https://github.com/BenchBox-dev/BenchBox", external: true },
];

export const HEADER_CTA = {
  label: "Run benchmark",
  href: "https://benchbox.dev/docs/usage/installation.html",
} as const;

export const HEADER_NAV_ARIA_LABEL = "BenchBox";
export const HEADER_TOGGLE_ARIA_LABEL = "Toggle site navigation";

export const FOOTER_THEME_ARIA_LABEL = "Color theme";
export const FOOTER_THEME_OPTION_LABELS = {
  system: "System theme",
  light: "Light theme",
  dark: "Dark theme",
} as const;

export const HEADER_DESKTOP_MIN_HEIGHT_PX = 64;
export const HEADER_MOBILE_MIN_HEIGHT_PX = 60;
export const HEADER_HEIGHT_TOLERANCE_PX = 8;

export function getHeaderVisibleLabels(): string[] {
  return [...HEADER_LINKS.map((link) => link.label), HEADER_CTA.label];
}
