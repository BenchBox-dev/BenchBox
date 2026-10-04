import { NotYetImplementedError, UnknownConstructError } from "./errors.ts";
import type { SourcePosition } from "./model.ts";
import type { DirectiveHandler, FrontMatterHandler, Handler, RoleHandler, SyntaxHandler, SyntaxName } from "./types.ts";

type SyntaxTable = { [N in SyntaxName]?: SyntaxHandler<N> };

type LooseSyntaxTable = Partial<Record<SyntaxName, SyntaxHandler>>;

export class HandlerRegistry {
  private readonly directives = new Map<string, DirectiveHandler>();
  private readonly roles = new Map<string, RoleHandler>();
  private readonly frontMatter = new Map<string, FrontMatterHandler>();
  private readonly syntax: SyntaxTable = {};

  register(handler: Handler): this {
    if (handler.kind === "directive") for (const name of handler.names) this.directives.set(name, handler);
    else if (handler.kind === "role") for (const name of handler.names) this.roles.set(name, handler);
    else if (handler.kind === "front-matter") for (const key of handler.keys) this.frontMatter.set(key, handler);
    else this.setSyntax(handler);
    return this;
  }

  private setSyntax(handler: SyntaxHandler): void {
    (this.syntax as LooseSyntaxTable)[handler.name] = handler;
  }

  directive(name: string, at: SourcePosition): DirectiveHandler {
    const handler = this.directives.get(name);
    if (!handler) throw new UnknownConstructError(at.file, at.line, `directive:${name}`);
    return handler;
  }

  role(name: string, at: SourcePosition): RoleHandler {
    const handler = this.roles.get(name);
    if (!handler) throw new UnknownConstructError(at.file, at.line, `role:${name}`);
    return handler;
  }

  frontMatterKey(key: string, at: SourcePosition): FrontMatterHandler {
    const handler = this.frontMatter.get(key);
    if (!handler) throw new UnknownConstructError(at.file, at.line, `front-matter:${key}`);
    return handler;
  }

  syntaxHandler<N extends SyntaxName>(name: N, at: SourcePosition): SyntaxHandler<N> {
    const handler = this.syntax[name];
    if (!handler) throw new UnknownConstructError(at.file, at.line, `syntax:${name}`);
    return handler;
  }

  names(): { directives: string[]; roles: string[]; frontMatter: string[]; syntax: string[] } {
    return {
      directives: [...this.directives.keys()].sort(),
      roles: [...this.roles.keys()].sort(),
      frontMatter: [...this.frontMatter.keys()].sort(),
      syntax: (Object.keys(this.syntax) as SyntaxName[]).sort(),
    };
  }
}

export function notYetImplementedDirective(owner: string, names: readonly string[]): DirectiveHandler {
  return {
    kind: "directive",
    names,
    options: "any",
    argument: "accepted",
    handle(call) {
      throw new NotYetImplementedError(call.at.file, call.at.line, `directive:${call.name}`, owner);
    },
  };
}

export function notYetImplementedSyntax<N extends SyntaxName>(owner: string, name: N): SyntaxHandler<N> {
  return {
    kind: "syntax",
    name,
    handle(_node, at) {
      throw new NotYetImplementedError(at.file, at.line, `syntax:${name}`, owner);
    },
  };
}
