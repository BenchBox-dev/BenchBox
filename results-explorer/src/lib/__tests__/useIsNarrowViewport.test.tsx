import { act, render } from "@testing-library/preact";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useIsNarrowViewport } from "@/lib/useIsNarrowViewport";

let lastValue: boolean | null = null;

function Probe({ query }: { query: string }) {
  lastValue = useIsNarrowViewport(query);
  return null;
}

/** Fake MediaQueryList whose `matches` can flip after render, firing every
 *  registered "change" listener - the path a real viewport resize takes. */
function stubResizableViewport(initialMatches: boolean) {
  let matches = initialMatches;
  const listeners = new Set<() => void>();
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      get matches() {
        return matches;
      },
      media: query,
      addEventListener: (_type: string, listener: () => void) => listeners.add(listener),
      removeEventListener: (_type: string, listener: () => void) => listeners.delete(listener),
    })),
  );
  return {
    change(next: boolean) {
      matches = next;
      for (const listener of listeners) listener();
    },
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  lastValue = null;
});

describe("useIsNarrowViewport", () => {
  it("reads the initial match state and updates when matchMedia reports a change", () => {
    const viewport = stubResizableViewport(false);
    render(<Probe query="(max-width: 639px)" />);
    expect(lastValue).toBe(false);

    act(() => viewport.change(true));
    expect(lastValue).toBe(true);
  });

  it("unsubscribes on unmount", () => {
    const removeEventListener = vi.fn();
    const addEventListener = vi.fn();
    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockImplementation((query: string) => ({
        matches: false,
        media: query,
        addEventListener,
        removeEventListener,
      })),
    );
    const { unmount } = render(<Probe query="(max-width: 639px)" />);
    expect(addEventListener).toHaveBeenCalledTimes(1);
    unmount();
    expect(removeEventListener).toHaveBeenCalledTimes(1);
  });
});
