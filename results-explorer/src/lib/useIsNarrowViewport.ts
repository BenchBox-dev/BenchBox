import { useEffect, useState } from "preact/hooks";

/**
 * Tracks whether the viewport currently matches `query` via `matchMedia`, so
 * components can swap layout without each re-deriving the same SSR guard and
 * subscribe/cleanup dance.
 *
 * Uses only `addEventListener`/`removeEventListener`, which every browser
 * this app targets has shipped since 2020. `lib/theme.ts` additionally falls
 * back to the deprecated `addListener`/`removeListener` pair for pre-14
 * Safari; that fallback is left where it is rather than folded in here - this
 * hook has no evidence that its callers need to support browsers that old,
 * and the mirrored effects it replaces (`CompareTray`, `SubmissionActivity`)
 * never carried it either.
 */
export function useIsNarrowViewport(query: string): boolean {
  const [matches, setMatches] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mql = window.matchMedia(query);
    const update = () => setMatches(mql.matches);
    update();
    mql.addEventListener("change", update);
    return () => mql.removeEventListener("change", update);
  }, [query]);

  return matches;
}
