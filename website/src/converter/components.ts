import type { ComponentName } from "./types.ts";

export const COMPONENT_MODULES: Readonly<Record<ComponentName, string>> = {
  Callout: "src/components/docs/Callout.astro",
  Mermaid: "src/components/docs/Mermaid.astro",
  Embed: "src/components/docs/Embed.astro",
};
