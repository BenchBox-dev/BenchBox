import { createHash } from "node:crypto";
import { cpSync, existsSync, mkdirSync } from "node:fs";
import { deflateSync } from "node:zlib";
import path from "node:path";

export type LegacyFiles = { downloads: string[]; images: string[] };

export function downloadUrlPath(relative: string): string {
  const digest = createHash("md5").update(relative).digest("hex");
  return `/docs/_downloads/${digest}/${path.posix.basename(relative)}`;
}

export function imageUrlPath(name: string): string {
  return `/docs/_images/${name}`;
}

export function publishLegacyFiles(files: LegacyFiles, docsRoot: string, out: string): number {
  const copies = [
    ...files.downloads.map((relative) => ({ from: path.resolve(docsRoot, relative), to: downloadUrlPath(relative) })),
    ...files.images.map((name) => ({ from: path.join(docsRoot, "blog", "images", name), to: imageUrlPath(name) })),
  ];
  for (const copy of copies) {
    if (!existsSync(copy.from)) throw new Error(`legacy public file is missing: ${copy.from}`);
    const target = path.join(out, copy.to);
    mkdirSync(path.dirname(target), { recursive: true });
    cpSync(copy.from, target);
  }
  return copies.length;
}

export const REDIRECT_PAGES: Readonly<Record<string, string>> = {
  "docs/genindex.html": "/docs/api.html",
  "docs/search.html": "/docs/",
  "docs/blog.html": "/blog/",
};

export type InventoryEntry = { name: string; role: "doc" | "label"; uri: string; title: string };

export function renderObjectsInventory(entries: readonly InventoryEntry[], project: string, version: string): Buffer {
  const header = `# Sphinx inventory version 2\n# Project: ${project}\n# Version: ${version}\n# The remainder of this file is compressed using zlib.\n`;
  const lines = entries.map((entry) => `${entry.name} std:${entry.role} -1 ${entry.uri} ${entry.title.replace(/\s+/g, " ").trim() || "-"}\n`);
  return Buffer.concat([Buffer.from(header, "utf-8"), deflateSync(Buffer.from(lines.join(""), "utf-8"))]);
}
