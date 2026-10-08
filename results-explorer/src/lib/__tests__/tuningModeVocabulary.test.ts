import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const repoRoot = resolve(process.cwd(), "..");
const VOCAB_RELATIVE_PATH = "tests/unit/core/tuning/fixtures/tuning_mode_vocabulary.yaml";

const EXPECTED_MODES = ["tuned", "tuned-fallback", "notuning", "auto", "custom"];
const EXPECTED_NOT_RECORDED_SENTINEL = "not-recorded";

interface VocabularyArtifact {
  modes: string[];
  not_recorded_sentinel: string;
}

function loadVocabularyArtifact(): VocabularyArtifact {
  const result = spawnSync(
    "uv",
    [
      "run",
      "--",
      "python",
      "-c",
      `import json, yaml; print(json.dumps(yaml.safe_load(open("${VOCAB_RELATIVE_PATH}"))))`,
    ],
    { cwd: repoRoot, encoding: "utf8" },
  );

  if (result.status !== 0) {
    throw new Error(
      `Failed to load shared tuning_mode vocabulary artifact at ${VOCAB_RELATIVE_PATH}: ${result.stderr}`,
    );
  }

  return JSON.parse(result.stdout) as VocabularyArtifact;
}

describe("tuning_mode vocabulary pin (ADR-2)", () => {
  it("shared artifact modes match the ADR-2 decided set", () => {
    const vocab = loadVocabularyArtifact();
    expect(vocab.modes).toEqual(EXPECTED_MODES);
  });

  it("shared artifact not-recorded sentinel matches ADR-2", () => {
    const vocab = loadVocabularyArtifact();
    expect(vocab.not_recorded_sentinel).toBe(EXPECTED_NOT_RECORDED_SENTINEL);
  });

  it("no artifact mode value looks like a raw file path", () => {
    const vocab = loadVocabularyArtifact();
    for (const mode of vocab.modes) {
      expect(mode.includes("/")).toBe(false);
      expect(mode.includes("\\")).toBe(false);
      expect(mode.endsWith(".yaml")).toBe(false);
    }
  });

  it("'balanced' is not part of the pinned vocabulary", () => {
    const vocab = loadVocabularyArtifact();
    expect(vocab.modes).not.toContain("balanced");
  });
});
