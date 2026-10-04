import {
  FOOTER_THEME_ARIA_LABEL,
  FOOTER_THEME_OPTION_LABELS,
  HEADER_BRAND,
  HEADER_CTA,
  HEADER_LINKS,
  HEADER_NAV_ARIA_LABEL,
  HEADER_TOGGLE_ARIA_LABEL,
} from "./headerContract.ts";

export const SITE_ORIGIN = "https://benchbox.dev";

export type Surface = "landing" | "docs" | "blog" | "results";

export type HrefMode = "site" | "absolute";

export type ShellLink = { label: string; href: string; external: boolean; current: boolean };

export type ThemeOption = "system" | "light" | "dark";

export type IconShape = { tag: "circle"; attrs: Record<string, string> } | { tag: "path"; attrs: { d: string } };

export const shellLabels = {
  nav: HEADER_NAV_ARIA_LABEL,
  toggle: HEADER_TOGGLE_ARIA_LABEL,
  theme: FOOTER_THEME_ARIA_LABEL,
  themeOptions: FOOTER_THEME_OPTION_LABELS,
  footerNav: "Footer",
} as const;

export const SHELL_FOOTER_LEGAL = "BenchBox is open source under the MIT License.";

export const THEME_OPTIONS: readonly ThemeOption[] = ["system", "light", "dark"];

export const THEME_ICON_ATTRS = {
  width: "18",
  height: "18",
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  "stroke-width": "2",
  "stroke-linecap": "round",
  "stroke-linejoin": "round",
} as const;

export const THEME_ICON_SHAPES: Record<ThemeOption, readonly IconShape[]> = {
  system: [
    { tag: "circle", attrs: { cx: "8", cy: "8", r: "2.75" } },
    {
      tag: "path",
      attrs: { d: "M8 2.25v1M8 12.75v1M2.25 8h1M12.75 8h1M3.93 3.93l.7.7M3.93 12.07l.7-.7M12.07 3.93l-.7.7" },
    },
    { tag: "path", attrs: { d: "M21.5 17.2A5.6 5.6 0 1 1 14.8 10.5a5 5 0 0 0 6.7 6.7z" } },
  ],
  light: [
    { tag: "circle", attrs: { cx: "12", cy: "12", r: "4" } },
    {
      tag: "path",
      attrs: {
        d: "M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41",
      },
    },
  ],
  dark: [{ tag: "path", attrs: { d: "M20.5 14.1A8.5 8.5 0 1 1 9.9 3.5a7.6 7.6 0 0 0 10.6 10.6z" } }],
};

export function sitePath(href: string): string {
  return href.startsWith(`${SITE_ORIGIN}/`) ? href.slice(SITE_ORIGIN.length) : href;
}

export function surfaceFor(pathname: string): Surface | undefined {
  if (pathname === "/" || pathname === "/index.html") return "landing";
  for (const surface of ["docs", "blog", "results"] as const) {
    if (pathname === `/${surface}` || pathname.startsWith(`/${surface}/`) || pathname.startsWith(`/${surface}.`)) return surface;
  }
  return undefined;
}

function resolveHref(href: string, mode: HrefMode): string {
  return mode === "site" ? sitePath(href) : href;
}

export function shellBrand(mode: HrefMode = "site"): { label: string; href: string } {
  return { label: HEADER_BRAND.label, href: resolveHref(HEADER_BRAND.href, mode) };
}

export function shellLinks(pathname: string, mode: HrefMode = "site"): ShellLink[] {
  const surface = surfaceFor(pathname);
  return HEADER_LINKS.map((link) => ({
    label: link.label,
    href: resolveHref(link.href, mode),
    external: link.external === true,
    current: link.activeOnSurface !== undefined && link.activeOnSurface === surface,
  }));
}

export function shellCta(mode: HrefMode = "site"): { label: string; href: string } {
  return { label: HEADER_CTA.label, href: resolveHref(HEADER_CTA.href, mode) };
}
