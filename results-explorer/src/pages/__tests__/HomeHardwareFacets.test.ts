/**
 * The hardware/engine facet chips on the index pages.
 *
 * w0's coverage gate cleared exactly one: engine version (7 populated
 * buckets). `arch` and `cpu_family` each have a single populated bucket and
 * ship as columns instead — a single-bucket chip implies a choice the data
 * cannot offer.
 */

import { describe, expect, it } from "vitest";

import { ALL_FACET_KEYS, CORE_FACET_KEYS, HARDWARE_FACET_KEYS } from "@/lib/facetModel";

describe("the coverage gate, encoded", () => {
  it("keeps every hardware key available in the model", () => {
    // The gate governs which chips RENDER, not which facets exist. URL state,
    // aliases and the SQL clause builder must keep working for all of them, so
    // a link someone already holds does not stop resolving.
    expect(HARDWARE_FACET_KEYS).toContain("platform_version");
    expect(HARDWARE_FACET_KEYS).toContain("arch");
    expect(HARDWARE_FACET_KEYS).toContain("cpu_family");
  });

  it("composes core and hardware keys without dropping any", () => {
    for (const key of [...CORE_FACET_KEYS, ...HARDWARE_FACET_KEYS]) {
      expect(ALL_FACET_KEYS).toContain(key);
    }
    expect(ALL_FACET_KEYS.length).toBe(CORE_FACET_KEYS.length + HARDWARE_FACET_KEYS.length);
  });

  it("does not silently promote a hardware key into the core set", () => {
    // CORE_FACET_KEYS is what pages iterate by default. A hardware key
    // appearing there would ship a chip without passing the coverage gate.
    for (const key of HARDWARE_FACET_KEYS) {
      expect(CORE_FACET_KEYS).not.toContain(key);
    }
  });
});
