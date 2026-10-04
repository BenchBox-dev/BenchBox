import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { unified } from "@astrojs/markdown-remark";
import sitemap from "@astrojs/sitemap";
import starlight from "@astrojs/starlight";
import { ExpressiveCodeTheme } from "@astrojs/starlight/expressive-code";
import type { AstroIntegration } from "astro";
import { defineConfig } from "astro/config";
import type { SidebarManifest } from "./src/converter/sidebar.ts";
import { toStarlightSidebar } from "./src/converter/sidebar.ts";
import { htmlSitemapUrl } from "./src/lib/sitemap-url.ts";
import { headingIds } from "./src/plugins/heading-ids.ts";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const cobalt2 = ExpressiveCodeTheme.fromJSONString(readFileSync(path.join(repoRoot, "website", "src", "lib", "cobalt2-theme.json"), "utf-8"));

function generatedSidebar() {
  const manifest = path.join(repoRoot, "website", ".generated", "manifest", "sidebar.json");
  if (!existsSync(manifest) && process.env.BENCHBOX_ALLOW_EMPTY_SIDEBAR === "1") return [];
  if (!existsSync(manifest)) throw new Error(`Converter output is missing: ${manifest}. Run npm run convert first.`);
  return toStarlightSidebar(JSON.parse(readFileSync(manifest, "utf-8")) as SidebarManifest);
}

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
  markdown: { processor: unified({ remarkPlugins: [headingIds] }) },
  integrations: [
    sitemap({ serialize: (item) => ({ ...item, url: htmlSitemapUrl(item.url) }) }),
    starlight({
      title: "BenchBox",
      pagefind: false,
      disable404Route: true,
      lastUpdated: false,
      customCss: ["../landing/shared/site-tokens.css", "./src/styles/shell.css", "./src/styles/starlight-map.css"],
      components: {
        Header: "./src/components/starlight/Header.astro",
        ThemeProvider: "./src/components/starlight/ThemeProvider.astro",
        ThemeSelect: "./src/components/starlight/Empty.astro",
      },
      sidebar: generatedSidebar(),
      expressiveCode: { themes: [cobalt2], useStarlightUiThemeColors: false, minSyntaxHighlightingColorContrast: 0 },
    }),
    publishStatic(),
  ],
});
