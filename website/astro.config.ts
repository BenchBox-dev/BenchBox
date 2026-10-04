import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { unified } from "@astrojs/markdown-remark";
import preact from "@astrojs/preact";
import starlight from "@astrojs/starlight";
import { ExpressiveCodeTheme } from "@astrojs/starlight/expressive-code";
import type { AstroIntegration } from "astro";
import { defineConfig } from "astro/config";
import type { SidebarManifest } from "./src/converter/sidebar.ts";
import { toStarlightSidebar } from "./src/converter/sidebar.ts";
import { renderRobots, renderSitemap, sitemapPathForFile } from "./src/lib/page-meta.ts";
import { docutilsQuotes, SMARTYPANTS } from "./src/lib/smartypants.ts";
import { explorerReceipt, treeDigest } from "./src/lib/tree-digest.ts";
import { headingIds } from "./src/plugins/heading-ids.ts";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const cobalt2 = ExpressiveCodeTheme.fromJSONString(readFileSync(path.join(repoRoot, "website", "src", "lib", "cobalt2-theme.json"), "utf-8"));

function generatedSidebar() {
  const manifest = path.join(repoRoot, "website", ".generated", "manifest", "sidebar.json");
  if (!existsSync(manifest) && process.env.BENCHBOX_ALLOW_EMPTY_SIDEBAR === "1") return [];
  if (!existsSync(manifest)) throw new Error(`Converter output is missing: ${manifest}. Run npm run convert first.`);
  return toStarlightSidebar(JSON.parse(readFileSync(manifest, "utf-8")) as SidebarManifest);
}

function htmlFiles(root: string, relative = ""): string[] {
  return readdirSync(path.join(root, relative), { withFileTypes: true }).flatMap((entry) => {
    const child = path.posix.join(relative, entry.name);
    if (entry.isDirectory()) return entry.name === "assets" || entry.name === "pagefind" || entry.name === "_astro" ? [] : htmlFiles(root, child);
    return entry.name.endsWith(".html") ? [child] : [];
  });
}

const sitemapOwnedByPublishStatic: AstroIntegration = { name: "@astrojs/sitemap", hooks: {} };

const publishStatic = (): AstroIntegration => ({
  name: "benchbox-publish-static",
  hooks: {
    "astro:build:done": ({ dir }) => {
      const out = fileURLToPath(dir);
      const explorerDist = path.join(repoRoot, "results-explorer", "dist");
      if (!existsSync(explorerDist)) throw new Error(`Results Explorer build is missing: ${explorerDist}`);
      const sourceDigest = treeDigest(explorerDist);
      cpSync(explorerDist, path.join(out, "results"), { recursive: true });
      const receipts = path.join(repoRoot, "website", ".receipts");
      mkdirSync(receipts, { recursive: true });
      writeFileSync(
        path.join(receipts, "explorer-artifact.json"),
        `${JSON.stringify(explorerReceipt(sourceDigest, treeDigest(path.join(out, "results"))), null, 2)}\n`,
      );
      cpSync(path.join(repoRoot, "landing", "hero.png"), path.join(out, "hero.png"));
      const images = path.join(repoRoot, "docs", "blog", "images");
      mkdirSync(path.join(out, "_images"), { recursive: true });
      cpSync(path.join(repoRoot, "docs", "CNAME"), path.join(out, "CNAME"));
      writeFileSync(path.join(out, ".nojekyll"), "");
      writeFileSync(path.join(out, "robots.txt"), renderRobots());
      const pages = htmlFiles(out).filter((file) => file !== "404.html");
      writeFileSync(path.join(out, "sitemap.xml"), renderSitemap(pages.map(sitemapPathForFile)));
      for (const name of readdirSync(images)) cpSync(path.join(images, name), path.join(out, "_images", name));
    },
  },
});

export default defineConfig({
  site: "https://benchbox.dev",
  trailingSlash: "ignore",
  build: { format: "file" },
  markdown: { processor: unified({ remarkPlugins: [headingIds, docutilsQuotes], smartypants: SMARTYPANTS }) },
  integrations: [
    sitemapOwnedByPublishStatic,
    preact(),
    starlight({
      title: "BenchBox",
      pagefind: false,
      disable404Route: true,
      lastUpdated: false,
      routeMiddleware: "./src/starlight-route.ts",
      customCss: ["../landing/shared/site-tokens.css", "../landing/shared/site-shell.css", "./src/styles/shell.css", "./src/styles/starlight-map.css"],
      components: {
        Header: "./src/components/starlight/Header.astro",
        PageTitle: "./src/components/starlight/PageTitle.astro",
        Footer: "./src/components/starlight/Footer.astro",
        ThemeProvider: "./src/components/starlight/ThemeProvider.astro",
        ThemeSelect: "./src/components/starlight/Empty.astro",
      },
      sidebar: generatedSidebar(),
      expressiveCode: { themes: [cobalt2], useStarlightUiThemeColors: false, minSyntaxHighlightingColorContrast: 4.5 },
    }),
    publishStatic(),
  ],
});
