import type { ComponentChildren } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import { FundingChip } from "@/components/FundingChip";
import { TrustBadge } from "@/components/TrustBadge";

export interface CompareTrayItem {
  id: string;
  platform: string;
  benchmarkLabel: string;
  scaleFactor: string | number;
  phase: string;
  runDate: string;
  trustLabel: string;
  funding: string | null | undefined;
  visibleResultId: string;
}

interface CompareTrayProps {
  summary: ComponentChildren;
  items: CompareTrayItem[];
  compareHref: string;
  compareLabel: string;
  onClear: () => void;
}

export function CompareTray({ summary, items, compareHref, compareLabel, onClear }: CompareTrayProps) {
  const trayRef = useRef<HTMLDivElement>(null);
  const [trayHeight, setTrayHeight] = useState(0);

  useEffect(() => {
    const tray = trayRef.current;
    if (!tray) return;

    const measure = () => setTrayHeight(Math.ceil(tray.getBoundingClientRect().height));
    measure();

    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(tray);
    return () => observer.disconnect();
  }, []);

  return (
    <>
      <div
        class="bb-compare-tray-spacer"
        data-testid="compare-tray-spacer"
        aria-hidden="true"
        style={{ height: `${trayHeight}px` }}
      />
      <div
        ref={trayRef}
        class="bb-compare-tray fixed bottom-0 left-0 right-0 z-50 border-t border-[var(--bb-data-border)] bg-[var(--bb-surface-data)] px-4 pt-3 shadow-lg"
        data-testid="compare-tray"
      >
        <div class="mx-auto flex max-w-7xl flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div class="min-w-0 flex-1">
            <div class="text-sm text-[var(--bb-data-fg-primary)]">{summary}</div>
            <div
              class="mt-2 flex max-h-32 flex-wrap gap-2 overflow-y-auto pr-1"
              role="list"
              aria-label="Selected compare results"
            >
              {items.map((item) => (
                <div
                  key={item.id}
                  data-testid={`compare-tray-row-${item.id}`}
                  role="listitem"
                  class="flex max-w-full flex-wrap items-center gap-1.5 rounded-md border border-[var(--bb-data-border)] bg-[var(--bb-surface-data-muted)] px-2 py-1 text-xs text-[var(--bb-data-fg-muted)]"
                >
                  <span class="font-medium text-[var(--bb-data-fg-primary)]">{item.platform}</span>
                  <span>{item.benchmarkLabel}</span>
                  <span>SF {item.scaleFactor}</span>
                  <span>{item.phase}</span>
                  <span>{item.runDate}</span>
                  <TrustBadge trustLabel={item.trustLabel} compact />
                  <FundingChip funding={item.funding} compact />
                  <span class="font-mono text-[var(--bb-data-fg-muted)]">Public ID {item.visibleResultId}</span>
                </div>
              ))}
            </div>
          </div>
          <div class="flex shrink-0 items-center gap-3">
            <button
              type="button"
              class="text-sm text-[var(--bb-data-fg-muted)] hover:text-[var(--bb-data-fg-primary)]"
              onClick={onClear}
            >
              Clear
            </button>
            <a href={compareHref} class="btn btn-primary text-sm no-underline">
              {compareLabel} →
            </a>
          </div>
        </div>
      </div>
    </>
  );
}
