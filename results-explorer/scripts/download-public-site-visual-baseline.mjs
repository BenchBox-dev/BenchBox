#!/usr/bin/env node
/** Download the baseline artifact produced by the exact protected-develop SHA. */

import { execFile } from "node:child_process";
import { appendFile, mkdir, writeFile } from "node:fs/promises";
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

async function listValidArtifacts() {
  const validArtifacts = [];
  for (let page = 1; ; page += 1) {
    const data = await github(
      `/repos/${repository}/actions/artifacts?name=public-site-visual-baseline&per_page=${ARTIFACT_PAGE_SIZE}&page=${page}`,
    );
    if (!Array.isArray(data.artifacts)) {
      throw new Error("GitHub API returned an invalid artifact list");
    }
    validArtifacts.push(...data.artifacts.filter((candidate) => !candidate.expired));
    if (data.artifacts.length < ARTIFACT_PAGE_SIZE) break;
  }
  return validArtifacts;
}

let artifact;
let sawValidArtifact = false;
let lookupSucceeded = false;
let lookupFailed = false;
let lastLookupError;
for (let attempt = 1; attempt <= BASELINE_LOOKUP_ATTEMPTS; attempt += 1) {
  try {
    const validArtifacts = await listValidArtifacts();
    lookupSucceeded = true;
    lookupFailed = false;
    lastLookupError = undefined;
    sawValidArtifact ||= validArtifacts.length > 0;
    artifact = validArtifacts.find((candidate) => candidate.workflow_run?.head_sha === baseSha);
    if (artifact) break;
  } catch (error) {
    lookupFailed = true;
    lastLookupError = error;
  }
  if (attempt < BASELINE_LOOKUP_ATTEMPTS) await sleep(BASELINE_LOOKUP_DELAY_MS);
}

if (!artifact && lookupFailed && lastLookupError) {
  throw new Error(`Unable to list protected public-site visual baselines after ${BASELINE_LOOKUP_ATTEMPTS} attempts`, {
    cause: lastLookupError,
  });
}
if (!artifact) {
  if (lookupSucceeded && !sawValidArtifact && !lookupFailed) {
    if (process.env.GITHUB_OUTPUT) await appendFile(process.env.GITHUB_OUTPUT, "bootstrap=true\n");
    throw new Error(`No protected public-site visual baseline exists yet; bootstrap from the next protected develop push (base SHA ${baseSha})`);
  }
  throw new Error(`No unexpired public-site visual baseline is bound to base SHA ${baseSha}`);
}

const response = await fetch(artifact.archive_download_url, { headers });
if (!response.ok) throw new Error(`Baseline artifact download failed with HTTP ${response.status}`);
await mkdir(output, { recursive: true });
const archive = `${output}.zip`;
await writeFile(archive, Buffer.from(await response.arrayBuffer()));
await execFileAsync("unzip", ["-q", archive, "-d", output]);
console.log(`Downloaded baseline artifact ${artifact.id} for ${baseSha} to ${output}`);
