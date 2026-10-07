import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";

// Renderer working directories; never documentation.
export const RENDERER_ROOTS: ReadonlySet<string> = new Set(["_build", "_tags", "_static", "_templates"]);

// docs/publish-exclusions.txt lists the unpublished documentation paths. It lives
// with the docs, so the build reads whatever list arrives with the pages.
// docs/conf.py applies the same file to Sphinx.
export const EXCLUSIONS_FILE = "publish-exclusions.txt";

export type PublishExclusions = { roots: ReadonlySet<string>; files: ReadonlySet<string> };

function readListFile(file: string): string[] | null {
  let text: string;
  try {
    text = readFileSync(file, "utf-8");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
  return text.split("\n").map((line) => line.trim()).filter((line) => line !== "" && !line.startsWith("#"));
}

export function readPublishExclusions(docsRoot: string): PublishExclusions {
  const entries = readListFile(path.join(docsRoot, EXCLUSIONS_FILE)) ?? [];
  return {
    roots: new Set(entries.filter((entry) => entry.endsWith("/")).map((entry) => entry.slice(0, -1))),
    files: new Set(entries.filter((entry) => !entry.endsWith("/"))),
  };
}

// Pages under these directories are published only when docs/publish-allowlist.txt
// lists them, so a new maintainer document stays off the site until someone decides
// it is for users. docs/conf.py applies the same list to Sphinx.
export const PUBLISH_LIST_ROOTS: readonly string[] = ["development", "operations"];
export const PUBLISH_LIST_FILE = "publish-allowlist.txt";

export type DocSourceFile = { absolute: string; relative: string };

export function readPublishList(docsRoot: string): ReadonlySet<string> {
  return new Set(readListFile(path.join(docsRoot, PUBLISH_LIST_FILE)) ?? []);
}

export function underPublishListRoot(relative: string): boolean {
  return PUBLISH_LIST_ROOTS.some((root) => relative.startsWith(`${root}/`));
}

function compareNames(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

function walk(root: string, directory: string, suffix: string, excluded: PublishExclusions, published: ReadonlySet<string>, found: DocSourceFile[]): void {
  const entries = readdirSync(directory, { withFileTypes: true }).sort((a, b) => compareNames(a.name, b.name));
  for (const entry of entries) {
    const absolute = path.join(directory, entry.name);
    const relative = path.relative(root, absolute).split(path.sep).join("/");
    if (entry.name.startsWith(".#")) continue;
    if (entry.isDirectory()) {
      if (directory === root && (RENDERER_ROOTS.has(entry.name) || excluded.roots.has(entry.name))) continue;
      if (entry.name === "_sources" || entry.name.endsWith(".lproj")) continue;
      walk(root, absolute, suffix, excluded, published, found);
    } else if (entry.name.endsWith(suffix) && !excluded.files.has(relative) && (!underPublishListRoot(relative) || published.has(relative))) {
      found.push({ absolute, relative });
    }
  }
}

export function listDocSources(docsRoot: string, suffix: ".md" | ".rst" = ".md"): DocSourceFile[] {
  const found: DocSourceFile[] = [];
  walk(docsRoot, docsRoot, suffix, readPublishExclusions(docsRoot), readPublishList(docsRoot), found);
  return found;
}
