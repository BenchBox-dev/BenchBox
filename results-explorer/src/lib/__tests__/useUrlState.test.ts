/**
 * Tests for useUrlState hook.
 *
 * Cases:
 *   (a) Initial value from URL beats the `initial` argument
 *   (b) Invalid/absent URL value falls back to `initial`
 *   (c) setValue writes ?key=... without pushing history (replaceState)
 *   (d) popstate re-hydrates state from the updated URL
 *   (e) SSR no-op: hook returns initial when window is undefined
 */

import { renderHook, act } from "@testing-library/preact";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { useUrlState, arraySerde, numberSerde } from "@/lib/useUrlState";

// ---------------------------------------------------------------------------
// URL helpers
// ---------------------------------------------------------------------------

function setSearch(params: Record<string, string>) {
  const search = new URLSearchParams(params).toString();
  window.history.replaceState(null, "", `/?${search}`);
}

function clearSearch() {
  window.history.replaceState(null, "", "/");
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useUrlState", () => {
  beforeEach(() => {
    clearSearch();
  });

  afterEach(() => {
    clearSearch();
  });

  it("(a) initial value from URL beats the initial argument", () => {
    setSearch({ phase: "standard" });
    const { result } = renderHook(() => useUrlState("phase", "power"));
    expect(result.current[0]).toBe("standard");
  });

  it("(b) absent key falls back to initial", () => {
    const { result } = renderHook(() => useUrlState("phase", "power"));
    expect(result.current[0]).toBe("power");
  });

  it("(b) invalid number value falls back to initial", () => {
    setSearch({ sf: "notanumber" });
    const { result } = renderHook(() => useUrlState("sf", 0.1, numberSerde));
    expect(result.current[0]).toBe(0.1);
  });

  it("(c) setValue writes ?key=... to URL without pushing history", () => {
    const pushSpy = vi.spyOn(history, "pushState");
    const replaceSpy = vi.spyOn(history, "replaceState");

    const { result } = renderHook(() => useUrlState("phase", "power"));
    act(() => {
      result.current[1]("standard");
    });

    expect(result.current[0]).toBe("standard");
    expect(pushSpy).not.toHaveBeenCalled();
    expect(replaceSpy).toHaveBeenCalled();

    const url = replaceSpy.mock.calls.at(-1)?.[2] as string;
    expect(url).toContain("phase=standard");

    pushSpy.mockRestore();
    replaceSpy.mockRestore();
  });

  it("(d) popstate re-hydrates state from the updated URL", () => {
    const { result } = renderHook(() => useUrlState("phase", "power"));

    // Simulate navigation that changes the URL externally
    act(() => {
      window.history.replaceState(null, "", "/?phase=throughput");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });

    expect(result.current[0]).toBe("throughput");
  });

  it("arraySerde round-trips comma-separated values", () => {
    setSearch({ benchmarks: "tpch,clickbench" });
    const { result } = renderHook(() =>
      useUrlState<string[]>("benchmarks", [], arraySerde),
    );
    expect(result.current[0]).toEqual(["tpch", "clickbench"]);

    act(() => {
      result.current[1](["tpcds", "ssb", "nyctaxi"]);
    });
    expect(result.current[0]).toEqual(["tpcds", "ssb", "nyctaxi"]);
    expect(window.location.search).toContain("benchmarks=tpcds%2Cssb%2Cnyctaxi");
  });

  it("numberSerde parses valid numeric values from URL", () => {
    setSearch({ sf: "1" });
    const { result } = renderHook(() => useUrlState("sf", 0.1, numberSerde));
    expect(result.current[0]).toBe(1);
  });

  it("setValue strips the key when the encoded value equals the default", () => {
    setSearch({ phase: "standard" });
    const { result } = renderHook(() => useUrlState("phase", "all"));
    act(() => {
      result.current[1]("all");
    });
    expect(window.location.search).toBe("");
  });

  it("setValue strips the key when an arraySerde value is empty", () => {
    setSearch({ bm: "tpch,clickbench" });
    const { result } = renderHook(() =>
      useUrlState<string[]>("bm", [], arraySerde),
    );
    act(() => {
      result.current[1]([]);
    });
    expect(window.location.search).toBe("");
  });

  it("mount-strips a URL key whose value matches the initial default", () => {
    setSearch({ phase: "all", other: "keep" });
    renderHook(() => useUrlState("phase", "all"));
    expect(window.location.search).toBe("?other=keep");
  });

  it("mount-strips an empty arraySerde URL key", () => {
    setSearch({ bm: "", other: "keep" });
    renderHook(() => useUrlState<string[]>("bm", [], arraySerde));
    expect(window.location.search).toBe("?other=keep");
  });

  it("mount does not strip a URL key whose value differs from the default", () => {
    setSearch({ phase: "standard" });
    renderHook(() => useUrlState("phase", "all"));
    expect(window.location.search).toBe("?phase=standard");
  });
});
