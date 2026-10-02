#!/usr/bin/env node
/** Publish the pull requests a visual approval may name for this run as the step output `pull_requests`. */

import { appendFile } from "node:fs/promises";

import { createGithubGet, mergeGroupPullRequests } from "./public-site-visual-approval-members.mjs";

const event = process.env.APPROVAL_EVENT ?? "";
const apiUrl = process.env.GITHUB_API_URL ?? "https://api.github.com";

const github = createGithubGet({ token: process.env.GITHUB_TOKEN, apiUrl });

let pullRequests = [];
try {
  if (event === "pull_request") {
    const number = process.env.APPROVAL_PR_NUMBER ?? "";
    pullRequests = /^[1-9]\d*$/.test(number) ? [number] : [];
  } else if (event === "merge_group") {
    pullRequests = await mergeGroupPullRequests({
      github,
      repository: process.env.GITHUB_REPOSITORY,
      baseSha: process.env.APPROVAL_BASE_SHA,
      headSha: process.env.APPROVAL_HEAD_SHA,
    });
  }
} catch (error) {
  // The comparison still runs; with no pull request named, no content-bound approval can apply.
  console.log(`::warning::Could not resolve the pull requests in this merge group: ${error.message}`);
  pullRequests = [];
}

const line = `pull_requests=${pullRequests.join(" ")}`;
console.log(line);
if (process.env.GITHUB_OUTPUT) await appendFile(process.env.GITHUB_OUTPUT, `${line}\n`);
