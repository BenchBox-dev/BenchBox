import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import type { Loader } from "astro/loaders";
import { docutilsSlug } from "../lib/docutils-slug.ts";

const REPO_ROOT = path.resolve(process.cwd(), "..");

export type DocSource = { id: string; file: string; summary?: string };

type Frontmatter = Record<string, string>;

function splitFrontmatter(raw: string): { data: Frontmatter; body: string } {
  const match = raw.match(/^---\n([\s\S]*?)\n---\n/);
  if (!match) return { data: {}, body: raw };
  const data: Frontmatter = {};
  for (const line of match[1].split("\n")) {
    const pair = line.match(/^([A-Za-z_][\w-]*):\s*(.*)$/);
    if (pair) data[pair[1]] = pair[2].replace(/^"(.*)"$/, "$1");
  }
  return { data, body: raw.slice(match[0].length) };
}

function splitTitle(body: string): { title: string; body: string } {
  const lines = body.split("\n");
  const index = lines.findIndex((line) => /^# /.test(line));
  if (index < 0) return { title: "Untitled", body };
  const title = lines[index].slice(2).trim();
  lines.splice(index, 1);
  return { title, body: lines.join("\n") };
}

function rstToHtml(file: string) {
  const out = execFileSync("uv", ["run", "python", path.join(process.cwd(), "scripts", "rst_to_html.py"), file], {
    cwd: REPO_ROOT,
    maxBuffer: 64 * 1024 * 1024,
  });
  return JSON.parse(out.toString("utf-8")) as {
    title: string;
    html: string;
    headings: { depth: number; slug: string; text: string }[];
  };
}

export function docsLoader(sources: DocSource[]): Loader {
  return {
    name: "benchbox-docs-loader",
    async load({ store, renderMarkdown, parseData, watcher }) {
      store.clear();
      for (const source of sources) {
        const file = path.isAbsolute(source.file) ? source.file : path.join(REPO_ROOT, source.file);
        watcher?.add(file);
        if (file.endsWith(".rst")) {
          const converted = rstToHtml(file);
          const data = await parseData({
            id: source.id,
            data: { title: converted.title, description: source.summary, sourcePath: path.relative(REPO_ROOT, file) },
          });
          store.set({
            id: source.id,
            data,
            rendered: {
              html: `<span id="${docutilsSlug(converted.title)}"></span>\n${converted.html}`,
              metadata: { headings: converted.headings },
            },
          });
          continue;
        }
        const raw = readFileSync(file, "utf-8");
        const front = splitFrontmatter(raw);
        const { title, body } = splitTitle(front.body);
        const data = await parseData({
          id: source.id,
          data: {
            ...front.data,
            title,
            description: front.data.meta_description ?? source.summary,
            sourcePath: path.relative(REPO_ROOT, file),
          },
        });
        const alias = `<span id="${docutilsSlug(title)}"></span>\n\n`;
        const rendered = await renderMarkdown(alias + body, { fileURL: new URL(`file://${file}`) });
        store.set({ id: source.id, data, body, rendered });
      }
    },
  };
}
