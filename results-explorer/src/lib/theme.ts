import { useEffect, useState } from "preact/hooks";

export type ThemeChoice = "system" | "light" | "dark";
export type EffectiveTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "benchbox:theme";
export const THEME_CHOICES: readonly ThemeChoice[] = ["system", "light", "dark"];

function systemTheme(): EffectiveTheme {
  if (typeof window === "undefined" || !window.matchMedia) return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function normalizeThemeChoice(value: string | null | undefined): ThemeChoice {
  return value === "light" || value === "dark" || value === "system" ? value : "system";
}

export function effectiveTheme(choice: ThemeChoice): EffectiveTheme {
  return choice === "system" ? systemTheme() : choice;
}

export function readThemeChoice(): ThemeChoice {
  if (typeof window === "undefined") return "system";
  try {
    return normalizeThemeChoice(window.localStorage.getItem(THEME_STORAGE_KEY));
  } catch {
    return "system";
  }
}

export function applyThemeChoice(choice: ThemeChoice): EffectiveTheme {
  const effective = effectiveTheme(choice);
  if (typeof document !== "undefined") {
    document.documentElement.dataset.bbThemeChoice = choice;
    document.documentElement.dataset.bbTheme = effective;
    document.documentElement.dataset.theme = effective;
    document.documentElement.style.colorScheme = effective;
    document.body?.setAttribute("data-theme", effective);
  }
  return effective;
}

export function persistThemeChoice(choice: ThemeChoice) {
  if (typeof window === "undefined") return;
  try {
    if (choice === "system") {
      window.localStorage.removeItem(THEME_STORAGE_KEY);
    } else {
      window.localStorage.setItem(THEME_STORAGE_KEY, choice);
    }
  } catch {
    // Storage can be unavailable in privacy contexts; data attributes still update.
  }
}

export function nextThemeChoice(choice: ThemeChoice): ThemeChoice {
  const index = THEME_CHOICES.indexOf(choice);
  return THEME_CHOICES[(index + 1) % THEME_CHOICES.length] ?? "system";
}

export function useThemeChoice() {
  const [choice, setChoiceState] = useState<ThemeChoice>(() => {
    const documentChoice = typeof document === "undefined" ? undefined : document.documentElement.dataset.bbThemeChoice;
    return normalizeThemeChoice(documentChoice ?? readThemeChoice());
  });
  const [theme, setTheme] = useState<EffectiveTheme>(() => effectiveTheme(choice));

  function setChoice(next: ThemeChoice) {
    persistThemeChoice(next);
    setChoiceState(next);
    setTheme(applyThemeChoice(next));
  }

  useEffect(() => {
    setTheme(applyThemeChoice(choice));
    if (!window.matchMedia) return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      if (choice === "system") setTheme(applyThemeChoice("system"));
    };
    if (media.addEventListener) {
      media.addEventListener("change", onChange);
      return () => media.removeEventListener("change", onChange);
    }
    media.addListener?.(onChange);
    return () => media.removeListener?.(onChange);
  }, [choice]);

  return { choice, theme, setChoice };
}
