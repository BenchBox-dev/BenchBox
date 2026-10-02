export const MAX_GROUP_COMMITS: number;
export const MAX_ATTEMPTS: number;
export const RETRY_BASE_DELAY_MS: number;
export const MAX_RETRY_WAIT_MS: number;

export type GithubGet = (path: string) => Promise<any>;

export function createGithubGet(options: {
  token: string | undefined;
  apiUrl?: string;
  fetchImpl?: (url: string, init?: any) => Promise<any>;
}): GithubGet;

export function rateLimitWaitMs(input: {
  retryAfter: string | null | undefined;
  reset: string | null | undefined;
  useReset: boolean;
  now?: number;
}): number | undefined;

export function isTransientGithubError(error: unknown): boolean;

export function withRetries<T>(
  operation: () => Promise<T>,
  options?: { sleep?: (ms: number) => Promise<void> },
): Promise<T>;

export function pullRequestFromCommitMessage(message: unknown): string;

export function mergeGroupPullRequests(context: {
  github: GithubGet;
  repository: string;
  baseSha: string | undefined;
  headSha: string | undefined;
  sleep?: (ms: number) => Promise<void>;
}): Promise<string[]>;
