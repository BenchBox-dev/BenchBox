import { useEffect, useRef, useState } from "preact/hooks";
import type { RefObject } from "preact";

export interface ElementSize {
  width: number;
  height: number;
}

export function useElementSize(defaultWidth = 600, defaultHeight = 0): [RefObject<HTMLDivElement>, ElementSize] {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState<ElementSize>({ width: defaultWidth, height: defaultHeight });

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

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
        setSize((prev) => (prev.width === w && prev.height === h ? prev : { width: w, height: h }));
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return [ref, size];
}
