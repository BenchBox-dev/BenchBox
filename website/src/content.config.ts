import { docsSchema } from "@astrojs/starlight/schema";
import { z } from "astro/zod";
import { defineCollection } from "astro:content";
import { docsLoader } from "./loaders/docs-loader.ts";

const docs = defineCollection({
  loader: docsLoader([
    { id: "docs/usage/getting-started", file: "docs/usage/getting-started.md" },
    { id: "docs/benchmarks/industry-benchmarks", file: "docs/benchmarks/industry-benchmarks.md" },
    { id: "docs/benchmarks/queries/tpch/q1", file: "docs/benchmarks/queries/tpch/q1.md" },
    {
      id: "docs/reference/python-api/additional-utilities",
      file: "website/spike-content/additional-utilities.md",
      summary: "Authored contract for format_scale_factor, written to the API reference page template.",
    },
  ]),
  schema: docsSchema({ extend: z.object({ sourcePath: z.string().optional() }) }),
});

const blog = defineCollection({
  loader: docsLoader([{ id: "blog/2026-05-18-v0-3-0-release-overview", file: "docs/blog/2026-05-18-v0-3-0-release-overview.md" }]),
  schema: z.looseObject({
    title: z.string(),
    date: z.string(),
    author: z.string().optional(),
    tags: z.string().optional(),
    description: z.string().optional(),
    sourcePath: z.string().optional(),
  }),
});

export const collections = { docs, blog };
