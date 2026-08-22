export const PUBLIC_SITE_CAPTURE_PROFILE = "landing-settled-v2";

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

export function compareVisualManifests(
  baseline: VisualManifest,
  current: VisualManifest,
): { missing: string[]; unexpected: string[]; changed: string[] } {
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
  return { missing, unexpected, changed };
}
