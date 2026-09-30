const test = require('node:test');
const assert = require('node:assert/strict');
const {spawnSync} = require('node:child_process');
const path = require('node:path');
const {scan} = require('../../../scripts/comment_syntax_js.cjs');

const contexts = [
  ['a.ts', 'const x = /https?:\\/\\//; const y = "// data"; // explanation', '// explanation'],
  ['a.ts', 'const x = `// data ${1 /* explanation */}`;', '/* explanation */'],
  ['a.tsx', 'const x = <div>https://host # data{/* explanation */}</div>;', '/* explanation */'],
  ['a.tsx', 'const x = <div>\n// data\n<span /></div>; // explanation', '// explanation'],
  ['a.ts', 'const x = 1; /* explanation */', '/* explanation */'],
];
for (const [name, source, text] of contexts) {
  test(`native syntax: ${name}: ${source}`, () => {
    assert.deepEqual(scan(name, source).map(f => [f.kind, f.text]), [['comment', text]]);
  });
}
test('qualified symbols distinguish moved comments', () => {
  const before = scan('a.ts', 'function a(){ // same\n}\nfunction b(){}');
  const after = scan('a.ts', 'function a(){}\nfunction b(){ // same\n}');
  assert.equal(before[0].symbol, 'a');
  assert.equal(after[0].symbol, 'b');
  assert.equal(scan('a.ts', 'class C { m(){ /* text */ } }')[0].symbol, 'C.m');
});
test('process Python payloads resolve local templates and joined arrays', () => {
  const source = 'const script = ["# explanation", "print(1)"].join("\\n"); spawnSync("uv", ["run", "--", "python", "-c", script]);';
  const result = scan('a.mjs', source);
  assert.equal(result[0].language, 'python');
  assert.equal(result[0].text, '# explanation\nprint(1)');
  const template = 'const script = `# explanation\nprint(${JSON.stringify(name)})`; spawnSync("python3", ["-c", script]);';
  assert.equal(scan('a.mjs', template)[0].text, '# explanation\nprint("__expression__")');
});
test('unknown process source fails coverage instead of hiding templates', () => {
  const source = 'function run(source){ spawnSync("uv", ["run", "--", "python", "-c", source]); }';
  assert.equal(scan('a.mjs', source)[0].kind, 'coverage-error');
});
test('SQL and nested Node source reach their language adapters', () => {
  const sql = scan('a.ts', 'const statement = "SELECT 1 -- explanation"; conn.query(statement);');
  assert.equal(sql[0].kind, 'payload');
  assert.equal(sql[0].language, 'sql');
  assert.equal(sql[0].text, 'SELECT 1 -- explanation');
  const js = scan('a.mjs', 'spawnSync("node", ["-e", "let x=1; // explanation"]);');
  assert.equal(js[0].kind, 'comment');
  assert.equal(js[0].text, '// explanation');
});
test('stdio request contract and parse errors', () => {
  const adapter = path.resolve(__dirname, '../../../scripts/comment_syntax_js.cjs');
  const result = spawnSync("node", [adapter], {input: JSON.stringify({'a.ts': '// text'}), encoding: 'utf8'});
  assert.equal(result.status, 0);
  assert.equal(JSON.parse(result.stdout)['a.ts'][0].text, '// text');
  assert.equal(scan('a.ts', 'function broken(')[0].kind, 'coverage-error');
});
