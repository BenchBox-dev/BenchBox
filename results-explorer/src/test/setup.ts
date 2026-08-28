import "@testing-library/jest-dom";

class TestResizeObserver implements ResizeObserver {
  constructor(private readonly callback: ResizeObserverCallback) {}

  observe(target: Element): void {
    this.callback([{ target, contentRect: target.getBoundingClientRect() } as ResizeObserverEntry], this);
  }

  unobserve(): void {}

  disconnect(): void {}
}

globalThis.ResizeObserver = TestResizeObserver;

if (typeof HTMLElement !== "undefined") {
  for (const property of ["clientWidth", "scrollWidth"] as const) {
    Object.defineProperty(HTMLElement.prototype, property, {
      configurable: true,
      get() {
        const element = this as HTMLElement;
        const explicit = element.dataset[property];
        if (explicit !== undefined) return Number(explicit);
        if (element.classList.contains("overflow-x-auto")) return property === "clientWidth" ? 800 : 1200;
        return 1024;
      },
    });
  }
}
