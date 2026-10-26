// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// РЕАЛЬНЫЙ Vue runtime-тест трёхуровневого «Склад → На складе» — inventory 1.7.11.
// Монтирует ДОСЛОВНУЮ разметку списка склада из shipped InventoryPanel.js настоящим вендорным Vue на
// самодельном DOM поверх ДОСЛОВНО извлечённых функций (warehouseGroups/toggleMat/toggleVar/matStateChips/
// groupSelState/toggleGroupSel/onRowClick/…). Доказывает:
//   T1  PETG ×39 → ОДНА карточка материала;
//   T2  37 одинаковых 100% → один агрегированный чип (≤3 чипа), НЕ 37 DOM-badge;
//   T3  разные color/location/lot → отдельные варианты внутри PETG;
//   T4  свёрнутая группа 1000 → 0 физических DOM-строк (и 0 строк вариантов);
//   T5  раскрытие материала → только строки ВАРИАНТОВ (0 физических);
//   T6  раскрытие одного варианта → только его физические катушки (другие варианты не раскрыты);
//   T7  закрытие варианта → физические строки удалены из DOM (v-if, не v-show);
//   T8  фильтр/поиск пересчитывают count и массу по видимым;
//   T9  checkbox материала + indeterminate работают на реальных spool id;
//   T10 chevron material/variant НЕ переключает checkbox и не открывает меню (stop);
//   T11 bulk-примитивы целы (selectAllVisible/ invertVisible по всем видимым катушкам склада);
//   T12 «В работе» (workSections) и bind-combobox 1.7.10 (bindStockGroups/bindGroupKey) в панели не тронуты;
//   DOM T13 отчётные количества DOM-элементов для 39 и 1000 (collapsed / mat-expanded / variant-expanded).
// Запуск: node tools/test_inventory_stock_levels_runtime.mjs   (0 = все проверки пройдены)
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
  constructor(tag) { super(1); this._tag = tag; this.tagName = String(tag).toUpperCase(); this.namespaceURI = 'http://www.w3.org/1999/xhtml'; this.attributes = {}; this._listeners = {}; this.style = {}; this._cls = ''; this._html = ''; }
  setAttribute(k, v) { this.attributes[k] = String(v); if (k === 'class') this._cls = String(v); }
  removeAttribute(k) { delete this.attributes[k]; if (k === 'class') this._cls = ''; }
  getAttribute(k) { return k in this.attributes ? this.attributes[k] : null; }
  hasAttribute(k) { return k in this.attributes; }
  get className() { return this._cls; }
  set className(v) { this._cls = v == null ? '' : String(v); this.attributes['class'] = this._cls; }
  get classList() { const s = this; const set = () => new Set(s._cls.split(/\s+/).filter(Boolean)); const put = (x) => { s.className = [...x].join(' '); }; return { add: (...c) => { const x = set(); c.forEach((y) => x.add(y)); put(x); }, remove: (...c) => { const x = set(); c.forEach((y) => x.delete(y)); put(x); }, contains: (c) => set().has(c), toggle: (c) => { const x = set(); x.has(c) ? x.delete(c) : x.add(c); put(x); } }; }
  addEventListener(t, fn) { (this._listeners[t] = this._listeners[t] || []).push(fn); }
  removeEventListener(t, fn) { const a = this._listeners[t]; if (a) { const i = a.indexOf(fn); if (i >= 0) a.splice(i, 1); } }
  get textContent() { return this.childNodes.map((c) => c.nodeType === 3 ? c.nodeValue : (c.nodeType === 1 ? c.textContent : '')).join(''); }
  set textContent(v) { this.childNodes.forEach((c) => (c.parentNode = null)); this.childNodes = []; if (v !== '' && v != null) this.appendChild(new DText(String(v))); }
  hasChildNodes() { return this.childNodes.length > 0; }
  get firstChild() { return this.childNodes[0] || null; }
  get innerHTML() { return this._html; }
  set innerHTML(v) { this._html = v == null ? '' : String(v); if (v === '' || v == null) { this.childNodes.forEach((c) => (c.parentNode = null)); this.childNodes = []; } }
  querySelector() { return null; }
  _fire(type, ev) { (this._listeners[type] || []).slice().forEach((fn) => fn(ev)); }
  _findAll(pred, out = []) { if (this.nodeType === 1 && pred(this)) out.push(this); this.childNodes.forEach((c) => { if (c.nodeType === 1) c._findAll(pred, out); }); return out; }
}
const doc = { createElement: (t) => new DElement(t), createElementNS: (ns, t) => new DElement(t), createTextNode: (t) => new DText(t), createComment: (t) => new DComment(t), querySelector: () => null, addEventListener: () => {}, removeEventListener: () => {}, activeElement: null };
doc.body = new DElement('body'); doc.head = new DElement('head'); doc.documentElement = new DElement('html');
if (!globalThis.document) globalThis.document = doc;
if (!globalThis.window) { try { globalThis.window = globalThis; } catch (e) {} }
for (const g of ['SVGElement', 'HTMLElement', 'Element', 'Node', 'ShadowRoot', 'Document', 'DocumentFragment']) { if (globalThis[g] === undefined) globalThis[g] = class {}; }

// ─────────── извлечение ДОСЛОВНОГО `const NAME = <expr>;` ───────────
const extractConst = (src, name) => {
  const anchor = 'const ' + name + ' = '; const i = src.indexOf(anchor);
  if (i < 0) throw new Error('not found: ' + name);
  let d = 0, q = null, esc = false;
  for (let k = i + anchor.length; k < src.length; k++) { const ch = src[k];
    if (esc) { esc = false; continue; } if (q) { if (ch === '\\') esc = true; else if (ch === q) q = null; continue; }
    if (ch === "'" || ch === '"' || ch === '`') { q = ch; continue; }
    if ('([{'.includes(ch)) d++; else if (')]}'.includes(ch)) d--; else if (ch === ';' && d === 0) return src.slice(i, k + 1); }
  throw new Error('unbalanced: ' + name);
};
const NAMES = ['pct', '_dir', '_spoolMatch', '_fMatch', 'spoolById', 'isBound', '_gnum', '_gtxt', '_ghex', 'safeHex', '_matKey', '_variantKey', '_lowW',
  'warehouseGroups', 'expandedMat', 'expandedVar', 'isMatOpen', 'isVarOpen', 'toggleMat', 'toggleVar',
  'matStateChips', 'matVendorLine', 'variantLabel', 'variantSub', '_hashId', 'spoolIdent', 'isEmptySpool', 'visibleSpoolsOrdered',
  'groupSelState', 'toggleGroupSel', 'toggleSpoolSel', 'onRowClick', 'selectAllVisible', 'invertVisible'];
const SRCS = NAMES.map((n) => extractConst(PANEL, n));
check('T0. дословные функции склада извлечены из shipped-панели (' + NAMES.length + ')', SRCS.every((s) => s.length > 3));

// ─────────── ДОСЛОВНАЯ разметка списка склада ───────────
const KEY = '<div v-else class="fm-inv-wlist">';
const ms = PANEL.indexOf(KEY); const mOpenEnd = PANEL.indexOf('>', ms) + 1;
const mRe = /<div\b|<\/div>/g; mRe.lastIndex = mOpenEnd; let mm, dep = 1, mClose = -1;
while ((mm = mRe.exec(PANEL))) { dep += (mm[0] === '</div>') ? -1 : 1; if (dep === 0) { mClose = mm.index; break; } }
const MARKUP = PANEL.slice(ms, mClose + 6).replace('v-else class="fm-inv-wlist"', 'v-if="true" class="fm-inv-wlist"');
check('T0b. разметка склада извлечена (mcard/mhead/секции/варианты/физ.строки)',
  MARKUP.includes('fm-inv-mcard') && MARKUP.includes('fm-inv-msec-state') && MARKUP.includes('v-for="v in g.variants"') && MARKUP.includes('v-for="s in v.spools"') && MARKUP.includes('toggleMat(g)') && MARKUP.includes('toggleVar(v)'));

const Vue = await import(pathToFileURL(join(REPO, 'web', 'vendor', 'vue.esm-browser.js')).href);
const { createApp, ref, reactive, computed, nextTick } = Vue;

// ─────────── фабрика: РЕАЛЬНЫЕ функции сшиты в setup ───────────
const buildSetup = new Function('Vue', 'env', [
  'const { ref, reactive, computed } = Vue;',
  'const { spoolList, lowGv } = env;',
  'const L = (ru, en) => ru;',
  'const spools = ref(spoolList.map((s) => ({ ...s })));',
  'const q = ref(""); const sortBy = ref("material"); const sortDir = ref("asc");',
  'const fMat = ref(""); const fVendor = ref(""); const fLoc = ref(""); const fLow = ref(false);',
  'const lowG = ref(lowGv);',
  'const locName = (id) => id ? ("Локация " + id) : "";',
  'const barColor = () => "#888"; const statusLabel = (k) => k; const spoolSvg = () => "<svg></svg>";',
  'const openHist = () => {}; const spoolMenu = () => {}; const groupMenu = () => {}; const flash = () => {};',
  'const selMode = ref(false); const selected = reactive(new Set()); const lastClickedId = ref("");',
  SRCS.join('\n'),
  'return { L, spools, q, sortBy, sortDir, fMat, fVendor, fLoc, fLow, lowG, locName, barColor, statusLabel, spoolSvg, openHist, spoolMenu, groupMenu, selMode, selected, lastClickedId, ' + NAMES.join(', ') + ' };',
].join('\n'));
const makeComp = (spoolList, lowGv) => {
  let state;
  return { component: {
    setup() { state = buildSetup(Vue, { spoolList, lowGv: lowGv == null ? 100 : lowGv }); return state; },
    template: '<div class="root">' + MARKUP + '</div>',
    compilerOptions: { decodeEntities: (x) => x },
  }, getState: () => state };
};
const mount = (mk) => { const app = createApp(mk.component); app.config.warnHandler = () => {}; const root = new DElement('div'); const vm = app.mount(root); return { root, vm, S: () => vm.$.setupState }; };
const byCls = (root, c) => root._findAll((e) => (' ' + e.className + ' ').includes(' ' + c + ' '));
const dataRows = (root) => byCls(root, 'fm-inv-srow').filter((e) => !(' ' + e.className + ' ').includes(' fm-inv-srow-h '));
const clickEl = (el) => el._fire('click', { type: 'click', target: el, currentTarget: el, stopPropagation() {}, preventDefault() {} });

// ─────────── fixtures ───────────
const sp = (id, over) => Object.assign({ id, filament_id: 'f_petg_blk', material: 'PETG', color_name: 'Чёрный', color_hex: '#111', vendor_name: 'GEHR', weight_remaining_g: 1000, weight_total_g: 1000, diameter: 1.75, location_id: 'loc1', lot: '', label: '', price: 10, status: 'in_stock', ams_printer_id: '', ams_slot: -1, is_deleted: 0, created_at: '2026-07-01 10:00:00' }, over);

// ═══ T1: PETG ×39 → одна карточка материала ═══
{
  const list = Array.from({ length: 39 }, (_, i) => sp('p' + String(i).padStart(3, '0')));
  const { root, S } = mount(makeComp(list));
  await nextTick();
  check('T1. PETG ×39 → 1 карточка материала (.fm-inv-mcard); warehouseGroups.length=1, count=39, variantCount=1',
    byCls(root, 'fm-inv-mcard').length === 1 && S().warehouseGroups.length === 1
    && S().warehouseGroups[0].count === 39 && S().warehouseGroups[0].variantCount === 1);
}

// ═══ T2: 37 одинаковых 100% → агрегат, не 37 badge ═══
{
  const list = [
    ...Array.from({ length: 37 }, (_, i) => sp('f' + i, { weight_remaining_g: 1000 })),   // full 100%
    ...Array.from({ length: 2 }, (_, i) => sp('o' + i, { weight_remaining_g: 930 })),      // open 93%
  ];
  const { root, S } = mount(makeComp(list, 100));
  await nextTick();
  const chips = byCls(root, 'fm-inv-schip');
  const M = S().warehouseGroups[0];
  check('T2. 37×100% + 2×93% → ровно ≤3 агрегированных чипа (Полные 37 / Открытые 2 / Мало 0), НЕ 37 badge',
    M.fullN === 37 && M.openN === 2 && M.lowN === 0 && chips.length === 3
    && chips[0].textContent.includes('37') && chips[1].textContent.includes('2'));
}

// ═══ T3: разные color/location/lot → отдельные варианты внутри PETG ═══
{
  const list = [
    sp('a1'), sp('a2'),                                                  // base variant
    sp('b1', { color_hex: '#2b6cff', color_name: 'Синий', filament_id: 'f_petg_blue' }),  // color
    sp('c1', { location_id: 'loc2' }),                                    // location
    sp('d1', { lot: 'B7' }),                                              // lot
  ];
  const { root, S } = mount(makeComp(list));
  await nextTick();
  const M = S().warehouseGroups[0];
  check('T3. PETG с различиями color/location/lot → 1 материал, 4 варианта (base=2)',
    S().warehouseGroups.length === 1 && M.variantCount === 4
    && M.variants.find((v) => v.count === 2) && M.variants.length === 4);
}

// ═══ T3-independent: КАЖДОЕ отдельное различающее поле создаёт отдельный вариант (variant key явно структурирован) ═══
// База: две идентичные PETG-катушки → 1 вариант; добавляем ТРЕТЬЮ, отличную РОВНО одним полем → 2 варианта.
// «one» — значения общей базы; отличаем ровно одно поле в третьей катушке.
{
  const base = () => ({ filament_id: 'f0', material: 'PETG', vendor_name: 'GEHR', color_name: 'Чёрный', color_hex: '#111111', diameter: 1.75, weight_total_g: 1000, location_id: 'loc1', lot: 'B7' });
  const mk = (id, over) => sp(id, Object.assign(base(), over, { weight_remaining_g: 1000 }));
  const cases = [
    ['I1 только manufacturer', { vendor_name: 'Bambu' }],
    ['I2 только color_name', { color_name: 'Графит' }],
    ['I3 только color_hex', { color_hex: '#222222' }],
    ['I4 только diameter', { diameter: 2.85 }],
    ['I5 только location', { location_id: 'loc2' }],
    ['I6 только lot', { lot: 'B8' }],
    ['I7 только nominal weight', { weight_total_g: 750 }],
    ['I8 legacy без filament_id (тот же материал/цвет, но разный производитель)', { filament_id: '', vendor_name: 'NoName' }],
  ];
  for (const [name, over] of cases) {
    // I8 особый: обе базовые тоже без filament_id, отличается только vendor → должны быть 2 варианта, не 1
    const b0 = over.filament_id === '' ? { filament_id: '' } : {};
    const list = [mk('a', b0), mk('b', b0), mk('c', over)];
    const { S } = mount(makeComp(list));
    const M = S().warehouseGroups[0];
    check('T3-' + name + ' → ОТДЕЛЬНЫЙ вариант (2 варианта: база×2 + отличие×1)',
      S().warehouseGroups.length === 1 && M.variantCount === 2
      && !!M.variants.find((v) => v.count === 2) && !!M.variants.find((v) => v.count === 1));
  }
  // Контроль: РАЗНЫЙ текущий остаток при прочих равных НЕ делит вариант
  const list2 = [mk('r1', { weight_remaining_g: 1000 }), mk('r2', { weight_remaining_g: 640 }), mk('r3', { weight_remaining_g: 90 })];
  const { S: S2 } = mount(makeComp(list2, 100));
  check('T3-ctl. разный ТЕКУЩИЙ остаток (1000/640/90) при прочих равных → ОДИН вариант (остаток не в ключе), count=3',
    S2().warehouseGroups.length === 1 && S2().warehouseGroups[0].variantCount === 1 && S2().warehouseGroups[0].variants[0].count === 3);
  // Нормализация: регистр текста / hex-регистр / 1000 vs 1000.0 НЕ делят вариант
  const list3 = [
    sp('n1', { filament_id: 'FX', material: 'PETG', vendor_name: 'GEHR', color_name: 'Чёрный', color_hex: '#AABBCC', diameter: 1.75, weight_total_g: 1000, location_id: 'loc1', lot: 'B7', weight_remaining_g: 1000 }),
    sp('n2', { filament_id: '  fx ', material: 'petg', vendor_name: ' gehr ', color_name: 'чёрный', color_hex: 'aabbcc', diameter: 1.75, weight_total_g: 1000.0, location_id: 'loc1', lot: 'b7', weight_remaining_g: 500 }),
  ];
  const { S: S3 } = mount(makeComp(list3));
  check('T3-norm. регистр/пробелы/hex-регистр/1000==1000.0 нормализованы (как bindGroupKey) → ОДИН вариант, count=2',
    S3().warehouseGroups.length === 1 && S3().warehouseGroups[0].variantCount === 1 && S3().warehouseGroups[0].variants[0].count === 2);
}

// ═══ T4: свёрнутая группа 1000 → 0 физических строк, 0 строк вариантов ═══
let dom1000collapsed, dom1000mat, dom1000var;
{
  const list = Array.from({ length: 1000 }, (_, i) => sp('big' + String(i).padStart(4, '0')));
  const { root, S } = mount(makeComp(list));
  await nextTick();
  dom1000collapsed = { mcard: byCls(root, 'fm-inv-mcard').length, vhead: byCls(root, 'fm-inv-vhead').length, srow: dataRows(root).length };
  check('T4. свёрнутый материал из 1000 катушек: 1 карточка, 0 строк вариантов, 0 физических строк',
    dom1000collapsed.mcard === 1 && dom1000collapsed.vhead === 0 && dom1000collapsed.srow === 0);
  // T5 (mat expand): только строки вариантов
  S().toggleMat(S().warehouseGroups[0]); await nextTick();
  dom1000mat = { vhead: byCls(root, 'fm-inv-vhead').length, srow: dataRows(root).length };
  check('T5. раскрытие материала (1000 одинаковых → 1 вариант): 1 строка варианта, 0 физических строк',
    dom1000mat.vhead === 1 && dom1000mat.srow === 0);
  // T6 (variant expand): физические катушки
  S().toggleVar(S().warehouseGroups[0].variants[0]); await nextTick();
  dom1000var = { vhead: byCls(root, 'fm-inv-vhead').length, srow: dataRows(root).length };
  check('T6. раскрытие варианта: появились 1000 физических строк (только его катушки)',
    dom1000var.srow === 1000);
  // T7 (close variant): rows removed
  S().toggleVar(S().warehouseGroups[0].variants[0]); await nextTick();
  check('T7. закрытие варианта: физические строки удалены из DOM (v-if): 0',
    dataRows(root).length === 0);
}

// ═══ T6b: раскрытие одного варианта не раскрывает другие ═══
{
  const list = [sp('v1a'), sp('v1b'), sp('v2a', { color_hex: '#2b6cff', filament_id: 'f2' }), sp('v2b', { color_hex: '#2b6cff', filament_id: 'f2' })];
  const { root, S } = mount(makeComp(list));
  await nextTick();
  S().toggleMat(S().warehouseGroups[0]); await nextTick();
  const M = S().warehouseGroups[0];
  S().toggleVar(M.variants[0]); await nextTick();
  check('T6b. раскрыт только вариант[0] (2 катушки); вариант[1] свёрнут → всего 2 физ.строки, не 4',
    dataRows(root).length === 2 && S().isVarOpen(M.variants[0]) === true && S().isVarOpen(M.variants[1]) === false);
}

// ═══ T8: фильтр/поиск пересчитывают count и массу по видимым ═══
{
  const list = [
    ...Array.from({ length: 3 }, (_, i) => sp('pg' + i, { weight_remaining_g: 1000 })),                                   // PETG 3×1000
    ...Array.from({ length: 2 }, (_, i) => sp('pl' + i, { material: 'PLA', filament_id: 'f_pla', weight_remaining_g: 500 })), // PLA 2×500
  ];
  const { root, S } = mount(makeComp(list));
  await nextTick();
  const before = S().warehouseGroups.length;
  const petgBefore = S().warehouseGroups.find((g) => g.material === 'PETG');
  S().fMat = 'PLA'; await nextTick();
  const after = S().warehouseGroups;
  check('T8. фильтр материала PLA: остаётся 1 карточка PLA, count=2, общий остаток=1000 г (пересчёт по видимым)',
    before === 2 && petgBefore.count === 3 && petgBefore.totalG === 3000
    && after.length === 1 && after[0].material === 'PLA' && after[0].count === 2 && after[0].totalG === 1000);
}

// ═══ T9: checkbox материала + indeterminate ═══
{
  const list = Array.from({ length: 4 }, (_, i) => sp('s' + i));
  const { root, S } = mount(makeComp(list));
  S().selMode = true; await nextTick();
  const M = S().warehouseGroups[0];
  // частичный выбор → indeterminate
  S().selected.add('s0'); await nextTick();
  const st1 = S().groupSelState(M);
  const cbInd = byCls(root, 'fm-inv-cb').find((e) => (' ' + e.className + ' ').includes(' ind '));
  // полный выбор через toggleGroupSel
  S().toggleGroupSel(M); await nextTick();
  const st2 = S().groupSelState(M);
  check('T9. selMode: 1 из 4 → indeterminate (some); toggleGroupSel → все выбраны (all), реальные spool id',
    st1.some === true && st1.all === false && !!cbInd
    && st2.all === true && S().selected.size === 4 && S().selected.has('s0') && S().selected.has('s3'));
}

// ═══ T10: 1.7.20 — chevron удалён; раскрытие по клику ЗАГОЛОВКА материала (.fm-inv-mhead), выбор не меняется ═══
{
  const list = Array.from({ length: 3 }, (_, i) => sp('c' + i));
  const { root, S } = mount(makeComp(list));
  S().selMode = true; await nextTick();
  const before = S().selected.size;
  const head = byCls(root, 'fm-inv-mhead')[0];
  const chevGone = byCls(root, 'fm-inv-mchev').length === 0;   // отдельной стрелки-chevron больше нет
  clickEl(head); await nextTick();
  check('T10. клик по заголовку материала (.fm-inv-mhead) раскрывает материал; chevron удалён; выбор НЕ меняется (checkbox @click.stop)',
    chevGone && S().isMatOpen(S().warehouseGroups[0]) === true && S().selected.size === before && before === 0);
}

// ═══ T10b: клавиатурная доступность — Enter и Space на заголовке материала раскрывают/сворачивают (a11y) ═══
{
  const { root, S } = mount(makeComp(Array.from({ length: 3 }, (_, i) => sp('k' + i))));
  const head = byCls(root, 'fm-inv-mhead')[0];
  const keyEl = (el, key) => el._fire('keydown', { type: 'keydown', key, target: el, currentTarget: el, preventDefault() {}, stopPropagation() {} });
  const g0 = () => S().warehouseGroups[0];
  const start = S().isMatOpen(g0());
  keyEl(head, 'Enter'); await nextTick(); const afterEnter = S().isMatOpen(g0());
  keyEl(head, ' '); await nextTick(); const afterSpace = S().isMatOpen(g0());
  check('T10b. a11y: role=button/tabindex=0; Enter раскрывает, Space сворачивает заголовок материала',
    head.getAttribute('role') === 'button' && head.getAttribute('tabindex') === '0'
    && start === false && afterEnter === true && afterSpace === false);
}

// ═══ T10c: checkbox группы (@click.stop) НЕ раскрывает материал случайно — только выбор ═══
{
  const { root, S } = mount(makeComp([sp('c0'), sp('c1')]));
  S().selMode = true; await nextTick();
  const openBefore = S().isMatOpen(S().warehouseGroups[0]);
  const cb = byCls(root, 'fm-inv-cb')[0];   // групповой checkbox в заголовке
  clickEl(cb); await nextTick();
  check('T10c. клик по checkbox заголовка (@click.stop) меняет ВЫБОР, но НЕ раскрывает материал (toggleGroupSel, не toggleMat)',
    !!cb && openBefore === false && S().isMatOpen(S().warehouseGroups[0]) === false && S().selected.size > 0);
}

// ═══ T11: bulk-примитивы целы (selectAllVisible / invertVisible по всем видимым катушкам склада) ═══
{
  const list = [sp('x1'), sp('x2', { color_hex: '#2b6cff', filament_id: 'f2' }), sp('x3', { material: 'PLA', filament_id: 'f_pla' })];
  const { S } = mount(makeComp(list));
  S().selMode = true; await nextTick();
  S().selectAllVisible(); await nextTick();
  const allN = S().selected.size, hadX1 = S().selected.has('x1'), hadX3 = S().selected.has('x3');
  S().invertVisible(); await nextTick();
  check('T11. selectAllVisible выбрал все 3 видимые (x1/x3 в т.ч., по вариантам/материалам); invertVisible снял все → 0',
    allN === 3 && hadX1 && hadX3 && S().selected.size === 0);
}

// ═══ T12: «В работе» и bind-combobox 1.7.10 не тронуты (мост к файлу) ═══
{
  check('T12. панель по-прежнему содержит workSections (В работе) и bindStockGroups/bindGroupKey (bind-combobox 1.7.10)',
    PANEL.includes('const workSections = computed') && PANEL.includes('const bindStockGroups = computed')
    && PANEL.includes('const bindGroupKey =') && PANEL.includes('(row,ri) in spickRows'));
}

// ═══ ID*: единый формат идентификации катушки в колонке «Катушка» (без наложения/дублей) ═══
// Хелпер: собрать физические строки с их primary/secondary текстами (реальный DOM после раскрытия).
const identRows = (root) => dataRows(root).map((r) => {
  const mid = byCls(r, 'fm-inv-srow-mid')[0];
  const lbl = mid && byCls(mid, 'fm-inv-srow-lbl')[0];
  const id2 = mid && byCls(mid, 'fm-inv-srow-id2')[0];
  return { primary: lbl ? lbl.textContent.trim() : '', primaryEl: lbl, secondary: id2 ? id2.textContent.trim() : null, secondaryEl: id2 || null };
});
const mountExpanded = async (list) => {
  const m = mount(makeComp(list)); await nextTick();
  m.S().toggleMat(m.S().warehouseGroups[0]); await nextTick();
  for (const v of m.S().warehouseGroups[0].variants) m.S().toggleVar(v);
  await nextTick();
  return m;
};
// ID1: катушка без label → ID один раз (primary «#id», нет secondary)
{
  const m = await mountExpanded([sp('spl_a1b2c3d4e5f6', { label: '' })]);
  const rows = identRows(m.root);
  check('ID1. без label → ID показан РОВНО один раз (primary «#spl_a1b2c3d4e5f6», secondary отсутствует)',
    rows.length === 1 && rows[0].primary === '#spl_a1b2c3d4e5f6' && rows[0].secondary === null);
}
// ID2: label == id (или «#id») → одна строка
{
  const m = await mountExpanded([sp('spl_x', { label: 'spl_x' }), sp('spl_y', { label: '#spl_y' })]);
  const rows = identRows(m.root);
  check('ID2. label совпадает с id / «#id» → ОДНА строка (secondary отсутствует у обеих)',
    rows.length === 2 && rows.every((r) => r.secondary === null)
    && rows.some((r) => r.primary === '#spl_x') && rows.some((r) => r.primary === '#spl_y'));
}
// ID3: label отличается → две отдельные строки (primary=label, secondary=«#id»)
{
  const m = await mountExpanded([sp('spl_z9', { label: 'Красная про-серия' })]);
  const rows = identRows(m.root);
  check('ID3. содержательный label ≠ id → ДВЕ строки: primary=label, secondary=«#spl_z9», это РАЗНЫЕ элементы',
    rows.length === 1 && rows[0].primary === 'Красная про-серия' && rows[0].secondary === '#spl_z9'
    && rows[0].primaryEl !== rows[0].secondaryEl);
}
// ID4: очень длинные label и id → обе строки с ellipsis-классами, отдельные элементы (геометрия — в Edge-рендере)
{
  const longId = 'spl_' + 'abcdef012345'.repeat(3);
  const m = await mountExpanded([sp(longId, { label: 'Очень длинное пользовательское имя катушки для проверки переноса и многоточия' })]);
  const rows = identRows(m.root);
  const lblCss = /overflow:hidden;text-overflow:ellipsis;white-space:nowrap/;
  const panelCss = PANEL;
  check('ID4. длинные label+id → 2 отдельных элемента; у .fm-inv-srow-lbl и .fm-inv-srow-id2 есть ellipsis+nowrap+min-width:0 у mid (без absolute)',
    rows[0].primaryEl && rows[0].secondaryEl && rows[0].primaryEl !== rows[0].secondaryEl
    && lblCss.test(panelCss.match(/\.fm-inv-srow-lbl\{[^}]*\}/)[0])
    && lblCss.test(panelCss.match(/\.fm-inv-srow-id2\{[^}]*\}/)[0])
    && /\.fm-inv-srow-mid\{[^}]*min-width:0/.test(panelCss)
    && !/position:absolute/.test(panelCss.match(/\.fm-inv-srow-id2\{[^}]*\}/)[0]));
}
// ID5: id уже начинается с # → без двойного ##
{
  const m = await mountExpanded([sp('#spl_hashed', { label: '' })]);
  const rows = identRows(m.root);
  check('ID5. id уже с «#» → primary «#spl_hashed» (нет «##»)',
    rows.length === 1 && rows[0].primary === '#spl_hashed' && !rows[0].primary.includes('##'));
}
// ID6: несколько физических строк независимы (свои primary/secondary)
{
  const m = await mountExpanded([sp('spl_m1', { label: '' }), sp('spl_m2', { label: 'Партия A' }), sp('spl_m3', { label: 'spl_m3' })]);
  const rows = identRows(m.root).sort((a, b) => a.primary.localeCompare(b.primary));
  const byId = (frag) => rows.find((r) => r.primary.includes(frag) || (r.secondary || '').includes(frag));
  check('ID6. 3 строки независимы: m1 (нет label→1 строка), m2 (label «Партия A» + «#spl_m2»), m3 (label=id→1 строка)',
    rows.length === 3
    && byId('spl_m1').secondary === null
    && byId('Партия A').primary === 'Партия A' && byId('Партия A').secondary === '#spl_m2'
    && (rows.find((r) => r.primary === '#spl_m3')).secondary === null);
}
// ID7: меню/checkbox/bulk/раскрытие целы при новой разметке идентификации
{
  const m = mount(makeComp([sp('spl_k1', { label: 'X' }), sp('spl_k2', { label: '' })]));
  m.S().selMode = true; await nextTick();
  m.S().toggleMat(m.S().warehouseGroups[0]); await nextTick();
  for (const v of m.S().warehouseGroups[0].variants) m.S().toggleVar(v);
  await nextTick();
  const cbBefore = byCls(m.root, 'fm-inv-cb').length;
  const gmore = byCls(m.root, 'fm-inv-gmore').length;   // кнопки «⋯» (группа + строки)
  m.S().toggleGroupSel(m.S().warehouseGroups[0]); await nextTick();
  check('ID7. при новой разметке: checkbox-ячейки рендерятся, есть меню «⋯», bulk выбирает все катушки материала',
    cbBefore >= 2 && gmore >= 1 && m.S().selected.size === 2);
}

// ═══ DOM-отчёт для 39 и 1000 ═══
{
  const mk39 = (n) => Array.from({ length: n }, (_, i) => sp('r' + String(i).padStart(4, '0')));
  const m39 = mount(makeComp(mk39(39))); await nextTick();
  const c39 = { mcard: byCls(m39.root, 'fm-inv-mcard').length, vhead: byCls(m39.root, 'fm-inv-vhead').length, srow: dataRows(m39.root).length };
  m39.S().toggleMat(m39.S().warehouseGroups[0]); await nextTick();
  const e39mat = { vhead: byCls(m39.root, 'fm-inv-vhead').length, srow: dataRows(m39.root).length };
  m39.S().toggleVar(m39.S().warehouseGroups[0].variants[0]); await nextTick();
  const e39var = dataRows(m39.root).length;
  console.log('\n  DOM (39 одинаковых): collapsed mcard=' + c39.mcard + ' vhead=' + c39.vhead + ' srow=' + c39.srow
    + ' | mat-expanded vhead=' + e39mat.vhead + ' srow=' + e39mat.srow + ' | variant-expanded srow=' + e39var);
  console.log('  DOM (1000 одинаковых): collapsed mcard=' + dom1000collapsed.mcard + ' vhead=' + dom1000collapsed.vhead + ' srow=' + dom1000collapsed.srow
    + ' | mat-expanded vhead=' + dom1000mat.vhead + ' srow=' + dom1000mat.srow + ' | variant-expanded srow=' + dom1000var.srow);
  check('T13. отчёт DOM: 39 collapsed→(1 карточка,0,0), mat→(1 вариант,0), variant→39; 1000 collapsed→(1,0,0), variant→1000',
    c39.mcard === 1 && c39.srow === 0 && e39mat.vhead === 1 && e39mat.srow === 0 && e39var === 39
    && dom1000collapsed.srow === 0 && dom1000var.srow === 1000);
}

console.log('\n' + (fail ? ('FAIL: ' + fail + ' проверок провалено') : 'PASS: трёхуровневый «На складе» — материал/вариант/катушки, агрегат состояния, ленивое раскрытие, bulk/фильтры целы (реальный Vue mount)'));
process.exit(fail ? 1 : 0);
