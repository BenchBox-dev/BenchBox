import { describe, expect, it } from "vitest";

import {
  compareVisualManifests,
  compareVisualManifestsAcrossRenderers,
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

describe("renderer-aware visual comparison", () => {
  const sphinx: VisualManifest = { capture_profile: PUBLIC_SITE_CAPTURE_PROFILE, renderer: "sphinx", captures };
  const astroSame: VisualManifest = { ...sphinx, renderer: "astro" };
  const exact = { approvedHeadSha: "abc123", currentHeadSha: "abc123", reason: "reviewed" };

  it("keeps the ordinary comparison when the renderer is unchanged", () => {
    const unchanged = compareVisualManifestsAcrossRenderers(sphinx, sphinx);
    expect(unchanged).toMatchObject({ rendererChanged: false, changed: [], approvalApplied: false });

    const drifted: VisualManifest = { ...sphinx, captures: [captures[0]!, { ...captures[1]!, digest: "docs-new" }] };
    expect(compareVisualManifestsAcrossRenderers(sphinx, drifted).changed).toEqual(["/docs/@390"]);
  });

  it("treats a missing renderer as sphinx", () => {
    const legacy: VisualManifest = { capture_profile: PUBLIC_SITE_CAPTURE_PROFILE, captures };
    expect(compareVisualManifestsAcrossRenderers(legacy, sphinx).rendererChanged).toBe(false);
  });

  it("fails a renderer change without approval and names both renderers", () => {
    const result = compareVisualManifestsAcrossRenderers(sphinx, astroSame);
    expect(result.rendererChanged).toBe(true);
    expect(result.changed).toEqual(["/@390", "/docs/@390"]);
    expect(result.message).toContain("sphinx");
    expect(result.message).toContain("astro");
  });

  it("fails a renderer change approved for a different head", () => {
    const result = compareVisualManifestsAcrossRenderers(sphinx, astroSame, { ...exact, approvedHeadSha: "def456" });
    expect(result.approvalApplied).toBe(false);
    expect(result.changed).toEqual(["/@390", "/docs/@390"]);
  });

  it("passes a renderer change with exact-head approval and reports every capture as changed", () => {
    const result = compareVisualManifestsAcrossRenderers(sphinx, astroSame, exact);
    expect(result).toMatchObject({
      rendererChanged: true,
      approvalApplied: true,
      changed: [],
      missing: [],
      unexpected: [],
      approvedChanged: ["/@390", "/docs/@390"],
    });
  });

  it("fails an unexpected capture under a renderer change without approval", () => {
    const extra: VisualManifest = {
      ...astroSame,
      captures: [...captures, { route: "/results/", viewport_width: 390, digest: "results" }],
    };
    const result = compareVisualManifestsAcrossRenderers(sphinx, extra);
    expect(result.rendererChanged).toBe(true);
    expect(result.unexpected).toEqual(["/results/@390"]);
    expect(result.approvedUnexpected).toEqual([]);
  });

  it("moves an unexpected capture to approvedUnexpected under exact-head approval", () => {
    const extra: VisualManifest = {
      ...astroSame,
      captures: [...captures, { route: "/results/", viewport_width: 390, digest: "results" }],
    };
    const result = compareVisualManifestsAcrossRenderers(sphinx, extra, exact);
    expect(result).toMatchObject({
      rendererChanged: true,
      approvalApplied: true,
      unexpected: [],
      approvedUnexpected: ["/results/@390"],
      missing: [],
      changed: [],
    });
  });

  it("never lets a renderer approval hide a missing capture", () => {
    const partial: VisualManifest = { ...astroSame, captures: [captures[0]!] };
    expect(compareVisualManifestsAcrossRenderers(sphinx, partial, exact).missing).toEqual(["/docs/@390"]);
  });
});

describe("site-deploy approval bound to release, candidate and baseline", () => {
  const release = "1".repeat(40);
  const candidate = "c".repeat(64);
  const baseline = "b".repeat(64);
  const binding = (releaseSha: string, candidateSha: string, baselineSha: string) =>
    `${releaseSha}+${candidateSha}+${baselineSha}`;
  const sphinx: VisualManifest = { capture_profile: PUBLIC_SITE_CAPTURE_PROFILE, renderer: "sphinx", captures };
  const moved: VisualManifest = {
    ...sphinx,
    captures: captures.map((capture) => ({ ...capture, digest: `${capture.digest}-next-release` })),
  };
  const approve = (approved: string) =>
    compareVisualManifestsAcrossRenderers(sphinx, moved, {
      approvedHeadSha: approved,
      currentHeadSha: binding(release, candidate, baseline),
      reason: "release pages reviewed",
    });

  it("fails an approval recorded for another release", () => {
    const result = approve(binding("2".repeat(40), candidate, baseline));
    expect(result.approvalApplied).toBe(false);
    expect(result.changed).toEqual(["/@390", "/docs/@390"]);
  });

  it("fails an approval recorded for another candidate artifact", () => {
    expect(approve(binding(release, "d".repeat(64), baseline)).approvalApplied).toBe(false);
  });

  it("fails an approval recorded against another baseline", () => {
    expect(approve(binding(release, candidate, "e".repeat(64))).approvalApplied).toBe(false);
  });

  it("passes only the exact binding", () => {
    const result = approve(binding(release, candidate, baseline));
    expect(result).toMatchObject({ approvalApplied: true, changed: [], missing: [] });
  });
});
