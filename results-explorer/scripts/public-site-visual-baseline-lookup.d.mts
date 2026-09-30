export const DOCS_WORKFLOW_PATH: string;
export const MERGE_QUEUE_BRANCH_PREFIX: string;
export const ARTIFACT_PAGE_SIZE: number;
export const LEGACY_BASELINE_NAME: string;
export const MAX_BASELINE_SHAS: number;
export const MAX_ARTIFACT_PAGES: number;

export type BaselineSource = "develop" | "merge-queue";

export type BaselineArtifact = {
  id: number;
  name: string;
  expired?: boolean;
  archive_download_url?: string;
  workflow_run?: { id: number; head_sha?: string };
};

export type GithubGet = (path: string) => Promise<any>;

export function trustedBaselineSource(
  run: Record<string, unknown> | undefined,
  context: { repository: string; baseSha: string },
): BaselineSource | undefined;

export function baselineNames(baseSha: string): string[];

export function baselineShaOrder(baseSha: string, candidateShas?: string[]): string[];

export function findTrustedBaseline(options: {
  github: GithubGet;
  repository: string;
  baseSha: string;
  candidateShas?: string[];
}): Promise<{ artifact: BaselineArtifact; source: BaselineSource; baselineSha: string } | undefined>;

export function waitForTrustedBaseline(options: {
  github: GithubGet;
  repository: string;
  baseSha: string;
  candidateShas?: string[];
  waitMs?: number;
  minAttempts?: number;
  delayMs?: number;
  waitDelayMs?: number;
  now?: () => number;
  sleep?: (ms: number) => Promise<void>;
  log?: (message: string) => void;
}): Promise<{
  artifact: BaselineArtifact | undefined;
  source: BaselineSource | undefined;
  baselineSha: string | undefined;
  attempts: number;
}>;
