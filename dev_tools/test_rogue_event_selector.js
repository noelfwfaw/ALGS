// Run the selector against its bundled data without browser dependencies.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const folder = path.join(__dirname, 'rogue_events');
const html = fs.readFileSync(path.join(folder, 'index.html'), 'utf8');
const data = JSON.parse(fs.readFileSync(path.join(folder, 'events.json'), 'utf8'));
const bundled = { window: {} };
vm.runInNewContext(fs.readFileSync(path.join(folder, 'events.js'), 'utf8'), bundled);
assert.equal(JSON.stringify(bundled.window.EVENTS_DATA), JSON.stringify(data));
class Element {
  children = [];
  dataset = {};
  textContent = '';
  value = '';
  className = '';
  id = '';
  tagName = '';
  checked = false;
  disabled = false;
  scrollTop = 0;
  get firstChild() { return this.children[0] || null; }
  appendChild(child) { this.children.push(child); }
  append(...children) { this.children.push(...children); }
  replaceChildren() { this.children.length = 0; }
  click() { if (this.download) downloaded = this.download; }
  contains() { return false; }
  querySelectorAll() { return []; }
  setAttribute() { }
}
const controls = new Map();
function control(id) {
  if (!controls.has(id)) {
    const element = new Element();
    element.id = id;
    controls.set(id, element);
  }
  return controls.get(id);
}
const storage = new Map();
let allowReplace = true;
let downloaded;
let exportBlob;
const context = vm.createContext({
  window: { EVENTS_DATA: data },
  // 桩元素要记住自己是 createElement 出来的哪个标签，测试才能区分标题（h3/p/div）。
  document: {
    createElement: tag => Object.assign(new Element(), { tagName: tag }),
    getElementById: control,
  },
  localStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value) },
  FileReader: class { readAsText(text) { this.result = text; this.onload(); } },
  confirm: () => allowReplace,
  Blob,
  URL: {
    createObjectURL: blob => { exportBlob = blob; return 'blob:test'; },
    revokeObjectURL() { },
  },
  setTimeout: callback => callback(),
});
const source = html.match(/<script>([\s\S]*?)<\/script>/)[1];
vm.runInContext(source, context);
const classify = context.classification;
const residue = data.packs.flatMap(p => p.events).find(e => e.id === 'uk_904_s01_06b');

assert.match(classify(residue).textContent, /页面选项数 3，上限 3；库内共 5 条分支/);
assert.match(classify(residue, residue.options[0]).textContent, /随机\/条件出现/);
assert.match(classify(residue, residue.options[0]).textContent, /与选项 4 互斥显示/);
assert.match(classify(residue, residue.options[3]).textContent, /与选项 1 互斥显示/);
assert.match(classify(residue, residue.options[1]).textContent, /常规/);
assert.match(classify(residue, residue.options[4]).textContent, /攻击（独立按钮）/);
assert.equal(residue.options[4].text, '攻击');
assert.equal(classify({}).textContent, '');

// 虚無牧者 has two independent variants; each only offers [#1, #4] on first sight.
const shepherd = id => ({ [id]: [1, 2, 3, 7] });
const loop = { ...shepherd('uk_904_s01_13a-1'), ...shepherd('uk_904_s01_13b-1') };
const valid = { version: 1, picks: { ...loop, [residue.id]: 1,
  'uk_904_s01_13a': { priority: [2] }, 'uk_904_s01_13b': { priority: [2] } } };
assert.equal(context.validatePicks(valid), valid.picks);
for (const invalid of [
  { picks: null }, { picks: [] }, { version: 2, picks: {} }, { unknown: 1 },
  { [residue.id]: 9999 }, { [residue.id]: 28 }, { [residue.id]: '1' },
  { [residue.id]: [] }, { [residue.id]: [1, 9999] },
  { [residue.id]: { priority: [1, 1] } }, { [residue.id]: { priority: [1, 9999] } },
  { [residue.id]: { priority: ['1'] } }, { [residue.id]: { priority: [] } },
  { [residue.id]: { priority: ['安慰'] } },
  { 'uk_904_s01_05a': { priority: [1, 8] } },
  { 'uk_401_s01_02a': { priority: [3] } },
]) {
  assert.throws(() => context.validatePicks(invalid));
}
context.importPicks(JSON.stringify(valid));
assert.deepEqual(JSON.parse(storage.get('czn_rogue_events_v1')), valid.picks);
context.exportPicks();
assert.equal(downloaded, undefined);
assert.match(control('status').textContent, /殘留物.*需改用优先顺序/);
assert.doesNotThrow(() => context.validatePicks({ [residue.id]: 2 }, true));
const legacyVariant = { 'uk_401_s01_02a': 3 };
context.importPicks(JSON.stringify(legacyVariant));
assert.deepEqual(JSON.parse(storage.get('czn_rogue_events_v1')), legacyVariant);
context.exportPicks();
assert.equal(downloaded, undefined);
assert.match(control('status').textContent, /路米納斯的呼喚.*请按标题重选/);
context.importPicks(JSON.stringify(valid));
context.importPicks(JSON.stringify({ [residue.id]: 9999 }));
assert.match(control('status').textContent, /当前草稿保留/);
allowReplace = false;
context.importPicks(JSON.stringify({ picks: {} }));
assert.deepEqual(JSON.parse(storage.get('czn_rogue_events_v1')), valid.picks);

// 每个 vm context 有独立的 realm，测试里 new 出来的元素不会被选择器的 `instanceof`
// 认出来：只用鸭子类型判断。
// 桩元素不知道父节点；按 id 找元素时顺便记下它的父节点，往上才能找到卡片。
function* walk(element) {
  if (!element || !Array.isArray(element.children)) return;
  yield element;
  for (const child of element.children) {
    child.parent = element;
    yield* walk(child);
  }
}
control('search').value = 'uk_904_s01_13a-1';
control('only-picked').checked = true;
control('search').oninput();
const list = control('list');
const byId = id => [...walk(list)].find(element => element.id === id);
const seqPath = 'uk_904_s01/uk_904_s01_13a/uk_904_s01_13a_s2';
const firstOption = seqPath + '/uk_904_s01_13a-1_s1';
const byClass = name => [...walk(list)].filter(element => element.className === name);
assert.ok(byId(seqPath), 'root option rendered');
assert.equal(byId('uk_904_s01/uk_904_s01_13a/phase'), undefined);
const card = () => byClass('fu-event')[0];
const childPhase = () => [...walk(card())].find(element => element.className.startsWith('phase'));
const childChoices = () => [...walk(card())].filter(element => element.className.startsWith('pick'));
assert.match(childPhase().textContent, /路线已配置/);
assert.deepEqual(childChoices(), []);

byId(seqPath + '/undo').onclick();
assert.match(childPhase().textContent, /第 4 步/);
assert.deepEqual(childChoices().map(element => element.id.split('_s').pop()), ['7', '8']);
childChoices()[0].onclick();
assert.deepEqual(JSON.parse(storage.get('czn_rogue_events_v1'))['uk_904_s01_13a-1'], [1, 2, 3, 7]);
control('only-picked').checked = false;
byId(seqPath + '/clear').onclick();
assert.ok(byId(firstOption));
assert.match(childPhase().textContent, /首次遇到/);
assert.deepEqual(childChoices().map(element => element.id.split('_s').pop()), ['1', '4', '8']);
allowReplace = true;
context.importPicks(JSON.stringify(valid));

const inline = { id: 'inline', options: [{ next: { id: 'inline' }, text: '繼續' }] };
assert.equal(context.isLoopEvent(inline), true);
assert.equal(context.branchHas(inline, node => node.missing === true), false);
assert.equal(context.branchHas(inline, node => node.id === 'inline'), true);

const food = 'uk_904_s01_05a';
const foodPath = 'uk_904_s01/' + food;
const foodChoice = order => byId(foodPath + '/' + food + '_s' + order);
const savedFood = () => JSON.parse(storage.get('czn_rogue_events_v1'))[food];
// 阻止進食 只在餵食後的某一階段出現；任一終結選擇之後不能再接步驟。
for (const sequence of [[6], [7], [8, 3], [2, 7], [2, 3, 6], [2, 6, 8], [2, 3, 7, 8]]) {
  assert.throws(() => context.validatePicks({ [food]: sequence }), /路线顺序无效/);
}
for (const sequence of [[1], [8], [2, 6], [2, 3, 7]]) {
  assert.doesNotThrow(() => context.validatePicks({ [food]: sequence }, true));
}

const nodeFor = id => vm.runInContext('eventsById.get(' + JSON.stringify(id) + ')', context);
const ordersAt = (id, sequence) => Array.from(context.stageOptions(nodeFor(id), sequence), option => option.order);
const keeper = 'uk_300_s02_13a';
assert.deepEqual(ordersAt(keeper, []), [1, 5]);
assert.deepEqual(ordersAt(keeper, [1]), [2, 4]);
assert.deepEqual(ordersAt(keeper, [1, 2]), [3]);
const idol = 'uk_402_s01_11a-1';
assert.equal(context.returnOutcome(nodeFor(idol), nodeFor(idol).options[0]), 'fail');
for (const id of ['uk_402_s01_11a-1', 'uk_402_s01_11b-1', 'uk_402_s01_11c-1']) {
  assert.deepEqual(ordersAt(id, []), [1, 5]);
  assert.doesNotThrow(() => context.validatePicks({ [id]: [1, 2, 3, 4] }, true));
}
const intake = 'uk_904_s01_04a';
assert.deepEqual(ordersAt(intake, []), [1, 2, 4]);
assert.deepEqual(ordersAt(intake, [2, 2]), [1, 3, 4]);
assert.throws(() => context.validatePicks({ [intake]: [2] }, true), /后续选择/);
assert.doesNotThrow(() => context.validatePicks({ [intake]: [2, 2, 3] }, true));
const cave = 'uk_904_s01_09b';
assert.deepEqual(ordersAt(cave, []), [1, 2, 3]);
assert.deepEqual(ordersAt(cave, [3]), [1, 2, 4]);
assert.deepEqual(ordersAt(cave, [3, 1]), [2, 4]);
assert.throws(() => context.validatePicks({ [cave]: [3, 3] }), /路线顺序无效/);
assert.doesNotThrow(() => context.validatePicks({ [cave]: [3, 1, 2, 4] }, true));

const mine = 'uk_403_s01_01b';
assert.equal(context.returnOutcome(nodeFor(mine), nodeFor(mine).options[1]), 'either');
assert.deepEqual(ordersAt(mine, [2]), [3, 7]);
assert.throws(() => context.validatePicks({ [mine]: [2, 5] }, true), /路线顺序无效/);
assert.doesNotThrow(() => context.validatePicks({ [mine]: [2, 3, 7] }, true));

const residueBranch = 'uk_403_s01_11c';
assert.deepEqual(ordersAt(residueBranch, []), [3, 4]);
assert.deepEqual(ordersAt(residueBranch, [3]), [8]);
assert.throws(() => context.validatePicks({ [residueBranch]: [1, 6] }, true), /路线顺序无效/);
const gallery = 'uk_402_s01_15a';
assert.deepEqual(ordersAt(gallery, []), [3, 4]);
control('only-picked').checked = false;
control('search').value = gallery;
control('search').oninput();
const galleryPath = 'uk_402_s01/' + gallery;
const galleryChoice = galleryPath + '/' + gallery + '_s3';
const galleryFollowup = galleryChoice + '/' + gallery + '-1_s1';
assert.ok(byId(galleryFollowup));
byId(galleryChoice).onclick();
assert.match(byId(galleryPath + '/phase').textContent, /路线已配置/);
assert.equal(byId(galleryChoice), undefined);
assert.equal(byId(galleryFollowup).disabled, false);
byId(galleryPath + '/clear').onclick();

const confusion = 'uk_904_s01_15a';
assert.throws(() => context.validatePicks({ [confusion]: [1, 4] }, true), /请按标题重选/);
assert.doesNotThrow(() => context.validatePicks({ [confusion]: { priority: [1, '打破混亂', 8] } }, true));
assert.doesNotThrow(() => context.validatePicks({ 'uk_300_s02_13b-1': { priority: [1, 6, 7] } }, true));
control('only-picked').checked = false;
control('search').value = confusion;
control('search').oninput();
const confusionPath = 'uk_904_s01/' + confusion;
assert.equal(byId(confusionPath + '/phase'), undefined);
assert.equal(byId(confusionPath + '/' + confusion + '_s1').disabled, false);
assert.equal(byId(confusionPath + '/title/打破混亂').disabled, false);
assert.equal(byId(confusionPath + '/' + confusion + '_s8').disabled, false);
byId(confusionPath + '/' + confusion + '_s1').onclick();
byId(confusionPath + '/title/打破混亂').onclick();
byId(confusionPath + '/' + confusion + '_s8').onclick();
assert.deepEqual(JSON.parse(storage.get('czn_rogue_events_v1'))[confusion], { priority: [1, '打破混亂', 8] });
byId(confusionPath + '/clear').onclick();
assert.throws(() => context.validatePicks({ [residue.id]: [1, 2] }, true), /只需配置一次/);

context.importPicks(JSON.stringify({ ...valid.picks, [residue.id]: { priority: [1] } }));
control('only-picked').checked = false;
control('search').value = food;
control('search').oninput();
assert.match(byId(foodPath + '/phase').textContent, /首次遇到/);
assert.ok(foodChoice(8));
assert.equal(foodChoice(3), undefined);
assert.equal(foodChoice(6), undefined);
assert.equal(foodChoice(7), undefined);
foodChoice(2).onclick();
assert.deepEqual(savedFood(), [2]);
assert.match(byId(foodPath + '/phase').textContent, /餵食糧食.*成功后/);
assert.ok(foodChoice(6));
assert.equal(foodChoice(8), undefined);
control('search').value = 'nothing';
context.exportPicks();
assert.equal(downloaded, undefined);
assert.equal(control('search').value, food);
assert.match(control('status').className, /err/);
assert.match(control('status').textContent, /请完成「食客」的后续选择/);
foodChoice(3).onclick();
assert.match(byId(foodPath + '/phase').textContent, /再次餵食.*成功后/);
assert.equal(foodChoice(6), undefined);
assert.ok(foodChoice(7));
byId(foodPath + '/undo').onclick();
assert.equal(foodChoice(7), undefined);
foodChoice(6).onclick();
assert.deepEqual(savedFood(), [2, 6]);
assert.match(byId(foodPath + '/phase').textContent, /路线已配置.*120/);
assert.equal(foodChoice(3), undefined);

// Every fixed phase contains only valid, nonexclusive options.
vm.runInContext(`
  for (const [id, stages] of Object.entries(eventStages)) {
    const node = eventsById.get(id);
    if (!node) throw new Error('Unknown staged event: ' + id);
    for (const [index, orders] of stages.entries()) {
      const options = orders.map(order => node.options.find(o => o.order === order && canPick(o)));
      if (options.some(option => !option)) throw new Error(id + ' has an unknown staged option');
      if (options.some(option => options.some(other => option.exclusive_with?.includes(other.id)))) {
        throw new Error(id + ' shows mutually exclusive options together at step ' + (index + 1));
      }
      const continuation = options.some(option => returnOutcome(node, option));
      if (continuation !== (index + 1 < stages.length || repeatsLastStage.has(id))) {
        throw new Error(id + ' has an inconsistent continuation at step ' + (index + 1));
      }
    }
  }
`, context);

control('search').value = '殘留物';
control('search').oninput();
const residuePath = 'uk_904_s01/' + residue.id;
const residueChoice = suffix => byId(residuePath + '/' + residue.id + '_' + suffix);
const savedResidue = () => JSON.parse(storage.get('czn_rogue_events_v1'))[residue.id];
const shown = (root, text) => [...walk(root)].some(element => element.textContent.includes(text));
assert.equal(residueChoice('sa').disabled, true);
assert.equal(residueChoice('s4').disabled, false);
assert.ok(shown(residueChoice('s1'), '首选'));
residueChoice('s4').onclick();
assert.deepEqual(savedResidue(), { priority: [1, 4] });
assert.ok(shown(list, '可能都不出现或不可选'));
residueChoice('s2').onclick();
assert.deepEqual(savedResidue(), { priority: [1, 4, 2] });
assert.ok(shown(residueChoice('s4'), '备选 1'));
assert.ok(!shown(list, '可能都不出现或不可选'));
residueChoice('s4').onclick();
assert.deepEqual(savedResidue(), { priority: [1, 2] });

const finale = 'uk_402_s01_19a';
const finalePriority = ['詢問有關他的事', '表示要寫下結局'];
assert.doesNotThrow(() => context.validatePicks({ [finale]: { priority: finalePriority } }, true));
assert.throws(() => context.validatePicks({ [finale]: { priority: [1, 2] } }), /同名分支请按标题配置/);
assert.doesNotThrow(() => context.validatePicks({
  'uk_401_s01_02a': { priority: ['對抗', 1] },
}, true));
const bag = 'uk_401_s01_05a-1';
assert.equal(context.priorityEvent(nodeFor(bag)), true);
assert.doesNotThrow(() => context.validatePicks({ [bag]: { priority: ['查看袋子'] } }, true));
assert.throws(() => context.validatePicks({ [bag]: 1 }, true), /请按标题重选/);
control('search').value = finale;
control('search').oninput();
const finalePath = 'uk_402_s01/' + finale;
const titleChoice = name => byId(finalePath + '/title/' + name);
assert.match(titleChoice(finalePriority[0]).textContent, /接受任一同名分支/);
for (const name of finalePriority) titleChoice(name).onclick();
assert.match(titleChoice(finalePriority[1]).textContent, /备选 1/);
assert.ok(shown(list, '查看各分支条件和结果'));
assert.equal(byId(finalePath + '/' + finale + '_s1').disabled, true);
assert.equal(byId(finalePath + '/' + finale + '_s3').disabled, true);

const caveBranch = nodeFor('uk_904_s01_09a-1');
const otherCave = nodeFor('uk_904_s01_09a-1-1');
for (const order of [2, 3]) {
  assert.equal(context.nextNode(caveBranch.options.find(option => option.order === order)), otherCave);
}

const altar = 'uk_000_s01_02';
assert.deepEqual(ordersAt(altar, [1, 2, 2]), [2, 8]);
assert.throws(() => context.validatePicks({ [altar]: [6, 8] }, true), /路线顺序无效/);
assert.doesNotThrow(() => context.validatePicks({ [altar]: [1, 2, 8] }, true));

assert.deepEqual(
  Array.from(vm.runInContext('[...eventsById.values()].filter(node => isLoopEvent(node) && !guidedEvent(node) && !priorityEvent(node)).map(node => node.id).sort()', context)),
  [],
);

assert.ok(nodeFor('uk_904_s01_09a-1-1'), 'second nested level indexed');

const nav = control('nav');
const headings = () => list.children.filter(element => element.tagName === 'h2').map(element => element.textContent);
const maps = [
  ['藍壺', 30], ['雙星之影', 40], ['霧之城市', 38], ['審判之沼', 32], ['降臨的混沌', 36],
  ['第0研究所', 45], ['燃燒的生命', 46], ['虛像劇場', 47], ['萬花筒孵化場', 43], ['天上防護牆', 37],
  ['其他', 13],
];
assert.deepEqual(nav.children.map(link => [link.textContent, Number(link.children[0].textContent.split('/')[1])]), maps);
for (const [name, count] of maps) {
  nav.children.find(link => link.textContent === name).onclick({preventDefault() {}});
  assert.deepEqual(headings(), [name + '　' + count + ' / ' + count]);
  assert.equal(list.children.filter(element => element.className.split(' ')[0] === 'event').length, count, name);
}
control('search').value = '次元隧道';
control('search').oninput();
assert.ok(headings().includes('第0研究所　3 / 45'), 'both Research Lab packs are searched under one map');
const labIds = [...walk(list)].filter(element => element.className === 'id').map(element => element.textContent);
for (const id of ['uk_400_s01_18a', 'uk_400_s01_18b', 'uk_e01_s01_99a']) {
  assert.ok(labIds.includes(id), id);
}
control('search').value = 'uk_904_s01_05a';
control('search').oninput();
assert.deepEqual(headings(), ['霧之城市　1 / 38']);
assert.ok(byId('uk_904_s01/uk_904_s01_05a/phase'), 'original pack-based option path is preserved');

context.exportPicks();
assert.equal(downloaded, 'rogue_event_picks.json');
exportBlob.text().then(async text => {
  const result = JSON.parse(text);
  assert.equal(result.version, 1);
  assert.deepEqual(result.picks, {
    ...valid.picks, [residue.id]: { priority: [1, 2] }, [food]: [2, 6],
    [finale]: { priority: finalePriority }
  });
  assert.doesNotThrow(() => context.validatePicks(result, true));

  const [convictBase, convictBattle, convictAmbush] = ['uk_300_s02_03b', 'uk_300_s02_03a-1', 'uk_300_s02_03c-1'];
  const convictCopy = (root, branch, event) => 'uk_300_s02/' + root + (branch ? '/' + root + '_' + branch : '') + '/' + event;
  const convictCopies = [
    convictCopy(convictBase, '', convictBase),
    convictCopy('uk_300_s02_03a', 'sa', convictBattle),
    convictCopy('uk_300_s02_03c', 'sa', convictBattle),
    convictCopy('uk_300_s02_03c', 's3', convictAmbush),
    convictCopy('uk_300_s02_03c', 's4', convictAmbush),
  ];
  const draftPicks = () => JSON.parse(storage.get('czn_rogue_events_v1'));
  const searchFor = (name, onlyConfigured = false) => {
    control('search').value = name;
    control('only-picked').checked = onlyConfigured;
    control('search').oninput();
  };
  const convictButtons = order => convictCopies.map(prefix => byId(prefix + '_s' + order));
  context.importPicks(JSON.stringify({ [convictBattle]: [1], [convictAmbush]: 1 }));
  assert.deepEqual(draftPicks(), { [convictBase]: 1 });
  searchFor('定罪者', true);
  assert.deepEqual(headings(), ['藍壺　3 / 30']);
  assert.equal(nav.children.find(link => link.textContent === '藍壺').children[0].textContent, '3/30');
  assert.match(control('stat').textContent, /已选 1 个事件/);
  assert.ok(shown(list, '战斗胜利后：定罪者（' + convictBattle + '）'));
  assert.ok(shown(list, '掷骰失败、战斗胜利后：定罪者（' + convictAmbush + '）'));
  assert.ok(shown(list, '选择会同步到其他入口'));
  assert.ok(convictButtons(1).every(button => button.className === 'pick on'));
  assert.equal(byId('uk_300_s02/uk_300_s02_03a/uk_300_s02_03a_s1').className, 'pick');
  convictButtons(2).at(-1).onclick();
  assert.deepEqual(draftPicks(), { [convictBase]: 2, 'uk_300_s02_03c': { priority: [4] } });
  assert.ok(convictButtons(1).every(button => button.className === 'pick'));
  assert.ok(convictButtons(2).every(button => button.className === 'pick on'));

  const conflict = { [convictBase]: 2, [convictBattle]: 1, [convictAmbush]: 3 };
  context.importPicks(JSON.stringify(conflict));
  assert.deepEqual(draftPicks(), conflict);
  assert.match(control('status').textContent, /有不同选项/);
  assert.ok(convictButtons(2).every(button => button.className === 'pick'));
  downloaded = undefined;
  context.exportPicks();
  assert.equal(downloaded, undefined);
  assert.match(control('status').textContent, /定罪者.*请重选/);
  assert.deepEqual(draftPicks(), conflict);
  convictButtons(3)[0].onclick();
  assert.deepEqual(draftPicks(), { [convictBase]: 3 });
  context.exportPicks();
  assert.equal(downloaded, 'rogue_event_picks.json');
  assert.deepEqual(JSON.parse(await exportBlob.text()).picks, { [convictBase]: 3 });
  context.importPicks(JSON.stringify(conflict));
  byId('uk_300_s02/' + convictBase + '/shared-clear').onclick();
  assert.deepEqual(draftPicks(), {});

  const herald = 'uk_sys_s02_01a';
  const heraldAlias = 'uk_sys_s02_01d';
  const heraldButton = (id, order) => byId('uk_sys_s02/' + id + '/' + id + '_s' + order);
  context.importPicks(JSON.stringify({ [herald]: { priority: [1, 2] }, [heraldAlias]: { priority: [1, 2] } }));
  assert.deepEqual(draftPicks(), { [herald]: { priority: [1, 2] } });
  searchFor('凱爾肯的傳令兵');
  assert.ok(shown(heraldButton(heraldAlias, 2), '备选 1'));
  heraldButton(heraldAlias, 4).onclick();
  assert.ok(shown(heraldButton(herald, 4), '备选 2'));
  assert.deepEqual(draftPicks(), { [herald]: { priority: [1, 2, 4] } });
  const priorityConflict = { [herald]: { priority: [1, 2] }, [heraldAlias]: { priority: [2, 1] } };
  assert.deepEqual(context.validatePicks(priorityConflict), priorityConflict);
  assert.throws(() => context.validatePicks(priorityConflict, true), /有不同|不同选项/);

  context.importPicks(JSON.stringify({ 'uk_904_s01_07b-1': 2, 'uk_904_s01_07e-2': 1, 'uk_302_s02_07a-4': 1 }));
  assert.deepEqual(draftPicks(), { 'uk_904_s01_07a-1': 2, 'uk_904_s01_07d-1': 1, 'uk_302_s02_07a-1': 1 });
  searchFor('尼希隆研究');
  assert.equal(byId('uk_904_s01/uk_904_s01_07c/uk_904_s01_07c_sa/uk_904_s01_07c-1_s2').className, 'pick on');
  assert.equal(byId('uk_904_s01/uk_904_s01_07e/uk_904_s01_07e_sa/uk_904_s01_07e-2_s2').className, 'pick');

  const enclosure = 'uk_300_s02_15b';
  const chest = enclosure + '-1';
  const entry = '查看食屍鬼飼養場';
  const firstChest = { priority: ['打開左邊的箱子'] };
  context.importPicks(JSON.stringify({ [enclosure]: { priority: [4] } }));
  searchFor(chest);
  const chestAction = [...walk(list)].find(el => el.id.includes(enclosure + '_s1/')
    && el.id.endsWith('/title/打開左邊的箱子'));
  assert.ok(chestAction);
  chestAction.onclick();
  assert.deepEqual(draftPicks(), { [enclosure]: { priority: [entry, 4] }, [chest]: firstChest });
  context.exportPicks();
  assert.deepEqual(JSON.parse(await exportBlob.text()).picks, draftPicks());

  context.importPicks(JSON.stringify({ [chest]: firstChest }));
  assert.deepEqual(draftPicks(), { [chest]: firstChest, [enclosure]: { priority: [entry] } });
  const oldSkip = { [enclosure]: { priority: [4] }, [chest]: firstChest };
  context.importPicks(JSON.stringify(oldSkip));
  assert.deepEqual(draftPicks(), oldSkip);

  const parallel = 'uk_300_s02_15a';
  const parallelChoices = { [parallel + '-1']: 1, [parallel + '-2']: { priority: [2] } };
  context.importPicks(JSON.stringify(parallelChoices));
  assert.deepEqual(draftPicks(), parallelChoices, 'opposing entrances do not depend on import ordering');

  context.importPicks(JSON.stringify({}));
  searchFor(gallery);
  byId(galleryFollowup).onclick();
  assert.deepEqual(draftPicks(), { [gallery]: [3], [gallery + '-1']: 1 });

  const greed = 'uk_403_s01_16a';
  context.importPicks(JSON.stringify({ [greed]: 1, [greed + '-1']: { priority: [4] } }));
  searchFor(greed + '-2');
  const deepAction = [...walk(list)].find(el => el.id.includes(greed + '_s2/')
    && el.id.includes(greed + '-1_s3/') && el.id.endsWith('/' + greed + '-2_s4'));
  assert.ok(deepAction);
  deepAction.onclick();
  assert.deepEqual(draftPicks(), {
    [greed]: 2, [greed + '-1']: { priority: [3, 4] }, [greed + '-2']: { priority: [4] },
  });

  // Startup applies the same migration and does not resolve conflicting drafts by position.
  storage.set('czn_rogue_events_v1', JSON.stringify({ [convictAmbush]: [2] }));
  vm.runInNewContext(source, {...context});
  assert.deepEqual(draftPicks(), { [convictBase]: 2 });
  storage.set('czn_rogue_events_v1', JSON.stringify(conflict));
  vm.runInNewContext(source, {...context});
  assert.deepEqual(draftPicks(), conflict);
  assert.match(control('status').textContent, /检查草稿.*有不同选项/);

  console.log('Event selector classification, import, search, sequence and export checks passed');
}).catch(error => {
  console.error(error);
  process.exitCode = 1;
});
