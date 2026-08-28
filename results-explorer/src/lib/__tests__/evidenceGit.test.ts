import { describe, expect, it } from "vitest";
import { assertEvidenceCaptureMatchesDevelop } from "@/lib/evidenceGit";

describe("assertEvidenceCaptureMatchesDevelop", () => {
  it("allows capture metadata when HEAD matches the recorded develop SHA", () => {
    expect(() =>
      assertEvidenceCaptureMatchesDevelop({
        developSha: "92bc2554cc8c4ac4bbaed644a073e7c9fc3e59e0",
        headSha: "92bc2554cc8c4ac4bbaed644a073e7c9fc3e59e0",
      }),
    ).not.toThrow();
  });

  it("rejects capture metadata when HEAD differs from the recorded develop SHA", () => {
    expect(() =>
      assertEvidenceCaptureMatchesDevelop({
        developSha: "92bc2554cc8c4ac4bbaed644a073e7c9fc3e59e0",
        headSha: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      }),
    ).toThrow(/HEAD is aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa, but origin\/develop is 92bc2554/);
  });
});
