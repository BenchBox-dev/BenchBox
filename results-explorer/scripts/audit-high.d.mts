export type AllowlistEntry = {
  id: string;
  package: string;
  reason: string;
  review_by: string;
  link: string;
};

export type AuditEvaluation = {
  failures: string[];
  active: AllowlistEntry[];
  unused: AllowlistEntry[];
};

export function entryProblems(entry: unknown, today: string, patchedVersions?: string[]): string[];

export function evaluateAudit(input: {
  audit: unknown;
  allowlist: unknown;
  today: string;
  versionsOutsideRange: (name: string, range: string) => string[];
}): AuditEvaluation;

export function main(options?: {
  audit?: () => unknown;
  allowlist?: () => unknown;
  versionsOutsideRange?: (name: string, range: string) => string[];
  now?: Date;
  log?: (message: string) => void;
  error?: (message: string) => void;
}): number;
