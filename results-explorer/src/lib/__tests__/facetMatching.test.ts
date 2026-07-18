/**
 * Tests for facetMatching tuning-mode semantics.
 *
 * Rows whose bundle never recorded a tuning mode (tuning_mode null/undefined)
 * are an explicit "not-recorded" state:
 *   (a) they never match a real-mode selection,
 *   (b) they match a selection that explicitly includes the not-recorded
 *       sentinel (or the legacy "untuned" token still used by chips/URLs),
 *   (c) real modes keep matching exactly as before (rule changes are gated
 *       on ADR-2 and owned by the facet implementation TODO).
 */

import { describe, expect, it } from "vitest";
import {
  LEGACY_UNLABELLED_TUNING_MODE,
  NOT_RECORDED_TUNING_MODE,
  matchesFacetRow,
  physicalRenderingIdsMatch,
  type FacetMatchRow,
} from "@/lib/facetMatching";
import { DEFAULT_FACETS, type FacetState } from "@/lib/facetModel";

function facets(tuningMode: string[]): FacetState {
  return { ...DEFAULT_FACETS, tuning_mode: tuningMode };
}

const TUNING_ONLY = { keys: ["tuning_mode"] as const };

function row(tuningMode: string | null | undefined): FacetMatchRow {
  return { tuning_mode: tuningMode };
}

describe("facetMatching tuning_mode", () => {
  it("empty selection matches every row, including not-recorded", () => {
    expect(matchesFacetRow(row("tuned"), facets([]), TUNING_ONLY)).toBe(true);
    expect(matchesFacetRow(row(null), facets([]), TUNING_ONLY)).toBe(true);
    expect(matchesFacetRow(row(undefined), facets([]), TUNING_ONLY)).toBe(true);
  });

  it("real modes match their own selection", () => {
    expect(matchesFacetRow(row("tuned"), facets(["tuned"]), TUNING_ONLY)).toBe(true);
    expect(matchesFacetRow(row("auto"), facets(["tuned"]), TUNING_ONLY)).toBe(false);
    expect(matchesFacetRow(row("notuning"), facets(["notuning", "auto"]), TUNING_ONLY)).toBe(true);
  });

  it("a not-recorded row never matches a real-mode selection", () => {
    for (const selection of [["tuned"], ["notuning"], ["auto"], ["tuned", "auto"]]) {
      expect(matchesFacetRow(row(null), facets(selection), TUNING_ONLY)).toBe(false);
      expect(matchesFacetRow(row(undefined), facets(selection), TUNING_ONLY)).toBe(false);
    }
  });

  it("a not-recorded row matches an explicit not-recorded selection", () => {
    expect(matchesFacetRow(row(null), facets([NOT_RECORDED_TUNING_MODE]), TUNING_ONLY)).toBe(true);
    expect(matchesFacetRow(row(undefined), facets([NOT_RECORDED_TUNING_MODE]), TUNING_ONLY)).toBe(true);
  });

  it("the legacy 'untuned' token still selects not-recorded rows (chips/URLs)", () => {
    expect(matchesFacetRow(row(null), facets([LEGACY_UNLABELLED_TUNING_MODE]), TUNING_ONLY)).toBe(true);
    expect(matchesFacetRow(row(undefined), facets([LEGACY_UNLABELLED_TUNING_MODE]), TUNING_ONLY)).toBe(true);
  });

  it("a recorded mode does not match the not-recorded sentinel selection", () => {
    expect(matchesFacetRow(row("tuned"), facets([NOT_RECORDED_TUNING_MODE]), TUNING_ONLY)).toBe(false);
    expect(matchesFacetRow(row("tuned"), facets([LEGACY_UNLABELLED_TUNING_MODE]), TUNING_ONLY)).toBe(false);
  });

  it("no producer emits the sentinel as a real mode, but if a row carried it verbatim it would match itself", () => {
    expect(matchesFacetRow(row(NOT_RECORDED_TUNING_MODE), facets([NOT_RECORDED_TUNING_MODE]), TUNING_ONLY)).toBe(true);
  });

  it("tuned-fallback (ADR-2) is an exact-match value like any other -- it never matches 'tuned'", () => {
    expect(matchesFacetRow(row("tuned-fallback"), facets(["tuned-fallback"]), TUNING_ONLY)).toBe(true);
    expect(matchesFacetRow(row("tuned-fallback"), facets(["tuned"]), TUNING_ONLY)).toBe(false);
    expect(matchesFacetRow(row("tuned"), facets(["tuned-fallback"]), TUNING_ONLY)).toBe(false);
  });

  it("custom (ADR-2) is an exact-match value like any other", () => {
    expect(matchesFacetRow(row("custom"), facets(["custom"]), TUNING_ONLY)).toBe(true);
    expect(matchesFacetRow(row("custom"), facets(["tuned"]), TUNING_ONLY)).toBe(false);
  });
});

describe("physicalRenderingIdsMatch (ADR-2 §3 secondary facet)", () => {
  it("matches when both rows share the same physical_rendering_id", () => {
    expect(
      physicalRenderingIdsMatch({ physical_rendering_id: "databricks_z_order" }, { physical_rendering_id: "databricks_z_order" }),
    ).toBe(true);
  });

  it("does not match when both rows have the field but it differs", () => {
    expect(
      physicalRenderingIdsMatch(
        { physical_rendering_id: "databricks_z_order" },
        { physical_rendering_id: "databricks_liquid_auto" },
      ),
    ).toBe(false);
  });

  it("is not part of the match when either side is absent (null, undefined, or missing)", () => {
    expect(physicalRenderingIdsMatch({ physical_rendering_id: "databricks_z_order" }, { physical_rendering_id: null })).toBe(
      true,
    );
    expect(
      physicalRenderingIdsMatch({ physical_rendering_id: "databricks_z_order" }, { physical_rendering_id: undefined }),
    ).toBe(true);
    expect(physicalRenderingIdsMatch({ physical_rendering_id: "databricks_z_order" }, {})).toBe(true);
    expect(physicalRenderingIdsMatch(null, { physical_rendering_id: "databricks_z_order" })).toBe(true);
    expect(physicalRenderingIdsMatch(undefined, undefined)).toBe(true);
  });
});
