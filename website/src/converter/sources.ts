import { readdirSync } from "node:fs";
import path from "node:path";

export const EXCLUDED_ROOTS: ReadonlySet<string> = new Set(["_build", "_tags", "_static", "_templates", "_project", "agent"]);

export const EXCLUDED_FILES: ReadonlySet<string> = new Set([
  "development/task-management-design.md",
  "development/dependency-audit-raw.md",
  "development/unified_frame_any_survey.md",
  "development/duplication-residuals.md",
  "development/comment-policy.md",
  "development/comment-cleanup-scope.md",
  "design/future-state/index.md",
  "design/future-state/contract-index.md",
  "design/future-state/formalize-mcp-internal-apis/README.md",
  "design/future-state/gate-monitoring-behind-optional-extra/README.md",
  "design/future-state/isolate-experimental-core-subsystems/README.md",
  "design/future-state/prune-publishing-subsystem/README.md",
  "design/future-state/remove-release-tooling-from-wheel/README.md",
  "development/adapter-refactor-map.md",
  "development/benchbox-results-platform-strategy.md",
  "development/dependency-inventory.md",
  "development/dev-loop-property-ledger.md",
  "development/independent-publication-threat-model.md",
  "development/pr-base-branch-policy.md",
  "development/result-validation-triage.md",
  "development/results-explorer-brand-ownership.md",
  "development/throughput-result-alignment.md",
  "development/transactional-benchmark-alignment.md",
  "development/adr/TEMPLATE-results-data-extraction.md",
  "development/adr/adr-dev-loop-v2.md",
  "development/adr/adr-duckdb-datasketches-vendoring.md",
  "development/adr/adr-explorer-cli-surface.md",
  "development/adr/adr-independent-publication-authorities.md",
  "development/adr/adr-published-results-history-retention.md",
  "development/adr/adr-published-results-slim-corpus-branch.md",
  "operations/agent-instruction-evaluation.md",
  "operations/branch-rename-runbook.md",
  "operations/browser-ci.md",
  "operations/corpus-refresh.md",
  "operations/dev-loop-worktrees.md",
  "operations/develop-post-merge-gaps.md",
  "operations/develop-push-drop-inventory.md",
  "operations/github-org-transfer.md",
  "operations/hosted-credentials.md",
  "operations/independent-publication-baseline.md",
  "operations/independent-publication-contract.md",
  "operations/mcp-production-readiness-evidence.md",
  "operations/mcp-production-readiness.md",
  "operations/merge-queue-canary-runbook.md",
  "operations/merge-queue-governance.md",
  "operations/nightly-t3.md",
  "operations/oracle-review-v2.md",
  "operations/pr-triage.md",
  "operations/publication-deployer-soak-and-retirement.md",
  "operations/release-artifacts.md",
  "operations/release-guide.md",
  "operations/repo-admin-settings.md",
  "operations/results-explorer-qa.md",
  "operations/results-phase-2-runbook.md",
  "operations/results-phase-3-runbook.md",
  "operations/site-deploy.md",
  "operations/soundness-drain.md",
  "operations/todo-db-benchbox-extraction.md",
  "platforms/workaround-index.md",
  "reference/threat-model.md",
]);

export type DocSourceFile = { absolute: string; relative: string };

function compareNames(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

function walk(root: string, directory: string, suffix: string, found: DocSourceFile[]): void {
  const entries = readdirSync(directory, { withFileTypes: true }).sort((a, b) => compareNames(a.name, b.name));
  for (const entry of entries) {
    const absolute = path.join(directory, entry.name);
    const relative = path.relative(root, absolute).split(path.sep).join("/");
    if (entry.name.startsWith(".#")) continue;
    if (entry.isDirectory()) {
      if (directory === root && EXCLUDED_ROOTS.has(entry.name)) continue;
      if (entry.name === "_sources" || entry.name.endsWith(".lproj")) continue;
      walk(root, absolute, suffix, found);
    } else if (entry.name.endsWith(suffix) && !EXCLUDED_FILES.has(relative)) {
      found.push({ absolute, relative });
    }
  }
}

export function listDocSources(docsRoot: string, suffix: ".md" | ".rst" = ".md"): DocSourceFile[] {
  const found: DocSourceFile[] = [];
  walk(docsRoot, docsRoot, suffix, found);
  return found;
}
