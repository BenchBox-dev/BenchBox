import { describe, expect, it } from "vitest";

import {
  compareVisualManifests,
  hasChangeDigestVisualApproval,
  hasExactHeadVisualApproval,
  PUBLIC_SITE_CAPTURE_PROFILE,
  pullRequestNumbers,
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
  const prRef = "2385";
  // A merge group can hold several PRs; its members come from the commits the group adds.
  const groupMembers = "2384 2385 2386";

  // What the PR run prints, which a maintainer records after reviewing the diagnostics.
  const digest = compareVisualManifests(baseline, reviewed).changeDigest;
  const entry = `${prRef}:${digest}`;
  const approve = (overrides: Record<string, string> = {}) => ({
    approvedChangeDigests: entry,
    changeReason: reason,
    pullRequests: prRef,
    ...overrides,
  });

  it("prints a stable digest only when something changed or appeared", () => {
    expect(digest).toMatch(/^[0-9a-f]{64}$/);
    expect(compareVisualManifests(baseline, baseline).changeDigest).toBe("");
  });

  it("accepts the reviewed change in a merge group that has a different head SHA", () => {
    // Approved on the PR run, then recomputed from the group's own captures. The group holds other
    // PRs too, none of which change what renders, so the whole group's change is the reviewed one.
    const result = compareVisualManifests(baseline, reviewed, approve({ pullRequests: groupMembers }));
    expect(result).toMatchObject({
      changed: [],
      unexpected: [],
      approvedChanged: ["/@390"],
      approvedUnexpected: ["/results/benchmarks/@390"],
      approvalApplied: true,
      approvalBasis: "change-digest",
    });
  });

  it("accepts the reviewed change whichever position its PR has in the group", () => {
    // The queue branch is named for the last entry only, so the reviewed PR can be any member.
    for (const members of ["2385", "2385 2390", "2380 2385", "2380 2385 2390"]) {
      expect(compareVisualManifests(baseline, reviewed, approve({ pullRequests: members })).approvalApplied).toBe(true);
    }
  });

  it("does not approve the same pixels for a different pull request", () => {
    // The replay scenario: the change is approved, merged and reverted, and another PR reapplies it.
    for (const members of ["2386", "2386 2387", "2386,2387"]) {
      const result = compareVisualManifests(baseline, reviewed, approve({ pullRequests: members }));
      expect(result.approvalApplied).toBe(false);
      expect(result.changed).toEqual(["/@390"]);
    }
  });

  it("fails closed when a group's change is the union of several reviewed PRs", () => {
    // Two members each change a different capture. Each has an entry for its own change, but the group's
    // digest covers both, so it matches neither entry and the group is rejected, not half approved.
    const second: VisualManifest = {
      ...reviewed,
      captures: reviewed.captures.map((capture) =>
        capture.route === "/docs/" ? { ...capture, digest: "docs-reviewed" } : capture,
      ),
    };
    const firstOnly = compareVisualManifests(baseline, reviewed).changeDigest;
    const secondOnly = compareVisualManifests(baseline, { ...baseline, captures: second.captures.map((capture) =>
      capture.route === "/" ? { ...captures[0]! } : capture,
    ) }).changeDigest;
    expect(secondOnly).not.toBe("");
    const result = compareVisualManifests(
      baseline,
      second,
      approve({ pullRequests: "2385 2386", approvedChangeDigests: `2385:${firstOnly} 2386:${secondOnly}` }),
    );
    expect(result.approvalApplied).toBe(false);
    expect(result.changed.length).toBeGreaterThan(1);
  });

  it.each([
    ["no pull requests", { pullRequests: "" }],
    ["a list with an item that is not a number", { pullRequests: "2385 pr-2386" }],
    ["a list that names the reviewed PR only as a branch", { pullRequests: "refs/heads/feature/pr-2385" }],
    ["the reviewed PR written with a sign", { pullRequests: "+2385" }],
    ["a bare digest with no pull request", { approvedChangeDigests: digest }],
    ["an entry with an empty pull request number and no pull requests", { approvedChangeDigests: `:${digest}`, pullRequests: "" }],
    ["pull request zero", { approvedChangeDigests: `0:${digest}`, pullRequests: "0" }],
    ["another pull request's entry", { approvedChangeDigests: `2386:${digest}` }],
    ["a missing reason", { changeReason: "" }],
    ["a blank reason", { changeReason: "   " }],
    ["no entries recorded", { approvedChangeDigests: "" }],
    ["a different digest", { approvedChangeDigests: `${prRef}:${"0".repeat(64)}` }],
    ["only a prefix of the digest", { approvedChangeDigests: `${prRef}:${digest.slice(0, 32)}` }],
    ["an entry for a pull request whose number is a prefix", { approvedChangeDigests: `238:${digest}` }],
  ])("does not approve with %s", (_label, overrides) => {
    const result = compareVisualManifests(baseline, reviewed, approve(overrides));
    expect(result.approvalApplied).toBe(false);
    expect(result.changed).toEqual(["/@390"]);
    expect(result.unexpected).toEqual(["/results/benchmarks/@390"]);
  });

  it("accepts an entry listed among several, separated by spaces or commas", () => {
    const listed = `7:${"1".repeat(64)} ${entry},9:${"2".repeat(64)}`;
    expect(hasChangeDigestVisualApproval(approve({ approvedChangeDigests: listed }), digest)).toBe(true);
  });

  it("does not approve nothing: an empty change has no digest to match", () => {
    expect(hasChangeDigestVisualApproval(approve({ approvedChangeDigests: `${prRef}:` }), "")).toBe(false);
    expect(hasChangeDigestVisualApproval(approve({ approvedChangeDigests: " , " }), "")).toBe(false);
  });

  it("stops matching when the group renders the reviewed capture differently", () => {
    const drifted: VisualManifest = {
      ...reviewed,
      captures: reviewed.captures.map((capture) =>
        capture.route === "/" ? { ...capture, digest: "landing-drifted" } : capture,
      ),
    };
    const result = compareVisualManifests(baseline, drifted, approve());
    expect(result.approvalApplied).toBe(false);
    expect(result.changed).toEqual(["/@390"]);
  });

  it("stops matching when the baseline already renders a different version of the capture", () => {
    // The base moved: it now renders "/" as something else, so the reviewed old-to-new change differs.
    const movedBase: VisualManifest = {
      capture_profile: profile,
      captures: [{ ...captures[0]!, digest: "landing-moved" }, captures[1]!],
    };
    expect(compareVisualManifests(movedBase, reviewed, approve()).approvalApplied).toBe(false);
  });

  it("stops matching when the group adds a change that was never reviewed", () => {
    const extra: VisualManifest = {
      ...reviewed,
      captures: reviewed.captures.map((capture) =>
        capture.route === "/docs/" ? { ...capture, digest: "docs-unreviewed" } : capture,
      ),
    };
    const result = compareVisualManifests(baseline, extra, approve());
    expect(result.approvalApplied).toBe(false);
    expect(result.changed).toEqual(["/@390", "/docs/@390"]);
  });

  it("does not use a digest approval during the landing-profile migration", () => {
    // The landing captures are left out of the comparison then, so a digest would not cover them.
    const legacyBaseline: VisualManifest = { captures };
    const migrating: VisualManifest = {
      capture_profile: profile,
      captures: [
        { ...captures[0]!, digest: "landing-settled" },
        { ...captures[1]!, digest: "docs-changed" },
      ],
    };
    const migratingDigest = compareVisualManifests(legacyBaseline, migrating).changeDigest;
    const result = compareVisualManifests(
      legacyBaseline,
      migrating,
      approve({ approvedChangeDigests: `${prRef}:${migratingDigest}` }),
    );
    expect(result.approvalApplied).toBe(false);
    expect(result.changed).toEqual(["/docs/@390"]);
  });

  it("never lets a digest approval hide a missing capture", () => {
    const missing: VisualManifest = { capture_profile: profile, captures: [{ ...captures[0]!, digest: "landing-reviewed" }] };
    const missingDigest = compareVisualManifests(baseline, missing).changeDigest;
    expect(
      compareVisualManifests(baseline, missing, approve({ approvedChangeDigests: `${prRef}:${missingDigest}` })),
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

  it("orders rows by code unit so keys that differ only by Unicode normalization stay distinct", () => {
    // `/é@390` composed and decomposed look the same and can collate as equal in a locale; code-unit
    // order keeps them distinct, so the digest does not depend on the order they were listed in.
    const composed = { key: "/\u00e9@390", to: "same" };
    const decomposed = { key: "/e\u0301@390", to: "same" };
    expect(visualChangeDigest([], [composed, decomposed])).toBe(visualChangeDigest([], [decomposed, composed]));
    expect(visualChangeDigest([], [composed])).not.toBe(visualChangeDigest([], [decomposed]));
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

  it("cannot be made to collide by characters inside a route", () => {
    // With tab and newline separated text, a route containing the separators and a second capture's
    // line could serialize to the same bytes as two real captures.
    const x = "x".repeat(64);
    const y = "y".repeat(64);
    const two = visualChangeDigest([], [
      { key: "/a@390", to: x },
      { key: "/b@390", to: y },
    ]);
    const forged = visualChangeDigest([], [{ key: `/a@390\t${x}\nnew\t/b@390`, to: y }]);
    expect(forged).not.toBe(two);
    // The same holds for a changed capture whose old and new digests contain separators.
    expect(visualChangeDigest([{ key: "/a@390", from: "p\tq", to: "r" }], [])).not.toBe(
      visualChangeDigest([{ key: "/a@390", from: "p", to: "q\tr" }], []),
    );
  });
});

describe("pull request numbers", () => {
  it.each([
    ["2385", ["2385"]],
    ["  2385 ", ["2385"]],
    ["2384 2385 2386", ["2384", "2385", "2386"]],
    ["2384,2385\n2386", ["2384", "2385", "2386"]],
    ["2385 2385", ["2385"]],
  ])("reads %j", (list, expected) => {
    expect(pullRequestNumbers(list)).toEqual(expected);
  });

  it.each([
    undefined,
    "",
    "   ",
    "0",
    "-5",
    "12abc",
    "pr-2385",
    "2385 pr-2386",
    "2385 0",
    "2385 +7",
    "1e3",
    "2385.5",
    `gh-readonly-queue/develop/pr-2385-${"a".repeat(40)}`,
  ])("reads nothing from %j, so no approval can apply", (list) => {
    // One unreadable item voids the whole list: a partial list must not grant an approval.
    expect(pullRequestNumbers(list)).toEqual([]);
  });
});
