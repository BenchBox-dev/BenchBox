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

const data = await github(`/repos/${repository}/actions/artifacts?name=public-site-visual-baseline&per_page=100`);
const validArtifacts = (data.artifacts ?? []).filter((candidate) => !candidate.expired);
const artifact = validArtifacts.find((candidate) => candidate.workflow_run?.head_sha === baseSha);
if (!artifact) {
  if (validArtifacts.length === 0) {
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
