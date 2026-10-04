import type { ComponentChildren } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import { useThemeChoice } from "@/lib/theme";
import {
  SHELL_FOOTER_LEGAL,
  THEME_ICON_ATTRS,
  THEME_ICON_SHAPES,
  THEME_OPTIONS,
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
  const [open, setOpen] = useState(false);
  const headerRef = useRef<HTMLElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const brand = shellBrand("absolute");
  const links = shellLinks(pathname, "absolute");
  const cta = shellCta("absolute");

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      toggleRef.current?.focus();
    };
    const onPointerDown = (event: Event) => {
      if (headerRef.current && event.target instanceof Node && !headerRef.current.contains(event.target)) setOpen(false);
    };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("click", onPointerDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("click", onPointerDown);
    };
  }, [open]);

  return (
    <header
      ref={headerRef}
      class="site-header"
      data-site-header
      data-open={open ? "true" : "false"}
      data-testid={testId}
    >
      <div class="site-header__inner">
        <a class="site-header__logo" href={brand.href}>
          {brand.label}
        </a>
        <button
          ref={toggleRef}
          class="site-header__toggle"
          type="button"
          aria-label={shellLabels.toggle}
          aria-controls="site-header-panel"
          aria-expanded={open ? "true" : "false"}
          data-site-header-toggle
          onClick={() => setOpen((value) => !value)}
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
        <ThemeToggle />
      </div>
    </footer>
  );
}

function ThemeIcon({ option }: { option: ThemeOption }) {
  return (
    <svg {...THEME_ICON_ATTRS} aria-hidden="true" focusable="false">
      {THEME_ICON_SHAPES[option].map((shape, index) =>
        shape.tag === "circle" ? <circle key={index} {...shape.attrs} /> : <path key={index} {...shape.attrs} />,
      )}
    </svg>
  );
}

export function ThemeToggle() {
  const { choice, setChoice } = useThemeChoice();
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);

  function selectAt(index: number) {
    const option = THEME_OPTIONS[index];
    if (!option) return;
    setChoice(option);
    optionRefs.current[index]?.focus();
  }

  function handleKeyDown(event: KeyboardEvent, index: number) {
    const count = THEME_OPTIONS.length;
    let next: number;
    switch (event.key) {
      case "ArrowRight":
      case "ArrowDown":
        next = (index + 1) % count;
        break;
      case "ArrowLeft":
      case "ArrowUp":
        next = (index - 1 + count) % count;
        break;
      case "Home":
        next = 0;
        break;
      case "End":
        next = count - 1;
        break;
      case " ":
      case "Enter":
        next = index;
        break;
      default:
        return;
    }
    event.preventDefault();
    selectAt(next);
  }

  return (
    <div class="theme-toggle" role="radiogroup" aria-label={shellLabels.theme}>
      {THEME_OPTIONS.map((option, index) => {
        const selected = choice === option;
        const label = shellLabels.themeOptions[option];
        return (
          <button
            key={option}
            ref={(element) => {
              optionRefs.current[index] = element;
            }}
            type="button"
            role="radio"
            aria-checked={selected}
            aria-label={label}
            title={label}
            tabIndex={selected ? 0 : -1}
            data-theme-option={option}
            onClick={() => selectAt(index)}
            onKeyDown={(event) => handleKeyDown(event, index)}
          >
            <ThemeIcon option={option} />
          </button>
        );
      })}
    </div>
  );
}
