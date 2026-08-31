/**
 * Grouping the cohort index tables.
 *
 * The load-bearing claim is that grouping is PRESENTATION ONLY: it rearranges
 * rows and never changes how a rank is computed or which rows are eligible.
 * Ranking semantics have their own contract and release gate, so a grouping
 * control that quietly reordered or re-filtered would become a second, hidden
 * ranking policy.
 */

import { describe, expect, it } from "vitest";

import {
  COHORT_GROUP_BY_LABELS,
  UNGROUPED_LABEL,
  cohortGroupTotal,
  groupCohortRows,
} from "@/lib/queryFilters";

interface Row {
  id: string;
  rank: number;
  engine: string | null;
  eligible: boolean;
}

// Already rank-sorted, as the page hands them over.
const rows: Row[] = [
  { id: "a", rank: 1, engine: "1.4.3", eligible: true },
  { id: "b", rank: 2, engine: "1.3.2", eligible: true },
  { id: "c", rank: 3, engine: "1.4.3", eligible: false },
  { id: "d", rank: 4, engine: null, eligible: true },
];

const byEngine = (r: Row) => r.engine;

describe("grouping is presentation only", () => {
  it("loses no rows", () => {
    const groups = groupCohortRows(rows, "engine_version", byEngine);
    expect(cohortGroupTotal(groups)).toBe(rows.length);
  });

  it("leaves ranking order unchanged across the full set", () => {
    // Flattening the groups must yield the same MULTISET, and within any
    // group the relative rank order must be preserved. That is what makes
    // "grouping does not change ranking" true in the rendered output.
    const groups = groupCohortRows(rows, "engine_version", byEngine);
    const flat = groups.flatMap((g) => g.rows);
    expect(flat.map((r) => r.id).sort()).toEqual(rows.map((r) => r.id).sort());
    for (const group of groups) {
      const ranks = group.rows.map((r) => r.rank);
      expect([...ranks].sort((x, y) => x - y)).toEqual(ranks);
    }
  });

  it("leaves eligibility untouched", () => {
    const groups = groupCohortRows(rows, "engine_version", byEngine);
    const flat = groups.flatMap((g) => g.rows);
    for (const row of rows) {
      expect(flat.find((r) => r.id === row.id)!.eligible).toBe(row.eligible);
    }
  });

  it("does not filter out ranking-ineligible rows", () => {
    // Grouping narrows nothing. An ineligible row is still part of the cohort
    // and still has to be visible in it.
    const groups = groupCohortRows(rows, "engine_version", byEngine);
    expect(groups.flatMap((g) => g.rows).some((r) => !r.eligible)).toBe(true);
  });
});

describe("group composition", () => {
  it("returns one group when grouping is off", () => {
    const groups = groupCohortRows(rows, "none", byEngine);
    expect(groups).toHaveLength(1);
    expect(groups[0]!.rows).toHaveLength(rows.length);
  });

  it("labels each group by its value and counts per group", () => {
    const groups = groupCohortRows(rows, "engine_version", byEngine);
    const byLabel = new Map(groups.map((g) => [g.label, g.rows.length]));
    expect(byLabel.get("1.3.2")).toBe(1);
    expect(byLabel.get("1.4.3")).toBe(2);
  });

  it("collects rows with no recorded value rather than dropping them", () => {
    // Dropping them would let grouping silently shrink the cohort, and the
    // per-group counts would stop summing to the total the page states.
    const groups = groupCohortRows(rows, "engine_version", byEngine);
    expect(groups.find((g) => g.label === UNGROUPED_LABEL)!.rows).toHaveLength(1);
  });

  it("sorts 'Not recorded' last", () => {
    const groups = groupCohortRows(rows, "engine_version", byEngine);
    expect(groups.at(-1)!.label).toBe(UNGROUPED_LABEL);
  });

  it("orders versions naturally, so 1.10 follows 1.9", () => {
    const versioned: Row[] = [
      { id: "x", rank: 1, engine: "1.10.0", eligible: true },
      { id: "y", rank: 2, engine: "1.9.0", eligible: true },
    ];
    const groups = groupCohortRows(versioned, "engine_version", byEngine);
    expect(groups.map((g) => g.label)).toEqual(["1.9.0", "1.10.0"]);
  });

  it("treats an empty string as not recorded", () => {
    const blank: Row[] = [{ id: "z", rank: 1, engine: "", eligible: true }];
    expect(groupCohortRows(blank, "engine_version", byEngine)[0]!.label).toBe(UNGROUPED_LABEL);
  });

  it("offers only the grouping modes the data can support", () => {
    // w0's coverage gate cleared engine version alone; architecture and CPU
    // are single-bucket and are not offered as grouping axes.
    expect(Object.keys(COHORT_GROUP_BY_LABELS).sort()).toEqual(["engine_version", "none"]);
  });
});
