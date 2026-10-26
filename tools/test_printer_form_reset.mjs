// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// РЕАЛЬНЫЙ runtime-тест формы принтера — Alpha 2.721.
// Баг: после «Изменить принтер» кнопка «＋ Добавить принтер» открывала форму с данными последнего
// редактировавшегося принтера, а если редактирование закрывали той же кнопкой («Отмена»), форма
// оставалась в режиме редактирования и «Сохранить» ОБНОВЛЯЛ прежний принтер вместо создания нового.
// Тест НЕ статический: из web/app.js во время выполнения извлекаются ДОСЛОВНЫЕ исходники функций
// (blankPrinterForm/openEditPrinter/openAddPrinter/toggleAddPrinter/addPrinterNode + ветка Escape),
// из web/index.html — ДОСЛОВНАЯ разметка кнопки шапки и всей модалки; всё монтируется настоящим
// вендорным Vue (web/vendor/vue.esm-browser.js) на самодельном DOM, события — реальные click/input.
// Последовательность (по задаче):
//   R2  открыть редактирование принтера A — форма в режиме редактирования с данными A;
//   R4  закрыть ОБЫЧНОЙ кнопкой («Отмена» в шапке);
//   R5  нажать «Добавить» — ЧИСТАЯ форма: дефолты, новый независимый объект, режим создания;
//   R7  отдельно: снова редактирование A -> закрытие ДОСЛОВНОЙ веткой Escape -> «Добавить» -> чисто;
//   R8  submit создаёт НОВОГО принтера (create, не update), A/B не изменены;
//   R9  последующее редактирование другого принтера B работает (update, без нового принтера);
//   R10 после этого «Добавить» снова открывает чистую форму создания.
// Harness тот же, что в tools/test_inventory_bind_runtime.mjs (+ options/selectedIndex для <select>,
// value у input, терпимый innerHTML для v-html; compilerOptions: decodeEntities=identity — самодельный
// DOM не декодирует сущности, hoistStatic=false — insertStaticContent требует настоящего HTML-парсера).
// Запуск: node tools/test_printer_form_reset.mjs   (0 = все проверки пройдены)
import { readFileSync } from 'fs';
import { fileURLToPath, pathToFileURL } from 'url';
import { dirname, join } from 'path';

const REPO = dirname(dirname(fileURLToPath(import.meta.url)));
const APPJS = readFileSync(join(REPO, 'web', 'app.js'), 'utf8');
const HTML = readFileSync(join(REPO, 'web', 'index.html'), 'utf8');
let fail = 0;
const check = (name, cond) => { console.log((cond ? 'PASS' : 'FAIL') + ' — ' + name); if (!cond) fail++; };

// ─────────── минимальный DOM (ровно тот API, который дёргает Vue runtime-dom) ───────────
class DNode {
  constructor(nodeType) { this.nodeType = nodeType; this.childNodes = []; this.parentNode = null; }
  get nextSibling() { const p = this.parentNode; if (!p) return null; const i = p.childNodes.indexOf(this); return i >= 0 ? (p.childNodes[i + 1] || null) : null; }
  _link(child, anchor) { if (child.parentNode) child.parentNode.removeChild(child); child.parentNode = this; if (anchor && anchor.parentNode === this) { this.childNodes.splice(this.childNodes.indexOf(anchor), 0, child); } else this.childNodes.push(child); return child; }
  insertBefore(child, anchor) { return this._link(child, anchor); }
  appendChild(child) { return this._link(child, null); }
  removeChild(child) { const i = this.childNodes.indexOf(child); if (i >= 0) this.childNodes.splice(i, 1); child.parentNode = null; return child; }
  getRootNode() { return globalThis.document; }   // vModelText.beforeUpdate сверяет activeElement корня
}
class DText extends DNode { constructor(t) { super(3); this.nodeValue = t == null ? '' : String(t); } get data() { return this.nodeValue; } set data(v) { this.nodeValue = v; } }
class DComment extends DNode { constructor(t) { super(8); this.nodeValue = t == null ? '' : String(t); } }
class DElement extends DNode {
  constructor(tag) { super(1); this._tag = tag; this.tagName = String(tag).toUpperCase(); this.namespaceURI = 'http://www.w3.org/1999/xhtml'; this.attributes = {}; this._listeners = {}; this.style = {}; this._cls = ''; this._disabled = false; this._html = ''; }
  setAttribute(k, v) { this.attributes[k] = String(v); if (k === 'class') this._cls = String(v); }
  removeAttribute(k) { delete this.attributes[k]; if (k === 'class') this._cls = ''; }
  getAttribute(k) { return k in this.attributes ? this.attributes[k] : null; }
  hasAttribute(k) { return k in this.attributes; }
  get className() { return this._cls; }
  set className(v) { this._cls = v == null ? '' : String(v); this.attributes['class'] = this._cls; }
  get disabled() { return this._disabled; }
  set disabled(v) { this._disabled = !!v; if (v) this.attributes['disabled'] = ''; else delete this.attributes['disabled']; }
  get options() { return this._findAll((e) => e._tag === 'option'); }   // <select> для vModelSelect.setSelected
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
const documentShim = { createElement: (t) => new DElement(t), createElementNS: (ns, t) => new DElement(t), createTextNode: (t) => new DText(t), createComment: (t) => new DComment(t), querySelector: () => null, addEventListener: () => {}, removeEventListener: () => {} };
documentShim.body = new DElement('body'); documentShim.documentElement = new DElement('html'); documentShim.activeElement = null;
if (!globalThis.document) globalThis.document = documentShim;
if (!globalThis.window) { try { globalThis.window = globalThis; } catch (e) {} }
for (const g of ['SVGElement', 'HTMLElement', 'Element', 'Node', 'ShadowRoot', 'Document', 'DocumentFragment']) { if (globalThis[g] === undefined) globalThis[g] = class {}; }

const Vue = await import(pathToFileURL(join(REPO, 'web', 'vendor', 'vue.esm-browser.js')).href);
const { createApp, ref, computed, nextTick } = Vue;

// ─────────── извлечение ДОСЛОВНЫХ исходников из app.js (не копии — сам файл) ───────────
// Скан с учётом строк/шаблонных литералов: от анкера с «{» до парной «}».
const extractFn = (src, anchor) => {
  const i = src.indexOf(anchor);
  if (i < 0) throw new Error('anchor not found: ' + anchor);
  let d = 1, q = null, esc = false;
  for (let k = i + anchor.length; k < src.length; k++) {
    const ch = src[k], ch2 = src[k + 1];
    if (esc) { esc = false; continue; }
    if (q) { if (ch === '\\') esc = true; else if (ch === q) q = null; continue; }
    // Alpha 2.795: пропускаем // и /* … */ ДО учёта кавычек — иначе апостроф внутри русского
    // комментария (напр. «payload'ом») рассинхронит квази-строковый счётчик и даст ложный
    // "unbalanced braces". Регэксп-литералов с фигурными скобками в этих функциях нет.
    if (ch === '/' && ch2 === '/') { const nl = src.indexOf('\n', k); if (nl < 0) break; k = nl; continue; }
    if (ch === '/' && ch2 === '*') { const ce = src.indexOf('*/', k + 2); if (ce < 0) break; k = ce + 1; continue; }
    if (ch === "'" || ch === '"' || ch === '`') { q = ch; continue; }
    if (ch === '{') d++;
    else if (ch === '}') { d--; if (d === 0) { const end = src[k + 1] === ';' ? k + 2 : k + 1; return src.slice(i, end); } }
  }
  throw new Error('unbalanced braces after: ' + anchor);
};
const BLANK_SRC = (APPJS.match(/const blankPrinterForm = \(\) => \(\{[^\n]*\}\);/) || [''])[0];
const OPEN_EDIT_SRC = extractFn(APPJS, 'const openEditPrinter = (p) => {');
const OPEN_ADD_SRC = extractFn(APPJS, 'const openAddPrinter = () => {');
const TOGGLE_SRC = extractFn(APPJS, 'const toggleAddPrinter = () => {');
const NEWID_SRC = extractFn(APPJS, 'const _newPrinterId = () => {');   // Alpha 2.831: генератор нового stable id (collision-safe)
//  16.10.2026 (R-020): addPrinterNode не сохраняет неполный адрес, а форма показывает ошибку под полем.
//  Блок проверки адреса (printerAddressProblem … newPrinterAddrText) — обычные const подряд; берётся
//  целиком, как он есть в app.js, до конца строки с newPrinterAddrText.
const ADDR_START = APPJS.indexOf('const printerAddressProblem = (ip) => {');
const ADDR_END = ADDR_START >= 0 ? APPJS.indexOf('const newPrinterAddrText = computed(', ADDR_START) : -1;
const ADDR_SRC = ADDR_END > ADDR_START ? APPJS.slice(ADDR_START, APPJS.indexOf('\n', ADDR_END)) : '';
//  2.955: список принтеров для сохранения собирает общая функция _printersPayload.
//  Она — стрелка БЕЗ фигурной скобки у объявления (сразу цепочка filter/map), поэтому
//  extractFn с его счётом парной «}» тут не годится: берём до «;» на нулевой глубине.
const extractArrow = (src, anchor) => {
  const i = src.indexOf(anchor);
  if (i < 0) throw new Error('anchor not found: ' + anchor);
  let cu = 0, pa = 0, br = 0, q = null, esc = false;
  for (let k = i + anchor.length; k < src.length; k++) {
    const ch = src[k], ch2 = src[k + 1];
    if (esc) { esc = false; continue; }
    if (q) { if (ch === '\\') esc = true; else if (ch === q) q = null; continue; }
    if (ch === '/' && ch2 === '/') { const nl = src.indexOf('\n', k); if (nl < 0) break; k = nl; continue; }
    if (ch === '/' && ch2 === '*') { const ce = src.indexOf('*/', k + 2); if (ce < 0) break; k = ce + 1; continue; }
    if (ch === "'" || ch === '"' || ch === '`') { q = ch; continue; }
    if (ch === '{') cu++;
    else if (ch === '}') cu--;
    else if (ch === '(') pa++;
    else if (ch === ')') pa--;
    else if (ch === '[') br++;
    else if (ch === ']') br--;
    else if (ch === ';' && cu === 0 && pa === 0 && br === 0) return src.slice(i, k + 1);
  }
  throw new Error('unterminated arrow: ' + anchor);
};
const PAYLOAD_SRC = extractArrow(APPJS, 'const _printersPayload = (extraTokenFor = null, token = "") =>');
const ADD_NODE_SRC = extractFn(APPJS, 'const addPrinterNode = async (keepOpen = false) => {');   // Alpha 2.831: +keepOpen (Save copy)
const SECRET_HINT_SRC = extractFn(APPJS, 'const printerSecretHint = (kind) => {');   // 2.776/2.777: подсказка «секрет сохранён»
const escAnchor = APPJS.indexOf('// 4) Добавление/редактирование принтера');
const escStart = APPJS.indexOf('if (showAddPrinterModal.value)', escAnchor);
const ESC_SRC = escAnchor >= 0 && escStart > escAnchor ? APPJS.slice(escStart, APPJS.indexOf('\n', escStart)).trim() : '';
check('R1a. исходники извлечены из app.js (blankPrinterForm/openEdit/openAdd/toggle/addPrinterNode/Escape-ветка)',
  !!BLANK_SRC && OPEN_EDIT_SRC.length > 50 && OPEN_ADD_SRC.length > 50 && TOGGLE_SRC.length > 50 && ADD_NODE_SRC.length > 200
  && ESC_SRC.includes('editingPrinterId.value = null') && ADDR_SRC.includes('newPrinterAddrProblem'));

// ─────────── ДОСЛОВНАЯ разметка из index.html: кнопка шапки + вся модалка ───────────
const btnAt = HTML.indexOf('data-tour="add-printer"');
const btnStart = HTML.lastIndexOf('<button', btnAt);
const BTN_SRC = HTML.slice(btnStart, HTML.indexOf('</button>', btnAt) + '</button>'.length);
//  3.000 (форма принтера переехала на общий стиль): сама модалка — это лист .fm-addp-sheet
//  с role="dialog", а прежний «absolute top-0» остался только у затемнения позади неё. Якорь
//  обязан указывать на САМУ модалку: иначе разметка не извлекается и монтировать нечего.
const modalKey = '<div v-if="showAddPrinterModal" class="fm-addp-sheet"';
let ms = HTML.indexOf(modalKey);
const mOpenEnd = HTML.indexOf('>', ms) + 1;
const mRe = /<div\b|<\/div>/g; mRe.lastIndex = mOpenEnd;
let mm, mDepth = 1, mClose = -1;
while ((mm = mRe.exec(HTML))) { mDepth += (mm[0] === '</div>') ? -1 : 1; if (mDepth === 0) { mClose = mm.index; break; } }
const MODAL_SRC = HTML.slice(ms, mClose + '</div>'.length);
check('R1b. разметка извлечена из index.html: кнопка шапки с toggleAddPrinter, модалка с pf-name/pf-save (+2.831 save-copy)',
  BTN_SRC.includes('@click="toggleAddPrinter"') && BTN_SRC.includes("tr('＋ Add Printer')")
  && MODAL_SRC.includes('data-help="pf-name"') && MODAL_SRC.includes('@click="addPrinterNode(false)"')
  && MODAL_SRC.includes('data-help="pf-save-copy"') && MODAL_SRC.includes("tr('Edit Printer')")
  && MODAL_SRC.includes("tr('Register Printer')"));

// ─────────── сборка setup: РЕАЛЬНЫЕ функции app.js поверх реальных refs ───────────
const netCalls = [], saved = [], toasts = [];
let confirms = 0;
const A0 = { id: 'node_aaa11', name: 'Alpha-A', type: 'bambu', ip: '10.0.0.11', port: null, token: 'tokA', gen: 'auto', serial: 'SNA', model: 'Bambu Lab X1 Carbon', credential_configured: true };
const B0 = { id: 'node_bbb22', name: 'Beta-B', type: 'klipper', ip: '10.0.0.12', port: 7125, token: '', gen: 'auto', serial: '', model: 'Klipper' };
const printers = ref([JSON.parse(JSON.stringify(A0)), JSON.parse(JSON.stringify(B0))]);
const env = {
  printers,
  tr: (s) => s,
  lang: ref('en'),
  confirm: () => { confirms++; return true; },
  pushToast: (m) => toasts.push(m),
  fetch: async (url, opts) => { netCalls.push({ url: String(url), body: opts && opts.body ? JSON.parse(opts.body) : null }); return { ok: true, status: 200, json: async () => ({ reachable: true, match: true }) }; },
  executePostMatrix: async (endpoint, data) => { saved.push({ endpoint, data: JSON.parse(JSON.stringify(data)) }); },
  fetchStateMatrix: async () => {},
  loadPrinterModels: () => { env._lpmCalls = (env._lpmCalls || 0) + 1; },
  //  2.980 (R-092): закрытие формы гасит и панель найденных в сети принтеров.
  //  В обвязке панели нет — считаем вызовы, чтобы закрытие было доказано.
  discClose: () => { env._discCloseCalls = (env._discCloseCalls || 0) + 1; },   // 2.733: openEditPrinter подгружает canonical registry (стаб-счётчик)
};
const buildState = new Function('Vue', 'env', [
  'const { ref, computed } = Vue;',
  'const { printers, tr, confirm, pushToast, fetch, executePostMatrix, fetchStateMatrix, loadPrinterModels, lang, discClose } = env;',
  'const showAddPrinterModal = ref(false);',
  'const editingPrinterId = ref(null);',
  'const showModelPicker = ref(false);',
  'const showModal = ref(false);',
  'const activeModalPrinterId = ref(null);',
  'const printerAddBusy = ref(false);',
  // Alpha 2.776/2.777: openEdit/openAdd управляют флагами «сохранённый секрет есть» — реальный
  // токен во фронтенд не приходит. Тест обязан объявить эти refs (иначе ReferenceError), а заодно
  // проверить, что при «Добавить» флаг сбрасывается (иначе форма создания намекала бы на чужой секрет).
  'const editingHasToken = ref(false);',
  'const editingHasSerial = ref(false);',
  'const copyBaseName = ref("");',   // Alpha 2.831: заголовок «на основе …» + сброс в open*
  BLANK_SRC,
  'const newPrinter = ref(blankPrinterForm());',
  ADDR_SRC,
  OPEN_EDIT_SRC,
  OPEN_ADD_SRC,
  TOGGLE_SRC,
  NEWID_SRC,
  PAYLOAD_SRC,
  ADD_NODE_SRC,
  'const savePrinterCopy = () => addPrinterNode(true);',   // Alpha 2.831: «Сохранить копию»
  SECRET_HINT_SRC,
  'const escCloseAddPrinter = () => { ' + ESC_SRC + ' };',
  'return { showAddPrinterModal, editingPrinterId, showModelPicker, showModal, activeModalPrinterId, printerAddBusy, editingHasToken, editingHasSerial, copyBaseName, newPrinter, blankPrinterForm, printerSecretHint, openEditPrinter, openAddPrinter, toggleAddPrinter, addPrinterNode, savePrinterCopy, escCloseAddPrinter, newPrinterAddrProblem, newPrinterAddrText, printerAddrServerProblem };',
].join('\n'))(Vue, env);
const S = buildState;

// ─────────── монтаж ДОСЛОВНОЙ разметки настоящим Vue ───────────
const comp = {
  setup() {
    return Object.assign({
      tr: env.tr, can: () => true, isMobile: false, svgAssets: { printer: '<svg></svg>' },
      printers, removePrinterById: () => {},
      openModelPicker: () => { S.showModelPicker.value = true; },           // как в app.js: открывает под-окно выбора модели
      selectedModelCover: computed(() => ''),
    }, S);
  },
  template: '<div class="troot">' + BTN_SRC + MODAL_SRC + '</div>',
};
const app = createApp(comp);
app.config.compilerOptions.decodeEntities = (x) => x;
app.config.compilerOptions.hoistStatic = false;
app.component('svg-icon', { props: { name: String }, template: '<i class="svgicon"></i>' });
const root = new DElement('div');
app.mount(root);

const ev = (type, el) => ({ type, target: el, currentTarget: el, timeStamp: Date.now(), stopPropagation() {}, stopImmediatePropagation() {}, preventDefault() {} });
const clickEl = (el) => el._fire('click', ev('click', el));
const typeInto = async (el, text) => { el.value = text; el._fire('input', ev('input', el)); await nextTick(); };
const settle = async () => { for (let i = 0; i < 3; i++) { await new Promise((r) => setTimeout(r, 0)); await nextTick(); } };
const byHelp = (k) => root._findAll((e) => e.getAttribute && e.getAttribute('data-help') === k)[0] || null;
const headerBtn = () => root._findAll((e) => e.getAttribute && e.getAttribute('data-tour') === 'add-printer')[0] || null;
const modalTitle = () => { const h = root._findAll((e) => e._tag === 'h3')[0]; return h ? h.textContent.trim() : null; };
const DEFAULTS = { name: '', type: 'bambu', ip: '', port: null, token: '', gen: 'auto', serial: '', model: '' };
const formIsBlank = () => { const f = S.newPrinter.value; const keys = Object.keys(f).sort().join(','); return keys === Object.keys(DEFAULTS).sort().join(',') && Object.keys(DEFAULTS).every((k) => f[k] === DEFAULTS[k]) && !('id' in f); };

// R1c: исходное состояние — модалка закрыта, кнопка шапки в режиме «Добавить»
await nextTick();
check('R1c. монтаж: модалка закрыта, кнопка шапки = «＋ Add Printer»',
  modalTitle() === null && headerBtn() && headerBtn().textContent.trim() === '＋ Add Printer');

// ═══ R2: открыть редактирование принтера A (реальная openEditPrinter из app.js) ═══
S.openEditPrinter(printers.value.find((x) => x.id === 'node_aaa11'));
await nextTick();
check('R2. редактирование A: режим редактирования (Edit Printer / Save Changes / есть Delete), форма = данные A',
  modalTitle() === 'Edit Printer'
  && byHelp('pf-save') && byHelp('pf-save').textContent.trim() === 'Save Changes'
  && !!byHelp('pf-delete')
  && byHelp('pf-name').value === 'Alpha-A' && byHelp('pf-ip').value === '10.0.0.11'
  && S.editingPrinterId.value === 'node_aaa11'
  && S.newPrinter.value.serial === 'SNA' && S.newPrinter.value.model === 'Bambu Lab X1 Carbon');
// Alpha 2.776/2.777: при редактировании поле токена открывается ПУСТЫМ — реальный секрет во
// фронтенд не приходит вовсе (пустое = «оставить текущее»). Старое ожидание token==='tokA'
// описывало ДОРЕЛИЗНОЕ поведение и означало бы утечку секрета в форму. Проверяем текущий контракт.
check('R2c. поле токена при редактировании ПУСТОЕ (секрет не подтягивается в форму, 2.776/2.777)',
  S.newPrinter.value.token === '');
check('R2b. редактирование A: флаг «сохранённый секрет есть» поднят из credential_configured (2.776/2.777)',
  S.editingHasToken.value === true);

// R3: открыть под-окно выбора модели (реальный клик) — временное состояние диалога
clickEl(byHelp('pf-model')); await nextTick();
check('R3. клик по «Выбрать модель» открывает под-окно (showModelPicker=true) — будет сброшено при «Добавить»',
  S.showModelPicker.value === true);

// ═══ R4: закрыть ОБЫЧНОЙ кнопкой — кнопка шапки в режиме «Cancel» (реальный клик по ДОСЛОВНОЙ кнопке) ═══
const dirtyFormObj = S.newPrinter.value;   // объект формы, заполненный данными A
check('R4a. пока модалка открыта, кнопка шапки подписана «Cancel»', headerBtn().textContent.trim() === 'Cancel');
clickEl(headerBtn()); await nextTick();
check('R4b. закрытие обычной кнопкой: модалка закрыта, режим редактирования снят',
  modalTitle() === null && S.showAddPrinterModal.value === false && S.editingPrinterId.value === null);

// ═══ R5: нажать «Добавить» — ЧИСТАЯ форма создания ═══
clickEl(headerBtn()); await nextTick();
check('R5a. «Добавить»: модалка открыта строго в режиме создания (Register Printer / Register, кнопки Delete НЕТ)',
  modalTitle() === 'Register Printer'
  && byHelp('pf-save') && byHelp('pf-save').textContent.trim() === 'Register'
  && !byHelp('pf-delete') && S.editingPrinterId.value === null);
check('R5b. форма ЧИСТАЯ: все штатные дефолты, без ID/имени/модели/IP/токенов прошлого принтера; DOM-поля пустые',
  formIsBlank() && byHelp('pf-name').value === '' && byHelp('pf-ip').value === '' && byHelp('pf-token').value === '');
check('R5c. это НОВЫЙ независимый объект состояния (не тот же, что был при редактировании A)',
  S.newPrinter.value !== dirtyFormObj && S.blankPrinterForm() !== S.blankPrinterForm());
check('R5d. временное под-окно выбора модели сброшено (showModelPicker=false)', S.showModelPicker.value === false);
check('R5d2. флаг «сохранённый секрет есть» сброшен: форма создания не намекает на чужой секрет (2.776)',
  S.editingHasToken.value === false && S.editingHasSerial.value === false);
check('R5e. кнопка «Register» задизейблена на пустой форме', byHelp('pf-save').disabled === true);

// независимость объекта: правка чистой формы не трогает принтер A
S.newPrinter.value.name = 'tmp-edit'; await nextTick();
check('R5f. правка чистой формы не меняет принтер A (объекты независимы)',
  printers.value.find((x) => x.id === 'node_aaa11').name === 'Alpha-A');

// ═══ R7: отдельно — закрытие редактирования ДОСЛОВНОЙ веткой Escape, затем «Добавить» ═══
S.openEditPrinter(printers.value.find((x) => x.id === 'node_aaa11'));
await nextTick();
const wasEdit = modalTitle() === 'Edit Printer' && byHelp('pf-name').value === 'Alpha-A';
S.escCloseAddPrinter();   // ДОСЛОВНО извлечённая ветка Escape из onKeydown app.js
await nextTick();
const closedByEsc = modalTitle() === null && S.editingPrinterId.value === null;
clickEl(headerBtn()); await nextTick();
check('R7. Escape-путь: редактирование A -> ДОСЛОВНАЯ ветка Escape закрывает -> «Добавить» -> чистая форма создания',
  wasEdit && closedByEsc && modalTitle() === 'Register Printer' && formIsBlank() && byHelp('pf-name').value === '');

// ═══ R8: submit из чистой формы = СОЗДАНИЕ нового принтера (реальная addPrinterNode из app.js) ═══
await typeInto(byHelp('pf-name'), 'Gamma-C');
await typeInto(byHelp('pf-ip'), '10.0.0.13');
S.newPrinter.value.model = 'Bambu Lab P1S';   // как pickModel: выбор модели в под-окне
await nextTick();
check('R8a. после заполнения (v-model через реальные input-события) кнопка «Register» активна',
  S.newPrinter.value.name === 'Gamma-C' && S.newPrinter.value.ip === '10.0.0.13' && byHelp('pf-save').disabled === false);
const savedBefore = saved.length;
clickEl(byHelp('pf-save'));
await settle();
const created = printers.value.find((x) => x.name === 'Gamma-C');
const lastSave = saved[saved.length - 1];
check('R8b. submit вызвал СОЗДАНИЕ: принтеров стало 3, у нового свой node_-id (не id A/B)',
  printers.value.length === 3 && created && /^node_/.test(created.id)
  && created.id !== 'node_aaa11' && created.id !== 'node_bbb22'
  && created.ip === '10.0.0.13' && created.model === 'Bambu Lab P1S');
check('R8c. это НЕ update: A и B не изменились (все поля дословно)',
  JSON.stringify(printers.value.find((x) => x.id === 'node_aaa11')) === JSON.stringify(A0)
  && JSON.stringify(printers.value.find((x) => x.id === 'node_bbb22')) === JSON.stringify(B0));
check('R8d. сохранение ушло в /api/printers/save с 3 принтерами; verify вызван; confirm не понадобился',
  saved.length === savedBefore + 1 && lastSave.endpoint === '/api/printers/save' && lastSave.data.length === 3
  && netCalls.some((c) => c.url === '/api/printer/verify') && confirms === 0);
check('R8e. после создания модалка закрыта, форма сброшена к дефолтам', S.showAddPrinterModal.value === false && formIsBlank());

// ═══ R9: последующее редактирование ДРУГОГО принтера B не сломано (update, не create) ═══
S.openEditPrinter(printers.value.find((x) => x.id === 'node_bbb22'));
await nextTick();
check('R9a. редактирование B открылось с его актуальными данными',
  modalTitle() === 'Edit Printer' && byHelp('pf-name').value === 'Beta-B'
  && byHelp('pf-ip').value === '10.0.0.12' && S.editingPrinterId.value === 'node_bbb22');
await typeInto(byHelp('pf-name'), 'Beta-B2');
clickEl(byHelp('pf-save'));
await settle();
const bAfter = printers.value.find((x) => x.id === 'node_bbb22');
check('R9b. submit в режиме редактирования = UPDATE: имя B обновлено, id сохранён, принтеров по-прежнему 3',
  printers.value.length === 3 && bAfter && bAfter.name === 'Beta-B2' && bAfter.ip === '10.0.0.12'
  && !printers.value.some((x) => x.name === 'Beta-B') && saved[saved.length - 1].data.length === 3);

// ═══ R10: контрольное «Добавить» после всей последовательности — снова чистая форма ═══
clickEl(headerBtn()); await nextTick();
check('R10. финальное «Добавить»: чистая форма создания (не данные B2)',
  modalTitle() === 'Register Printer' && formIsBlank() && byHelp('pf-name').value === '' && S.editingPrinterId.value === null);

// ═══ R11 (16.10.2026, R-020): неполный адрес — ошибка под полем, «Register» недоступна, ничего не уходит ═══
await typeInto(byHelp('pf-name'), 'Delta-D');
await typeInto(byHelp('pf-ip'), '198.68.104');
S.newPrinter.value.model = 'Klipper';
await nextTick();
const addrErr = () => root._findAll((e) => String(e.className || '').split(/\s+/).includes('fm-addp-err'))[0] || null;
check('R11a. адрес «198.68.104»: под полем ошибка «Incomplete address…», поле помечено, «Register» недоступна',
  !!addrErr() && addrErr().textContent.trim().startsWith('Incomplete address')
  && String(byHelp('pf-ip').className).includes('fm-addp-bad') && byHelp('pf-save').disabled === true);
const netBefore11 = netCalls.length, savedBefore11 = saved.length;
await S.addPrinterNode(false);   // прямой вызов (как Enter в поле), мимо недоступной кнопки
await settle();
check('R11b. с неполным адресом не уходит ничего: ни пробы адреса, ни записи; форма открыта, принтеров по-прежнему 3',
  netCalls.length === netBefore11 && saved.length === savedBefore11 && S.showAddPrinterModal.value === true
  && printers.value.length === 3);
await typeInto(byHelp('pf-ip'), '198.68.1.104');
check('R11c. дописали адрес — ошибки нет, «Register» снова доступна', !addrErr() && byHelp('pf-save').disabled === false);

// ─────────── мосты runtime<->файлы и регресс-охрана ───────────
check('S11. index.html: кнопка шапки вызывает toggleAddPrinter (ровно 1 раз); голого тоггла showAddPrinterModal=!... больше НЕТ',
  (HTML.match(/@click="toggleAddPrinter"/g) || []).length === 1 && !HTML.includes('showAddPrinterModal=!showAddPrinterModal'));
// Alpha 2.795: проверяем НАЛИЧИЕ каждого экспорта, а не их точную последовательность — вставка
// нового ключа (напр. printerSecretHint) между ними не должна ломать инвариант доступности.
check('S12. app.js: openAddPrinter/toggleAddPrinter/addPrinterNode/openEditPrinter экспортированы из setup (доступны шаблону)',
  ['openAddPrinter', 'toggleAddPrinter', 'addPrinterNode', 'openEditPrinter', 'editingPrinterId'].every((n) =>
    new RegExp('(^|[\\s,{])' + n + '\\s*[,}]').test(APPJS.slice(APPJS.lastIndexOf('return {')))));
check('S13. регресс-охрана: закрытие кликом по фону по-прежнему снимает режим редактирования',
  HTML.includes('@click="showAddPrinterModal=false; editingPrinterId=null"'));
check('S14. регресс-охрана: ветка Escape в onKeydown не тронута (закрывает модалку и снимает режим редактирования)',
  //  2.980 (R-092): Escape гасит ещё и панель найденных в сети принтеров (discClose).
  //  Инвариант прежний: модалка закрыта, режим правки снят, сохранения нет.
  ESC_SRC === 'if (showAddPrinterModal.value) { showAddPrinterModal.value = false; editingPrinterId.value = null; discClose(); return; }');

console.log('\n' + (fail ? ('FAIL: ' + fail + ' проверок провалено') : 'PASS: форма принтера — «Добавить» всегда чистая форма создания; редактирование не сломано (реальный Vue mount + DOM-события)'));
process.exit(fail ? 1 : 0);
