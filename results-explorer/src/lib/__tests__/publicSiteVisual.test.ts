import { describe, expect, it } from "vitest";

import {
  compareVisualManifests,
  hasExactHeadVisualApproval,
  PUBLIC_SITE_CAPTURE_PROFILE,
  type VisualManifest,
} from "../publicSiteVisual";

const captures: VisualManifest["captures"] = [
  { route: "/", viewport_width: 390, digest: "landing-old" },
  { route: "/docs/", viewport_width: 390, digest: "docs" },
];

describe("public site visual manifest comparison", () => {
  it("ignores only landing digests during the one-time legacy-profile migration", () => {
    const baseline: VisualManifest = { captures };
    const current: VisualManifest = {
      capture_profile: PUBLIC_SITE_CAPTURE_PROFILE,
      captures: [
        { ...captures[0]!, digest: "landing-settled" },
        { ...captures[1]!, digest: "docs-changed" },
      ],
    };

    expect(compareVisualManifests(baseline, current).changed).toEqual(["/docs/@390"]);
  });

  it("compares every digest once both manifests use the settled profile", () => {
    const baseline: VisualManifest = { capture_profile: PUBLIC_SITE_CAPTURE_PROFILE, captures };
    const current: VisualManifest = {
      capture_profile: PUBLIC_SITE_CAPTURE_PROFILE,
      captures: captures.map((capture) => ({ ...capture, digest: `${capture.digest}-changed` })),
    };

    expect(compareVisualManifests(baseline, current).changed).toEqual(["/@390", "/docs/@390"]);
  });

  it("does not suppress landing drift unless the current manifest opts into the new profile", () => {
    const baseline: VisualManifest = { captures };
    const current: VisualManifest = {
      captures: captures.map((capture) => ({ ...capture, digest: `${capture.digest}-changed` })),
    };

    expect(compareVisualManifests(baseline, current).changed).toEqual(["/@390", "/docs/@390"]);
  });

  it("never hides route or viewport matrix drift", () => {
    const baseline: VisualManifest = { captures };
    const current: VisualManifest = {
      capture_profile: PUBLIC_SITE_CAPTURE_PROFILE,
      captures: [{ route: "/", viewport_width: 768, digest: "landing" }],
    };

    expect(compareVisualManifests(baseline, current)).toMatchObject({
      missing: ["/@390", "/docs/@390"],
      unexpected: ["/@768"],
    });
  });

  it("allows reviewed changed and unexpected captures only for the exact PR head", () => {
    const baseline: VisualManifest = { capture_profile: PUBLIC_SITE_CAPTURE_PROFILE, captures };
    const current: VisualManifest = {
      capture_profile: PUBLIC_SITE_CAPTURE_PROFILE,
      captures: [
        { ...captures[0]!, digest: "landing-reviewed" },
        captures[1]!,
        { route: "/results/benchmarks/", viewport_width: 390, digest: "new-route" },
      ],
    };

    expect(
      compareVisualManifests(baseline, current, {
        approvedHeadSha: "abc123",
        currentHeadSha: "abc123",
        reason: "Reviewed the section indexes at all captured widths",
      }),
    ).toEqual({
      missing: [],
      unexpected: [],
      changed: [],
      approvedUnexpected: ["/results/benchmarks/@390"],
      approvedChanged: ["/@390"],
      approvalApplied: true,
    });
  });

  it.each([
    { approvedHeadSha: "stale", currentHeadSha: "current", reason: "reviewed" },
    { approvedHeadSha: "current", currentHeadSha: "current", reason: "   " },
    { approvedHeadSha: "", currentHeadSha: "current", reason: "reviewed" },
  ])("rejects stale or incomplete approval: %o", (approval) => {
    expect(hasExactHeadVisualApproval(approval)).toBe(false);
  });

  it("never allows an exact-head approval to hide missing captures", () => {
    const current: VisualManifest = {
      capture_profile: PUBLIC_SITE_CAPTURE_PROFILE,
      captures: [captures[0]!],
    };

    expect(
      compareVisualManifests(
        { capture_profile: PUBLIC_SITE_CAPTURE_PROFILE, captures },
        current,
        { approvedHeadSha: "abc123", currentHeadSha: "abc123", reason: "reviewed" },
      ),
    ).toMatchObject({
      missing: ["/docs/@390"],
      unexpected: [],
      changed: [],
      approvalApplied: true,
    });
  });
});
