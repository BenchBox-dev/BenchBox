#!/usr/bin/env node

import { readExplorerBuildContract } from "./explorer-build-contract.mjs";

function fail(message) {
  console.error(`[validate-explorer-build-contract] ${message}`);
  process.exit(1);
}

try {
  const contract = readExplorerBuildContract();
  console.log("[validate-explorer-build-contract] OK", JSON.stringify(contract));
} catch (error) {
  fail(error instanceof Error ? error.message : String(error));
}
