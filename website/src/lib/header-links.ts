import {
  FOOTER_THEME_ARIA_LABEL,
  FOOTER_THEME_OPTION_LABELS,
  HEADER_BRAND,
  HEADER_CTA,
  HEADER_LINKS,
  HEADER_NAV_ARIA_LABEL,
  HEADER_TOGGLE_ARIA_LABEL,
} from "../../../results-explorer/src/components/headerContract.ts";

export const SITE_ORIGIN = "https://benchbox.dev";

export type Surface = "landing" | "docs" | "blog" | "results";

export type ShellLink = { label: string; href: string; external: boolean; current: boolean };

export const shellLabels = {
  nav: HEADER_NAV_ARIA_LABEL,
  toggle: HEADER_TOGGLE_ARIA_LABEL,
  theme: FOOTER_THEME_ARIA_LABEL,
  themeOptions: FOOTER_THEME_OPTION_LABELS,
} as const;

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

export function shellBrand(): { label: string; href: string } {
  return { label: HEADER_BRAND.label, href: sitePath(HEADER_BRAND.href) };
}

export function shellLinks(pathname: string): ShellLink[] {
  const surface = surfaceFor(pathname);
  return HEADER_LINKS.map((link) => ({
    label: link.label,
    href: sitePath(link.href),
    external: link.external === true,
    current: link.activeOnSurface !== undefined && link.activeOnSurface === surface,
  }));
}

export function shellCta(): { label: string; href: string } {
  return { label: HEADER_CTA.label, href: sitePath(HEADER_CTA.href) };
}
