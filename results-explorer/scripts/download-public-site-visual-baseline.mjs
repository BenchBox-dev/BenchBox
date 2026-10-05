#!/usr/bin/env node
/** Download the visual baseline for the exact base SHA or a site-equivalent ancestor. */

import { execFile } from "node:child_process";
import { appendFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { promisify } from "node:util";

import { waitForTrustedBaseline } from "./public-site-visual-baseline-lookup.mjs";

const execFileAsync = promisify(execFile);
const token = process.env.GITHUB_TOKEN;
const repository = process.env.GITHUB_REPOSITORY;
const baseSha = process.env.PUBLIC_SITE_VISUAL_BASE_SHA;
const output = process.env.PUBLIC_SITE_VISUAL_BASELINE;
const apiUrl = process.env.GITHUB_API_URL ?? "https://api.github.com";
// Space-separated first-parent ancestors of the base whose public-site inputs
// are byte-identical to it, nearest first. The workflow classifier computes
// them; they render the same site as the base.
const candidateShas = (process.env.PUBLIC_SITE_VISUAL_BASELINE_CANDIDATES ?? "").split(/\s+/).filter(Boolean);
// Optional bounded wait for a develop push to publish the base.
const waitSeconds = Number(process.env.PUBLIC_SITE_VISUAL_BASELINE_WAIT_SECONDS ?? "0");

if (!/^[0-9a-f]{40}$/.test(baseSha ?? "")) {
  throw new Error("PUBLIC_SITE_VISUAL_BASE_SHA must be a 40-character lowercase SHA");
}
if (!token || !repository || !output) {
  throw new Error("GITHUB_TOKEN, GITHUB_REPOSITORY, and PUBLIC_SITE_VISUAL_BASELINE are required");
}
if (!Number.isFinite(waitSeconds) || waitSeconds < 0) {
  throw new Error("PUBLIC_SITE_VISUAL_BASELINE_WAIT_SECONDS must be a non-negative number");
}

const headers = {
  Accept: "application/vnd.github+json",
  Authorization: `Bearer ${token}`,
  "X-GitHub-Api-Version": "2022-11-28",
};

async function github(path) {
  const response = await fetch(`${apiUrl}${path}`, { headers });
  if (!response.ok) throw new Error(`GitHub API ${response.status} for ${path}`);
  return response.json();
}

const { artifact, source, baselineSha } = await waitForTrustedBaseline({
  github,
  repository,
  baseSha,
  candidateShas,
  waitMs: waitSeconds * 1000,
  log: (message) => console.log(message),
});

if (!artifact) {
  throw new Error(`No unexpired protected public-site visual baseline is bound to base SHA ${baseSha} or a site-equivalent ancestor; dispatch Documentation on develop with baseline_source_sha=${baseSha}`);
}

const response = await fetch(artifact.archive_download_url, { headers });
if (!response.ok) throw new Error(`Baseline artifact download failed with HTTP ${response.status}`);
await mkdir(output, { recursive: true });
const archive = `${output}.zip`;
await writeFile(archive, Buffer.from(await response.arrayBuffer()));
await execFileAsync("unzip", ["-q", archive, "-d", output]);
const manifest = JSON.parse(await readFile(`${output}/manifest.json`, "utf8"));
if (manifest.source_sha !== baselineSha) {
  throw new Error(`Baseline artifact ${artifact.id} has source SHA ${manifest.source_sha}, expected ${baselineSha}`);
}
if (process.env.GITHUB_OUTPUT) {
  await appendFile(process.env.GITHUB_OUTPUT, `baseline_sha=${baselineSha}\n`);
}
const equivalence = baselineSha === baseSha ? "exact base" : `site-equivalent ancestor of ${baseSha}`;
console.log(
  `Downloaded baseline artifact ${artifact.id} for ${baselineSha} (${equivalence}) to ${output} (source: ${source}, run ${artifact.workflow_run.id})`,
);
