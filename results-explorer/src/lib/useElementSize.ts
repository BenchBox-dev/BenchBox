/**
 * useElementSize - ResizeObserver hook for responsive SVG charts.
 *
 * Returns a ref to attach to a container element and the observed
 * { width, height } in CSS pixels.  When the element hasn't been
 * measured yet (e.g. SSR, first render before effects run), falls back
 * to `defaultWidth × defaultHeight` so charts render at a useful size
 * rather than collapsing to zero.
 *
 * ResizeObserver is available in all modern browsers since 2020.
 * If it is not available (e.g. old test environments without a polyfill),
 * the hook falls back to `offsetWidth × offsetHeight` from the first
 * effect run and does not observe subsequent changes.
 */

import { useEffect, useRef, useState } from "preact/hooks";
import type { RefObject } from "preact";

export interface ElementSize {
  width: number;
  height: number;
}

/**
 * @param defaultWidth  Fallback width before the first measurement. Default: 600.
 * @param defaultHeight Fallback height before the first measurement. Default: 0.
 */
export function useElementSize(defaultWidth = 600, defaultHeight = 0): [RefObject<HTMLDivElement>, ElementSize] {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState<ElementSize>({ width: defaultWidth, height: defaultHeight });

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    // Initial synchronous measurement covers the common case where the element
    // has a known width before any resize events fire.
    // All current consumers use only `width`; height starts at 0 before the SVG
    // renders its own computed height, so `|| h > 0` ensures we still capture
    // width early without requiring both dimensions to be positive.
    const w = el.offsetWidth;
    const h = el.offsetHeight;
    if (w > 0 || h > 0) {
      setSize({ width: w, height: h });
    }

    if (typeof ResizeObserver === "undefined") return;

    const ro = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      const { width, height } = entry.contentRect;
      const w = Math.round(width);
      const h = Math.round(height);
      if (w > 0 || h > 0) {
        // Functional update skips a re-render when dimensions haven't changed
        // (e.g. vertical-only resizes on a fixed-width container).
        setSize((prev) => (prev.width === w && prev.height === h ? prev : { width: w, height: h }));
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return [ref, size];
}
