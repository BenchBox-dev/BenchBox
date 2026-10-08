import { render, waitFor, act } from "@testing-library/preact";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { useElementSize } from "@/lib/useElementSize";

let lastSizeUpdate: { width: number; height: number } | null = null;

function SizedBox({ defaultWidth = 600, defaultHeight = 0 }: { defaultWidth?: number; defaultHeight?: number }) {
  const [ref, size] = useElementSize(defaultWidth, defaultHeight);
  lastSizeUpdate = size;
  return <div ref={ref} data-testid="box" style="width:800px;height:200px" />;
}

type ROCallback = (entries: ResizeObserverEntry[]) => void;
let capturedCallback: ROCallback | null = null;
let disconnectSpy: ReturnType<typeof vi.fn>;
let observeSpy: ReturnType<typeof vi.fn>;

function installResizeObserver() {
  capturedCallback = null;
  disconnectSpy = vi.fn();
  observeSpy = vi.fn();
  class MockResizeObserver {
    constructor(cb: ROCallback) { capturedCallback = cb; }
    observe = observeSpy;
    disconnect = disconnectSpy;
  }
  (globalThis as Record<string, unknown>)["ResizeObserver"] = MockResizeObserver;
}

function removeResizeObserver() {
  delete (globalThis as Record<string, unknown>)["ResizeObserver"];
}

function fireResize(width: number, height: number) {
  capturedCallback?.([
    { contentRect: { width, height } } as unknown as ResizeObserverEntry,
  ]);
}

describe("useElementSize", () => {

  describe("(a) ResizeObserver unavailable", () => {
    beforeEach(() => {
      removeResizeObserver();
      Object.defineProperty(HTMLElement.prototype, "offsetWidth", {
        configurable: true,
        get: () => 0,
      });
    });

    afterEach(() => {
      removeResizeObserver();
      Object.defineProperty(HTMLElement.prototype, "offsetWidth", {
        configurable: true,
        get: () => 0,
      });
    });

    it("returns defaultWidth when offsetWidth is 0", async () => {
      lastSizeUpdate = null;
      render(<SizedBox defaultWidth={600} />);
      await waitFor(() => expect(lastSizeUpdate).not.toBeNull());
      expect(lastSizeUpdate!.width).toBe(600);
    });

    it("reads offsetWidth from element when non-zero", async () => {
      Object.defineProperty(HTMLElement.prototype, "offsetWidth", {
        configurable: true,
        get: () => 750,
      });
      lastSizeUpdate = null;
      render(<SizedBox defaultWidth={600} />);
      await waitFor(() => expect(lastSizeUpdate!.width).toBe(750));
    });
  });

  describe("(b) disconnect on unmount", () => {
    beforeEach(() => installResizeObserver());
    afterEach(() => removeResizeObserver());

    it("calls disconnect() when the hook unmounts", async () => {
      const { unmount } = render(<SizedBox />);
      act(() => { fireResize(800, 200); });
      unmount();
      expect(disconnectSpy).toHaveBeenCalledOnce();
    });
  });

  describe("(c) 0×0 resize ignored", () => {
    beforeEach(() => installResizeObserver());
    afterEach(() => removeResizeObserver());

    it("does not update size when resize fires with 0×0", async () => {
      lastSizeUpdate = null;
      render(<SizedBox defaultWidth={600} defaultHeight={400} />);
      act(() => { fireResize(0, 0); });
      await waitFor(() => expect(lastSizeUpdate).not.toBeNull());
      expect(lastSizeUpdate!.width).toBe(600);
      expect(lastSizeUpdate!.height).toBe(400);
    });
  });

  describe("(d) same-dimension resize skips re-render", () => {
    beforeEach(() => installResizeObserver());
    afterEach(() => removeResizeObserver());

    it("size object is stable (same reference) when dimensions unchanged", async () => {
      lastSizeUpdate = null;
      render(<SizedBox defaultWidth={600} />);
      act(() => { fireResize(700, 0); });
      await waitFor(() => expect(lastSizeUpdate!.width).toBe(700));
      const sizeBefore = lastSizeUpdate;
      act(() => { fireResize(700, 0); });
      expect(lastSizeUpdate).toBe(sizeBefore);
    });

    it("size object changes when dimensions differ", async () => {
      lastSizeUpdate = null;
      render(<SizedBox defaultWidth={600} />);
      act(() => { fireResize(700, 0); });
      await waitFor(() => expect(lastSizeUpdate!.width).toBe(700));
      const sizeBefore = lastSizeUpdate;
      act(() => { fireResize(900, 0); });
      await waitFor(() => expect(lastSizeUpdate!.width).toBe(900));
      expect(lastSizeUpdate).not.toBe(sizeBefore);
    });
  });
});
