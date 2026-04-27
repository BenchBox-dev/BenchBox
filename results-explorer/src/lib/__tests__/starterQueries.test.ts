import { describe, expect, it } from "vitest";
import {
  STARTER_QUERIES,
  STARTER_QUERY_CATEGORIES,
  starterQueriesByCategory,
  type StarterQueryCategory,
} from "@/lib/starterQueries";

describe("starterQueries", () => {
  it("covers every required analyst category", () => {
    const required: StarterQueryCategory[] = [
      "results",
      "per_query_timings",
      "cohort_comparisons",
      "trust_and_tuning",
      "detail_drilldown",
    ];
    const grouped = starterQueriesByCategory();
    for (const category of required) {
      expect(grouped[category].length, `category ${category}`).toBeGreaterThan(0);
    }
  });

  it("has unique ids across the registry", () => {
    const ids = STARTER_QUERIES.map((q) => q.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("only references the canonical bench schema", () => {
    for (const query of STARTER_QUERIES) {
      const tableReferences = query.sql.match(/\bFROM\s+([\w.]+)/gi) ?? [];
      const joinReferences = query.sql.match(/\bJOIN\s+([\w.]+)/gi) ?? [];
      const all = [...tableReferences, ...joinReferences];
      for (const ref of all) {
        const target = ref.split(/\s+/)[1]!;
        if (target.toLowerCase() === "latest") continue;
        expect(target, `query ${query.id}`).toMatch(/^bench\./);
      }
    }
  });

  it("contains no DDL/DML keywords so read-only attach stays honoured", () => {
    const forbidden = /\b(CREATE|INSERT|UPDATE|DELETE|DROP|ALTER|ATTACH|COPY\s+TO|INSTALL|LOAD)\b/i;
    for (const query of STARTER_QUERIES) {
      expect(query.sql, `query ${query.id}`).not.toMatch(forbidden);
    }
  });

  it("labels every category exposed by the registry", () => {
    for (const category of Object.keys(STARTER_QUERY_CATEGORIES) as StarterQueryCategory[]) {
      expect(STARTER_QUERY_CATEGORIES[category]).toBeTruthy();
    }
  });
});
