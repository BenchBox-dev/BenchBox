import type { ComponentChildren } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import { useThemeChoice } from "@/lib/theme";
import {
  SHELL_FOOTER_LEGAL,
  THEME_ICON_ATTRS,
  THEME_ICON_SHAPES,
  THEME_OPTIONS,
  logoGrid,
  nextThemeOption,
  shellBrand,
  shellCta,
  shellLabels,
  shellLinks,
  type ThemeOption,
} from "@/components/shellModel";

interface SiteHeaderProps {
  pathname: string;
  testId?: string;
}

export function SiteHeader({ pathname, testId }: SiteHeaderProps) {
  const [open, setOpenState] = useState(false);
  const openRef = useRef(false);
  const panelFocusRef = useRef(false);
  const headerRef = useRef<HTMLElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const brand = shellBrand("absolute");
  const links = shellLinks(pathname, "absolute");
  const cta = shellCta("absolute");

  function setOpen(next: boolean) {
    openRef.current = next;
    setOpenState(next);
  }

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(min-width: 56.3125rem)");
    const onChange = (event: MediaQueryListEvent) => {
      if (event.matches) {
        setOpen(false);
        return;
      }
      const active = document.activeElement;
      const inPanel = active instanceof HTMLElement && active.closest("[data-site-header-panel]") !== null;
      if (inPanel || (panelFocusRef.current && (active === null || active === document.body))) toggleRef.current?.focus();
      panelFocusRef.current = false;
    };
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!openRef.current || event.key !== "Escape" || document.querySelector('dialog[open], [aria-modal="true"]')) return;
      setOpen(false);
      toggleRef.current?.focus();
    };
    const onClick = (event: Event) => {
      if (!(event.target instanceof Element && event.target.closest("[data-site-header-panel]"))) panelFocusRef.current = false;
      if (openRef.current && headerRef.current && event.target instanceof Node && !headerRef.current.contains(event.target)) setOpen(false);
    };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("click", onClick);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("click", onClick);
    };
  }, []);

  return (
    <header
      ref={headerRef}
      class="site-header"
      data-site-header
      data-open={open ? "true" : "false"}
      data-testid={testId}
      onFocusIn={(event) => {
        panelFocusRef.current = event.target instanceof Element && event.target.closest("[data-site-header-panel]") !== null;
      }}
      onFocusOut={(event) => {
        const next = event.relatedTarget;
        if (next instanceof Element && !next.closest("[data-site-header-panel]")) panelFocusRef.current = false;
        if (openRef.current && next instanceof Node && !headerRef.current?.contains(next)) setOpen(false);
      }}
    >
      <div class="site-header__inner">
        <a class="site-header__logo" href={brand.href}>
          <Logo />
          <span class="site-header__logo-text">{brand.label}</span>
        </a>
        <button
          ref={toggleRef}
          class="site-header__toggle"
          type="button"
          aria-label={shellLabels.toggle}
          aria-controls="site-header-panel"
          aria-expanded={open ? "true" : "false"}
          data-site-header-toggle
          onClick={() => setOpen(!openRef.current)}
        >
          <span class="site-header__toggle-lines" aria-hidden="true" />
        </button>
        <div id="site-header-panel" class="site-header__panel" data-site-header-panel>
          <nav
            id="benchbox-site-header-nav"
            class="site-header__nav"
            aria-label={shellLabels.nav}
            data-site-header-nav
            onClick={(event) => {
              if (event.target instanceof Element && event.target.closest("a")) setOpen(false);
            }}
          >
            {links.map((link) => (
              <a
                key={link.label}
                class="site-header__link"
                href={link.href}
                target={link.external ? "_blank" : undefined}
                rel={link.external ? "noopener" : undefined}
                aria-current={link.current ? "page" : undefined}
              >
                {link.label}
              </a>
            ))}
            <a class="site-header__cta" href={cta.href}>
              {cta.label}
            </a>
          </nav>
        </div>
        <div class="site-header__tools">
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}

interface SiteFooterProps {
  pathname: string;
  children?: ComponentChildren;
}

export function SiteFooter({ pathname, children }: SiteFooterProps) {
  const links = shellLinks(pathname, "absolute");
  return (
    <footer class="site-footer" data-site-footer>
      <div class="site-footer__inner">
        <p class="site-footer__legal">{SHELL_FOOTER_LEGAL}</p>
        {children}
        <nav class="site-footer__nav" aria-label={shellLabels.footerNav}>
          {links.map((link) => (
            <a
              key={link.label}
              class="site-footer__link"
              href={link.href}
              target={link.external ? "_blank" : undefined}
              rel={link.external ? "noopener" : undefined}
            >
              {link.label}
            </a>
          ))}
        </nav>
      </div>
    </footer>
  );
}

function Logo() {
  const { width, height, cells } = logoGrid();
  return (
    <svg
      class="logo"
      viewBox={`0 0 ${width} ${height}`}
      shape-rendering="crispEdges"
      fill="currentColor"
      aria-hidden="true"
      focusable="false"
    >
      {cells.map((cell) => (
        <rect key={`${cell.x}-${cell.y}`} x={cell.x} y={cell.y} width={cell.width} height="1" />
      ))}
    </svg>
  );
}

function ThemeIcon({ option }: { option: ThemeOption }) {
  return (
    <svg {...THEME_ICON_ATTRS} class="theme-toggle__icon" data-theme-icon={option} aria-hidden="true" focusable="false">
      {THEME_ICON_SHAPES[option].map((shape, index) =>
        shape.tag === "circle" ? <circle key={index} {...shape.attrs} /> : <path key={index} {...shape.attrs} />,
      )}
    </svg>
  );
}

export function ThemeToggle() {
  const { choice, setChoice } = useThemeChoice();
  const next = nextThemeOption(choice);
  const label = shellLabels.themeOptions[choice];
  return (
    <button
      type="button"
      class="theme-toggle"
      data-theme-toggle
      data-theme-choice={choice}
      aria-label={`${shellLabels.theme}: ${label}`}
      title={`${label}. Switch to ${shellLabels.themeOptions[next]}.`}
      onClick={() => setChoice(next)}
    >
      {THEME_OPTIONS.map((option) => (
        <ThemeIcon key={option} option={option} />
      ))}
    </button>
  );
}
