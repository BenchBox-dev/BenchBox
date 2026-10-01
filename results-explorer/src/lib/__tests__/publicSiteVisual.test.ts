import { describe, expect, it } from "vitest";

import {
  compareVisualManifests,
  hasChangeDigestVisualApproval,
  hasExactHeadVisualApproval,
  PUBLIC_SITE_CAPTURE_PROFILE,
  VISUAL_CHANGE_DIGEST_VERSION,
  visualChangeDigest,
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
    ).toMatchObject({
      missing: [],
      unexpected: [],
      changed: [],
      approvedUnexpected: ["/results/benchmarks/@390"],
      approvedChanged: ["/@390"],
      approvalApplied: true,
      approvalBasis: "head",
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

describe("content-bound visual change approval", () => {
  const profile = PUBLIC_SITE_CAPTURE_PROFILE;
  const baseline: VisualManifest = { capture_profile: profile, captures };
  const reviewed: VisualManifest = {
    capture_profile: profile,
    captures: [
      { ...captures[0]!, digest: "landing-reviewed" },
      captures[1]!,
      { route: "/results/benchmarks/", viewport_width: 390, digest: "new-route" },
    ],
  };
  const reason = "Reviewed the section indexes at all captured widths";

  // What the PR run prints, which a maintainer records after reviewing the diagnostics.
  const digest = compareVisualManifests(baseline, reviewed).changeDigest;

  it("prints a stable digest only when something changed or appeared", () => {
    expect(digest).toMatch(/^[0-9a-f]{64}$/);
    expect(compareVisualManifests(baseline, baseline).changeDigest).toBe("");
    // Capture order does not matter: the same change gives the same digest.
    const shuffled: VisualManifest = { ...reviewed, captures: [...reviewed.captures].reverse() };
    expect(compareVisualManifests(baseline, shuffled).changeDigest).toBe(digest);
  });

  it("accepts the reviewed change in a merge group that has a different head SHA", () => {
    // The PR run approved nothing by SHA; the group recomputes the same digest from its own tree.
    const result = compareVisualManifests(baseline, reviewed, {
      approvedChangeDigests: digest,
      changeReason: reason,
      approvedHeadSha: "",
      currentHeadSha: "synthetic-merge-group-head",
    });
    expect(result).toMatchObject({
      changed: [],
      unexpected: [],
      approvedChanged: ["/@390"],
      approvedUnexpected: ["/results/benchmarks/@390"],
      approvalApplied: true,
      approvalBasis: "change-digest",
    });
  });

  it("accepts a digest listed among several, separated by spaces or commas", () => {
    expect(hasChangeDigestVisualApproval({ approvedChangeDigests: `a1 ${digest},b2`, changeReason: reason }, digest)).toBe(
      true,
    );
  });

  it.each([
    ["a missing reason", { approvedChangeDigests: digest, changeReason: "" }],
    ["a blank reason", { approvedChangeDigests: digest, changeReason: "   " }],
    ["no digests recorded", { approvedChangeDigests: "", changeReason: reason }],
    ["a different digest", { approvedChangeDigests: "0".repeat(64), changeReason: reason }],
    ["only a prefix of the digest", { approvedChangeDigests: digest.slice(0, 32), changeReason: reason }],
  ])("does not approve with %s", (_label, approval) => {
    const result = compareVisualManifests(baseline, reviewed, approval);
    expect(result.approvalApplied).toBe(false);
    expect(result.changed).toEqual(["/@390"]);
    expect(result.unexpected).toEqual(["/results/benchmarks/@390"]);
  });

  it("does not approve nothing: an empty change has no digest to match", () => {
    expect(hasChangeDigestVisualApproval({ approvedChangeDigests: "", changeReason: reason }, "")).toBe(false);
    expect(hasChangeDigestVisualApproval({ approvedChangeDigests: " , ", changeReason: reason }, "")).toBe(false);
  });

  it("stops matching when the group renders the reviewed capture differently", () => {
    const drifted: VisualManifest = {
      ...reviewed,
      captures: reviewed.captures.map((capture) =>
        capture.route === "/" ? { ...capture, digest: "landing-drifted" } : capture,
      ),
    };
    const result = compareVisualManifests(baseline, drifted, { approvedChangeDigests: digest, changeReason: reason });
    expect(result.approvalApplied).toBe(false);
    expect(result.changed).toEqual(["/@390"]);
  });

  it("stops matching when the baseline already renders a different version of the capture", () => {
    // The base moved: it now renders "/" as something else, so the reviewed old-to-new change differs.
    const movedBase: VisualManifest = {
      capture_profile: profile,
      captures: [{ ...captures[0]!, digest: "landing-moved" }, captures[1]!],
    };
    const result = compareVisualManifests(movedBase, reviewed, { approvedChangeDigests: digest, changeReason: reason });
    expect(result.approvalApplied).toBe(false);
  });

  it("stops matching when the group adds a change that was never reviewed", () => {
    const extra: VisualManifest = {
      ...reviewed,
      captures: reviewed.captures.map((capture) =>
        capture.route === "/docs/" ? { ...capture, digest: "docs-unreviewed" } : capture,
      ),
    };
    const result = compareVisualManifests(baseline, extra, { approvedChangeDigests: digest, changeReason: reason });
    expect(result.approvalApplied).toBe(false);
    expect(result.changed).toEqual(["/@390", "/docs/@390"]);
  });

  it("never lets a digest approval hide a missing capture", () => {
    const missing: VisualManifest = { capture_profile: profile, captures: [{ ...captures[0]!, digest: "landing-reviewed" }] };
    const missingDigest = compareVisualManifests(baseline, missing).changeDigest;
    expect(
      compareVisualManifests(baseline, missing, { approvedChangeDigests: missingDigest, changeReason: reason }),
    ).toMatchObject({ missing: ["/docs/@390"], approvalApplied: true });
  });

  it("does not depend on the order captures are listed, with several of each kind", () => {
    const many: VisualManifest = { capture_profile: profile, captures: [captures[0]!, captures[1]!] };
    const changedTwo: VisualManifest = {
      capture_profile: profile,
      captures: [
        { ...captures[0]!, digest: "landing-a" },
        { ...captures[1]!, digest: "docs-a" },
        { route: "/results/one/", viewport_width: 390, digest: "new-one" },
        { route: "/results/two/", viewport_width: 390, digest: "new-two" },
      ],
    };
    const reversed: VisualManifest = { ...changedTwo, captures: [...changedTwo.captures].reverse() };
    const forward = compareVisualManifests(many, changedTwo);
    expect(forward.changed).toHaveLength(2);
    expect(forward.unexpected).toHaveLength(2);
    expect(compareVisualManifests(many, reversed).changeDigest).toBe(forward.changeDigest);
  });

  it("binds the direction and the capture of each change", () => {
    const base = visualChangeDigest([{ key: "/x@390", from: "a", to: "b" }], []);
    // Swapping old and new is a different change, as is the same change on another capture.
    expect(visualChangeDigest([{ key: "/x@390", from: "b", to: "a" }], [])).not.toBe(base);
    expect(visualChangeDigest([{ key: "/x@768", from: "a", to: "b" }], [])).not.toBe(base);
    expect(visualChangeDigest([{ key: "/x@390", from: "a", to: "b" }], [{ key: "/y@390", to: "c" }])).not.toBe(base);
    expect(visualChangeDigest([], [])).toBe("");
    expect(VISUAL_CHANGE_DIGEST_VERSION).toMatch(/^public-site-visual-change-v\d+$/);
  });
});
