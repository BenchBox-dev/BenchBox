import { describe, expect, it } from "vitest";

import {
  compareVisualManifests,
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
});
