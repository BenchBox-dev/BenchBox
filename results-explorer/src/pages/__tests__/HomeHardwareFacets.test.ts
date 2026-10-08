import { describe, expect, it } from "vitest";

import { ALL_FACET_KEYS, CORE_FACET_KEYS, HARDWARE_FACET_KEYS } from "@/lib/facetModel";

describe("the coverage gate, encoded", () => {
  it("keeps every hardware key available in the model", () => {
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
    for (const key of HARDWARE_FACET_KEYS) {
      expect(CORE_FACET_KEYS).not.toContain(key);
    }
  });
});
