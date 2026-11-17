// No browser or npm packages required: check the classification text against real data.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const folder = path.join(__dirname, 'rogue_events');
const html = fs.readFileSync(path.join(folder, 'index.html'), 'utf8');
const source = html.match(/function classification\(node, option\) \{[\s\S]*?\n\}/)[0];
const context = vm.createContext({document: {createElement: () => ({textContent: ''})}});
vm.runInContext(source, context);
const classify = context.classification;
const data = JSON.parse(fs.readFileSync(path.join(folder, 'events.json'), 'utf8'));
const residue = data.packs.flatMap(p => p.events).find(e => e.id === 'uk_904_s01_06b');

assert.match(classify(residue).textContent, /页面选项数 3，上限 3；库内共 5 条分支/);
assert.match(classify(residue, residue.options[0]).textContent, /随机\/条件出现/);
assert.match(classify(residue, residue.options[0]).textContent, /与选项 4 互斥显示/);
assert.match(classify(residue, residue.options[3]).textContent, /与选项 1 互斥显示/);
assert.match(classify(residue, residue.options[1]).textContent, /常规/);
assert.match(classify(residue, residue.options[4]).textContent, /攻击（独立按钮）/);
assert.equal(residue.options[4].text, '攻击');
assert.equal(classify({}).textContent, '');
console.log('Event selector classification checks passed');
