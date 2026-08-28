import { beforeEach, describe, expect, it } from "vitest";
import {
  EXPLORER_PERFORMANCE_MARKS,
  EXPLORER_PERFORMANCE_MEASURES,
  clearExplorerPerformanceEntriesForTests,
  markExplorerPerformance,
  measureExplorerPerformance,
} from "@/lib/performanceMarks";

beforeEach(() => {
  clearExplorerPerformanceEntriesForTests();
});

describe("performanceMarks", () => {
  it("records first-only marks without duplicating entries", () => {
    const first = markExplorerPerformance(EXPLORER_PERFORMANCE_MARKS.DB_INIT_START, { once: true });
    const duplicate = markExplorerPerformance(EXPLORER_PERFORMANCE_MARKS.DB_INIT_START, { once: true });

    expect(first).not.toBeNull();
    expect(duplicate).toBeNull();
    expect(performance.getEntriesByName(EXPLORER_PERFORMANCE_MARKS.DB_INIT_START, "mark")).toHaveLength(1);
  });

  it("measures between existing marks once", () => {
    markExplorerPerformance(EXPLORER_PERFORMANCE_MARKS.DB_INIT_START);
    markExplorerPerformance(EXPLORER_PERFORMANCE_MARKS.DB_INIT_READY);

    const first = measureExplorerPerformance(
      EXPLORER_PERFORMANCE_MEASURES.DB_INIT,
      EXPLORER_PERFORMANCE_MARKS.DB_INIT_START,
      EXPLORER_PERFORMANCE_MARKS.DB_INIT_READY,
      { once: true },
    );
    const duplicate = measureExplorerPerformance(
      EXPLORER_PERFORMANCE_MEASURES.DB_INIT,
      EXPLORER_PERFORMANCE_MARKS.DB_INIT_START,
      EXPLORER_PERFORMANCE_MARKS.DB_INIT_READY,
      { once: true },
    );

    expect(first).not.toBeNull();
    expect(duplicate).toBeNull();
    expect(performance.getEntriesByName(EXPLORER_PERFORMANCE_MEASURES.DB_INIT, "measure")).toHaveLength(1);
  });

  it("skips measures when either boundary mark is absent", () => {
    const measure = measureExplorerPerformance(
      EXPLORER_PERFORMANCE_MEASURES.DB_INIT,
      EXPLORER_PERFORMANCE_MARKS.DB_INIT_START,
      EXPLORER_PERFORMANCE_MARKS.DB_INIT_READY,
    );

    expect(measure).toBeNull();
    expect(performance.getEntriesByName(EXPLORER_PERFORMANCE_MEASURES.DB_INIT, "measure")).toHaveLength(0);
  });
});
