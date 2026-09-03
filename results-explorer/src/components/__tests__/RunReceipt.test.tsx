import { fireEvent, render, screen, within } from "@testing-library/preact";
import { describe, expect, it } from "vitest";
import type { DetailResult } from "@/types";
import { RunReceipt, planDownloadUrl } from "@/components/RunReceipt";

function makeDetail(overrides: Partial<DetailResult> = {}): DetailResult {
  return {
    result_id: "abcdef1234567890",
    benchmark: "tpch",
    scale_factor: 0.1,
    platform: "DuckDB",
    platform_id: "duckdb",
    driver_version: "1.2.0",
    run_date: "2026-04-01",
    total_duration_s: 60,
    geomean_ms: 15,
    display_geomean_ms: 12,
    power_score: 3000,
    has_display_timing: true,
    valid_query_count: 2,
    missing_query_count: 0,
    zero_timing_count: 0,
    display_exclusion_reason: null,
    comparison_exclusion_reason: null,
    ranking_exclusion_reason: null,
    environment: {
      os: "macOS",
      arch: "arm64",
      cpu_family: "apple_silicon",
      cpu_model: "Apple M1 Max",
      cpu_identity_provenance: "measured",
      cpu_count: 10,
      memory_gb: 64,
      python: "3.12.4",
    },
    queries: [
      { query_id: "Q1", duration_ms: 10, status: "pass", run_type: "measurement", iter: 1, stream: null },
      { query_id: "Q1", duration_ms: 12, status: "pass", run_type: "measurement", iter: 2, stream: null },
      { query_id: "Q2", duration_ms: 20, status: "pass", run_type: "measurement", iter: 1, stream: null },
      { query_id: "Q2", duration_ms: 22, status: "pass", run_type: "measurement", iter: 2, stream: null },
      { query_id: "Q2", duration_ms: 24, status: "pass", run_type: "measurement", iter: 3, stream: null },
    ],
    display_timings: [
      { query_id: "Q1", display_ms: 11, sample_count: 2, is_valid_display_timing: true, timing_exclusion_reason: null },
      { query_id: "Q2", display_ms: 22, sample_count: 3, is_valid_display_timing: true, timing_exclusion_reason: null },
    ],
    has_plans: false,
    has_tuning: true,
    bundle_download_url: "https://example.test/bundles/abcdef1234567890.json",
    trust_label: "maintainer-run",
    visibility: "public-curated",
    funding: "unspecified",
    platform_version: "1.2.0",
    execution_mode: "sql",
    tuning_mode: "tuned",
    tuning_hash: "tuning123",
    requested_config_hash: "a".repeat(64),
    applied_ledger_hash: "b".repeat(64),
    tuning_validation_status: "applied_verified",
    test_type: "power",
    validation_status: "exact",
    cost_usd: null,
    normalized_cost_usd: null,
    cost_model_version: "2026.05.0",
    cost_model_source: "benchbox.core.cost.pricing",
    cost_scope: "compute_only",
    cost_status: "unavailable",
    billing_unit: "unknown",
    pricing_region: "unknown",
    compliance_class: "unofficial_subscale",
    ...overrides,
  };
}

describe("RunReceipt", () => {
  it("renders compact workload, platform, environment, integrity, artifact, and cost sections", () => {
    render(
      <RunReceipt
        detail={makeDetail()}
        shortId="abc12345"
        isRankingEligible={true}
      />,
    );

    const receipt = screen.getByRole("region", { name: "Run receipt" });
    for (const section of ["Workload", "Platform", "Environment", "Integrity", "Artifacts", "Cost"]) {
      expect(within(receipt).getByRole("heading", { name: section })).toBeTruthy();
    }

    expect(within(receipt).getByText("TPC-H")).toBeTruthy();
    expect(within(receipt).getByText("SF 0.1")).toBeTruthy();
    expect(within(receipt).getByText("power")).toBeTruthy();
    expect(within(receipt).getByText("DuckDB")).toBeTruthy();
    expect(within(receipt).getByText("macOS")).toBeTruthy();
    expect(within(receipt).getByText("Trust")).toBeTruthy();
    // `results-explorer-result-detail-metadata-density` w4 wires
    // RunReceipt onto the shared display-label formatters so the
    // hyphenated source slug renders as a humanized label here too.
    expect(within(receipt).getByText("maintainer run")).toBeTruthy();
    expect(within(receipt).getByText("public (curated)")).toBeTruthy();
    expect(within(receipt).getByText("exact")).toBeTruthy();
    // Funding is recorded on the receipt even when undisclosed. The chip is
    // omitted for "unspecified"; the receipt states it.
    expect(within(receipt).getByText("Funding")).toBeTruthy();
    expect(within(receipt).getByText("unspecified")).toBeTruthy();
    expect(within(receipt).getByText("Eligible")).toBeTruthy();
    expect(within(receipt).getByText("abc12345")).toBeTruthy();
    expect(within(receipt).getByText("Plans not published")).toBeTruthy();
    expect(within(receipt).getByText("unavailable")).toBeTruthy();
    expect(within(receipt).getByText("2026.05.0 (benchbox.core.cost.pricing)")).toBeTruthy();
    // Sentinel "unknown" for billing/region is suppressed (finding #12);
    // only the cost scope renders.
    expect(within(receipt).getByText("compute only")).toBeTruthy();
  });

  it("renders normalized cost metadata when it is present", () => {
    render(
      <RunReceipt
        detail={makeDetail({
          normalized_cost_usd: 0.42,
          cost_status: "normalized",
          billing_unit: "warehouse_hour",
          pricing_region: "us-east-1",
        })}
      />,
    );

    const receipt = screen.getByRole("region", { name: "Run receipt" });
    expect(within(receipt).getByText("$0.42")).toBeTruthy();
    expect(within(receipt).getByText("compute only, billing: warehouse hour, region: us-east-1")).toBeTruthy();
  });

  it("does not leak raw not_applicable enum into the Cost section copy (finding #12)", () => {
    render(
      <RunReceipt
        detail={makeDetail({
          cost_status: "not_applicable_local",
          cost_scope: "compute_only",
          billing_unit: "not_applicable",
          pricing_region: "not_applicable",
        })}
      />,
    );

    const receipt = screen.getByRole("region", { name: "Run receipt" });
    expect(within(receipt).getByText("compute only")).toBeTruthy();
    expect(receipt.textContent ?? "").not.toMatch(/not_applicable/);
    expect(receipt.textContent ?? "").not.toMatch(/billing: not applicable/);
    expect(receipt.textContent ?? "").not.toMatch(/region: not applicable/);
  });

  it("counts placeholder cost summaries as missing receipt metadata", () => {
    render(
      <RunReceipt
        detail={makeDetail({
          cost_model_version: null,
          cost_model_source: null,
          cost_scope: null,
          billing_unit: null,
          pricing_region: null,
        })}
        shortId="abc12345"
        isRankingEligible={true}
      />,
    );

    const receipt = screen.getByRole("region", { name: "Run receipt" });
    const cost = within(receipt).getByRole("heading", { name: "Cost" }).closest("section");
    expect(cost).not.toBeNull();
    const costSection = within(cost as HTMLElement);

    expect(within(receipt).getByText("2 fields not recorded for this run.")).toBeTruthy();
    expect(within(receipt).getAllByText(/\d+ fields? not recorded/)).toHaveLength(1);
    expect(costSection.queryByText("Cost model")).toBeNull();
    expect(costSection.queryByText("Cost scope")).toBeNull();
    expect(costSection.getByText("unavailable")).toBeTruthy();

    fireEvent.click(within(receipt).getByRole("button", { name: /Show missing metadata/ }));
    expect(costSection.getByText("Cost model")).toBeTruthy();
    expect(costSection.getByText("Cost scope")).toBeTruthy();
    expect(costSection.getAllByText("Not recorded")).toHaveLength(2);
  });

  it("keeps logical query count separate from measurement samples", () => {
    render(<RunReceipt detail={makeDetail()} />);

    const receipt = screen.getByRole("region", { name: "Run receipt" });
    const workload = within(receipt).getByRole("heading", { name: "Workload" }).closest("section");
    expect(workload).not.toBeNull();
    expect(workload).toHaveTextContent("Query count");
    expect(workload).toHaveTextContent("2");
    expect(workload).toHaveTextContent("Measurement samples");
    expect(workload).toHaveTextContent("5");
  });

  it("renders bundle and reproduce artifacts; only shows a Download plans link when plans are actually published", () => {
    render(<RunReceipt detail={makeDetail({ has_plans: true, plans_published: true })} />);

    const receipt = screen.getByRole("region", { name: "Run receipt" });
    expect(within(receipt).getByRole("link", { name: "Download bundle" })).toHaveAttribute(
      "href",
      "https://example.test/bundles/abcdef1234567890.json",
    );
    expect(within(receipt).getByRole("link", { name: "Download plans" })).toHaveAttribute(
      "href",
      "https://example.test/bundles/abcdef1234567890.plans.json",
    );
    expect(within(receipt).getByText("benchbox run --platform duckdb --benchmark tpch --scale 0.1 --phases power"))
      .toBeTruthy();
  });

  it("does NOT render a Download plans link when has_plans is true but plans were not published (w1 regression)", () => {
    render(<RunReceipt detail={makeDetail({ has_plans: true })} />);

    const receipt = screen.getByRole("region", { name: "Run receipt" });
    // Download bundle link must still render — only the plans link is gated.
    expect(within(receipt).getByRole("link", { name: "Download bundle" })).toBeTruthy();
    expect(within(receipt).queryByRole("link", { name: "Download plans" })).toBeNull();
    // The non-link "Plans available" fallback string is shown instead.
    expect(within(receipt).getByText("Plans available")).toBeTruthy();
  });

  it("hides missing metadata behind the Show missing metadata disclosure (w3)", () => {
    // Sparse-metadata fixture: trust + visibility recorded, the entire
    // Platform/Environment surface unrecorded, validation/compliance
    // missing, no normalized cost. The default view should expose
    // recorded fields plus one aggregate missing-metadata count;
    // clicking the global disclosure reveals the actual
    // Not-recorded rows so audit users can still see them.
    render(
      <RunReceipt
        detail={makeDetail({
          platform_version: null,
          driver_version: null,
          execution_mode: null,
          tuning_mode: null,
          tuning_hash: null,
          environment: {
            os: undefined,
            arch: undefined,
            cpu_family: undefined,
            cpu_model: undefined,
            cpu_count: undefined,
            memory_gb: undefined,
            python: undefined,
          },
          test_type: null,
          validation_status: null,
          compliance_class: null,
          has_tuning: false,
        })}
      />,
    );

    const receipt = screen.getByRole("region", { name: "Run receipt" });
    // Recorded fields (Benchmark, Scale, Platform name, Trust, Visibility)
    // remain visible without expanding the disclosure.
    expect(within(receipt).getByText("TPC-H")).toBeTruthy();
    expect(within(receipt).getByText("DuckDB")).toBeTruthy();
    expect(within(receipt).getByText("maintainer run")).toBeTruthy();
    expect(within(receipt).getByText("public (curated)")).toBeTruthy();

    // Missing rows are NOT in the default DOM.
    expect(within(receipt).queryByText("Platform version")).toBeNull();
    expect(within(receipt).queryByText("Driver version")).toBeNull();
    expect(within(receipt).queryByText("OS")).toBeNull();
    expect(within(receipt).queryByText("Validation")).toBeNull();
    // One aggregate count replaces the repeated per-section counters.
    expect(within(receipt).getAllByText(/\d+ fields? not recorded/)).toHaveLength(1);

    // Click the global disclosure — every previously-hidden field
    // becomes visible.
    const toggle = within(receipt).getByRole("button", { name: /Show missing metadata/ });
    fireEvent.click(toggle);
    expect(within(receipt).getByText("Platform version")).toBeTruthy();
    expect(within(receipt).getByText("OS")).toBeTruthy();
    expect(within(receipt).getByText("Validation")).toBeTruthy();
    expect(within(receipt).getAllByText("Not recorded").length).toBeGreaterThan(0);

    // The button copy flips and the disclosure round-trips.
    const hideToggle = within(receipt).getByRole("button", { name: /Hide missing metadata/ });
    fireEvent.click(hideToggle);
    expect(within(receipt).queryByText("Platform version")).toBeNull();
  });

  it("does not render the missing-metadata disclosure when every field is recorded (w3)", () => {
    render(
      <RunReceipt
        detail={makeDetail({ plans_published: true })}
        shortId="abc12345"
        isRankingEligible={true}
      />,
    );

    const receipt = screen.getByRole("region", { name: "Run receipt" });
    // No "Show missing metadata" toggle, no per-section "N field(s)
    // not recorded" footer when every row is populated.
    expect(within(receipt).queryByRole("button", { name: /Show missing metadata/ })).toBeNull();
    expect(within(receipt).queryByText(/\d+ fields? not recorded/)).toBeNull();
  });

  it("derives the plans companion URL only when publication is signaled (w1 regression)", () => {
    // Pre-w1 behavior gated only on has_plans; the URL would resolve to a
    // 404 for every published bundle because the explorer pipeline excludes
    // *.plans.json from bundle discovery. Post-w1, the link only renders
    // when plans_published is explicitly true.
    expect(planDownloadUrl(makeDetail({ has_plans: true, plans_published: true }))).toBe(
      "https://example.test/bundles/abcdef1234567890.plans.json",
    );
    expect(planDownloadUrl(makeDetail({ has_plans: true }))).toBeNull();
    expect(planDownloadUrl(makeDetail({ has_plans: true, plans_published: false }))).toBeNull();
    expect(planDownloadUrl(makeDetail({ has_plans: false, plans_published: true }))).toBeNull();
    expect(
      planDownloadUrl(
        makeDetail({ has_plans: true, plans_published: true, bundle_download_url: "" }),
      ),
    ).toBeNull();
  });

  it("humanizes a disclosed funding source on the receipt", () => {
    render(<RunReceipt detail={makeDetail({ funding: "vendor-sponsored" })} />);
    expect(screen.getByText("vendor sponsored")).toBeTruthy();
  });

  it("renders the ADR-1 requested-config and applied-ledger hashes as monospace fingerprints", () => {
    const requested = "a".repeat(64);
    const applied = "b".repeat(64);
    render(<RunReceipt detail={makeDetail({ requested_config_hash: requested, applied_ledger_hash: applied })} />);

    const receipt = screen.getByRole("region", { name: "Run receipt" });
    expect(within(receipt).getByText("Requested config hash")).toBeTruthy();
    expect(within(receipt).getByText("Applied ledger hash")).toBeTruthy();
    // Each renders a monospace <code> with the SHORT prefix visible and the
    // FULL hash preserved in the title tooltip (identity kept, receipt compact).
    const requestedCode = receipt.querySelector(`code[title="${requested}"]`);
    const appliedCode = receipt.querySelector(`code[title="${applied}"]`);
    expect(requestedCode).not.toBeNull();
    expect(appliedCode).not.toBeNull();
    expect(requestedCode?.textContent).toBe("aaaaaaaaaaaa");
    expect(appliedCode?.textContent).toBe("bbbbbbbbbbbb");
  });

  it("does NOT dress the self-derived tuning_hash up as an identity fingerprint", () => {
    // The mode-only `tuning_hash` is a coarse self-derived value, not an
    // ADR-1 bundle identity, so it renders as a plain labeled string rather
    // than a monospace hash fingerprint (no title-tooltip <code>).
    render(<RunReceipt detail={makeDetail({ tuning_hash: "tuning123" })} />);

    const receipt = screen.getByRole("region", { name: "Run receipt" });
    expect(within(receipt).getByText("Tuning hash")).toBeTruthy();
    expect(within(receipt).getByText("tuning123")).toBeTruthy();
    // It must NOT be wrapped in the identity-hash <code title=...> fingerprint.
    expect(receipt.querySelector('code[title="tuning123"]')).toBeNull();
  });

  it("marks missing ADR-1 hashes as not-recorded rather than fabricating a fingerprint", () => {
    render(<RunReceipt detail={makeDetail({ requested_config_hash: null, applied_ledger_hash: null })} />);

    const receipt = screen.getByRole("region", { name: "Run receipt" });
    // Missing hash rows are hidden behind the disclosure, not rendered as a hash.
    expect(within(receipt).queryByText("Requested config hash")).toBeNull();
    expect(within(receipt).queryByText("Applied ledger hash")).toBeNull();
    fireEvent.click(within(receipt).getByRole("button", { name: /Show missing metadata/ }));
    expect(within(receipt).getByText("Requested config hash")).toBeTruthy();
    expect(within(receipt).getByText("Applied ledger hash")).toBeTruthy();
    expect(within(receipt).getAllByText("Not recorded").length).toBeGreaterThan(0);
  });

  it("renders the ADR-1 tuning verified-state as a verification badge", () => {
    render(<RunReceipt detail={makeDetail({ tuning_validation_status: "applied_verified" })} />);

    const receipt = screen.getByRole("region", { name: "Run receipt" });
    expect(within(receipt).getByText("Tuning verification")).toBeTruthy();
    expect(within(receipt).getByText("Verified")).toBeTruthy();
  });

  it("labels a self-attested (applied_unverified) run distinctly from a verified one", () => {
    render(<RunReceipt detail={makeDetail({ tuning_validation_status: "applied_unverified" })} />);

    const receipt = screen.getByRole("region", { name: "Run receipt" });
    expect(within(receipt).getByText("Applied (self-attested)")).toBeTruthy();
    expect(within(receipt).queryByText("Verified")).toBeNull();
  });

  it("marks an unrecorded tuning verification state as not-recorded, not verified", () => {
    render(<RunReceipt detail={makeDetail({ tuning_validation_status: null })} />);

    const receipt = screen.getByRole("region", { name: "Run receipt" });
    // Legacy bundles: the row is hidden behind the disclosure, never shown as verified.
    expect(within(receipt).queryByText("Tuning verification")).toBeNull();
    expect(within(receipt).queryByText("Verified")).toBeNull();
    fireEvent.click(within(receipt).getByRole("button", { name: /Show missing metadata/ }));
    expect(within(receipt).getByText("Tuning verification")).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// ADR-1 applied-tuning receipt drill-down
//
// `applied_receipt` carries the `{stem}.applied.json` companion's `receipt`
// sub-object verbatim. The drill-down displays what the platform recorded; it
// never recomputes a verdict or a corroboration decision. Every degraded shape
// must leave the existing verified-state row exactly as it renders today.
// ---------------------------------------------------------------------------

const APPLIED_RECEIPT = JSON.stringify({
  platform: "duckdb",
  corroborated: true,
  summary: { corroborated: 1, divergent: 1 },
  entries: [
    {
      statement: "CREATE INDEX idx_l_shipdate ON lineitem(l_shipdate)",
      phase: "post_load",
      verdict: "corroborated",
      kind: "index",
      table: "lineitem",
      expected_columns: ["l_shipdate"],
      observed_columns: ["l_shipdate"],
      diff: null,
      reason: null,
      detail: "catalog introspection completed",
    },
    {
      statement: "CREATE INDEX idx_o_orderdate ON orders(o_orderdate)",
      phase: "post_load",
      verdict: "divergent",
      kind: "index",
      table: "orders",
      expected_columns: ["o_orderdate"],
      observed_columns: ["o_custkey"],
      diff: "column mismatch",
      reason: "catalog reports a different index definition",
    },
  ],
});

function expectVerifiedRowIntact() {
  const receipt = screen.getByRole("region", { name: "Run receipt" });
  expect(within(receipt).getByText("Tuning verification")).toBeTruthy();
  expect(within(receipt).getByText("Verified")).toBeTruthy();
  return receipt;
}

describe("RunReceipt applied-tuning receipt drill-down", () => {
  it("renders one collapsed drill-down entry per receipt entry, verbatim", () => {
    render(<RunReceipt detail={makeDetail({ applied_receipt: APPLIED_RECEIPT })} />);

    const receipt = expectVerifiedRowIntact();
    const drilldown = within(receipt).getByTestId("applied-receipt-drilldown");
    // Native <details>: collapsed by default, so the summary is the only
    // thing competing for space in the receipt grid.
    expect((drilldown as HTMLDetailsElement).open).toBe(false);
    expect(within(drilldown).getByText(/Receipt entries \(2\)/)).toBeTruthy();

    const entries = within(drilldown).getAllByTestId("applied-receipt-entry");
    expect(entries.length).toBe(2);
    const [corroborated, divergent] = entries as [HTMLElement, HTMLElement];

    // Verdicts are shown as recorded - never recomputed from the columns.
    expect(within(corroborated).getByText("corroborated")).toBeTruthy();
    expect(within(corroborated).getByText(/CREATE INDEX idx_l_shipdate/)).toBeTruthy();
    expect(within(corroborated).getByText("lineitem")).toBeTruthy();
    expect(within(corroborated).getByText("Detail")).toBeTruthy();
    expect(within(corroborated).getByText("catalog introspection completed")).toBeTruthy();

    expect(within(divergent).getByText("divergent")).toBeTruthy();
    expect(within(divergent).getByText("Expected columns")).toBeTruthy();
    expect(within(divergent).getByText("o_orderdate")).toBeTruthy();
    expect(within(divergent).getByText("Observed columns")).toBeTruthy();
    expect(within(divergent).getByText("o_custkey")).toBeTruthy();
    expect(within(divergent).getByText("column mismatch")).toBeTruthy();
    expect(within(divergent).getByText("catalog reports a different index definition")).toBeTruthy();
  });

  it("omits fields the receipt did not record rather than inventing them", () => {
    const sparse = JSON.stringify({ entries: [{ verdict: "corroborated" }] });
    render(<RunReceipt detail={makeDetail({ applied_receipt: sparse })} />);

    const drilldown = screen.getByTestId("applied-receipt-drilldown");
    expect(within(drilldown).getByText("corroborated")).toBeTruthy();
    expect(within(drilldown).queryByText("Expected columns")).toBeNull();
    expect(within(drilldown).queryByText("Reason")).toBeNull();
    expect(within(drilldown).queryByText("Table")).toBeNull();
  });

  it("labels defensive truncation loudly and preserves the original entry count", () => {
    const truncated = JSON.stringify({
      entries: [{ verdict: "corroborated" }],
      truncated: true,
      original_entry_count: 25001,
    });
    render(<RunReceipt detail={makeDetail({ applied_receipt: truncated })} />);

    const drilldown = screen.getByTestId("applied-receipt-drilldown");
    expect(within(drilldown).getByText("Receipt entries (1 of 25001; truncated)")).toBeTruthy();
    expect(within(drilldown).getByText(/exceeded the defensive receipt bound/)).toBeTruthy();
  });

  it.each([
    ["absent (undefined)", undefined],
    ["explicitly null", null],
    ["an empty string", ""],
    ["unparsable JSON", '{"entries": ['],
    ["valid JSON that is not an object", "[1, 2, 3]"],
    ["a receipt with no entries key", JSON.stringify({ platform: "duckdb", corroborated: true })],
    ["a receipt with an empty entries list", JSON.stringify({ platform: "duckdb", entries: [] })],
    ["a receipt whose entries are not objects", JSON.stringify({ entries: ["nope", 7, null] })],
  ])("renders no drill-down and no error when applied_receipt is %s", (_label, raw) => {
    render(<RunReceipt detail={makeDetail({ applied_receipt: raw as string | null | undefined })} />);

    // The verified-state row and badge render exactly as they do without a receipt.
    const receipt = expectVerifiedRowIntact();
    expect(within(receipt).queryByTestId("applied-receipt-drilldown")).toBeNull();
    expect(within(receipt).queryByTestId("applied-receipt-entry")).toBeNull();
    expect(within(receipt).queryByText(/Receipt entries/)).toBeNull();
  });

  it("leaves a self-attested run's badge untouched when a receipt is present", () => {
    render(
      <RunReceipt
        detail={makeDetail({ tuning_validation_status: "applied_unverified", applied_receipt: APPLIED_RECEIPT })}
      />,
    );

    const receipt = screen.getByRole("region", { name: "Run receipt" });
    // The drill-down never upgrades the badge - corroboration is not decided here.
    expect(within(receipt).getByText("Applied (self-attested)")).toBeTruthy();
    expect(within(receipt).queryByText("Verified")).toBeNull();
    expect(within(receipt).getByTestId("applied-receipt-drilldown")).toBeTruthy();
  });

  it("keeps the legacy not-recorded row unchanged when no verified-state exists", () => {
    render(<RunReceipt detail={makeDetail({ tuning_validation_status: null, applied_receipt: APPLIED_RECEIPT })} />);

    const receipt = screen.getByRole("region", { name: "Run receipt" });
    expect(within(receipt).queryByText("Tuning verification")).toBeNull();
    expect(within(receipt).queryByTestId("applied-receipt-drilldown")).toBeNull();
    fireEvent.click(within(receipt).getByRole("button", { name: /Show missing metadata/ }));
    expect(within(receipt).getByText("Tuning verification")).toBeTruthy();
    expect(within(receipt).getAllByText("Not recorded").length).toBeGreaterThan(0);
  });

  it("renders CPU family and CPU model when recorded, and hides them when missing", () => {
    // Recorded run
    const { unmount } = render(<RunReceipt detail={makeDetail()} />);
    let receipt = screen.getByRole("region", { name: "Run receipt" });
    expect(within(receipt).getByText("CPU family")).toBeTruthy();
    expect(within(receipt).getByText("apple_silicon")).toBeTruthy();
    expect(within(receipt).getByText("CPU model")).toBeTruthy();
    expect(within(receipt).getByText("Apple M1 Max")).toBeTruthy();
    unmount();

    // Run without CPU metadata
    render(
      <RunReceipt
        detail={makeDetail({
          environment: {
            os: "Linux",
            arch: "x86_64",
            cpu_count: 8,
            memory_gb: 32,
            python: "3.12",
          },
        })}
      />,
    );
    receipt = screen.getByRole("region", { name: "Run receipt" });
    expect(within(receipt).queryByText("CPU family")).toBeNull();
    expect(within(receipt).queryByText("CPU model")).toBeNull();

    // Expand disclosure
    fireEvent.click(within(receipt).getByRole("button", { name: /Show missing metadata/ }));
    expect(within(receipt).getByText("CPU family")).toBeTruthy();
    expect(within(receipt).getByText("CPU model")).toBeTruthy();
  });

  it("does not mislabel an unsupported CPU evidence value as inferred", () => {
    render(<RunReceipt detail={makeDetail({ environment: { ...makeDetail().environment, cpu_identity_provenance: "typo" as never } })} />);

    expect(screen.getByText("Unknown")).toBeInTheDocument();
    expect(screen.queryByText("Inferred")).toBeNull();
  });

  it("renders client locality and statement overhead when present", () => {
    render(
      <RunReceipt
        detail={makeDetail({
          environment: {
            ...makeDetail().environment,
            client_region: "us-east-1",
            client_cloud: "aws",
            statement_overhead_min_ms: 0.85,
            statement_overhead_median_ms: 1.42,
            link_status: "measured",
          },
        })}
      />,
    );

    const receipt = screen.getByRole("region", { name: "Run receipt" });
    expect(within(receipt).getByText("Client locality")).toBeTruthy();
    expect(
      within(receipt).getByText(/us-east-1 \/ aws \(overhead: 0\.85 ms min, 1\.42 ms median\) \[measured\]/),
    ).toBeTruthy();
  });
});
