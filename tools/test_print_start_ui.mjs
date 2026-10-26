// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// РЕАЛЬНЫЙ Vue runtime-тест окна «Параметры запуска печати» — Alpha 2.723.
// Монтирует ДОСЛОВНУЮ разметку окна (web/index.html) настоящим вендорным Vue на самодельном DOM
// поверх ДОСЛОВНО извлечённых из web/app.js функций (PRINT_OPTS_DEFAULT/printerCapabilities/
// _loadPrintOpts/_printSrcOptions/printStart/openPrintStart/closePrintStart/confirmPrintStart/printFileOn).
// fetch/localStorage/sendJob-хелперы замоканы — сети и принтеров нет. Проверяем ВЫПОЛНЕНИЕМ:
//   V2  принтер БЕЗ живого AMS → источник ФИКСИРОВАННО «Внешняя катушка» (селекта нет), дефолты
//       таймлапс OFF / поток OFF / стол ON; «Печать» → body: ams_slot=-1 + print_opts с дефолтами;
//   V3  переключатели доходят до body (ON/ON/OFF); выбор сохраняется в localStorage per-printer
//       и восстанавливается при повторном открытии;
//   V4  AMS-принтер → «Авто (как в файле)» + «Внешняя катушка» (Alpha 2.734) + РЕАЛЬНЫЕ слоты (unit 0 → A1,
//       unit 1 → A2, HT unit 128 → A3); предвыбор из переданного слота; слот 0 → ams_slot=0; External → ams_slot=-1;
//   V5  «Авто» → body БЕЗ ams_slot (null) + print_opts присутствует; подсказка «как в файле» видна;
//   W1  guard: запомненный/предвыбранный слот ОТСУТСТВУЕТ в свежем live-отчёте AMS → сброс на «Авто (как в файле)»;
//   W2  guard: у принтера больше НЕТ живого AMS (а слот запомнен) → принудительно «Внешняя катушка», body.ams_slot=-1;
//   V6  не-Bambu (klipper): простое подтверждение, cb(null) → body БЕЗ print_opts и БЕЗ ams_slot (как раньше);
//   V7  «Отмена» не запускает печать (fetch не вызван, onConfirm не сработал);
//   V8  мосты: в index.html не осталось tr('Ext. spool'); amsPick/exAms → «Авто (как в файле)»,
//       cellAms (печать файла С принтера, где null = настоящая внешняя) → «Внешняя катушка».
// Запуск: node tools/test_print_start_ui.mjs   (0 = все проверки пройдены)
import { readFileSync } from 'fs';
import { fileURLToPath, pathToFileURL } from 'url';
import { dirname, join } from 'path';

const REPO = dirname(dirname(fileURLToPath(import.meta.url)));
const APPJS = readFileSync(join(REPO, 'web', 'app.js'), 'utf8');
const HTML = readFileSync(join(REPO, 'web', 'index.html'), 'utf8');
let fail = 0;
const check = (name, cond) => { console.log((cond ? 'PASS' : 'FAIL') + ' — ' + name); if (!cond) fail++; };

// ─────────── минимальный DOM (harness как в других runtime-тестах; + checked/selected/value) ───────────
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
  constructor(tag) { super(1); this._tag = tag; this.tagName = String(tag).toUpperCase(); this.namespaceURI = 'http://www.w3.org/1999/xhtml'; this.attributes = {}; this._listeners = {}; this.style = {}; this._cls = ''; this._disabled = false; this._value = ''; this.checked = false; this.selected = false; this.selectedIndex = -1; }
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
for (const g of ['SVGElement', 'HTMLElement', 'Element', 'Node', 'ShadowRoot', 'Document', 'DocumentFragment']) { if (globalThis[g] === undefined) globalThis[g] = class {}; }

// ─────────── извлечение ДОСЛОВНЫХ исходников ───────────
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
const line = (re) => (APPJS.match(re) || [''])[0];
const SRC_DEFAULT = line(/const PRINT_OPTS_DEFAULT = \{[^\n]*\};/);
const SRC_CAPS = extractFn(APPJS, 'const printerCapabilities = (printer) => {');
const SRC_LOAD = extractFn(APPJS, 'const _loadPrintOpts = (pid, caps) => {');
//  16.10.2026 (R-137): второй аргумент — двухсопельный ли принтер; подпись внешней катушки и пояснение под
//  ней — отдельные функции (у H2D сторона катушки — по соплу в файле, показаны материалы обеих катушек).
const SRC_SRCOPTS = extractFn(APPJS, 'const _printSrcOptions = (trays, dual) => {');
const SRC_EXTMAT = extractFn(APPJS, 'const _extTrayMat = (pid, id) => {');
const SRC_EXTLABEL = extractFn(APPJS, 'const printExtLabel = (ps) => {');
const SRC_EXTNOTE = extractFn(APPJS, 'const printExtNote = (ps) => {');
const SRC_STATE = line(/const printStart = ref\(\{[^\n]*\}\);/);
const SRC_OPEN = extractFn(APPJS, 'const openPrintStart = (ctx) => {');
const SRC_CLOSE = line(/const closePrintStart = \(\) => \{[^\n]*\};/);
const SRC_CONFIRM = extractFn(APPJS, 'const confirmPrintStart = () => {');
const SRC_TYPE = line(/const printStartTypeLabel = \(t\) => \{[^\n]*\};/);
const SRC_PRINTFILEON = extractFn(APPJS, "const printFileOn = async (filename, printerId, amsSlot, source = 'plan', partName = '', print_opts = undefined) => {");
// Alpha 2.839: блок сбора диагностического отчёта Klipper живёт в этой же секции окна и
// обязан монтироваться вместе с ней. Берём его ДОСЛОВНО: забытое имя в setup-возврате
// должно ронять этот тест, а не превращаться в молчаливо неотрисованный блок.
const _kri = APPJS.indexOf('const klRep = ref(');
const _krj = APPJS.indexOf('};', APPJS.indexOf('const copyKlipperSummary')) + 2;
const SRC_KLREPORT = (_kri > 0 && _krj > _kri) ? APPJS.slice(_kri, _krj) : '';
check('V1. дословные исходники извлечены (default/caps/load/srcOptions/state/open/close/confirm/klReport/printFileOn)',
  SRC_DEFAULT.includes('bed_leveling: true') && SRC_CAPS.length > 80 && SRC_LOAD.length > 100 && SRC_SRCOPTS.length > 100
  && SRC_EXTMAT.length > 50 && SRC_EXTLABEL.length > 50 && SRC_EXTNOTE.length > 100
  && SRC_STATE.includes("src: 'external'") && SRC_OPEN.length > 200 && SRC_CONFIRM.includes('srcSlot') && SRC_PRINTFILEON.length > 500
  && SRC_KLREPORT.length > 1500);

// ─────────── ДОСЛОВНАЯ разметка окна из index.html ───────────
const wKey = '<div v-if="printStart.open" v-backdrop-close="closePrintStart"';
let ws = HTML.indexOf(wKey);
const wOpenEnd = HTML.indexOf('>', ws) + 1;
const wRe = /<div\b|<\/div>/g; wRe.lastIndex = wOpenEnd;
let wm, wd = 1, wc = -1;
while ((wm = wRe.exec(HTML))) { wd += (wm[0] === '</div>') ? -1 : 1; if (wd === 0) { wc = wm.index; break; } }
const PANE = HTML.slice(ws, wc + '</div>'.length).replace('v-backdrop-close="closePrintStart"', '');   // кастомная директива не нужна для теста
check('V1b. разметка окна извлечена: источник/таймлапс/поток/стол/Печать/Отмена присутствуют',
  PANE.includes('printStart.srcOptions') && PANE.includes('printStart.opts.timelapse') && PANE.includes('printStart.opts.flow_cal')
  && PANE.includes('printStart.opts.bed_leveling') && PANE.includes('confirmPrintStart()') && PANE.includes('closePrintStart()'));

// ─────────── окружение: refs + стабы ───────────
const Vue = await import(pathToFileURL(join(REPO, 'web', 'vendor', 'vue.esm-browser.js')).href);
const { createApp, ref, nextTick } = Vue;
const store = new Map();
const localStorageStub = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) };
const net = [];
const fetchStub = async (url, opts) => { net.push({ url: String(url), body: opts && opts.body ? JSON.parse(opts.body) : null }); return { ok: true, status: 200, json: async () => ({ status: 'ok' }) }; };
const TRAYS = [
  { index: 0, unit: 0, tray: 0, type: 'PLA', color: '#c00' },
  { index: 1, unit: 0, tray: 1, type: 'PETG', color: '#0c0' },
  { index: 5, unit: 1, tray: 1, type: 'ABS', color: '#00c' },
  { index: 512, unit: 128, tray: 0, type: 'PA-CF', color: '#333' },
];
const env = {
  printers: ref([{ id: 'p1', name: 'X1-noAMS', type: 'bambu' }, { id: 'p2', name: 'X1-AMS', type: 'bambu' }, { id: 'p3', name: 'K1', type: 'klipper' }, { id: 'p4', name: 'X1-AMS-removed', type: 'bambu' }]),
  wsData: ref({ p2: { ams_trays: TRAYS } }),
  lang: ref('ru'),
  tr: (s) => s, confirm: () => true, alert: () => {}, pushToast: () => {}, toast: () => {},
  localStorage: localStorageStub, fetch: fetchStub,
  printMenuUid: ref(null), amsSelectFor: ref(null),
  _printerNameOf: (pid) => pid,
  beginSendJob: () => 'sj', setSendJobStage: () => {}, finishSendJob: () => {}, failSendJob: () => {}, cleanupSendJob: () => {},
};
const S = new Function('Vue', 'env', [
  'const { ref, computed } = Vue;',
  'const { printers, wsData, lang, tr, confirm, alert, pushToast, toast, localStorage, fetch, printMenuUid, amsSelectFor, _printerNameOf, beginSendJob, setSendJobStage, finishSendJob, failSendJob, cleanupSendJob } = env;',
  SRC_DEFAULT, SRC_CAPS, SRC_LOAD, SRC_SRCOPTS, SRC_EXTMAT, SRC_EXTLABEL, SRC_EXTNOTE, SRC_STATE, SRC_OPEN, SRC_CLOSE, SRC_CONFIRM, SRC_TYPE, SRC_KLREPORT, SRC_PRINTFILEON,
  'return { printStart, openPrintStart, closePrintStart, confirmPrintStart, printStartTypeLabel, printFileOn, PRINT_OPTS_DEFAULT, printExtLabel, printExtNote,',
  '         klRep, klRepPhaseText, klRepBusy, klRepDone, klRepSummaryLines, collectKlipperReport, saveKlipperReport, copyKlipperSummary };',
].join('\n'))(Vue, env);

const comp = { setup() { return Object.assign({ lang: env.lang }, S); }, template: '<div class="troot">' + PANE + '</div>' };
const app = createApp(comp);
app.config.compilerOptions.decodeEntities = (x) => x;
app.config.compilerOptions.hoistStatic = false;
app.config.warnHandler = () => {};
const root = new DElement('div');
app.mount(root);
const settle = async () => { for (let i = 0; i < 4; i++) { await new Promise((r) => setTimeout(r, 0)); await nextTick(); } };
await settle();

const txt = () => root.textContent;
const btn = (t) => root._findAll((e) => e._tag === 'button').find((b) => b.textContent.trim() === t);
const click = (el) => el._fire('click', { type: 'click', target: el, currentTarget: el, stopPropagation() {}, preventDefault() {} });
const checkboxes = () => root._findAll((e) => e._tag === 'input' && e.getAttribute('type') === 'checkbox');
const selects = () => root._findAll((e) => e._tag === 'select');
const setCheckbox = async (el, v) => { el.checked = v; el._fire('change', { type: 'change', target: el, stopPropagation() {}, preventDefault() {} }); await settle(); };
const pickOption = async (sel, value) => {
  const os = sel.options;
  os.forEach((o) => { o.selected = false; });
  const t = os.find((o) => String(o._value !== undefined ? o._value : o.getAttribute('value')) === String(value));
  t.selected = true;
  sel._fire('change', { type: 'change', target: sel, stopPropagation() {}, preventDefault() {} });
  await settle();
};

// ═══ V2: принтер БЕЗ AMS → фиксированная «Внешняя катушка», дефолты, body ams_slot=-1 ═══
net.length = 0;
await S.printFileOn('part.gcode.3mf', 'p1', null, 'quick', '');
await settle();
const cbs = checkboxes();
check('V2a. окно для p1 (без AMS): источник фиксирован «Внешняя катушка», селекта НЕТ; 3 чекбокса с дефолтами OFF/OFF/ON',
  S.printStart.value.open === true && txt().includes('Внешняя катушка') && selects().length === 0
  && cbs.length === 3 && cbs[0].checked === false && cbs[1].checked === false && cbs[2].checked === true);
click(btn('Печать'));
await settle(); await settle();
const b2 = net.find((c) => c.url === '/api/part/print');
check('V2b. «Печать» → /api/part/print: ams_slot=-1 (внешняя, подтверждённый формат) + print_opts {timelapse:false, bed_leveling:true, flow_cal:false}',
  b2 && b2.body.ams_slot === -1
  && JSON.stringify(b2.body.print_opts) === JSON.stringify({ timelapse: false, bed_leveling: true, flow_cal: false }));

// ═══ V3: переключатели → body; localStorage сохраняет и восстанавливает ═══
net.length = 0;
await S.printFileOn('part.gcode.3mf', 'p1', null, 'quick', '');
await settle();
const cbs3 = checkboxes();
await setCheckbox(cbs3[0], true);    // таймлапс ON
await setCheckbox(cbs3[1], true);    // поток ON
await setCheckbox(cbs3[2], false);   // стол OFF
click(btn('Печать'));
await settle(); await settle();
const b3 = net.find((c) => c.url === '/api/part/print');
check('V3a. ON/ON/OFF доходят до body.print_opts точно',
  b3 && JSON.stringify(b3.body.print_opts) === JSON.stringify({ timelapse: true, bed_leveling: false, flow_cal: true }));
await S.printFileOn('part.gcode.3mf', 'p1', null, 'quick', '');
await settle();
const cbs3b = checkboxes();
check('V3b. localStorage per-printer: повторное открытие восстанавливает ON/ON/OFF; ключ fm_printopts_p1 записан',
  cbs3b[0].checked === true && cbs3b[1].checked === true && cbs3b[2].checked === false
  && JSON.parse(store.get('fm_printopts_p1')).flow_cal === true);
S.closePrintStart(); await settle();
store.set('fm_printopts_p1', JSON.stringify({ timelapse: false, bed_leveling: true, flow_cal: false }));   // вернуть дефолты следующим сценариям

// ═══ V4: AMS-принтер → Авто + реальные слоты, БЕЗ ложной «Внешней»; выбор слота → body ═══
net.length = 0;
await S.printFileOn('multi.gcode.3mf', 'p2', 5, 'quick', '');   // предвыбор: слот 5 (пришёл из amsPick)
await settle();
const sel4 = selects()[0];
const optTexts = sel4 ? sel4.options.map((o) => o.textContent.trim()) : [];
check('V4a. AMS-принтер (Alpha 2.734): селект = «Авто (как в файле)» + «Внешняя катушка» + 4 РЕАЛЬНЫХ слота (6 пунктов); External на 2-й позиции; предвыбран слот 5',
  !!sel4 && optTexts.length === 6 && optTexts[0] === 'Авто (как в файле)' && optTexts[1] === 'Внешняя катушка'
  && optTexts.some((t) => t.startsWith('AMS A1 · Слот 1')) && optTexts.some((t) => t.startsWith('AMS A1 · Слот 2'))
  && optTexts.some((t) => t.startsWith('AMS A2 · Слот 2')) && optTexts.some((t) => t.includes('AMS A3 · Слот 1') && t.includes('PA-CF'))
  && optTexts.slice(2).every((t) => !t.includes('Внешн'))   // «Внешн» только в выделенном пункте External, не в подписях слотов
  && S.printStart.value.src === 5);
await pickOption(sel4, 0);   // пользователь меняет на слот 0 (A1 · Слот 1)
click(btn('Печать'));
await settle(); await settle();
const b4 = net.find((c) => c.url === '/api/part/print');
check('V4b. выбран слот 0 → body.ams_slot=0 + print_opts присутствует', b4 && b4.body.ams_slot === 0 && !!b4.body.print_opts);

// ═══ V4c (задача A): AMS-принтер + выбор «Внешняя катушка» → body.ams_slot=-1 (external доступен и при живом AMS) ═══
net.length = 0;
await S.printFileOn('multi.gcode.3mf', 'p2', null, 'quick', '');   // AMS-принтер, дефолт «Авто»
await settle();
const sel4c = selects()[0];
await pickOption(sel4c, -1);   // пользователь выбирает «Внешняя катушка»
//  16.10.2026 (R-137): внешняя катушка разрешена, когда ПЛИТА печатает один материал (а не проект объявляет один).
check('V4c1. AMS-принтер: выбор «Внешняя катушка» → src=-1; видна подсказка «Только если плита печатает один материал»',
  S.printStart.value.src === -1 && txt().includes('Только если плита печатает один материал'));
click(btn('Печать'));
await settle(); await settle();
const b4c = net.find((c) => c.url === '/api/part/print');
check('V4c2. External на AMS-принтере → body.ams_slot=-1 (тот же -1, что и без AMS) + print_opts присутствует',
  b4c && b4c.body.ams_slot === -1 && !!b4c.body.print_opts);

// ═══ V5: «Авто (как в файле)» → body БЕЗ ams_slot ═══
net.length = 0;
await S.printFileOn('multi.gcode.3mf', 'p2', null, 'quick', '');
await settle();
check('V5a. предвыбор «Авто», подсказка «Слоты назначатся автоматически…» видна',
  S.printStart.value.src === 'auto' && txt().includes('Слоты назначатся автоматически'));
click(btn('Печать'));
await settle(); await settle();
const b5 = net.find((c) => c.url === '/api/part/print');
check('V5b. Авто → body БЕЗ ams_slot (сервер сам маппит по файлу), print_opts присутствует',
  b5 && !('ams_slot' in b5.body) && !!b5.body.print_opts);

// ═══ W1: guard — запомненный слот исчез из живого отчёта → сброс на «Авто» ═══
net.length = 0;
await S.printFileOn('part.gcode.3mf', 'p2', 99, 'quick', '');   // слот 99 в live-отчёте НЕ существует
await settle();
check('W1a. предвыбранный слот 99 отсутствует в живом AMS-отчёте → окно сброшено на «Авто (как в файле)»',
  S.printStart.value.open === true && S.printStart.value.src === 'auto' && txt().includes('Слоты назначатся автоматически'));
click(btn('Печать'));
await settle(); await settle();
const bw1 = net.find((c) => c.url === '/api/part/print');
check('W1b. подтверждение после сброса → body БЕЗ ams_slot (авто), print_opts присутствует',
  bw1 && !('ams_slot' in bw1.body) && !!bw1.body.print_opts);

// ═══ W2: guard — у принтера больше нет живого AMS, а слот запомнен → принудительно «Внешняя катушка» ═══
net.length = 0;
await S.printFileOn('part.gcode.3mf', 'p4', 1, 'quick', '');   // p4: слот 1 запомнен, но live-AMS у принтера НЕТ
await settle();
check('W2a. принтер без живого AMS: источник принудительно «Внешняя катушка» (селекта нет), запомненный слот игнорирован',
  S.printStart.value.open === true && S.printStart.value.hasAms === false && S.printStart.value.src === 'external'
  && selects().length === 0 && txt().includes('Внешняя катушка'));
click(btn('Печать'));
await settle(); await settle();
const bw2 = net.find((c) => c.url === '/api/part/print');
check('W2b. подтверждение → body.ams_slot=-1 (подтверждённый external-формат), а НЕ запомненный слот 1',
  bw2 && bw2.body.ams_slot === -1 && !!bw2.body.print_opts);

// ═══ V6: klipper — adapter-driven секция (2.833); без выбора запрос БАЙТ-В-БАЙТ прежний ═══
net.length = 0;
await S.printFileOn('k.gcode', 'p3', null, 'quick', '');
await settle();
check('V6a. окно для klipper: adapter-driven «Как в файле» (Bambu-опции НЕ протекают: нет их чекбоксов/селекта источника)',
  S.printStart.value.open === true && checkboxes().length === 0 && selects().length === 0
  && txt().includes('Как в файле') && !txt().includes('Таймлапс') && !txt().includes('Внешняя катушка'));
check('V6a2. discovery выполняется read-only GET-ом klipper-prestart (не printer-командой)',
  net.some((c) => c.url === '/api/printer/p3/klipper-prestart' && c.body === null));
click(btn('Печать'));
await settle(); await settle();
const b6 = net.find((c) => c.url === '/api/part/print');
check('V6b. klipper без выбранных операций: body БЕЗ print_opts и БЕЗ ams_slot — запрос как раньше', b6 && !('print_opts' in b6.body) && !('ams_slot' in b6.body));

// ═══ V7: «Отмена» не запускает печать ═══
net.length = 0;
await S.printFileOn('part.gcode.3mf', 'p1', null, 'quick', '');
await settle();
click(btn('Отмена'));
await settle();
check('V7. «Отмена»: окно закрыто, fetch печати НЕ вызван', S.printStart.value.open === false && net.length === 0);

// ═══ V8: мосты по файлам ═══
check('V8a. index.html: tr(\'Ext. spool\') не осталось; amsPick/exAms переименованы в «Авто (как в файле)»; cellAms — в «Внешняя катушка»',
  !HTML.includes("tr('Ext. spool')")
  && />\{\{ lang==='ru'\?'Авто \(как в файле\)':'Auto \(as in file\)' \}\}<\/button>/.test(HTML)
  && HTML.includes("sendCmd('start_print', printFileName)\" class=\"block w-full text-left px-3 py-1.5 text-xs text-gray-300 hover:bg-neon/15 hover:text-neon transition-colors truncate\">{{ lang==='ru'?'Внешняя катушка':'External spool' }}</button>"));
// 2.825: +5-й путь — «Печать» из файлового менеджера принтеров (pfPrintNow, режим c1);
// сигнатура (opts, srcSlot) та же, пакетный гейт ids.length===1 не менялся.
// 08.10.2026 (R-008): _doSend собирает body проекта и задачи в одном месте — гейт ams_slot стал одной
// строкой на оба пути (было две). Проверяем, что он один, стоит в _doSend после выбора адреса обоих
// путей и до отправки.
const _ds = APPJS.slice(APPJS.indexOf('const _doSend = async (print_opts, srcSlot)'));
const _dsBody = _ds.slice(0, _ds.indexOf('await Promise.all(ids.map(sendOne))'));
const _gate = _dsBody.indexOf('if (ids.length === 1 && srcSlot !== undefined && srcSlot !== null) body.ams_slot');
check('V8b. app.js: onConfirm всех пяти путей принимает (opts, srcSlot); пакетный путь ≥2 не шлёт ams_slot (ids.length === 1 гейт)',
  (APPJS.match(/onConfirm: \(opts, srcSlot\)/g) || []).length === 5
  && (APPJS.match(/ids\.length === 1 && srcSlot !== undefined && srcSlot !== null/g) || []).length === 1
  && _gate > _dsBody.indexOf("url = '/api/projects2/'") && _gate > _dsBody.indexOf("url = '/api/part/print'")
  && _dsBody.indexOf("url = '/api/projects2/'") > 0 && _gate < _dsBody.indexOf('await _post(body)'));

// ═══ V9 (16.10.2026, R-137): двухсопельный Bambu (H2D) — сторону внешней катушки выбирает файл ═══
env.printers.value = env.printers.value.concat([{ id: 'p5', name: 'H2D-noAMS', type: 'bambu' }, { id: 'p6', name: 'H2D-AMS', type: 'bambu' }]);
env.wsData.value = Object.assign({}, env.wsData.value, {
  p5: { nozzle_count: 2, ext_trays: { '254': { tray_type: 'PLA' }, '255': { tray_type: 'PETG' } } },
  p6: { nozzle_count: 2, ams_trays: TRAYS.slice(0, 1), ext_trays: { '254': { tray_type: 'ABS' } } } });
net.length = 0;
await S.printFileOn('part.gcode.3mf', 'p5', null, 'quick', '');
await settle();
check('V9a. H2D без AMS: «Внешняя катушка (сторона — по соплу в файле)», селекта нет, под ним — материалы обеих катушек',
  S.printStart.value.dual === true && selects().length === 0 && txt().includes('Внешняя катушка (сторона — по соплу в файле)')
  && txt().includes('левая: PLA') && txt().includes('правая: PETG'));
click(btn('Печать'));
await settle(); await settle();
const b9 = net.find((c) => c.url === '/api/part/print');
check('V9b. H2D без AMS → body.ams_slot=-1 (сторону сервер берёт из файла)', b9 && b9.body.ams_slot === -1);
await S.printFileOn('part.gcode.3mf', 'p6', null, 'quick', '');
await settle();
const sel9 = selects()[0];
const opt9 = sel9 ? sel9.options.map((o) => o.textContent.trim()) : [];
await pickOption(sel9, -1);
check('V9c. H2D с AMS: пункт «Внешняя катушка (сторона — по соплу в файле)»; выбран — под списком обе катушки (правой нет — «—»)',
  opt9[1] === 'Внешняя катушка (сторона — по соплу в файле)' && S.printStart.value.src === -1
  && txt().includes('левая: ABS') && txt().includes('правая: —'));
S.closePrintStart(); await settle();

console.log('\n' + (fail ? ('FAIL: ' + fail + ' проверок провалено') : 'PASS: окно «Параметры запуска печати» — источник External/AMS честный, опции доходят до body, per-printer память, non-Bambu не изменён (реальный Vue mount + DOM-события)'));
process.exit(fail ? 1 : 0);
