// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// РЕАЛЬНЫЙ runtime-тест секций «Склад → В работе» — inventory 1.7.10.
// Fixture повторяет реальный скриншот фермы: Bambu с одним AMS, Bambu с двумя unit, синтетический
// AMS HT (index 512 / unit 128 / tray 0), внешние Bambu, MT500 на Klipper, полностью пустые принтеры.
// Часть S* — НАСТОЯЩИЙ вендорный Vue на самодельном DOM (монтируется ДОСЛОВНЫЙ блок таблицы,
// ИЗВЛЕЧЁННЫЙ из shipped InventoryPanel.js): классификация по трём секциям, счётчики, Klipper-иконка
// ПО ТИПУ (не по имени), локальный номер лотка «1» вместо «513» при bind с глобальным index 512,
// A1/A2/AMS HT, тумблер пустых, порядок строк, sticky-шапка первым элементом.
// Часть L* — РЕАЛЬНЫЙ layout-движок (установленный Edge/Chromium, headless): страница с НАСТОЯЩИМ
// Vue (file://vendor) + реальными CSS (правила ядра из web/app.css + CARD_CSS модуля) рендерится в
// dark/light на 1366x768 и 1750x880; измеряются переполнение, выравнивание колонок с шапкой, перенос
// unit-групп, просвет над sticky-шапкой; PNG-скриншоты пишутся во временную папку прогона.
// Alpha 2.835: L* переведены со сломанного `--dump-dom` на общий CDP-мост (_edge_cdp_lib.mjs) —
// стенд, четыре сценария и все пороги сохранены дословно; недоступный браузер или не вернувшийся
// результат теперь КРАСНЫЕ, а не пропуск.
// Запуск: node tools/test_inventory_sections_runtime.mjs   (0 = пройдено)
import { readFileSync, writeFileSync, mkdirSync } from 'fs';
import { tmpdir } from 'os';
import { fileURLToPath, pathToFileURL } from 'url';
import { dirname, join } from 'path';
import { findEngine, measure, browserProblems } from './_edge_cdp_lib.mjs';

const REPO = dirname(dirname(fileURLToPath(import.meta.url)));
const PANEL = readFileSync(join(REPO, 'modules', 'inventory', 'web', 'InventoryPanel.js'), 'utf8');
const APP_CSS = readFileSync(join(REPO, 'web', 'app.css'), 'utf8');
let fail = 0;
const check = (name, cond) => { console.log((cond ? 'PASS' : 'FAIL') + ' — ' + name); if (!cond) fail++; };

// ─────────── минимальный DOM (harness как в других runtime-тестах) ───────────
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
  constructor(tag) { super(1); this._tag = tag; this.tagName = String(tag).toUpperCase(); this.namespaceURI = 'http://www.w3.org/1999/xhtml'; this.attributes = {}; this._listeners = {}; this.style = {}; this._cls = ''; this._disabled = false; }
  setAttribute(k, v) { this.attributes[k] = String(v); if (k === 'class') this._cls = String(v); }
  removeAttribute(k) { delete this.attributes[k]; if (k === 'class') this._cls = ''; }
  getAttribute(k) { return k in this.attributes ? this.attributes[k] : null; }
  hasAttribute(k) { return k in this.attributes; }
  get className() { return this._cls; }
  set className(v) { this._cls = v == null ? '' : String(v); this.attributes['class'] = this._cls; }
  get disabled() { return this._disabled; }
  set disabled(v) { this._disabled = !!v; }
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

const Vue = await import(pathToFileURL(join(REPO, 'web', 'vendor', 'vue.esm-browser.js')).href);
const { createApp, ref, reactive, computed, nextTick } = Vue;

// ─────────── ДОСЛОВНЫЙ блок таблицы из shipped-панели ───────────
const extractTable = () => {
  const key = '<div v-else class="fm-inv-ptable">';
  const s = PANEL.indexOf(key);
  const openEnd = PANEL.indexOf('>', s) + 1;
  const re = /<div\b|<\/div>/g; re.lastIndex = openEnd;
  let m, d = 1, close = -1;
  while ((m = re.exec(PANEL))) { d += (m[0] === '</div>') ? -1 : 1; if (d === 0) { close = m.index; break; } }
  return PANEL.slice(s, close + 6).replace('v-else class="fm-inv-ptable"', 'class="fm-inv-ptable"');
};
const TABLE_BLOCK = extractTable();
check('S0. дословный блок таблицы извлечён из shipped-панели (секции/группы/иконка внутри)',
  TABLE_BLOCK.includes('workSections') && TABLE_BLOCK.includes('fm-inv-punit2') && TABLE_BLOCK.includes('klipperSvg') && TABLE_BLOCK.includes('slotLocalN(sl)'));

// ─────────── fixture «как на скриншоте» ───────────
const SP = (id, mat, g, t) => ({ id, material: mat, color_name: 'Зелёный', color_hex: '00aa55', weight_remaining_g: g, weight_total_g: t || 1000, vendor_name: 'GEHR' });
const OVERVIEW = { printers: [
  // H1: Bambu, ДВА unit — обычный A1 (4×PETG) + AMS HT (index 512 / unit 128 / tray 0)
  { printer_id: 'PRN_H1', printer_name: 'H1', has_ams: true, slots: [
    { index: 0, unit: 0, tray: 0, spool: SP('h1a', 'PETG', 1000) }, { index: 1, unit: 0, tray: 1, spool: SP('h1b', 'PETG', 1000) },
    { index: 2, unit: 0, tray: 2, spool: SP('h1c', 'PETG', 1000) }, { index: 3, unit: 0, tray: 3, spool: SP('h1d', 'PETG', 1000) },
    { index: 512, unit: 128, tray: 0, spool: SP('h1e', 'PETG', 1000) } ] },
  // X5: Bambu, один AMS, частично занят
  { printer_id: 'PRN_X5', printer_name: 'X5', has_ams: true, slots: [
    { index: 0, unit: 0, tray: 0, spool: SP('x5a', 'PETG', 800) }, { index: 1, unit: 0, tray: 1 }, { index: 2, unit: 0, tray: 2 }, { index: 3, unit: 0, tray: 3 } ] },
  // HTE: Bambu, ПУСТОЙ AMS HT (для проверки bind по глобальному 512 при локальном «1») + занятая внешняя,
  //      чтобы принтер не был полностью пустым и остался в секции AMS
  { printer_id: 'PRN_HTE', printer_name: 'HTE', has_ams: true, slots: [
    { index: 0, external: true, spool: SP('hte-ext', 'PETG', 500) },
    { index: 512, unit: 128, tray: 0 } ] },
  // X9: Bambu, внешняя занята (без AMS)
  { printer_id: 'PRN_X9', printer_name: 'X9', has_ams: false, slots: [ { index: 0, external: true, spool: SP('x9a', 'PETG', 4644, 5000) } ] },
  // MT500: KLIPPER (тип из /api/printers!), внешняя занята; модель задана — но для Klipper cover НЕ грузим
  { printer_id: 'PRN_MT', printer_name: 'MT500', has_ams: false, slots: [ { index: 0, external: true, spool: SP('mta', 'PETG', 5000, 5000) } ] },
  // VORON: второй Klipper с ДРУГИМ именем — доказательство «не по имени»
  { printer_id: 'PRN_VO', printer_name: 'Voron', has_ams: false, slots: [ { index: 0, external: true, spool: SP('voa', 'PLA', 900) } ] },
  // Пустые: X2 (внешняя без катушки), X10 (AMS пустой)
  { printer_id: 'PRN_X2', printer_name: 'X2', has_ams: false, slots: [ { index: 0, external: true } ] },
  { printer_id: 'PRN_X10', printer_name: 'X10', has_ams: true, slots: [ { index: 0, unit: 0, tray: 0 }, { index: 1, unit: 0, tray: 1 }, { index: 2, unit: 0, tray: 2 }, { index: 3, unit: 0, tray: 3 } ] },
] };
const MODELS = { PRN_H1: 'Bambu Lab H2D', PRN_X5: 'Bambu Lab X1 Carbon', PRN_HTE: 'Bambu Lab H2S', PRN_X9: 'Bambu Lab P1S', PRN_MT: 'MT500', PRN_VO: 'Voron 2.4 300', PRN_X2: 'Bambu Lab P1P', PRN_X10: 'Bambu Lab X1 Carbon' };
const TYPES = { PRN_H1: 'bambu', PRN_X5: 'bambu', PRN_HTE: 'bambu', PRN_X9: 'bambu', PRN_MT: 'klipper', PRN_VO: 'klipper', PRN_X2: 'bambu', PRN_X10: 'bambu' };
// 1.7.15: cover_url — как отдаёт ядро (GET /api/printers, allowlisted registry). MT500 — custom без файла ('').
// PRN_VO (Voron) — klipper С обложкой: доказывает, что type=klipper больше НЕ блокирует cover.
const COVERS = { PRN_H1: '/covers/Bambu%20Lab%20H2D_cover.png', PRN_X5: '/covers/Bambu%20Lab%20X1%20Carbon_cover.png', PRN_HTE: '/covers/Bambu%20Lab%20H2S_cover.png', PRN_X9: '/covers/Bambu%20Lab%20P1S_cover.png', PRN_MT: '', PRN_VO: '/covers/Voron%202.4%20300_cover.png', PRN_X2: '/covers/Bambu%20Lab%20P1P_cover.png', PRN_X10: '/covers/Bambu%20Lab%20X1%20Carbon_cover.png' };
const KL_SVG = '<svg viewBox="0 0 10 10" class="owner-printer-icon"><path d="M1 1h8v8H1z"/></svg>';   // стаб owner-иконки

// ─────────── фабрика: ДОСЛОВНО shipped-логика 1.7.10 (как в workmode-тесте) ───────────
const makeWork = (overview, opts = {}) => {
  const state = { loading: ref(false), ams: ref(overview), q: ref(''), showEmptyPrinters: ref(true),
    fcMap: ref({}), printerModelById: ref(opts.models || {}), printerTypeById: ref(opts.types || {}),
    printerCoverById: ref(opts.covers || {}),
    klipperSvg: ref(opts.klipperSvg || ''), calls: { bind: [], click: [], menu: [] } };
  const component = {
    setup() {
      const L = (ru) => ru;
      const { loading, ams, q, showEmptyPrinters, fcMap, printerModelById, printerTypeById, printerCoverById, klipperSvg, calls } = state;
      const spoolById = computed(() => { const m = {}; for (const p of (ams.value.printers || [])) for (const sl of (p.slots || [])) if (sl.spool) m[sl.spool.id] = sl.spool; return m; });
      const slotFull = (sl) => (sl && sl.spool && spoolById.value[sl.spool.id]) || null;
      const slotLow = (sl) => { const sp = sl && sl.spool; return !!(sp && (+sp.weight_remaining_g || 0) <= 100); };
      const pct = (s) => { const t = +s.weight_total_g || 0; return t <= 0 ? 0 : Math.max(0, Math.min(100, Math.round((+s.weight_remaining_g || 0) / t * 100))); };
      const barColor = () => '#888';
      const printerBoundG = (p) => { let g = 0; for (const sl of (p.slots || [])) if (sl && sl.spool) g += (+sl.spool.weight_remaining_g || 0); return Math.round(g); };
      const printerBoundN = (p) => (p.slots || []).filter((sl) => sl && sl.spool).length;
      const slotUnits = (p) => { const order = []; const map = {}; for (const sl of (p.slots || [])) { const u = (sl.unit == null ? 0 : sl.unit); if (!(u in map)) { map[u] = []; order.push(u); } map[u].push(sl); } return order.map((u, i) => ({ unit: u, n: i + 1, slots: map[u] })); };
      const coverBroken = reactive({});
      const coverUrl = (model) => '/covers/' + encodeURIComponent(String(model) + '_cover.png');
      const printerOcc = (p) => (p.slots || []).some((sl) => sl && sl.spool);
      const _printerHasLow = (p) => (p.slots || []).some((sl) => slotLow(sl));
      const _amsSearched = computed(() => (ams.value.printers || []).slice());
      const workPrinters = computed(() => {
        const rank = (p) => (_printerHasLow(p) ? 0 : (printerOcc(p) ? 1 : 2));
        let arr = _amsSearched.value;
        if (!showEmptyPrinters.value) arr = arr.filter(printerOcc);
        return arr.map((p, i) => ({ p, i })).sort((a, b) => (rank(a.p) - rank(b.p)) || (a.i - b.i)).map((x) => x.p);
      });
      const workEmptyCount = computed(() => _amsSearched.value.filter((p) => !printerOcc(p)).length);
      const workExternal = (p) => { for (const sl of (p.slots || [])) if (sl.external) return sl; return null; };
      const workAmsUnits = (p) => slotUnits({ slots: (p.slots || []).filter((sl) => !sl.external) });
      const workDaysLeft = () => null;
      const workStatus = (p) => { if (!printerOcc(p)) return { k: 'empty', t: L('Пусто') }; if (_printerHasLow(p)) return { k: 'low', t: L('Мало остатка') }; return { k: 'ok', t: L('Готов') }; };
      const workRows = computed(() => workPrinters.value.map((p) => ({
        p, ext: workExternal(p), units: workAmsUnits(p), unconfirmed: (p.slots||[]).filter((sl)=>sl.unconfirmed&&sl.spool), remainG: printerBoundG(p), boundN: printerBoundN(p),
        days: workDaysLeft(p), st: workStatus(p), model: printerModelById.value[p.printer_id] || '',
        cover: printerCoverById.value[p.printer_id] || '',
        kl: (printerTypeById.value[p.printer_id] || '') === 'klipper',
        hasFree: (p.slots || []).some((sl) => !sl.spool && !sl.offline),
      })));
      // ==== ДОСЛОВНО shipped 1.7.10 ====
      const workSections = computed(() => {
        const ams2 = [], ext = [], empty = [];
        for (const r of workRows.value) {
          if (r.st.k === 'empty') { empty.push(r); continue; }
          (r.units.length ? ams2 : ext).push(r);
        }
        const busy = ams2.reduce((n, r) => n + r.units.reduce((m, u) => m + u.slots.filter((s) => s.spool).length, 0), 0);
        const spools = ext.reduce((n, r) => n + (r.boundN || 0), 0);
        return [
          { key: 'ams', title: L('Системы AMS', 'AMS systems'), count: ams2.length + ' ' + L('принт.', 'prn.') + ' · ' + busy + ' ' + L('занятых слотов', 'busy slots'), rows: ams2 },
          { key: 'ext', title: L('Внешняя подача', 'External feed'), count: ext.length + ' ' + L('принт.', 'prn.') + ' · ' + spools + ' ' + L('кат.', 'spools'), rows: ext },
          { key: 'empty', title: L('Без катушки', 'No spool'), count: empty.length + ' ' + L('принт.', 'prn.'), rows: empty },
        ].filter((s) => s.rows.length);
      });
      const unitLabel = (u) => ((u.slots.length === 1 && !u.slots[0].offline && u.slots[0].unit != null) ? 'AMS HT' : ('A' + u.n));
      const slotLocalN = (sl) => { if (!sl) return ''; if (sl.tray != null) return Number(sl.tray) + 1; const i = Number(sl.index) || 0; if (sl.unit != null) return i - Number(sl.unit) * 4 + 1; return (i % 4) + 1; };
      const workSlotTitle = () => '';
      const onSlotClick = (sl) => calls.click.push(sl);
      const onSlotMenu = (e, sl) => calls.menu.push(sl);
      const openBindFor = (p, idx) => calls.bind.push({ printer_id: p.printer_id, idx });
      const workRowMenu = () => {};
      const spoolSvg = () => '';
      return { L, loading, ams, q, showEmptyPrinters, fcMap, printerModelById, printerTypeById, klipperSvg, coverBroken, coverUrl, workRows, workSections, unitLabel, slotLocalN, workEmptyCount, workSlotTitle, matCheckView: () => null, workRowMenu, slotFull, slotLow, onSlotClick, onSlotMenu, openBindFor, spoolSvg, barColor, pct, calls };
    },
    template: '<div class="wrap">' + TABLE_BLOCK + '</div>',
    compilerOptions: { decodeEntities: (x) => x },
  };
  return { component, state };
};
const mount = (component) => { const app = createApp(component); app.config.warnHandler = () => {}; app.component('svg-icon', { props: { name: { type: String, default: '' } }, template: '<i class="ico" :data-name="name"></i>' }); const root = new DElement('div'); const vm = app.mount(root); return { root, vm }; };
const byCls = (root, c) => root._findAll((e) => (' ' + e.className + ' ').includes(' ' + c + ' '));
const hasCls = (e, c) => (' ' + e.className + ' ').includes(' ' + c + ' ');
const rowName = (r) => (byCls(r, 'fm-inv-pname2')[0] || { textContent: '' }).textContent.trim();
const fireEv = (el, type) => el._fire(type, { type, target: el, stopPropagation() {}, preventDefault() {} });

const { root, vm } = mount(makeWork(OVERVIEW, { models: MODELS, types: TYPES, covers: COVERS, klipperSvg: KL_SVG }).component);
await nextTick();
const S = vm.$.setupState;

// ═══ S1: три секции в верном порядке, шапка — первый элемент таблицы (sticky не сломан) ═══
{
  const table = byCls(root, 'fm-inv-ptable')[0];
  const secs = byCls(root, 'fm-inv-psec');
  const titles = secs.map((s) => (byCls(s, 'fm-inv-psec-t')[0] || { textContent: '' }).textContent.trim());
  const firstChild = table.childNodes.filter((c) => c.nodeType === 1)[0];
  check('S1. секции по порядку: «Системы AMS» → «Внешняя подача» → «Без катушки»; sticky-шапка — ПЕРВЫЙ элемент таблицы (вне секций)',
    secs.length === 3 && titles.join(' | ') === 'Системы AMS | Внешняя подача | Без катушки'
    && hasCls(firstChild, 'fm-inv-prow-h'));
}

// ═══ S2: классификация строк и счётчики секций ═══
{
  const secs = byCls(root, 'fm-inv-psec');
  const namesIn = (s) => byCls(s, 'fm-inv-prow').map(rowName);
  const cnt = (s) => (byCls(s, 'fm-inv-psec-c')[0] || { textContent: '' }).textContent.trim();
  // AMS: H1 (4+1 занятых), X5 (1), HTE (external занята + пустой HT-unit -> секция AMS по живому unit)
  check('S2a. «Системы AMS» = H1, X5, HTE; счётчик «3 принт. · 6 занятых слотов» (5 H1 + 1 X5; пустой HT HTE не считается)',
    namesIn(secs[0]).join(',') === 'H1,X5,HTE' && cnt(secs[0]) === '3 принт. · 6 занятых слотов');
  check('S2b. «Внешняя подача» = X9, MT500, Voron (без живого AMS, катушка привязана); счётчик «3 принт. · 3 кат.»',
    namesIn(secs[1]).join(',') === 'X9,MT500,Voron' && cnt(secs[1]) === '3 принт. · 3 кат.');
  check('S2c. «Без катушки» = X2, X10 (полностью пустые, тумблер ВКЛ); счётчик «2 принт.»',
    namesIn(secs[2]).join(',') === 'X2,X10' && cnt(secs[2]) === '2 принт.');
}

// ═══ S3: cover_url приоритетнее type — klipper С обложкой показывает PNG; без обложки → силуэт Klipper (1.7.15) ═══
{
  const rowOf = (n) => byCls(root, 'fm-inv-prow').find((r) => rowName(r) === n);
  const mt = rowOf('MT500'), vo = rowOf('Voron'), x9 = rowOf('X9');
  const klBox = (r) => byCls(r, 'fm-inv-pimg-kl');
  const imgs = (r) => r._findAll((e) => e._tag === 'img');
  check('S3a. MT500 (type=klipper, cover_url="") → owner-силуэт Klipper (.fm-inv-pimg.kl + .fm-inv-pimg-kl), обложки нет (custom без файла)',
    klBox(mt).length === 1 && imgs(mt).length === 0 && hasCls(byCls(mt, 'fm-inv-pimg')[0], 'kl'));
  check('S3b. Voron (type=klipper, НО cover_url задан) → показывает СВОЮ обложку <img>, а НЕ силуэт (тип больше НЕ блокирует cover); плашка без kl-тона',
    klBox(vo).length === 0 && imgs(vo).length === 1 && imgs(vo)[0].getAttribute('src') === '/covers/Voron%202.4%20300_cover.png' && !hasCls(byCls(vo, 'fm-inv-pimg')[0], 'kl'));
  check('S3c. Bambu X9: обычный cover <img /covers/Bambu%20Lab%20P1S_cover.png>, klipper-ветки нет',
    klBox(x9).length === 0 && imgs(x9).length === 1 && imgs(x9)[0].getAttribute('src') === '/covers/Bambu%20Lab%20P1S_cover.png');
}

// ═══ S4: AMS HT — заголовок «AMS HT», ЛОКАЛЬНЫЙ номер «1» (не 513), bind шлёт глобальный 512 ═══
{
  const rowOf = (n) => byCls(root, 'fm-inv-prow').find((r) => rowName(r) === n);
  const h1 = rowOf('H1'), hte = rowOf('HTE');
  const h1units = byCls(h1, 'fm-inv-punit2');
  const h1labels = h1units.map((u) => (byCls(u, 'fm-inv-punit2-l')[0] || { textContent: '' }).textContent.trim());
  const htCell = byCls(h1units[1], 'fm-inv-pslot')[0];
  const htNum = (byCls(htCell, 'fm-inv-pslot-n')[0] || { textContent: '' }).textContent.trim();
  check('S4a. H1: группы «A1» (4 слота) + «AMS HT» (1 слот); номер в HT-ячейке «1», НЕ «513»',
    h1labels.join(',') === 'A1,AMS HT'
    && byCls(h1units[0], 'fm-inv-pslot').length === 4 && byCls(h1units[1], 'fm-inv-pslot').length === 1
    && htNum === '1' && !h1.textContent.includes('513'));
  const hteUnits = byCls(hte, 'fm-inv-punit2');
  const hteCell = byCls(hteUnits[0], 'fm-inv-pslot')[0];
  const hteNum = (byCls(hteCell, 'fm-inv-pslot-n')[0] || { textContent: '' }).textContent.trim();
  fireEv(hteCell, 'click'); await nextTick();
  const b = S.calls.bind[S.calls.bind.length - 1];
  check('S4b. пустой HT-слот HTE: локальный номер «1», клик -> openBindFor(HTE, 512) — bind получает НАСТОЯЩИЙ глобальный index',
    hteNum === '1' && b && b.printer_id === 'PRN_HTE' && b.idx === 512);
  check('S4c. нигде в таблице нет глобальных номеров «513»/«512» на ячейках', !root.textContent.includes('513'));
}

// ═══ S5: локальные номера у обычного unit прежние (1..4), клик по занятому — история ═══
{
  const rowOf = (n) => byCls(root, 'fm-inv-prow').find((r) => rowName(r) === n);
  const x5 = rowOf('X5');
  const nums = byCls(x5, 'fm-inv-pslot').map((c) => (byCls(c, 'fm-inv-pslot-n')[0] || { textContent: '' }).textContent.trim());
  const occ = byCls(x5, 'fm-inv-pslot').find((c) => !hasCls(c, 'add'));
  fireEv(occ, 'click'); await nextTick();
  check('S5. X5: номера слотов 1,2,3,4 (локальные); клик занятого -> onSlotClick (история)',
    nums.join(',') === '1,2,3,4' && S.calls.click.length === 1 && S.calls.click[0].spool.id === 'x5a');
}

// ═══ S6: тумблер «Показывать пустые» — секция «Без катушки» исчезает/возвращается целиком ═══
{
  S.showEmptyPrinters = false; await nextTick();
  const secsOff = byCls(root, 'fm-inv-psec');
  const titlesOff = secsOff.map((s) => (byCls(s, 'fm-inv-psec-t')[0] || { textContent: '' }).textContent.trim());
  S.showEmptyPrinters = true; await nextTick();
  const secsOn = byCls(root, 'fm-inv-psec');
  check('S6. тумблер OFF: секции «Без катушки» нет (2 секции), остальные целы; ON: снова 3 секции; workEmptyCount=2',
    secsOff.length === 2 && titlesOff.join('|') === 'Системы AMS|Внешняя подача'
    && secsOn.length === 3 && S.workEmptyCount === 2);
}

// ═══ L*: реальный layout-движок (Edge/Chromium headless): dark/light × 1366x768 / 1750x880 ═══
const ENGINE = findEngine();

const cssVar = (block, name) => { const m = new RegExp(name.replace(/[-]/g, '[-]') + ':\\s*([^;}]+)[;}]').exec(block); return m ? m[1].trim() : ''; };
// РОВНО блоки объявлений тем из app.css: {…} вокруг первого (тёмная :root) и второго (светлая тема)
// вхождения --fm-surface-raised — так light-переменные гарантированно берутся из светлого блока.
const _blockAround = (idx) => APP_CSS.slice(APP_CSS.lastIndexOf('{', idx) + 1, APP_CSS.indexOf('}', idx));
// именно ДЕКЛАРАЦИЯ (имя+двоеточие), а не использование var(--fm-surface-raised) в комментарии/правилах
const _dIdx = APP_CSS.indexOf('--fm-surface-raised:');
const _lIdx = APP_CSS.indexOf('--fm-surface-raised:', _dIdx + 10);
const darkRoot = _blockAround(_dIdx);
const lightRoot = _blockAround(_lIdx);
const VARS = (block, fallback) => ['--fm-surface-raised', '--fm-surface-card', '--fm-border-soft', '--fm-border-strong', '--fm-border', '--fm-text-primary', '--fm-text-secondary', '--fm-text-subtle', '--fm-accent-rgb', '--fm-black-rgb', '--fm-accent', '--fm-success', '--fm-danger']
  .map((v) => v + ':' + (cssVar(block, v) || cssVar(fallback, v) || '#888')).join(';');
const coreRule = (sel) => (new RegExp(sel.replace(/[.]/g, '\\.') + '\\{[^}]*\\}')).exec(APP_CSS)[0];
const CARD_CSS_TEXT = (() => { const i = PANEL.indexOf('const CARD_CSS = ['); const j = PANEL.indexOf("].join('\\n');", i); const arr = new Function('return ' + PANEL.slice(i + 'const CARD_CSS ='.length, j + 1))(); return arr.join('\n'); })();
// РЕАЛЬНАЯ owner-иконка Klipper проекта (svgAssets.printer из web/design/icons.js) — чтобы layout-скриншот
// показывал именно её (а не стаб). Извлекаем строковый литерал printer: '<svg…>' из файла иконок.
const ICONS_JS = readFileSync(join(REPO, 'web', 'design', 'icons.js'), 'utf8');
const REAL_KL_SVG = (() => { const a = ICONS_JS.indexOf("printer: '") + "printer: '".length; const b = ICONS_JS.indexOf("'", a); return ICONS_JS.slice(a, b); })();

check('L0. движок рендера для браузерных измерений найден (без него L-проверки невозможны)', !!ENGINE);
if (ENGINE) {
  const tmp = join(tmpdir(), 'fm-inv-sections-' + process.pid);
  mkdirSync(tmp, { recursive: true });
  // Снимки — во временную папку прогона (раньше _incoming/): рабочие каталоги проекта не трогаем.
  const shotsDir = join(tmp, 'shots');
  try { mkdirSync(shotsDir, { recursive: true }); } catch (e) {}
  const vueUrl = pathToFileURL(join(REPO, 'web', 'vendor', 'vue.esm-browser.js')).href;
  // Страница-стенд для реального движка: правила ядра (.fm-inv-panel/.fm-inv-body/.fm-inv-toolbar
  // из web/app.css) + CARD_CSS модуля + переменные темы; НАСТОЯЩИЙ Vue монтирует извлечённый TABLE_BLOCK.
  const buildPage = (theme) => {
    const setupSrc = `
const L = (ru) => ru;
const loading = ref(false); const ams = ref(OVERVIEW); const q = ref(''); const showEmptyPrinters = ref(true);
const fcMap = ref({}); const printerModelById = ref(MODELS); const printerTypeById = ref(TYPES); const klipperSvg = ref(KL);
const spoolById = computed(() => { const m = {}; for (const p of (ams.value.printers||[])) for (const sl of (p.slots||[])) if (sl.spool) m[sl.spool.id] = sl.spool; return m; });
const slotFull = (sl) => (sl && sl.spool && spoolById.value[sl.spool.id]) || null;
const slotLow = (sl) => false;
const pct = (s) => { const t = +s.weight_total_g || 0; return t<=0?0:Math.max(0,Math.min(100,Math.round((+s.weight_remaining_g||0)/t*100))); };
const barColor = () => 'var(--fm-success)';
const printerBoundG = (p) => { let g=0; for (const sl of (p.slots||[])) if (sl&&sl.spool) g += (+sl.spool.weight_remaining_g||0); return Math.round(g); };
const printerBoundN = (p) => (p.slots||[]).filter((sl)=>sl&&sl.spool).length;
const slotUnits = (p) => { const order=[]; const map={}; for (const sl of (p.slots||[])) { const u=(sl.unit==null?0:sl.unit); if(!(u in map)){map[u]=[];order.push(u);} map[u].push(sl); } return order.map((u,i)=>({unit:u,n:i+1,slots:map[u]})); };
const coverBroken = reactive({});
const coverUrl = (m) => 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="52" height="52"><rect width="52" height="52" fill="#456"/></svg>');
const printerOcc = (p) => (p.slots||[]).some((sl)=>sl&&sl.spool);
const _amsSearched = computed(() => (ams.value.printers||[]).slice());
const workPrinters = computed(() => { const rank=(p)=>(printerOcc(p)?1:2); let arr=_amsSearched.value; if(!showEmptyPrinters.value) arr=arr.filter(printerOcc); return arr.map((p,i)=>({p,i})).sort((a,b)=>(rank(a.p)-rank(b.p))||(a.i-b.i)).map((x)=>x.p); });
const workEmptyCount = computed(() => _amsSearched.value.filter((p)=>!printerOcc(p)).length);
const workExternal = (p) => { for (const sl of (p.slots||[])) if (sl.external) return sl; return null; };
const workAmsUnits = (p) => slotUnits({ slots: (p.slots||[]).filter((sl)=>!sl.external) });
const workStatus = (p) => (!printerOcc(p) ? {k:'empty',t:'Пусто'} : {k:'ok',t:'Готов'});
const workRows = computed(() => workPrinters.value.map((p) => ({ p, ext: workExternal(p), units: workAmsUnits(p), unconfirmed: (p.slots||[]).filter((sl)=>sl.unconfirmed&&sl.spool), remainG: printerBoundG(p), boundN: printerBoundN(p), days: null, st: workStatus(p), model: printerModelById.value[p.printer_id] || '', kl: (printerTypeById.value[p.printer_id] || '') === 'klipper', hasFree: (p.slots||[]).some((sl)=>!sl.spool&&!sl.offline) })));
const workSections = computed(() => { const a=[],e=[],em=[]; for (const r of workRows.value){ if(r.st.k==='empty'){em.push(r);continue;} (r.units.length?a:e).push(r);} const busy=a.reduce((n,r)=>n+r.units.reduce((m,u)=>m+u.slots.filter((s)=>s.spool).length,0),0); const sp=e.reduce((n,r)=>n+(r.boundN||0),0); return [ {key:'ams',title:'Системы AMS',count:a.length+' принт. · '+busy+' занятых слотов',rows:a}, {key:'ext',title:'Внешняя подача',count:e.length+' принт. · '+sp+' кат.',rows:e}, {key:'empty',title:'Без катушки',count:em.length+' принт.',rows:em} ].filter((s)=>s.rows.length); });
const unitLabel = (u) => ((u.slots.length === 1 && !u.slots[0].offline && u.slots[0].unit != null) ? 'AMS HT' : ('A' + u.n));
const slotLocalN = (sl) => { if(!sl) return ''; if (sl.tray != null) return Number(sl.tray)+1; const i=Number(sl.index)||0; if (sl.unit != null) return i - Number(sl.unit)*4 + 1; return (i%4)+1; };
const workSlotTitle = () => ''; const onSlotClick = () => {}; const onSlotMenu = () => {}; const openBindFor = () => {}; const workRowMenu = () => {};
const spoolSvg = () => '<svg viewBox="0 0 10 10" width="24" height="24"><circle cx="5" cy="5" r="4" fill="var(--fm-accent)"/></svg>';
return { L, loading, ams, q, showEmptyPrinters, fcMap, printerModelById, printerTypeById, klipperSvg, coverBroken, coverUrl, workRows, workSections, unitLabel, slotLocalN, workEmptyCount, workSlotTitle, matCheckView: () => null, workRowMenu, slotFull, slotLow, onSlotClick, onSlotMenu, openBindFor, spoolSvg, barColor, pct };`;
    return `<!doctype html><html><head><meta charset="utf-8"><style>
:root{${theme === 'dark' ? VARS(darkRoot, darkRoot) : VARS(lightRoot, darkRoot)}}
html,body{margin:0;background:${theme === 'dark' ? '#141416' : '#eef1f4'};font:13px system-ui}
${coreRule('.fm-inv-panel')}
${coreRule('.fm-inv-body')}
${coreRule('.fm-inv-toolbar')}
${CARD_CSS_TEXT}
.fm-inv-panel{margin:10px auto;height:calc(100vh - 20px)}
#__res{position:fixed;left:0;bottom:0;font:11px monospace;background:rgba(0,0,0,.85);color:#0f0;z-index:99;white-space:pre;max-width:100vw;overflow:hidden}
</style></head><body>
<div class="fm-inv-panel"><div class="fm-inv-body" id="sc"><div class="fm-inv-tabpane"><div id="app"></div></div></div></div>
<pre id="__res"></pre>
<script type="module">
import { createApp, ref, reactive, computed } from '${vueUrl}';
const OVERVIEW = ${JSON.stringify(OVERVIEW)};
const MODELS = ${JSON.stringify(MODELS)};
const TYPES = ${JSON.stringify(TYPES)};
const KL = ${JSON.stringify(REAL_KL_SVG)};
const app = createApp({ setup() { ${setupSrc} }, template: ${JSON.stringify('<div>' + TABLE_BLOCK + '</div>')} });
app.component('svg-icon', { props: { name: String }, template: '<i style="display:inline-block;width:26px;height:26px;background:currentColor;opacity:.4;border-radius:4px"></i>' });
app.mount('#app');
requestAnimationFrame(() => requestAnimationFrame(() => {
  const sc = document.getElementById('sc');
  const hdr = document.querySelector('.fm-inv-prow-h');
  const rows = [...document.querySelectorAll('.fm-inv-prow')].filter((r) => r !== hdr);
  const secs = [...document.querySelectorAll('.fm-inv-psec')];
  const units = [...document.querySelectorAll('.fm-inv-punit2')];
  // выравнивание колонок: левый край первой ячейки строки vs шапки
  const gcol = (el) => [...el.children].map((c) => Math.round(c.getBoundingClientRect().left));
  const hcols = gcol(hdr);
  const rcols = gcol(rows[0]);
  const colDiff = Math.max(...hcols.slice(0, 3).map((x, i) => Math.abs(x - rcols[i])));
  // переполнение по горизонтали
  const overflowX = sc.scrollWidth - sc.clientWidth;
  // sticky-просвет после прокрутки
  sc.scrollTop = 300;
  const gap = hdr.getBoundingClientRect().top - sc.getBoundingClientRect().top;
  sc.scrollTop = 0;
  // перенос unit-групп: группы не выходят за правый край своей колонки-контейнера
  const amsOk = units.every((u) => { const r = u.getBoundingClientRect(); const cell = u.closest('.fm-inv-pams').getBoundingClientRect(); return r.right <= cell.right + 1 && r.left >= cell.left - 1; });
  // наложения: заголовок секции не перекрыт первой строкой
  const secHeadOk = secs.every((s) => { const h = s.querySelector('.fm-inv-psec-h').getBoundingClientRect(); const fr = s.querySelector('.fm-inv-prow'); return !fr || fr.getBoundingClientRect().top >= h.bottom - 0.5; });
  const res = { w: innerWidth, h: innerHeight, theme: ${JSON.stringify('__THEME__')}, rows: rows.length, secs: secs.length, units: units.length,
    colDiff, overflowX, stickyGap: +gap.toFixed(1), amsOk, secHeadOk,
    ht1: (document.querySelector('.fm-inv-punit2-l') || {}).textContent || '', has513: document.querySelector('.fm-inv-ptable').textContent.includes('5' + '13') };
  document.getElementById('__res').textContent = '@@RES@@' + JSON.stringify(res) + '@@END@@';
  document.title = 'ready';
}));
</scr` + `ipt></body></html>`;
  };
  // Мост сам ставит --allow-file-access-from-files: страница и vendored Vue оба file:// (ES-module
  // import между file:// иначе блокируется CORS'ом origin=null). Только локальные файлы репозитория.
  const run = async (page, w, h, shot) => {
    try {
      return { out: await measure({ url: pathToFileURL(page).href, width: w, height: h, engine: ENGINE, shot }), why: '' };
    } catch (e) { return { out: null, why: String((e && e.message) || e) }; }
  };
  const CASES = [['dark', 1366, 768], ['dark', 1750, 880], ['light', 1366, 768], ['light', 1750, 880]];
  let allOk = true, ran = 0;
  for (const [theme, w, h] of CASES) {
    const pg = join(tmp, 'sec-' + theme + '.html');
    writeFileSync(pg, buildPage(theme).replace('"__THEME__"', JSON.stringify(theme)), 'utf8');
    const shot = join(shotsDir, `inv_1710_${theme}_${w}x${h}.png`);
    const { out, why } = await run(pg, w, h, shot);
    if (!out) { check(`L. ${theme} ${w}x${h}: стенд выполнен в реальном браузере`, false); console.log('   причина: ' + why); allOk = false; continue; }
    const probs = browserProblems(out);
    check(`L. ${theme} ${w}x${h}: страница без ошибок JS/консоли/Vue`, probs.length === 0);
    if (probs.length) { console.log('   ' + probs.join('\n   ')); allOk = false; }
    const r = out.res;
    ran++;
    const ok = r.rows === 8 && r.secs === 3 && r.units >= 4
      && r.colDiff <= 2 && r.overflowX <= 0
      && r.stickyGap <= 1.5 && r.amsOk && r.secHeadOk
      && r.ht1 === 'A1' && r.has513 === false;
    check(`L. ${theme} ${w}x${h}: 8 строк / 3 секции / unit-группы в своих колонках (без наложений), колонки шапки совпадают (Δ${r.colDiff}px), overflowX=${r.overflowX}, sticky-просвет ${r.stickyGap}px, «513» нет — скриншот ${shot}`, ok);
    if (!ok) allOk = false;
  }
  check('L. все 4 сценария (dark/light × 1366x768 / 1750x880) реально исполнены в браузере', ran === CASES.length);
  if (allOk) console.log('   скриншоты: ' + shotsDir);
}

console.log('\n' + (fail ? ('FAIL: ' + fail + ' проверок провалено') : 'PASS: секции «В работе» — классификация/счётчики/Klipper-иконка по type/локальные номера при глобальном bind/тумблер/sticky живы (реальный Edge через CDP, 0 пропусков)'));
process.exit(fail ? 1 : 0);
