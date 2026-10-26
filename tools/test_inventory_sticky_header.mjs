// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// РЕАЛЬНЫЙ runtime-регрессионный тест sticky-шапки «Склад → В работе» — inventory 1.7.9.
// Баг: при вертикальной прокрутке над заголовками «Принтер/Катушка/AMS/Остаток/Прогноз» оставался
// просвет ~21px, сквозь который были видны прокрученные строки. ПРИЧИНА (доказана измерением в
// Chromium): scroll-контейнер .fm-inv-body (правило ядра app.css) имеет padding:20px — sticky top:0
// закрепляется на границе CONTENT-box (на 20px ниже видимого верха прокрутки), а строки клипаются по
// PADDING-box и просвечивают в полосе (+1px border-top). Фикс 1.7.9: CARD_CSS переопределяет
// .fm-inv-body{padding-top:0}, те же 20px переезжают на обёртки вкладок .fm-inv-tabpane.
//
// Тест трёхуровневый (НЕ текстовый grep):
//   M*  монтаж НАСТОЯЩЕГО InventoryPanel (весь компонент, реальный вендорный Vue, teleport, load()
//       на fetch-стабах, 30 принтеров) → структура DOM: 5 панелей .fm-inv-tabpane, шапка — ПЕРВЫЙ
//       элемент .fm-inv-ptable, 30 строк (высоты гарантируют прокрутку), scrollTop>0 выставляется;
//   C*  каскадная резолюция ФАКТИЧЕСКИ ИНЖЕКТИРОВАННОГО стиля (#fm-inv-style-2665 из runtime-DOM)
//       поверх правила ядра .fm-inv-body из web/app.css (порядок как в браузере): эффективный
//       padding-top скроллера = 0, панель = 20px, шапка sticky/top:0/z-index>строк, фон через
//       --fm-surface-raised → НЕПРОЗРАЧНЫЙ hex в тёмной И светлой темах;
//   L*  НАСТОЯЩИЙ layout-движок (установленный Edge/Chrome, headless, БЕЗ новых зависимостей):
//       старый CSS (без двух фикс-правил) ОБЯЗАН воспроизвести просвет >10px со строками в нём,
//       новый CSS — просвет ≤1.5px (только непрозрачный border), выше шапки строк НЕТ, sticky живой
//       (без прокрутки шапка в естественном положении ниже тулбара).
// Alpha 2.835: L* переведены со сломанного `--dump-dom` на общий CDP-мост (_edge_cdp_lib.mjs).
// Стенды «старый CSS» / «новый CSS», пороги и смысл L1-L4 сохранены дословно; отсутствие браузера
// или результата теперь КРАСНОЕ (раньше один пропуск скрывал сразу четыре проверки геометрии).
// Запуск: node tools/test_inventory_sticky_header.mjs   (0 = пройдено)
import { readFileSync, writeFileSync, mkdirSync, rmSync } from 'fs';
import { tmpdir } from 'os';
import { fileURLToPath, pathToFileURL } from 'url';
import { dirname, join } from 'path';
import { findEngine, measure, browserProblems } from './_edge_cdp_lib.mjs';

const REPO = dirname(dirname(fileURLToPath(import.meta.url)));
const PANEL_PATH = join(REPO, 'modules', 'inventory', 'web', 'InventoryPanel.js');
const PANEL_SRC = readFileSync(PANEL_PATH, 'utf8');
const APP_CSS = readFileSync(join(REPO, 'web', 'app.css'), 'utf8');
let fail = 0;
const check = (name, cond) => { console.log((cond ? 'PASS' : 'FAIL') + ' — ' + name); if (!cond) fail++; };

// ─────────── минимальный DOM (API, который дёргает Vue runtime-dom; + head/getElementById/scrollTop) ───────────
class DNode {
  constructor(nodeType) { this.nodeType = nodeType; this.childNodes = []; this.parentNode = null; }
  get nextSibling() { const p = this.parentNode; if (!p) return null; const i = p.childNodes.indexOf(this); return i >= 0 ? (p.childNodes[i + 1] || null) : null; }
  _link(child, anchor) { if (child.parentNode) child.parentNode.removeChild(child); child.parentNode = this; if (anchor && anchor.parentNode === this) { this.childNodes.splice(this.childNodes.indexOf(anchor), 0, child); } else this.childNodes.push(child); return child; }
  insertBefore(child, anchor) { return this._link(child, anchor); }
  appendChild(child) { return this._link(child, null); }
  removeChild(child) { const i = this.childNodes.indexOf(child); if (i >= 0) this.childNodes.splice(i, 1); child.parentNode = null; return child; }
  getRootNode() { return globalThis.document; }
  get ownerDocument() { return globalThis.document; }
}
class DText extends DNode { constructor(t) { super(3); this.nodeValue = t == null ? '' : String(t); } get data() { return this.nodeValue; } set data(v) { this.nodeValue = v; } }
class DComment extends DNode { constructor(t) { super(8); this.nodeValue = t == null ? '' : String(t); } }
class DElement extends DNode {
  constructor(tag) { super(1); this._tag = tag; this.tagName = String(tag).toUpperCase(); this.namespaceURI = 'http://www.w3.org/1999/xhtml'; this.attributes = {}; this._listeners = {}; this.style = {}; this._cls = ''; this._disabled = false; this._html = ''; this.scrollTop = 0; }
  setAttribute(k, v) { this.attributes[k] = String(v); if (k === 'class') this._cls = String(v); }
  removeAttribute(k) { delete this.attributes[k]; if (k === 'class') this._cls = ''; }
  getAttribute(k) { return k in this.attributes ? this.attributes[k] : null; }
  hasAttribute(k) { return k in this.attributes; }
  get className() { return this._cls; }
  set className(v) { this._cls = v == null ? '' : String(v); this.attributes['class'] = this._cls; }
  get id() { return this.attributes['id'] || ''; }
  set id(v) { this.attributes['id'] = String(v); }
  get disabled() { return this._disabled; }
  set disabled(v) { this._disabled = !!v; if (v) this.attributes['disabled'] = ''; else delete this.attributes['disabled']; }
  get options() { return this._findAll((e) => e._tag === 'option'); }
  get classList() {   // Transition/withDirectives дёргают classList — маппим на _cls
    const self = this, set = () => new Set(self._cls.split(/\s+/).filter(Boolean)), put = (s) => { self.className = [...s].join(' '); };
    return { add: (...cs) => { const s = set(); cs.forEach((c) => s.add(c)); put(s); }, remove: (...cs) => { const s = set(); cs.forEach((c) => s.delete(c)); put(s); }, contains: (c) => set().has(c), toggle: (c) => { const s = set(); s.has(c) ? s.delete(c) : s.add(c); put(s); } };
  }
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
const documentShim = {
  createElement: (t) => new DElement(t), createElementNS: (ns, t) => new DElement(t),
  createTextNode: (t) => new DText(t), createComment: (t) => new DComment(t),
  addEventListener: () => {}, removeEventListener: () => {}, activeElement: null,
};
documentShim.body = new DElement('body'); documentShim.head = new DElement('head'); documentShim.documentElement = new DElement('html');
documentShim.querySelector = (sel) => (sel === 'body' ? documentShim.body : null);
documentShim.getElementById = (id) => {
  const scan = (root) => root._findAll((e) => e.attributes && e.attributes.id === id)[0] || null;
  return scan(documentShim.head) || scan(documentShim.body);
};
if (!globalThis.document) globalThis.document = documentShim;
if (!globalThis.window) { try { globalThis.window = globalThis; } catch (e) {} }
if (!globalThis.localStorage) globalThis.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
for (const g of ['SVGElement', 'HTMLElement', 'Element', 'Node', 'ShadowRoot', 'Document', 'DocumentFragment']) { if (globalThis[g] === undefined) globalThis[g] = class {}; }
// окружение window для компонента (панель читает размеры и вешает слушатели) и Vue Transition
if (typeof globalThis.addEventListener !== 'function') { globalThis.addEventListener = () => {}; globalThis.removeEventListener = () => {}; globalThis.dispatchEvent = () => true; }
if (globalThis.innerWidth == null) { globalThis.innerWidth = 1600; globalThis.innerHeight = 900; }
if (typeof globalThis.confirm !== 'function') globalThis.confirm = () => true;
if (typeof globalThis.requestAnimationFrame !== 'function') { globalThis.requestAnimationFrame = (fn) => setTimeout(fn, 0); globalThis.cancelAnimationFrame = (t) => clearTimeout(t); }
if (typeof globalThis.getComputedStyle !== 'function') globalThis.getComputedStyle = () => new Proxy({}, { get: (t, k) => (k === 'getPropertyValue' ? () => '' : '') });

// ─────────── fetch-стаб фермы: 30 принтеров, каждый с привязанной катушкой (строк хватает для прокрутки) ───────────
const N = 30;
const P = Array.from({ length: N }, (_, i) => ({
  printer_id: 'p' + i, printer_name: 'PRN-' + String(i).padStart(2, '0'), has_ams: true,
  slots: [
    { index: 0, unit: 0, spool: { id: 'sp' + i, material: 'PLA', color_name: 'Red', color_hex: '#c33', vendor_name: 'Vendor', weight_remaining_g: 500 + i, weight_g: 1000 } },
    { index: 1, unit: 0 }, { index: 2, unit: 0 }, { index: 3, unit: 0 },
  ],
}));
globalThis.fetch = async (url) => {
  const u = String(url);
  const json = (o) => ({ ok: true, status: 200, json: async () => o, text: async () => '<svg viewBox="0 0 10 10"></svg>' });
  if (u.includes('/api/mod/inventory/filament')) return json({ vendors: [], filaments: [], spools: P.map((p) => ({ ...p.slots[0].spool, status: 'loaded', printer_id: p.printer_id, ams_slot: 0 })) });
  if (u.includes('/api/mod/inventory/ams')) return json({ printers: P });
  if (u.includes('/api/mod/inventory/forecast')) return json({ spools: [{ id: 'sp0', days_left: 3 }] });
  if (u.includes('/api/printers')) return json(P.map((p) => ({ id: p.printer_id, model: 'Bambu Lab X1 Carbon' })));
  // прочие секции «падают» (fail-open путь компонента): ref-ы сохраняют свои штатные исходные формы
  return { ok: false, status: 404, json: async () => ({}), text: async () => '' };
};

// ─────────── M: монтаж НАСТОЯЩЕГО InventoryPanel (import с 'vue' → вендорный файл) ───────────
const VUE_URL = pathToFileURL(join(REPO, 'web', 'vendor', 'vue.esm-browser.js')).href;
const tmpBase = join(tmpdir(), 'fm-inv-sticky-' + process.pid);
mkdirSync(tmpBase, { recursive: true });
const tmpPanel = join(tmpBase, 'InventoryPanel.under-test.mjs');
// 1.7.36: окно склада подключает соседние файлы модуля (./InventoryI18n.js) — во временной папке их
// нет, поэтому относительные ссылки ведут в настоящую папку модуля.
const PANEL_DIR_URL = pathToFileURL(dirname(PANEL_PATH)).href + '/';
writeFileSync(tmpPanel, PANEL_SRC.replace("from 'vue'", `from '${VUE_URL.replace(/'/g, "%27")}'`)
  .split("from './").join(`from '${PANEL_DIR_URL.replace(/'/g, "%27")}`), 'utf8');
const Vue = await import(VUE_URL);
const { createApp, nextTick } = Vue;
const Panel = (await import(pathToFileURL(tmpPanel).href)).default;

const app = createApp(Panel, { open: true, lang: 'ru', startTab: 'filament' });
app.config.compilerOptions.decodeEntities = (x) => x;
app.config.compilerOptions.hoistStatic = false;
app.component('svg-icon', { props: { name: String }, template: '<i class="svgicon"></i>' });
app.config.warnHandler = () => {};   // inject() ядра недоступен вне приложения — ожидаемо
const mountRoot = new DElement('div');
const vm = app.mount(mountRoot);
const settle = async () => { for (let i = 0; i < 4; i++) { await new Promise((r) => setTimeout(r, 0)); await nextTick(); } };
await settle();

const S = vm.$.setupState;
S.wmode = 'work';           // режим «В работе» (openInit по умолчанию открывает «На складе»)
await settle();

const body = documentShim.body;   // teleport to body
const one = (pred) => body._findAll(pred)[0] || null;
const cls = (e) => String((e && e.className) || '');
const scroller = one((e) => cls(e).split(/\s+/).includes('fm-inv-body'));
const panes = body._findAll((e) => cls(e).split(/\s+/).includes('fm-inv-tabpane'));
const ptable = one((e) => cls(e).split(/\s+/).includes('fm-inv-ptable'));

check('M1. настоящий InventoryPanel смонтирован (teleport в body, есть .fm-inv-body и таблица .fm-inv-ptable)',
  !!scroller && !!ptable && !!one((e) => cls(e).includes('fm-inv-root')));
check('M2. ВСЕ 5 обёрток вкладок несут класс .fm-inv-tabpane (переехавший верхний отступ) и лежат прямо в скроллере',
  panes.length === 5 && panes.every((p) => p.parentNode === scroller) && scroller.childNodes.filter((c) => c.nodeType === 1).length === 5);
const workPane = panes.find((p) => p._findAll((e) => cls(e).includes('fm-inv-ptable')).length);
const stockPane = panes.find((p) => p._findAll((e) => cls(e).includes('fm-inv-wlist') || cls(e).includes('fm-inv-fbar')).length);
check('M3. панель «В работе» видима (v-show), панель «На складе» скрыта — переключение режимов живо',
  workPane && workPane.style.display !== 'none' && stockPane && stockPane.style.display === 'none');
const kids = ptable ? ptable.childNodes.filter((c) => c.nodeType === 1) : [];
const hdr = kids[0];
// 1.7.10: строки живут внутри секций .fm-inv-psec — ищем по всему поддереву таблицы
const rows = ptable ? ptable._findAll((e) => cls(e).split(/\s+/).includes('fm-inv-prow') && !cls(e).split(/\s+/).includes('fm-inv-prow-h')) : [];
check('M4. шапка .fm-inv-prow-h — ПЕРВЫЙ элемент таблицы (выше неё внутри области прокрутки только тулбар)',
  hdr && cls(hdr).split(/\s+/).includes('fm-inv-prow-h') && cls(hdr).split(/\s+/).includes('fm-inv-prow'));
check('M5. строк достаточно для вертикальной прокрутки: ' + rows.length + ' строк × min-height 76px = ' + (rows.length * 76) + 'px > max-height панели 900px',
  rows.length === N && rows.length * 76 > 900);
// 1.7.26: колонка называется «Слоты подачи» — панель обслуживает и AMS у Bambu, и CFS у Creality K2.
check('M6. заголовки шапки — Принтер/Катушка/Слоты подачи/Остаток/Прогноз',
  hdr && /Принтер/.test(hdr.textContent) && /Катушка/.test(hdr.textContent) && /Слоты подачи/.test(hdr.textContent) && /Остаток/.test(hdr.textContent) && /Прогноз/.test(hdr.textContent));
scroller.scrollTop = 480;
check('M7. scrollTop скроллера выставлен > 0 (сценарий прокрутки)', scroller.scrollTop === 480);

// ─────────── C: каскад по ФАКТИЧЕСКИ ИНЖЕКТИРОВАННОМУ стилю модуля поверх правила ядра ───────────
const styleEl = documentShim.getElementById('fm-inv-style-2665');
const injectedCss = styleEl ? styleEl.textContent : '';
check('C1. модуль в runtime инжектировал свой стиль #fm-inv-style-2665 в <head>', injectedCss.length > 1000);

const parseDecls = (block) => { const d = {}; for (const part of block.split(';')) { const i = part.indexOf(':'); if (i > 0) d[part.slice(0, i).trim().toLowerCase()] = part.slice(i + 1).trim(); } return d; };
const expandPadding = (d) => {
  const out = {};
  if (d['padding'] != null) { const v = d['padding'].split(/\s+/); const [t, r, b, l] = [v[0], v[1] ?? v[0], v[2] ?? v[0], v[3] ?? v[1] ?? v[0]]; out['padding-top'] = t; out['padding-right'] = r; out['padding-bottom'] = b; out['padding-left'] = l; }
  for (const k of ['padding-top', 'padding-right', 'padding-bottom', 'padding-left']) if (d[k] != null) out[k] = d[k];
  return out;
};
// эффективные декларации для селектора: правила в порядке [ядро app.css, затем инжектированный CARD_CSS]
const effective = (selector) => {
  const rules = [];
  const collect = (css) => { for (const m of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) { const sels = m[1].split(',').map((x) => x.trim()); if (sels.includes(selector)) rules.push(m[2]); } };
  collect(APP_CSS.replace(/@media[^{]*\{/g, ''));   // media-обёртки ядра не содержат fm-inv-body — плоско
  collect(injectedCss.replace(/@media[^{]*\{/g, ''));
  const eff = {};
  for (const r of rules) { const d = parseDecls(r); Object.assign(eff, d, expandPadding(d)); }
  return eff;
};
const effBody = effective('.fm-inv-body');
check('C2. ПРИЧИНА зафиксирована: ядро даёт .fm-inv-body padding:20px, CARD_CSS (позже в каскаде) обнуляет ТОЛЬКО верх: эффективный padding-top=0, бока/низ 20px, overflow-y:auto жив',
  /(^|\s)20px/.test((/\.fm-inv-body\{[^}]*\}/.exec(APP_CSS) || [''])[0].match(/padding:([^;]+)/)?.[1] || '') === true
  && effBody['padding-top'] === '0' && effBody['padding-right'] === '20px' && effBody['padding-bottom'] === '20px' && effBody['padding-left'] === '20px'
  && effBody['overflow-y'] === 'auto');
const effPane = effective('.fm-inv-tabpane');
check('C3. .fm-inv-tabpane несёт перенесённый верхний отступ 20px (прокручивается вместе с содержимым)', effPane['padding-top'] === '20px');
const effHdr = effective('.fm-inv-prow-h');
const hdrZ = parseInt(effHdr['z-index'] || '0', 10);
check('C4. шапка: position:sticky, top:0 (закрепление точно от верхней границы прокрутки), z-index=' + hdrZ + ' > слоя строк',
  effHdr['position'] === 'sticky' && effHdr['top'] === '0' && hdrZ >= 1);
const rowScopeZ = [...injectedCss.matchAll(/\.fm-inv-p(?!row-h)[a-z0-9-]*[^{}]*\{[^}]*z-index:\s*(-?\d+)/g)].map((m) => parseInt(m[1], 10));
check('C5. ни один элемент строк (.fm-inv-p*) не поднимается по z-index до шапки (макс: ' + (rowScopeZ.length ? Math.max(...rowScopeZ) : '—') + ')',
  rowScopeZ.every((z) => z < hdrZ));
const dark = /--fm-surface-raised:\s*(#[0-9a-fA-F]{6})\b/.exec(APP_CSS);
const lightBlock = APP_CSS.slice(APP_CSS.indexOf('--fm-surface-raised', dark ? dark.index + 10 : 0));
const light = /--fm-surface-raised:\s*(#[0-9a-fA-F]{6})\b/.exec(lightBlock);
check('C6. фон шапки — var(--fm-surface-raised), НЕПРОЗРАЧНЫЙ в обеих темах (тёмная ' + (dark && dark[1]) + ', светлая ' + (light && light[1]) + ')',
  /var\(--fm-surface-raised\)/.test(effHdr['background'] || '') && !!dark && !!light && dark[1].length === 7 && light[1].length === 7);
check('C7. фикс не маскирует дефект отступом шапки: top остаётся 0, ВЕРТИКАЛЬНОГО margin нет (горизонтальная компенсация рамки секций margin:0 1px — допустима, 1.7.10)',
  effHdr['top'] === '0' && !('margin-top' in effHdr) && (!effHdr['margin'] || effHdr['margin'] === '0 1px'));

// ─────────── L: НАСТОЯЩИЙ layout-движок (установленный браузер, headless, без новых зависимостей) ───────────
const ENGINE = findEngine();

const coreRules = ['.fm-inv-panel', '.fm-inv-body', '.fm-inv-toolbar']
  .map((s) => (new RegExp(s.replace(/[.]/g, '\\.') + '\\{[^}]*\\}')).exec(APP_CSS)[0]).join('\n');
const mkHarness = (cardCss, paneClass) => {
  const rowsHtml = Array.from({ length: 30 }, (_, i) =>
    `<div class="fm-inv-prow"><div class="fm-inv-pcol"><span class="fm-inv-pimg" style="background:hsl(${i * 37 % 360},80%,55%)"></span><span class="fm-inv-pcol-t"><span class="fm-inv-pname2">Printer ${i}</span></span></div><div>spool</div><div>ams</div><div>rem</div><div>fc</div><div>·</div></div>`).join('\n');
  return `<!doctype html><html><head><meta charset="utf-8"><style>
:root{--fm-surface-raised:#202023;--fm-border-strong:#3f3f46;--fm-border-soft:#2a2a2e;--fm-text-primary:#ededef;--fm-text-subtle:#9b9ba3;--fm-accent-rgb:77,166,255;--fm-black-rgb:0,0,0;--fm-border:#333}
body{margin:0;background:#111;font:13px system-ui}
${coreRules}
</style><style>
${cardCss}
.fm-inv-panel{margin:0 auto;height:480px}
</style></head><body>
<div class="fm-inv-panel"><div class="fm-inv-body" id="sc"><div${paneClass ? ' class="fm-inv-tabpane"' : ''}>
<div class="fm-inv-toolbar"><button>Добавить катушку</button></div>
<div class="fm-inv-ptable"><div class="fm-inv-prow fm-inv-prow-h" id="h"><span>Принтер</span><span>Катушка</span><span>AMS слоты</span><span>Остаток</span><span>Прогноз</span><span></span></div>
${rowsHtml}</div></div></div></div>
<pre id="__result"></pre>
<script>
const sc = document.getElementById('sc'), h = document.getElementById('h');
sc.scrollTop = 0;
const nat = h.getBoundingClientRect().top - sc.getBoundingClientRect().top;   // естественное положение без прокрутки
sc.scrollTop = 400;
const sr = sc.getBoundingClientRect(), hr = h.getBoundingClientRect();
const gap = hr.top - sr.top;
const probe = (y) => { const el = document.elementFromPoint(sr.left + sr.width * 0.3, y); const c = []; let e = el; while (e && c.length < 3) { c.push(String(e.className || e.tagName)); e = e.parentElement; } return c.join('<'); };
document.getElementById('__result').textContent = '@@RES@@' + JSON.stringify({
  nat: +nat.toFixed(1), scrollTop: sc.scrollTop, gap: +gap.toFixed(2),
  border: parseFloat(getComputedStyle(sc).borderTopWidth),
  padTop: getComputedStyle(sc).paddingTop,
  pos: getComputedStyle(h).position, z: getComputedStyle(h).zIndex, bg: getComputedStyle(h).backgroundColor,
  above: gap > 2 ? probe(sr.top + gap / 2) : probe(hr.top - 2),
  inside: probe(hr.top + 3),
}) + '@@END@@';
</script></body></html>`;
};
// 800x600 — прежний размер окна этого стенда (раньше --window-size не передавался и движок брал
// свой умолчательный размер): условия измерения не изменились, изменился только транспорт.
const runHeadless = async (htmlPath) => {
  const out = await measure({ url: pathToFileURL(htmlPath).href, width: 800, height: 600, engine: ENGINE });
  return out;
};

check('L0. движок рендера для layout-проверки найден (без него L1-L4 невозможны)', !!ENGINE);
if (ENGINE) {
  // старый CSS = инжектированный МИНУС два фикс-правила; обёртка без .fm-inv-tabpane (репро 1.7.8)
  const oldCss = injectedCss.replace('.fm-inv-body{padding-top:0}', '').replace('.fm-inv-tabpane{padding-top:20px}', '');
  const pOld = join(tmpBase, 'old.html'), pNew = join(tmpBase, 'new.html');
  writeFileSync(pOld, mkHarness(oldCss, false), 'utf8');
  writeFileSync(pNew, mkHarness(injectedCss, true), 'utf8');
  let oOld = null, oNew = null, why = '';
  try { oOld = await runHeadless(pOld); oNew = await runHeadless(pNew); }
  catch (e) { why = String((e && e.message) || e); }
  check('L0b. оба стенда (без фикса / с фиксом) выполнены в реальном браузере', !!oOld && !!oNew);
  if (why) console.log('   причина: ' + why);
  if (oOld && oNew) {
    const probs = browserProblems(oOld).concat(browserProblems(oNew));
    check('L0c. страницы стендов без ошибок JS/консоли/Vue', probs.length === 0);
    if (probs.length) console.log('   ' + probs.join('\n   '));
    const rOld = oOld.res, rNew = oNew.res;
    check('L1. РЕПРО без фикса: просвет над шапкой ' + rOld.gap + 'px (>10) и в нём видны СТРОКИ (' + String(rOld.above).slice(0, 48) + '…) — тест ловит регрессию',
      rOld.gap > 10 && /fm-inv-p(row|col|img|name)/.test(rOld.above || ''));
    check('L2. С фиксом: просвет ' + rNew.gap + 'px ≤ 1.5px (только непрозрачный border ' + rNew.border + 'px), padding-top скроллера = ' + rNew.padTop + ', scrollTop=' + rNew.scrollTop + '>0',
      rNew.gap <= 1.5 && rNew.padTop === '0px' && rNew.scrollTop > 0);
    check('L3. С фиксом: выше шапки НЕТ элементов строк (виден только контейнер: ' + String(rNew.above).slice(0, 40) + '…), внутри шапки — сама шапка (z-слой выше строк), фон вычислен непрозрачным: ' + rNew.bg,
      !/fm-inv-p(row(?!-h)|col|img|name|ext|slot)/.test(rNew.above || '') && /fm-inv-prow-h/.test(rNew.inside || '')
      && rNew.pos === 'sticky' && parseInt(rNew.z, 10) >= 1 && /^rgb\(/.test(rNew.bg));
    check('L4. sticky НЕ отключён и не заменён на fixed: без прокрутки шапка в естественном положении ' + rOld.nat + '/' + rNew.nat + 'px ниже верха (после тулбара)',
      rNew.nat > 20 && rOld.nat > 20);
  }
}
try { if (tmpBase.startsWith(tmpdir())) rmSync(tmpBase, { recursive: true, force: true }); } catch (e) {}

console.log('\n' + (fail ? ('FAIL: ' + fail + ' проверок провалено') : 'PASS: sticky-шапка «В работе» — без просвета, непрозрачна, выше строк; sticky/колонки/высота сохранены (реальный Edge через CDP, 0 пропусков)'));
process.exit(fail ? 1 : 0);
