import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import * as pagefind from "pagefind";

const site = path.resolve(process.argv[2] ?? "dist");

function* htmlFiles(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) yield* htmlFiles(full);
    else if (entry.name.endsWith(".html")) yield full;
  }
}

const { index, errors: createErrors } = await pagefind.createIndex();
if (!index) throw new Error(`pagefind createIndex failed: ${createErrors.join("; ")}`);

let indexed = 0;
for (const section of ["docs", "blog"]) {
  for (const file of htmlFiles(path.join(site, section))) {
    const url = `/${path.relative(site, file).split(path.sep).join("/")}`;
    const content = readFileSync(file, "utf-8");
    if (/http-equiv="refresh"/i.test(content)) continue;
    const { errors } = await index.addHTMLFile({ sourcePath: path.relative(site, file), url, content });
    if (errors.length > 0) throw new Error(`pagefind failed on ${url}: ${errors.join("; ")}`);
    indexed += 1;
  }
}

const { errors } = await index.writeFiles({ outputPath: path.join(site, "pagefind") });
if (errors.length > 0) throw new Error(`pagefind write failed: ${errors.join("; ")}`);
await pagefind.close();
console.log(`pagefind indexed ${indexed} pages`);
