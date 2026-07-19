/**
 * Shared Python<->TypeScript `tuning_mode` vocabulary pin (ADR-2).
 *
 * docs/development/tuning-adr-002-mode-vocabulary-fallback-facets.md §2 pins
 * the canonical tuning_mode value set as exactly {tuned, tuned-fallback,
 * notuning, auto, custom} plus a distinct "not recorded" state for
 * absent/legacy data, and requires this be "defined once in a single shared
 * artifact consumed by both the Python and TypeScript test suites, so the
 * two sides cannot drift independently again".
 *
 * The shared artifact is tests/unit/core/tuning/fixtures/tuning_mode_vocabulary.yaml
 * (kept out of a `data/` directory since the repo .gitignore blanket-ignores
 * those; Python side: tests/unit/core/tuning/test_tuning_mode_vocabulary.py). This
 * test loads that *same* file via a `uv run -- python -c` subprocess -- the
 * shell-out pattern already established by db-remediation-pin.test.ts --
 * rather than hardcoding a separate TS mirror of the vocabulary, so there is
 * exactly one place it's declared.
 *
 * This pins the ADR-2 TARGET vocabulary as a test contract. It intentionally
 * does NOT assert that TuningBadge.tsx (TUNING_CONFIG) or facetMatching.ts
 * already consume the full five-value set -- they don't yet; migrating them
 * is tuning-mode-vocabulary-and-facet-implementation-20260712, a separate,
 * unstarted TODO. This test only proves the artifact and this test file
 * agree with the ADR-2 decision, so a future edit to either one is caught.
 */
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const repoRoot = resolve(process.cwd(), "..");
const VOCAB_RELATIVE_PATH = "tests/unit/core/tuning/fixtures/tuning_mode_vocabulary.yaml";

// ADR-2 §2's decided vocabulary, in the order the ADR lists it.
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
    // ADR-2 §2: "Raw file paths are not a legal tuning_mode value under any
    // circumstance."
    const vocab = loadVocabularyArtifact();
    for (const mode of vocab.modes) {
      expect(mode.includes("/")).toBe(false);
      expect(mode.includes("\\")).toBe(false);
      expect(mode.endsWith(".yaml")).toBe(false);
    }
  });

  it("'balanced' is not part of the pinned vocabulary", () => {
    // ADR-2 §2: the wizard's "balanced" string is a template flavor
    // selector, not a tuning_mode value.
    const vocab = loadVocabularyArtifact();
    expect(vocab.modes).not.toContain("balanced");
  });
});
