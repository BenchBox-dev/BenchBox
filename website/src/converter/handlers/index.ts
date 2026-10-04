import { HandlerRegistry } from "../registry.ts";
import { admonitionDirective } from "./admonitions.ts";
import { colonFenceSyntax } from "./colon-fence.ts";
import { commentSyntax, htmlCommentSyntax } from "./comments.ts";
import { deflistSyntax } from "./deflist.ts";
import { evalRstDirective } from "./eval-rst.ts";
import { descriptionFrontMatter, mystFrontMatter, passthroughFrontMatter, tagsFrontMatter, titleFrontMatter } from "./front-matter.ts";
import { headingSyntax } from "./headings.ts";
import { imageSyntax } from "./images.ts";
import { labelSyntax } from "./labels.ts";
import { linkSyntax } from "./links.ts";
import { mermaidDirective } from "./mermaid.ts";
import { postlistDirective } from "./postlist.ts";
import { listTableDirective } from "./list-table.ts";
import { rawHtmlInlineSyntax, rawHtmlSyntax } from "./raw-html.ts";
import { docRole, refRole } from "./references.ts";
import { tagsDirective } from "./tags.ts";
import { todoHandlers } from "./todo.ts";
import { toctreeDirective } from "./toctree.ts";

export function createDefaultRegistry(): HandlerRegistry {
  const registry = new HandlerRegistry();
  for (const handler of todoHandlers) registry.register(handler);
  registry
    .register(tagsDirective)
    .register(imageSyntax)
    .register(rawHtmlSyntax)
    .register(rawHtmlInlineSyntax)
    .register(colonFenceSyntax)
    .register(evalRstDirective)
    .register(postlistDirective)
    .register(admonitionDirective)
    .register(mermaidDirective)
    .register(deflistSyntax)
    .register(listTableDirective)
    .register(toctreeDirective)
    .register(docRole)
    .register(refRole)
    .register(labelSyntax)
    .register(commentSyntax)
    .register(htmlCommentSyntax)
    .register(headingSyntax)
    .register(linkSyntax)
    .register(passthroughFrontMatter)
    .register(titleFrontMatter)
    .register(descriptionFrontMatter)
    .register(tagsFrontMatter)
    .register(mystFrontMatter);
  return registry;
}
