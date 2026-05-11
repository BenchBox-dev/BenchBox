interface EvidenceCaptureShas {
  developRef?: string;
  developSha: string;
  headSha: string;
}

export function assertEvidenceCaptureMatchesDevelop({
  developRef = "origin/develop",
  developSha,
  headSha,
}: EvidenceCaptureShas): void {
  if (headSha === developSha) {
    return;
  }

  throw new Error(
    [
      `PR #246 final evidence capture must run against ${developRef}.`,
      `HEAD is ${headSha}, but ${developRef} is ${developSha}.`,
      `Checkout ${developRef} before setting PR246_FINAL_CAPTURE=1.`,
    ].join(" "),
  );
}
