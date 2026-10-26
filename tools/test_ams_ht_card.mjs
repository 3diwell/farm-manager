// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// РЕАЛЬНЫЙ Vue runtime-тест отображения дополнительного AMS HT в карточке принтера — Alpha 2.730.
// Баг: amsGroups нумеровал блоки ПОЗИЦИОННО (n=i+1), поэтому AMS HT (unit 128, глоб. index 512)
// подписывался как «AMS 2», а filamentRows выдавал «AMS 2·1». Фикс: unit>=128 → «AMS HT» (единый источник),
// обычные → «AMS 1/2/…»; index 512 остаётся идентификатором позиции, но НЕ превращается в 513 ячеек.
// Проверяем ВЫПОЛНЕНИЕМ ДОСЛОВНО извлечённых из web/app.js amsGroups/filamentRows/amsIsHt + МОНТИРУЕМ
// ДОСЛОВНУЮ разметку компактной AMS-полосы (web/index.html) настоящим вендорным Vue на самодельном DOM.
// Fixture = принтер H1 со скриншота. Запуск: node tools/test_ams_ht_card.mjs   (0 = все проверки пройдены)
import { readFileSync } from 'fs';
import { fileURLToPath, pathToFileURL } from 'url';
import { dirname, join } from 'path';

const REPO = dirname(dirname(fileURLToPath(import.meta.url)));
const APPJS = readFileSync(join(REPO, 'web', 'app.js'), 'utf8');
const HTML = readFileSync(join(REPO, 'web', 'index.html'), 'utf8');
let fail = 0;
const check = (name, cond) => { console.log((cond ? 'PASS' : 'FAIL') + ' — ' + name); if (!cond) fail++; };

// ─────────── минимальный DOM (как в других runtime-тестах) ───────────
class DNode { constructor(t) { this.nodeType = t; this.childNodes = []; this.parentNode = null; }
  get nextSibling() { const p = this.parentNode; if (!p) return null; const i = p.childNodes.indexOf(this); return i >= 0 ? (p.childNodes[i + 1] || null) : null; }
  _link(c, a) { if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = this; if (a && a.parentNode === this) this.childNodes.splice(this.childNodes.indexOf(a), 0, c); else this.childNodes.push(c); return c; }
  insertBefore(c, a) { return this._link(c, a); } appendChild(c) { return this._link(c, null); }
  removeChild(c) { const i = this.childNodes.indexOf(c); if (i >= 0) this.childNodes.splice(i, 1); c.parentNode = null; return c; }
  getRootNode() { return globalThis.document; } get ownerDocument() { return globalThis.document; } }
class DText extends DNode { constructor(t) { super(3); this.nodeValue = t == null ? '' : String(t); } get data() { return this.nodeValue; } set data(v) { this.nodeValue = v; } }
class DComment extends DNode { constructor(t) { super(8); this.nodeValue = t == null ? '' : String(t); } }
class DElement extends DNode {
  constructor(tag) { super(1); this._tag = tag; this.tagName = String(tag).toUpperCase(); this.namespaceURI = 'http://www.w3.org/1999/xhtml'; this.attributes = {}; this._listeners = {}; this.style = {}; this._cls = ''; }
  setAttribute(k, v) { this.attributes[k] = String(v); if (k === 'class') this._cls = String(v); }
  removeAttribute(k) { delete this.attributes[k]; if (k === 'class') this._cls = ''; }
  getAttribute(k) { return k in this.attributes ? this.attributes[k] : null; }
  hasAttribute(k) { return k in this.attributes; }
  get className() { return this._cls; } set className(v) { this._cls = v == null ? '' : String(v); this.attributes['class'] = this._cls; }
  addEventListener(t, fn) { (this._listeners[t] = this._listeners[t] || []).push(fn); }
  removeEventListener(t, fn) { const a = this._listeners[t]; if (a) { const i = a.indexOf(fn); if (i >= 0) a.splice(i, 1); } }
  get textContent() { return this.childNodes.map((c) => c.nodeType === 3 ? c.nodeValue : (c.nodeType === 1 ? c.textContent : '')).join(''); }
  set textContent(v) { this.childNodes.forEach((c) => (c.parentNode = null)); this.childNodes = []; if (v !== '' && v != null) this.appendChild(new DText(String(v))); }
  hasChildNodes() { return this.childNodes.length > 0; } get firstChild() { return this.childNodes[0] || null; }
  get innerHTML() { return ''; } set innerHTML(v) { if (v === '' || v == null) { this.childNodes.forEach((c) => (c.parentNode = null)); this.childNodes = []; } }
  querySelector() { return null; }
  _fire(type, ev) { (this._listeners[type] || []).slice().forEach((fn) => fn(ev)); }
  _findAll(pred, out = []) { if (this.nodeType === 1 && pred(this)) out.push(this); this.childNodes.forEach((c) => { if (c.nodeType === 1) c._findAll(pred, out); }); return out; } }
const doc = { createElement: (t) => new DElement(t), createElementNS: (ns, t) => new DElement(t), createTextNode: (t) => new DText(t), createComment: (t) => new DComment(t), querySelector: () => null, addEventListener: () => {}, removeEventListener: () => {}, activeElement: null };
doc.body = new DElement('body'); doc.head = new DElement('head'); doc.documentElement = new DElement('html');
if (!globalThis.document) globalThis.document = doc;
if (!globalThis.window) { try { globalThis.window = globalThis; } catch (e) {} }
for (const g of ['SVGElement', 'HTMLElement', 'Element', 'Node', 'ShadowRoot', 'Document', 'DocumentFragment']) { if (globalThis[g] === undefined) globalThis[g] = class {}; }

// ─────────── извлечение ДОСЛОВНЫХ исходников ───────────
const extractFn = (src, anchor) => {
  const i = src.indexOf(anchor); if (i < 0) throw new Error('anchor not found: ' + anchor);
  let d = 1, q = null, esc = false;
  for (let k = i + anchor.length; k < src.length; k++) { const ch = src[k];
    if (esc) { esc = false; continue; }
    if (q) { if (ch === '\\') esc = true; else if (ch === q) q = null; continue; }
    if (ch === "'" || ch === '"' || ch === '`') { q = ch; continue; }
    if (ch === '{') d++; else if (ch === '}') { d--; if (d === 0) { let e = k + 1; while (src[e] === ')') e++; if (src[e] === ';') e++; return src.slice(i, e); } } }
  throw new Error('unbalanced: ' + anchor);
};
const line = (re) => (APPJS.match(re) || [''])[0];
const SRC_HTMIN = line(/const AMS_HT_MIN = \d+;/);
const SRC_ISHT = line(/const amsIsHt = \([^\n]*;/);
const SRC_GROUPS = extractFn(APPJS, 'const amsGroups = (p) => {');
const SRC_FILROWS = extractFn(APPJS, 'const filamentRows = (p) => {');
const SRC_SAFEHEX = extractFn(APPJS, 'const safeHex = (v) => {');   // 2.736: filamentRows зовёт safeHex(sp.color_hex)
check('S1. извлечены amsGroups/filamentRows/amsIsHt; amsGroups строит label+ht, не позиционный «AMS»',
  SRC_HTMIN.includes('128') && SRC_ISHT.includes('AMS_HT_MIN') && /label = 'AMS HT'/.test(SRC_GROUPS) && /ht: ht/.test(SRC_GROUPS) && SRC_FILROWS.length > 300);
check('S2. index.html: компактная полоса и C1-дропдаун подписывают группу через grp.label (не «AMS » + grp.n)',
  /:title="grp\.label \+ '·'/.test(HTML) && />\{\{ grp\.label \}\}<\/div>/.test(HTML) && /\{\{ grp\.label \}\}·\{\{ t\.tray \+ 1 \}\}/.test(HTML));
check('S3. C1-дропдаун по-прежнему шлёт НАСТОЯЩИЙ глобальный index (printAmsSlot=t.index) — HT уйдёт как 512',
  /printAmsSlot=t\.index; cellAmsOpen=false; sendCmd\('start_print', printFileName\)/.test(HTML));

// ─────────── окружение: refs + извлечённые функции ───────────
const Vue = await import(pathToFileURL(join(REPO, 'web', 'vendor', 'vue.esm-browser.js')).href);
const { ref } = Vue;
const env = { wsData: ref({}), lang: ref('ru'), printerFilament: ref({}) };
const S = new Function('Vue', 'env', [
  'const { ref, computed } = Vue;',
  'const { wsData, lang, printerFilament } = env;',
  SRC_HTMIN, SRC_ISHT, SRC_GROUPS, SRC_SAFEHEX, SRC_FILROWS,
  'return { amsGroups, filamentRows, amsIsHt, AMS_HT_MIN };',
].join('\n'))(Vue, env);

// ─────────── fixture H1 (со скриншота): обычный AMS A1 (slot1 пуст, 2/3/4 PETG) + AMS HT (slot1 PETG) ───────────
const TRAYS_H1 = [
  { index: 0, unit: 0, tray: 0, type: 'Empty', color: '#3f3f46' },
  { index: 1, unit: 0, tray: 1, type: 'PETG', color: '#118ab2' },
  { index: 2, unit: 0, tray: 2, type: 'PETG', color: '#06d6a0' },
  { index: 3, unit: 0, tray: 3, type: 'PETG', color: '#ef476f' },
  { index: 512, unit: 128, tray: 0, type: 'PETG', color: '#ffd166' },
];
const sp = (m, c, cn, rem) => ({ material: m, color_hex: c, color_name: cn, vendor_name: 'Bambu', weight_remaining_g: rem, weight_total_g: 1000 });
const FIL_H1 = { has_ams: true, slots: [
  { index: 1, unit: 0, tray: 1, spool: sp('PETG', '#118ab2', 'Blue', 800) },
  { index: 2, unit: 0, tray: 2, spool: sp('PETG', '#06d6a0', 'Green', 700) },
  { index: 3, unit: 0, tray: 3, spool: sp('PETG', '#ef476f', 'Red', 600) },
  { index: 512, unit: 128, tray: 0, spool: sp('PETG', '#ffd166', 'Yellow', 500) },
] };

// ═══════════════ A: amsGroups — правильная модель групп ═══════════════
env.wsData.value = { H1: { ams_trays: TRAYS_H1, ams_now: -1 } };
const gH1 = S.amsGroups('H1');
check('A1. H1 → РОВНО 2 группы: обычная «AMS 1» (4 лотка) + «AMS HT» (1 лоток)',
  gH1.length === 2 && gH1[0].label === 'AMS 1' && gH1[0].ht === false && gH1[0].slots.length === 4
  && gH1[1].label === 'AMS HT' && gH1[1].ht === true && gH1[1].slots.length === 1);
check('A2. AMS HT сохраняет НАСТОЯЩИЙ глобальный index 512 (не 513, не позиция массива)',
  gH1[1].slots[0].index === 512 && gH1[1].unit === 128);
check('A3. HT НЕ подписан позиционным «AMS 2» и НЕ «AMS 129» по id',
  gH1[1].label === 'AMS HT' && gH1.every(g => g.label !== 'AMS 2' && g.label !== 'AMS 129'));
check('A4. занятость A1 верная: slot1 пуст (Empty), slots 2/3/4 — PETG',
  gH1[0].slots[0].type === 'Empty' && gH1[0].slots.slice(1).every(t => t.type === 'PETG'));
// мульти-AMS + HT: unit 0,1,128 → «AMS 1»,«AMS 2»,«AMS HT» (обычный второй остаётся A2, HT отдельно)
env.wsData.value = { M: { ams_trays: [
  { index: 0, unit: 0, tray: 0, type: 'PLA' }, { index: 4, unit: 1, tray: 0, type: 'ABS' }, { index: 5, unit: 1, tray: 1, type: 'ABS' }, { index: 512, unit: 128, tray: 0, type: 'PETG' },
] } };
const gM = S.amsGroups('M');
check('A5. multi-AMS (unit 0/1/128): «AMS 1»,«AMS 2»,«AMS HT»; обычный A2 (index 4/5) — отдельная группа, не смешан с HT',
  gM.length === 3 && gM[0].label === 'AMS 1' && gM[1].label === 'AMS 2' && gM[1].ht === false && gM[1].slots.length === 2 && gM[2].label === 'AMS HT' && gM[2].ht === true);
check('A6. unit 129 (второй HT-id) тоже → «AMS HT», а не «AMS 129»/«AMS 2»',
  (() => { env.wsData.value = { X: { ams_trays: [{ index: 516, unit: 129, tray: 0, type: 'PLA' }] } }; const g = S.amsGroups('X'); return g.length === 1 && g[0].ht === true && g[0].label === 'AMS HT'; })());
check('A7. HT-only: одна группа «AMS HT», без пустой обычной группы',
  (() => { env.wsData.value = { H: { ams_trays: [{ index: 512, unit: 128, tray: 0, type: 'PLA' }] } }; const g = S.amsGroups('H'); return g.length === 1 && g[0].label === 'AMS HT'; })());
check('A8. нет AMS → [] (пустая группа HT не создаётся)',
  (() => { env.wsData.value = { E: { ams_trays: [] } }; return S.amsGroups('E').length === 0; })());

// ═══════════════ F: filamentRows — правильные подписи, HT ≠ «AMS 2:1» ═══════════════
env.wsData.value = { H1: { ams_trays: TRAYS_H1, ams_now: -1 } };
env.printerFilament.value = { H1: FIL_H1 };
const rows = S.filamentRows('H1');
const labels = rows.map(r => r.label);
check('F1. H1 «Филамент»: 4 привязки → подписи AMS 1·2 / AMS 1·3 / AMS 1·4 / AMS HT·1',
  rows.length === 4 && labels[0] === 'AMS 1·2' && labels[1] === 'AMS 1·3' && labels[2] === 'AMS 1·4' && labels[3] === 'AMS HT·1');
check('F2. HT-строка НЕ «AMS 2·1», НЕ «AMS 129·1», НЕ «Внешняя катушка», НЕ «Слот 513»',
  labels[3] === 'AMS HT·1' && !labels.some(l => /AMS 2·1|AMS 129|Слот 513|Внешн/.test(l)));
check('F3. остаток/материал/цвет/производитель сохранены (HT-строка: PETG · Bambu · Yellow · 500 г)',
  rows[3].text.includes('PETG') && rows[3].text.includes('Bambu') && rows[3].text.includes('Yellow') && rows[3].hex === '#FFD166' && /500/.test(rows[3].rem));
// external как отдельная позиция (не AMS slot 0)
env.printerFilament.value = { P: { has_ams: false, slots: [{ index: 0, unit: null, tray: null, external: true, spool: sp('PLA', '#fff', 'White', 900) }] } };
env.wsData.value = { P: { ams_trays: [] } };
check('F4. external-катушка → «Внешняя катушка» (отдельная позиция, не «AMS …»)',
  (() => { const r = S.filamentRows('P'); return r.length === 1 && r[0].label === 'Внешняя катушка'; })());
// офлайн-HT: провайдер даёт unit=128, но принтера нет в живом ряду → всё равно «AMS HT·1», не «Слот 513»
env.wsData.value = {};
env.printerFilament.value = { OFF: { has_ams: true, slots: [{ index: 512, unit: 128, tray: 0, spool: sp('PETG', '#ffd166', 'Yellow', 500) }] } };
check('F5. офлайн-HT (нет в живом ряду) → «AMS HT·1», а не «Слот 513»',
  (() => { const r = S.filamentRows('OFF'); return r.length === 1 && r[0].label === 'AMS HT·1'; })());
// 16.10.2026 (R-137): у H2D две внешние катушки; склад помечает сторону (ext_side). Обе строки видны
// и подписаны по-разному; у одноцветного принтера без пометки подпись прежняя (F4).
env.wsData.value = { H2D: { ams_trays: [] } };
env.printerFilament.value = { H2D: { has_ams: false, slots: [
  { index: -2, unit: null, tray: null, external: true, ext_side: 'left', spool: sp('PETG', '#00ff00', 'Green', 300) },
  { index: -1, unit: null, tray: null, external: true, ext_side: 'right', spool: sp('PLA', '#ff0000', 'Red', 700) },
] } };
check('F4b. H2D: левая и правая внешние катушки — две строки «Внешняя левая» / «Внешняя правая»',
  (() => { const r = S.filamentRows('H2D'); return r.length === 2 && r[0].label === 'Внешняя левая' && r[1].label === 'Внешняя правая'
    && r[0].text.includes('PETG') && r[1].text.includes('PLA'); })());
check('F6. нет складского провайдера → filamentRows = [] (fail-open, без падения)',
  (() => { env.printerFilament.value = {}; return Array.isArray(S.filamentRows('H1')) && S.filamentRows('H1').length === 0; })());

// ═══════════════ D: МОНТИРУЕМ компактную AMS-полосу карточки (ДОСЛОВНАЯ разметка index.html) ═══════════════
const stripKey = '<div v-if="p.type===\'bambu\' && (wsData[p.id]?.ams_trays || []).length"';
const ss = HTML.indexOf(stripKey);
const sOpenEnd = HTML.indexOf('>', ss) + 1;
const sRe = /<div\b|<\/div>/g; sRe.lastIndex = sOpenEnd; let sm, sd = 1, sc = -1;
while ((sm = sRe.exec(HTML))) { sd += (sm[0] === '</div>') ? -1 : 1; if (sd === 0) { sc = sm.index; break; } }
const STRIP = HTML.slice(ss, sc + '</div>'.length);
check('D0. разметка компактной AMS-полосы извлечена (amsGroups + EXT-ячейка присутствуют)',
  STRIP.includes('amsGroups(p)') && STRIP.includes('grp.label') && STRIP.includes("tr('External spool')"));

env.wsData.value = { H1: { ams_trays: TRAYS_H1, ams_now: -1 } };
const comp = { setup() { return { p: { id: 'H1', type: 'bambu' }, wsData: env.wsData, amsGroups: S.amsGroups, tr: (s) => s, isLightColor: () => false, shortFilament: (t) => String(t).slice(0, 3), onPrinterCardClick: () => {} }; }, template: '<div class="troot">' + STRIP + '</div>' };
const app = Vue.createApp(comp);
app.config.compilerOptions.decodeEntities = (x) => x;
app.config.warnHandler = () => {};
const root = new DElement('div');
app.mount(root);
await new Promise(r => setTimeout(r, 0));

const titled = root._findAll((e) => e.getAttribute && e.getAttribute('title'));
const amsCells = titled.filter((e) => /^AMS /.test(e.getAttribute('title')));
const htCells = titled.filter((e) => /^AMS HT/.test(e.getAttribute('title')));
const extCells = titled.filter((e) => e.getAttribute('title') === 'External spool');
check('D1. в полосе РОВНО 5 AMS-ячеек (4 «AMS 1·N» + 1 «AMS HT·1») — НЕ сотни пустых, НЕ 513',
  amsCells.length === 5);
check('D2. РОВНО одна ячейка AMS HT, подписана «AMS HT·1»',
  htCells.length === 1 && htCells[0].getAttribute('title').startsWith('AMS HT·1'));
check('D3. ни одна ячейка не подписана позиционным «AMS 2·» (HT не выдаёт себя за второй обычный AMS)',
  !amsCells.some((e) => /^AMS 2·/.test(e.getAttribute('title'))));
check('D4. A1 даёт 4 ячейки «AMS 1·1..4»; external — отдельная EXT-ячейка (1), не считается AMS',
  amsCells.filter((e) => /^AMS 1·/.test(e.getAttribute('title'))).length === 4 && extCells.length === 1);

console.log('\n' + (fail ? ('FAIL: ' + fail + ' проверок провалено') : 'PASS: AMS HT в карточке — отдельная группа «AMS HT» (unit>=128), настоящий index 512 без 513 ячеек, «Филамент» подписан «AMS HT·1» (реальное исполнение amsGroups/filamentRows + монтаж полосы)'));
process.exit(fail ? 1 : 0);
