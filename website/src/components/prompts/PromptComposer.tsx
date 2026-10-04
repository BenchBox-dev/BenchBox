import { useEffect, useRef, useState } from "preact/hooks";
import {
  COPY_LABELS,
  benchmarksForInterface,
  buildOutput,
  normaliseState,
  platformsForFilters,
  searchFromState,
  stateFromSearch,
  type Catalog,
  type Entry,
  type RawState,
  type SelectorKey,
  type State,
} from "../../lib/prompt-builder.ts";

type Props = { catalog: Catalog };

function Field(props: {
  id: SelectorKey;
  label: string;
  options: Entry[];
  value: string | undefined;
  mode?: "test_one" | "compare";
  hidden?: boolean;
  onChange: (key: SelectorKey, value: string) => void;
}) {
  return (
    <label class="prompts-field" data-mode={props.mode} hidden={props.hidden}>
      <span>{props.label}</span>
      <select id={`sel-${props.id}`} name={props.id} value={props.value ?? ""} onChange={(event) => props.onChange(props.id, event.currentTarget.value)}>
        {(props.hidden ? [] : props.options).map((option) => (
          <option key={option.id} value={option.id}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

async function writeClipboard(text: string): Promise<boolean> {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      return false;
    }
  }
  try {
    const area = document.createElement("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    document.body.removeChild(area);
    return true;
  } catch {
    return false;
  }
}

function CopyButton(props: { target: string; text: string; onStatus: (message: string) => void }) {
  const [label, setLabel] = useState("Copy");
  const timer = useRef<number | undefined>(undefined);
  const copy = async () => {
    const ok = await writeClipboard(props.text);
    props.onStatus(ok ? `Copied ${COPY_LABELS[props.target] ?? props.target}` : "Copy failed");
    setLabel(ok ? "Copied" : "Copy");
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      setLabel("Copy");
      props.onStatus("");
    }, 1500);
  };
  return (
    <button type="button" class="prompts-copy" data-copy-target={props.target} onClick={copy}>
      {label}
    </button>
  );
}

export default function PromptComposer({ catalog }: Props) {
  const [raw, setRaw] = useState<RawState>({});
  const [status, setStatus] = useState("");
  const [ready, setReady] = useState(false);
  const state: State = normaliseState(catalog, raw);
  const output = buildOutput(catalog, state);
  const isCompare = state.goal === "compare";
  const pool = platformsForFilters(catalog, state.interface, state.deployment);

  const apply = (next: RawState) => {
    const normalised = normaliseState(catalog, next);
    const merged: RawState = { ...next };
    for (const [key, value] of Object.entries(normalised)) if (value !== undefined) merged[key as SelectorKey] = value;
    setRaw(merged);
    return normalised;
  };

  useEffect(() => {
    apply(stateFromSearch(window.location.search));
    setReady(true);
  }, []);

  useEffect(() => {
    if (!ready) return;
    const search = searchFromState(state);
    window.history.replaceState({}, "", window.location.pathname + (search ? `?${search}` : ""));
  });

  const onChange = (key: SelectorKey, value: string) => {
    const current: RawState = { ...raw };
    for (const [name, entry] of Object.entries(state)) if (entry !== undefined) current[name as SelectorKey] = entry;
    apply({ ...current, [key]: value });
  };

  const scales = catalog.scales.map((scale) => ({ id: String(scale), label: String(scale) }));
  const poolB = pool.filter((p) => p.id !== state.platformA);

  return (
    <>
      <form class="prompts-form" id="prompts-form" aria-label="Prompt builder" onSubmit={(event) => event.preventDefault()}>
        <div class="prompts-grid">
          <Field id="goal" label="Goal" options={catalog.goals} value={state.goal} onChange={onChange} />
          <Field id="surface" label="Surface" options={catalog.surfaces} value={state.surface} onChange={onChange} />
          <Field id="interface" label="Interface" options={catalog.interfaces} value={state.interface} onChange={onChange} />
          <Field id="deployment" label="Deployment" options={catalog.deployments} value={state.deployment} onChange={onChange} />
          <Field id="platform" label="Platform" options={pool} value={state.platform} mode="test_one" hidden={isCompare} onChange={onChange} />
          <Field id="platformA" label="Platform A" options={pool} value={state.platformA} mode="compare" hidden={!isCompare} onChange={onChange} />
          <Field id="platformB" label="Platform B" options={poolB.length ? poolB : pool} value={state.platformB} mode="compare" hidden={!isCompare} onChange={onChange} />
          <Field id="benchmark" label="Benchmark" options={benchmarksForInterface(catalog, state.interface)} value={state.benchmark} onChange={onChange} />
          <Field id="scale" label="Scale" options={scales} value={state.scale} onChange={onChange} />
        </div>
      </form>

      <section class="prompts-output">
        <div class="prompts-block" id="block-prompt">
          <header>
            <h2>📋 Agent prompt</h2>
            <CopyButton target="prompt-text" text={output.prompt} onStatus={setStatus} />
          </header>
          <pre id="prompt-text">{output.prompt}</pre>
        </div>

        <div class="prompts-block" id="block-mcp-setup" hidden={!output.showMcpSetup}>
          <header>
            <h2>🔧 MCP server config</h2>
            <CopyButton target="mcp-setup-text" text={output.mcpSetup} onStatus={setStatus} />
          </header>
          <p class="prompts-block-hint">
            Add this entry to your agent's MCP config (e.g. <code>~/.codex/config.toml</code> or <code>claude_desktop_config.json</code>):
          </p>
          <pre id="mcp-setup-text">{output.mcpSetup}</pre>
        </div>

        <div class="prompts-block prompts-block--warn" id="block-cloud-safety" hidden={output.safety.length === 0}>
          <header>
            <h2>Credential safety</h2>
          </header>
          <ul id="cloud-safety-list">
            {output.safety.map((text) => (
              <li key={text}>{text}</li>
            ))}
          </ul>
        </div>

        <div role="status" aria-live="polite" class="prompts-aria" id="copy-status">
          {status}
        </div>
      </section>
    </>
  );
}
