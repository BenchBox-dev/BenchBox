import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

export type TreeDigest = { sha256: string; totalBytes: number; totalFiles: number };

function directories(root: string): string[] {
  const found = [root];
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    if (entry.isSymbolicLink()) throw new Error(`symlink in digested tree: ${path.join(root, entry.name)}`);
    if (entry.isDirectory()) found.push(...directories(path.join(root, entry.name)));
  }
  return found;
}

export function treeDigest(root: string): TreeDigest {
  const hash = createHash("sha256");
  let totalBytes = 0;
  let totalFiles = 0;
  for (const directory of directories(root).sort()) {
    const files = readdirSync(directory, { withFileTypes: true })
      .filter((entry) => {
        if (entry.isSymbolicLink()) throw new Error(`symlink in digested tree: ${path.join(directory, entry.name)}`);
        return !entry.isDirectory();
      })
      .map((entry) => entry.name)
      .sort();
    for (const name of files) {
      const full = path.join(directory, name);
      const content = readFileSync(full);
      const relative = path.relative(root, full).split(path.sep).join("/");
      hash.update(`${relative}:${createHash("sha256").update(content).digest("hex")}:${statSync(full).size}\n`);
      totalBytes += content.length;
      totalFiles += 1;
    }
  }
  return { sha256: hash.digest("hex"), totalBytes, totalFiles };
}
