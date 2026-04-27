import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const EXPECTED_CONTRACT_VERSION = "1";
const REQUIRED_FLAGS = ["--data-dir", "--output", "--trust-label", "--visibility"];
const EXPECTED_COMMAND = "benchbox explorer build";

const here = fileURLToPath(new URL(".", import.meta.url));
const repoRoot = resolve(here, "..", "..");

function formatSpawnError(result) {
  const stderr = result.stderr?.trim();
  return stderr ? `\n${stderr}` : "";
}

export function readExplorerBuildContract() {
  const result = spawnSync("uv", ["run", "--", "benchbox", "explorer", "build-contract"], {
    cwd: repoRoot,
    encoding: "utf8",
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
  });

  if (result.status !== 0) {
    throw new Error(
      "Could not read the explorer build contract from benchbox/cli/commands/explorer.py. " +
        `uv exited ${result.status ?? "unknown"}.${formatSpawnError(result)}`,
    );
  }

  let contract;
  try {
    contract = JSON.parse(result.stdout.trim());
  } catch (error) {
    throw new Error(
      "Explorer build contract was not valid JSON. " +
        "Update benchbox/cli/commands/explorer.py or results-explorer/scripts/explorer-build-contract.mjs.\n" +
        String(error),
    );
  }

  if (contract.version !== EXPECTED_CONTRACT_VERSION) {
    throw new Error(
      `Explorer build contract version ${EXPECTED_CONTRACT_VERSION} expected, got ${contract.version}. ` +
        "Update results-explorer/scripts/explorer-build-contract.mjs or benchbox/cli/commands/explorer.py to re-align.",
    );
  }

  if (contract.command !== EXPECTED_COMMAND) {
    throw new Error(
      `Explorer build contract command ${EXPECTED_COMMAND} expected, got ${contract.command}. ` +
        "Update results-explorer/scripts/explorer-build-contract.mjs or benchbox/cli/commands/explorer.py to re-align.",
    );
  }

  const actualFlags = new Set(contract.flags ?? []);
  for (const flag of REQUIRED_FLAGS) {
    if (!actualFlags.has(flag)) {
      throw new Error(
        `Explorer build contract missing required flag ${flag}. ` +
          "Update results-explorer/scripts/explorer-build-contract.mjs or benchbox/cli/commands/explorer.py to re-align.",
      );
    }
  }

  return {
    ...contract,
    commandArgs: contract.command.split(/\s+/),
  };
}
