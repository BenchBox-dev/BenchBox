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
    expect(recovery.unprocessed).toEqual([]);
  });

  it("does not start detail reads for IDs confirmed missing by the batch probe", async () => {
    const loadResult = vi.fn(async (id: string) => ({ id }));
    const recovery = await recoverCompareResults(["kept", "missing"], 4, {
      resolveId: async (id) => id,
      findExistingIds: async () => new Set(["kept"]),
      loadResult,
    });
    expect(recovery).not.toBeNull();
    if (recovery === null) throw new Error("recovery was unexpectedly cancelled");

    expect(loadResult).toHaveBeenCalledTimes(1);
    expect(loadResult).toHaveBeenCalledWith("kept");
    expect(recovery.recovered).toEqual([
      { requestedId: "kept", resolvedId: "kept", detail: { id: "kept" } },
    ]);
    expect(recovery.missing).toEqual([{ requestedId: "missing", resolvedId: "missing" }]);
  });

  it("starts detail reads for initial positive matches while omissions are confirmed", async () => {
    let finishConfirmation: ((ids: ReadonlySet<string>) => void) | undefined;
    const loadResult = vi.fn(async (id: string) => ({ id }));
    const recoveryPromise = recoverCompareResults(["kept", "missing"], 4, {
      resolveId: async (id) => id,
      findExistingIds: async (_ids, onInitialExistingIds) => {
        onInitialExistingIds?.(new Set(["kept"]));
        return new Promise<ReadonlySet<string>>((resolve) => {
          finishConfirmation = resolve;
        });
      },
      loadResult,
    });

    await vi.waitFor(() => expect(loadResult).toHaveBeenCalledWith("kept"));
    expect(loadResult).not.toHaveBeenCalledWith("missing");
    finishConfirmation?.(new Set(["kept"]));

    const recovery = await recoveryPromise;
    expect(recovery?.recovered.map((entry) => entry.requestedId)).toEqual(["kept"]);
    expect(recovery?.missing).toEqual([{ requestedId: "missing", resolvedId: "missing" }]);
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
    expect(recovery.unprocessed).toEqual([]);
  });

  it("bounds resolver work for a long crafted ID list", async () => {
    const rawIds = Array.from({ length: 50 }, (_, index) => `id-${index + 1}`);
    const resolveId = vi.fn(async (id: string) => id);
    const recovery = await recoverCompareResults(rawIds, 4, {
      resolveId,
      loadResult: async (id) => ({ id }),
    });
    expect(recovery).not.toBeNull();
    if (recovery === null) throw new Error("recovery was unexpectedly cancelled");

    expect(resolveId).toHaveBeenCalledTimes(8);
    expect(recovery.recovered.map((entry) => entry.requestedId)).toEqual(rawIds.slice(0, 4));
    expect(recovery.overflow).toEqual(rawIds.slice(4, 8));
    expect(recovery.unprocessed).toEqual(rawIds.slice(8));
  });

  it("does not resolve IDs when the comparison limit is zero", async () => {
    const resolveId = vi.fn(async (id: string) => id);
    const recovery = await recoverCompareResults(["a", "b"], 0, {
      resolveId,
      loadResult: async (id) => ({ id }),
    });

    expect(resolveId).not.toHaveBeenCalled();
    expect(recovery?.unprocessed).toEqual(["a", "b"]);
  });

  it("retains four canonical IDs when every requested result also has an alias", async () => {
    const resolveId = vi.fn(async (id: string) => id.replace(/^alias-/, ""));
    const recovery = await recoverCompareResults(
      ["a", "alias-a", "b", "alias-b", "c", "alias-c", "d", "alias-d", "e"],
      4,
      {
        resolveId,
        loadResult: async (id) => ({ id }),
      },
    );
    expect(recovery).not.toBeNull();
    if (recovery === null) throw new Error("recovery was unexpectedly cancelled");

    expect(resolveId).toHaveBeenCalledTimes(8);
    expect(recovery.aliases).toEqual(["alias-a", "alias-b", "alias-c", "alias-d"]);
    expect(recovery.recovered.map((entry) => entry.requestedId)).toEqual(["a", "b", "c", "d"]);
    expect(recovery.overflow).toEqual([]);
    expect(recovery.unprocessed).toEqual(["e"]);
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

  it("does not begin detail reads after cancellation during a failed membership probe", async () => {
    const loadResult = vi.fn(async (id: string) => ({ id }));
    let cancelled = false;
    await expect(
      recoverCompareResults(["a", "b"], 4, {
        resolveId: async (id) => id,
        findExistingIds: async () => {
          cancelled = true;
          throw new Error("membership unavailable");
        },
        loadResult,
        isCancelled: () => cancelled,
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
