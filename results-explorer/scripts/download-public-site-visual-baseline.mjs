#!/usr/bin/env node
/** Download the baseline artifact produced by the exact protected-develop SHA. */

import { execFile } from "node:child_process";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const token = process.env.GITHUB_TOKEN;
const repository = process.env.GITHUB_REPOSITORY;
const baseSha = process.env.PUBLIC_SITE_VISUAL_BASE_SHA;
const output = process.env.PUBLIC_SITE_VISUAL_BASELINE;
const apiUrl = process.env.GITHUB_API_URL ?? "https://api.github.com";
const BASELINE_LOOKUP_ATTEMPTS = 6;
const BASELINE_LOOKUP_DELAY_MS = 2_000;
const ARTIFACT_PAGE_SIZE = 100;
const BASELINE_NAMES = [`public-site-visual-baseline-${baseSha}`, "public-site-visual-baseline"];

if (!token || !repository || !baseSha || !output) {
  throw new Error("GITHUB_TOKEN, GITHUB_REPOSITORY, PUBLIC_SITE_VISUAL_BASE_SHA, and PUBLIC_SITE_VISUAL_BASELINE are required");
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

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function listValidArtifacts(name) {
  const validArtifacts = [];
  for (let page = 1; ; page += 1) {
    const data = await github(
      `/repos/${repository}/actions/artifacts?name=${encodeURIComponent(name)}&per_page=${ARTIFACT_PAGE_SIZE}&page=${page}`,
    );
    if (!Array.isArray(data.artifacts)) {
      throw new Error("GitHub API returned an invalid artifact list");
    }
    validArtifacts.push(...data.artifacts.filter((candidate) => !candidate.expired && candidate.name === name));
    if (data.artifacts.length < ARTIFACT_PAGE_SIZE) break;
  }
  return validArtifacts;
}

let artifact;
let lastLookupError;
for (let attempt = 1; attempt <= BASELINE_LOOKUP_ATTEMPTS; attempt += 1) {
  try {
    const candidates = (await Promise.all(BASELINE_NAMES.map((name) => listValidArtifacts(name)))).flat();
    lastLookupError = undefined;
    for (const candidate of candidates) {
      const runId = candidate.workflow_run?.id;
      if (!Number.isInteger(runId)) continue;
      if (candidate.name === "public-site-visual-baseline" && candidate.workflow_run.head_sha !== baseSha) continue;
      // Artifact names alone are untrusted: PR runs can upload the same name.
      const run = await github(`/repos/${repository}/actions/runs/${runId}`);
      if (run.head_branch !== "develop" || !["push", "workflow_dispatch"].includes(run.event)) continue;
      if (run.path !== ".github/workflows/docs.yml") continue;
      artifact = candidate;
      break;
    }
    if (artifact) break;
  } catch (error) {
    lastLookupError = error;
  }
  if (attempt < BASELINE_LOOKUP_ATTEMPTS) await sleep(BASELINE_LOOKUP_DELAY_MS);
}

if (!artifact && lastLookupError) {
  throw new Error(`Unable to list protected public-site visual baselines after ${BASELINE_LOOKUP_ATTEMPTS} attempts`, {
    cause: lastLookupError,
  });
}
if (!artifact) {
  throw new Error(`No unexpired protected public-site visual baseline is bound to base SHA ${baseSha}; dispatch Documentation on develop with baseline_source_sha=${baseSha}`);
}

const response = await fetch(artifact.archive_download_url, { headers });
if (!response.ok) throw new Error(`Baseline artifact download failed with HTTP ${response.status}`);
await mkdir(output, { recursive: true });
const archive = `${output}.zip`;
await writeFile(archive, Buffer.from(await response.arrayBuffer()));
await execFileAsync("unzip", ["-q", archive, "-d", output]);
const manifest = JSON.parse(await readFile(`${output}/manifest.json`, "utf8"));
if (manifest.source_sha !== baseSha) {
  throw new Error(`Baseline artifact ${artifact.id} has source SHA ${manifest.source_sha}, expected ${baseSha}`);
}
console.log(`Downloaded baseline artifact ${artifact.id} for ${baseSha} to ${output}`);
