export const MAX_GROUP_COMMITS: number;

export type GithubGet = (path: string) => Promise<any>;

export function pullRequestFromCommitMessage(message: unknown): string;

export function mergeGroupPullRequests(context: {
  github: GithubGet;
  repository: string;
  baseSha: string | undefined;
  headSha: string | undefined;
}): Promise<string[]>;
