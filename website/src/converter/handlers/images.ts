import { existsSync, statSync } from "node:fs";
import path from "node:path";
import { ConverterError, UnknownConstructError } from "../errors.ts";
import type { SyntaxHandler } from "../types.ts";

const EXTERNAL = /^([a-z][a-z0-9+.-]*:|\/\/)/i;
const IMAGE_DIRECTORY = "blog/images";
export const IMAGE_URL_PREFIX = "/_images";

export const imageSyntax: SyntaxHandler<"image"> = {
  kind: "syntax",
  name: "image",
  handle(node, at, context) {
    if (node.type === "imageReference") throw new UnknownConstructError(at.file, at.line, "syntax:image-reference");
    if (EXTERNAL.test(node.url)) return [node];
    if (node.url === "" || node.url.startsWith("/")) throw new ConverterError(at.file, at.line, `image ${JSON.stringify(node.url)} must be a path relative to the document`);
    const target = path.resolve(context.docsRoot, path.dirname(context.file), decodeURI(node.url.split(/[?#]/)[0]));
    if (!existsSync(target) || !statSync(target).isFile()) throw new ConverterError(at.file, at.line, `image file not found: ${node.url}`);
    const relative = path.relative(context.docsRoot, target).split(path.sep).join("/");
    if (path.posix.dirname(relative) !== IMAGE_DIRECTORY) {
      throw new ConverterError(at.file, at.line, `image ${node.url} is not published: images must live directly in docs/${IMAGE_DIRECTORY}/`);
    }
    return [{ ...node, url: `${IMAGE_URL_PREFIX}/${encodeURI(path.posix.basename(relative))}` }];
  },
};
