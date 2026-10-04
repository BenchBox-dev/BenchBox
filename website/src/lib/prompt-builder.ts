export type Entry = { id: string; label: string };

export type Platform = Entry & {
  interfaces: string[];
  deployments: string[];
  cost_class?: string;
  install_command?: string;
  dependency_check_command?: string;
  dependency_check_platform?: string;
  platform_option_hints?: string[];
  safety_terms?: Record<string, string>;
  credential_deployments?: string[];
};

export type Benchmark = Entry & { interfaces: string[]; requires_bundled_dsdgen_below?: string };

export type Catalog = {
  benchmarks: Benchmark[];
  platforms: Platform[];
  goals: Entry[];
  surfaces: Entry[];
  interfaces: Entry[];
  deployments: Entry[];
  scales: (string | number)[];
  defaults: Record<string, string>;
  runtime_hints?: { log_dir?: string; log_slug_template?: string; long_run_threshold_scale?: string };
  mcp: {
    run_tool: string;
    list_tool: string;
    analysis_tool?: string;
    system_profile_tool?: string;
    plan_tool?: string;
    prompts: { compare_platforms: string; benchmark_run: string };
  };
  templates: {
    cli: {
      compare: string;
      test_one: string;
      dry_run: string;
      provenance_snapshot?: string;
      results_paths: string;
      show_cli: string;
      force_datagen_footer: string;
      capture_plans_footer: string;
    };
  };
};

export const SELECTORS = ["goal", "surface", "interface", "deployment", "platform", "platformA", "platformB", "benchmark", "scale"] as const;
export type SelectorKey = (typeof SELECTORS)[number];
export type RawState = Partial<Record<SelectorKey, string>>;
export type State = RawState & Record<"goal" | "surface" | "interface" | "deployment" | "benchmark" | "scale", string>;

export const COPY_LABELS: Record<string, string> = {
  "prompt-text": "agent prompt",
  "mcp-setup-text": "MCP server config",
};

export const MCP_SETUP_TEXT = ["[mcp_servers.benchbox]", 'command = "uv"', 'args = ["run", "--", "python", "-m", "benchbox.mcp"]'].join("\n");

type Output = { prompt: string; mcpSetup: string; showMcpSetup: boolean; safety: string[] };

const findById = <T extends Entry>(list: T[], id: string | undefined | null): T | null => list.find((item) => item.id === id) ?? null;

export function stateFromSearch(search: string): RawState {
  const params = new URLSearchParams(search);
  const state: RawState = {};
  for (const key of SELECTORS) {
    const value = params.get(key);
    if (value !== null && value !== "") state[key] = value;
  }
  return state;
}

export function searchFromState(state: RawState): string {
  const params = new URLSearchParams();
  for (const key of SELECTORS) {
    const value = state[key];
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  return params.toString();
}

export function platformsForFilters(catalog: Catalog, iface: string, deployment: string): Platform[] {
  return catalog.platforms.filter((p) => p.interfaces.includes(iface) && p.deployments.includes(deployment));
}

export function benchmarksForInterface(catalog: Catalog, iface: string): Benchmark[] {
  return catalog.benchmarks.filter((b) => b.interfaces.includes(iface));
}

function deriveCompareDefaults(catalog: Catalog, state: RawState): [string | null, string | null] {
  const pool = platformsForFilters(catalog, state.interface ?? "", state.deployment ?? "");
  if (pool.length < 2) return [null, null];
  const a = state.platformA && pool.some((p) => p.id === state.platformA) ? state.platformA : pool[0].id;
  const b =
    state.platformB && state.platformB !== a && pool.some((p) => p.id === state.platformB)
      ? state.platformB
      : (pool.find((p) => p.id !== a) ?? pool[0]).id;
  return [a, b];
}

export function normaliseState(catalog: Catalog, raw: RawState): State {
  const defaults = catalog.defaults;
  const state = {} as State;
  for (const key of ["goal", "surface", "interface", "deployment", "benchmark"] as const) {
    state[key] = raw[key] || defaults[key];
  }
  if (!catalog.goals.some((goal) => goal.id === state.goal)) state.goal = defaults.goal;
  if (!catalog.surfaces.some((surface) => surface.id === state.surface)) state.surface = defaults.surface;
  const scaleStr = String(raw.scale || defaults.scale);
  const scaleIds = catalog.scales.map(String);
  let scaleIdx = scaleIds.indexOf(scaleStr);
  if (scaleIdx === -1) {
    const scaleNum = parseFloat(scaleStr);
    if (Number.isFinite(scaleNum)) scaleIdx = scaleIds.findIndex((id) => parseFloat(id) === scaleNum);
  }
  state.scale = scaleIdx !== -1 ? scaleIds[scaleIdx] : String(defaults.scale);

  if (!benchmarksForInterface(catalog, state.interface).some((b) => b.id === state.benchmark)) {
    state.benchmark = (benchmarksForInterface(catalog, state.interface)[0] ?? catalog.benchmarks[0]).id;
  }

  let pool = platformsForFilters(catalog, state.interface, state.deployment);
  if (pool.length === 0) {
    state.deployment = defaults.deployment;
    pool = platformsForFilters(catalog, state.interface, state.deployment);
  }
  if (pool.length === 0) {
    state.interface = defaults.interface;
    pool = platformsForFilters(catalog, state.interface, state.deployment);
  }
  if (state.goal === "compare" && pool.length < 2) state.goal = defaults.goal;

  if (state.goal === "compare") {
    const [a, b] = deriveCompareDefaults(catalog, { ...raw, ...state });
    state.platformA = a ?? undefined;
    state.platformB = b ?? undefined;
    state.platform = undefined;
  } else {
    const preferred = raw.platform || defaults.platform;
    state.platform = preferred && pool.some((p) => p.id === preferred) ? preferred : (pool[0] && pool[0].id) || defaults.platform;
    state.platformA = undefined;
    state.platformB = undefined;
  }
  return state;
}

function renderTemplate(template: string, vars: Record<string, string>): string {
  return template.replace(/\{([a-z_]+)\}/g, (_, key: string) => (vars[key] !== undefined ? String(vars[key]) : `{${key}}`));
}

const platformLabel = (entry: Entry | null) => (entry ? entry.label || entry.id : "the selected platform");

const dryRunDir = (platform: string) => `/tmp/benchbox-dryrun-${String(platform).replace(/[^A-Za-z0-9_.-]/g, "-")}`;

function logPath(catalog: Catalog, state: State, platformSlug: string): string {
  const hints = catalog.runtime_hints ?? {};
  const dir = String(hints.log_dir || "/tmp").replace(/\/+$/, "");
  const template = hints.log_slug_template || "bench_{platform}_{benchmark}_{scale}";
  const slug = renderTemplate(template, { platform: platformSlug, benchmark: state.benchmark, scale: state.scale }).replace(/[^A-Za-z0-9_.-]/g, "-");
  return `${dir}/${slug}.log`;
}

function shouldAnnounceRun(catalog: Catalog, state: State): boolean {
  const threshold = parseFloat(catalog.runtime_hints?.long_run_threshold_scale || "0.1");
  return parseFloat(state.scale) >= threshold || state.deployment !== "local";
}

const commandWithLogCapture = (command: string, file: string) => `set -o pipefail; ${command} 2>&1 | tee ${file}`;
const commandAtScale = (command: string, scale: string) => command.replace(/--scale\s+\S+/, `--scale ${scale}`);
const isPaidEntry = (entry: Platform | null) => Boolean(entry) && (entry?.cost_class || "free") !== "free";
const isPaidSelection = (a: Platform | null, b: Platform | null) => isPaidEntry(a) || isPaidEntry(b);
const needsSmokeStep = (state: State, isPaid: boolean) => state.scale !== "0.01" && (isPaid || state.deployment !== "local");
const needsCostAcknowledgment = (state: State, isPaid: boolean) => isPaid && parseFloat(state.scale) >= 0.1;

function safetyTexts(entries: (Platform | null)[], key: string, deployment: string): string[] {
  const texts: string[] = [];
  for (const entry of entries) {
    if (!entry || !entry.safety_terms || !entry.safety_terms[key]) continue;
    if (deployment && entry.credential_deployments && !entry.credential_deployments.includes(deployment)) continue;
    if (!texts.includes(entry.safety_terms[key])) texts.push(entry.safety_terms[key]);
  }
  return texts;
}

function appendDeploymentSafetyLines(lines: string[], entries: (Platform | null)[], deployment: string): void {
  const checks = safetyTexts(entries, "dependency", deployment);
  const dryRuns = safetyTexts(entries, "dry_run", deployment);
  if (checks.length === 0 && dryRuns.length === 0) return;
  lines.push("", "Deployment safety:");
  for (const text of checks.concat(dryRuns)) lines.push(`  • ${text}`);
}

function uniqueField(entries: (Platform | null)[], field: "install_command" | "dependency_check_command" | "dependency_check_platform"): string[] {
  const values: string[] = [];
  for (const entry of entries) {
    const value = entry?.[field];
    if (value && !values.includes(value)) values.push(value);
  }
  return values;
}

type HintBlock = { label: string; hints: string[] };

function platformOptionHintBlocks(entries: (Platform | null)[]): HintBlock[] {
  const blocks: HintBlock[] = [];
  const seen: Record<string, boolean> = {};
  for (const entry of entries) {
    if (!entry || !entry.platform_option_hints || !entry.platform_option_hints.length) continue;
    const hints: string[] = [];
    for (const hint of entry.platform_option_hints) if (!hints.includes(hint)) hints.push(hint);
    if (!hints.length || seen[entry.id]) continue;
    seen[entry.id] = true;
    blocks.push({ label: platformLabel(entry), hints });
  }
  return blocks;
}

function bundledDsdgenThreshold(benchmark: Benchmark | null): string | null {
  if (!benchmark || !benchmark.requires_bundled_dsdgen_below) return null;
  return Number.isFinite(parseFloat(benchmark.requires_bundled_dsdgen_below)) ? benchmark.requires_bundled_dsdgen_below : null;
}

const BUNDLED_DSDGEN_PATH_HINT =
  "`_binaries/tpc-ds/<os>-<arch>/dsdgen` (for example `_binaries/tpc-ds/linux-x86_64/dsdgen` or `_binaries/tpc-ds/darwin-arm64/dsdgen`)";

const bundledDsdgenWarningStep = (stepNumber: number, benchmark: Benchmark | null) =>
  `  ${stepNumber}. TPC-DS sub-scale warning: scale factors below ${bundledDsdgenThreshold(benchmark)} require BenchBox's bundled patched dsdgen at ${BUNDLED_DSDGEN_PATH_HINT}; do not use stock dsdgen.`;

function needsBundledDsdgenWarning(state: State, benchmark: Benchmark | null, isPaid: boolean): boolean {
  const threshold = bundledDsdgenThreshold(benchmark);
  if (threshold === null) return false;
  const numeric = parseFloat(threshold);
  return parseFloat(state.scale) < numeric || (needsSmokeStep(state, isPaid) && 0.01 < numeric);
}

const mcpModeArg = (state: State) => (state.interface === "dataframe" ? ', mode="dataframe"' : "");

function mcpRunCall(tool: string, platform: string, state: State, scale: string, dryRun: boolean | null): string {
  const dry = dryRun === null ? "" : `, dry_run=${dryRun ? "true" : "false"}`;
  return `\`${tool}(platform="${platform}", benchmark="${state.benchmark}", scale_factor=${scale}${dry}${mcpModeArg(state)})\``;
}

const mcpRunCalls = (tool: string, platforms: string[], state: State, scale: string, dryRun: boolean) =>
  platforms.map((p) => mcpRunCall(tool, p, state, scale, dryRun)).join(" and ");

function mcpPromptCall(promptName: string, state: State, platform: string, platformB: string | undefined): string {
  if (state.goal === "compare") {
    return `\`${promptName}(benchmark="${state.benchmark}", platforms="${platform},${platformB}", scale_factor=${state.scale})\``;
  }
  return `\`${promptName}(platform="${platform}", benchmark="${state.benchmark}", scale_factor=${state.scale})\``;
}

function appendMcpPlatformOptionLines(lines: string[], entries: (Platform | null)[], step: { value: number }): void {
  for (const block of platformOptionHintBlocks(entries)) {
    lines.push(
      `  ${step.value++}. Platform option gap for ${block.label}: MCP \`run_benchmark\` does not expose platform option arguments yet. Configure these via BenchBox config/env or switch to the CLI surface if required.`,
    );
    for (const hint of block.hints) {
      const parts = hint.split("#");
      const option = parts[0].replace("--platform-option", "").trim();
      const note = parts.slice(1).join("#").trim();
      lines.push(`     • \`${option}\`${note ? ` — ${note}` : ""}`);
    }
  }
}

function mcpAnalysisStep(catalog: Catalog, state: State, platform: string): string {
  const tool = catalog.mcp.analysis_tool || "analyze_results";
  if (state.goal === "compare") {
    return `Use the \`${tool}(analysis="compare", file1="<first-result-json>", file2="<second-result-json>")\` tool with only the filename component from each live response's \`mcp_metadata.result_file\`; summarize total runtime, per-query timing, and failures.`;
  }
  return `Summarize total runtime, per-query timings, and failures from the MCP tool result payload. If you need a result rollup, call \`${tool}(analysis="aggregate", platform="${platform}", benchmark="${state.benchmark}", limit=1)\`.`;
}

const mcpProvenanceStep = (catalog: Catalog) =>
  `Save provenance: call \`${catalog.mcp.system_profile_tool || "system_profile"}()\` and record the BenchBox version plus system profile fields next to the result bundle.`;

const mcpCapturePlansFootnote = (catalog: Catalog) =>
  `To capture EXPLAIN plans, rerun live with \`capture_plans=true\` only when plans are needed, then inspect a supported plan with \`${catalog.mcp.plan_tool || "get_query_plan"}(result_file="<result-json>", query_id="Q1")\`.`;

function renderMcpDependencyStep(stepNumber: number, platforms: string[], fallbackScope: string): string {
  if (platforms.length > 0) {
    const checks = platforms.map((p) => `\`check_dependencies(platform="${p}")\``).join(" and ");
    return `  ${stepNumber}. Call ${checks}. Stop and report if anything is missing.`;
  }
  return `  ${stepNumber}. No optional connector dependency check is registered for this ${fallbackScope}; confirm the install step completed successfully.`;
}

const CREDENTIALS_STEP = "Make sure platform connection credentials/config are set outside this conversation (env vars, config files). Do NOT ask me to paste secrets here.";
const COST_STEP = "COST ACKNOWLEDGMENT: ask the user to confirm credit or compute spend before running the target scale.";

type Selection = {
  platform: string;
  platformB: string | undefined;
  platformEntry: Platform | null;
  platformBEntry: Platform | null;
  benchmarkEntry: Benchmark | null;
  needsCredentials: boolean;
};

function buildMcpPrompt(catalog: Catalog, state: State, selection: Selection): string {
  const { platform, platformB, platformEntry, platformBEntry, benchmarkEntry, needsCredentials } = selection;
  const isCompare = state.goal === "compare";
  const tool = catalog.mcp.run_tool;
  const promptName = isCompare ? catalog.mcp.prompts.compare_platforms : catalog.mcp.prompts.benchmark_run;
  const dependencyPlatforms = uniqueField([platformEntry, platformBEntry], "dependency_check_platform");
  const selectedPlatforms = isCompare ? [platform, platformB as string] : [platform];
  const entries = isCompare ? [platformEntry, platformBEntry] : [platformEntry];
  const isPaid = isPaidSelection(platformEntry, platformBEntry);
  const step = { value: 1 };
  const lines: string[] = [];
  const target = (dryRun: boolean) => mcpRunCalls(tool, selectedPlatforms, state, state.scale, dryRun);

  if (isCompare) {
    lines.push(
      `Use the BenchBox MCP server to compare ${platformLabel(platformEntry)} and ${platformLabel(platformBEntry)}.`,
      "Steps:",
      `  ${step.value++}. Call the \`${catalog.mcp.list_tool}\` tool to confirm both platforms are available.`,
      renderMcpDependencyStep(step.value++, dependencyPlatforms, "selection"),
    );
  } else {
    lines.push(
      `Use the BenchBox MCP server to run ${benchmarkEntry ? benchmarkEntry.label : state.benchmark} on ${platformLabel(platformEntry)}.`,
      "Steps:",
      `  ${step.value++}. Call the \`${catalog.mcp.list_tool}\` tool to confirm the platform is installed.`,
      renderMcpDependencyStep(step.value++, dependencyPlatforms, "platform"),
    );
  }
  appendMcpPlatformOptionLines(lines, entries, step);
  lines.push(`  ${step.value++}. Use the ${mcpPromptCall(promptName, state, platform, platformB)} prompt.`);
  if (needsBundledDsdgenWarning(state, benchmarkEntry, isPaid)) lines.push(bundledDsdgenWarningStep(step.value++, benchmarkEntry));
  if (needsCredentials) lines.push(`  ${step.value++}. ${CREDENTIALS_STEP}`);
  if (needsSmokeStep(state, isPaid)) {
    const smoke = mcpRunCalls(tool, selectedPlatforms, state, "0.01", false);
    lines.push(
      isCompare
        ? `  ${step.value++}. SMOKE: call ${smoke} before the target-scale dry run. Abort if either smoke run fails.`
        : `  ${step.value++}. SMOKE: call ${smoke}. Abort if the smoke run fails.`,
    );
  }
  lines.push(`  ${step.value++}. Call ${target(true)}. ${isCompare ? "Inspect both plans." : "Inspect the plan."}`);
  if (shouldAnnounceRun(catalog, state)) {
    lines.push(
      `  ${step.value++}. Announce before running: target MCP call(s) ${target(false)}, expected runtime, and stop condition. Stop promptly on user interrupt or redirect.`,
    );
  }
  if (needsCostAcknowledgment(state, isPaid)) lines.push(`  ${step.value++}. ${COST_STEP}`);
  lines.push(`  ${step.value++}. Run live: ${target(false)}.`);
  lines.push(`  ${step.value++}. ${mcpAnalysisStep(catalog, state, platform)}`);
  lines.push(`  ${step.value++}. ${mcpProvenanceStep(catalog)}`);
  lines.push(`  • ${mcpCapturePlansFootnote(catalog)}`);
  if (needsCredentials) appendDeploymentSafetyLines(lines, entries, state.deployment);
  lines.push(needsCredentials ? "  • Stop and ask the user if credentials or config are missing — do not request secrets in chat." : "");
  return lines.filter(Boolean).join("\n");
}

function buildAgentPrompt(catalog: Catalog, state: State, selection: Selection): string {
  const { platform, platformB, platformEntry, platformBEntry, benchmarkEntry, needsCredentials } = selection;
  const isCompare = state.goal === "compare";
  const modeFlag = state.interface === "dataframe" ? " --mode dataframe" : "";
  const compareTypeFlag = state.interface === "dataframe" ? " --type dataframe" : "";
  const cli = catalog.templates.cli;
  const cliCmd = isCompare
    ? renderTemplate(cli.compare, { platform_a: platform, platform_b: platformB as string, benchmark: state.benchmark, scale: state.scale }) + compareTypeFlag
    : renderTemplate(cli.test_one, { platform, benchmark: state.benchmark, scale: state.scale }) + modeFlag;
  const depChecks = uniqueField([platformEntry, platformBEntry], "dependency_check_command");
  const dryRunFor = (p: string) => renderTemplate(cli.dry_run, { dry_run_dir: dryRunDir(p), platform: p, benchmark: state.benchmark, scale: state.scale }) + modeFlag;
  const dryRun = dryRunFor(platform);
  const dryRunB = isCompare ? dryRunFor(platformB as string) : null;

  const pretty = benchmarkEntry ? benchmarkEntry.label : state.benchmark;
  const platformSlug = isCompare ? `${platform}-vs-${platformB}` : platform;
  const liveLogPath = logPath(catalog, state, platformSlug);
  const liveCmd = commandWithLogCapture(cliCmd, liveLogPath);
  const isPaid = isPaidSelection(platformEntry, platformBEntry);
  const smokeCmd = commandWithLogCapture(commandAtScale(cliCmd, "0.01"), logPath(catalog, { ...state, scale: "0.01" }, platformSlug));
  let step = 1;
  const lines: string[] = [];
  const subject = isCompare ? `compare ${platformLabel(platformEntry)} and ${platformLabel(platformBEntry)}` : `run ${pretty} on ${platformLabel(platformEntry)}`;
  const tail = isCompare ? ` on ${pretty}` : "";
  lines.push(`Goal: ${subject}${tail} at scale factor ${state.scale} (${state.interface.toUpperCase()} interface, ${state.deployment} deployment).`);
  lines.push("", "Steps:");
  const installs = uniqueField([platformEntry, platformBEntry], "install_command");
  lines.push(`  ${step++}. Install dependencies: \`${installs.join("` and `")}\`.`);
  for (const block of platformOptionHintBlocks([platformEntry, platformBEntry])) {
    lines.push(`  ${step++}. Likely required platform options for ${block.label}:`);
    for (const hint of block.hints) lines.push(`     • \`${hint}\``);
  }
  if (depChecks.length > 0) {
    lines.push(`  ${step++}. Check dependencies: \`${depChecks.join("` and `")}\`. Stop and report if anything is missing.`);
  } else {
    lines.push(`  ${step++}. Check dependencies: no optional connector check is registered for this selection; confirm the install command completed successfully.`);
  }
  if (needsBundledDsdgenWarning(state, benchmarkEntry, isPaid)) lines.push(bundledDsdgenWarningStep(step++, benchmarkEntry));
  if (needsCredentials) lines.push(`  ${step++}. ${CREDENTIALS_STEP}`);
  if (needsSmokeStep(state, isPaid)) {
    lines.push(`  ${step++}. SMOKE: run the same live command at scale factor 0.01 before the target-scale dry run: \`${smokeCmd}\`. Abort if the smoke run fails.`);
  }
  lines.push(`  ${step++}. Dry run first: \`${dryRun}\`${dryRunB ? ` and \`${dryRunB}\`` : ""}. Inspect the plan${dryRunB ? "s" : ""}.`);
  if (shouldAnnounceRun(catalog, state)) {
    lines.push(`  ${step++}. Announce before running: command \`${liveCmd}\`, log path \`${liveLogPath}\`, expected runtime, and stop condition. Stop promptly on user interrupt or redirect.`);
  }
  const cost = needsCostAcknowledgment(state, isPaid);
  if (cost) lines.push(`  ${step++}. ${COST_STEP}`);
  if (needsCredentials) {
    const confirmed = cost ? "credentials and cost acknowledgment are" : "credentials are";
    lines.push(`  ${step++}. Once ${confirmed} confirmed, run live: \`${liveCmd}\`.`);
  } else {
    lines.push(`  ${step++}. Run live: \`${liveCmd}\`.`);
  }
  if (isCompare) {
    lines.push(
      `  ${step++}. Discover & summarize: summarize total runtime, per-query timings, and failures from the comparison output in \`${liveLogPath}\`. If the compare command was run with an explicit output path, inspect that file too.`,
    );
  } else {
    lines.push(
      `  ${step++}. Discover & summarize: run \`${cli.results_paths}\`, then run \`${cli.show_cli}\` with the result JSON path. Summarize total runtime, per-query timings, and failures from the result JSON.`,
    );
  }
  lines.push(`  ${step++}. Save provenance next to the result bundle. Replace \`<bundle-dir>\` with the bundle directory from the previous step, then run:`);
  const snapshot = (cli.provenance_snapshot || "").replace("<exact command line used>", liveCmd);
  for (const line of snapshot.split("\n")) if (line) lines.push(`     ${line}`);
  lines.push("", cli.force_datagen_footer, cli.capture_plans_footer);
  return lines.join("\n");
}

export function buildOutput(catalog: Catalog, state: State): Output {
  const isCompare = state.goal === "compare";
  const platform = (isCompare ? state.platformA : state.platform) as string;
  const platformB = isCompare ? state.platformB : undefined;
  const platformEntry = findById(catalog.platforms, platform);
  const platformBEntry = isCompare ? findById(catalog.platforms, platformB) : null;
  const benchmarkEntry = findById(catalog.benchmarks, state.benchmark);
  const safety = safetyTexts([platformEntry, platformBEntry], "no_secrets", state.deployment);
  const selection: Selection = { platform, platformB, platformEntry, platformBEntry, benchmarkEntry, needsCredentials: safety.length > 0 };
  const prompt = state.surface === "mcp" ? buildMcpPrompt(catalog, state, selection) : buildAgentPrompt(catalog, state, selection);
  return { prompt, mcpSetup: MCP_SETUP_TEXT, showMcpSetup: state.surface === "mcp", safety };
}
