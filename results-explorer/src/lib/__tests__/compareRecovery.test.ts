import { describe, expect, it, vi } from "vitest";
import {
  planCompareIds,
  recoverCompareResults,
  shouldPreserveMultiSelectionUrl,
} from "@/lib/compareRecovery";

describe("planCompareIds", () => {
  it("trims, deduplicates, caps, and ignores empty IDs", () => {
    expect(planCompareIds([" a ", "", "a", "b", "c"], 2)).toEqual({
      retained: ["a", "b"],
      duplicates: ["a"],
      overflow: ["c"],
    });
  });

  it("returns an empty plan for an empty selection", () => {
    expect(planCompareIds([], 4)).toEqual({ retained: [], duplicates: [], overflow: [] });
  });
});

describe("recoverCompareResults", () => {
  it("retains loaded results and reports confirmed absence separately", async () => {
    const recovery = await recoverCompareResults(["kept", "missing"], 4, {
      resolveId: async (id) => id,
      loadResult: async (id) => (id === "missing" ? null : { id }),
    });
    expect(recovery).not.toBeNull();
    if (recovery === null) throw new Error("recovery was unexpectedly cancelled");

    expect(recovery.recovered).toEqual([
      { requestedId: "kept", resolvedId: "kept", detail: { id: "kept" } },
    ]);
    expect(recovery.missing).toEqual([{ requestedId: "missing", resolvedId: "missing" }]);
    expect(recovery.failed).toEqual([]);
  });

  it("deduplicates resolved aliases before applying the selection limit", async () => {
    const loadResult = vi.fn(async (id: string) => ({ id }));
    const recovery = await recoverCompareResults(["a", "alias-a", "b", "c"], 2, {
      resolveId: async (id) => (id === "alias-a" ? "a" : id),
      loadResult,
    });
    expect(recovery).not.toBeNull();
    if (recovery === null) throw new Error("recovery was unexpectedly cancelled");

    expect(recovery.aliases).toEqual(["alias-a"]);
    expect(recovery.overflow).toEqual(["c"]);
    expect(recovery.recovered.map((entry) => entry.requestedId)).toEqual(["a", "b"]);
    expect(loadResult).toHaveBeenCalledTimes(2);
  });

  it("keeps transient resolution and load failures distinct from missing results", async () => {
    const resolutionFailure = new Error("resolver unavailable");
    const loadFailure = new Error("detail unavailable");
    const recovery = await recoverCompareResults(["missing", "resolve-failed", "load-failed"], 4, {
      resolveId: async (id) => {
        if (id === "resolve-failed") throw resolutionFailure;
        return id;
      },
      loadResult: async (id) => {
        if (id === "load-failed") throw loadFailure;
        return null;
      },
    });
    expect(recovery).not.toBeNull();
    if (recovery === null) throw new Error("recovery was unexpectedly cancelled");

    expect(recovery.missing).toEqual([{ requestedId: "missing", resolvedId: "missing" }]);
    expect(recovery.failed).toEqual([
      { requestedId: "resolve-failed", error: resolutionFailure },
      { requestedId: "load-failed", error: loadFailure },
    ]);
  });

  it("does not begin detail reads after the caller cancels during ID resolution", async () => {
    const loadResult = vi.fn(async (id: string) => ({ id }));
    await expect(
      recoverCompareResults(["a", "b"], 4, {
        resolveId: async (id) => id,
        loadResult,
        isCancelled: () => true,
      }),
    ).resolves.toBeNull();
    expect(loadResult).not.toHaveBeenCalled();
  });
});

describe("shouldPreserveMultiSelectionUrl", () => {
  it("keeps a multi-selection URL multi after only one result recovers", () => {
    expect(shouldPreserveMultiSelectionUrl(["kept", "stale"], 1, 4)).toBe(true);
    expect(shouldPreserveMultiSelectionUrl(["kept"], 1, 4)).toBe(false);
    expect(shouldPreserveMultiSelectionUrl(["kept", "kept"], 1, 4)).toBe(false);
  });
});
