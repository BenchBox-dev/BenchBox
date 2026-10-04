import { cpSync, existsSync, mkdirSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { unified } from "@astrojs/markdown-remark";
import starlight from "@astrojs/starlight";
import type { AstroIntegration } from "astro";
import { defineConfig } from "astro/config";
import { mystLite } from "./src/plugins/myst-lite.ts";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const publishStatic = (): AstroIntegration => ({
  name: "benchbox-publish-static",
  hooks: {
    "astro:build:done": ({ dir }) => {
      const out = fileURLToPath(dir);
      const explorerDist = path.join(repoRoot, "results-explorer", "dist");
      if (!existsSync(explorerDist)) throw new Error(`Results Explorer build is missing: ${explorerDist}`);
      cpSync(explorerDist, path.join(out, "results"), { recursive: true });
      cpSync(path.join(repoRoot, "landing", "hero.png"), path.join(out, "hero.png"));
      const images = path.join(repoRoot, "docs", "blog", "images");
      mkdirSync(path.join(out, "_images"), { recursive: true });
      for (const name of readdirSync(images)) cpSync(path.join(images, name), path.join(out, "_images", name));
    },
  },
});

export default defineConfig({
  site: "https://benchbox.dev",
  trailingSlash: "ignore",
  build: { format: "file" },
  markdown: { processor: unified({ remarkPlugins: [mystLite] }) },
  integrations: [
    starlight({
      title: "BenchBox",
      pagefind: false,
      disable404Route: true,
      lastUpdated: false,
      customCss: ["./src/styles/tokens.css", "./src/styles/shell.css", "./src/styles/starlight-map.css"],
      components: {
        Header: "./src/components/starlight/Header.astro",
        ThemeProvider: "./src/components/starlight/ThemeProvider.astro",
        ThemeSelect: "./src/components/starlight/Empty.astro",
      },
      sidebar: [
        {
          label: "Usage",
          items: [{ label: "Getting Started in 5 Minutes", link: "/docs/usage/getting-started.html" }],
        },
        {
          label: "Benchmarks",
          items: [
            { label: "Industry Benchmarks", link: "/docs/benchmarks/industry-benchmarks.html" },
            { label: "TPC-H Q1", link: "/docs/benchmarks/queries/tpch/q1.html" },
          ],
        },
        {
          label: "Reference",
          items: [{ label: "Additional Utilities", link: "/docs/reference/python-api/additional-utilities.html" }],
        },
      ],
    }),
    publishStatic(),
  ],
});
