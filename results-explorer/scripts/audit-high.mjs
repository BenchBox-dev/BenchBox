#!/usr/bin/env node
/**
 * Dependency audit gate: `npm audit` at the high level, minus an explicit,
 * self-expiring allowlist of advisories that have no available fix.
 *
 * An allowlist entry (audit-high-allowlist.json) stops covering its advisory,
 * and the gate fails, once any of these is true:
 * - its `review_by` date has passed;
 * - the registry now holds a release outside the advisory's vulnerable range
 *   (a fix exists, so the entry should be removed and the dependency updated);
 * - the entry is malformed.
 *
 * Every other high or critical finding fails the gate. A vulnerability reached
 * only through other vulnerable packages (npm reports these by package name) is
 * covered when every advisory beneath it is allowlisted.
 */
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = fileURLToPath(new URL(".", import.meta.url));
const explorerRoot = resolve(here, "..");
const ALLOWLIST_PATH = resolve(here, "audit-high-allowlist.json");
const BLOCKING = new Set(["high", "critical"]);
const REQUIRED_FIELDS = ["id", "package", "reason", "review_by", "link"];

function advisoryId(url) {
  const match = /GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}/i.exec(String(url ?? ""));
  return match ? match[0].toLowerCase() : null;
}

function isoDay(date) {
  return date.toISOString().slice(0, 10);
}

/** Problems that make an allowlist entry unusable, as messages. */
export function entryProblems(entry, today, patchedVersions = []) {
  const label = `allowlist entry ${entry?.id ?? "<missing id>"}`;
  const problems = [];
  const missing = REQUIRED_FIELDS.filter(
    (field) => typeof entry?.[field] !== "string" || entry[field].trim() === "",
  );
  if (missing.length > 0) {
    problems.push(`${label} is missing: ${missing.join(", ")}`);
    return problems;
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(entry.review_by) || Number.isNaN(Date.parse(entry.review_by))) {
    problems.push(`${label} has an invalid review_by date "${entry.review_by}" (use YYYY-MM-DD)`);
  } else if (today > entry.review_by) {
    problems.push(
      `${label} expired on ${entry.review_by}: re-check ${entry.link} and either remove the entry or set a new review_by`,
    );
  }
  if (patchedVersions.length > 0) {
    problems.push(
      `${label} has a fix: ${entry.package} ${patchedVersions.join(", ")} is outside the vulnerable range; remove the entry and update the dependency`,
    );
  }
  return problems;
}

/** Vulnerable ranges npm reported for an advisory id, from the audit JSON. */
function reportedRanges(audit, id) {
  const ranges = new Set();
  for (const vulnerability of Object.values(audit.vulnerabilities ?? {})) {
    for (const via of vulnerability.via ?? []) {
      if (typeof via === "object" && advisoryId(via.url) === id && via.range) {
        ranges.add(via.range);
      }
    }
  }
  return [...ranges];
}

/**
 * Decide the gate from parsed `npm audit --json` output.
 *
 * `versionsOutsideRange(package, range)` returns the published stable versions
 * of `package` that do not satisfy the vulnerable `range`.
 */
export function evaluateAudit({ audit, allowlist, today, versionsOutsideRange }) {
  const failures = [];
  const active = [];
  const unused = [];

  if (audit?.error) {
    return {
      failures: [`npm audit failed: ${audit.error.summary ?? audit.error.code ?? "unknown error"}`],
      active,
      unused,
    };
  }
  if (typeof audit?.vulnerabilities !== "object" || audit.vulnerabilities === null) {
    return { failures: ["npm audit output has no vulnerabilities object"], active, unused };
  }
  if (!Array.isArray(allowlist)) {
    return { failures: ["the allowlist must be a JSON array"], active, unused };
  }

  const usable = new Map();
  for (const entry of allowlist) {
    const ranges = reportedRanges(audit, String(entry?.id ?? "").toLowerCase());
    const patched = ranges.flatMap((range) => versionsOutsideRange(entry?.package, range));
    const problems = entryProblems(entry, today, [...new Set(patched)]);
    failures.push(...problems);
    if (problems.length === 0) {
      usable.set(entry.id.toLowerCase(), entry);
    }
  }

  const vulnerabilities = audit.vulnerabilities;
  const covered = new Map();
  const used = new Set();
  const isCovered = (name, trail = new Set()) => {
    if (covered.has(name)) return covered.get(name);
    if (trail.has(name)) return true;
    const vulnerability = vulnerabilities[name];
    if (!vulnerability) return false;
    trail.add(name);
    let ok = true;
    for (const via of vulnerability.via ?? []) {
      if (typeof via === "string") {
        ok = isCovered(via, trail) && ok;
      } else if (BLOCKING.has(via.severity)) {
        const id = advisoryId(via.url);
        const entry = id && usable.get(id);
        if (entry && entry.package === via.name) {
          used.add(id);
        } else {
          ok = false;
        }
      }
    }
    trail.delete(name);
    covered.set(name, ok);
    return ok;
  };

  for (const [name, vulnerability] of Object.entries(vulnerabilities)) {
    if (BLOCKING.has(vulnerability.severity) && !isCovered(name)) {
      const advisories = (vulnerability.via ?? [])
        .filter((via) => typeof via === "object")
        .map((via) => advisoryId(via.url) ?? via.title);
      failures.push(
        `${vulnerability.severity} finding in ${name}${advisories.length > 0 ? ` (${advisories.join(", ")})` : ""} is not allowlisted`,
      );
    }
  }

  for (const [id, entry] of usable) {
    (used.has(id) ? active : unused).push(entry);
  }
  return { failures, active, unused };
}

/** Stable versions the registry lists outside `range`, via npm itself. */
function registryVersionsOutsideRange(name, range, run = spawnSync) {
  const list = (spec) => {
    const result = run("npm", ["view", spec, "version", "--json"], {
      cwd: explorerRoot,
      encoding: "utf8",
    });
    if (result.status !== 0) {
      throw new Error(`npm view ${spec} failed: ${String(result.stderr).trim()}`);
    }
    const parsed = result.stdout.trim() === "" ? [] : JSON.parse(result.stdout);
    return (Array.isArray(parsed) ? parsed : [parsed]).filter((v) => !v.includes("-"));
  };
  const all = list(name);
  const vulnerable = new Set(list(`${name}@${range}`));
  return all.filter((version) => !vulnerable.has(version));
}

function runNpmAudit() {
  const result = spawnSync("npm", ["audit", "--json", "--audit-level=high"], {
    cwd: explorerRoot,
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
  });
  if (result.error) throw result.error;
  // npm exits non-zero when it finds vulnerabilities but still writes the report.
  return JSON.parse(result.stdout);
}

export function main({
  audit = runNpmAudit,
  allowlist = () => JSON.parse(readFileSync(ALLOWLIST_PATH, "utf8")),
  versionsOutsideRange = registryVersionsOutsideRange,
  now = new Date(),
  log = console.log,
  error = console.error,
} = {}) {
  let result;
  try {
    result = evaluateAudit({
      audit: audit(),
      allowlist: allowlist(),
      today: isoDay(now),
      versionsOutsideRange,
    });
  } catch (cause) {
    error(`audit:high could not complete: ${cause instanceof Error ? cause.message : cause}`);
    return 1;
  }

  for (const entry of result.active) {
    log(`allowlisted until ${entry.review_by}: ${entry.id} (${entry.package}) - ${entry.reason} ${entry.link}`);
  }
  for (const entry of result.unused) {
    log(`allowlist entry ${entry.id} (${entry.package}) matches no current finding; remove it.`);
  }
  for (const message of result.failures) {
    error(`audit:high: ${message}`);
  }
  if (result.failures.length > 0) return 1;
  log("audit:high: no high or critical findings beyond the allowlist.");
  return 0;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = main();
}
