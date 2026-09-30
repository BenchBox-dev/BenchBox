const fs = require('node:fs');
const path = require('node:path');
const ts = require(path.join(process.env.COMMENT_POLICY_ROOT, 'results-explorer/node_modules/typescript'));

function scan(name, source) {
  const kind = name.endsWith('.tsx') || name.endsWith('.jsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const tree = ts.createSourceFile(name, source, ts.ScriptTarget.Latest, true, kind);
  if (tree.parseDiagnostics.length) {
    return tree.parseDiagnostics.map(d => ({
      kind: 'coverage-error',
      line: tree.getLineAndCharacterOfPosition(d.start || 0).line + 1,
      text: ts.flattenDiagnosticMessageText(d.messageText, '\n'),
    }));
  }
  const protectedRanges = [];
  function visit(node) {
    if (ts.isStringLiteralLike(node) || ts.isRegularExpressionLiteral(node) || ts.isJsxText(node)
        || node.kind === ts.SyntaxKind.TemplateHead || node.kind === ts.SyntaxKind.TemplateMiddle
        || node.kind === ts.SyntaxKind.TemplateTail) {
      protectedRanges.push([node.getStart(tree), node.end]);
    }
    ts.forEachChild(node, visit);
  }
  visit(tree);
  protectedRanges.sort((a, b) => a[0] - b[0]);
  const findings = [];
  let range = 0;
  let pos = 0;
  while (pos < source.length) {
    while (range < protectedRanges.length && protectedRanges[range][1] <= pos) range++;
    if (range < protectedRanges.length && protectedRanges[range][0] <= pos) {
      pos = protectedRanges[range][1];
      continue;
    }
    let end;
    if (source.startsWith('//', pos) || (pos === 0 && source.startsWith('#!', pos))) {
      end = source.indexOf('\n', pos);
      if (end < 0) end = source.length;
    } else if (source.startsWith('/*', pos)) {
      end = source.indexOf('*/', pos + 2);
      if (end < 0) throw new Error('unterminated JavaScript comment');
      end += 2;
    } else {
      pos++;
      continue;
    }
    findings.push({kind: 'comment', line: tree.getLineAndCharacterOfPosition(pos).line + 1,
      text: source.slice(pos, end).replace(/\r$/, '')});
    pos = end;
  }
  return findings;
}

const requests = JSON.parse(fs.readFileSync(0, 'utf8'));
const result = Object.fromEntries(Object.entries(requests).map(([name, source]) => [name, scan(name, source)]));
process.stdout.write(JSON.stringify(result));
