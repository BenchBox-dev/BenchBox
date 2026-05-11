import { describe, expect, it } from "vitest";
import { preserveUniqueAfterTruncation } from "@/components/RankTable";

describe("preserveUniqueAfterTruncation", () => {
  it("truncates identities that exceed the cap", () => {
    expect(preserveUniqueAfterTruncation(["DuckDB"], 16)).toEqual(["DuckDB"]);
    expect(preserveUniqueAfterTruncation(["A very long platform name here"], 16)).toEqual([
      "A very lon… here",
    ]);
  });

  it("middle-truncates duplicate-prone identities while preserving the suffix", () => {
    // Adversarial cohort: two same-platform runs disambiguated by the
    // version suffix that lives past the 16-char cap. The cohort-aware
    // formatter produced unique strings, but a naive slice would
    // collide them. The helper falls back to the full identity for
    // both rows so the visual contract is preserved.
    const result = preserveUniqueAfterTruncation(["DataFusion v1.40.0", "DataFusion v1.40.1"], 16);
    expect(new Set(result).size).toBe(2);
    expect(result[0]).toBe("DataFus… v1.40.0");
    expect(result[1]).toBe("DataFus… v1.40.1");
  });

  it("keeps every truncated label within the cap", () => {
    const input = ["DataFusion v1.40.0", "DataFusion v1.40.1", "A very long platform name"];
    const result = preserveUniqueAfterTruncation(input, 16);
    expect(new Set(result).size).toBe(3);
    expect(result.every((label) => label.length <= 16)).toBe(true);
  });
});
