const FENCE_OPEN = /^ {0,3}(`{3,}|~{3,})/;
const LABEL_LINE = /^(\s*)\(([^)\s][^)]*)\)=\s*$/;
const COMMENT_LINE = /^ {0,3}%/;
const ATTRS_LINE = /^(\s*)\{([#.][^{}]*|[A-Za-z_][\w-]*=[^{}]*)\}\s*$/;

export const LABEL_MARKER = /^<!--benchbox-label (.+) -->$/;

export const ATTRS_MARKER = /^<!--benchbox-attrs (.+) -->$/;

export const COMMENT_MARKER = "<!--benchbox-comment-->";

export function preprocess(source: string): string {
  const lines = source.split("\n");
  let fence: { marker: string; length: number } | null = null;
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    if (fence) {
      const trimmed = line.trim();
      if (trimmed.length >= fence.length && trimmed === fence.marker.repeat(trimmed.length)) fence = null;
      continue;
    }
    const open = line.match(FENCE_OPEN);
    if (open) {
      fence = { marker: open[1][0], length: open[1].length };
      continue;
    }
    if (COMMENT_LINE.test(line)) {
      lines[index] = COMMENT_MARKER;
      continue;
    }
    const attrs = line.match(ATTRS_LINE);
    if (attrs) {
      lines[index] = `${attrs[1]}<!--benchbox-attrs ${attrs[2].trim()} -->`;
      continue;
    }
    const label = line.match(LABEL_LINE);
    if (label) lines[index] = `${label[1]}<!--benchbox-label ${label[2]} -->`;
  }
  return lines.join("\n");
}
