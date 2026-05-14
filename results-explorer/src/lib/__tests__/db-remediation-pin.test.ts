import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const EXPECTED_EXPLORER_BUILD_COMMAND =
  "uv run -- python _project/scripts/explorer_publish.py build";
const repoRoot = resolve(process.cwd(), "..");

describe("db remediation command pin", () => {
  it("matches the live explorer build contract", () => {
    const result = spawnSync(
      "uv",
      ["run", "--", "python", "_project/scripts/explorer_publish.py", "build-contract"],
      {
        cwd: repoRoot,
        encoding: "utf8",
        env: { ...process.env, PYTHONUNBUFFERED: "1" },
      },
    );

    expect(result.status, result.stderr).toBe(0);
    const contract = JSON.parse(result.stdout) as { command?: string };
    expect(contract.command).toBe(EXPECTED_EXPLORER_BUILD_COMMAND);
  });
});
