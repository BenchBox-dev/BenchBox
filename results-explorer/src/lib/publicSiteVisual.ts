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
  // Digests of reviewed visual changes, separated by whitespace or commas. Unlike a head SHA, a
  // change digest can be recorded at PR review time and still match in a merge group, whose own
  // head SHA does not exist until the group forms.
  approvedChangeDigests?: string;
  changeReason?: string;
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
  const lines = [
    ...changed.map((entry) => `changed\t${entry.key}\t${entry.from}\t${entry.to}`),
    ...unexpected.map((entry) => `new\t${entry.key}\t${entry.to}`),
  ].sort();
  return createHash("sha256")
    .update([VISUAL_CHANGE_DIGEST_VERSION, ...lines].join("\n"))
    .digest("hex");
}

export function hasChangeDigestVisualApproval(approval: VisualApproval | undefined, changeDigest: string): boolean {
  if (!approval || changeDigest.length === 0) return false;
  const reason = approval.changeReason?.trim() ?? "";
  const approved = (approval.approvedChangeDigests ?? "").split(/[\s,]+/).filter((digest) => digest.length > 0);
  return reason.length > 0 && approved.includes(changeDigest);
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
  const approvedByDigest = hasChangeDigestVisualApproval(approval, changeDigest);
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
