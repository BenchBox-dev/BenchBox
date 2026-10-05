export const PUBLIC_SITE_CAPTURE_PROFILE = "landing-settled-v3";

export type VisualCapture = {
  digest: string;
  filename?: string;
  route: string;
  viewport_width: number;
};

export const DEFAULT_VISUAL_RENDERER = "sphinx";

export type VisualManifest = {
  capture_profile?: string;
  renderer?: string;
  captures: VisualCapture[];
};

export type VisualApproval = {
  approvedHeadSha?: string;
  currentHeadSha?: string;
  reason?: string;
};

export type VisualComparison = {
  missing: string[];
  unexpected: string[];
  changed: string[];
  approvedUnexpected: string[];
  approvedChanged: string[];
  approvalApplied: boolean;
};

export function hasExactHeadVisualApproval(approval: VisualApproval | undefined): boolean {
  if (!approval) return false;
  const approvedHeadSha = approval.approvedHeadSha?.trim() ?? "";
  const currentHeadSha = approval.currentHeadSha?.trim() ?? "";
  const reason = approval.reason?.trim() ?? "";
  return approvedHeadSha.length > 0 && approvedHeadSha === currentHeadSha && reason.length > 0;
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
  const approvalApplied = hasExactHeadVisualApproval(approval);
  return {
    missing,
    unexpected: approvalApplied ? [] : unexpected,
    changed: approvalApplied ? [] : changed,
    approvedUnexpected: approvalApplied ? unexpected : [],
    approvedChanged: approvalApplied ? changed : [],
    approvalApplied,
  };
}

export type RendererAwareComparison = VisualComparison & {
  baselineRenderer: string;
  currentRenderer: string;
  rendererChanged: boolean;
  message: string;
};

export function compareVisualManifestsAcrossRenderers(
  baseline: VisualManifest,
  current: VisualManifest,
  approval?: VisualApproval,
): RendererAwareComparison {
  const baselineRenderer = baseline.renderer ?? DEFAULT_VISUAL_RENDERER;
  const currentRenderer = current.renderer ?? DEFAULT_VISUAL_RENDERER;
  const rendererChanged = baselineRenderer !== currentRenderer;
  const labels = { baselineRenderer, currentRenderer, rendererChanged };
  if (!rendererChanged) {
    const comparison = compareVisualManifests(baseline, current, approval);
    return { ...comparison, ...labels, message: `visual baseline mismatch; changed captures: ${comparison.changed.join(", ")}` };
  }
  const key = (capture: VisualCapture) => `${capture.route}@${capture.viewport_width}`;
  const baselineKeys = new Set(baseline.captures.map(key));
  const unmatched = compareVisualManifests(baseline, current, approval);
  const everyCapture = current.captures.map(key).filter((captureKey) => baselineKeys.has(captureKey));
  const approvalApplied = hasExactHeadVisualApproval(approval);
  return {
    missing: unmatched.missing,
    unexpected: unmatched.unexpected,
    changed: approvalApplied ? [] : everyCapture,
    approvedUnexpected: unmatched.approvedUnexpected,
    approvedChanged: approvalApplied ? everyCapture : [],
    approvalApplied,
    ...labels,
    message: `renderer changed from ${baselineRenderer} to ${currentRenderer}; every capture differs and needs an exact-head approval (APPROVED_HEAD_SHA equal to the PR head and a nonempty APPROVAL_REASON)`,
  };
}
