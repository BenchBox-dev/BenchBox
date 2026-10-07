import { NotYetImplementedError, UnknownConstructError } from "../errors.ts";
import type { FrontMatterHandler } from "../types.ts";

const PASSTHROUGH = ["author", "blogpost", "created", "date", "orphan", "owner", "post_number", "series", "status", "type"] as const;

const SUPPORTED_EXTENSIONS = new Set(["deflist", "attrs_block"]);

export const passthroughFrontMatter: FrontMatterHandler = {
  kind: "front-matter",
  keys: PASSTHROUGH,
  handle(key, value, _at, context) {
    context.setPageData(key, value);
  },
};

export const titleFrontMatter: FrontMatterHandler = {
  kind: "front-matter",
  keys: ["title"],
  handle(_key, value, _at, context) {
    context.setPageData("title", String(value));
  },
};

export const descriptionFrontMatter: FrontMatterHandler = {
  kind: "front-matter",
  keys: ["meta_description"],
  handle(_key, value, _at, context) {
    context.setPageData("description", String(value));
  },
};

export const tagsFrontMatter: FrontMatterHandler = {
  kind: "front-matter",
  keys: ["tags"],
  handle(_key, value, _at, context) {
    const items = Array.isArray(value) ? value.map(String) : String(value).split(",");
    context.addTags(items.map((tag) => tag.trim()).filter(Boolean));
  },
};

export const mystFrontMatter: FrontMatterHandler = {
  kind: "front-matter",
  keys: ["myst"],
  handle(_key, value, at) {
    const settings = (value && typeof value === "object" ? value : {}) as Record<string, unknown>;
    for (const key of Object.keys(settings)) {
      if (key !== "enable_extensions") throw new UnknownConstructError(at.file, at.line, `front-matter:myst.${key}`);
    }
    const extensions = Array.isArray(settings.enable_extensions) ? settings.enable_extensions.map(String) : [];
    for (const extension of extensions) {
      if (!SUPPORTED_EXTENSIONS.has(extension)) throw new NotYetImplementedError(at.file, at.line, `extension:${extension}`, "myst-extensions");
    }
  },
};
