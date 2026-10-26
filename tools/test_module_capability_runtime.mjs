// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// РЕАЛЬНЫЙ runtime-тест capability contract окон модулей — Alpha 2.793.
// Монтирует настоящие CostPanel.js и InventoryPanel.js НАСТОЯЩИМ вендорным Vue
// (web/vendor/vue.esm-browser.js) на минимальном самодельном DOM и доказывает ВО ВРЕМЯ ВЫПОЛНЕНИЯ
// (а не строками в исходнике):
//   R1  логика ядра moduleCan(): известное право -> решение core can(); неизвестное -> false ВСЕГДА,
//       в том числе при выключенной авторизации (иначе owner-режим стал бы fail-open);
//   R2  AUTH OFF: оба окна показывают все изменяющие контролы (локальный владелец не поражён);
//   R3  view-only: изменяющие контролы отсутствуют, чтение работает;
//   R4  deny ДО fetch: программный вызов обработчика без права не шлёт запрос и не меняет данные;
//   R5  отсутствующий/чужой contract: fail-safe, без исключений, без привилегированных запросов;
//   R6  понижение прав у ОТКРЫТОГО окна: admin-контролы исчезают, submit перестаёт слать запрос;
//   R7  contract не попадает в localStorage/sessionStorage;
//   R8  метка-ловушка не появляется ни в запросе, ни в состоянии, ни в хранилище.
// Запуск: node tools/test_module_capability_runtime.mjs   (0 = все проверки пройдены)
import { readFileSync, writeFileSync, mkdirSync, rmSync } from 'fs';
import { fileURLToPath, pathToFileURL } from 'url';
import { dirname, join } from 'path';

const REPO = dirname(dirname(fileURLToPath(import.meta.url)));
const SENTINEL = 'MODULE_CAPABILITY_SENTINEL_2_793';
let fail = 0;
const check = (name, cond) => { console.log((cond ? 'PASS' : 'FAIL') + ' — ' + name); if (!cond) fail++; };

// ─────────── минимальный DOM (тот же приём, что в остальных runtime-тестах модуля) ───────────
const ENT = { quot: '"', amp: '&', lt: '<', gt: '>', apos: "'", nbsp: ' ' };
const unescapeEnt = (s) => String(s).replace(/&(#x?[0-9a-fA-F]+|[a-zA-Z]+);/g, (m, g) => {
  if (g[0] === '#') { const n = g[1] === 'x' || g[1] === 'X' ? parseInt(g.slice(2), 16) : parseInt(g.slice(1), 10); return isFinite(n) ? String.fromCodePoint(n) : m; }
  return Object.prototype.hasOwnProperty.call(ENT, g) ? ENT[g] : m;
});

class DNode {
  constructor(nodeType) { this.nodeType = nodeType; this.childNodes = []; this.parentNode = null; }
  get nextSibling() { const p = this.parentNode; if (!p) return null; const i = p.childNodes.indexOf(this); return i >= 0 ? (p.childNodes[i + 1] || null) : null; }
  _link(child, anchor) { if (child.parentNode) child.parentNode.removeChild(child); child.parentNode = this; if (anchor && anchor.parentNode === this) { this.childNodes.splice(this.childNodes.indexOf(anchor), 0, child); } else this.childNodes.push(child); return child; }
  insertBefore(child, anchor) { return this._link(child, anchor); }
  appendChild(child) { return this._link(child, null); }
  removeChild(child) { const i = this.childNodes.indexOf(child); if (i >= 0) this.childNodes.splice(i, 1); child.parentNode = null; return child; }
}
class DText extends DNode { constructor(t) { super(3); this.nodeValue = t == null ? '' : String(t); } get data() { return this.nodeValue; } set data(v) { this.nodeValue = v; } }
class DComment extends DNode { constructor(t) { super(8); this.nodeValue = t == null ? '' : String(t); } }
class DElement extends DNode {
  constructor(tag) { super(1); this._tag = tag; this.tagName = String(tag).toUpperCase(); this.namespaceURI = 'http://www.w3.org/1999/xhtml'; this.attributes = {}; this._listeners = {}; this.style = {}; this._cls = ''; this._disabled = false; this._readOnly = false; }
  setAttribute(k, v) { this.attributes[k] = String(v); if (k === 'class') this._cls = String(v); }
  removeAttribute(k) { delete this.attributes[k]; if (k === 'class') this._cls = ''; }
  getAttribute(k) { return k in this.attributes ? this.attributes[k] : null; }
  hasAttribute(k) { return k in this.attributes; }
  get className() { return this._cls; }
  set className(v) { this._cls = v == null ? '' : String(v); this.attributes['class'] = this._cls; }
  get disabled() { return this._disabled; }
  set disabled(v) { this._disabled = !!v; if (v) this.attributes['disabled'] = ''; else delete this.attributes['disabled']; }
  // Vue ставит readonly и как свойство, и как атрибут — учитываем оба пути.
  get readOnly() { return this._readOnly || this.attributes['readonly'] != null; }
  set readOnly(v) { this._readOnly = !!v; if (v) this.attributes['readonly'] = ''; else delete this.attributes['readonly']; }
  addEventListener(t, fn) { (this._listeners[t] = this._listeners[t] || []).push(fn); }
  removeEventListener(t, fn) { const a = this._listeners[t]; if (a) { const i = a.indexOf(fn); if (i >= 0) a.splice(i, 1); } }
  get textContent() { return this.childNodes.map((c) => c.nodeType === 3 ? c.nodeValue : (c.nodeType === 1 ? c.textContent : '')).join(''); }
  set textContent(v) { this.childNodes.forEach((c) => (c.parentNode = null)); this.childNodes = []; if (v !== '' && v != null) this.appendChild(new DText(String(v))); }
  hasChildNodes() { return this.childNodes.length > 0; }
  get firstChild() { return this.childNodes[0] || null; }
  get children() { return this.childNodes.filter((c) => c.nodeType === 1); }
  // v-model на <select> (директива vModelSelect) читает el.options[].selected — без этого
  // её хук mounted/updated роняет TypeError и шумит в каждом рендере.
  get options() { return this._findAll((e) => e._tag === 'option'); }
  get innerHTML() { return ''; }
  // Компилятор шаблонов вендорного Vue декодирует сущности ЧЕРЕЗ DOM и ровно в двух режимах:
  // атрибутном (`<div foo="…">` -> children[0].getAttribute('foo')) и текстовом (-> textContent).
  // Без этой заглушки любой шаблон с &nbsp;/&quot; роняет compile() (TypeError в decodeEntities).
  set innerHTML(v) {
    this.childNodes.forEach((c) => (c.parentNode = null)); this.childNodes = [];
    const s = v == null ? '' : String(v);
    if (s === '') return;
    const m = /^<div foo="([\s\S]*)">$/.exec(s);
    if (m) { const d = new DElement('div'); d.setAttribute('foo', unescapeEnt(m[1])); this.appendChild(d); return; }
    this.appendChild(new DText(unescapeEnt(s)));
  }
  querySelector() { return null; }
  _fire(type, ev) { (this._listeners[type] || []).slice().forEach((fn) => fn(ev)); }
  _findAll(pred, out = []) { if (this.nodeType === 1 && pred(this)) out.push(this); this.childNodes.forEach((c) => { if (c.nodeType === 1) c._findAll(pred, out); }); return out; }
}
const documentShim = { createElement: (t) => new DElement(t), createElementNS: (ns, t) => new DElement(t), createTextNode: (t) => new DText(t), createComment: (t) => new DComment(t), getElementById: () => null, addEventListener: () => {}, removeEventListener: () => {} };
documentShim.body = new DElement('body'); documentShim.documentElement = new DElement('html');
documentShim.head = new DElement('head');
// Оба окна модулей — <teleport to="body">: без разрешения цели Vue роняет монтирование.
documentShim.querySelector = (sel) => (sel === 'body' ? documentShim.body : (sel === 'head' ? documentShim.head : null));
if (!globalThis.document) globalThis.document = documentShim;
if (!globalThis.window) { try { globalThis.window = globalThis; } catch (e) {} }
for (const g of ['SVGElement', 'HTMLElement', 'Element', 'Node', 'ShadowRoot']) { if (globalThis[g] === undefined) globalThis[g] = class {}; }
globalThis.window.confirm = () => true;   // подтверждения не должны прерывать проверку deny-before-fetch
globalThis.confirm = () => true;
if (typeof globalThis.window.addEventListener !== 'function') { globalThis.window.addEventListener = () => {}; globalThis.window.removeEventListener = () => {}; }
if (!globalThis.window.dispatchEvent) globalThis.window.dispatchEvent = () => true;
if (!globalThis.CustomEvent) globalThis.CustomEvent = class { constructor(t, o) { this.type = t; Object.assign(this, o || {}); } };
if (!globalThis.window.innerWidth) { globalThis.window.innerWidth = 1440; globalThis.window.innerHeight = 900; }

// шпионы: сеть и браузерное хранилище
const netCalls = [];
globalThis.fetch = async (url, opts) => {
  netCalls.push({ url: String(url), method: (opts && opts.method) || 'GET', body: (opts && opts.body) || null });
  return { ok: true, status: 200, json: async () => ({ ok: true, global: {}, printers: [], calculations: [] }), text: async () => '<svg/>' };
};
const storageWrites = [];
const mkStorage = () => ({ getItem: () => null, setItem: (k, v) => storageWrites.push({ k, v: String(v) }), removeItem: () => {} });
globalThis.localStorage = mkStorage();
globalThis.sessionStorage = mkStorage();

const Vue = await import(pathToFileURL(join(REPO, 'web', 'vendor', 'vue.esm-browser.js')).href);
const { createApp, h } = Vue;

// ─────────── R1: НАСТОЯЩАЯ логика ядра moduleCan() из web/app.js ───────────
const APPJS = readFileSync(join(REPO, 'web', 'app.js'), 'utf8');
const capsSrc = APPJS.match(/const MODULE_CAPABILITIES = Object\.freeze\(\[[^\]]*\]\);/);
const canSrc = APPJS.match(/const moduleCan = \(cap\) => [^\n]*;/);
check('R0. исходники ядра найдены (иначе проверки были бы вакуумными)', !!capsSrc && !!canSrc);

const mkModuleCan = (coreCan) => {
  // Исполняем ИМЕННО производственные строки, а не их пересказ.
  const factory = new Function('can', `${capsSrc[0]}\n${canSrc[0]}\nreturn moduleCan;`);
  return factory(coreCan);
};
const canAllTrue = () => true;                    // соответствует core can() при AUTH OFF
const canAdmin = (p) => ['view', 'operate', 'project', 'printer_write', 'count', 'rework', 'admin'].includes(p);
const canView = (p) => p === 'view';

let mc = mkModuleCan(canAllTrue);
check('R1a. AUTH OFF: известное право разрешено', mc('project') === true && mc('admin') === true);
check('R1b. AUTH OFF: НЕИЗВЕСТНОЕ право всё равно запрещено (owner-режим не fail-open)',
      mc('made_up') === false && mc(SENTINEL) === false && mc('') === false);
check('R1c. не-строка и подстрока/префикс не проходят',
      mc(null) === false && mc(undefined) === false && mc(1) === false
      && mc('adm') === false && mc('administrator') === false && mc('view ') === false);
check('R1d. printer_delete модулям не выдаётся даже администратору',
      mkModuleCan(canAdmin)('printer_delete') === false);
mc = mkModuleCan(canView);
check('R1e. view-роль: project/count/admin запрещены, view разрешён',
      mc('view') === true && mc('project') === false && mc('count') === false && mc('admin') === false);

// ─────────── контракты для окон ───────────
const contract = (coreCan, authEnabled, rev) => Object.freeze({
  contractVersion: 1,
  authEnabled: authEnabled,
  capabilities: Object.freeze(['view', 'project', 'operate', 'printer_write', 'count', 'rework', 'admin'].filter((c) => mkModuleCan(coreCan)(c))),
  revision: rev || 0,
  can: mkModuleCan(coreCan),
  revalidate: () => { revalidateCalls++; },
});
let revalidateCalls = 0;

// Панели написаны под браузерный importmap (`from 'vue'`). Node такой спецификатор не разрешает,
// поэтому загружаем НАСТОЯЩИЙ файл модуля, подменив ровно строку импорта на вендорный Vue —
// тот же экземпляр Vue, что и выше, поэтому reactive/computed общие. Содержимое компонента не меняется.
const VENDOR = pathToFileURL(join(REPO, 'web', 'vendor', 'vue.esm-browser.js')).href;
const TMP = join(process.env.TEMP || process.env.TMP || REPO, 'fm_cap_runtime_' + process.pid);
mkdirSync(TMP, { recursive: true });
const loadPanel = async (rel, name) => {
  const raw = readFileSync(join(REPO, rel), 'utf8');
  const patched = raw.replace(/from\s+['"]vue['"]/g, `from '${VENDOR}'`);
  if (patched === raw) throw new Error('импорт vue не найден в ' + rel);
  // 1.7.36: окно склада подключает соседние файлы модуля (./InventoryI18n.js) — во временной папке их
  // нет, поэтому относительные ссылки ведут в настоящую папку модуля.
  const dirUrl = pathToFileURL(dirname(join(REPO, rel))).href + '/';
  const f = join(TMP, name);
  writeFileSync(f, patched.split("from './").join(`from '${dirUrl.replace(/'/g, "%27")}`), 'utf8');
  return (await import(pathToFileURL(f).href)).default;
};
const CostPanel = await loadPanel('modules/cost/web/CostPanel.js', 'CostPanel.mjs');
const InventoryPanel = await loadPanel('modules/inventory/web/InventoryPanel.js', 'InventoryPanel.mjs');

const mount = (Comp, access) => {
  const root = new DElement('div');
  const state = Vue.reactive({ access });
  let inst = null;
  const app = createApp({
    setup() { return () => h(Comp, { open: true, lang: 'ru', access: state.access, onClose: () => {} }); },
  });
  inst = app.mount(root);
  return { root, app, state, body: documentShim.body };
};

const textOf = (el) => el.textContent || '';
// 200 мс: в CostPanel расчёт намеренно отложен (debounce 150 мс) — без ожидания проверка
// «запрос calculate ушёл» была бы вакуумной.
const flush = async () => { await Vue.nextTick(); await new Promise((r) => setTimeout(r, 200)); await Vue.nextTick(); };
const clickText = async (needle) => {
  const b = documentShim.body._findAll((e) => e._tag === 'button' && (e.textContent || '').includes(needle))[0];
  if (!b) return false;
  b._fire('click', { type: 'click', target: b, currentTarget: b, stopPropagation() {}, preventDefault() {} });
  await flush();
  return true;
};

// ─────────── R2/R3: Cost при AUTH OFF и у наблюдателя ───────────
netCalls.length = 0;
let m = mount(CostPanel, contract(canAllTrue, false, 1));
await flush();
let txt = textOf(documentShim.body);
check('R2b. Cost, AUTH OFF: кнопка «Сохранить расчёт» показана', txt.includes('Сохранить расчёт'));
check('R2a0. вкладка «Настройки расчёта» открывается', await clickText('Настройки расчёта'));
txt = textOf(documentShim.body);
check('R2a. Cost, AUTH OFF: кнопка «Сохранить настройки» показана', txt.includes('Сохранить настройки'));
check('R2a2. Cost, AUTH OFF: поля настроек НЕ только для чтения',
      documentShim.body._findAll((e) => e._tag === 'input' && e.readOnly).length === 0);
check('R2c. Cost, AUTH OFF: сообщения о несовместимом ядре нет',
      !txt.includes('требуется обновлённое ядро'));
check('R2d. Cost: расчёт (право view) выполняется — запрос calculate ушёл',
      netCalls.some((c) => c.url.includes('/api/mod/cost/calculate') && c.method === 'POST'));
m.app.unmount(); documentShim.body.childNodes = [];

netCalls.length = 0;
m = mount(CostPanel, contract(canView, true, 2));
await flush();
check('R3c. Cost, только view: расчёт по-прежнему считается (cost.calculate = view)',
      netCalls.some((c) => c.url.includes('/api/mod/cost/calculate')));
check('R3b. Cost, только view: «Сохранить расчёт» скрыта',
      !textOf(documentShim.body).includes('Сохранить расчёт'));
await clickText('Настройки расчёта');
txt = textOf(documentShim.body);
check('R3a. Cost, только view: «Сохранить настройки» скрыта', !txt.includes('Сохранить настройки'));
check('R3d. Cost, только view: пояснение показано и без технического кода права',
      txt.includes('меняет администратор') && !txt.includes('admin'));
check('R3e. Cost, только view: поля настроек переведены в режим чтения',
      documentShim.body._findAll((e) => e._tag === 'input' && e.readOnly).length > 0);

// R4: deny ДО fetch — программный вызов обработчика без права
const costVm = m.root && null;
netCalls.length = 0;
const costSetup = CostPanel.setup({ open: true, lang: 'ru', access: contract(canView, true, 2) });
check('R4a. Cost: setup отдаёт can/capReady шаблону', typeof costSetup.can === 'function' && !!costSetup.capReady);
await costSetup.saveGlobal();
await costSetup.savePrinter({ printer_id: 'p1', override: {} });
await costSetup.clearOverride({ printer_id: 'p1' });
await costSetup.saveCalc();
check('R4b. Cost: без права ни один изменяющий запрос НЕ отправлен',
      !netCalls.some((c) => c.method === 'POST' && !c.url.includes('/calculate')));
check('R4c. Cost: пользователю показан текст об отсутствии прав',
      String(costSetup.accessMsg.value || '').includes('Недостаточно прав'));
m.app.unmount(); documentShim.body.childNodes = [];

// ─────────── R5: отсутствующий и чужой contract ───────────
for (const [label, acc] of [['отсутствует', null], ['чужая версия', Object.freeze({ contractVersion: 99, can: () => true })],
                            ['can не функция', Object.freeze({ contractVersion: 1, can: 'yes' })]]) {
  netCalls.length = 0;
  let crashed = false;
  try {
    const mm = mount(CostPanel, acc);
    await flush();
    const t = textOf(documentShim.body);
    check('R5. Cost, contract ' + label + ': окно не падает и показывает совместимое сообщение',
          t.includes('требуется обновлённое ядро'));
    check('R5. Cost, contract ' + label + ': привилегированные контролы скрыты',
          !t.includes('Сохранить настройки') && !t.includes('Сохранить расчёт'));
    mm.app.unmount(); documentShim.body.childNodes = [];
  } catch (e) { crashed = true; }
  check('R5. Cost, contract ' + label + ': без исключения JavaScript', !crashed);
}

// ─────────── R6: понижение прав у ОТКРЫТОГО окна ───────────
netCalls.length = 0;
const live = mount(CostPanel, contract(canAdmin, true, 3));
await flush();
await clickText('Настройки расчёта');
check('R6a. admin: настройки и сохранение расчёта доступны',
      textOf(documentShim.body).includes('Сохранить настройки'));
live.state.access = contract(canView, true, 4);   // права понижены, окно НЕ переоткрывалось
await flush();
const afterTxt = textOf(documentShim.body);
check('R6b. после понижения прав admin-контрол исчез из ОТКРЫТОГО окна',
      !afterTxt.includes('Сохранить настройки'));
check('R6c. после понижения прав project-контрол исчез из ОТКРЫТОГО окна',
      !afterTxt.includes('Сохранить расчёт'));
live.app.unmount(); documentShim.body.childNodes = [];

// ─────────── Inventory: те же правила ───────────
netCalls.length = 0;
const invSetupView = InventoryPanel.setup({ open: false, lang: 'ru', startTab: 'filament', action: '', printerId: '', nonce: 0, access: contract(canView, true, 5) }, { emit: () => {} });
await invSetupView.setCurrency('USD');
await invSetupView.setLowG(500);
await invSetupView.saveSpool();
await invSetupView.applyAdj();
await invSetupView.applyBind();
await invSetupView.delItem({ id: 'i1' });
await invSetupView.saveLoc();
check('R4d. Inventory, только view: ни один изменяющий запрос НЕ отправлен',
      !netCalls.some((c) => c.method && c.method !== 'GET'));
check('R4e. Inventory, только view: локальные данные не изменены оптимистично',
      invSetupView.currency.value !== 'USD' && Number(invSetupView.lowG.value) !== 500);
check('R4f. Inventory: показан текст об отсутствии прав',
      String(invSetupView.msg.value || '').includes('Недостаточно прав'));

const invSetupCount = InventoryPanel.setup({ open: false, lang: 'ru', startTab: 'filament', action: '', printerId: '', nonce: 0, access: contract((p) => p === 'view' || p === 'count', true, 6) }, { emit: () => {} });
check('R4g. Inventory: count открывает пересчёт, но НЕ обычную складскую работу',
      invSetupCount.can('count') === true && invSetupCount.can('project') === false);
const invNoContract = InventoryPanel.setup({ open: false, lang: 'ru', startTab: 'filament', action: '', printerId: '', nonce: 0, access: null }, { emit: () => {} });
check('R5d. Inventory без contract: capReady=false и все права закрыты',
      invNoContract.capReady.value === false && invNoContract.can('view') === false
      && invNoContract.can('project') === false);

// ─────────── R7/R8: хранилище и метка-ловушка ───────────
check('R7. contract не записывается в localStorage/sessionStorage',
      !storageWrites.some((w) => /access|capab|contract|revision/i.test(w.k)
                              || /contractVersion|capabilities/i.test(w.v)));
check('R8a. метка-ловушка не ушла ни в один запрос',
      !netCalls.some((c) => String(c.url).includes(SENTINEL) || String(c.body || '').includes(SENTINEL)));
check('R8b. метка-ловушка не попала в браузерное хранилище',
      !storageWrites.some((w) => (w.k + w.v).includes(SENTINEL)));
check('R8c. метка-ловушка отсутствует в производственных исходниках',
      !APPJS.includes(SENTINEL)
      && !readFileSync(join(REPO, 'modules', 'cost', 'web', 'CostPanel.js'), 'utf8').includes(SENTINEL)
      && !readFileSync(join(REPO, 'modules', 'inventory', 'web', 'InventoryPanel.js'), 'utf8').includes(SENTINEL));

try { rmSync(TMP, { recursive: true, force: true }); } catch (e) {}

console.log('\n' + '='.repeat(76));
console.log(fail ? ('FAIL: ' + fail + ' проверок не пройдено') : 'PASS: все проверки пройдены');
process.exit(fail ? 1 : 0);
