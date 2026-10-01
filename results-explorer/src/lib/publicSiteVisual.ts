import { createHash } from "node:crypto";

export const PUBLIC_SITE_CAPTURE_PROFILE = "landing-settled-v2";
// Versions the digest input so a change to how it is built cannot match an older approval.
export const VISUAL_CHANGE_DIGEST_VERSION = "public-site-visual-change-v1";

export type VisualCapture = {
  digest: string;
  filename?: string;
  route: string;
  viewport_width: number;
};

export type VisualManifest = {
  capture_profile?: string;
  captures: VisualCapture[];
};

export type VisualApproval = {
  approvedHeadSha?: string;
  currentHeadSha?: string;
  reason?: string;
  // Reviewed visual changes, each `<pull request number>:<change digest>`, separated by whitespace or
  // commas. Unlike a head SHA, this can be recorded at PR review time and still match in a merge
  // group, whose own head SHA does not exist until the group forms. The pull request number keeps an
  // approval from authorizing the same pixels in a different PR, for example after a revert.
  approvedChangeDigests?: string;
  changeReason?: string;
  // The pull request number, or the merge-queue branch name `gh-readonly-queue/<base>/pr-<n>-<sha>`
  // that GitHub generates for a group, which carries the number of the PR it was built for.
  pullRequestRef?: string;
};

export type VisualComparison = {
  missing: string[];
  unexpected: string[];
  changed: string[];
  approvedUnexpected: string[];
  approvedChanged: string[];
  approvalApplied: boolean;
  approvalBasis?: "head" | "change-digest";
  // Empty when nothing changed or appeared. Print it so a maintainer can record it after review.
  changeDigest: string;
};

export function hasExactHeadVisualApproval(approval: VisualApproval | undefined): boolean {
  if (!approval) return false;
  const approvedHeadSha = approval.approvedHeadSha?.trim() ?? "";
  const currentHeadSha = approval.currentHeadSha?.trim() ?? "";
  const reason = approval.reason?.trim() ?? "";
  return approvedHeadSha.length > 0 && approvedHeadSha === currentHeadSha && reason.length > 0;
}

/**
 * Digest of one reviewed visual change: each changed capture as baseline digest to new digest, and
 * each capture that is new. It binds an approval to the rendering that was reviewed, so it matches
 * only a tree that renders exactly that change against exactly that baseline. If the base later
 * renders the same capture differently, the baseline side differs and the approval stops matching.
 */
export function visualChangeDigest(
  changed: { key: string; from: string; to: string }[],
  unexpected: { key: string; to: string }[],
): string {
  if (changed.length === 0 && unexpected.length === 0) return "";
  // JSON keeps field boundaries unambiguous whatever characters a route contains, so two different
  // change sets cannot serialize to the same bytes. Sorting makes the digest independent of order.
  const byText = (left: unknown[], right: unknown[]) => JSON.stringify(left).localeCompare(JSON.stringify(right));
  const changedRows = changed.map((entry) => [entry.key, entry.from, entry.to]).sort(byText);
  const newRows = unexpected.map((entry) => [entry.key, entry.to]).sort(byText);
  return createHash("sha256")
    .update(JSON.stringify([VISUAL_CHANGE_DIGEST_VERSION, changedRows, newRows]))
    .digest("hex");
}

/** The pull request number from a number or a merge-queue branch name, or "" when it cannot be read. */
export function pullRequestNumberFromRef(ref: string | undefined): string {
  const value = ref?.trim() ?? "";
  if (/^[1-9]\d*$/.test(value)) return value;
  return /^(?:refs\/heads\/)?gh-readonly-queue\/[^/]+\/pr-([1-9]\d*)-[0-9a-f]{40}$/.exec(value)?.[1] ?? "";
}

export function hasChangeDigestVisualApproval(approval: VisualApproval | undefined, changeDigest: string): boolean {
  if (!approval || changeDigest.length === 0) return false;
  const reason = approval.changeReason?.trim() ?? "";
  const pullRequest = pullRequestNumberFromRef(approval.pullRequestRef);
  if (reason.length === 0 || pullRequest.length === 0) return false;
  const approved = (approval.approvedChangeDigests ?? "").split(/[\s,]+/).filter((entry) => entry.length > 0);
  return approved.includes(`${pullRequest}:${changeDigest}`);
}

export function compareVisualManifests(
  baseline: VisualManifest,
  current: VisualManifest,
  approval?: VisualApproval,
): VisualComparison {
  const key = (capture: VisualCapture) => `${capture.route}@${capture.viewport_width}`;
  const expected = new Map(baseline.captures.map((capture) => [key(capture), capture.digest]));
  const actual = new Map(current.captures.map((capture) => [key(capture), capture.digest]));
  const missing = [...expected.keys()].filter((captureKey) => !actual.has(captureKey));
  const unexpected = [...actual.keys()].filter((captureKey) => !expected.has(captureKey));
  const migratingLanding =
    current.capture_profile === PUBLIC_SITE_CAPTURE_PROFILE &&
    baseline.capture_profile !== PUBLIC_SITE_CAPTURE_PROFILE;
  const changed = current.captures
    .filter((capture) => expected.has(key(capture)))
    .filter((capture) => !(migratingLanding && capture.route === "/"))
    .filter((capture) => expected.get(key(capture)) !== capture.digest)
    .map(key);
  const changeDigest = visualChangeDigest(
    changed.map((captureKey) => ({
      key: captureKey,
      from: expected.get(captureKey) ?? "",
      to: actual.get(captureKey) ?? "",
    })),
    unexpected.map((captureKey) => ({ key: captureKey, to: actual.get(captureKey) ?? "" })),
  );
  const approvedByHead = hasExactHeadVisualApproval(approval);
  // During the one-time landing migration the landing captures are left out of `changed`, so a
  // digest would not cover them. Approve by head SHA then, or wait for a settled baseline.
  const approvedByDigest = !migratingLanding && hasChangeDigestVisualApproval(approval, changeDigest);
  const approvalApplied = approvedByHead || approvedByDigest;
  return {
    missing,
    unexpected: approvalApplied ? [] : unexpected,
    changed: approvalApplied ? [] : changed,
    approvedUnexpected: approvalApplied ? unexpected : [],
    approvedChanged: approvalApplied ? changed : [],
    approvalApplied,
    approvalBasis: approvedByHead ? "head" : approvedByDigest ? "change-digest" : undefined,
    changeDigest,
  };
}
