import { describe, expect, it } from "vitest";
import {
  ensureSentence,
  formatCandidateCount,
  formatCount,
  formatSelectedCount,
  formatWarningCount,
  removeDuplicatedTerminalPunctuation,
} from "@/lib/copyFormatters";

describe("copyFormatters", () => {
  it("pluralizes common count labels", () => {
    expect(formatWarningCount(1)).toBe("1 warning");
    expect(formatWarningCount(2)).toBe("2 warnings");
    expect(formatCandidateCount(1)).toBe("1 candidate");
    expect(formatCandidateCount(3)).toBe("3 candidates");
    expect(formatCount(1, "run")).toBe("1 run");
    expect(formatCount(4, "run")).toBe("4 runs");
    expect(formatCount(2, "query", "queries")).toBe("2 queries");
    expect(formatCount(2, "more", "more")).toBe("2 more");
  });

  it("formats selected states without duplicating count rules", () => {
    expect(formatSelectedCount(1)).toBe("1 result selected");
    expect(formatSelectedCount(2)).toBe("2 results selected");
    expect(formatSelectedCount(3, "run")).toBe("3 runs selected");
  });

  it("normalizes sentence punctuation", () => {
    expect(ensureSentence("Review receipt")).toBe("Review receipt.");
    expect(ensureSentence("Review receipt.")).toBe("Review receipt.");
    expect(removeDuplicatedTerminalPunctuation("coverage.. Review receipt!!")).toBe(
      "coverage. Review receipt!",
    );
  });
});
