import { docsSchema } from "@astrojs/starlight/schema";
import { glob } from "astro/loaders";
import { z } from "astro/zod";
import { defineCollection } from "astro:content";

const generatedContent = (pattern: string | string[]) =>
  glob({
    pattern,
    base: "./.generated/content",
    generateId: ({ entry }) => entry.replace(/\.mdx?$/, ""),
  });

const docsSchemaExtended = () =>
  docsSchema({
    extend: z.looseObject({
      sourcePath: z.string().optional(),
      titleId: z.string().optional(),
      headingIds: z.array(z.string()).optional(),
      tags: z.array(z.string()).optional(),
    }),
  });

const docs = defineCollection({
  loader: generatedContent(["docs/**/*.{md,mdx}", "!docs/**/index.{md,mdx}"]),
  schema: docsSchemaExtended(),
});

const docsIndex = defineCollection({
  loader: generatedContent("docs/**/index.{md,mdx}"),
  schema: docsSchemaExtended(),
});

const blog = defineCollection({
  loader: generatedContent("blog/**/*.{md,mdx}"),
  schema: z.looseObject({
    title: z.string(),
    date: z.string().optional(),
    author: z.string().optional(),
    tags: z.array(z.string()).optional(),
    description: z.string().optional(),
    sourcePath: z.string().optional(),
    titleId: z.string().optional(),
    headingIds: z.array(z.string()).optional(),
  }),
});

export const collections = { docs, docsIndex, blog };
