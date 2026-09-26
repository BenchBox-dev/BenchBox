#!/usr/bin/env node
/** Download the visual baseline captured from the exact base SHA. */

import { execFile } from "node:child_process";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { promisify } from "node:util";

import { waitForTrustedBaseline } from "./public-site-visual-baseline-lookup.mjs";

const execFileAsync = promisify(execFile);
const token = process.env.GITHUB_TOKEN;
const repository = process.env.GITHUB_REPOSITORY;
const baseSha = process.env.PUBLIC_SITE_VISUAL_BASE_SHA;
const output = process.env.PUBLIC_SITE_VISUAL_BASELINE;
const apiUrl = process.env.GITHUB_API_URL ?? "https://api.github.com";
// A merge-queue follower's base is the leader group's head. Its baseline is
// published by the leader's own visual job, so followers wait for it instead of
// failing on the first lookup. Pull requests keep the short retry only.
const waitSeconds = Number(process.env.PUBLIC_SITE_VISUAL_BASELINE_WAIT_SECONDS ?? "0");

if (!token || !repository || !baseSha || !output) {
  throw new Error("GITHUB_TOKEN, GITHUB_REPOSITORY, PUBLIC_SITE_VISUAL_BASE_SHA, and PUBLIC_SITE_VISUAL_BASELINE are required");
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

const { artifact, source } = await waitForTrustedBaseline({
  github,
  repository,
  baseSha,
  waitMs: waitSeconds * 1000,
  log: (message) => console.log(message),
});

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
console.log(
  `Downloaded baseline artifact ${artifact.id} for ${baseSha} to ${output} (source: ${source}, run ${artifact.workflow_run.id})`,
);
