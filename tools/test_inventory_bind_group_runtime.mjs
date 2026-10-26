// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// РЕАЛЬНЫЙ Vue runtime-тест combobox выбора катушки в диалоге «Привязать материал к принтеру» — inventory 1.7.10.
// Монтирует ДОСЛОВНЫЙ блок combobox из shipped InventoryPanel.js настоящим вендорным Vue на самодельном DOM
// поверх ДОСЛОВНО извлечённых из файла функций (bindGroupKey/_fifoCmp/bindStockGroups/bindStockFiltered/
// spickRows/bindGroupOpen/pickGroup/pickSpool/toggleGroupExpand/spickKey/bindPickedSpool/applyBind). Доказывает:
//   G1  100 ФИЗИЧЕСКИ одинаковых катушек -> ОДНА групповая строка, бейдж «100 шт.»;
//   G2  различия material/manufacturer/color/weight/location/lot -> отдельные группы;
//   G3  различаются только id/created_at/цена -> группа остаётся одной;
//   G4  основной клик по группе -> FIFO выбирает ТОЧНЫЙ ожидаемый spool id (ранний created_at, tiebreak id);
//   G5  раскрытие группы + ручной выбор -> bind.sid = выбранный конкретный id (не FIFO);
//   G6  поиск по конкретному spool id -> раскрывает нужную группу и показывает катушку;
//   G7  после bind() + load() количество группы 100 -> 99;
//   G8  pending/bound/deleted НЕ входят в количество группы;
//   G9  Escape закрывает СНАЧАЛА listbox (stopPropagation), затем bind-диалог (стек ядра);
//   G10 AMS slot 0 / slot 1 / multi-AMS / external -> applyBind шлёт НАСТОЯЩИЙ target (printer_id, ams_slot) + реальный id;
//   G11 500–1000 одинаковых кандидатов -> в DOM НЕ сотни верхнеуровневых строк (группировка держит 1 строку).
// Vue-правило: экспортируемые setup-ключи без префикса «_»/«$» (проверяется по факту рендера).
// Запуск: node tools/test_inventory_bind_group_runtime.mjs   (0 = все проверки пройдены)
import { readFileSync } from 'fs';
import { fileURLToPath, pathToFileURL } from 'url';
import { dirname, join } from 'path';

const REPO = dirname(dirname(fileURLToPath(import.meta.url)));
const PANEL = readFileSync(join(REPO, 'modules', 'inventory', 'web', 'InventoryPanel.js'), 'utf8');
let fail = 0;
const check = (name, cond) => { console.log((cond ? 'PASS' : 'FAIL') + ' — ' + name); if (!cond) fail++; };

// ─────────── минимальный DOM ───────────
class DNode {
  constructor(t) { this.nodeType = t; this.childNodes = []; this.parentNode = null; }
  get nextSibling() { const p = this.parentNode; if (!p) return null; const i = p.childNodes.indexOf(this); return i >= 0 ? (p.childNodes[i + 1] || null) : null; }
  _link(c, a) { if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = this; if (a && a.parentNode === this) this.childNodes.splice(this.childNodes.indexOf(a), 0, c); else this.childNodes.push(c); return c; }
  insertBefore(c, a) { return this._link(c, a); }
  appendChild(c) { return this._link(c, null); }
  removeChild(c) { const i = this.childNodes.indexOf(c); if (i >= 0) this.childNodes.splice(i, 1); c.parentNode = null; return c; }
  getRootNode() { return globalThis.document; }
  get ownerDocument() { return globalThis.document; }
}
class DText extends DNode { constructor(t) { super(3); this.nodeValue = t == null ? '' : String(t); } get data() { return this.nodeValue; } set data(v) { this.nodeValue = v; } }
class DComment extends DNode { constructor(t) { super(8); this.nodeValue = t == null ? '' : String(t); } }
class DElement extends DNode {
  constructor(tag) { super(1); this._tag = tag; this.tagName = String(tag).toUpperCase(); this.namespaceURI = 'http://www.w3.org/1999/xhtml'; this.attributes = {}; this._listeners = {}; this.style = {}; this._cls = ''; this._disabled = false; this._value = ''; }
  setAttribute(k, v) { this.attributes[k] = String(v); if (k === 'class') this._cls = String(v); }
  removeAttribute(k) { delete this.attributes[k]; if (k === 'class') this._cls = ''; }
  getAttribute(k) { return k in this.attributes ? this.attributes[k] : null; }
  hasAttribute(k) { return k in this.attributes; }
  get className() { return this._cls; }
  set className(v) { this._cls = v == null ? '' : String(v); this.attributes['class'] = this._cls; }
  get disabled() { return this._disabled; }
  set disabled(v) { this._disabled = !!v; }
  get value() { return this._value; }
  set value(v) { this._value = v == null ? '' : String(v); }
  get classList() { const s = this; const set = () => new Set(s._cls.split(/\s+/).filter(Boolean)); const put = (x) => { s.className = [...x].join(' '); }; return { add: (...c) => { const x = set(); c.forEach((y) => x.add(y)); put(x); }, remove: (...c) => { const x = set(); c.forEach((y) => x.delete(y)); put(x); }, contains: (c) => set().has(c), toggle: (c) => { const x = set(); x.has(c) ? x.delete(c) : x.add(c); put(x); } }; }
  addEventListener(t, fn) { (this._listeners[t] = this._listeners[t] || []).push(fn); }
  removeEventListener(t, fn) { const a = this._listeners[t]; if (a) { const i = a.indexOf(fn); if (i >= 0) a.splice(i, 1); } }
  get textContent() { return this.childNodes.map((c) => c.nodeType === 3 ? c.nodeValue : (c.nodeType === 1 ? c.textContent : '')).join(''); }
  set textContent(v) { this.childNodes.forEach((c) => (c.parentNode = null)); this.childNodes = []; if (v !== '' && v != null) this.appendChild(new DText(String(v))); }
  hasChildNodes() { return this.childNodes.length > 0; }
  get firstChild() { return this.childNodes[0] || null; }
  get innerHTML() { return ''; }
  set innerHTML(v) { if (v === '' || v == null) { this.childNodes.forEach((c) => (c.parentNode = null)); this.childNodes = []; } }
  querySelector() { return null; }
  _fire(type, ev) { (this._listeners[type] || []).slice().forEach((fn) => fn(ev)); }
  _findAll(pred, out = []) { if (this.nodeType === 1 && pred(this)) out.push(this); this.childNodes.forEach((c) => { if (c.nodeType === 1) c._findAll(pred, out); }); return out; }
}
const doc = { createElement: (t) => new DElement(t), createElementNS: (ns, t) => new DElement(t), createTextNode: (t) => new DText(t), createComment: (t) => new DComment(t), querySelector: () => null, addEventListener: () => {}, removeEventListener: () => {}, activeElement: null };
doc.body = new DElement('body'); doc.head = new DElement('head'); doc.documentElement = new DElement('html');
if (!globalThis.document) globalThis.document = doc;
if (!globalThis.window) { try { globalThis.window = globalThis; } catch (e) {} }
for (const g of ['SVGElement', 'HTMLElement', 'Element', 'Node', 'ShadowRoot', 'Document', 'DocumentFragment']) { if (globalThis[g] === undefined) globalThis[g] = class {}; }

// ─────────── извлечение ДОСЛОВНОГО исходника `const NAME = <expr>;` (баланс ()[]{}/строк) ───────────
const extractConst = (src, name) => {
  const anchor = 'const ' + name + ' = ';
  const i = src.indexOf(anchor);
  if (i < 0) throw new Error('not found: ' + name);
  let d = 0, q = null, esc = false;
  for (let k = i + anchor.length; k < src.length; k++) {
    const ch = src[k];
    if (esc) { esc = false; continue; }
    if (q) { if (ch === '\\') esc = true; else if (ch === q) q = null; continue; }
    if (ch === "'" || ch === '"' || ch === '`') { q = ch; continue; }
    if (ch === '(' || ch === '[' || ch === '{') d++;
    else if (ch === ')' || ch === ']' || ch === '}') d--;
    else if (ch === ';' && d === 0) return src.slice(i, k + 1);
  }
  throw new Error('unbalanced: ' + name);
};

const NAMES = ['_gnum', '_gtxt', '_ghex', 'safeHex', 'bindGroupKey', '_fifoRank', '_fifoCmp', 'bindStockGroups',
  'spick', 'bindGroupOpen', 'bindStockFiltered', 'spickRows', 'bindPickedSpool',
  'spickOpen', 'spickClose', 'pickGroup', 'pickSpool', 'toggleGroupExpand', 'spickLabel', 'spickSub', 'spickKey', 'applyBind'];
const SRCS = NAMES.map((n) => extractConst(PANEL, n));
check('G0. дословные функции combobox извлечены из shipped-панели (' + NAMES.length + ')', SRCS.every((s) => s.length > 5));

// ─────────── ДОСЛОВНАЯ разметка combobox из shipped-шаблона ───────────
const MARK_KEY = '<div v-if="bind.pick" class="fm-inv-field fm-inv-spick">';
const ms = PANEL.indexOf(MARK_KEY);
const mOpenEnd = PANEL.indexOf('>', ms) + 1;
const mRe = /<div\b|<\/div>/g; mRe.lastIndex = mOpenEnd;
let mm, dep = 1, mClose = -1;
while ((mm = mRe.exec(PANEL))) { dep += (mm[0] === '</div>') ? -1 : 1; if (dep === 0) { mClose = mm.index; break; } }
const COMBOBOX_MARKUP = PANEL.slice(ms, mClose + '</div>'.length).replace('v-if="bind.pick"', 'v-if="true"');
check('G0b. разметка combobox извлечена (bindStockGroups/pickGroup/toggleGroupExpand/pickSpool/spickKey)',
  COMBOBOX_MARKUP.includes('pickGroup(row.g)') && COMBOBOX_MARKUP.includes('toggleGroupExpand(row.g') && COMBOBOX_MARKUP.includes('pickSpool(row.s)') && COMBOBOX_MARKUP.includes('spickKey($event)') && COMBOBOX_MARKUP.includes("{{ row.g.count }}"));

const Vue = await import(pathToFileURL(join(REPO, 'web', 'vendor', 'vue.esm-browser.js')).href);
const { createApp, ref, reactive, computed, nextTick } = Vue;

// ─────────── фабрика: РЕАЛЬНЫЕ функции (ДОСЛОВНЫЕ SRCS) сшиты в один setup через new Function ───────────
const netCalls = [];
const RETURN_KEYS = 'L, spools, bind, bindBusy, spoolById, isBound, locName, load, ' + NAMES.join(', ') + ', spickOpen, spickClose, spickLabel, spickSub';
const buildSetup = new Function('Vue', 'env', [
  'const { ref, reactive, computed } = Vue;',
  'const { spoolList, bindInit, netCalls } = env;',
  'const L = (ru, en) => ru;',
  'const flash = () => {};',
  // 1.7.24: тест изолирует ЛОГИКУ ПРИВЯЗКИ, а не права — извлечённым функциям нужны те же
  // заглушки, что и flash/load. Права проверяются отдельными тестами capability contract.
  'const guard = () => true;',
  'const accessDenied = () => false;',
  'const spools = ref(spoolList.map((s) => ({ ...s })));',
  'const bindBusy = ref(false);',
  "const bind = reactive(Object.assign({ open: true, pick: true, sid: '', bound: false, printer_id: '', slot: -1 }, bindInit || {}));",
  'const isBound = (s) => !!(s && s.ams_printer_id && s.ams_slot >= 0);',
  'const spoolById = computed(() => { const m = {}; for (const s of spools.value) m[s.id] = s; return m; });',
  "const locName = (id) => id ? ('Локация ' + id) : '';",
  'const load = async () => {};',
  SRCS.join('\n'),
  'return { ' + RETURN_KEYS + ' };',
].join('\n'));
const makeComp = (spoolList, bindInit) => {
  let state;
  const component = {
    setup() { state = buildSetup(Vue, { spoolList, bindInit, netCalls }); return state; },
    template: '<div class="root">' + COMBOBOX_MARKUP + '</div>',
    compilerOptions: { decodeEntities: (x) => x },
  };
  return { component };
};
// fetch-стаб (applyBind шлёт настоящий bind.sid + printer/slot)
globalThis.fetch = async (url, opts) => { netCalls.push({ url: String(url), body: opts && opts.body ? JSON.parse(opts.body) : null }); return { ok: true, status: 200, json: async () => ({ ok: true }) }; };

const mount = (component) => { const app = createApp(component); app.config.warnHandler = () => {}; const root = new DElement('div'); const vm = app.mount(root); return { root, vm }; };
const byCls = (root, c) => root._findAll((e) => (' ' + e.className + ' ').includes(' ' + c + ' '));
const clickEl = (el) => el._fire('click', { type: 'click', target: el, currentTarget: el, stopPropagation() {}, preventDefault() {} });
const keyEl = (el, key) => { let stopped = false; el._fire('keydown', { type: 'keydown', key, target: el, stopPropagation() { stopped = true; }, preventDefault() {} }); return stopped; };

// ─────────── fixtures ───────────
const spool = (id, over) => Object.assign({ id, filament_id: 'fil_petg_black', material: 'PETG', color_name: 'Чёрный', color_hex: '#111111', vendor_name: 'GEHR', weight_remaining_g: 5000, weight_total_g: 5000, diameter: 1.75, location_id: 'loc1', lot: '', label: '', price: 10, purchased_at: '', created_at: '2026-07-01 10:00:00', status: 'in_stock', ams_printer_id: '', ams_slot: -1, is_deleted: 0 }, over || {});

// ═══ G1: 100 одинаковых -> одна групповая строка, «100 шт.» ═══
{
  const list = Array.from({ length: 100 }, (_, i) => spool('sp' + String(i).padStart(3, '0'), { created_at: '2026-07-01 10:00:0' + (i % 10), price: 10 + i }));
  const { root, vm } = mount(makeComp(list).component);
  const S = vm.$.setupState;
  S.spickOpen(); await nextTick();
  const groups = byCls(root, 'fm-inv-spick-g');
  const badge = byCls(root, 'fm-inv-spick-badge')[0];
  check('G1. 100 одинаковых катушек -> 1 групповая строка; бейдж «100 шт.»',
    S.bindStockGroups.length === 1 && S.bindStockGroups[0].count === 100
    && groups.length === 1 && !!badge && badge.textContent.trim() === '100 шт.');
}

// ═══ G2: различия по каждой характеристике -> отдельные группы ═══
{
  const list = [
    spool('a1'), spool('a2'),                                  // базовая группа (2)
    spool('b1', { material: 'PLA' }),                          // material
    spool('c1', { vendor_name: 'Bambu' }),                    // manufacturer
    spool('d1', { color_hex: '#00ff00', color_name: 'Зелёный' }), // color
    spool('e1', { weight_remaining_g: 4000 }),                // remaining
    spool('f1', { weight_total_g: 1000 }),                    // nominal capacity
    spool('g1', { location_id: 'loc2' }),                     // location
    spool('h1', { lot: 'B42' }),                              // lot
    spool('i1', { label: 'спец' }),                           // user label
  ];
  const { vm } = mount(makeComp(list).component);
  const S = vm.$.setupState;
  const base = S.bindStockGroups.find((g) => g.count === 2);
  // база {a1,a2}=1 группа + 8 отличий (material/vendor/color/remaining/nominal/location/lot/label) = 9 групп
  check('G2. различия material/manufacturer/color/weight(rem+nominal)/location/lot/label -> 9 групп (базовая=2)',
    S.bindStockGroups.length === 9 && !!base && base.spools.map((s) => s.id).sort().join(',') === 'a1,a2');
}

// ═══ G3: различаются только id/created_at/price -> одна группа ═══
{
  const list = [
    spool('x1', { created_at: '2026-01-01 00:00:00', price: 5 }),
    spool('x2', { created_at: '2026-05-05 12:00:00', price: 99 }),
    spool('x3', { created_at: '2026-09-09 23:59:59', price: 0 }),
  ];
  const { vm } = mount(makeComp(list).component);
  const S = vm.$.setupState;
  check('G3. различаются только id/created_at/цена -> ОДНА группа (эти поля не в ключе), count=3',
    S.bindStockGroups.length === 1 && S.bindStockGroups[0].count === 3);
}

// ═══ G4: FIFO выбирает точный ожидаемый id (ранний created_at; равные -> id) ═══
{
  const list = [
    spool('zzz', { created_at: '2026-03-03 09:00:00' }),   // не самый ранний
    spool('mmm', { created_at: '2026-01-01 08:00:00' }),   // самый ранний -> ожидаем его
    spool('aaa', { created_at: '2026-01-01 08:00:00' }),   // равен по времени, но id 'aaa' < 'mmm'
  ];
  // равные времена: mmm и aaa в '2026-01-01 08:00:00' -> tiebreak по id -> 'aaa'
  const { root, vm } = mount(makeComp(list).component);
  const S = vm.$.setupState;
  S.spickOpen(); await nextTick();
  const grow = byCls(root, 'fm-inv-spick-g')[0];
  clickEl(grow); await nextTick();
  check('G4. основной клик -> FIFO: bind.sid = «aaa» (ранний created_at + меньший id при равенстве); spick.auto=true; список закрыт',
    S.bind.sid === 'aaa' && S.spick.auto === true && S.spick.open === false
    && S.bindStockGroups[0].first.id === 'aaa');
}

// ═══ G5: раскрытие + ручной выбор -> bind.sid = выбранный конкретный id ═══
{
  const list = [spool('p1', { created_at: '2026-01-01' }), spool('p2', { created_at: '2026-02-02' }), spool('p3', { created_at: '2026-03-03' })];
  const { root, vm } = mount(makeComp(list).component);
  const S = vm.$.setupState;
  S.spickOpen(); await nextTick();
  const expBtn = byCls(root, 'fm-inv-spick-exp')[0];
  clickEl(expBtn); await nextTick();
  const subs = byCls(root, 'fm-inv-spick-s');
  const groupsAfterExpand = byCls(root, 'fm-inv-spick-g').length;
  // выбрать ВРУЧНУЮ вторую катушку (p2), а не FIFO-первую (p1)
  const p2row = subs.find((el) => el.textContent.includes('#p2'));
  clickEl(p2row); await nextTick();
  check('G5. раскрытие (кнопка ▾, не pickGroup) показывает 3 катушки; ручной клик по #p2 -> bind.sid=p2, spick.auto=false; bind НЕ выполнен',
    groupsAfterExpand === 1 && subs.length === 3 && !!p2row
    && S.bind.sid === 'p2' && S.spick.auto === false && S.spick.open === false
    && netCalls.length === 0);
}

// ═══ G6: поиск по spool id -> раскрывает нужную группу ═══
{
  netCalls.length = 0;
  const list = [
    ...Array.from({ length: 5 }, (_, i) => spool('petg' + i)),
    ...Array.from({ length: 5 }, (_, i) => spool('pla' + i, { material: 'PLA', filament_id: 'fil_pla' })),
  ];
  const { root, vm } = mount(makeComp(list).component);
  const S = vm.$.setupState;
  S.spickOpen(); await nextTick();
  S.spick.search = 'pla3'; await nextTick();
  const groups = byCls(root, 'fm-inv-spick-g');
  const subs = byCls(root, 'fm-inv-spick-s');
  const found = subs.find((el) => el.textContent.includes('#pla3'));
  check('G6. поиск «pla3» -> отфильтрована 1 группа PLA и она АВТО-раскрыта, катушка #pla3 видна',
    S.bindStockFiltered.length === 1 && groups.length === 1 && !!found
    && S.bindGroupOpen(S.bindStockFiltered[0]) === true);
}

// ═══ G7: после bind() + load() количество группы 100 -> 99 ═══
{
  netCalls.length = 0;
  const list = Array.from({ length: 100 }, (_, i) => spool('q' + String(i).padStart(3, '0'), { created_at: '2026-07-01 10:00:00', id: 'q' + String(i).padStart(3, '0') }));
  const built = makeComp(list, { printer_id: 'PRN1', slot: 0 });
  const { root, vm } = mount(built.component);
  const S = vm.$.setupState;
  check('G7a. до bind: группа = 100', S.bindStockGroups[0].count === 100);
  S.spickOpen(); await nextTick();
  clickEl(byCls(root, 'fm-inv-spick-g')[0]); await nextTick();   // FIFO выбор
  const chosen = S.bind.sid;
  await S.applyBind();                                            // POST + load()
  // эмуляция load(): выбранная катушка стала привязанной -> уходит из доступных
  const sp = S.spools.find((s) => s.id === chosen); sp.ams_printer_id = 'PRN1'; sp.ams_slot = 0;
  await nextTick();
  check('G7b. bind FIFO-катушки #' + chosen + ' -> POST на /spool/' + chosen + '/bind; после load() группа = 99',
    netCalls.length === 1 && netCalls[0].url.includes('/spool/' + chosen + '/bind')
    && netCalls[0].body.printer_id === 'PRN1' && netCalls[0].body.ams_slot === 0
    && S.bindStockGroups[0].count === 99);
}

// ═══ G8: pending/bound/deleted не входят в количество ═══
{
  const list = [
    spool('ok1'), spool('ok2'), spool('ok3'),                        // 3 доступных
    spool('bound1', { ams_printer_id: 'PRN1', ams_slot: 0 }),        // привязана
    spool('empty1', { status: 'empty' }),                            // «пустая» (эквивалент недоступной)
  ];
  // deleted катушки backend не отдаёт вовсе (is_deleted=0 фильтр на сервере) — эмулируем отсутствием в списке
  const { vm } = mount(makeComp(list).component);
  const S = vm.$.setupState;
  check('G8. bound и empty(=pending/недоступные) НЕ в количестве: группа доступных = 3 (ok1..ok3)',
    S.bindStockGroups.length === 1 && S.bindStockGroups[0].count === 3
    && S.bindStockGroups[0].spools.map((s) => s.id).sort().join(',') === 'ok1,ok2,ok3');
}

// ═══ G9: Escape закрывает СНАЧАЛА listbox (stopPropagation), потом уходит в стек ядра ═══
{
  const list = [spool('e1'), spool('e2')];
  const { root, vm } = mount(makeComp(list).component);
  const S = vm.$.setupState;
  S.spickOpen(); await nextTick();
  const inp = byCls(root, 'fm-inv-spick-inp')[0];
  const q = byCls(root, 'fm-inv-spick-q')[0];
  const stopped1 = keyEl(q, 'Escape'); await nextTick();
  check('G9a. Escape при открытом listbox: список закрыт И событие остановлено (stopPropagation -> диалог ядра НЕ закрыт)',
    S.spick.open === false && stopped1 === true);
  const stopped2 = keyEl(inp, 'Escape'); await nextTick();
  check('G9b. Escape при закрытом listbox: НЕ останавливаем событие (уйдёт в стек ядра -> закроет bind-диалог)',
    stopped2 === false);
}

// ═══ G10: AMS slot 0 / slot 1 / multi-AMS / external -> applyBind шлёт настоящий target ═══
{
  const targets = [
    { name: 'AMS slot 0', init: { printer_id: 'PRN_A', slot: 0 }, expSlot: 0 },
    { name: 'AMS slot 1', init: { printer_id: 'PRN_A', slot: 1 }, expSlot: 1 },
    { name: 'multi-AMS slot 5', init: { printer_id: 'PRN_B', slot: 5 }, expSlot: 5 },
    { name: 'external slot 0', init: { printer_id: 'PRN_C', slot: 0 }, expSlot: 0 },
  ];
  let ok = true;
  for (const t of targets) {
    netCalls.length = 0;
    const { root, vm } = mount(makeComp([spool('t1'), spool('t2')], t.init).component);
    const S = vm.$.setupState;
    S.spickOpen(); await nextTick();
    clickEl(byCls(root, 'fm-inv-spick-g')[0]); await nextTick();
    await S.applyBind();
    const c = netCalls[netCalls.length - 1];
    if (!(c && c.url.includes('/spool/' + S.bind.sid + '/bind') && c.body.printer_id === t.init.printer_id && c.body.ams_slot === t.expSlot && /^t[12]$/.test(S.bind.sid))) ok = false;
  }
  check('G10. AMS slot0/slot1/multi-AMS(5)/external -> applyBind шлёт настоящий (printer_id, ams_slot) + реальный spool id (не group id)', ok);
}

// ═══ G11: 1000 одинаковых кандидатов -> в DOM НЕ сотни верхнеуровневых строк ═══
{
  const list = Array.from({ length: 1000 }, (_, i) => spool('big' + String(i).padStart(4, '0'), { created_at: '2026-07-01 10:00:00' }));
  const { root, vm } = mount(makeComp(list).component);
  const S = vm.$.setupState;
  S.spickOpen(); await nextTick();
  const topRows = byCls(root, 'fm-inv-spick-g');       // верхнеуровневые групповые строки
  const subRows = byCls(root, 'fm-inv-spick-s');       // раскрытые катушки (группа свёрнута -> 0)
  const badge = byCls(root, 'fm-inv-spick-badge')[0];
  check('G11. 1000 одинаковых -> в DOM 1 верхнеуровневая строка (не сотни), sub-строк 0 (свёрнута), бейдж «1000 шт.»',
    S.bindStockGroups.length === 1 && S.bindStockGroups[0].count === 1000
    && topRows.length === 1 && subRows.length === 0 && !!badge && badge.textContent.trim() === '1000 шт.');
}

// ═══ CG: круглый маркер группы .fm-inv-spick-sw залит РЕАЛЬНЫМ цветом (safeHex); бел/чёрн/невалид; закрытое поле ═══
{
  const list = [
    spool('cr', { filament_id: 'f_r', color_name: 'Red', color_hex: 'FF0000' }),
    spool('cb', { filament_id: 'f_b', color_name: 'Blue', color_hex: '#00aeef' }),
    spool('cw', { filament_id: 'f_w', color_name: 'White', color_hex: 'FFFFFF' }),
    spool('ck', { filament_id: 'f_k', color_name: 'Black', color_hex: '000000' }),
    spool('cx', { filament_id: 'f_x', color_name: 'Bad', color_hex: 'red; url(x)' }),   // невалид/CSS-инъекция
  ];
  const { root, vm } = mount(makeComp(list).component);
  const S = vm.$.setupState;
  S.spickOpen(); await nextTick();
  const gsw = byCls(root, 'fm-inv-spick-sw');   // маркеры групп (закрытого поля ещё нет: bind.sid='')
  const bgs = gsw.map((e) => e.style.background);
  check('CG1. 5 групп разного цвета: круг .fm-inv-spick-sw залит ФАКТИЧЕСКИМ цветом через safeHex (#FF0000/#00AEEF/#FFFFFF/#000000); невалид/CSS-инъекция → нейтраль var(--fm-border-strong)',
    gsw.length === 5 && new Set(bgs).size === 5
    && bgs.includes('#FF0000') && bgs.includes('#00AEEF') && bgs.includes('#FFFFFF') && bgs.includes('#000000')
    && bgs.includes('var(--fm-border-strong)'));
  // клик по красной группе (маркер декоративен) → закрытое поле показывает её цвет; выбран реальный FIFO spool id, не group id
  const redRow = byCls(root, 'fm-inv-spick-g').find((r) => byCls(r, 'fm-inv-spick-sw')[0] && byCls(r, 'fm-inv-spick-sw')[0].style.background === '#FF0000');
  clickEl(redRow); await nextTick();
  const closed = byCls(root, 'fm-inv-spick-sw');
  check('CG2. клик по красной группе → закрытое поле показывает #FF0000; bind.sid = реальный FIFO spool id "cr" (не group id); список закрыт; декоративный маркер не вызвал преждевременный bind',
    S.spick.open === false && S.bind.sid === 'cr' && closed.length === 1 && closed[0].style.background === '#FF0000' && S.bind.bound === false);
}

console.log('\n' + (fail ? ('FAIL: ' + fail + ' проверок провалено') : 'PASS: combobox привязки — группировка одинаковых катушек, FIFO/ручной выбор, поиск по ID, Escape-стек, реальный spool id в backend, 1000→1 строка, ЦВЕТ группы/закрытого поля через safeHex (реальный Vue mount)'));
process.exit(fail ? 1 : 0);
