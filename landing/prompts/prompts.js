/* /prompts/ landing route — state + rendering for the prompt builder.
 *
 * Reads `window.__BENCHBOX_PROMPT_CATALOG__` (set by catalog.generated.js),
 * syncs selection state to URL query parameters, filters platform options
 * by selected interface + deployment, and renders agent / MCP output
 * blocks. No framework — plain vanilla JS so the page stays a static
 * deploy under `landing/`.
 *
 * URL parameters (pinned by `landing-prompts-static-route` w3):
 *   goal, agent, surface, interface, deployment, platform, platformA,
 *   platformB, benchmark, scale.
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

    var SELECTORS = ["goal", "agent", "surface", "interface", "deployment", "platform", "platformA", "platformB", "benchmark", "scale"];
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
        ["goal", "agent", "surface", "interface", "deployment", "benchmark"].forEach(function (k) {
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

        if (state.goal === "compare") {
            var pair = deriveCompareDefaults(Object.assign({}, raw, state));
            state.platformA = pair[0];
            state.platformB = pair[1];
            state.platform = undefined;
        } else {
            var p = raw.platform && pool.some(function (pp) { return pp.id === raw.platform; }) ? raw.platform : (pool[0] && pool[0].id) || defaults.platform;
            state.platform = p;
            state.platformA = undefined;
            state.platformB = undefined;
        }
        return state;
    }

    function renderSelectors(state) {
        fillSelect($("sel-goal"), catalog.goals, state.goal);
        fillSelect($("sel-agent"), catalog.agents, state.agent);
        fillSelect($("sel-surface"), catalog.surfaces, state.surface);
        fillSelect($("sel-interface"), catalog.interfaces, state["interface"]);
        fillSelect($("sel-deployment"), catalog.deployments, state.deployment);
        fillSelect($("sel-benchmark"), benchmarksForInterface(state["interface"]), state.benchmark);
        fillSelect($("sel-scale"), catalog.scales.map(function (s) { return { id: String(s), label: String(s) }; }), state.scale);
        syncAgentHint(state);

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
        // Decide which output blocks to show by agent + surface
        var isCompare = state.goal === "compare";
        var platform = isCompare ? state.platformA : state.platform;
        var platformB = isCompare ? state.platformB : null;
        var platformEntry = findById(catalog.platforms, platform);
        var platformBEntry = isCompare ? findById(catalog.platforms, platformB) : null;
        var benchmarkEntry = findById(catalog.benchmarks, state.benchmark);
        var managed = state.deployment === "managed";

        var cliCmd = isCompare
            ? renderTemplate(catalog.templates.cli.compare, { platform_a: platform, platform_b: platformB, benchmark: state.benchmark, scale: state.scale })
            : renderTemplate(catalog.templates.cli.test_one, { platform: platform, benchmark: state.benchmark, scale: state.scale });

        var depCheck = renderTemplate(catalog.templates.cli.dependency_check, { platform: platform });
        var depCheckB = isCompare ? renderTemplate(catalog.templates.cli.dependency_check, { platform: platformB }) : null;
        var dryRun = isCompare
            ? cliCmd + " --dry-run"
            : renderTemplate(catalog.templates.cli.dry_run, { platform: platform, benchmark: state.benchmark, scale: state.scale });

        // MCP setup block
        var mcpTomlLines = [
            "[mcp_servers.benchbox]",
            'command = "uv"',
            'args = ["run", "--", "python", "-m", "benchbox.mcp"]'
        ];
        $("mcp-setup-text").textContent = mcpTomlLines.join("\n");

        var mcpToolName = catalog.mcp.run_tool;
        var mcpPromptName = isCompare ? catalog.mcp.prompts.compare_platforms : catalog.mcp.prompts.benchmark_run;
        var mcpPromptText;
        if (isCompare) {
            mcpPromptText = [
                "Use the BenchBox MCP server to compare " + platformLabel(platformEntry) + " and " + platformLabel(platformBEntry) + ".",
                "Steps:",
                "  1. Call the `" + catalog.mcp.list_tool + "` tool to confirm both platforms are available.",
                "  2. Use the `" + mcpPromptName + "` prompt with benchmark=" + state.benchmark + ", platforms=\"" + platform + "," + platformB + "\", scale_factor=" + state.scale + ".",
                "  3. Run the `" + mcpToolName + "` tool for each platform with the same benchmark and scale.",
                "  4. Summarise total runtime, per-query timing, and any failures.",
                managed ? "  • Stop and ask the user if credentials or config for a managed platform are missing — do not request secrets in chat." : ""
            ].filter(Boolean).join("\n");
        } else {
            mcpPromptText = [
                "Use the BenchBox MCP server to run " + (benchmarkEntry ? benchmarkEntry.label : state.benchmark) + " on " + platformLabel(platformEntry) + ".",
                "Steps:",
                "  1. Call the `" + catalog.mcp.list_tool + "` tool to confirm the platform is installed.",
                "  2. Use the `" + mcpPromptName + "` prompt with platform=" + platform + ", benchmark=" + state.benchmark + ", scale_factor=" + state.scale + ".",
                "  3. Run the `" + mcpToolName + "` tool with the same arguments.",
                "  4. Summarise total runtime and any failures.",
                managed ? "  • Stop and ask the user if credentials or config are missing — do not request secrets in chat." : ""
            ].filter(Boolean).join("\n");
        }

        $("prompt-text").textContent = state.surface === "mcp"
            ? mcpPromptText
            : buildAgentPrompt(state, platform, platformB, platformEntry, platformBEntry, benchmarkEntry, cliCmd, dryRun, depCheck, depCheckB, managed);

        // Visibility rules:
        // - Agent prompt: always shown.
        // - MCP setup: shown for surface=MCP.
        // - Cloud safety: shown for deployment=managed.
        $("block-prompt").hidden = false;
        $("block-mcp-setup").hidden = state.surface !== "mcp";

        var safetyList = $("cloud-safety-list");
        safetyList.innerHTML = "";
        if (managed && platformEntry && platformEntry.safety_terms) {
            ["dependency", "dry_run", "no_secrets"].forEach(function (k) {
                if (platformEntry.safety_terms[k]) {
                    var li = document.createElement("li");
                    li.textContent = platformEntry.safety_terms[k];
                    safetyList.appendChild(li);
                }
            });
            $("block-cloud-safety").hidden = false;
        } else {
            $("block-cloud-safety").hidden = true;
        }
    }

    function platformLabel(entry) { return entry ? (entry.label || entry.id) : "the selected platform"; }

    function renderTemplate(tpl, vars) {
        return tpl.replace(/\{([a-z_]+)\}/g, function (_, k) {
            return vars[k] !== undefined ? String(vars[k]) : "{" + k + "}";
        });
    }

    function syncAgentHint(state) {
        var hint = $("agent-hint");
        if (!hint) return;
        var agent = findById(catalog.agents, state.agent);
        hint.textContent = agent && agent.hint ? agent.hint : "";
        hint.hidden = !(state.agent === "generic" && hint.textContent);
    }

    function buildAgentPrompt(state, platform, platformB, platformEntry, platformBEntry, benchmarkEntry, cliCmd, dryRun, depCheck, depCheckB, managed) {
        var pretty = benchmarkEntry ? benchmarkEntry.label : state.benchmark;
        var agentLine;
        if (state.agent === "codex") {
            agentLine = "You are Codex with shell access. Help me run a BenchBox benchmark end-to-end.";
        } else if (state.agent === "claude-code") {
            agentLine = "You are Claude Code with shell access. Help me run a BenchBox benchmark end-to-end.";
        } else {
            agentLine = "You are a coding agent (e.g. Pi, OpenCode, Cline, Aider) with shell access. Help me run a BenchBox benchmark end-to-end.";
        }

        var lines = [agentLine, ""];
        if (state.goal === "compare") {
            lines.push("Goal: compare " + platformLabel(platformEntry) + " and " + platformLabel(platformBEntry) + " on " + pretty + " at scale factor " + state.scale + " (" + state["interface"].toUpperCase() + " interface, " + state.deployment + " deployment).");
        } else {
            lines.push("Goal: run " + pretty + " on " + platformLabel(platformEntry) + " at scale factor " + state.scale + " (" + state["interface"].toUpperCase() + " interface, " + state.deployment + " deployment).");
        }
        lines.push("");
        lines.push("Steps:");
        lines.push("  1. Install: `uv add 'benchbox[" + platform + "]'" + (platformB ? " 'benchbox[" + platformB + "]'" : "") + "`.");
        lines.push("  2. Check dependencies: `" + depCheck + "`" + (depCheckB ? " and `" + depCheckB + "`" : "") + ". Stop and report if anything is missing.");
        lines.push("  3. Dry run first: `" + dryRun + "`. Inspect the plan.");
        if (managed) {
            lines.push("  4. Make sure managed-platform credentials are configured outside this conversation (env vars, config files). Do NOT ask me to paste secrets here.");
            lines.push("  5. Once credentials are confirmed, run live: `" + cliCmd + "`.");
        } else {
            lines.push("  4. Run live: `" + cliCmd + "`.");
        }
        lines.push("  " + (managed ? "6" : "5") + ". Summarise the result: total runtime, per-query timing, and any failures.");
        return lines.join("\n");
    }

    function readStateFromForm() {
        return {
            goal: $("sel-goal").value,
            agent: $("sel-agent").value,
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
