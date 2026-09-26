export const DOCS_WORKFLOW_PATH: string;
export const MERGE_QUEUE_BRANCH_PREFIX: string;
export const ARTIFACT_PAGE_SIZE: number;

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

export function findTrustedBaseline(options: {
  github: GithubGet;
  repository: string;
  baseSha: string;
}): Promise<{ artifact: BaselineArtifact; source: BaselineSource } | undefined>;

export function waitForTrustedBaseline(options: {
  github: GithubGet;
  repository: string;
  baseSha: string;
  waitMs?: number;
  minAttempts?: number;
  delayMs?: number;
  waitDelayMs?: number;
  now?: () => number;
  sleep?: (ms: number) => Promise<void>;
  log?: (message: string) => void;
}): Promise<{ artifact: BaselineArtifact | undefined; source: BaselineSource | undefined; attempts: number }>;
