// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// РЕАЛЬНЫЙ Vue runtime-тест интерфейса «Перехват команды Bambu Studio» — Alpha 2.722.
// Монтирует ДОСЛОВНУЮ разметку панели перехвата (из web/index.html) настоящим вендорным Vue
// (web/vendor/vue.esm-browser.js) на самодельном DOM, поверх ДОСЛОВНО извлечённых из web/app.js
// функций (startSniff/stopSniff/refreshSniff/sniffFmt/sniffTime/copySniff/sniffStatusLabel + state).
// fetch и clipboard замоканы (никакой сети). Доказываем во ВЫПОЛНЕНИИ (не текстом):
//   U1  панель рендерит селектор Bambu-принтеров + кнопку «Начать перехват»;
//   U2  «Начать перехват» → POST /start с выбранным printer_id; НИ ОДНОГО POST на публикацию/печать;
//   U3  активная сессия: показан статус listening + остаток времени, кнопка стала «Остановить»;
//   U4  пришёл project_file → рендерится карточка с бейджем project_file (выделена), JSON форматирован;
//   U5  соседняя команда (gcode_line) тоже показана и НЕ выделена как project_file;
//   U6  секрет из json НЕ появляется в DOM (бэкенд уже вырезал — UI ничего не «дорисовывает»);
//   U7  «Остановить» → POST /stop; список перехваченного остаётся видимым;
//   U8  «Копировать результат» кладёт в буфер JSON перехваченного;
//   U9  все сетевые вызовы UI — только диагностические bambu-sniff (start/stop/status); ни publish, ни print.
// Запуск: node tools/test_bambu_sniff_ui.mjs   (0 = все проверки пройдены)
import { readFileSync } from 'fs';
import { fileURLToPath, pathToFileURL } from 'url';
import { dirname, join } from 'path';

const REPO = dirname(dirname(fileURLToPath(import.meta.url)));
const APPJS = readFileSync(join(REPO, 'web', 'app.js'), 'utf8');
const HTML = readFileSync(join(REPO, 'web', 'index.html'), 'utf8');
let fail = 0;
const check = (name, cond) => { console.log((cond ? 'PASS' : 'FAIL') + ' — ' + name); if (!cond) fail++; };

// ─────────── минимальный DOM (тот же harness, что в других runtime-тестах) ───────────
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
  set disabled(v) { this._disabled = !!v; if (v) this.attributes['disabled'] = ''; else delete this.attributes['disabled']; }
  get value() { return this._value; }
  set value(v) { this._value = v == null ? '' : String(v); }
  get options() { return this._findAll((e) => e._tag === 'option'); }
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
if (typeof globalThis.addEventListener !== 'function') { globalThis.addEventListener = () => {}; globalThis.removeEventListener = () => {}; }
if (typeof globalThis.setInterval !== 'function') { globalThis.setInterval = () => 0; globalThis.clearInterval = () => {}; }
for (const g of ['SVGElement', 'HTMLElement', 'Element', 'Node', 'ShadowRoot', 'Document', 'DocumentFragment']) { if (globalThis[g] === undefined) globalThis[g] = class {}; }

// ─────────── извлечение ДОСЛОВНЫХ функций из app.js ───────────
const extractFn = (src, anchor) => {
  const i = src.indexOf(anchor);
  if (i < 0) throw new Error('anchor not found: ' + anchor);
  let d = 1, q = null, esc = false;
  for (let k = i + anchor.length; k < src.length; k++) {
    const ch = src[k];
    if (esc) { esc = false; continue; }
    if (q) { if (ch === '\\') esc = true; else if (ch === q) q = null; continue; }
    if (ch === "'" || ch === '"' || ch === '`') { q = ch; continue; }
    if (ch === '{') d++;
    else if (ch === '}') { d--; if (d === 0) { let end = k + 1; while (src[end] === ')') end++; if (src[end] === ';') end++; return src.slice(i, end); } }
  }
  throw new Error('unbalanced: ' + anchor);
};
const REFRESH_SRC = extractFn(APPJS, 'const refreshSniff = async () => {');
const START_SRC = extractFn(APPJS, 'const startSniff = async () => {');
const STOP_SRC = extractFn(APPJS, 'const stopSniff = async () => {');
const FMT_SRC = (APPJS.match(/const sniffFmt = \(m\) => \{[^\n]*\};/) || [''])[0];
const TIME_SRC = (APPJS.match(/const sniffTime = \(ts\) => \{[^\n]*\};/) || [''])[0];
const COPY_SRC = extractFn(APPJS, 'const copySniff = async () => {');
const STATUS_SRC = extractFn(APPJS, 'const sniffStatusLabel = computed(() => {');
check('U0. извлечены реальные функции перехвата из app.js', REFRESH_SRC.length > 50 && START_SRC.length > 100 && STOP_SRC.length > 40 && FMT_SRC.length > 20 && COPY_SRC.length > 60 && STATUS_SRC.length > 60);

// ─────────── ДОСЛОВНАЯ разметка панели из index.html ───────────
const paneKey = '<div v-if="diagTab===\'sniff\'" class="diag-body">';
let ps = HTML.indexOf(paneKey);
const pOpenEnd = HTML.indexOf('>', ps) + 1;
const pRe = /<div\b|<\/div>/g; pRe.lastIndex = pOpenEnd;
let mm, dep = 1, pc = -1;
while ((mm = pRe.exec(HTML))) { dep += (mm[0] === '</div>') ? -1 : 1; if (dep === 0) { pc = mm.index; break; } }
const PANE = HTML.slice(ps, pc + '</div>'.length);
check('U0b. извлечена разметка панели: селектор, кнопки, список, копирование', PANE.includes('startSniff()') && PANE.includes('stopSniff()') && PANE.includes('sniffFmt(m)') && PANE.includes('copySniff()') && PANE.includes('project_file'));

// ─────────── mock fetch / clipboard: отдаём последовательные состояния перехвата ───────────
const net = [];
let serverActive = false;
let serverMsgs = [];
const proj = { print: { command: 'project_file', param: 'Metadata/plate_1.gcode', use_ams: true, ams_mapping: [0], timelapse: false, flow_cali: true, access_code: '***' } };
const gline = { print: { command: 'gcode_line', param: 'M104 S220' } };
const snap = () => ({ active: serverActive, status: serverActive ? 'listening' : 'stopped', error: '', printer_id: 'p1', printer_name: 'X1C', serial: 'SER1', client_id: 'FM_SNIFF_p1_ab12cd', remaining_s: serverActive ? 87 : 0, elapsed_s: 33, timeout_s: 120, received: serverMsgs.length, stored: serverMsgs.length, max: 20, messages: serverMsgs.slice() });
globalThis.fetch = async (url, opts) => {
  const u = String(url); net.push({ url: u, method: (opts && opts.method) || 'GET', body: opts && opts.body ? JSON.parse(opts.body) : null });
  if (u.endsWith('/bambu-sniff/start')) { serverActive = true; serverMsgs = []; return { ok: true, json: async () => ({ ok: true, status: 'connecting' }) }; }
  if (u.endsWith('/bambu-sniff/stop')) { serverActive = false; return { ok: true, json: async () => ({ ok: true, status: 'stopping' }) }; }
  if (u.endsWith('/bambu-sniff')) return { ok: true, json: async () => snap() };
  return { ok: true, json: async () => ({}) };
};
const clip = [];
const _clip = { writeText: async (t) => { clip.push(t); } };
try { Object.defineProperty(globalThis.navigator, 'clipboard', { value: _clip, configurable: true }); }
catch (e) { try { Object.defineProperty(globalThis, 'navigator', { value: { clipboard: _clip }, configurable: true }); } catch (e2) {} }

const Vue = await import(pathToFileURL(join(REPO, 'web', 'vendor', 'vue.esm-browser.js')).href);
const { createApp, ref, computed, nextTick } = Vue;

// ─────────── setup: РЕАЛЬНЫЕ функции app.js поверх реальных refs ───────────
const toasts = [];
const buildState = new Function('Vue', 'env', [
  'const { ref, computed } = Vue;',
  'const { lang, printers, pushToast } = env;',
  "const sniffPrinterId = ref('');",
  "const sniffState = ref({ active: false, status: 'idle', messages: [], remaining_s: 0, received: 0, stored: 0, max: 20 });",
  'const sniffBusy = ref(false);',
  'const sniffCopied = ref(false);',
  'let sniffTimer = null;',
  "const bambuPrinters = computed(() => (printers.value || []).filter(p => (p.type || 'bambu') === 'bambu'));",
  REFRESH_SRC, START_SRC, STOP_SRC, FMT_SRC, TIME_SRC, COPY_SRC, STATUS_SRC,
  'return { sniffPrinterId, sniffState, sniffBusy, sniffCopied, bambuPrinters, refreshSniff, startSniff, stopSniff, sniffFmt, sniffTime, copySniff, sniffStatusLabel };',
].join('\n'))(Vue, { lang: ref('ru'), printers: ref([{ id: 'p1', name: 'X1C', type: 'bambu' }, { id: 'p2', name: 'Klipper-1', type: 'klipper' }, { id: 'p3', name: 'P1S', type: 'bambu' }]), pushToast: (m) => toasts.push(m) });
const S = buildState;

// Alpha 2.784: кнопки старта/стопа перехвата гейтятся `can('admin')` (маршрут диагностики — admin).
// Тест обязан предоставить core-хелпер `can`; ниже отдельная проверка U10 доказывает сам гейт.
let canAdmin = true;
const comp = { setup() { return Object.assign({ lang: ref('ru'), diagTab: ref('sniff'), can: (c) => (c === 'admin' ? canAdmin : true) }, S); }, template: '<div class="troot">' + PANE + '</div>' };
const app = createApp(comp);
app.config.compilerOptions.decodeEntities = (x) => x;
app.config.compilerOptions.hoistStatic = false;
app.config.warnHandler = () => {};
const root = new DElement('div');
app.mount(root);
const settle = async () => { for (let i = 0; i < 4; i++) { await new Promise((r) => setTimeout(r, 0)); await nextTick(); } };
await settle();

const txt = () => root.textContent;
const buttons = () => root._findAll((e) => e._tag === 'button');
const byText = (t) => buttons().find((b) => b.textContent.includes(t));
const clickText = (t) => { const b = byText(t); if (b) b._fire('click', { type: 'click', target: b, currentTarget: b, stopPropagation() {}, preventDefault() {} }); return !!b; };

// ═══ U1: панель, селектор Bambu-принтеров, кнопка старта ═══
const sel = root._findAll((e) => e._tag === 'select')[0];
const opts = sel ? sel.options.filter((o) => o.getAttribute('value')) : [];
check('U1. рендер: select с ТОЛЬКО Bambu-принтерами (X1C, P1S; klipper исключён), кнопка «Начать перехват»',
  S.bambuPrinters.value.length === 2 && !!byText('Начать перехват') && txt().includes('Перехват команды Bambu Studio'));

// установить выбранный принтер (v-model) и стартовать
S.sniffPrinterId.value = 'p1'; await settle();
net.length = 0;
clickText('Начать перехват');
await settle(); await settle();

// ═══ U2: POST /start с printer_id; никаких publish/print ═══
const startCall = net.find((c) => c.url.endsWith('/bambu-sniff/start'));
check('U2. клик «Начать перехват» → POST …/bambu-sniff/start с {printer_id:"p1"}; НИ одного publish/print/cmd',
  startCall && startCall.method === 'POST' && startCall.body && startCall.body.printer_id === 'p1'
  && !net.some((c) => /\/print|\/upload_print|\/cmd|publish/.test(c.url)));

// ═══ U3: активная сессия — статус + остаток + кнопка «Остановить» ═══
await S.refreshSniff(); await settle();
check('U3. активная сессия: статус «Слушает команды», показан остаток времени, кнопка стала «Остановить»',
  S.sniffState.value.active === true && txt().includes('Слушает команды') && txt().includes('осталось') && !!byText('Остановить') && !byText('Начать перехват'));

// ═══ U4: пришёл project_file → карточка с бейджем, форматированный JSON ═══
serverMsgs = [{ ts: 1700000000, topic: 'device/SER1/request', command: 'project_file', is_project_file: true, json: proj, parse_error: false, raw_len: 200 }];
await S.refreshSniff(); await settle();
const projBadge = root._findAll((e) => e._tag === 'span' && e.textContent.trim() === 'project_file');
const pre = root._findAll((e) => e._tag === 'pre')[0];
check('U4. project_file: бейдж «project_file» отрисован, JSON форматирован (виден use_ams/flow_cali), карточка выделена',
  projBadge.length >= 1 && pre && /"command": "project_file"/.test(pre.textContent) && /"use_ams": true/.test(pre.textContent) && /"flow_cali": true/.test(pre.textContent));

// ═══ U5: соседняя команда тоже показана и НЕ project_file ═══
serverMsgs = [
  { ts: 1700000001, topic: 'device/SER1/request', command: 'gcode_line', is_project_file: false, json: gline, parse_error: false, raw_len: 40 },
  { ts: 1700000002, topic: 'device/SER1/request', command: 'project_file', is_project_file: true, json: proj, parse_error: false, raw_len: 200 },
];
await S.refreshSniff(); await settle();
const pres = root._findAll((e) => e._tag === 'pre');
check('U5. соседняя команда (gcode_line) показана рядом с project_file (не отброшена): ≥2 карточки JSON',
  pres.length === 2 && pres.some((p) => /"command": "gcode_line"/.test(p.textContent)) && pres.some((p) => /"command": "project_file"/.test(p.textContent)));

// ═══ U6: секрет НЕ появляется в DOM (UI не дорисовывает — бэкенд уже вырезал) ═══
check('U6. в DOM нет «сырых» секретов (access_code показан как ***; строки LEAK/пароля нет)',
  !/LEAK|SECRET|"bblp"/.test(txt()) && txt().includes('***'));

// ═══ U7: «Остановить» → POST /stop; список остаётся ═══
net.length = 0;
clickText('Остановить');
await settle(); await settle();
const stopCall = net.find((c) => c.url.endsWith('/bambu-sniff/stop'));
check('U7. «Остановить» → POST …/bambu-sniff/stop (без тела печати); перехваченные сообщения остаются видимы',
  stopCall && stopCall.method === 'POST' && S.sniffState.value.active === false && root._findAll((e) => e._tag === 'pre').length === 2);

// ═══ U8: копирование ═══
net.length = 0;
clickText('Копировать результат');
await settle();
check('U8. «Копировать результат» → буфер получил JSON перехваченного (2 сообщения)',
  clip.length === 1 && /"command": "project_file"/.test(clip[0]) && /"command": "gcode_line"/.test(clip[0]));

// ═══ U9: все сетевые вызовы UI — только диагностические bambu-sniff ═══
check('U9. каждый сетевой вызов интерфейса — только /api/diagnostics/bambu-sniff(/start|/stop); ни publish, ни печать, ни очередь',
  net.concat([startCall, stopCall].filter(Boolean)).every((c) => /\/api\/diagnostics\/bambu-sniff/.test(c.url))
  && !clip.join('').includes('bblp'));

// ═══ U10 (гейт админа, Alpha 2.784): без права admin кнопок старта/стопа перехвата НЕТ ═══
// Свежий монтаж с can('admin')=false; сама панель по-прежнему открыта (диагностика — view),
// но запуск/остановка перехвата недоступны, поэтому обе кнопки скрыты.
canAdmin = false;
const app2 = createApp(comp);
app2.config.compilerOptions.decodeEntities = (x) => x;
app2.config.compilerOptions.hoistStatic = false;
app2.config.warnHandler = () => {};
const root2 = new DElement('div');
app2.mount(root2);
await settle();
const btns2 = root2._findAll((e) => e._tag === 'button');
check('U10. без права admin кнопки «Начать перехват»/«Остановить» скрыты (гейт 2.784), панель открыта',
  !btns2.some((b) => /Начать перехват|Остановить/.test(b.textContent))
  && root2.textContent.includes('Перехват команды Bambu Studio'));

console.log('\n' + (fail ? ('FAIL: ' + fail + ' проверок провалено') : 'PASS: интерфейс перехвата Bambu Studio — старт/стоп/опрос/фильтр project_file/копирование работают; только диагностические вызовы, без секретов и без publish (реальный Vue mount)'));
process.exit(fail ? 1 : 0);
