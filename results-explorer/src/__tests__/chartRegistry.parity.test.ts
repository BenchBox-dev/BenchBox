import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { ALL_CHART_IDS } from "@/lib/chartRegistry";

function loadCanonicalChartIds(): string[] {
  const fixturePath = resolve(import.meta.dirname, "../../../tests/parity/fixtures/chart_ids.json");
  const fixture = JSON.parse(readFileSync(fixturePath, "utf8")) as { chart_ids: string[] };
  return fixture.chart_ids;
}

describe("chartRegistry CLI parity", () => {
  it("matches chart_types.py _CHART_SPECS exactly (bidirectional)", () => {
    const canonicalIds = loadCanonicalChartIds();
    const canonicalSet = new Set(canonicalIds);
    const registrySet = new Set(ALL_CHART_IDS);

    const missingFromRegistry = canonicalIds.filter((id) => !registrySet.has(id));
    const extrasInRegistry = ALL_CHART_IDS.filter((id) => !canonicalSet.has(id));

    expect(missingFromRegistry).toStrictEqual([]);
    expect(extrasInRegistry).toStrictEqual([]);
  });
});
