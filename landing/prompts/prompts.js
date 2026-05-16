/* /prompts/ landing route — state + rendering for the prompt builder.
 *
 * Reads `window.__BENCHBOX_PROMPT_CATALOG__` (set by catalog.generated.js),
 * syncs selection state to URL query parameters, filters platform options
 * by selected interface + deployment, and renders prompt / MCP output
 * blocks. No framework — plain vanilla JS so the page stays a static
 * deploy under `landing/`.
 *
 * URL parameters:
 *   goal, surface, interface, deployment, platform, platformA, platformB,
 *   benchmark, scale.
 */
(function () {
    "use strict";

    var catalog = window.__BENCHBOX_PROMPT_CATALOG__;
    if (!catalog) {
        console.error("__BENCHBOX_PROMPT_CATALOG__ missing — catalog.generated.js failed to load");
        return;
    }

    var $ = function (id) { return document.getElementById(id); };
    var qs = function (s) { return document.querySelectorAll(s); };

    var SELECTORS = ["goal", "surface", "interface", "deployment", "platform", "platformA", "platformB", "benchmark", "scale"];
    var COPY_LABELS = {
        "prompt-text": "agent prompt",
        "mcp-setup-text": "MCP server config"
    };

    function getStateFromURL() {
        var params = new URLSearchParams(window.location.search);
        var state = {};
        SELECTORS.forEach(function (k) {
            var v = params.get(k);
            if (v !== null && v !== "") state[k] = v;
        });
        return state;
    }

    function writeStateToURL(state) {
        var params = new URLSearchParams();
        SELECTORS.forEach(function (k) {
            if (state[k] !== undefined && state[k] !== null && state[k] !== "") {
                params.set(k, String(state[k]));
            }
        });
        var qs = params.toString();
        var newUrl = window.location.pathname + (qs ? "?" + qs : "");
        window.history.replaceState({}, "", newUrl);
    }

    function findById(list, id) {
        for (var i = 0; i < list.length; i++) {
            if (list[i].id === id) return list[i];
        }
        return null;
    }

    function platformsForFilters(iface, deployment) {
        return catalog.platforms.filter(function (p) {
            return p.interfaces.indexOf(iface) !== -1 && p.deployments.indexOf(deployment) !== -1;
        });
    }

    function benchmarksForInterface(iface) {
        return catalog.benchmarks.filter(function (b) { return b.interfaces.indexOf(iface) !== -1; });
    }

    function fillSelect(el, items, currentValue, labelFn) {
        var current = currentValue;
        el.innerHTML = "";
        items.forEach(function (item) {
            var opt = document.createElement("option");
            opt.value = item.id || String(item);
            opt.textContent = labelFn ? labelFn(item) : (item.label || item.id || String(item));
            el.appendChild(opt);
        });
        var ids = items.map(function (i) { return i.id || String(i); });
        if (current && ids.indexOf(String(current)) !== -1) {
            el.value = String(current);
        } else {
            el.value = ids[0] || "";
        }
    }

    function deriveCompareDefaults(state) {
        var pool = platformsForFilters(state["interface"], state.deployment);
        if (pool.length < 2) return [null, null];
        var a = state.platformA && pool.some(function (p) { return p.id === state.platformA; }) ? state.platformA : pool[0].id;
        var b = state.platformB && state.platformB !== a && pool.some(function (p) { return p.id === state.platformB; }) ? state.platformB : (pool.find(function (p) { return p.id !== a; }) || pool[0]).id;
        return [a, b];
    }

    function normaliseState(raw) {
        var defaults = catalog.defaults;
        var state = {};
        ["goal", "surface", "interface", "deployment", "benchmark"].forEach(function (k) {
            state[k] = raw[k] || defaults[k];
        });
        var scaleStr = String(raw.scale || defaults.scale);
        var scaleIds = catalog.scales.map(function (s) { return String(s); });
        var scaleIdx = scaleIds.indexOf(scaleStr);
        if (scaleIdx === -1) {
            // Match legacy numeric aliases (e.g. "1" -> "1.0") so bookmarked
            // URLs from before string-id normalisation still resolve.
            var scaleNum = parseFloat(scaleStr);
            if (isFinite(scaleNum)) {
                for (var i = 0; i < scaleIds.length; i++) {
                    if (parseFloat(scaleIds[i]) === scaleNum) { scaleIdx = i; break; }
                }
            }
        }
        state.scale = scaleIdx !== -1 ? scaleIds[scaleIdx] : String(defaults.scale);

        // benchmark must support selected interface
        if (!benchmarksForInterface(state["interface"]).some(function (b) { return b.id === state.benchmark; })) {
            var bb = benchmarksForInterface(state["interface"])[0] || catalog.benchmarks[0];
            state.benchmark = bb.id;
        }

        // platform filtering
        var pool = platformsForFilters(state["interface"], state.deployment);
        if (pool.length === 0) {
            // fall back: relax deployment first
            state.deployment = defaults.deployment;
            pool = platformsForFilters(state["interface"], state.deployment);
        }
        if (pool.length === 0) {
            state["interface"] = defaults["interface"];
            pool = platformsForFilters(state["interface"], state.deployment);
        }

        if (state.goal === "compare" && pool.length < 2) {
            state.goal = defaults.goal;
        }

        if (state.goal === "compare") {
            var pair = deriveCompareDefaults(Object.assign({}, raw, state));
            state.platformA = pair[0];
            state.platformB = pair[1];
            state.platform = undefined;
        } else {
            var preferredPlatform = raw.platform || defaults.platform;
            var p = preferredPlatform && pool.some(function (pp) { return pp.id === preferredPlatform; }) ? preferredPlatform : (pool[0] && pool[0].id) || defaults.platform;
            state.platform = p;
            state.platformA = undefined;
            state.platformB = undefined;
        }
        return state;
    }

    function renderSelectors(state) {
        fillSelect($("sel-goal"), catalog.goals, state.goal);
        fillSelect($("sel-surface"), catalog.surfaces, state.surface);
        fillSelect($("sel-interface"), catalog.interfaces, state["interface"]);
        fillSelect($("sel-deployment"), catalog.deployments, state.deployment);
        fillSelect($("sel-benchmark"), benchmarksForInterface(state["interface"]), state.benchmark);
        fillSelect($("sel-scale"), catalog.scales.map(function (s) { return { id: String(s), label: String(s) }; }), state.scale);

        var pool = platformsForFilters(state["interface"], state.deployment);

        qs('[data-mode="test_one"]').forEach(function (el) { el.hidden = state.goal === "compare"; });
        qs('[data-mode="compare"]').forEach(function (el) { el.hidden = state.goal !== "compare"; });

        if (state.goal === "compare") {
            fillSelect($("sel-platformA"), pool, state.platformA);
            // exclude A from B options if possible
            var poolB = pool.filter(function (p) { return p.id !== state.platformA; });
            if (poolB.length === 0) poolB = pool;
            fillSelect($("sel-platformB"), poolB, state.platformB);
        } else {
            fillSelect($("sel-platform"), pool, state.platform);
        }
    }

    function renderOutput(state) {
        // Decide which output blocks to show by surface
        var isCompare = state.goal === "compare";
        var platform = isCompare ? state.platformA : state.platform;
        var platformB = isCompare ? state.platformB : null;
        var platformEntry = findById(catalog.platforms, platform);
        var platformBEntry = isCompare ? findById(catalog.platforms, platformB) : null;
        var benchmarkEntry = findById(catalog.benchmarks, state.benchmark);
        var selectedEntries = [platformEntry, platformBEntry];
        var needsCredentials = safetyTexts(selectedEntries, "no_secrets", state.deployment).length > 0;

        var modeFlag = state["interface"] === "dataframe" ? " --mode dataframe" : "";
        var compareTypeFlag = state["interface"] === "dataframe" ? " --type dataframe" : "";
        var cliCmd = isCompare
            ? renderTemplate(catalog.templates.cli.compare, { platform_a: platform, platform_b: platformB, benchmark: state.benchmark, scale: state.scale }) + compareTypeFlag
            : renderTemplate(catalog.templates.cli.test_one, { platform: platform, benchmark: state.benchmark, scale: state.scale }) + modeFlag;

        var depChecks = dependencyCommands(selectedEntries);
        var dryRun = renderTemplate(catalog.templates.cli.dry_run, {
            dry_run_dir: dryRunDir(platform),
            platform: platform,
            benchmark: state.benchmark,
            scale: state.scale
        }) + modeFlag;
        var dryRunB = isCompare ? renderTemplate(catalog.templates.cli.dry_run, {
            dry_run_dir: dryRunDir(platformB),
            platform: platformB,
            benchmark: state.benchmark,
            scale: state.scale
        }) + modeFlag : null;

        // MCP setup block
        var mcpTomlLines = [
            "[mcp_servers.benchbox]",
            'command = "uv"',
            'args = ["run", "--", "python", "-m", "benchbox.mcp"]'
        ];
        $("mcp-setup-text").textContent = mcpTomlLines.join("\n");

        // block-prompt text: shell-oriented agent prompt for CLI, MCP workflow prompt for MCP surface.
        if (state.surface === "mcp") {
            $("prompt-text").textContent = buildMcpPrompt(state, platform, platformB, platformEntry, platformBEntry, benchmarkEntry, needsCredentials);
        } else {
            $("prompt-text").textContent = buildAgentPrompt(state, platform, platformB, platformEntry, platformBEntry, benchmarkEntry, cliCmd, dryRun, dryRunB, depChecks, needsCredentials);
        }

        // Visibility rules:
        // - Agent prompt: always shown.
        // - MCP setup: shown for surface=MCP.
        // - Credential safety: shown when selected deployment needs connection secrets.
        $("block-prompt").hidden = false;
        $("block-mcp-setup").hidden = state.surface !== "mcp";

        var safetyList = $("cloud-safety-list");
        safetyList.innerHTML = "";
        if (needsCredentials) {
            safetyTexts(selectedEntries, "no_secrets", state.deployment).forEach(function (text) {
                var li = document.createElement("li");
                li.textContent = text;
                safetyList.appendChild(li);
            });
            $("block-cloud-safety").hidden = safetyList.children.length === 0;
        } else {
            $("block-cloud-safety").hidden = true;
        }
    }

    function platformLabel(entry) { return entry ? (entry.label || entry.id) : "the selected platform"; }

    function dryRunDir(platform) {
        return "/tmp/benchbox-dryrun-" + String(platform).replace(/[^A-Za-z0-9_.-]/g, "-");
    }

    function renderTemplate(tpl, vars) {
        return tpl.replace(/\{([a-z_]+)\}/g, function (_, k) {
            return vars[k] !== undefined ? String(vars[k]) : "{" + k + "}";
        });
    }

    function runtimeHints() {
        return catalog.runtime_hints || {};
    }

    function logPath(state, platformSlug) {
        var hints = runtimeHints();
        var dir = String(hints.log_dir || "/tmp").replace(/\/+$/, "");
        var template = hints.log_slug_template || "bench_{platform}_{benchmark}_{scale}";
        var slug = renderTemplate(template, {
            platform: platformSlug,
            benchmark: state.benchmark,
            scale: state.scale
        }).replace(/[^A-Za-z0-9_.-]/g, "-");
        return dir + "/" + slug + ".log";
    }

    function shouldAnnounceRun(state) {
        var threshold = parseFloat(runtimeHints().long_run_threshold_scale || "0.1");
        return parseFloat(state.scale) >= threshold || state.deployment !== "local";
    }

    function commandWithLogCapture(command, path) {
        return "set -o pipefail; " + command + " 2>&1 | tee " + path;
    }

    function safetyTexts(entries, key, deployment) {
        var texts = [];
        entries.forEach(function (entry) {
            if (!entry || !entry.safety_terms || !entry.safety_terms[key]) return;
            if (deployment && entry.credential_deployments && entry.credential_deployments.indexOf(deployment) === -1) return;
            if (texts.indexOf(entry.safety_terms[key]) === -1) texts.push(entry.safety_terms[key]);
        });
        return texts;
    }

    function appendDeploymentSafetyLines(lines, entries, deployment) {
        var checks = safetyTexts(entries, "dependency", deployment);
        var dryRuns = safetyTexts(entries, "dry_run", deployment);
        if (checks.length === 0 && dryRuns.length === 0) return;
        lines.push("");
        lines.push("Deployment safety:");
        checks.concat(dryRuns).forEach(function (text) {
            lines.push("  • " + text);
        });
    }

    function installCommands(entries) {
        var commands = [];
        entries.forEach(function (entry) {
            if (!entry || !entry.install_command) return;
            if (commands.indexOf(entry.install_command) === -1) commands.push(entry.install_command);
        });
        return commands;
    }

    function dependencyCommands(entries) {
        var commands = [];
        entries.forEach(function (entry) {
            if (!entry || !entry.dependency_check_command) return;
            if (commands.indexOf(entry.dependency_check_command) === -1) commands.push(entry.dependency_check_command);
        });
        return commands;
    }

    function dependencyCheckPlatforms(entries) {
        var platforms = [];
        entries.forEach(function (entry) {
            if (!entry || !entry.dependency_check_platform) return;
            if (platforms.indexOf(entry.dependency_check_platform) === -1) platforms.push(entry.dependency_check_platform);
        });
        return platforms;
    }

    function buildMcpPrompt(state, platform, platformB, platformEntry, platformBEntry, benchmarkEntry, needsCredentials) {
        var isCompare = state.goal === "compare";
        var mcpToolName = catalog.mcp.run_tool;
        var mcpPromptName = isCompare ? catalog.mcp.prompts.compare_platforms : catalog.mcp.prompts.benchmark_run;
        var dependencyPlatforms = dependencyCheckPlatforms([platformEntry, platformBEntry]);
        if (isCompare) {
            var compareLines = [
                "Use the BenchBox MCP server to compare " + platformLabel(platformEntry) + " and " + platformLabel(platformBEntry) + ".",
                "Steps:",
                "  1. Call the `" + catalog.mcp.list_tool + "` tool to confirm both platforms are available.",
                renderMcpDependencyStep("2", dependencyPlatforms, "selection"),
                "  3. Call `" + mcpToolName + "` for each platform with benchmark=" + state.benchmark + ", scale_factor=" + state.scale + ", dry_run=true" + (state["interface"] === "dataframe" ? ", mode=\"dataframe\"" : "") + ". Inspect both plans.",
                "  4. Use the `" + mcpPromptName + "` prompt with benchmark=" + state.benchmark + ", platforms=\"" + platform + "," + platformB + "\", scale_factor=" + state.scale + ".",
                "  5. Run the `" + mcpToolName + "` tool for each platform with the same benchmark and scale.",
                "  6. Summarise total runtime, per-query timing, and any failures."
            ];
            if (needsCredentials) appendDeploymentSafetyLines(compareLines, [platformEntry, platformBEntry], state.deployment);
            compareLines.push(needsCredentials ? "  • Stop and ask the user if credentials or config are missing — do not request secrets in chat." : "");
            return compareLines.filter(Boolean).join("\n");
        }
        var lines = [
            "Use the BenchBox MCP server to run " + (benchmarkEntry ? benchmarkEntry.label : state.benchmark) + " on " + platformLabel(platformEntry) + ".",
            "Steps:",
            "  1. Call the `" + catalog.mcp.list_tool + "` tool to confirm the platform is installed.",
            renderMcpDependencyStep("2", dependencyPlatforms, "platform"),
            "  3. Use the `" + mcpPromptName + "` prompt with platform=" + platform + ", benchmark=" + state.benchmark + ", scale_factor=" + state.scale + ".",
            "  4. Call `" + mcpToolName + "` with platform=" + platform + ", benchmark=" + state.benchmark + ", scale_factor=" + state.scale + ", dry_run=true" + (state["interface"] === "dataframe" ? ", mode=\"dataframe\"" : "") + ". Inspect the plan.",
            "  5. Run the `" + mcpToolName + "` tool with the same arguments and dry_run=false.",
            "  6. Summarise total runtime and any failures."
        ];
        if (needsCredentials) appendDeploymentSafetyLines(lines, [platformEntry], state.deployment);
        lines.push(needsCredentials ? "  • Stop and ask the user if credentials or config are missing — do not request secrets in chat." : "");
        return lines.filter(Boolean).join("\n");
    }

    function renderMcpDependencyStep(stepNumber, platforms, fallbackScope) {
        if (platforms.length > 0) {
            return "  " + stepNumber + ". Call " + renderMcpDependencyChecks(platforms) + ". Stop and report if anything is missing.";
        }
        return "  " + stepNumber + ". No optional connector dependency check is registered for this " + fallbackScope + "; confirm the install step completed successfully.";
    }

    function renderMcpDependencyChecks(platforms) {
        return platforms.map(function (platform) {
            return "`check_dependencies(platform=\"" + platform + "\")`";
        }).join(" and ");
    }

    function buildAgentPrompt(state, platform, platformB, platformEntry, platformBEntry, benchmarkEntry, cliCmd, dryRun, dryRunB, depChecks, needsCredentials) {
        var pretty = benchmarkEntry ? benchmarkEntry.label : state.benchmark;
        var platformSlug = state.goal === "compare" ? platform + "-vs-" + platformB : platform;
        var liveLogPath = logPath(state, platformSlug);
        var liveCmd = commandWithLogCapture(cliCmd, liveLogPath);
        var resultsPaths = catalog.templates.cli.results_paths;
        var showCli = catalog.templates.cli.show_cli;
        var step = 1;
        var lines = [];
        if (state.goal === "compare") {
            lines.push("Goal: compare " + platformLabel(platformEntry) + " and " + platformLabel(platformBEntry) + " on " + pretty + " at scale factor " + state.scale + " (" + state["interface"].toUpperCase() + " interface, " + state.deployment + " deployment).");
        } else {
            lines.push("Goal: run " + pretty + " on " + platformLabel(platformEntry) + " at scale factor " + state.scale + " (" + state["interface"].toUpperCase() + " interface, " + state.deployment + " deployment).");
        }
        lines.push("");
        lines.push("Steps:");
        var installs = installCommands([platformEntry, platformBEntry]);
        lines.push("  " + step++ + ". Install dependencies: `" + installs.join("` and `") + "`.");
        if (depChecks.length > 0) {
            lines.push("  " + step++ + ". Check dependencies: `" + depChecks.join("` and `") + "`. Stop and report if anything is missing.");
        } else {
            lines.push("  " + step++ + ". Check dependencies: no optional connector check is registered for this selection; confirm the install command completed successfully.");
        }
        lines.push("  " + step++ + ". Dry run first: `" + dryRun + "`" + (dryRunB ? " and `" + dryRunB + "`" : "") + ". Inspect the plan" + (dryRunB ? "s" : "") + ".");
        if (shouldAnnounceRun(state)) {
            lines.push("  " + step++ + ". Announce before running: command `" + liveCmd + "`, log path `" + liveLogPath + "`, expected runtime, and stop condition. Stop promptly on user interrupt or redirect.");
        }
        if (needsCredentials) {
            lines.push("  " + step++ + ". Make sure platform connection credentials/config are set outside this conversation (env vars, config files). Do NOT ask me to paste secrets here.");
            lines.push("  " + step++ + ". Once credentials are confirmed, run live: `" + liveCmd + "`.");
        } else {
            lines.push("  " + step++ + ". Run live: `" + liveCmd + "`.");
        }
        lines.push("  " + step++ + ". Discover & summarize: run `" + resultsPaths + "`, then run `" + showCli + "` with the result JSON path. Summarize total runtime, per-query timings, and failures from the result JSON.");
        lines.push("");
        lines.push(catalog.templates.cli.force_datagen_footer);
        return lines.join("\n");
    }

    function readStateFromForm() {
        return {
            goal: $("sel-goal").value,
            surface: $("sel-surface").value,
            "interface": $("sel-interface").value,
            deployment: $("sel-deployment").value,
            platform: $("sel-platform").value,
            platformA: $("sel-platformA").value,
            platformB: $("sel-platformB").value,
            benchmark: $("sel-benchmark").value,
            scale: $("sel-scale").value
        };
    }

    function applyAndRender(raw) {
        var state = normaliseState(raw);
        renderSelectors(state);
        renderOutput(state);
        writeStateToURL(state);
        return state;
    }

    function attachHandlers() {
        var form = $("prompts-form");
        form.addEventListener("change", function () {
            applyAndRender(readStateFromForm());
        });

        qs(".prompts-copy").forEach(function (btn) {
            btn.addEventListener("click", function () {
                var targetId = btn.getAttribute("data-copy-target");
                var node = $(targetId);
                if (!node) return;
                var text = node.textContent;
                var done = function (ok) {
                    var status = $("copy-status");
                    var label = COPY_LABELS[targetId] || targetId;
                    if (status) status.textContent = ok ? "Copied " + label : "Copy failed";
                    btn.textContent = ok ? "Copied" : "Copy";
                    setTimeout(function () { btn.textContent = "Copy"; }, 1500);
                };
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(text).then(function () { done(true); }, function () { done(false); });
                } else {
                    try {
                        var ta = document.createElement("textarea");
                        ta.value = text;
                        document.body.appendChild(ta);
                        ta.select();
                        document.execCommand("copy");
                        document.body.removeChild(ta);
                        done(true);
                    } catch (e) { done(false); }
                }
            });
        });
    }

    function init() {
        attachHandlers();
        applyAndRender(getStateFromURL());
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
